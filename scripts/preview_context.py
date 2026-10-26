"""D5 C：离线回放 D4 的三组正式候选，展示实际消息与字符预算选择。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from paper_assistant.context import PROMPT_VERSION, build_messages, prepare_context
from paper_assistant.indexing import atomic_json


ROOT = Path(__file__).resolve().parents[1]


def main():
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S_%f")
    sources = ["paper_assistant/context.py", "paper_assistant/schemas.py", "scripts/preview_context.py"]
    report = {"task": "D5-C-offline-context-replay", "run_id": stamp, "created_at_utc": now.isoformat(),
              "status": "success", "prompt_version": PROMPT_VERSION, "scope": "D4 recorded candidate replay only",
              "network_requests": 0, "llm_requests": 0, "embedding_requests": 0, "env_loaded": False,
              "is_answer_accuracy": False, "cases": [], "history_report": f"archive/run_logs/d5/context_preview_{stamp}.json",
              "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}}
    records = json.loads((ROOT / "artifacts/d4/retrieval_validation.json").read_text(encoding="utf-8"))
    # Only the recorded query envelope enters context; expected annotations are
    # never supplied to the prompt or used to add passages.
    for case in records["cases"]:
        source = case["result_history"]
        search = json.loads((ROOT / source).read_text(encoding="utf-8"))
        context = prepare_context(search)
        row = {"case_id": case["case_id"], "recorded_search": source,
               "recorded_search_sha256": hashlib.sha256((ROOT / source).read_bytes()).hexdigest(),
               "context": context, "messages": build_messages(context["question"], context)}
        if case["case_id"] == "D2-001":
            ordered = sorted(search["results"], key=lambda item: item["rank"])
            smaller = min(8000, len(ordered[0]["text"]) + len(ordered[1]["text"]) - 1)
            small_context = prepare_context(search, max_chars=smaller)
            row["smaller_budget_demonstration"] = {"context": small_context,
                          "messages": build_messages(small_context["question"], small_context)}
        report["cases"].append(row)
    report["source_unchanged_during_run"] = all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h
                                              for p, h in report["source_sha256"].items())
    assert report["source_unchanged_during_run"]
    atomic_json(ROOT / report["history_report"], report)
    atomic_json(ROOT / "artifacts/d5/context_preview.json", report)
    lines = ["# D5 C：三组候选离线回放", "", "没有执行新检索或聊天请求；旧检索的 token 用量不计入本次。", "",
             "| 题目 | 展示片段 | 正文字符数 | 省略片段 |", "|---|---:|---:|---:|"]
    for row in report["cases"]:
        c = row["context"]
        lines.append(f"| {row['case_id']} | {len(c['shown_evidence'])} | {c['shown_chars']} | {len(c['omitted_evidence'])} |")
        if "smaller_budget_demonstration" in row:
            smaller = row["smaller_budget_demonstration"]["context"]
            lines.append(f"| {row['case_id']} 较小预算 {smaller['max_chars']} | {len(smaller['shown_evidence'])} | {smaller['shown_chars']} | {len(smaller['omitted_evidence'])} |")
    lines += ["", "实际原文、区间、SHA、允许引用 ID 和完整消息见 [context_preview.json](/D:/course/paper-research-assistant/artifacts/d5/context_preview.json)。",
              "正文按 Python 字符计数，不代表 token；消息中的字段和 JSON 编码不计入正文预算。", "",
              f"历史记录：`{report['history_report']}`。", ""]
    (ROOT / "artifacts/d5/context_preview.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "cases": len(report["cases"]), "network_requests": 0,
                      "report": "artifacts/d5/context_preview.json"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
