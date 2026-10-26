"""D8 E: pure post-hoc scoring of recorded multi-round Agent evidence.

Annotations never enter an answering call. Exact quotes are retrieval proxies,
not semantic support or QA accuracy. No environment, file, store or API access.
"""

from copy import deepcopy
from collections import Counter
import hashlib
import json

from paper_assistant.evaluation import _number, _ratio, score_case, summarize_case_scores


STAGE_NAMES = ("initial_returned", "initial_shown", "retry_returned", "retry_shown",
               "merged_returned", "final_shown")
MACHINE_RUBRIC = {
    "version": "d8-agent-machine-rubric-v1",
    "annotation_isolation": "Only saved outputs are scored; expected answers, labels and quotes must never enter model/tool inputs.",
    "exact_target_hit": "Normalize whitespace only. Require annotated paper, fixed PDF SHA and PDF file page, a selected complete paper/parse pair, and a contiguous quote within one complete chunk. Case and wording remain exact.",
    "shown_identity": "Join shown chunks to genuine candidates from their recorded round, or both genuine rounds for final evidence. Require identical full source identity, exact full text, original/shown SHA and complete character range. A conflicting same ID in the two rounds cannot establish final provenance.",
    "stages": "Keep first-round returned/selected, retry returned/standalone-selected, all merged candidates and final selected evidence separate. Retry standalone selection is a diagnostic snapshot, not a separately sent model context.",
    "stage_denominators": "First/final stages apply to every attempted answerable case with targets. Retry/merge stages apply only when a retry round was attempted. Applicable missing/failed stages count as misses; unattempted stages have null hit scores. Availability is reported separately, never used to remove failures.",
    "program_completion": "answered means program completion only; an answerable refusal is unfinished. Negative refusal still needs semantic review.",
    "citation_location": "Count final published citation occurrences, including duplicates, and final matching valid occurrence checks. Zero published citations is N/A. Earlier failed occurrence checks and action parse intercepts are separate.",
    "semantic_review": "All machine scores remain not_reviewed/human pending with QA accuracy and semantic refusal null.",
    "cost": "Preserve actual recorded counts and usage, including failures. Missing values stay null; report known sums and missing records. Do not estimate prices.",
}
_IDENTITY = ("chunk_id", "paper_id", "parse_revision", "pdf_page", "pdf_sha256", "text_sha256", "text")


