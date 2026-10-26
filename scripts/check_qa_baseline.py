"""D5 F：批次恢复、标注隔离和评分分母的离线检查，真实 API 0 次。"""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from paper_assistant.answer_export import atomic_text, exclusive_json
from paper_assistant.evaluation import MACHINE_RUBRIC, score_case, summarize_case_scores
from paper_assistant.indexing import atomic_json
from scripts import run_qa_baseline as runner


ROOT = Path(__file__).resolve().parents[1]
CASES = [{"case_id": case_id, "question": "Original question " + case_id,
          "paper_ids": ["arxiv_2005.11401v4"], "answerable": case_id != "D2-006",
          "question_type": "unanswerable" if case_id == "D2-006" else "fact",
          "expected_points": ["SECRET_EXPECTED_POINTS"],
          "expected_evidence": [{"paper_id": "arxiv_2005.11401v4", "pdf_sha256": "pdf", "pdf_page": 1, "quote": "Target quote"}]
          if case_id != "D2-006" else []} for case_id in runner.FIRST_FOUR]


def frozen():
    return {"cases": deepcopy(CASES), "case_order": list(runner.FIRST_FOUR),
            "policy": {"max_attempts": 3}, "top_k": 5, "max_chars": 8000,
            "rubric": deepcopy(MACHINE_RUBRIC), "semantic_rubric_sha256": "fixed", "source_sha256": {name: "fixed" for name in runner.SOURCES},
            "index_profile": {"id": "profile"}, "eval_sha256": "eval",
            "chat_configuration": {"provider": "fake", "model_id": "fake-model", "configured_timeout": 30}}


