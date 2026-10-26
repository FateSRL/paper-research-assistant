"""D8 F: post-hoc review bundle only; no answering, environment or API access.

All output paths are immutable. It uses saved first outputs and separate AI
reviews, leaving source reports and every human status unchanged.
"""

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from paper_assistant.agent_export import _exclusive_text, _identifier, _path
from paper_assistant.answer_export import code_span, exclusive_json, fenced


ROOT = Path(__file__).resolve().parents[1]
VERSION = "d8-four-case-review-package-v1"
MODES = ("fixed_rag", "agent")
CASES = ("D2-001", "D2-002", "D2-003", "D5-006")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_package(batch_id, *, project_root=ROOT):
    root = Path(project_root).resolve()
    path = _path(root, "artifacts/d8/comparison/" + _identifier(batch_id))
    manifest, summary = _read(path / "manifest.json"), _read(path / "summary.json")
    if tuple(manifest["case_ids"]) != CASES or summary["freeze_sha256"] != manifest["freeze_sha256"]:
        raise ValueError("four_case_binding_mismatch")
    inputs = {"manifest.json": _sha(path / "manifest.json"), "summary.json": _sha(path / "summary.json")}
    records = {case_id: _read(path / (case_id + ".json")) for case_id in CASES}
    inputs.update({case_id + ".json": _sha(path / (case_id + ".json")) for case_id in CASES})
    reviews = []
    for name in ("ai_review_rag_cases.json", "ai_review_react_cases.json"):
        report = _read(path / name)
        if report.get("qa_accuracy") is not None or report.get("paid_judge_requests") != 0:
            raise ValueError("review_scope_mismatch")
        inputs[name] = _sha(path / name)
        reviews.extend(deepcopy(report["case_reviews"]))
    keyed = {(r["case_id"], r["mode"]): r for r in reviews}
    if len(reviews) != 8 or set(keyed) != {(case_id, mode) for case_id in CASES for mode in MODES}:
        raise ValueError("missing_or_duplicate_mode_review")
    for (case_id, mode), review in keyed.items():
        if (review["source_record_sha256"] != inputs[case_id + ".json"]
                or review["program_status"] != records[case_id]["pair"]["modes"][mode]["status"]):
            raise ValueError("review_first_record_mismatch")
    binding = {"batch_id": batch_id, "freeze_sha256": manifest["freeze_sha256"],
               "source_sha256": {"scripts/build_d8_f_review_package.py": _sha(Path(__file__))},
               "input_sha256": inputs}
    ai_summary = {}
    for mode in MODES:
        selected = [keyed[(c["case_id"], mode)] for c in manifest["cases"]]
        answerable = [keyed[(c["case_id"], mode)] for c in manifest["cases"] if c["answerable"]]
        negative = [keyed[(c["case_id"], mode)] for c in manifest["cases"] if not c["answerable"]]
        support = Counter(str(claim["citation_support"]) for r in selected for claim in r["claim_reviews"])
        ai_summary[mode] = {"answerable_task_completed": {"numerator": sum(r["task_completed"] is True for r in answerable),
                                                          "denominator": len(answerable)},
                            "claim_citation_support_counts": dict(support),
                            "negative_reasonable_refusal": {"numerator": sum(r["refusal_reasonable_with_shown"] is True for r in negative),
                                                             "denominator": len(negative)}}
    combined = {"task": "D8-F-AI-review", "version": VERSION, **binding,
                "reviewer": "codex_ai", "review_method": "Independent AI manual review of saved first outputs and actual final cited evidence",
                "paid_judge_requests": 0, "human_review": {"status": "pending", "reviewed_modes": 0, "planned_modes": 8},
                "qa_accuracy": None, "is_human_accuracy": False, "mode_summaries": ai_summary,
                "case_reviews": [keyed[(case_id, mode)] for case_id in CASES for mode in MODES],
                "limitations": "Four development cases only; AI support/completeness differs from exact-quote hits, program status and citation location. No human review or frozen acceptance evaluation."}
    human = {"task": "D8-F-human-review", "version": VERSION, **binding,
             "status": "pending", "reviewer_name": None, "reviewed_at": None,
             "question_labels_are_not_answer_review": True, "qa_accuracy": None,
             "review_items": []}
    snapshots = {"task": "D8-F-first-retrieval-snapshots", **binding,
                 "actual_first_search_count": 4,
                 "records": [{"case_id": case_id, "snapshot": deepcopy(records[case_id]["pair"]["shared_first_retrieval"])} for case_id in CASES]}
    lines = ["# D8 F 人工复核包", "", "状态：pending。四题八份首次输出；题目的人审标记不代表答案已经人审。", "",
             "先独立核对原问题及真实引用原文，再查看独立 AI 初审。PDF 页码均为文件页序。", "",
             "可先审 D2-002 的两方法补查及 D2-003 的摘要限制，再核对另外两题。", "",
             "请在 human_review_template.json 填姓名、时间，每条结论的支持程度、问题是否完整完成和不足是否合理；未复核项保留 pending。", "",
             "合法引用只证明定位；基准名字正确还需符合题目的来源限制。记录中没有发布结论的模式不计零条全部支持。", ""]
    for case in manifest["cases"]:
        case_id = case["case_id"]
        lines += ["## " + case_id, "", "原问题：", "", fenced(case["question"]), "",
                  "中文：", "", fenced(case.get("question_zh") or ""), "",
                  "以下期望要点只供事后复核，没有送给问答模型：", "", fenced(json.dumps(case["expected_points"], ensure_ascii=False, indent=2)), ""]
        for mode in MODES:
            report = records[case_id]["pair"]["modes"][mode]
            answer = report["result"].get("answer") or {}
            item = {"case_id": case_id, "mode": mode, "source_record_sha256": inputs[case_id + ".json"],
                    "run_id": report["run_id"], "program_status": report["status"], "review_status": "pending",
                    "task_completed": None, "source_scope_satisfied": None, "refusal_reasonable": None,
                    "claim_reviews": [{"claim_index": i, "claim": claim["claim"], "citation_ids": claim["citation_ids"],
                                       "citation_support": "pending", "note": ""} for i, claim in enumerate(answer.get("claims", []))],
                    "failure_categories": [], "review_note": ""}
            human["review_items"].append(item)
            lines += ["### " + mode, "", "程序终态：" + code_span(report["status"]) + "；人工：pending。", "",
                      "首次运行：" + code_span(report["run_id"]) + "。", ""]
            for i, claim in enumerate(answer.get("claims", []), 1):
                lines += [f"结论 {i}：", "", fenced(claim["claim"]), "",
                          "实际引用：" + ", ".join(code_span(cid) for cid in claim["citation_ids"]), ""]
            if answer.get("reason"):
                lines += ["资料不足理由：", "", fenced(answer["reason"]), ""]
            if report["status"] not in ("answered", "insufficient_evidence"):
                lines += ["本模式未发布答案；请区分故障与语义不足。", ""]
            for source in answer.get("evidence_sources", []):
                lines += ["来源：" + code_span(source["chunk_id"]) + "；文件页序 " + str(source["pdf_page"]) + "。", "",
                          "[打开 PDF](/" + Path(source["pdf_absolute_path"]).as_posix() + ")。", "",
                          "原文SHA：" + code_span(source["text_sha256"]) + "。", "", fenced(source["text"]), ""]
    ai_md = ["# D8 F 独立 AI 初审汇总", "", "AI 初审；human pending，QA accuracy 未测量。", "",
             "| 题目 | 模式 | 程序状态 | AI 任务完成 | AI 结论 |", "|---|---|---|---|---|"]
    for review in combined["case_reviews"]:
        ai_md.append("| " + " | ".join(str(review[k]).replace("|", "\\|") for k in
                                         ("case_id", "mode", "program_status", "task_completed", "ai_outcome")) + " |")
    ai_md += ["", "逐结论/逐引用和范围理由见 ai_review_rag_cases.md、ai_review_react_cases.md 与完整 ai_semantic_review.json。", "",
              "本批次同时改变候选、选证据和聊天次数，不能把观察归因于查询改写单独有效，不能外推全量准确率。", ""]
    # Check every immutable destination before publishing any package component.
    outputs = {"ai_semantic_review.json": combined, "human_review_template.json": human,
               "first_retrieval_snapshots.json": snapshots}
    texts = {"ai_semantic_review.md": "\n".join(ai_md), "human_review.md": "\n".join(lines)}
    if any((path / name).exists() for name in (*outputs, *texts)):
        raise FileExistsError("review package already exists")
    for name, value in outputs.items():
        exclusive_json(path / name, value)
    for name, text in texts.items():
        _exclusive_text(path / name, text)
    return {"status": "completed", "batch_id": batch_id, "reviewed_AI_modes": 8,
            "human_reviewed_modes": 0, "human_review_status": "pending", "qa_accuracy": None,
            "answerable_AI_observations": ai_summary, "API_requests": 0,
            "outputs": [*outputs, *texts]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_package(args.batch_id)
    except Exception:
        print(json.dumps({"status": "failed", "error": "review_package_input_or_export_error", "API_requests": 0}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