def _dict(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _candidate_map(rows, pairs):
    lookup, conflicts = {}, set()
    for row in rows:
        identifier, text = row.get("chunk_id"), row.get("text")
        if (not isinstance(identifier, str) or not identifier or not isinstance(text, str) or not text.strip()
                or (row.get("paper_id"), row.get("parse_revision")) not in pairs
                or type(row.get("pdf_page")) is not int or row["pdf_page"] < 1
                or not isinstance(row.get("pdf_sha256"), str) or not row["pdf_sha256"]
                or row.get("text_sha256") != _sha(text)):
            continue
        if identifier in lookup and any(row.get(key) != lookup[identifier].get(key) for key in _IDENTITY):
            conflicts.add(identifier)
        else:
            lookup[identifier] = row
    for identifier in conflicts:
        lookup.pop(identifier, None)
    return lookup, conflicts


def _returned_hits(expected, lookup):
    quote = _text(expected.get("quote"))
    if not quote or not expected.get("pdf_sha256"):
        return []
    return [identifier for identifier, row in lookup.items()
            if row["paper_id"] == expected.get("paper_id")
            and row["pdf_page"] == expected.get("pdf_page")
            and row["pdf_sha256"] == expected["pdf_sha256"]
            and ("parse_revision" not in expected or row["parse_revision"] == expected["parse_revision"])
            and quote in _text(row["text"])]


def _shown_lookup(context, candidates):
    allowed = context.get("allowed_citation_ids")
    allowed = set(allowed) if isinstance(allowed, list) and all(isinstance(v, str) for v in allowed) else set()
    found = {}
    for row in _rows(context.get("shown_evidence")):
        identifier = row.get("chunk_id")
        original = candidates.get(identifier)
        if not original or identifier not in allowed:
            continue
        text = row.get("shown_text")
        if (text != original["text"] or row.get("text_sha256") != original["text_sha256"]
                or row.get("shown_text_sha256") != original["text_sha256"]
                or type(row.get("shown_char_start")) is not int or row["shown_char_start"] != 0
                or type(row.get("shown_char_end")) is not int or row["shown_char_end"] != len(original["text"])
                or any(row.get(key) != original[key] for key in ("paper_id", "parse_revision", "pdf_page"))
                or ("pdf_sha256" in row and row["pdf_sha256"] != original["pdf_sha256"])):
            continue
        found[identifier] = original
    return found


def _stage(expected, lookup, *, applicable, available, answerable):
    targets = [{"target_index": index, "paper_id": target.get("paper_id"), "pdf_page": target.get("pdf_page"),
                "hit": bool(ids := _returned_hits(target, lookup)), "chunk_ids": ids}
               for index, target in enumerate(expected)]
    return {"applicable": applicable, "available": available,
            "targets": targets, "all_targets_hit": all(t["hit"] for t in targets)
            if applicable and answerable and targets else None}


def score_agent_case(case: dict, report: dict | None) -> dict:
    """Score one attempted outer CLI/batch record without changing its data."""
    report = _dict(report)
    result = _dict(report.get("result"))
    versions = report.get("selected_versions", result.get("selected_versions"))
    pairs = {(row.get("paper_id"), row.get("parse_revision")) for row in _rows(versions)}
    rounds = _rows(result.get("search_rounds"))
    initial_entry = next((row for row in rounds if row.get("round") == 1), {})
    retry_entry = next((row for row in rounds if row.get("round") == 2), {})
    initial_search = _dict(initial_entry.get("search")) or _dict(result.get("search"))
    retry_search = _dict(retry_entry.get("search"))
    initial_rows = _rows(initial_search.get("results"))
    retry_rows = _rows(retry_search.get("results"))
    initial_map, initial_conflicts = _candidate_map(initial_rows, pairs)
    retry_map, retry_conflicts = _candidate_map(retry_rows, pairs)
    union_map, cross_conflicts = _candidate_map(initial_rows + retry_rows, pairs)
    trace = _dict(result.get("merge_trace"))
    initial_context = _dict(result.get("initial_context"))
    if not initial_context and not retry_entry:
        initial_context = _dict(result.get("context"))
    retry_context = next((_dict(row.get("context")) for row in _rows(trace.get("rounds"))
                          if row.get("round") == "retry"), {})
    final_context = _dict(result.get("context"))
    merged_rows = _rows(trace.get("merged_candidates"))
    if not retry_entry:
        merged_rows = initial_rows
    merged_map, merged_conflicts = _candidate_map(merged_rows, pairs)
    merged_map = {identifier: row for identifier, row in merged_map.items()
                  if identifier in union_map and all(row.get(key) == union_map[identifier].get(key) for key in _IDENTITY)}
    expected = _rows(case.get("expected_evidence"))
    answerable = case["answerable"]
    stage_metrics = {
        "initial_returned": _stage(expected, initial_map, applicable=True, available=bool(initial_search), answerable=answerable),
        "initial_shown": _stage(expected, _shown_lookup(initial_context, initial_map), applicable=True, available=bool(initial_context), answerable=answerable),
        "retry_returned": _stage(expected, retry_map, applicable=bool(retry_entry), available=bool(retry_search), answerable=answerable),
        "retry_shown": _stage(expected, _shown_lookup(retry_context, retry_map), applicable=bool(retry_entry), available=bool(retry_context), answerable=answerable),
        "merged_returned": _stage(expected, merged_map, applicable=bool(retry_entry), available=bool(trace), answerable=answerable),
        "final_shown": _stage(expected, _shown_lookup(final_context, union_map), applicable=True, available=bool(final_context), answerable=answerable),
    }
    stats = _dict(result.get("statistics"))
    embedding = _dict(report.get("embedding_statistics", stats.get("embedding")))
    chat = _dict(report.get("chat_statistics", stats.get("chat")))
    embedding_requests = report.get("embedding_requests", embedding.get("embedding_requests"))
    llm_requests = report.get("llm_requests", chat.get("http_request_attempts"))
    network = report.get("network_requests")
    if "network_requests" not in report and _number(embedding_requests) is not None and _number(llm_requests) is not None:
        network = embedding_requests + llm_requests
    # Reuse the established citation occurrence and cost rules only. Override
    # retrieval targets with the separately validated genuine multi-round join.
    adapted = {**deepcopy(report), "status": report.get("status", result.get("status", "runner_failure")),
               "selected_versions": deepcopy(versions), "answer": deepcopy(report.get("answer", result.get("answer"))),
               "embedding_statistics": embedding, "chat_statistics": chat,
               "embedding_requests": embedding_requests, "llm_requests": llm_requests, "network_requests": network,
               "failure_stage": report.get("failure_stage", result.get("failure_stage")),
               "result": {**deepcopy(result), "search": {"results": list(merged_map.values())}, "context": deepcopy(final_context)}}
    score = score_case(case, adapted)
    final_targets, merged_targets = stage_metrics["final_shown"]["targets"], stage_metrics["merged_returned"]["targets"]
    score["targets"] = [{"target_index": target["target_index"], "paper_id": target["paper_id"], "pdf_page": target["pdf_page"],
                         "exact_target_hit_returned": merged["hit"], "exact_target_hit_shown": target["hit"],
                         "returned_chunk_ids": merged["chunk_ids"], "shown_chunk_ids": target["chunk_ids"]}
                        for target, merged in zip(final_targets, merged_targets)]
    initial_ids, retry_ids = list(initial_map), list(retry_map)
    initial_shown_ids = list(_shown_lookup(initial_context, initial_map))
    final_shown_ids = list(_shown_lookup(final_context, union_map))
    score.update(rubric_version=MACHINE_RUBRIC["version"], mode="agent", stage_metrics=stage_metrics,
                 exact_all_targets_hit_returned=all(t["hit"] for t in merged_targets) if answerable and merged_targets else None,
                 exact_all_targets_hit_shown=stage_metrics["final_shown"]["all_targets_hit"],
                 identity_conflicts=sorted(initial_conflicts | retry_conflicts | cross_conflicts | merged_conflicts),
                 evidence_changes={"new_returned_ids": [value for value in retry_ids if value not in initial_map],
                                   "new_shown_ids": [value for value in final_shown_ids if value not in initial_shown_ids],
                                   "new_recalled_shown_ids": [value for value in final_shown_ids if value not in initial_map],
                                   "initial_returned_unshown_now_shown_ids": [value for value in final_shown_ids
                                                                           if value in initial_map and value not in initial_shown_ids]},
                 retry_attempted=bool(retry_entry),
                 raw_parse_intercepts=sum(bool(row.get("parse_error_code")) for row in _rows(result.get("action_steps"))))
    score["tokens"]["known_embedding"] = _number(embedding.get("known_total_tokens"))
    return score


def summarize_agent_cases(scores: list[dict], planned_cases: list[dict] | None = None) -> dict:
    """Aggregate attempted cases; retain failed cases and unknown costs."""
    scores = deepcopy(scores)
    summary = summarize_case_scores(scores, planned_cases=planned_cases)
    summary.update(rubric_version=MACHINE_RUBRIC["version"], mode="agent", stage_metrics={},
                   retry_attempted_count=sum(bool(s.get("retry_attempted")) for s in scores),
                   identity_conflict_case_count=sum(bool(s.get("identity_conflicts")) for s in scores))
    answerable = [score for score in scores if score["answerable"] and score["exact_targets_available"]]
    for name in STAGE_NAMES:
        applicable = [s["stage_metrics"][name] for s in answerable if s["stage_metrics"][name]["applicable"]]
        summary["stage_metrics"][name] = {
            "applicable_count": len(applicable), "available_count": sum(s["available"] for s in applicable),
            "missing_or_failed_count": sum(not s["available"] for s in applicable),
            "all_targets_hit": _ratio(sum(bool(s["all_targets_hit"]) for s in applicable), len(applicable)),
            "quote_hit": _ratio(sum(t["hit"] for s in applicable for t in s["targets"]),
                                sum(len(s["targets"]) for s in applicable))}
    values = [score["tokens"].get("known_embedding") for score in scores]
    known = [v for v in values if v is not None]
    summary["tokens"]["known_embedding"] = {"total": sum(known) if len(known) == len(values) else None,
                                             "known_total": sum(known), "missing_records": len(values) - len(known)}
    summary["evidence_changes"] = {name: sum(len(s["evidence_changes"][name]) for s in scores)
                                   for name in ("new_returned_ids", "new_shown_ids", "new_recalled_shown_ids",
                                                "initial_returned_unshown_now_shown_ids")}
    return summary


CURRENT_RUBRIC = {
    **MACHINE_RUBRIC,
    "version": "v2-current-runtime-machine-rubric-v1",
    "shown_identity": "Match saved complete shown text and existing identity fields to recorded retrieval, reading, restored or citation sources. Do not recompute hashes or reopen PDFs.",
    "stages": "Returned is the genuine union of every attempted search. Final shown is independent. Per-round selection snapshots are diagnostic; only saved model messages establish per-round model input.",
    "stage_denominators": "Every attempted answerable case with annotated quotes remains in Returned and Final shown denominators, including zero-search answers and failures. Unattempted cases are separate.",
}


def _recorded_candidates(rows, pairs):
    """Join saved identities without repeating runtime text/PDF validation."""
    lookup, conflicts = {}, set()
    for row in rows:
        identifier = row.get("chunk_id")
        if (not isinstance(identifier, str) or not identifier
                or (row.get("paper_id"), row.get("parse_revision")) not in pairs
                or not isinstance(row.get("text"), str) or not row["text"].strip()
                or type(row.get("pdf_page")) is not int or row["pdf_page"] < 1
                or not row.get("pdf_sha256") or not row.get("text_sha256")):
            continue
        if identifier in lookup and any(row.get(key) != lookup[identifier].get(key) for key in _IDENTITY):
            conflicts.add(identifier)
        else:
            lookup[identifier] = row
    return {key: row for key, row in lookup.items() if key not in conflicts}, conflicts


def _current_shown(context, originals, pairs, metadata, conflicts):
    identities = {(row.get("paper_id"), row.get("parse_revision")): row.get("pdf_sha256")
                  for row in [*metadata, *originals.values()] if row.get("pdf_sha256")}
    candidates = dict(originals)
    for row in _rows(context.get("shown_evidence")):
        identifier = row.get("chunk_id")
        if identifier in candidates or identifier in conflicts:
            continue
        pair = row.get("paper_id"), row.get("parse_revision")
        pdf_identity = row.get("pdf_sha256") or identities.get(pair)
        if pair in pairs and pdf_identity:
            candidates[identifier] = {**row, "text": row.get("shown_text"), "pdf_sha256": pdf_identity}
    return _shown_lookup(context, candidates)


def _model_context(entry):
    for message in _rows(entry.get("messages")):
        if message.get("role") != "user" or not isinstance(message.get("content"), str):
            continue
        try:
            value = json.loads(message["content"])
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("shown_evidence"), list):
            return value
    return {}


