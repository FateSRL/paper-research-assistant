"""D5 F：只在运行之后计算机器指标，不把题目标注送给问答模型。"""

from collections import Counter
from copy import deepcopy
from datetime import datetime
import math


MACHINE_RUBRIC = {
    "version": "d5-machine-rubric-v1",
    "frozen_before_results": True,
    "exact_target_hit": "Each expected quote must occur contiguously inside one candidate/shown chunk on the annotated paper, fixed PDF SHA and PDF file page, within a selected complete paper/revision pair; shown PDF identity is joined from the returned candidate by chunk_id and matching identity. Normalize whitespace only, retain wording/case/ligatures. Report each quote and all-target case hit. A miss is not proof of missing semantic evidence.",
    "program_completion": "answered on answerable cases is program completion only, never QA accuracy. insufficient_evidence on answerable cases is an uncompleted answer/refusal, not a correct negative.",
    "negative_refusal": "insufficient_evidence on answerable=false is program refusal only. Correct refusal requires independent semantic review.",
    "citation_location": "Count output citation occurrences, including repeats. A corresponding final valid claim_index/citation_index/chunk_id check is a legal location; zero output citations has no defined ratio.",
    "intercepts": "Count failed citation occurrence checks across all original and repair validations; separately count generation/repair parse failures. Do not count these as answered quality.",
    "semantic_review": "expected-point completeness, claim support, source scope and correct refusal require separate AI/human review; all machine scores leave these not_reviewed/human pending.",
    "cost": "Missing usage/request counts remain null; report known sums and missing-record counts, never impute zero. Use recorded start/finish for observed wall-clock duration.",
}


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "ratio": numerator / denominator if denominator else None}


