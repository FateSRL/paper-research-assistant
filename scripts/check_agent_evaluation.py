"""D8 E: synthetic offline validation of multi-round post-hoc scoring."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from paper_assistant.agent_evaluation import (
    MACHINE_RUBRIC, score_agent_case, summarize_agent_cases, score_current_case, summarize_current_cases,
)
from paper_assistant.context import prepare_context, select_context


ROOT = Path(__file__).resolve().parents[1]
PDF_SHA = "1" * 64
PAIRS = [{"paper_id": "p1", "parse_revision": "r1"}]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def candidate(identifier="a", *, text="Target alpha.", page=1, rank=1, pdf_sha=PDF_SHA, paper="p1", revision="r1"):
    return {"chunk_id": identifier, "paper_id": paper, "parse_revision": revision,
            "pdf_page": page, "pdf_sha256": pdf_sha, "rank": rank, "score": 0.8,
            "text": text, "text_sha256": sha(text)}


def search(rows, query="Original question"):
    return {"status": "success" if rows else "no_hits", "query": query, "selected_versions": deepcopy(PAIRS),
            "results": deepcopy(rows), "returned_count": len(rows), "top_k": 5, "index_profile_id": "offline"}


def case(*, beta=False, answerable=True):
    expected = [{"paper_id": "p1", "pdf_page": 1, "pdf_sha256": PDF_SHA, "quote": "Target alpha"}] if answerable else []
    if beta:
        expected.append({"paper_id": "p1", "pdf_page": 2, "pdf_sha256": PDF_SHA, "quote": "Target beta"})
    return {"case_id": "offline-case", "answerable": answerable, "question_type": "fact", "expected_evidence": expected}


def report(initial=None, retry=None, *, final_rows=None, max_chars=8000, status="answered"):
    initial = [candidate()] if initial is None else initial
    first_search = search(initial)
    first_context = prepare_context(first_search, max_chars=max_chars)
    rounds = [{"round": 1, "search": deepcopy(first_search), "status": first_search["status"]}]
    trace = None
    selected_rows = initial if final_rows is None else final_rows
    if retry is not None:
        second_search = search(retry, "Retry query")
        second_context = prepare_context(second_search, max_chars=max_chars)
        rounds.append({"round": 2, "search": deepcopy(second_search), "status": second_search["status"]})
        all_merged = []
        seen = set()
        for row in retry + initial:
            if row["chunk_id"] not in seen:
                seen.add(row["chunk_id"])
                all_merged.append({**deepcopy(row), "rank": len(all_merged) + 1})
        trace = {"merged_candidates": all_merged,
                 "rounds": [{"round": "initial", "context": first_context}, {"round": "retry", "context": second_context}]}
        selected_rows = all_merged if final_rows is None else final_rows
    selected = [{**deepcopy(row), "rank": index + 1} for index, row in enumerate(selected_rows)]
    final_context = {**select_context(selected, [("p1", "r1")], max_chars=max_chars), "question": "Original question"}
    answer = {"status": status, "claims": [{"claim": "Claim.", "citation_ids": final_context["allowed_citation_ids"]}]} if status == "answered" else None
    result = {"status": status, "selected_versions": deepcopy(PAIRS), "search": first_search,
              "initial_context": first_context, "context": final_context, "search_rounds": rounds,
              "merge_trace": trace, "answer": answer, "citation_checks": [], "action_steps": [],
              "statistics": {"embedding": {"embedding_requests": len(rounds), "total_tokens": 7 * len(rounds), "known_total_tokens": 7 * len(rounds)},
                             "chat": {"sdk_request_attempts": len(rounds), "http_request_attempts": len(rounds), "network_retries": 0,
                                      "repairs": 0, "total_tokens": 25 * len(rounds), "known_total_tokens": 25 * len(rounds)}}}
    return {"status": status, "selected_versions": deepcopy(PAIRS), "answer": deepcopy(answer), "result": result,
            "started_at_utc": "2026-10-05T00:00:00+00:00", "finished_at_utc": "2026-10-05T00:00:02+00:00"}


class AgentEvaluationChecks(unittest.TestCase):
    def test_all_target_and_quote_hits_are_separate_at_each_round_and_final(self):
        saved = report(retry=[candidate("b", text="Target beta.", page=2)])
        score = score_agent_case(case(beta=True), saved)
        self.assertFalse(score["stage_metrics"]["initial_returned"]["all_targets_hit"])
        self.assertFalse(score["stage_metrics"]["retry_returned"]["all_targets_hit"])
        self.assertTrue(score["stage_metrics"]["merged_returned"]["all_targets_hit"])
        self.assertTrue(score["exact_all_targets_hit_shown"])
        self.assertEqual([row["hit"] for row in score["stage_metrics"]["initial_shown"]["targets"]], [True, False])
        self.assertEqual([row["hit"] for row in score["stage_metrics"]["retry_shown"]["targets"]], [False, True])

        later_alpha = candidate("later-alpha")
        later_beta = candidate("later-beta", text="Target beta.", page=2)
        unrelated = candidate("first", text="Unrelated first retrieval.")
        current = report(initial=[unrelated], final_rows=[later_alpha, later_beta])
        current["mode"] = "agent"
        result = current["result"]
        result.update(retrieval_strategy="autonomous", autonomous_step_limit=5,
                      autonomous_steps_used=5, limit_finalize=True, stop_reason="step_limit_answered")
        result["initial_context"] = prepare_context(search([]))
        result["search_rounds"], trace_rounds, actions, executed, accumulated = [], [], [], [], []
        for number, rows in enumerate(([unrelated], None, [later_alpha], [], [later_beta]), 1):
            context = {**select_context([{**row, "rank": i + 1} for i, row in enumerate(accumulated)],
                                       [("p1", "r1")]), "executed_actions": deepcopy(executed)}
            actions.append({"autonomous_step": number, "messages": [
                {"role": "user", "content": json.dumps(context)}]})
            raw = search(rows, "Adaptive query " + str(number)) if rows is not None else None
            result["search_rounds"].append({"round": number, "kind": "adaptive", "autonomous_step": number,
                "query": "Adaptive query " + str(number), "selected_versions": deepcopy(PAIRS),
                "status": raw["status"] if raw else "tool_error", "search": raw})
            if raw:
                trace_rounds.append({"round": "adaptive", "query_index": number,
                                     "context": prepare_context(raw)})
                accumulated.extend(rows)
            executed.append({"autonomous_step": number, "tool_observation": {"status": "success" if raw else "tool_error"}})
        actions.append({"autonomous_step": 5, "limit_finalize": True, "messages": [
            {"role": "user", "content": json.dumps({**result["context"], "executed_actions": executed})}]})
        result["action_steps"] = actions
        result["merge_trace"] = {"rounds": trace_rounds,
                                 "merged_candidates": [candidate("diagnostic-only", text="Target beta.", page=2)]}
        with patch("paper_assistant.agent_evaluation._sha", side_effect=AssertionError("No new text hashes")):
            scored = score_current_case(case(beta=True), current)
        self.assertTrue(scored["exact_all_targets_hit_returned"])
        self.assertTrue(scored["exact_all_targets_hit_shown"])
        self.assertEqual(scored["retrieval_attempts"], 5)
        self.assertEqual(scored["retrieval_kind_counts"], {"adaptive": 5})
        self.assertFalse(scored["retry_attempted"])
        self.assertEqual(scored["targets"][1]["returned_chunk_ids"], ["later-beta"])
        self.assertEqual([row["returned"]["targets"][0]["hit"] for row in scored["round_metrics"]],
                         [False, False, True, False, False])
        self.assertEqual([row["selection_snapshot"]["available"] for row in scored["round_metrics"]],
                         [True, False, True, True, True])
        self.assertEqual(scored["round_metrics"][0]["shown"]["targets"][0]["hit"], False)
        self.assertEqual(scored["round_metrics"][2]["shown"]["targets"][0]["hit"], True)
        self.assertTrue(scored["round_metrics"][-1]["shown"]["all_targets_hit"])

        diagnostic = deepcopy(current)
        diagnostic["result"]["action_steps"] = []
        diagnostic_score = score_current_case(case(beta=True), diagnostic)
        self.assertFalse(diagnostic_score["round_metrics"][2]["shown"]["available"])
        self.assertTrue(diagnostic_score["round_metrics"][2]["selection_snapshot"]["available"])

        reading = report(initial=[unrelated], final_rows=[later_alpha])
        reading["mode"] = "agent"
        reading["result"]["search_rounds"][0]["kind"] = "adaptive"
        reading["result"]["context"]["reading_origins"] = [
            {"chunk_id": later_alpha["chunk_id"], "anchor_chunk_id": unrelated["chunk_id"],
             "kind": "adjacent_body_read"}]
        read_score = score_current_case(case(), reading)
        self.assertFalse(read_score["exact_all_targets_hit_returned"])
        self.assertTrue(read_score["exact_all_targets_hit_shown"])
        self.assertEqual(read_score["targets"][0]["shown_chunk_ids"], ["later-alpha"])

        zero = report(initial=[])
        zero["mode"] = "agent"
        zero["result"].update(search=None, search_rounds=[], merge_trace=None, autonomous_steps_used=1,
                              autonomous_step_limit=5, limit_finalize=False, stop_reason="answered")
        zero_score = score_current_case(case(), zero)
        self.assertEqual(zero_score["retrieval_attempts"], 0)
        self.assertEqual(zero_score["round_metrics"], [])
        self.assertTrue(zero_score["program_answered_completion"])
        self.assertFalse(zero_score["exact_all_targets_hit_returned"])
        self.assertFalse(zero_score["exact_all_targets_hit_shown"])
        self.assertIsNone(zero_score["qa_accuracy"])

        restored = deepcopy(zero)
        restored["result"]["context"] = prepare_context(search([later_alpha]))
        restored["answer"]["evidence_sources"] = [later_alpha]
        restored_score = score_current_case(case(), restored)
        self.assertFalse(restored_score["exact_all_targets_hit_returned"])
        self.assertTrue(restored_score["exact_all_targets_hit_shown"])

        failed = score_current_case(case(), {"mode": "agent", "status": "tool_error", "selected_versions": PAIRS,
                                            "result": {"stop_reason": "resource_failure"}})
        planned = [case(), {**case(), "case_id": "unattempted"}]
        summary = summarize_current_cases([scored, zero_score, failed], planned_cases=planned)
        self.assertEqual(summary["exact_all_targets_hit_shown"]["denominator"], 3)
        self.assertEqual(summary["exact_all_targets_hit_shown"]["numerator"], 1)
        self.assertEqual(summary["failed_count"], 1)
        self.assertEqual(summary["unattempted_count"], 1)
        self.assertEqual(summary["retrieval_attempts"]["total"], 5)
        self.assertEqual(summary["limit_finalize_count"], 1)
        self.assertEqual(summary["retry_attempted_count"], 0)
        self.assertIsNone(summary["qa_accuracy"])

    def test_final_shown_pdf_identity_joins_new_retry_candidate_not_initial_search(self):
        saved = report(initial=[candidate(text="No target here.")], retry=[candidate("new", text="Target alpha.")])
        score = score_agent_case(case(), saved)
        self.assertTrue(score["exact_all_targets_hit_shown"])
        self.assertEqual(score["targets"][0]["shown_chunk_ids"], ["new"])
        self.assertEqual(score["evidence_changes"]["new_recalled_shown_ids"], ["new"])

    def test_wrong_pdf_page_and_paper_fail_even_with_exact_quote(self):
        for field, value in (("pdf_sha256", "2" * 64), ("pdf_page", 9), ("paper_id", "p2"), ("parse_revision", "r2")):
            with self.subTest(field=field):
                saved = report()
                for row in (saved["result"]["search"]["results"][0], saved["result"]["search_rounds"][0]["search"]["results"][0]):
                    row[field] = value
                score = score_agent_case(case(), saved)
                self.assertFalse(score["exact_all_targets_hit_returned"])
                self.assertFalse(score["exact_all_targets_hit_shown"])

    def test_expected_revision_if_recorded_is_respected(self):
        target = case()
        target["expected_evidence"][0]["parse_revision"] = "r2"
        self.assertFalse(score_agent_case(target, report())["exact_all_targets_hit_returned"])

    def test_case_sensitive_quote_only_normalizes_whitespace(self):
        saved = report(initial=[candidate(text="Target\n   alpha.")])
        self.assertTrue(score_agent_case(case(), saved)["exact_all_targets_hit_shown"])
        target = case()
        target["expected_evidence"][0]["quote"] = "target alpha"
        self.assertFalse(score_agent_case(target, saved)["exact_all_targets_hit_shown"])

    def test_quote_cannot_be_spliced_across_chunks(self):
        saved = report(initial=[candidate("a", text="Target", rank=1), candidate("b", text="alpha", rank=2)])
        self.assertFalse(score_agent_case(case(), saved)["exact_all_targets_hit_returned"])

    def test_final_snapshot_text_hash_range_and_allowed_id_must_match_candidate(self):
        mutators = [lambda row: row.update(shown_text="Target alpha"), lambda row: row.update(shown_text_sha256="0" * 64),
                    lambda row: row.update(text_sha256="0" * 64), lambda row: row.update(shown_char_start=1),
                    lambda row: row.update(shown_char_end=True), lambda row: row.update(parse_revision="r2")]
        for index, mutate in enumerate(mutators):
            with self.subTest(index=index):
                saved = report()
                mutate(saved["result"]["context"]["shown_evidence"][0])
                self.assertFalse(score_agent_case(case(), saved)["exact_all_targets_hit_shown"])
        saved = report()
        saved["result"]["context"]["allowed_citation_ids"] = []
        self.assertFalse(score_agent_case(case(), saved)["exact_all_targets_hit_shown"])

    def test_candidate_original_text_hash_is_checked(self):
        saved = report()
        saved["result"]["search_rounds"][0]["search"]["results"][0]["text_sha256"] = "0" * 64
        score = score_agent_case(case(), saved)
        self.assertFalse(score["exact_all_targets_hit_returned"])
        self.assertFalse(score["exact_all_targets_hit_shown"])

    def test_conflicting_same_id_pdf_identity_does_not_join_final_source(self):
        saved = report(retry=[candidate("a", pdf_sha="2" * 64)])
        score = score_agent_case(case(), saved)
        self.assertEqual(score["identity_conflicts"], ["a"])
        self.assertTrue(score["stage_metrics"]["initial_returned"]["all_targets_hit"])
        self.assertFalse(score["exact_all_targets_hit_shown"])

    def test_forged_merge_candidate_never_counts_as_returned_or_shown(self):
        saved = report(retry=[])
        saved["result"]["merge_trace"]["merged_candidates"] = [candidate("forged")]
        saved["result"]["context"] = {**select_context([candidate("forged")], [("p1", "r1")]), "question": "Original question"}
        score = score_agent_case(case(), saved)
        self.assertFalse(score["exact_all_targets_hit_returned"])
        self.assertFalse(score["exact_all_targets_hit_shown"])

    def test_new_returned_new_shown_and_initial_unshown_now_shown_are_distinct(self):
        first = [candidate("initial", text="abcde", rank=1), candidate("omitted", text="Target alpha.", rank=2)]
        saved = report(initial=first, retry=[{**first[1], "rank": 1}], max_chars=14)
        score = score_agent_case(case(), saved)
        self.assertEqual(score["evidence_changes"]["new_returned_ids"], [])
        self.assertEqual(score["evidence_changes"]["new_shown_ids"], ["omitted"])
        self.assertEqual(score["evidence_changes"]["new_recalled_shown_ids"], [])
        self.assertEqual(score["evidence_changes"]["initial_returned_unshown_now_shown_ids"], ["omitted"])

    def test_unattempted_retry_is_null_but_failed_attempted_retry_is_a_miss(self):
        score = score_agent_case(case(), report())
        self.assertFalse(score["stage_metrics"]["retry_returned"]["applicable"])
        self.assertIsNone(score["stage_metrics"]["retry_returned"]["all_targets_hit"])
        failed = report(status="tool_error")
        failed["result"]["search_rounds"].append({"round": 2, "search": None, "status": "tool_error"})
        attempted = score_agent_case(case(), failed)
        self.assertTrue(attempted["stage_metrics"]["retry_returned"]["applicable"])
        self.assertFalse(attempted["stage_metrics"]["retry_returned"]["all_targets_hit"])
        summary = summarize_agent_cases([score, attempted])
        self.assertEqual(summary["stage_metrics"]["retry_returned"]["all_targets_hit"]["denominator"], 1)
        self.assertEqual(summary["stage_metrics"]["retry_returned"]["missing_or_failed_count"], 1)

    def test_failed_first_attempt_stays_in_initial_and_final_denominators(self):
        score = score_agent_case(case(), {"status": "tool_error", "selected_versions": PAIRS, "result": {}})
        summary = summarize_agent_cases([score])
        self.assertEqual(summary["exact_all_targets_hit_shown"], {"numerator": 0, "denominator": 1, "ratio": 0.0})
        self.assertEqual(summary["stage_metrics"]["initial_returned"]["all_targets_hit"]["denominator"], 1)

    def test_published_duplicate_citations_and_prior_intercepts_are_counted_separately(self):
        # Legacy claim records keep their original occurrence metric.
        legacy = report()
        legacy["answer"]["claims"][0]["citation_ids"] = ["a", "a"]
        legacy["result"]["citation_checks"] = [{"checks": [{"claim_index": 0, "citation_index": 0, "chunk_id": "bad", "status": "invalid_output"}]},
                                               {"checks": [{"claim_index": 0, "citation_index": 0, "chunk_id": "a", "status": "valid"},
                                                           {"claim_index": 0, "citation_index": 1, "chunk_id": "a", "status": "valid"}]}]
        legacy["result"]["action_steps"] = [{"parse_error_code": "invalid_json"}, {"parse_error_code": None}]
        legacy_score = score_agent_case(case(), legacy)
        self.assertEqual(legacy_score["citation_location"], {"numerator": 2, "denominator": 2, "ratio": 1.0})
        self.assertEqual(legacy_score["output_claim_count"], 1)
        self.assertIsNone(legacy_score["published_citation_occurrences"])

        # New prose answers count every published occurrence, including repeats;
        # unique sources are separate and claims are not invented.
        saved = report()
        from paper_assistant.prose import normalize_citation_markers, parse_markers
        text = normalize_citation_markers(
            "Alpha result [ID:1]. Beta result [ID: 2]. Alpha again [ID:1]. Bibliography [1] [99].")
        saved["answer"] = {
            "text": text,
            "citations": [{**marker, "chunk_id": {1: "a", 2: "b"}[marker["ref"]]}
                          for marker in parse_markers(text)],
            "evidence_sources": [candidate("a"), candidate("b", text="Target beta.", page=2)],
        }
        saved["result"]["answer"] = deepcopy(saved["answer"])
        saved["result"]["citation_checks"] = [
            {"checks": [{"claim_index": 0, "citation_index": 0, "chunk_id": "bad", "status": "invalid_output"}]},
            {"checks": [{"claim_index": 0, "citation_index": 0, "chunk_id": "a", "status": "valid"},
                         {"claim_index": 0, "citation_index": 1, "chunk_id": "b", "status": "valid"},
                         {"claim_index": 0, "citation_index": 2, "chunk_id": "a", "status": "valid"}]}]
        saved["result"]["action_steps"] = [{"parse_error_code": "invalid_json"}, {"parse_error_code": None}]
        score = score_agent_case(case(), saved)
        self.assertEqual(score["citation_location"], {"numerator": 3, "denominator": 3, "ratio": 1.0})
        self.assertEqual(score["published_citation_occurrences"], 3)
        self.assertEqual(score["published_unique_sources"], 2)
        self.assertIsNone(score["output_claim_count"])
        self.assertTrue(score["program_answered_completion"])
        self.assertEqual(score["raw_citation_intercepts"], 1)
        self.assertEqual(score["raw_parse_intercepts"], 1)

        saved["answer"] = {"text": "The available evidence cannot determine that value. Bibliography [1] [99].",
                           "citations": [], "evidence_sources": []}
        saved["result"]["answer"] = deepcopy(saved["answer"])
        saved["result"]["citation_checks"] = [{"status": "valid", "checks": []}]
        empty = score_agent_case(case(), saved)
        self.assertEqual(empty["published_citation_occurrences"], 0)
        self.assertEqual(empty["published_unique_sources"], 0)
        self.assertEqual(empty["citation_location"], {"numerator": 0, "denominator": 0, "ratio": None})
        self.assertIsNone(empty["output_claim_count"])

    def test_program_answer_and_negative_refusal_never_become_semantic_scores(self):
        positive = score_agent_case(case(), report())
        negative = score_agent_case(case(answerable=False), report(status="insufficient_evidence"))
        self.assertTrue(positive["program_answered_completion"])
        self.assertTrue(negative["program_negative_refusal"])
        for score in (positive, negative):
            self.assertIsNone(score["qa_accuracy"])
            self.assertIsNone(score["correct_refusal_semantic"])
            self.assertEqual(score["human_review_status"], "pending")
        self.assertIsNone(negative["exact_all_targets_hit_shown"])
        self.assertIsNone(negative["citation_location"]["ratio"])

    def test_unknown_usage_and_explicit_unknown_counts_stay_null_in_summary(self):
        saved = report()
        saved["result"]["statistics"]["embedding"].update(total_tokens=None, known_total_tokens=7)
        saved["result"]["statistics"]["chat"].update(total_tokens=None, known_total_tokens=25)
        saved["embedding_requests"] = None
        saved["network_requests"] = None
        score = score_agent_case(case(), saved)
        self.assertIsNone(score["tokens"]["embedding"])
        self.assertIsNone(score["tokens"]["chat"])
        self.assertIsNone(score["requests"]["embedding"])
        self.assertIsNone(score["requests"]["network"])
        summary = summarize_agent_cases([score])
        self.assertIsNone(summary["tokens"]["embedding"]["total"])
        self.assertEqual(summary["tokens"]["embedding"]["missing_records"], 1)
        self.assertEqual(summary["tokens"]["known_embedding"]["known_total"], 7)

    def test_empty_summary_has_na_ratios_and_no_invented_accuracy(self):
        summary = summarize_agent_cases([])
        self.assertEqual(summary["attempted_count"], 0)
        self.assertIsNone(summary["citation_location"]["ratio"])
        self.assertIsNone(summary["qa_accuracy"])
        for metric in summary["stage_metrics"].values():
            self.assertEqual(metric["all_targets_hit"]["denominator"], 0)
            self.assertIsNone(metric["all_targets_hit"]["ratio"])

    def test_planned_cases_are_reported_without_entering_attempted_denominators(self):
        planned = [case(), case(beta=True), case(answerable=False)]
        before = deepcopy(planned)
        score = score_agent_case(planned[0], report())
        summary = summarize_agent_cases([score], planned_cases=planned)
        self.assertEqual(summary["planned_count"], 3)
        self.assertEqual(summary["planned_answerable_count"], 2)
        self.assertEqual(summary["attempted_count"], 1)
        self.assertEqual(summary["stage_metrics"]["initial_returned"]["all_targets_hit"]["denominator"], 1)
        self.assertEqual(planned, before)
        self.assertIsNone(summarize_agent_cases([score])["planned_count"])

    def test_scoring_and_summary_do_not_mutate_annotations_or_records(self):
        target, saved = case(), report(retry=[candidate("new")])
        before_target, before_saved = deepcopy(target), deepcopy(saved)
        score = score_agent_case(target, saved)
        before_score = deepcopy(score)
        summarize_agent_cases([score])
        self.assertEqual(target, before_target)
        self.assertEqual(saved, before_saved)
        self.assertEqual(score, before_score)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
