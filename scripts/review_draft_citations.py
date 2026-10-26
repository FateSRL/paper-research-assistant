"""D5 D：离线回查 C 保存的真实草稿与 PDF 来源；不重新检索或生成。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from paper_assistant.citations import validate_citations
from paper_assistant.indexing import atomic_json
from paper_assistant.storage import PaperStore


ROOT = Path(__file__).resolve().parents[1]


def main():
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S_%f")
    source = ROOT / "artifacts/d5/generation_smoke.json"
    previous = json.loads(source.read_text(encoding="utf-8"))
    sources = ["paper_assistant/citations.py", "paper_assistant/context.py", "paper_assistant/schemas.py",
               "paper_assistant/storage.py", "scripts/review_draft_citations.py"]
    before_db = hashlib.sha256((ROOT / "data/index/papers.sqlite3").read_bytes()).hexdigest()
    with PaperStore(ROOT / "data/index/papers.sqlite3", read_only=True) as store:
        validation = validate_citations(previous["generation"]["draft"], previous["context"], store, project_root=ROOT)
    unchanged = before_db == hashlib.sha256((ROOT / "data/index/papers.sqlite3").read_bytes()).hexdigest()
    report = {"task": "D5-D-C-draft-citation-replay", "run_id": stamp, "created_at_utc": now.isoformat(),
              "status": validation["status"], "validation": validation,
              "original_c_run_id": previous["run_id"], "original_c_report": "artifacts/d5/generation_smoke.json",
              "original_c_report_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "question": previous["question"], "draft": previous["generation"]["draft"],
              "network_requests": 0, "embedding_requests": 0, "llm_requests": 0, "env_loaded": False,
              "sqlite_bytes_unchanged": unchanged, "is_new_end_to_end_run": False,
              "semantic_support_status": "not_reviewed", "is_answer_accuracy": False,
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
              "history_report": f"archive/run_logs/d5/citation_replay_{stamp}.json"}
    if not unchanged:
        report["status"] = "failed"
    atomic_json(ROOT / report["history_report"], report)
    atomic_json(ROOT / "artifacts/d5/citation_replay.json", report)
    lines = ["# D5 D：C 草稿的离线引用回查", "", f"状态：`{report['status']}`。", "",
             "本次借用 C 保存的真实草稿与展示证据，只读取 SQLite 和原 PDF；没有新检索或聊天费用。", "",
             f"共 {len(validation['checks'])} 次引用检查，{len(validation['evidence_refs'])} 个去重来源。", "",
             "| chunk ID | PDF 文件页序 | 论文 |", "|---|---:|---|"]
    for ref in validation["evidence_refs"]:
        lines.append(f"| `{ref['chunk_id']}` | {ref['pdf_page']} | {ref['paper_id']} |")
    lines += ["", "原文、完整来源与检查明细见 [citation_replay.json](/D:/course/paper-research-assistant/artifacts/d5/citation_replay.json)。",
              "这是身份与定位检查，语义支持尚未评分。", "", f"历史记录：`{report['history_report']}`。", ""]
    (ROOT / "artifacts/d5/citation_replay.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": len(validation["checks"]),
                      "sources": len(validation["evidence_refs"]), "network_requests": 0,
                      "report": "artifacts/d5/citation_replay.json"}, ensure_ascii=False))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