def report(case, status="answered"):
    claims = [{"claim": "Answer", "citation_ids": ["chunk", "chunk"]}] if status == "answered" else []
    checks = [{"claim_index": 0, "citation_index": index, "chunk_id": "chunk", "status": "valid"} for index in range(len(claims[0]["citation_ids"]) if claims else 0)]
    return {"status": status, "run_id": case["case_id"] + "_first", "query": case["question"],
            "selected_versions": [{"paper_id": p, "parse_revision": runner.READY_PAIRS[p]} for p in case["paper_ids"]],
            "top_k": 5, "max_chars": 8000, "policy": {"max_attempts": 3},
            "configuration": {"chat": {"provider": "fake", "model_id": "fake-model", "configured_timeout": 30}},
            "index_profile": {"id": "profile"}, "source_unchanged_during_run": True,
            "source_sha256": {name: "fixed" for name in runner.SOURCES[:-2]}, "eval_sha256": {"eval/dev.jsonl": "eval"},
            "started_at_utc": "2026-10-04T00:00:00+00:00", "finished_at_utc": "2026-10-04T00:00:02+00:00",
            "answer": {"claims": claims}, "embedding_requests": 1, "llm_requests": 1, "network_requests": 2,
            "embedding_statistics": {"total_tokens": 7},
            "chat_statistics": {"total_tokens": 20, "known_total_tokens": 20, "sdk_request_attempts": 1, "network_retries": 0, "repairs": 0},
            "result": {"search": {"results": [{"chunk_id": "chunk", "paper_id": "arxiv_2005.11401v4", "parse_revision": runner.READY_PAIRS["arxiv_2005.11401v4"], "pdf_sha256": "pdf", "pdf_page": 1, "text": "prefix Target\n quote suffix"}]},
                       "context": {"shown_evidence": [{"chunk_id": "chunk", "paper_id": "arxiv_2005.11401v4", "parse_revision": runner.READY_PAIRS["arxiv_2005.11401v4"], "pdf_page": 1, "shown_text": "Target quote"}]},
                       "citation_checks": [{"checks": checks}], "generation": {}, "citation_repairs": []}}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = frozen()
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, argv, **kwargs):
        self.calls.append(deepcopy(argv))
        question = argv[argv.index("--query") + 1]
        case = next(c for c in CASES if c["question"] == question)
        r = report(case)
        r["history_report"] = "archive/run_logs/d5/answer_" + case["case_id"] + ".json"
        exclusive_json(self.root / r["history_report"], r)
        return SimpleNamespace(returncode=0, stdout=json.dumps(r), stderr="deprecated")

    def run_batch(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return runner.run_batch("test", root=self.root, make_binding=lambda _: deepcopy(self.config), run_process=self.fake, **kwargs)

    def directory(self):
        return self.root / "artifacts/d5/qa_baseline/test"

    def test_prepare_has_no_process_and_freezes_rubric(self):
        value = self.run_batch()
        self.assertEqual(self.calls, [])
        self.assertEqual(value["completed_case_ids"], [])
        self.assertEqual(runner.read_json(self.directory() / "rubric.json"), MACHINE_RUBRIC)
        self.assertEqual(runner.read_json(self.directory() / "manifest.initial.json")["binding"], self.config)

    def test_runtime_only_question_and_pairs(self):
        self.run_batch(live=True, case_ids=["D2-001"])
        command = self.calls[0]
        self.assertEqual(command, runner.cli_command(CASES[0]))
        self.assertNotIn("SECRET_EXPECTED_POINTS", " ".join(command))
        self.assertNotIn("Target quote", " ".join(command))
        self.assertNotIn("answerable", " ".join(command))

    def test_four_then_resume_no_repeat(self):
        self.run_batch(live=True, case_ids=["D2-001", "D2-005"])
        original = (self.directory() / "results/D2-001.json").read_bytes()
        value = self.run_batch(live=True, resume=True)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(value["completed_case_ids"], runner.FIRST_FOUR)
        self.assertEqual((self.directory() / "results/D2-001.json").read_bytes(), original)

    def test_completed_resume_does_not_charge(self):
        self.run_batch(live=True)
        self.run_batch(live=True, resume=True)
        self.assertEqual(len(self.calls), 4)

    def test_existing_batch_refused(self):
        self.run_batch()
        with self.assertRaises(FileExistsError):
            self.run_batch(live=True)
        self.assertEqual(self.calls, [])


    def test_eval_plan_change_resume_refused(self):
        self.run_batch()
        self.config["cases"][0]["expected_points"] = ["changed"]
        with self.assertRaises(ValueError):
            self.run_batch(live=True, resume=True)

    def test_profile_policy_rubric_change_refused(self):
        self.run_batch()
        for key in ("policy", "semantic_rubric_sha256", "top_k"):
            old = deepcopy(self.config[key])
            self.config[key] = "changed"
            with self.assertRaises(ValueError):
                self.run_batch(live=True, resume=True)
            self.config[key] = old
        self.assertEqual(self.calls, [])

    def test_initial_manifest_change_refused(self):
        self.run_batch()
        path = self.directory() / "manifest.initial.json"
        value = runner.read_json(path)
        value["binding_sha256"] = "changed"
        atomic_json(path, value)
        with self.assertRaises(ValueError):
            self.run_batch(live=True, resume=True)

    def test_result_tampering_refused(self):
        self.run_batch(live=True, case_ids=["D2-001"])
        path = self.directory() / "results/D2-001.json"
        value = runner.read_json(path)
        value["report"]["status"] = "changed"
        atomic_json(path, value)
        with self.assertRaisesRegex(ValueError, "case_record_mismatch"):
            self.run_batch(live=True, resume=True)
        self.assertEqual(len(self.calls), 1)

    def test_nonzero_valid_failure_is_saved_without_retry(self):
        def failed(argv, **kwargs):
            self.calls.append(argv)
            r = report(CASES[0], "invalid_output")
            r["history_report"] = "archive/run_logs/d5/answer_failed.json"
            exclusive_json(self.root / r["history_report"], r)
            return SimpleNamespace(returncode=1, stdout=json.dumps(r), stderr="")
        with redirect_stdout(io.StringIO()):
            runner.run_batch("test", live=True, case_ids=["D2-001"], root=self.root, make_binding=lambda _: deepcopy(self.config), run_process=failed)
        self.run_batch(live=True, resume=True, case_ids=["D2-001"])
        result = runner.read_json(self.directory() / "results/D2-001.json")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["report"]["status"], "invalid_output")
        self.assertEqual(len(self.calls), 1)

    def test_unknown_stdout_preserves_unknown_cost_stops_batch(self):
        def bad(argv, **kwargs):
            self.calls.append(argv)
            return SimpleNamespace(returncode=2, stdout="unsafe secret could be here", stderr="unsafe secret")
        with redirect_stdout(io.StringIO()):
            value = runner.run_batch("test", live=True, root=self.root, make_binding=lambda _: deepcopy(self.config), run_process=bad)
        result = runner.read_json(self.directory() / "results/D2-001.json")
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(result["machine_score"]["requests"]["embedding"])
        self.assertNotIn("unsafe secret", json.dumps(result))
        self.assertEqual(value["needs_attention_case_ids"], ["D2-001"])
        self.run_batch(live=True, resume=True)
        self.assertEqual(len(self.calls), 1)

    def test_process_exception_saves_unknown_not_zero(self):
        def bad(*args, **kwargs):
            self.calls.append(args[0])
            raise OSError("secret")
        with redirect_stdout(io.StringIO()):
            runner.run_batch("test", live=True, root=self.root, make_binding=lambda _: deepcopy(self.config), run_process=bad)
        result = runner.read_json(self.directory() / "results/D2-001.json")
        self.assertIsNone(result["machine_score"]["requests"]["network"])
        self.assertEqual(result["runner_error"]["code"], "process_failure")

    def test_input_mismatch_is_runner_failure(self):
        bad = report(CASES[1])
        entry = runner.capture_case(CASES[0], self.config, root=self.root,
                                    run_process=lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(bad), stderr=""))
        self.assertEqual(entry["attempt_status"], "needs_attention")
        self.assertEqual(entry["report"], bad)
        self.assertEqual(entry["machine_score"]["requests"]["network"], 2)

    def test_interrupted_reservation_requires_attention_no_process(self):
        self.run_batch()
        exclusive_json(self.directory() / "reservations/D2-001.json", {"status": "may_have_requested"})
        value = self.run_batch(live=True, resume=True)
        self.assertEqual(value["needs_attention_case_ids"], ["D2-001"])
        self.assertEqual(self.calls, [])

    def test_keyboard_interrupt_keeps_reservation_and_releases_lock(self):
        def interrupted(*a, **k):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt), redirect_stdout(io.StringIO()):
            runner.run_batch("test", live=True, root=self.root, make_binding=lambda _: deepcopy(self.config), run_process=interrupted)
        self.assertTrue((self.directory() / "reservations/D2-001.json").exists())
        self.assertFalse((self.directory().parent / ".runner.lock").exists())
        value = self.run_batch(live=True, resume=True)
        self.assertEqual(value["needs_attention_case_ids"], ["D2-001"])

    def test_lock_prevents_other_runner(self):
        self.run_batch()
        exclusive_json(self.directory().parent / ".runner.lock", {"owner": "other"})
        with self.assertRaises(FileExistsError):
            self.run_batch(live=True, resume=True)
        self.assertEqual(self.calls, [])

    def test_case_order_fixed(self):
        self.run_batch(live=True, case_ids=["D2-006", "D2-001"])
        questions = [c[c.index("--query") + 1] for c in self.calls]
        self.assertEqual(questions, [CASES[0]["question"], CASES[3]["question"]])

    def test_invalid_case_selection_no_process(self):
        for selection in (["missing"], ["D2-001", "D2-001"]):
            with self.assertRaises(ValueError):
                self.run_batch(live=True, case_ids=selection)
        self.assertEqual(self.calls, [])

    def test_unsafe_batch_id_refused(self):
        with self.assertRaises(ValueError):
            runner.run_batch("../escape", root=self.root, make_binding=lambda _: self.config)

    def test_change_before_next_call_stops(self):
        counters = [0]
        def changing(_):
            counters[0] += 1
            value = deepcopy(self.config)
            if counters[0] >= 3:
                value["top_k"] = 6
            return value
        with self.assertRaisesRegex(ValueError, "binding_changed_before_case"), redirect_stdout(io.StringIO()):
            runner.run_batch("test", live=True, root=self.root, make_binding=changing, run_process=self.fake)
        self.assertEqual(len(self.calls), 1)

    def test_original_stdout_exact_and_history_verified(self):
        r = report(CASES[0])
        r["history_report"] = "archive/run_logs/d5/answer_first.json"
        exclusive_json(self.root / r["history_report"], r)
        stdout = json.dumps(r, indent=2)
        entry = runner.capture_case(CASES[0], self.config, root=self.root,
                                    run_process=lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout, stderr=""))
        self.assertEqual(entry["stdout"], stdout)
        self.assertTrue(entry["source_history_verified"])

    def test_model_source_profile_mismatch_preserves_cost(self):
        for mutate in (lambda r: r["configuration"]["chat"].update(model_id="changed"),
                       lambda r: r.update(index_profile={"id": "changed"})):
            r = report(CASES[0])
            mutate(r)
            entry = runner.capture_case(CASES[0], self.config, root=self.root,
                                        run_process=lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(r), stderr=""))
            self.assertEqual(entry["attempt_status"], "needs_attention")
            self.assertEqual(entry["report"], r)
            self.assertEqual(entry["machine_score"]["tokens"]["chat"], 20)

    def test_missing_history_requires_attention_preserves_report(self):
        r = report(CASES[0])
        entry = runner.capture_case(CASES[0], self.config, root=self.root,
                                    run_process=lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(r), stderr=""))
        self.assertEqual(entry["attempt_status"], "needs_attention")
        self.assertEqual(entry["report"], r)
        self.assertIn("source_history_not_verified", entry["runner_warnings"])



