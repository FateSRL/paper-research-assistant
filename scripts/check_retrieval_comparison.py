"""D6 检索入口的离线边界检查；临时根目录和 mock，不发真实请求。"""

from contextlib import ExitStack, redirect_stderr
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from paper_assistant.search import SearchError
from scripts import run_retrieval_comparison as runner


PAIR = {"paper_id": "paper.1", "parse_revision": "revision_1"}
PDF_SHA = "a" * 64


def case(case_id="TEST-001", answerable=True):
    return {"case_id": case_id, "split": "dev", "review_status": "human_verified",
            "question": "Original question with no secret expected answer.", "paper_ids": [PAIR["paper_id"]],
            "answerable": answerable, "expected_points": ["Secret expected answer never enters retrieval."],
            "expected_evidence": [{"paper_id": PAIR["paper_id"], "pdf_sha256": PDF_SHA,
                                   "pdf_page": 1, "quote": "target_eighteen"}] if answerable else []}


def search(question=None, count=20):
    rows = []
    for rank in range(1, count + 1):
        text = ("target_eighteen " if rank == 18 else "evidence ") + "x" * 491
        rows.append({"chunk_id": f"chunk_{rank}", **PAIR, "rank": rank,
                     "score": 1.0 - rank / 100, "pdf_page": 1,
                     "pdf_sha256": PDF_SHA, "text": text,
                     "text_sha256": hashlib.sha256(text.encode()).hexdigest()})
    return {"query": question or case()["question"], "selected_versions": [deepcopy(PAIR)],
            "status": "success" if rows else "no_hits", "top_k": 20,
            "results": rows, "returned_count": len(rows),
            "statistics": {"embedding_requests": 1, "total_tokens": 7, "failed_requests": 0}}


def temp_root(path, cases=None):
    root = Path(path)
    for name in runner.SOURCES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("mock_source\n", encoding="utf-8")
    (root / "eval").mkdir()
    (root / "eval/dev.jsonl").write_text("\n".join(json.dumps(c) for c in (cases or [case()])) + "\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs/mock.md").write_text("stable documentation\n", encoding="utf-8")
    return root


class FakeSearcher:
    def __init__(self, operation=None):
        self.calls = []
        self.operation = operation

    def search_evidence(self, question, pairs, top_k):
        self.calls.append((question, deepcopy(pairs), top_k))
        return self.operation() if self.operation else search(question)


