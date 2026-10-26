"""D4 任务 C：将指定或三篇当前分块版本写入 SQLite。"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from paper_assistant.chunk_snapshot import load_chunk_version
from paper_assistant.chunking import SAFE_ID, pretty_json_bytes
from paper_assistant.storage import PaperStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data/index/papers.sqlite3"


def main() -> int:
    """先核对输入，再逐篇事务入库；一篇失败不会伪装成全库成功。"""
    parser = argparse.ArgumentParser(description="保存分块事实到 SQLite，不生成向量")
    parser.add_argument("--paper-id", help="仅存指定论文；省略时存清单全部论文")
    parser.add_argument("--parse-revision", help="指定已保存处理版本，必须同时指定 paper-id")
    args = parser.parse_args()
    if args.parse_revision and not args.paper_id:
        parser.error("parse-revision 必须配合 paper-id 使用")
    report = {
        "task": "D4-C-sqlite-storage", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "failed", "database_path": str(DATABASE_PATH), "papers": [],
        "embedding_requests": 0, "network_requests": 0, "vector_index_status": "not_started",
    }
    try:
        corpus = json.loads((PROJECT_ROOT / "eval/corpus.json").read_text(encoding="utf-8-sig"))
        if not isinstance(corpus, list) or not corpus or any(not isinstance(paper, dict) for paper in corpus):
            raise ValueError("corpus.json 必须是非空论文对象数组")
        ids = [paper["paper_id"] for paper in corpus]
        if any(not isinstance(paper_id, str) or not SAFE_ID.fullmatch(paper_id) for paper_id in ids):
            raise ValueError("清单中的论文 ID 必须是安全的非空标识符")
        if len(ids) != len(set(ids)):
            raise ValueError("清单论文 ID 重复")
        selected = [paper for paper in corpus if not args.paper_id or paper["paper_id"] == args.paper_id]
        if not selected:
            raise ValueError("清单没有指定论文")
        # 先在内存验证快照。报告中的版本号只用于定位，事实来自快照本身。
        bundles = []
        for paper in selected:
            if args.parse_revision:
                revision = args.parse_revision
            else:
                pointer = PROJECT_ROOT / "artifacts/d4/chunk_reports" / f"{paper['paper_id']}.json"
                current = json.loads(pointer.read_text(encoding="utf-8-sig"))
                if current["status"] != "success" or current["paper_id"] != paper["paper_id"]:
                    raise ValueError("当前分块报告没有通过，不能作为入库入口")
                revision = current["parse_revision"]
            bundle = load_chunk_version(PROJECT_ROOT, paper["paper_id"], revision)
            if bundle.paper != paper:
                raise ValueError("分块快照中的论文元数据与当前清单不同")
            bundles.append(bundle)

        with PaperStore(DATABASE_PATH) as store:
            report["counts_before"] = store.counts()
            for bundle in bundles:
                entry = {"paper_id": bundle.paper["paper_id"], "parse_revision": bundle.manifest["parse_revision"], "status": "failed"}
                try:
                    result = store.import_version(bundle)
                    entry.update(result, status="stored", snapshot_path=bundle.snapshot_path)
                    print(
                        f"[OK] {result['paper_id']}：{result['chunk_count']} 个 chunk，"
                        f"{'复用已有记录' if result['reused'] else '新增入库'}"
                    )
                except (ValueError, sqlite3.Error) as error:
                    entry["error"] = str(error)
                    print(f"[FAIL] {entry['paper_id']}：{error}")
                report["papers"].append(entry)
            report["counts_after"] = store.counts()
            report["versions"] = store.list_versions()
            report["status"] = "success" if all(entry["status"] == "stored" for entry in report["papers"]) else "partial_failure"
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        report["error"] = str(error)
        print(f"[FAIL] {error}")

    output = PROJECT_ROOT / "artifacts/d4/storage_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pretty_json_bytes(report))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    history = PROJECT_ROOT / "archive/run_logs/d4" / f"sqlite_import_{stamp}.json"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_bytes(pretty_json_bytes(report))
    print(f"数据库：{DATABASE_PATH}")
    print(f"报告：{output}")
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
