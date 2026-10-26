"""D4 任务 E：输入问题，检索明确论文/处理版本的候选原文。

例如：python -X utf8 -m scripts.search_evidence --list-ready
真正查询每次调用一次问题 embedding，不调用回答生成模型。
"""

import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from qdrant_client import QdrantClient

from paper_assistant.config import ConfigError, EmbeddingSettings, load_embedding_settings, load_rerank_settings
from paper_assistant.embedding_client import EmbeddingAPIError
from paper_assistant.hybrid_search import HybridEvidenceSearcher
from paper_assistant.rerank_client import RerankClient
from paper_assistant.indexing import IndexingError, atomic_json, make_index_profile
from paper_assistant.retrieval import QdrantStore, VectorStoreError
from paper_assistant.search import EvidenceSearcher, SearchError
from paper_assistant.storage import PaperStore, StorageError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_ROOT = PROJECT_ROOT / "data/index"


def load_current_profile() -> dict:
    """只读取已完成建库的配置；先核对指纹，才用 ID 定位固定清单。

    列出 ready 版本时不需要 .env；用配置清单中的公开字段重新计算身份。
    查询时还会拿本机实际 embedding 设置与这份清单比较，不能换模型硬查。
    """
    try:
        profile = json.loads((INDEX_ROOT / "current_profile.json").read_text(encoding="utf-8"))
        recipe = profile["recipe"]
        public = EmbeddingSettings(backend=recipe["backend"], model=recipe["model"], api_key=None,
                                   base_url=recipe["base_url"], dimension=recipe["dimension"])
        if make_index_profile(public) != profile:
            raise IndexingError("当前索引配置指纹不一致，请核对任务D的固定清单")
        saved = json.loads((INDEX_ROOT / "profiles" / (profile["index_profile_id"] + ".json")).read_text(encoding="utf-8"))
        if saved != profile:
            raise IndexingError("当前配置指针与固定索引清单不一致")
        return profile
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise IndexingError("不能读取完整的当前索引配置，请先完成任务D") from error


def fenced(text: str) -> str:
    """原文放代码块中保留换行，选择足够长的围栏避免正文意外结束代码块。"""
    longest = max((len(match.group()) for match in re.finditer(r"`+", text)), default=0)
    marker = "`" * max(3, longest + 1)
    return marker + "text\n" + text + "\n" + marker


