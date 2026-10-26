"""D4 任务 D 的命令入口：先小规模验证，再构建三篇本地向量索引。"""

import argparse
from datetime import datetime, timezone
from functools import partial
from importlib.metadata import version
import json
from pathlib import Path
from time import perf_counter

import httpx

from paper_assistant.chunk_snapshot import load_chunk_version
from paper_assistant.config import ConfigError, load_embedding_settings
from paper_assistant.embedding_client import embed_texts
from paper_assistant.indexing import EmbeddingCache, IndexBuilder, IndexingError, atomic_json, make_index_profile, save_index_profile
from paper_assistant.retrieval import QdrantStore, VectorStoreError
from paper_assistant.storage import PaperStore, StorageError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_ROOT = PROJECT_ROOT / "data/index"


def selected_versions(store: PaperStore, paper_id: str | None, revision: str | None) -> list[tuple[str, str]]:
    """报告只定位当前版本，事实须与不可变快照和 SQLite 全字段核对。

    不从某篇的版本列表猜“最新”，也不把不同论文的版本做笛卡尔组合。
    正式数据库不存在时直接失败，请先执行任务 C，不创建空事实库凑流程。
    """
    corpus = json.loads((PROJECT_ROOT / "eval/corpus.json").read_text(encoding="utf-8-sig"))
    selected = [paper for paper in corpus if paper_id is None or paper["paper_id"] == paper_id]
    if not selected:
        raise ValueError("语料清单中没有指定论文")
    pairs = []
    for paper in selected:
        if revision:
            chosen = revision
        else:
            pointer = json.loads((PROJECT_ROOT / "artifacts/d4/chunk_reports" / (paper["paper_id"] + ".json")).read_text(encoding="utf-8"))
            if pointer["status"] != "success" or pointer["paper_id"] != paper["paper_id"]:
                raise ValueError("分块报告未通过，不能定位正式入库版本")
            chosen = pointer["parse_revision"]
        bundle = load_chunk_version(PROJECT_ROOT, paper["paper_id"], chosen)
        if bundle.paper != paper:
            raise ValueError("版本快照与当前论文清单不同")
        stored = store.get_version_chunks(paper["paper_id"], chosen)
        by_id = {chunk["chunk_id"]: chunk for chunk in stored}
        if len(stored) != len(bundle.chunks) or set(by_id) != {c["chunk_id"] for c in bundle.chunks}:
            raise ValueError("SQLite 与分块快照的完整 chunk 集合不同")
        for chunk in bundle.chunks:
            if any(by_id[chunk["chunk_id"]].get(key) != value for key, value in chunk.items()):
                raise ValueError("SQLite 与不可变快照的 chunk 正文或来源不同")
        pairs.append((paper["paper_id"], chosen))
    return pairs


