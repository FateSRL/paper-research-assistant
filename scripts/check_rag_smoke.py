"""D5 D：真实首题脚本的资源关闭、费用记录及输入保护离线检查。

运行：python -X utf8 -m scripts.check_rag_smoke
ROOT 为临时目录，配置、资源与 RAG 核心均替换为假对象；只执行真正的
报告写入和哈希保护，不读取 .env、不访问正式库、不发送网络请求。
"""

from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from paper_assistant.llm_client import ChatBudget
from scripts.check_llm import FakeClock
from scripts import smoke_rag as target


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OFFLINE_SECRET = "offline-rag-smoke-secret-do-not-log"
SIMULATED_RUNS = 0
SIMULATED_CORE_CALLS = 0
SIMULATED_HTTP_ATTEMPTS = 0
SOURCE_FILES = ["paper_assistant/citations.py", "paper_assistant/rag.py", "paper_assistant/context.py",
                "paper_assistant/generation.py", "paper_assistant/schemas.py", "paper_assistant/storage.py",
                "paper_assistant/llm_client.py", "paper_assistant/search.py", "scripts/search_evidence.py",
                "scripts/smoke_rag.py"]


class FakeResource:
    def __init__(self, fail_exit=False):
        self.fail_exit, self.entered, self.closed = fail_exit, False, False
        self.on_exit = None

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_):
        self.closed = True
        if self.on_exit:
            self.on_exit()
        if self.fail_exit:
            raise RuntimeError(OFFLINE_SECRET)


class FakeQdrant:
    def __init__(self, fail_close=False, collection=True):
        self.fail_close, self.closed, self.collection = fail_close, False, collection

    def collection_exists(self, _collection):
        return self.collection

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError(OFFLINE_SECRET)