def _text(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def score_case(case: dict, report: dict | None) -> dict:
    """Pure post-hoc scoring; the original case and CLI report are never mutated."""
    report = report if isinstance(report, dict) else {}
    result = report.get("result") or {}
    context = result.get("context") or {}
    search = result.get("search") or {}
    returned = search.get("results") or []
    shown = context.get("shown_evidence") or []
    pairs = {(p.get("paper_id"), p.get("parse_revision")) for p in report.get("selected_versions") or []}
    candidates = {item.get("chunk_id"): item for item in returned}
    targets = []
    for index, expected in enumerate(case.get("expected_evidence") or []):
        quote = _text(expected.get("quote"))
        def hits(items, text_key):
            found = []
            for item in items:
                metadata = item if text_key == "text" else candidates.get(item.get("chunk_id"), {})
                identity = ("paper_id", "parse_revision", "pdf_page")
                if (quote and item.get("paper_id") == expected.get("paper_id")
                        and item.get("pdf_page") == expected.get("pdf_page")
                        and (item.get("paper_id"), item.get("parse_revision")) in pairs
                        and expected.get("pdf_sha256") and metadata.get("pdf_sha256") == expected["pdf_sha256"]
                        and all(item.get(k) == metadata.get(k) for k in identity)
                        and quote in _text(item.get(text_key))):
                    found.append(item.get("chunk_id"))
            return found
        returned_ids = hits(returned, "text")
        shown_ids = hits(shown, "shown_text")
        targets.append({"target_index": index, "paper_id": expected.get("paper_id"),
                        "pdf_page": expected.get("pdf_page"),
                        "exact_target_hit_returned": bool(returned_ids),
                        "exact_target_hit_shown": bool(shown_ids),
                        "returned_chunk_ids": returned_ids, "shown_chunk_ids": shown_ids})
    status = report.get("status", "runner_failure")
    claims = (report.get("answer") or {}).get("claims") or []
    validations = result.get("citation_checks") or []
    final_checks = validations[-1].get("checks", []) if validations else []
    legal = {(c.get("claim_index"), c.get("citation_index"), c.get("chunk_id"))
             for c in final_checks if c.get("status") == "valid"}
    citation_total = citation_valid = 0
    for claim_index, claim in enumerate(claims):
        for citation_index, chunk_id in enumerate(claim.get("citation_ids") or []):
            citation_total += 1
            citation_valid += (claim_index, citation_index, chunk_id) in legal
    citation_intercepts = sum(c.get("status") != "valid"
                              for validation in validations for c in validation.get("checks", []))
    generation = result.get("generation") or {}
    parse_intercepts = sum(bool(item.get("parse_error_code")) for item in generation.get("generation_attempts", []))
    parse_intercepts += sum(bool(item.get("parse_error_code")) for item in result.get("citation_repairs", []))
    elapsed = None
    try:
        elapsed = _number((datetime.fromisoformat(report["finished_at_utc"])
                           - datetime.fromisoformat(report["started_at_utc"])).total_seconds())
    except (KeyError, TypeError, ValueError):
        pass
    embedding = report.get("embedding_statistics") or {}
    chat = report.get("chat_statistics") or {}
    answerable = case["answerable"]
    return {"case_id": case["case_id"], "answerable": answerable, "status": status,
            "question_type": case.get("question_type"), "targets": targets,
            "exact_targets_available": bool(answerable and targets),
            "exact_all_targets_hit_returned": all(t["exact_target_hit_returned"] for t in targets) if answerable and targets else None,
            "exact_all_targets_hit_shown": all(t["exact_target_hit_shown"] for t in targets) if answerable and targets else None,
            "program_answered_completion": answerable and status == "answered",
            "answerable_refusal": answerable and status == "insufficient_evidence",
            "program_negative_refusal": not answerable and status == "insufficient_evidence",
            "output_claim_count": len(claims), "citation_location": _ratio(citation_valid, citation_total),
            "raw_citation_intercepts": citation_intercepts, "raw_parse_intercepts": parse_intercepts,
            "semantic_support_status": "not_reviewed", "human_review_status": "pending",
            "qa_accuracy": None, "correct_refusal_semantic": None,
            "requests": {"embedding": _number(report.get("embedding_requests")),
                         "chat_sdk": _number(chat.get("sdk_request_attempts")),
                         "chat_http": _number(report.get("llm_requests")),
                         "network": _number(report.get("network_requests"))},
            "retries_and_repairs": {"network_retries": _number(chat.get("network_retries")),
                                   "repairs": _number(chat.get("repairs"))},
            "tokens": {"embedding": _number(embedding.get("total_tokens")),
                       "chat": _number(chat.get("total_tokens")),
                       "known_chat": _number(chat.get("known_total_tokens"))},
            "elapsed_seconds": elapsed, "failure_stage": report.get("failure_stage")}


def summarize_case_scores(scores: list[dict], planned_cases: list[dict] | None = None) -> dict:
    """Aggregate measured records, keeping planned and attempted denominators separate."""
    scores = deepcopy(scores)
    answerable = [s for s in scores if s["answerable"]]
    negatives = [s for s in scores if not s["answerable"]]
    targets = [s for s in answerable if s["exact_targets_available"]]
    def aggregate(values):
        known = [v for v in values if v is not None]
        return {"total": sum(known) if len(known) == len(values) else None,
                "known_total": sum(known), "missing_records": len(values) - len(known)}
    return {"rubric_version": MACHINE_RUBRIC["version"], "is_qa_accuracy": False,
            "attempted_count": len(scores), "planned_count": len(planned_cases) if planned_cases is not None else None,
            "planned_answerable_count": sum(c["answerable"] for c in planned_cases) if planned_cases is not None else None,
            "status_counts": dict(Counter(s["status"] for s in scores)),
            "exact_all_targets_hit_returned": _ratio(sum(s["exact_all_targets_hit_returned"] for s in targets), len(targets)),
            "exact_all_targets_hit_shown": _ratio(sum(s["exact_all_targets_hit_shown"] for s in targets), len(targets)),
            "exact_quote_hit_returned": _ratio(sum(t["exact_target_hit_returned"] for s in targets for t in s["targets"]), sum(len(s["targets"]) for s in targets)),
            "exact_quote_hit_shown": _ratio(sum(t["exact_target_hit_shown"] for s in targets for t in s["targets"]), sum(len(s["targets"]) for s in targets)),
            "answerable_without_expected_quotes": len(answerable) - len(targets),
            "program_answered_completion": _ratio(sum(s["program_answered_completion"] for s in answerable), len(answerable)),
            "answerable_refusal_count": sum(s["answerable_refusal"] for s in answerable),
            "program_negative_refusal": _ratio(sum(s["program_negative_refusal"] for s in negatives), len(negatives)),
            "citation_location": _ratio(sum(s["citation_location"]["numerator"] for s in scores), sum(s["citation_location"]["denominator"] for s in scores)),
            "raw_citation_intercepts": sum(s["raw_citation_intercepts"] for s in scores),
            "raw_parse_intercepts": sum(s["raw_parse_intercepts"] for s in scores),
            "output_claim_count": sum(s["output_claim_count"] for s in scores),
            "semantic_support_status": "not_reviewed", "human_review_status": "pending", "qa_accuracy": None,
            "requests": {key: aggregate([s["requests"][key] for s in scores]) for key in ("embedding", "chat_sdk", "chat_http", "network")},
            "retries_and_repairs": {key: aggregate([s["retries_and_repairs"][key] for s in scores]) for key in ("network_retries", "repairs")},
            "tokens": {key: aggregate([s["tokens"][key] for s in scores]) for key in ("embedding", "chat", "known_chat")},
            "elapsed_seconds": aggregate([s["elapsed_seconds"] for s in scores])}