def main() -> int:
    """解析命令参数、协调模块并写报告；它是正式入口，不只是一个检查。"""
    parser = argparse.ArgumentParser(description="分批生成文档向量并持久化到 Qdrant，已有向量可复用")
    parser.add_argument("--paper-id", help="只构建一篇；省略时处理三篇清单")
    parser.add_argument("--parse-revision", help="明确旧版本，必须同时指定 paper-id")
    parser.add_argument("--batch-size", type=int, default=10, help="每批1–10条，默认10")
    parser.add_argument("--dry-run", action="store_true", help="只读核对来源与配置，不请求服务、不写索引")
    parser.add_argument("--smoke-only", action="store_true", help="仅10条独立collection试验和缓存，不设正式ready")
    args = parser.parse_args()
    if args.parse_revision and not args.paper_id:
        parser.error("parse-revision 必须配合 paper-id 使用")
    if not 1 <= args.batch_size <= 10:
        parser.error("batch-size 必须是1–10")
    if args.dry_run and args.smoke_only:
        parser.error("dry-run 与 smoke-only 不能同时使用")
    start = perf_counter()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    report_path = PROJECT_ROOT / "artifacts/d4/import_report.json"
    history_path = PROJECT_ROOT / "archive/run_logs/d4" / ("vector_import_" + stamp + ".json")
    report = {
        "task": "D4-D-vector-index", "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pending", "mode": "dry_run" if args.dry_run else "smoke_only" if args.smoke_only else "formal",
        "database_path": str(INDEX_ROOT / "papers.sqlite3"), "qdrant_path": str(INDEX_ROOT / "qdrant"),
        "qdrant_client_version": version("qdrant-client"), "batch_size": args.batch_size,
        "papers": [], "requests": [], "request_statistics": {"embedding_requests": 0},
    }
    builder = None
    cache = None
    index_started = None

    def persist() -> None:
        if args.dry_run:
            return
        if builder:
            report["requests"] = builder.requests
            report["request_statistics"] = builder.request_stats()
        if cache:
            report["cache_statistics"] = cache.stats()
        now = perf_counter()
        report["elapsed_seconds"] = round(now - start, 6)
        report["stage_timings_seconds"] = {
            "preparation": round((index_started if index_started is not None else now) - start, 6),
            "index": round(now - index_started, 6) if index_started is not None else 0.0,
        }
        atomic_json(report_path, report)
        atomic_json(history_path, report)

    def progress(event: dict) -> None:
        stage = event["stage"]
        if stage in ("paper_ready", "paper_failed"):
            entry = dict(event["paper"])
            report["papers"] = [p for p in report["papers"] if (p["paper_id"], p["parse_revision"]) != (entry["paper_id"], entry["parse_revision"])]
            report["papers"].append(entry)
            print(f"[{'OK' if stage == 'paper_ready' else 'FAIL'}] {entry['paper_id']}：{entry['completed_count']}/{entry['expected_count']}，{entry['status']}", flush=True)
        elif stage == "batch_upserted":
            report["current_progress"] = event
            # 每50个报告一次；每批的请求与状态仍在磁盘日志更新。
            if event["completed_count"] % 50 == 0 or event["completed_count"] == event["expected_count"]:
                print(f"[进度] {event['paper_id']}：{event['completed_count']}/{event['expected_count']}", flush=True)
        persist()

    try:
        settings = load_embedding_settings()
        profile = make_index_profile(settings)
        report["index_profile"] = profile
        # 预检用只读连接，失败不会产生新的SQLite事实库或正式导入状态。
        with PaperStore(INDEX_ROOT / "papers.sqlite3", read_only=True) as store:
            pairs = selected_versions(store, args.paper_id, args.parse_revision)
            report["selected_versions"] = [{"paper_id": p, "parse_revision": r, "chunk_count": len(store.get_version_chunks(p, r))} for p, r in pairs]
            report["counts_before"] = store.counts()
            sample = store.get_version_chunks(*pairs[0])[:10]
        if args.dry_run:
            report["status"] = "dry_run_passed"
            report["stage_timings_seconds"] = {"preparation": round(perf_counter() - start, 6), "index": 0.0}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if not settings.api_key:
            raise ValueError("缺少向量模型 API 密钥")
        save_index_profile(INDEX_ROOT, profile)
        # 先打开唯一Qdrant客户端取得目录锁，再读取或更新缓存与状态。
        index_started = perf_counter()
        with QdrantStore(INDEX_ROOT / "qdrant", profile["collection_name"], profile["index_profile_id"], settings.dimension) as vectors, \
                httpx.Client(timeout=30.0, follow_redirects=False) as shared_client:
            cache = EmbeddingCache(INDEX_ROOT / "embeddings", profile)
            with PaperStore(INDEX_ROOT / "papers.sqlite3") as store:
                builder = IndexBuilder(store, vectors, cache, settings, profile,
                                       embedder=partial(embed_texts, http_client=shared_client), on_progress=progress)
                persist()
                unfinished = [pair for pair in pairs if (store.get_index_import(*pair, profile["index_profile_id"]) or {}).get("status") != "ready"]
                if args.smoke_only or unfinished:
                    # 正式重复运行全ready版本时跳过试验，避免缓存意外丢失后
                    # 先偷偷再付费10条、最后才发现完整缓存缺失。
                    if unfinished and not args.smoke_only:
                        sample = store.get_version_chunks(*unfinished[0])[:10]
                    report["smoke"] = builder.smoke(sample, args.batch_size)
                    print(f"[OK] 小规模验证：{len(sample)}条，临时collection已删除，正式ready未提前设置", flush=True)
                else:
                    report["smoke"] = {"status": "skipped", "reason": "selected_versions_already_ready"}
                persist()
                if args.smoke_only:
                    report["status"] = "smoke_passed"
                else:
                    for paper, revision in pairs:
                        builder.import_version(paper, revision, args.batch_size)
                    report["status"] = "success"
                    atomic_json(INDEX_ROOT / "current_profile.json", profile)
                report["counts_after"] = store.counts()
                report["index_imports"] = store.list_index_imports(index_profile_id=profile["index_profile_id"])
                report["collection_count"] = vectors.collection_count()
    except KeyboardInterrupt:
        report.update(status="interrupted", error="用户中断；未完成版本不能进入ready，重跑可复用缓存")
        print("[中断] 已完成的缓存与点保留；重跑同一命令继续。", flush=True)
    except Exception as error:
        # 已知EmbeddingAPIError信息由现有客户端脱敏；未知异常只报类型。
        from paper_assistant.embedding_client import EmbeddingAPIError
        safe_types = (EmbeddingAPIError, ConfigError, IndexingError, VectorStoreError, StorageError)
        safe = str(error) if isinstance(error, safe_types) else type(error).__name__
        report.update(status="failed", error=safe)
        print(f"[FAIL] 构建没有完成：{safe}", flush=True)
    finally:
        if not args.dry_run:
            report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            persist()
            print(f"报告：{report_path}", flush=True)
    if report["status"] in ("success", "smoke_passed"):
        stats = report["request_statistics"]
        print(f"本次向量请求 {stats['embedding_requests']} 次，已知实际用量 {stats['known_total_tokens']} tokens。", flush=True)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