class RetrievalChecks(unittest.TestCase):
    def test_same_search_prefix_and_display_budget(self):
        original = search()
        frozen = deepcopy(original)
        comparisons = runner.compare_search(case(), original)
        self.assertEqual(original, frozen)
        self.assertEqual([len(comparisons[str(k)]["search"]["results"]) for k in (5, 10, 20)], [5, 10, 20])
        self.assertFalse(comparisons["5"]["score"]["exact_all_targets_hit_returned"])
        self.assertTrue(comparisons["20"]["score"]["exact_all_targets_hit_returned"])
        self.assertFalse(comparisons["20"]["score"]["exact_all_targets_hit_shown"])
        self.assertLessEqual(comparisons["20"]["context"]["shown_chars"], 8000)
        self.assertNotIn("chunk_18", comparisons["20"]["context"]["allowed_citation_ids"])

    def test_empty_and_negative_have_no_false_accuracy(self):
        comparisons = runner.compare_search(case(answerable=False), search(count=0))
        summary = runner.summarize([{"case_id": "TEST-001", "status": "completed", "answerable": False,
                                     "expected_target_count": 0, "comparisons": comparisons}], 20)
        self.assertEqual(summary["negative_case_count"], 1)
        self.assertEqual(summary["exact_all_targets_hit_returned"]["denominator"], 0)
        self.assertIsNone(summary["exact_all_targets_hit_shown"]["ratio"])
        self.assertIsNone(summary["qa_accuracy"])

    def test_rank_gap_and_invalid_text_hash_fail(self):
        bad = search()
        bad["results"][3]["rank"] = 99
        with self.assertRaises(ValueError):
            runner.compare_search(case(), bad)
        bad = search()
        bad["results"][-1]["text_sha256"] = "invalid"
        with self.assertRaises(ValueError):
            runner.compare_search(case(), bad)

    def test_quote_page_and_pdf_identity_required(self):
        baseline = runner.compare_search(case(), search())["20"]["score"]
        self.assertTrue(baseline["exact_all_targets_hit_returned"])
        for key, value in (("pdf_sha256", "b" * 64), ("pdf_page", 2)):
            changed = search()
            changed["results"][17][key] = value
            self.assertFalse(runner.compare_search(case(), changed)["20"]["score"]["exact_all_targets_hit_returned"])

    def test_success_and_failure_both_remain_in_target_denominators(self):
        successful = case()
        successful["expected_evidence"][0]["quote"] = "evidence"
        comparisons = runner.compare_search(successful, search())
        records = [{"case_id": successful["case_id"], "status": "completed", "answerable": True,
                    "expected_target_count": 1, "comparisons": comparisons},
                   {"case_id": "TEST-FAILED", "status": "tool_error", "answerable": True,
                    "expected_target_count": 2, "comparisons": {}}]
        for k in (5, 10, 20):
            summary = runner.summarize(records, k)
            self.assertEqual(summary["attempted_count"], 2)
            self.assertEqual(summary["scored_count"], 1)
            self.assertEqual(summary["failed_attempted_count"], 1)
            for scope in ("returned", "shown"):
                self.assertEqual(summary[f"exact_all_targets_hit_{scope}"],
                                 {"numerator": 1, "denominator": 2, "ratio": 0.5})
                self.assertEqual(summary[f"exact_quote_hit_{scope}"],
                                 {"numerator": 1, "denominator": 3, "ratio": 1 / 3})

    def test_live_once_no_annotation_input_existing_batch_refused(self):
        with TemporaryDirectory(prefix="d6_retrieval_check_") as folder:
            root = temp_root(folder)
            spy, factory_calls, cleaned = FakeSearcher(), [], []
            def factory(path, chosen):
                factory_calls.append(True)
                stack = ExitStack()
                stack.callback(lambda: cleaned.append(True))
                return stack, spy, {PAIR["paper_id"]: PAIR["parse_revision"]}, {"mock_profile": True}
            summary = runner.run_batch("once", live=True, root=root, live_factory=factory)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(spy.calls, [(case()["question"], [(PAIR["paper_id"], PAIR["parse_revision"])], 20)])
            self.assertEqual(summary["new_usage"]["embedding_requests"], 1)
            self.assertEqual(summary["new_usage"]["embedding_tokens"], 7)
            self.assertEqual(summary["new_usage"]["llm_requests"], 0)
            self.assertEqual(cleaned, [True])
            with self.assertRaises(FileExistsError):
                runner.run_batch("once", live=True, root=root, live_factory=factory)
            self.assertEqual(factory_calls, [True])
            batch = root / "artifacts/d6/retrieval_comparison/once"
            self.assertTrue((batch / "reservations/TEST-001.json").is_file())
            manifest = runner.read_json(batch / "manifest.json")
            self.assertEqual(manifest["input_binding_sha256"], runner.digest(manifest["input_binding"]))
            self.assertEqual(manifest["results"]["TEST-001"]["sha256"], runner.sha(batch / "results/TEST-001.json"))

    def test_failed_request_usage_preserved_no_next_case(self):
        with TemporaryDirectory(prefix="d6_retrieval_check_") as folder:
            root = temp_root(folder, [case(), case("TEST-002")])
            def failure():
                raise SearchError("safe simulated failure", stage="embedding", statistics={"embedding_requests": 1, "failed_requests": 1, "total_tokens": None})
            spy = FakeSearcher(failure)
            summary = runner.run_batch("failed", live=True, root=root,
                                       live_factory=lambda r, c: (ExitStack(), spy, {PAIR["paper_id"]: PAIR["parse_revision"]}, {}))
            self.assertEqual(len(spy.calls), 1)
            self.assertEqual(summary["status"], "needs_attention")
            self.assertEqual(summary["new_usage"]["embedding_requests"], 1)
            self.assertIsNone(summary["new_usage"]["embedding_tokens"])
            manifest = runner.read_json(root / "artifacts/d6/retrieval_comparison/failed/manifest.json")
            self.assertEqual(manifest["unattempted_case_ids"], ["TEST-002"])
            self.assertEqual(manifest["completed_case_ids"], [])

    def test_unknown_failure_usage_stays_null(self):
        with TemporaryDirectory(prefix="d6_retrieval_check_") as folder:
            root = temp_root(folder)
            def failure():
                raise RuntimeError("untrusted exception must never be recorded")
            spy = FakeSearcher(failure)
            summary = runner.run_batch("unknown", live=True, root=root,
                                       live_factory=lambda r, c: (ExitStack(), spy, {PAIR["paper_id"]: PAIR["parse_revision"]}, {}))
            self.assertIsNone(summary["new_usage"]["embedding_requests"])
            self.assertEqual(summary["new_usage"]["unknown_request_records"], 1)
            text = (root / "artifacts/d6/retrieval_comparison/unknown/results/TEST-001.json").read_text(encoding="utf-8")
            self.assertNotIn("untrusted exception", text)

    def test_input_mutation_preserves_result_and_flags_attention(self):
        with TemporaryDirectory(prefix="d6_retrieval_check_") as folder:
            root = temp_root(folder)
            def mutate():
                (root / "docs/mock.md").write_text("changed", encoding="utf-8")
                return search()
            summary = runner.run_batch("mutation", live=True, root=root,
                                       live_factory=lambda r, c: (ExitStack(), FakeSearcher(mutate), {PAIR["paper_id"]: PAIR["parse_revision"]}, {}))
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["new_usage"]["embedding_requests"], 1)

    def test_cleanup_failure_preserves_usage(self):
        with TemporaryDirectory(prefix="d6_retrieval_check_") as folder:
            root = temp_root(folder)
            def factory(r, c):
                stack = ExitStack()
                def bad_cleanup():
                    raise RuntimeError("simulated cleanup failure")
                stack.callback(bad_cleanup)
                return stack, FakeSearcher(), {PAIR["paper_id"]: PAIR["parse_revision"]}, {}
            summary = runner.run_batch("cleanup", live=True, root=root, live_factory=factory)
            self.assertEqual(summary["status"], "needs_attention")
            self.assertEqual(summary["new_usage"]["embedding_requests"], 1)
            self.assertEqual(summary["new_usage"]["embedding_tokens"], 7)

    def test_disk_failure_retains_full_in_memory_usage(self):
        with TemporaryDirectory(prefix="d6_retrieval_check_") as folder:
            root = temp_root(folder)
            spy = FakeSearcher()
            with patch.object(runner, "atomic_json", side_effect=OSError("mock disk failure")):
                with self.assertRaises(runner.BatchExportError) as caught:
                    runner.run_batch("disk_failure", live=True, root=root,
                                     live_factory=lambda r, c: (ExitStack(), spy, {PAIR["paper_id"]: PAIR["parse_revision"]}, {}))
            payload = caught.exception.payload
            self.assertEqual(len(spy.calls), 1)
            self.assertEqual(payload["new_usage"]["embedding_requests"], 1)
            self.assertEqual(payload["new_usage"]["embedding_tokens"], 7)
            self.assertEqual(payload["records"][0]["comparisons"]["20"]["search"]["returned_count"], 20)
            self.assertNotIn("mock disk failure", json.dumps(payload))

    def test_invalid_selection_or_acceptance_split_no_outputs(self):
        with TemporaryDirectory(prefix="d6_retrieval_check_") as folder:
            root = temp_root(folder)
            for ids in (["TEST-001", "TEST-001"], ["unknown"]):
                with self.assertRaises(ValueError):
                    runner.run_batch("invalid", live=True, case_ids=ids, root=root)
            changed = case()
            changed["split"] = "acceptance"
            (root / "eval/dev.jsonl").write_text(json.dumps(changed) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                runner.run_batch("invalid", live=True, root=root)
            self.assertFalse((root / "artifacts").exists())

    def test_cli_mode_required_and_no_resume(self):
        with redirect_stderr(io.StringIO()):
            for args in (["--batch-id", "x"], ["--from-first-runs", "--live", "--batch-id", "x"],
                         ["--from-first-runs", "--batch-id", "x", "--case-id", "TEST-001"],
                         ["--live", "--batch-id", "../unsafe"], ["--live", "--batch-id", "x", "--resume"]):
                with self.assertRaises(SystemExit):
                    runner.parse_args(args)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