def score_current_case(case: dict, report: dict | None) -> dict:
    """Score current page-runtime records, including zero or many searches."""
    report = _dict(report)
    result = _dict(report.get("result"))
    versions = report.get("selected_versions", result.get("selected_versions"))
    pairs = {(row.get("paper_id"), row.get("parse_revision")) for row in _rows(versions)}
    rounds = _rows(result.get("search_rounds"))
    if not rounds and (isinstance(result.get("search"), dict) or result.get("search_error")):
        raw = _dict(result.get("search"))
        rounds = [{"round": 1, "kind": "fixed", "query": raw.get("query", result.get("query")),
                   "selected_versions": raw.get("selected_versions", versions), "search": raw or None,
                   "status": raw.get("status", result.get("status"))}]
    returned_rows = [row for entry in rounds for row in _rows(_dict(entry.get("search")).get("results"))]
    returned, conflicts = _recorded_candidates(returned_rows, pairs)
    answer = _dict(report.get("answer", result.get("answer")))
    sources = _rows(answer.get("evidence_sources"))
    sources += [source for checked in _rows(result.get("citation_checks"))
                for source in _rows(checked.get("evidence_sources"))]
    originals, source_conflicts = _recorded_candidates([*returned_rows, *sources], pairs)
    conflicts |= source_conflicts
    metadata = _rows(report.get("selected_version_metadata"))
    final_context = _dict(result.get("context"))
    final_shown = _current_shown(final_context, originals, pairs, metadata, conflicts)
    expected, answerable = _rows(case.get("expected_evidence")), case["answerable"]
    stage_metrics = {
        "returned": _stage(expected, returned, applicable=True, available=bool(rounds), answerable=answerable),
        "final_shown": _stage(expected, final_shown, applicable=True, available=bool(final_context), answerable=answerable),
    }
    actions = _rows(result.get("action_steps"))
    inputs = [_model_context(row) for row in actions + _rows(_dict(result.get("generation")).get("generation_attempts"))]
    inputs = [row for row in inputs if row]
    trace_rounds = _rows(_dict(result.get("merge_trace")).get("rounds"))
    round_metrics = []
    for index, entry in enumerate(rounds, 1):
        number = entry.get("round", index)
        search = _dict(entry.get("search"))
        candidates, _ = _recorded_candidates(_rows(search.get("results")), pairs)
        selection = next((_dict(row.get("context")) for row in trace_rounds
                          if row.get("query_index") == number), {})
        autonomous_step = entry.get("autonomous_step")
        model_context = next((context for context in inputs if autonomous_step is not None
            and any(row.get("autonomous_step") == autonomous_step and row.get("tool_observation")
                    for row in _rows(context.get("executed_actions")))), {})
        if not model_context and len(rounds) == 1 and autonomous_step is None and inputs:
            model_context = inputs[0]
        shown = _current_shown(model_context, originals, pairs, metadata, conflicts)
        round_metrics.append({"round": number, "kind": entry.get("kind"),
            "autonomous_step": autonomous_step, "query": entry.get("query", search.get("query")),
            "selected_versions": deepcopy(entry.get("selected_versions", search.get("selected_versions"))),
            "status": entry.get("status", search.get("status")),
            "returned": _stage(expected, candidates, applicable=True, available=bool(search), answerable=answerable),
            "shown": _stage(expected, shown, applicable=True, available=bool(model_context), answerable=answerable),
            "selection_snapshot": _stage(expected, _shown_lookup(selection, candidates), applicable=True,
                                          available=bool(selection), answerable=answerable),
            "shown_is_model_input": bool(model_context)})
    stats = _dict(result.get("statistics"))
    embedding = _dict(report.get("embedding_statistics", stats.get("embedding")))
    chat = _dict(report.get("chat_statistics", stats.get("chat")))
    rerank = _dict(report.get("rerank_statistics", stats.get("rerank")))
    embedding_requests = report.get("embedding_requests", embedding.get("embedding_requests"))
    llm_requests = report.get("llm_requests", chat.get("http_request_attempts"))
    rerank_requests = report.get("rerank_requests", rerank.get("requests"))
    network = report.get("network_requests")
    if "network_requests" not in report and all(_number(value) is not None
            for value in (embedding_requests, llm_requests, rerank_requests)):
        network = embedding_requests + llm_requests + rerank_requests
    adapted = {**report, "status": report.get("status", result.get("status", "runner_failure")),
               "selected_versions": versions, "answer": answer,
               "embedding_statistics": embedding, "chat_statistics": chat,
               "embedding_requests": embedding_requests, "llm_requests": llm_requests,
               "network_requests": network, "failure_stage": report.get("failure_stage", result.get("failure_stage")),
               "result": {**result, "search": {"results": list(returned.values())}}}
    score = score_case(case, adapted)
    score["targets"] = [{"target_index": shown["target_index"], "paper_id": shown["paper_id"],
        "pdf_page": shown["pdf_page"], "exact_target_hit_returned": recalled["hit"],
        "exact_target_hit_shown": shown["hit"], "returned_chunk_ids": recalled["chunk_ids"],
        "shown_chunk_ids": shown["chunk_ids"]}
        for recalled, shown in zip(stage_metrics["returned"]["targets"], stage_metrics["final_shown"]["targets"])]
    score.update(rubric_version=CURRENT_RUBRIC["version"], pipeline="current", mode=report.get("mode"),
        stage_metrics=stage_metrics, round_metrics=round_metrics,
        exact_all_targets_hit_returned=stage_metrics["returned"]["all_targets_hit"],
        exact_all_targets_hit_shown=stage_metrics["final_shown"]["all_targets_hit"],
        retrieval_attempts=len(rounds), retrieval_kind_counts=dict(Counter(row.get("kind") or "unspecified" for row in rounds)),
        autonomous_step_limit=result.get("autonomous_step_limit"), autonomous_steps_used=result.get("autonomous_steps_used"),
        limit_finalize=result.get("limit_finalize", False), stop_reason=report.get("stop_reason", result.get("stop_reason")),
        retry_attempted=any(row.get("kind") == "retry" for row in rounds),
        raw_parse_intercepts=score["raw_parse_intercepts"] + sum(bool(row.get("parse_error_code")) for row in actions),
        identity_conflicts=sorted(conflicts), statistics={"embedding": deepcopy(embedding),
            "chat": deepcopy(chat), "rerank": deepcopy(rerank)})
    score["requests"]["rerank"] = _number(rerank_requests)
    score["tokens"]["known_embedding"] = _number(embedding.get("known_total_tokens"))
    return score


