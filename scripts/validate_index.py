"""离线核对正式磁盘索引，生成任务 D 的持久化验证报告。

不读取 .env，不请求 embedding；向量方向直接与已刷盘的成功响应比较。
用于构建进程退出后，在另一个 Python 进程证明数据仍然完整。
"""

from datetime import datetime, timezone
from contextlib import closing
import json
from pathlib import Path

from qdrant_client import QdrantClient

from paper_assistant.config import EmbeddingSettings
from paper_assistant.indexing import EmbeddingCache, atomic_json, make_index_profile
from paper_assistant.retrieval import QdrantStore
from paper_assistant.storage import PaperStore
from scripts.build_index import selected_versions


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    report = {"task": "D4-D-persistent-index-validation", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "status": "failed", "embedding_requests": 0, "network_requests": 0, "papers": []}
    try:
        root = PROJECT_ROOT / "data/index"
        profile = json.loads((root / "current_profile.json").read_text(encoding="utf-8"))
        recipe = profile["recipe"]
        settings = EmbeddingSettings(backend=recipe["backend"], model=recipe["model"], api_key=None,
                                     base_url=recipe["base_url"], dimension=recipe["dimension"])
        if make_index_profile(settings) != profile:
            raise ValueError("索引配置身份与完整指纹不匹配")
        saved = json.loads((root / "profiles" / (profile["index_profile_id"] + ".json")).read_text(encoding="utf-8"))
        if saved != profile:
            raise ValueError("当前索引配置指针与固定清单不匹配")
        if not (root / "qdrant/meta.json").is_file():
            raise ValueError("Qdrant 正式持久化元数据不存在")
        report["index_profile"] = profile
        cache = EmbeddingCache(root / "embeddings", profile)
        with PaperStore(root / "papers.sqlite3", read_only=True) as store:
            pairs = selected_versions(store, None, None)
            report["counts"] = store.counts()
            integrity = store.connection.execute("PRAGMA integrity_check").fetchall()
            foreign_keys = store.connection.execute("PRAGMA foreign_key_check").fetchall()
            if [row[0] for row in integrity] != ["ok"] or foreign_keys:
                raise ValueError("SQLite 完整性或外键检查未通过")
            report.update(sqlite_integrity="ok", foreign_key_violations=0)
            # 检查器先确认既有collection，不能顺手建一个空collection误当正式库。
            with closing(QdrantClient(path=str(root / "qdrant"))) as client:
                if not client.collection_exists(profile["collection_name"]):
                    raise ValueError("当前配置的正式 collection 不存在")
                with QdrantStore(root / "qdrant", profile["collection_name"], profile["index_profile_id"],
                                 recipe["dimension"], client=client) as vectors:
                    chunks = []
                    for paper, revision in pairs:
                        state = store.get_index_import(paper, revision, profile["index_profile_id"])
                        if state is None or state["status"] != "ready":
                            raise ValueError("选定版本没有完整ready导入")
                        scope = store.get_version_chunks(paper, revision)
                        cached = [cache.load(chunk) for chunk in scope]
                        if any(vector is None for vector in cached):
                            raise ValueError("完整索引缺少向量缓存")
                        verification = vectors.validate(scope, cached)
                        report["papers"].append({"paper_id": paper, "parse_revision": revision,
                                                "state": state, "verification": verification})
                        chunks.extend(scope)
                    report["all_selected_versions"] = vectors.validate(chunks, [cache.load(c) for c in chunks])
                    report["collection_count"] = vectors.collection_count()
                    # 用已缓存文档向量做内部读回探针，无收费的问题向量请求。
                    # 后续E仍须实现 query embedding、ready筛选与SQLite正文回查。
                    hit = client.query_points(collection_name=profile["collection_name"],
                                              query=cache.load(chunks[0]), limit=1, with_payload=True).points
                    if not hit:
                        raise ValueError("持久化collection无法返回内部读回探针")
                    report["restart_query_probe"] = {"status": "success", "query_type": "cached_document_vector",
                                                      "chunk_id": hit[0].payload["chunk_id"], "score": hit[0].score,
                                                      "is_user_question_retrieval_evaluation": False}
                    report["collections"] = [collection.name for collection in client.get_collections().collections]

        report["cache_statistics"] = cache.stats()
        latest_path = PROJECT_ROOT / "artifacts/d4/import_report.json"
        if latest_path.exists():
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
            if latest.get("index_profile") == profile:
                report["latest_import_run"] = {
                    "started_at_utc": latest.get("started_at_utc"), "status": latest["status"],
                    "selected_versions": latest.get("selected_versions"),
                    "request_statistics": latest.get("request_statistics"),
                    "reused_ready_versions": sum(entry.get("reused_ready", False) for entry in latest["papers"]),
                }
        report["status"] = "success"
    except Exception as error:
        report["error_type"] = type(error).__name__
        print(f"[FAIL] 离线完整索引验证失败：{type(error).__name__}")
    target = PROJECT_ROOT / "artifacts/d4/index_validation.json"
    atomic_json(target, report)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    atomic_json(PROJECT_ROOT / "archive/run_logs/d4" / ("index_validation_" + stamp + ".json"), report)
    print(f"[{'OK' if report['status'] == 'success' else 'FAIL'}] 正式索引：{report.get('collection_count', 0)}点，离线请求0次；报告：{target}")
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
