"""D6 D new UI/runtime checks, isolated from historical D5 checks.

Run: python -X utf8 -m scripts.check_web_app
Temporary project roots and resource doubles are used throughout. AppTest is
Streamlit's serverless component harness, not a real browser or answer review.
No .env is read and external socket/HTTP sends are forbidden. Windows asyncio
uses a local socketpair for AppTest; only that loopback transport is permitted.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
import streamlit
from streamlit.testing.v1 import AppTest

from paper_assistant import web_runtime as target
from paper_assistant.config import LLMSettings
from paper_assistant.llm_client import ChatBudget, ChatPolicy


ROOT = Path(__file__).resolve().parents[1]
SECRET = "offline-web-secret-must-never-appear"
EVIDENCE = "Exact shown evidence with `backticks`, <tags> and a second line.\nORIGINAL-SOURCE-MARKER"
PAIR = ("p1", "r1")
PROFILE = {"index_profile_id": "offline-profile", "collection_name": "offline-collection",
           "recipe": {"dimension": 2, "backend": "local", "model": "offline", "base_url": None}}
READY = [{"paper_id": "p1", "parse_revision": "r1", "title": "Offline one", "chunk_count": 1},
         {"paper_id": "p2", "parse_revision": "r2", "title": "Offline two", "chunk_count": 1}]
COUNTS = {"mock_core_calls": 0, "mock_ui_submissions": 0, "real_api_calls": 0}
FIVE_STATE_EXAMPLES = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_row():
    return {"chunk_id": "p1_r1_p2_c1", "paper_id": "p1", "parse_revision": "r1",
            "pdf_page": 2, "title": "Offline paper", "arxiv_version": "v1",
            "pdf_absolute_path": str(ROOT / "offline-unused.pdf"), "text": EVIDENCE,
            "shown_text": EVIDENCE, "rank": 1, "score": 0.8}


def core_result(status="answered"):
    answer = ({"status": status, "claims": [{"claim": "Supported fixture claim.",
               "citation_ids": [source_row()["chunk_id"]]}], "evidence_sources": [source_row()],
               "reason": None} if status == "answered" else
              {"status": status, "claims": [], "evidence_sources": [],
               "reason": "Fixture evidence does not report the requested quantity."}
              if status == "insufficient_evidence" else None)
    error = None if answer is not None else {"code": "fixture_failure", "message": "Safe fixture failure"}
    return {"status": status, "answer": answer, "error": error,
            "failure_stage": None if answer else "generation",
            "search": {"returned_evidence": [source_row()]},
            "context": {"shown_evidence": [source_row()], "shown_chars": len(EVIDENCE)},
            "generation": {"generation_attempts": [{"response": {"content": "fixture-raw-response"}}]},
            "statistics": {"embedding": {"embedding_requests": 1, "total_tokens": 7}}}


def ui_report(status="answered"):
    result = core_result(status)
    return {"task": "D6-D-web-answer-question", "run_id": "fixture-run", "query": "Fixture question?",
            "status": status, "selected_versions": [{"paper_id": "p1", "parse_revision": "r1"}],
            "answer": deepcopy(result["answer"]), "result": result, "error": deepcopy(result["error"]),
            "embedding_requests": 1, "llm_requests": 1, "network_requests": 2,
            "embedding_statistics": {"total_tokens": 7},
            "chat_statistics": {"total_tokens": None, "known_total_tokens": 0,
                                "network_retries": 0, "repairs": 0},
            "history_report": "archive/run_logs/d6/web_answer_fixture-run.json",
            "export": {"status": "prepared"}, "is_answer_accuracy": False}


class Resource:
    def __init__(self, fail_close=False):
        self.closed = False
        self.fail_close = fail_close

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError(SECRET)


class FakeStore(Resource):
    def list_versions(self):
        return deepcopy(READY)

    def list_index_imports(self, **_):
        return [{"paper_id": row["paper_id"], "parse_revision": row["parse_revision"],
                 "status": "ready", "index_profile_id": PROFILE["index_profile_id"],
                 "chunk_count": 1, "expected_chunk_count": 1, "completed_count": 1}
                for row in READY]


class FakeQdrant(Resource):
    def collection_exists(self, _):
        return True


class FakeChat(Resource):
    def __init__(self, budget, fail_close=False):
        super().__init__(fail_close)
        self.budget = budget


class RuntimeChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="d6-web-offline-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in target.SOURCES:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / name).read_bytes())
        for name in ("data/index/qdrant/meta.json", "data/index/papers.sqlite3", "data/chunks/fake.json",
                     "eval/dev.jsonl", "eval/acceptance.jsonl", "artifacts/d5/answer_result.json",
                     "archive/run_logs/d5/answer_old.json"):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"historical-or-fixture-data\n")

    def inventory(self):
        return {p.relative_to(self.root).as_posix(): sha(p) for p in self.root.rglob("*") if p.is_file()}

    def run_fixture(self, status="answered", *, query="Question?", pairs=None,
                    close_fault=None, construction_fault=None, config_fault=False,
                    core_fault=False, export_fault=None, mutate_input=False):
        store = FakeStore(close_fault == "store")
        qdrant = FakeQdrant(close_fault == "qdrant")
        vectors = Resource(close_fault == "vectors")
        searcher = SimpleNamespace()
        budgets, clients = [], []
        constructors = {}

        def budget_factory(policy):
            budget = ChatBudget(policy)
            budgets.append(budget)
            return budget

        def chat_factory(settings, *, policy, budget):
            client = FakeChat(budget, close_fault == "chat")
            clients.append(client)
            return client

        def pipeline(*args, **kwargs):
            COUNTS["mock_core_calls"] += 1
            client = args[4]
            client.budget.reserve(retry=False, repair_start=False)
            client.budget.http_requests += 1
            client.budget.records.append({"number": 1, "usage": None, "status": "answered"})
            if mutate_input:
                (self.root / "data/chunks/fake.json").write_bytes(b"mutated-input")
            if core_fault:
                raise RuntimeError(SECRET)
            return core_result(status)

        with ExitStack() as stack:
            stack.enter_context(patch.object(target, "_load_current_profile", return_value=deepcopy(PROFILE)))
            stack.enter_context(patch.object(target, "_ready_versions", return_value=deepcopy(READY)))
            stack.enter_context(patch.object(target, "make_index_profile", return_value=deepcopy(PROFILE)))
            embedding_config = stack.enter_context(patch.object(target, "load_embedding_settings",
                return_value=SimpleNamespace(), side_effect=RuntimeError(SECRET) if config_fault else None))
            stack.enter_context(patch.object(target, "load_llm_settings", return_value=LLMSettings(
                provider="deepseek", model_id="offline", api_key=SECRET,
                base_url="https://example.invalid/v1", timeout=30)))
            stack.enter_context(patch.object(target, "ChatBudget", side_effect=budget_factory))
            for name, resource in (("PaperStore", store), ("QdrantClient", qdrant),
                                   ("QdrantStore", vectors), ("EvidenceSearcher", searcher)):
                constructors[name] = stack.enter_context(patch.object(target, name, return_value=resource,
                    side_effect=RuntimeError(SECRET) if construction_fault == name else None))
            constructors["RecordedLLM"] = stack.enter_context(patch.object(target, "RecordedLLM", side_effect=
                RuntimeError(SECRET) if construction_fault == "RecordedLLM" else chat_factory))
            core = stack.enter_context(patch.object(target, "answer_question", side_effect=pipeline))
            if export_fault:
                helper, substring = export_fault
                original = getattr(target, helper)

                def failed_export(path, value):
                    if substring in str(path):
                        raise OSError(SECRET)
                    return original(path, value)

                stack.enter_context(patch.object(target, helper, side_effect=failed_export))
            report = target.run_question(query, [PAIR] if pairs is None else pairs, project_root=self.root)
        self.assertNotIn(SECRET, json.dumps(report, ensure_ascii=False))
        return SimpleNamespace(report=report, store=store, qdrant=qdrant, vectors=vectors,
            clients=clients, budgets=budgets, constructors=constructors, core=core,
            embedding_config=embedding_config)

    def test_submit_uses_fixed_core_once_and_one_borrowed_qdrant(self):
        s = self.run_fixture()
        self.assertEqual(s.report["status"], "answered")
        self.assertEqual(s.core.call_count, 1)
        self.assertEqual(s.constructors["QdrantClient"].call_count, 1)
        self.assertIs(s.constructors["QdrantStore"].call_args.kwargs["client"], s.qdrant)
        self.assertEqual(s.core.call_args.args[:2], ("Question?", [PAIR]))
        self.assertEqual(s.core.call_args.kwargs["top_k"], 5)
        self.assertEqual(s.core.call_args.kwargs["max_chars"], 8000)
        self.assertTrue(all(r.closed for r in (s.store, s.qdrant, s.vectors, *s.clients)))

    def test_each_question_has_new_budget_clients_and_exclusive_history(self):
        a, b = self.run_fixture(), self.run_fixture()
        self.assertIsNot(a.budgets[0], b.budgets[0])
        self.assertIsNot(a.clients[0], b.clients[0])
        self.assertNotEqual(a.report["run_id"], b.report["run_id"])
        for s in (a, b):
            saved = json.loads((self.root / s.report["history_report"]).read_text(encoding="utf-8"))
            self.assertEqual(saved, s.report)

    def test_same_history_destination_is_exclusive_and_recovery_preserves_costs(self):
        s = self.run_fixture()
        history = self.root / s.report["history_report"]
        previous = history.read_bytes()
        repeated = deepcopy(s.report)
        self.assertFalse(target._save_report(repeated, self.root))
        self.assertEqual(history.read_bytes(), previous)
        self.assertEqual(repeated["status"], "tool_error")
        self.assertEqual(repeated["export"]["failed_step"], "history_json")
        self.assertEqual(repeated["network_requests"], 2)
        recovery = self.root / repeated["export"]["recovery_history_report"]
        self.assertEqual(json.loads(recovery.read_text(encoding="utf-8")), repeated)

    def test_list_ready_versions_is_read_only_without_config_or_qdrant(self):
        store = FakeStore()
        before = self.inventory()
        with ExitStack() as stack:
            stack.enter_context(patch.object(target, "_load_current_profile", return_value=PROFILE))
            stack.enter_context(patch.object(target, "_ready_versions", return_value=READY))
            factory = stack.enter_context(patch.object(target, "PaperStore", return_value=store))
            config = stack.enter_context(patch.object(target, "load_embedding_settings"))
            qdrant = stack.enter_context(patch.object(target, "QdrantClient"))
            actual = target.list_ready_versions(project_root=self.root)
        self.assertEqual(actual, READY)
        self.assertEqual(factory.call_args.kwargs["read_only"], True)
        self.assertEqual(config.call_count, 0)
        self.assertEqual(qdrant.call_count, 0)
        self.assertTrue(store.closed)
        self.assertEqual(before, self.inventory())

    def test_five_core_statuses_pass_through_without_extra_core_calls(self):
        for status in ("answered", "insufficient_evidence", "tool_error", "invalid_output", "budget_exceeded"):
            with self.subTest(status=status):
                s = self.run_fixture(status)
                self.assertEqual(s.report["status"], status)
                self.assertEqual(s.core.call_count, 1)
                self.assertEqual(s.report["result"]["status"], status)

    def test_empty_question_and_malformed_pairs_do_not_read_config_write_or_call(self):
        cases = [("  ", [PAIR]), ("q", []), ("q", [PAIR, PAIR]), ("q", [("p1",)]),
                 ("q", [(" p1", "r1")]), ("q", [("p", "r")] * 4)]
        before = self.inventory()
        for query, pairs in cases:
            with self.subTest(query=query, pairs=pairs):
                with self.assertRaises(ValueError):
                    self.run_fixture(query=query, pairs=pairs)
        self.assertEqual(before, self.inventory())

    def test_unready_selection_never_calls_config_core_or_writes(self):
        before = self.inventory()
        with ExitStack() as stack:
            stack.enter_context(patch.object(target, "_load_current_profile", return_value=PROFILE))
            stack.enter_context(patch.object(target, "_ready_versions", return_value=READY))
            store = FakeStore()
            stack.enter_context(patch.object(target, "PaperStore", return_value=store))
            config = stack.enter_context(patch.object(target, "load_embedding_settings"))
            core = stack.enter_context(patch.object(target, "answer_question"))
            with self.assertRaises(ValueError):
                target.run_question("Question?", [("unknown", "r9")], project_root=self.root)
        self.assertEqual(config.call_count, 0)
        self.assertEqual(core.call_count, 0)
        self.assertTrue(store.closed)
        self.assertEqual(before, self.inventory())

    def test_configuration_failure_has_no_core_qdrant_or_chat_and_safe_message(self):
        s = self.run_fixture(config_fault=True)
        self.assertEqual(s.report["status"], "tool_error")
        self.assertEqual(s.core.call_count, 0)
        self.assertEqual(s.constructors["QdrantClient"].call_count, 0)
        self.assertEqual(s.constructors["RecordedLLM"].call_count, 0)
        self.assertEqual(s.report["network_requests"], 0)
        self.assertTrue(s.store.closed)

    def test_partial_construction_failure_closes_already_owned_resources(self):
        for constructor, expected in (("QdrantStore", ["store", "qdrant"]),
                                      ("RecordedLLM", ["store", "qdrant", "vectors"])):
            with self.subTest(constructor=constructor):
                s = self.run_fixture(construction_fault=constructor)
                self.assertEqual(s.report["status"], "tool_error")
                self.assertEqual(s.core.call_count, 0)
                self.assertTrue(all(getattr(s, name).closed for name in expected))

    def test_core_exception_preserves_known_chat_usage_and_unknown_embedding(self):
        s = self.run_fixture(core_fault=True)
        self.assertEqual(s.report["status"], "tool_error")
        self.assertIsNone(s.report["embedding_requests"])
        self.assertIsNone(s.report["network_requests"])
        self.assertEqual(s.report["llm_requests"], 1)
        self.assertEqual(len(s.report["chat_attempts"]), 1)
        self.assertIsNone(s.report["chat_statistics"]["total_tokens"])
        self.assertTrue(all(r.closed for r in (s.store, s.qdrant, s.vectors, *s.clients)))

    def test_cleanup_failures_preserve_raw_core_and_costs_but_clear_public_answer(self):
        for resource in ("store", "qdrant", "vectors", "chat"):
            with self.subTest(resource=resource):
                s = self.run_fixture(close_fault=resource)
                self.assertEqual(s.report["status"], "tool_error")
                self.assertIsNone(s.report["answer"])
                self.assertEqual(s.report["result"]["status"], "answered")
                self.assertEqual(s.report["result"]["generation"]["generation_attempts"][0]
                                 ["response"]["content"], "fixture-raw-response")
                self.assertEqual(s.report["embedding_requests"], 1)
                self.assertEqual(s.report["llm_requests"], 1)
                self.assertTrue(all(r.closed for r in (s.store, s.qdrant, s.vectors, *s.clients)))

    def test_export_failure_does_not_retry_question_or_lose_costs(self):
        s = self.run_fixture(export_fault=("atomic_text", "web_answer_result.md"))
        self.assertEqual(s.report["status"], "tool_error")
        self.assertEqual(s.report["export"]["status"], "failed")
        self.assertEqual(s.core.call_count, 1)
        self.assertEqual(s.report["network_requests"], 2)
        self.assertEqual(s.report["result"]["status"], "answered")
        recovery = self.root / s.report["export"]["recovery_history_report"]
        self.assertEqual(json.loads(recovery.read_text(encoding="utf-8")), s.report)

    def test_existing_d5_latest_history_and_formal_inputs_are_unchanged(self):
        before = self.inventory()
        self.run_fixture()
        after = self.inventory()
        for name, digest in before.items():
            self.assertEqual(after[name], digest, name)
        added = [name for name in after if name not in before]
        self.assertTrue(added)
        self.assertTrue(all(name.startswith(("artifacts/d6/", "archive/run_logs/d6/")) for name in added))

    def test_unrelated_input_mutation_does_not_discard_answer_or_costs(self):
        s = self.run_fixture(mutate_input=True)
        self.assertEqual(s.report["status"], "answered")
        self.assertNotIn("protected_files", s.report)
        self.assertEqual(s.report["network_requests"], 2)

    def test_download_is_read_only_uses_this_report_and_d6_history(self):
        s = self.run_fixture()
        before = self.inventory()
        with patch.object(target, "answer_question") as core, patch.object(target, "load_embedding_settings") as config:
            machine, readable = target.download_payloads(s.report, project_root=self.root)
        self.assertEqual(json.loads(machine), s.report)
        self.assertIn(s.report["run_id"], readable.decode("utf-8"))
        self.assertIn(s.report["history_report"], readable.decode("utf-8"))
        self.assertNotIn("artifacts/d5/answer_result", readable.decode("utf-8"))
        self.assertEqual(core.call_count, 0)
        self.assertEqual(config.call_count, 0)
        self.assertEqual(before, self.inventory())

    def test_download_preserves_unknown_usage_as_null_and_original_evidence(self):
        report = ui_report()
        machine, readable = target.download_payloads(report, project_root=self.root)
        self.assertIsNone(json.loads(machine)["chat_statistics"]["total_tokens"])
        self.assertIn(EVIDENCE, readable.decode("utf-8"))
        self.assertIn("null", readable.decode("utf-8"))


class PageChecks(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(target, "list_ready_versions", return_value=deepcopy(READY)))
        self.core = self.stack.enter_context(patch.object(target, "run_question", return_value=ui_report()))
        self.download = self.stack.enter_context(patch.object(target, "download_payloads",
            return_value=(b'{"fixture":true}', b"Fixture Markdown")))

    def app(self):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()
        self.assertFalse(app.exception)
        return app

    def values(self, app, name):
        return "\n".join(str(item.value) for item in getattr(app, name))

    def capture_example(self, app, status):
        """Retain text from the actual AppTest tree after assertions, not hand-written UI output."""
        FIVE_STATE_EXAMPLES[status] = {
            "status": status, "question": app.session_state["current_report"]["query"],
            "actual_rendered_elements": {
                kind: [str(item.value) for item in getattr(app, kind)]
                for kind in ("title", "subheader", "success", "warning", "error", "info", "text", "caption", "code", "markdown")
            },
            "expander_labels": [str(item.label) for item in app.get("expander")],
            "mock_runtime_submissions_so_far_in_this_test": self.core.call_count,
            "runtime_fixture_report": deepcopy(app.session_state["current_report"]),
            "exception_count": len(app.exception),
        }

    def submit(self, app, question="Fixture question?"):
        app.text_area[0].set_value(question)
        app.multiselect[0].set_value([PAIR])
        app.button[0].click().run()
        COUNTS["mock_ui_submissions"] += 1
        self.assertFalse(app.exception)
        return app

    def test_initial_page_and_manual_reruns_never_submit(self):
        app = self.app()
        app.run()
        app.run()
        self.assertEqual(self.core.call_count, 0)

    def test_submit_once_then_rerun_and_option_change_do_not_resubmit(self):
        app = self.submit(self.app())
        self.assertEqual(self.core.call_count, 1)
        self.assertEqual(self.core.call_args.args[0], "Fixture question?")
        app.run()
        app.multiselect[0].set_value([PAIR, ("p2", "r2")]).run()
        self.assertEqual(self.core.call_count, 1)
        self.assertIn("Supported fixture claim.", self.values(app, "text"))

    def test_blank_question_and_empty_selection_do_not_call_runtime(self):
        app = self.app()
        app.text_area[0].set_value("  ")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.core.call_count, 0)
        app.text_area[0].set_value("q")
        app.multiselect[0].set_value([])
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.core.call_count, 0)

    def test_answered_page_has_claim_citation_original_and_file_page(self):
        app = self.submit(self.app())
        text = self.values(app, "text") + self.values(app, "caption") + self.values(app, "code")
        self.assertIn("Supported fixture claim.", text)
        self.assertIn(source_row()["chunk_id"], text)
        self.assertIn(EVIDENCE, text)
        self.assertIn("2", text)
        self.capture_example(app, "answered")

    def test_insufficient_page_shows_reason_and_actual_shown_original(self):
        self.core.return_value = ui_report("insufficient_evidence")
        app = self.submit(self.app())
        text = self.values(app, "text") + self.values(app, "caption") + self.values(app, "code")
        self.assertIn("Fixture evidence does not report the requested quantity.", text)
        self.assertIn(EVIDENCE, text)
        self.assertTrue(app.warning or app.info)
        self.capture_example(app, "insufficient_evidence")

    def test_three_failure_states_are_distinct_and_do_not_display_answer(self):
        texts = []
        for status in ("tool_error", "invalid_output", "budget_exceeded"):
            with self.subTest(status=status):
                self.core.return_value = ui_report(status)
                app = self.submit(self.app())
                self.assertTrue(app.error or app.warning)
                text = self.values(app, "text") + self.values(app, "error") + self.values(app, "warning")
                texts.append(text)
                self.assertNotIn("Supported fixture claim.", text)
                self.capture_example(app, status)
        self.assertEqual(len(set(texts)), 3)

    def test_downloads_render_and_rerun_without_new_question(self):
        app = self.submit(self.app())
        self.assertEqual(len(app.get("download_button")), 2)
        for button in app.get("download_button"):
            button.click().run()
            self.assertFalse(app.exception)
            self.assertEqual(self.core.call_count, 1)
        app.run()
        self.assertEqual(self.core.call_count, 1)
        self.assertGreaterEqual(self.download.call_count, 1)

    def test_runtime_exception_is_safe_and_does_not_leak_secret(self):
        self.core.side_effect = RuntimeError(SECRET)
        app = self.submit(self.app())
        self.assertEqual(self.core.call_count, 1)
        text = "\n".join(self.values(app, kind) for kind in ("markdown", "error", "warning", "caption", "code"))
        self.assertNotIn(SECRET, text)
        self.assertTrue(app.error or app.warning)
        app.run()
        self.assertEqual(self.core.call_count, 1)

    def test_invalid_question_has_safe_input_notice_without_unknown_usage_or_fake_report(self):
        self.core.side_effect = target.InvalidQuestion(SECRET)
        app = self.submit(self.app())
        self.assertEqual(self.core.call_count, 1)
        notices = self.values(app, "warning") + self.values(app, "error")
        self.assertIn("输入", notices)
        self.assertIn("无效", notices)
        self.assertNotIn("未知", notices)
        self.assertNotIn(SECRET, notices)
        self.assertNotIn("current_report", app.session_state)
        self.assertEqual(len(app.get("download_button")), 0)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(self.core.call_count, 1)

    def test_download_render_failure_keeps_json_and_does_not_resubmit(self):
        self.download.side_effect = RuntimeError(SECRET)
        app = self.submit(self.app())
        self.assertEqual(len(app.get("download_button")), 1)
        self.assertTrue(app.warning)
        self.assertNotIn(SECRET, self.values(app, "warning"))
        app.get("download_button")[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(self.core.call_count, 1)

    def test_unknown_usage_is_displayed_as_unknown_not_zero(self):
        app = self.submit(self.app())
        labels = [item.value for item in app.text]
        self.assertIn("聊天 tokens：未知", labels)
        self.assertNotIn("聊天 tokens：0", labels)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