def _current_total(values):
    known = [value for value in values if value is not None]
    return {"total": sum(known) if len(known) == len(values) else None,
            "known_total": sum(known), "missing_records": len(values) - len(known)}


def summarize_current_cases(scores: list[dict], planned_cases: list[dict] | None = None) -> dict:
    """Aggregate actual independent attempts; failures remain in denominators."""
    summary = summarize_case_scores(scores, planned_cases=planned_cases)
    completed = sum(score["status"] in ("answered", "insufficient_evidence", "needs_clarification") for score in scores)
    attempted_ids = {score["case_id"] for score in scores}
    summary.update(rubric_version=CURRENT_RUBRIC["version"], pipeline="current",
        completed_count=completed, failed_count=len(scores) - completed,
        unattempted_count=sum(case["case_id"] not in attempted_ids for case in planned_cases)
            if planned_cases is not None else None,
        retrieval_attempts=_current_total([score["retrieval_attempts"] for score in scores]),
        autonomous_steps_used=_current_total([_number(score["autonomous_steps_used"]) for score in scores]),
        limit_finalize_count=sum(bool(score["limit_finalize"]) for score in scores),
        stop_reason_counts=dict(Counter(score["stop_reason"] or "unspecified" for score in scores)),
        retrieval_kind_counts=dict(sum((Counter(score["retrieval_kind_counts"]) for score in scores), Counter())),
        retry_attempted_count=sum(score["retry_attempted"] for score in scores), stage_metrics={})
    answerable = [score for score in scores if score["exact_targets_available"]]
    for name in ("returned", "final_shown"):
        stages = [score["stage_metrics"][name] for score in answerable]
        summary["stage_metrics"][name] = {
            "applicable_count": len(stages), "available_count": sum(stage["available"] for stage in stages),
            "missing_or_failed_count": sum(not stage["available"] for stage in stages),
            "all_targets_hit": _ratio(sum(bool(stage["all_targets_hit"]) for stage in stages), len(stages)),
            "quote_hit": _ratio(sum(target["hit"] for stage in stages for target in stage["targets"]),
                                sum(len(stage["targets"]) for stage in stages))}
    summary["requests"]["rerank"] = _current_total([score["requests"]["rerank"] for score in scores])
    summary["tokens"]["known_embedding"] = _current_total([score["tokens"]["known_embedding"] for score in scores])
    summary["provider_elapsed_seconds"] = {name: _current_total([
        _number(score["statistics"][name].get("elapsed_seconds" if name in ("chat", "rerank")
                                                       else "total_elapsed_seconds")) for score in scores])
        for name in ("embedding", "chat", "rerank")}
    summary["rerank_usage"] = [deepcopy(score["statistics"]["rerank"]) for score in scores]
    return summary