class ScoringTests(unittest.TestCase):
    def test_exact_whitespace_match_and_repeat_citations(self):
        s = score_case(CASES[0], report(CASES[0]))
        self.assertTrue(s["targets"][0]["exact_target_hit_returned"])
        self.assertTrue(s["targets"][0]["exact_target_hit_shown"])
        self.assertEqual(s["citation_location"], {"numerator": 2, "denominator": 2, "ratio": 1})

    def test_wrong_pdf_page_does_not_hit(self):
        r = report(CASES[0])
        r["result"]["search"]["results"][0]["pdf_page"] = 2
        self.assertFalse(score_case(CASES[0], r)["exact_all_targets_hit_returned"])

    def test_wrong_paper_does_not_hit(self):
        r = report(CASES[0])
        r["result"]["context"]["shown_evidence"][0]["paper_id"] = "other"
        self.assertFalse(score_case(CASES[0], r)["exact_all_targets_hit_shown"])

    def test_wrong_pdf_sha_does_not_hit_returned_or_shown(self):
        r = report(CASES[0])
        r["result"]["search"]["results"][0]["pdf_sha256"] = "wrong_pdf"
        s = score_case(CASES[0], r)
        self.assertFalse(s["exact_all_targets_hit_returned"])
        self.assertFalse(s["exact_all_targets_hit_shown"])

    def test_wrong_candidate_revision_does_not_hit(self):
        r = report(CASES[0])
        r["result"]["search"]["results"][0]["parse_revision"] = "old_revision"
        s = score_case(CASES[0], r)
        self.assertFalse(s["exact_all_targets_hit_returned"])
        self.assertFalse(s["exact_all_targets_hit_shown"])

    def test_wrong_shown_revision_does_not_hit(self):
        r = report(CASES[0])
        r["result"]["context"]["shown_evidence"][0]["parse_revision"] = "old_revision"
        self.assertFalse(score_case(CASES[0], r)["exact_all_targets_hit_shown"])

    def test_shown_without_returned_identity_does_not_hit(self):
        r = report(CASES[0])
        r["result"]["search"]["results"] = []
        self.assertFalse(score_case(CASES[0], r)["exact_all_targets_hit_shown"])

    def test_quote_missing_pdf_sha_is_not_eligible_hit(self):
        case = deepcopy(CASES[0])
        del case["expected_evidence"][0]["pdf_sha256"]
        s = score_case(case, report(case))
        self.assertFalse(s["exact_all_targets_hit_returned"])
        self.assertFalse(s["exact_all_targets_hit_shown"])

    def test_quote_case_and_ligature_not_normalized(self):
        r = report(CASES[0])
        r["result"]["search"]["results"][0]["text"] = "target quote"
        self.assertFalse(score_case(CASES[0], r)["exact_all_targets_hit_returned"])

    def test_returned_but_omitted_separated(self):
        r = report(CASES[0])
        r["result"]["context"]["shown_evidence"] = []
        s = score_case(CASES[0], r)
        self.assertTrue(s["exact_all_targets_hit_returned"])
        self.assertFalse(s["exact_all_targets_hit_shown"])

    def test_answered_not_semantic_accuracy(self):
        s = score_case(CASES[0], report(CASES[0]))
        self.assertTrue(s["program_answered_completion"])
        self.assertIsNone(s["qa_accuracy"])
        self.assertEqual(s["semantic_support_status"], "not_reviewed")

    def test_answerable_refusal_not_correct_negative(self):
        s = score_case(CASES[2], report(CASES[2], "insufficient_evidence"))
        self.assertTrue(s["answerable"])
        self.assertTrue(s["answerable_refusal"])
        self.assertFalse(s["program_negative_refusal"])

    def test_unanswerable_program_refusal_requires_semantic_review(self):
        s = score_case(CASES[3], report(CASES[3], "insufficient_evidence"))
        self.assertTrue(s["program_negative_refusal"])
        self.assertIsNone(s["correct_refusal_semantic"])
        self.assertIsNone(s["exact_all_targets_hit_shown"])

    def test_denominators_negative_excluded_no_cite_ratio_none(self):
        scores = [score_case(CASES[0], report(CASES[0], "insufficient_evidence")),
                  score_case(CASES[3], report(CASES[3], "insufficient_evidence"))]
        summary = summarize_case_scores(scores, CASES)
        self.assertEqual(summary["exact_all_targets_hit_shown"]["denominator"], 1)
        self.assertEqual(summary["program_answered_completion"]["denominator"], 1)
        self.assertEqual(summary["program_negative_refusal"]["denominator"], 1)
        self.assertIsNone(summary["citation_location"]["ratio"])
        self.assertEqual(summary["planned_answerable_count"], 3)

    def test_missing_usage_never_imputed_zero(self):
        r = report(CASES[0])
        r["embedding_statistics"]["total_tokens"] = None
        r["chat_statistics"].update(total_tokens=None, known_total_tokens=8)
        scores = [score_case(CASES[0], r), score_case(CASES[1], report(CASES[1]))]
        summary = summarize_case_scores(scores)
        self.assertIsNone(summary["tokens"]["embedding"]["total"])
        self.assertEqual(summary["tokens"]["embedding"]["known_total"], 7)
        self.assertEqual(summary["tokens"]["chat"]["missing_records"], 1)
        self.assertEqual(summary["tokens"]["known_chat"]["total"], 28)

    def test_intercepts_and_final_citations_separated(self):
        r = report(CASES[0])
        r["result"]["citation_checks"].insert(0, {"checks": [{"status": "invalid_output", "code": "citation_not_shown"}]})
        r["result"]["generation"]["generation_attempts"] = [{"parse_error_code": "invalid_json"}]
        s = score_case(CASES[0], r)
        self.assertEqual(s["raw_citation_intercepts"], 1)
        self.assertEqual(s["raw_parse_intercepts"], 1)
        self.assertEqual(s["citation_location"]["numerator"], 2)

    def test_multiple_target_all_vs_quote_denominator(self):
        case = deepcopy(CASES[0])
        case["expected_evidence"].append({"paper_id": "arxiv_2005.11401v4", "pdf_sha256": "pdf", "pdf_page": 2, "quote": "missing"})
        s = score_case(case, report(case))
        summary = summarize_case_scores([s])
        self.assertFalse(s["exact_all_targets_hit_shown"])
        self.assertEqual(summary["exact_quote_hit_shown"], {"numerator": 1, "denominator": 2, "ratio": .5})

    def test_source_inputs_unchanged_by_score(self):
        case, r = deepcopy(CASES[0]), report(CASES[0])
        before = json.dumps([case, r], sort_keys=True)
        score_case(case, r)
        self.assertEqual(json.dumps([case, r], sort_keys=True), before)

    def test_retry_repair_and_sdk_totals_preserved(self):
        r = report(CASES[0])
        r["chat_statistics"].update(sdk_request_attempts=3, network_retries=1, repairs=1)
        r["llm_requests"] = 3
        summary = summarize_case_scores([score_case(CASES[0], r)])
        self.assertEqual(summary["requests"]["chat_sdk"]["total"], 3)
        self.assertEqual(summary["requests"]["chat_http"]["total"], 3)
        self.assertEqual(summary["retries_and_repairs"]["network_retries"]["total"], 1)
        self.assertEqual(summary["retries_and_repairs"]["repairs"]["total"], 1)

    def test_retry_repair_missing_stays_unknown(self):
        s = score_case(CASES[0], None)
        summary = summarize_case_scores([s])
        self.assertIsNone(summary["retries_and_repairs"]["repairs"]["total"])
        self.assertEqual(summary["retries_and_repairs"]["repairs"]["missing_records"], 1)
        self.assertIsNone(summary["requests"]["chat_sdk"]["total"])

    def test_empty_summary_ratios_none(self):
        summary = summarize_case_scores([], CASES)
        self.assertIsNone(summary["program_answered_completion"]["ratio"])
        self.assertIsNone(summary["exact_quote_hit_shown"]["ratio"])


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