def render_result(report: dict) -> str:
    """保存可读副本，完整原文仍以结果 JSON 和 SQLite 事实库为准。"""
    lines = ["# 最近一次证据检索", "", f"状态：`{report['status']}`；这份结果是候选原文，尚未生成答案。", "",
             "问题：", "", fenced(report.get("query", "")), ""]
    if report.get("error"):
        lines += ["错误：" + report["error"], ""]
    lines += ["所选版本：", ""]
    for pair in report.get("selected_versions", []):
        lines.append(f"- `{pair['paper_id']}` / `{pair['parse_revision']}`")
    lines += ["", f"实际候选数量：{report.get('returned_count', 0)}；top-k：{report.get('top_k', 5)}。", ""]
    score_label = "RRF 排序分数" if report.get("score_kind") == "rrf" else "向量相似度"
    for hit in report.get("results", []):
        lines += [f"## 候选 {hit['rank']}，{score_label} {hit['score']:.6f}", "", hit["title"], "",
                  f"论文：`{hit['paper_id']}`；处理版本：`{hit['parse_revision']}`；PDF 文件页序：**{hit['pdf_page']}**。", "",
                  f"chunk ID：`{hit['chunk_id']}`", "", f"文本 SHA-256：`{hit['text_sha256']}`", "", fenced(hit["text"]), ""]
        source = (PROJECT_ROOT / hit["local_path"]).resolve()
        if source.is_relative_to(PROJECT_ROOT):
            lines += [f"[打开原 PDF](/{source.as_posix()})；按文件页序 {hit['pdf_page']} 对照。", ""]
    stats = report.get("statistics", {})
    rerank = report.get("rerank_statistics") or {}
    lines += [f"最终排序方式：{report.get('ranking_method', 'cosine')}；重排请求：{rerank.get('requests', 0)}；重排耗时：{rerank.get('elapsed_seconds', 0):.3f} 秒。", ""]
    lines += [f"本次问题向量请求：{stats.get('embedding_requests', 0)}；实际 tokens：{stats.get('total_tokens', '缺失')}；LLM 请求：0。", "",
              "没有候选只表示本次检索返回空集合；排序分数不能代替原文支持度判断。", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """正式查询入口：参数、已有库、核心检索、完整原文展示和运行记录。"""
    parser = argparse.ArgumentParser(description="在指定ready论文版本中检索候选原文，不生成模型答案")
    parser.add_argument("--list-ready", action="store_true", help="离线列出当前配置下可检索的明确论文/版本")
    parser.add_argument("--paper-id", help="单篇论文ID，必须同时给parse-revision")
    parser.add_argument("--parse-revision", help="单篇明确处理版本，必须同时给paper-id")
    parser.add_argument("--version", action="append", nargs=2, metavar=("PAPER_ID", "PARSE_REVISION"), help="多篇明确配对，可重复使用")
    parser.add_argument("--query", help="问题原文；每次查询向量化一次")
    parser.add_argument("--top-k", type=int, default=5, help="最多返回1–20个候选，默认5")
    parser.add_argument("--json", action="store_true", help="标准输出只打印结构化JSON")
    args = parser.parse_args(argv)
    if bool(args.paper_id) != bool(args.parse_revision):
        parser.error("paper-id 与 parse-revision 必须一起明确提供")
    if args.version and args.paper_id:
        parser.error("多篇version配对与单篇paper-id/parse-revision不能混用")
    if args.list_ready:
        if args.query is not None or args.version or args.paper_id:
            parser.error("list-ready 仅列版本，不同时执行查询")
    elif args.query is None or not (args.version or args.paper_id):
        parser.error("查询必须提供query，并明确指定单篇论文/版本或一个以上version配对")
    if not 1 <= args.top_k <= 20:
        parser.error("top-k 必须是1–20")
    pairs = args.version or ([(args.paper_id, args.parse_revision)] if args.paper_id else [])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    report = {"task": "D4-E-evidence-retrieval", "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "status": "failed", "query": args.query, "top_k": args.top_k,
              "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in pairs],
              "results": [], "returned_count": 0, "statistics": {"embedding_requests": 0}, "llm_requests": 0}
    try:
        profile = load_current_profile()
        report["index_profile"] = profile
        with PaperStore(INDEX_ROOT / "papers.sqlite3", read_only=True) as store:
            if args.list_ready:
                ready = store.list_index_imports(status="ready", index_profile_id=profile["index_profile_id"])
                listing = {"status": "success", "index_profile": profile, "ready_versions": ready, "embedding_requests": 0, "llm_requests": 0}
                if args.json:
                    print(json.dumps(listing, ensure_ascii=False, indent=2, allow_nan=False))
                else:
                    print(f"当前配置：{profile['index_profile_id']}，{profile['recipe']['model']} / {profile['recipe']['dimension']}维")
                    for row in ready:
                        print(f"{row['paper_id']}  {row['parse_revision']}  {row['completed_count']}个chunk  ready")
                    print(f"共{len(ready)}个版本；此命令未调用模型。")
                return 0
            settings = load_embedding_settings()
            if make_index_profile(settings) != profile:
                raise IndexingError("本机向量配置与正式索引不同，不能混用；请恢复配置或构建新索引")
            if not (INDEX_ROOT / "qdrant/meta.json").is_file():
                raise VectorStoreError("Qdrant 持久化索引不存在，请先完成任务D")
            # QdrantClient本身不支持with，用closing保证错误路径也释放目录锁。
            # 先检查正式collection存在，查询不能悄悄新建一个空库。
            with closing(QdrantClient(path=str(INDEX_ROOT / "qdrant"))) as client:
                if not client.collection_exists(profile["collection_name"]):
                    raise VectorStoreError("当前配置的正式collection不存在")
                with QdrantStore(INDEX_ROOT / "qdrant", profile["collection_name"], profile["index_profile_id"],
                                 profile["recipe"]["dimension"], client=client) as vectors:
                    with ExitStack() as resources:
                        rerank_settings = load_rerank_settings()
                        reranker = resources.enter_context(RerankClient(rerank_settings)) if rerank_settings else None
                        searcher = HybridEvidenceSearcher(EvidenceSearcher(store, vectors, settings, profile), store, reranker)
                        report.update(searcher.search_evidence(args.query, pairs, args.top_k))
    except SearchError as error:
        report.update(error=str(error), error_stage=error.stage, statistics=error.statistics)
        report["rerank_statistics"] = getattr(error, "rerank_statistics", None)
    except Exception as error:
        safe_types = (ConfigError, EmbeddingAPIError, IndexingError, VectorStoreError, StorageError)
        safe = str(error) if isinstance(error, safe_types) else type(error).__name__
        report.update(error=safe, error_type=type(error).__name__)
    if args.list_ready:
        # 列表失败也不写查询产物；stdout/stderr仍明确给出失败和非零退出码。
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else "[FAIL] " + report["error"])
        return 1
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    target = PROJECT_ROOT / "artifacts/d4/retrieval_result.json"
    atomic_json(target, report)
    atomic_json(PROJECT_ROOT / "archive/run_logs/d4" / ("retrieval_" + stamp + ".json"), report)
    (target.with_suffix(".md")).write_text(render_result(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    elif report["status"] in ("success", "no_hits"):
        print(f"[OK] 返回 {report['returned_count']} 个候选；这些是原文证据候选，尚未生成答案。")
        score_label = "rrf_score" if report.get("score_kind") == "rrf" else "cosine_score"
        for hit in report["results"]:
            print(f"\n[{hit['rank']}] {score_label}={hit['score']:.6f}  {hit['paper_id']}  PDF文件页序={hit['pdf_page']}")
            print(f"parse_revision={hit['parse_revision']}\nchunk_id={hit['chunk_id']}\n{hit['text']}")
        stats = report["statistics"]
        print(f"\n问题向量请求 {stats['embedding_requests']} 次；实际 tokens：{stats.get('total_tokens')}；LLM请求0次。")
        print(f"结果：{target}\n可读预览：{target.with_suffix('.md')}")
    else:
        print("[FAIL] " + report["error"], file=sys.stderr)
        print(f"失败记录：{target}", file=sys.stderr)
    return 0 if report["status"] in ("success", "no_hits") else 1


if __name__ == "__main__":
    raise SystemExit(main())