class SmokeChecks(unittest.TestCase):
    def run_scenario(self, *, fail_exit=None, fail_construct=None, configuration_error=False,
                     collection=True, core_status="answered", change=None, cleanup_timeout=False,
                     verification_timeout=False):
        global SIMULATED_RUNS
        SIMULATED_RUNS += 1
        temporary = tempfile.TemporaryDirectory(prefix="d5-d-smoke-offline-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in SOURCE_FILES:
            copied = root / name
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes((PROJECT_ROOT / name).read_bytes())
        protected = ["data/index/offline.bin", "data/chunks/offline.json", "data/papers/offline.pdf", "eval/offline.json"]
        for name in protected:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"offline protected input")
        profile = {"collection_name": "offline-collection", "index_profile_id": "offline-profile",
                   "recipe": {"dimension": 2}}
        store = FakeResource(fail_exit == "sqlite")
        qdrant = FakeQdrant(fail_exit == "qdrant", collection=collection)
        vectors = FakeResource(fail_exit == "vectors")
        chat = FakeResource(fail_exit == "chat")
        budget = ChatBudget(clock=FakeClock())
        if cleanup_timeout:
            chat.on_exit = lambda: budget.clock.advance(121)
        chat.budget = budget
        searcher = SimpleNamespace(label="offline-searcher")
        expected_core = {}
        core_finished = False
        verification_clock_advanced = False
        original_read = Path.read_bytes

        def controlled_read(path):
            nonlocal verification_clock_advanced
            source = root / "paper_assistant/rag.py"
            if core_finished and path == source:
                if change == "unreadable_source":
                    raise OSError(OFFLINE_SECRET)
                if verification_timeout and not verification_clock_advanced:
                    verification_clock_advanced = True
                    budget.clock.advance(121)
            if core_finished and change == "unreadable_protected" and path == root / protected[0]:
                raise OSError(OFFLINE_SECRET)
            return original_read(path)

        def fake_core(query, versions, actual_searcher, actual_store, actual_client, *, project_root):
            nonlocal core_finished
            global SIMULATED_CORE_CALLS, SIMULATED_HTTP_ATTEMPTS
            SIMULATED_CORE_CALLS += 1
            self.assertEqual(query, target.QUESTION)
            self.assertEqual(versions, target.PAIRS)
            self.assertIs(actual_searcher, searcher)
            self.assertIs(actual_store, store)
            self.assertIs(actual_client, chat)
            self.assertEqual(project_root, root)
            budget.reserve(retry=False, repair_start=False)
            budget.http_requests += 1
            SIMULATED_HTTP_ATTEMPTS += 1
            budget.records.append({"number": 1, "purpose": "answer", "is_network_retry": False,
                                   "http_request_attempts": 1, "status": "success", "error_code": None,
                                   "http_status": 200, "usage": {"total_tokens": 25}, "finish_reason": "stop",
                                   "content": "Original raw response for forensic preservation"})
            reference = {"chunk_id": "offline-chunk", "paper_id": versions[0][0],
                         "parse_revision": versions[0][1], "pdf_page": 1}
            answer = {"status": core_status, "claims": [{"claim": "Synthetic claim", "citation_ids": ["offline-chunk"]}],
                      "evidence_refs": [reference], "semantic_support_status": "not_reviewed",
                      "evidence_sources": [{**reference, "title": "Offline paper", "arxiv_version": "v1",
                                            "pdf_absolute_path": str(root / "data/papers/offline.pdf"),
                                            "text": "Exact synthetic text with `backticks` and whitespace  ."}]}
            if core_status == "insufficient_evidence":
                answer.update(claims=[], evidence_refs=[], evidence_sources=[], reason="This run lacks evidence.")
            if core_status not in ("answered", "insufficient_evidence"):
                answer = None
            expected_core.update({"status": core_status, "answer": answer,
                                  "error": None if answer else {"code": "offline_error", "message": "Safe core failure"},
                                  "failure_stage": None if answer else "citations",
                                  "search": {"original_search": "preserved"}, "context": {"original_snapshot": "preserved"},
                                  "generation": {"generation_attempts": [{"messages": [{"role": "user", "content": "Original message"}],
                                                                            "response": {"content": "Original model output"}}]},
                                  "citation_checks": [{"status": "valid", "checks": [{"chunk_id": "offline-chunk"}]}],
                                  "citation_repairs": [{"messages": [{"role": "user", "content": "Original repair prompt"}]}],
                                  "statistics": {"embedding": {"embedding_requests": 1, "failed_requests": 0, "total_tokens": 7},
                                                 "chat": budget.statistics()}})
            if change == "source":
                (root / "paper_assistant/rag.py").write_text("changed offline source", encoding="utf-8")
            elif change == "delete_source":
                (root / "paper_assistant/rag.py").unlink()
            elif change == "protected":
                (root / protected[0]).write_bytes(b"changed offline input")
            elif change == "delete_protected":
                (root / protected[0]).unlink()
            core_finished = True
            return deepcopy(expected_core)

        captured = io.StringIO()
        with ExitStack() as mocks:
            mocks.enter_context(patch.object(target, "ROOT", root))
            mocks.enter_context(patch.object(Path, "read_bytes", controlled_read))
            mocks.enter_context(patch("sys.argv", ["smoke_rag", "--live"]))
            mocks.enter_context(patch.object(target, "load_embedding_settings",
                side_effect=RuntimeError(OFFLINE_SECRET) if configuration_error else None,
                return_value=SimpleNamespace(provider="offline")))
            mocks.enter_context(patch.object(target, "load_llm_settings",
                                            return_value=SimpleNamespace(provider="offline", model_id="offline-model")))
            mocks.enter_context(patch.object(target, "load_current_profile", return_value=profile))
            mocks.enter_context(patch.object(target, "make_index_profile", return_value=profile))
            mocks.enter_context(patch.object(target, "ChatBudget", return_value=budget))
            constructors = {}
            for name, returned in [("PaperStore", store), ("QdrantClient", qdrant), ("QdrantStore", vectors),
                                   ("EvidenceSearcher", searcher), ("RecordedLLM", chat)]:
                constructors[name] = mocks.enter_context(patch.object(target, name, return_value=returned,
                    side_effect=RuntimeError(OFFLINE_SECRET) if fail_construct == name else None))
            core = mocks.enter_context(patch.object(target, "answer_question", side_effect=fake_core))
            with redirect_stdout(captured):
                exit_code = target.main()
        report = json.loads((root / "artifacts/d5/rag_smoke.json").read_text(encoding="utf-8"))
        history = json.loads((root / report["history_report"]).read_text(encoding="utf-8"))
        markdown = (root / "artifacts/d5/rag_smoke.md").read_text(encoding="utf-8")
        self.assertEqual(report, history)
        self.assertEqual(report["chat_attempts"], budget.records)
        self.assertEqual(report["chat_statistics"], budget.statistics())
        self.assertNotIn(OFFLINE_SECRET, json.dumps(report, ensure_ascii=False))
        self.assertNotIn(OFFLINE_SECRET, captured.getvalue())
        self.assertNotIn(OFFLINE_SECRET, markdown)
        if not configuration_error and fail_construct != "PaperStore":
            constructors["PaperStore"].assert_called_once_with(root / "data/index/papers.sqlite3", read_only=True)
            self.assertTrue(store.closed)
        if not configuration_error and fail_construct not in ("PaperStore", "QdrantClient"):
            self.assertTrue(qdrant.closed)
        if not configuration_error and collection and fail_construct not in ("PaperStore", "QdrantClient", "QdrantStore"):
            self.assertTrue(vectors.closed)
        if core.called:
            self.assertTrue(chat.closed)
        return SimpleNamespace(report=report, exit_code=exit_code, expected_core=expected_core, budget=budget,
                               root=root, markdown=markdown, store=store, vectors=vectors, chat=chat, qdrant=qdrant,
                               constructors=constructors, core=core)

    def assert_steps_and_charges(self, scenario):
        report, expected = scenario.report, scenario.expected_core
        for name in ["search", "context", "generation", "citation_checks", "citation_repairs", "statistics"]:
            self.assertEqual(report["result"][name], expected[name])
        self.assertEqual(report["embedding_requests"], 1)
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(report["network_requests"], 2)
        self.assertEqual(report["chat_statistics"]["total_tokens"], 25)

    def test_normal_answer_contains_core_derived_refs_and_preserves_steps_and_charges(self):
        scenario = self.run_scenario()
        report = scenario.report
        self.assertEqual(scenario.exit_code, 0)
        self.assertEqual(report["status"], "answered")
        self.assertEqual(report["answer"], scenario.expected_core["answer"])
        self.assertEqual(report["result"], scenario.expected_core)
        self.assertEqual(set(report["answer"]["evidence_refs"][0]), {"chunk_id", "paper_id", "parse_revision", "pdf_page"})
        self.assertIsNone(report["failure_stage"])
        self.assertFalse(report["is_answer_accuracy"])
        self.assert_steps_and_charges(scenario)

    def assert_cleanup_fault(self, resource):
        scenario = self.run_scenario(fail_exit=resource)
        report = scenario.report
        self.assertEqual(scenario.exit_code, 1)
        self.assertEqual(report["status"], "tool_error")
        self.assertEqual(report["result"]["status"], "tool_error")
        self.assertIsNone(report["answer"])
        self.assertIsNone(report["result"]["answer"])
        self.assertEqual(report["failure_stage"], "resource_cleanup")
        self.assertEqual(report["error"]["code"], "local_error")
        self.assertTrue(scenario.store.closed and scenario.qdrant.closed and scenario.vectors.closed and scenario.chat.closed)
        self.assert_steps_and_charges(scenario)

    def test_sqlite_exit_fault_clears_answer_without_losing_original_steps_or_charge(self):
        self.assert_cleanup_fault("sqlite")

    def test_qdrant_close_fault_clears_answer_without_losing_original_steps_or_charge(self):
        self.assert_cleanup_fault("qdrant")

    def test_vectors_exit_fault_clears_answer_without_losing_original_steps_or_charge(self):
        self.assert_cleanup_fault("vectors")

    def test_chat_exit_fault_clears_answer_without_losing_original_steps_or_charge(self):
        self.assert_cleanup_fault("chat")

    def test_configuration_fault_is_safe_and_prevents_all_resources_and_calls(self):
        scenario = self.run_scenario(configuration_error=True)
        self.assertEqual(scenario.exit_code, 1)
        self.assertEqual(scenario.report["failure_stage"], "configuration")
        self.assertEqual(scenario.report["status"], "tool_error")
        self.assertEqual(scenario.report["network_requests"], 0)
        self.assertEqual(scenario.report["chat_attempts"], [])
        self.assertIsNone(scenario.report["result"])
        for constructor in scenario.constructors.values():
            constructor.assert_not_called()
        scenario.core.assert_not_called()

    def test_resource_constructor_fault_releases_every_prior_resource_without_network(self):
        for name in ["PaperStore", "QdrantClient", "QdrantStore", "EvidenceSearcher", "RecordedLLM"]:
            with self.subTest(failed_constructor=name):
                scenario = self.run_scenario(fail_construct=name)
                self.assertEqual(scenario.exit_code, 1)
                self.assertEqual(scenario.report["status"], "tool_error")
                self.assertEqual(scenario.report["failure_stage"], "resources")
                self.assertEqual(scenario.report["network_requests"], 0)
                self.assertIsNone(scenario.report["answer"])
                self.assertIsNone(scenario.report["result"])
                scenario.core.assert_not_called()

    def test_missing_collection_releases_store_and_qdrant_before_chat(self):
        scenario = self.run_scenario(collection=False)
        self.assertEqual(scenario.exit_code, 1)
        self.assertEqual(scenario.report["status"], "tool_error")
        self.assertTrue(scenario.store.closed and scenario.qdrant.closed)
        self.assertFalse(scenario.vectors.entered or scenario.chat.entered)
        scenario.constructors["RecordedLLM"].assert_not_called()
        scenario.core.assert_not_called()
        self.assertEqual(scenario.report["network_requests"], 0)




    def test_cleanup_deadline_crossing_clears_success_and_keeps_steps_and_charges(self):
        scenario = self.run_scenario(cleanup_timeout=True)
        self.assertEqual(scenario.exit_code, 1)
        self.assertEqual(scenario.report["status"], "budget_exceeded")
        self.assertEqual(scenario.report["failure_stage"], "resource_cleanup")
        self.assertIsNone(scenario.report["answer"])
        self.assertIsNone(scenario.report["result"]["answer"])
        self.assertEqual(scenario.report["chat_statistics"]["elapsed_seconds"], 121)
        self.assert_steps_and_charges(scenario)


    def test_core_program_failure_keeps_exact_terminal_status_error_and_exit_code(self):
        for status in ["tool_error", "invalid_output", "budget_exceeded"]:
            with self.subTest(status=status):
                scenario = self.run_scenario(core_status=status)
                self.assertEqual(scenario.exit_code, 1)
                self.assertEqual(scenario.report["status"], status)
                self.assertEqual(scenario.report["result"], scenario.expected_core)
                self.assertIsNone(scenario.report["answer"])
                self.assertEqual(scenario.report["failure_stage"], "citations")
                self.assert_steps_and_charges(scenario)

    def test_core_insufficient_evidence_is_success_exit_without_refs(self):
        scenario = self.run_scenario(core_status="insufficient_evidence")
        self.assertEqual(scenario.exit_code, 0)
        self.assertEqual(scenario.report["status"], "insufficient_evidence")
        self.assertEqual(scenario.report["answer"]["claims"], [])
        self.assertEqual(scenario.report["answer"]["evidence_refs"], [])
        self.assertIsNone(scenario.report["failure_stage"])
        self.assert_steps_and_charges(scenario)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
