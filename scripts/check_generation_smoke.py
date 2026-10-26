"""D5 C：真实验证脚本的关闭故障与费用记录离线检查。

运行：python -X utf8 -m scripts.check_generation_smoke
临时 ROOT 及模拟配置/检索/生成/资源替代所有外部入口；不读取 .env，
不打开正式数据库、不调用真实 SDK 或网络。模拟费用只用于断言记录行为。
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
from paper_assistant.search import SearchError
from scripts.check_llm import FakeClock
from scripts import smoke_generation as target


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OFFLINE_SECRET = "offline-close-failure-secret-do-not-log"
SIMULATED_RUNS = 0
SIMULATED_SEARCH_CALLS = 0
SIMULATED_GENERATION_CALLS = 0
SOURCE_FILES = ["paper_assistant/context.py", "paper_assistant/generation.py", "paper_assistant/schemas.py",
                "paper_assistant/llm_client.py", "paper_assistant/search.py", "scripts/search_evidence.py",
                "scripts/smoke_generation.py"]


class FakeResource:
    def __init__(self, fail_exit=False):
        self.fail_exit = fail_exit
        self.entered = self.closed = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_):
        self.closed = True
        if self.fail_exit:
            raise RuntimeError(OFFLINE_SECRET)


class FakeQdrant:
    def __init__(self, fail_close=False):
        self.fail_close = fail_close
        self.closed = False

    def collection_exists(self, _collection):
        return True

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError(OFFLINE_SECRET)


class SmokeChecks(unittest.TestCase):
    def run_scenario(self, *, fail_exit=None, search_error=False, generation_error=False, configuration_error=False):
        """真正执行 main 的文件记录路径，外部动作全部替换为可检查的模拟对象。"""
        global SIMULATED_RUNS
        SIMULATED_RUNS += 1
        temp = tempfile.TemporaryDirectory(prefix="d5-c-smoke-boundary-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name in SOURCE_FILES:
            copied = root / name
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes((PROJECT_ROOT / name).read_bytes())
        # 只生成临时文件，供脚本真实的输入保护哈希逻辑检查。
        for name in ["data/index/offline.bin", "data/chunks/offline.json", "data/papers/offline.pdf", "eval/offline.json"]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"offline protected input")
        profile = {"collection_name": "offline-collection", "index_profile_id": "offline-profile",
                   "recipe": {"dimension": 2}}
        body = "Synthetic source evidence."
        row = {"chunk_id": "offline-chunk", "paper_id": target.PAIRS[0][0],
               "parse_revision": target.PAIRS[0][1], "pdf_page": 1, "rank": 1, "score": 0.8,
               "text": body, "text_sha256": hashlib.sha256(body.encode()).hexdigest()}
        search = {"status": "success", "query": target.QUESTION,
                  "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in target.PAIRS],
                  "results": [row], "returned_count": 1, "top_k": 5,
                  "index_profile_id": "offline-profile",
                  "statistics": {"embedding_requests": 1, "total_tokens": 7, "failed_requests": 0}}
        store = FakeResource(fail_exit == "sqlite")
        qdrant = FakeQdrant(fail_exit == "qdrant")
        vectors = FakeResource(fail_exit == "vectors")
        chat = FakeResource(fail_exit == "chat")
        budget = ChatBudget(clock=FakeClock())
        chat.budget = budget
        messages = [{"role": "system", "content": "Offline system rules."},
                    {"role": "user", "content": '{"question":"offline","shown_evidence":[]}'}]
        expected_generation = {}

        def fake_search(*args, **kwargs):
            global SIMULATED_SEARCH_CALLS
            SIMULATED_SEARCH_CALLS += 1
            self.assertEqual(args, (target.QUESTION, target.PAIRS))
            self.assertEqual(kwargs, {"top_k": 5})
            if search_error:
                raise SearchError("Offline retrieval failed safely", stage="embedding", statistics={
                    "embedding_requests": 1, "total_tokens": None, "failed_requests": 1})
            return deepcopy(search)

        def fake_generation(_context, client):
            global SIMULATED_GENERATION_CALLS
            SIMULATED_GENERATION_CALLS += 1
            self.assertIs(client, chat)
            budget.reserve(retry=False, repair_start=False)
            budget.http_requests += 1
            budget.records.append({"number": 1, "purpose": "answer", "is_network_retry": False,
                                   "http_request_attempts": 1, "status": "success", "error_code": None,
                                   "http_status": 200, "usage": {"total_tokens": 25}, "finish_reason": "stop",
                                   "content": '{"status":"answered"}'})
            if generation_error:
                raise RuntimeError(OFFLINE_SECRET)
            expected_generation.update({"status": "draft_valid", "draft": {"status": "answered", "claims": [
                {"claim": "Synthetic claim", "citation_ids": ["offline-chunk"]}], "reason": None},
                "error": None, "citation_validation_status": "pending", "statistics": budget.statistics(),
                "generation_attempts": [{"messages": deepcopy(messages), "response": {
                    "content": "Original raw model text", "finish_reason": "stop", "usage": {"total_tokens": 25}},
                    "parse_error_code": None}]})
            return deepcopy(expected_generation)

        fake_searcher = SimpleNamespace(search_evidence=fake_search)
        captured = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(target, "ROOT", root))
            stack.enter_context(patch("sys.argv", ["smoke_generation", "--live"]))
            loaders = []
            loaders.append(stack.enter_context(patch.object(target, "load_embedding_settings",
                side_effect=RuntimeError(OFFLINE_SECRET) if configuration_error else None,
                return_value=SimpleNamespace(provider="offline"))))
            loaders.append(stack.enter_context(patch.object(target, "load_llm_settings",
                return_value=SimpleNamespace(provider="offline", model_id="offline-model"))))
            stack.enter_context(patch.object(target, "load_current_profile", return_value=profile))
            stack.enter_context(patch.object(target, "make_index_profile", return_value=profile))
            stack.enter_context(patch.object(target, "ChatBudget", return_value=budget))
            mocked_store = stack.enter_context(patch.object(target, "PaperStore", return_value=store))
            mocked_qdrant = stack.enter_context(patch.object(target, "QdrantClient", return_value=qdrant))
            mocked_vectors = stack.enter_context(patch.object(target, "QdrantStore", return_value=vectors))
            stack.enter_context(patch.object(target, "EvidenceSearcher", return_value=fake_searcher))
            mocked_chat = stack.enter_context(patch.object(target, "RecordedLLM", return_value=chat))
            mocked_generate = stack.enter_context(patch.object(target, "generate_draft", side_effect=fake_generation))
            with redirect_stdout(captured):
                exit_code = target.main()
        report = json.loads((root / "artifacts/d5/generation_smoke.json").read_text(encoding="utf-8"))
        history = json.loads((root / report["history_report"]).read_text(encoding="utf-8"))
        self.assertEqual(report, history)
        self.assertEqual(report["protected_files"]["checked_count"], 4)
        self.assertEqual(report["protected_files"]["changed_paths"], [])
        self.assertTrue(report["source_unchanged_during_run"])
        self.assertNotIn(OFFLINE_SECRET, json.dumps(report, ensure_ascii=False))
        self.assertNotIn(OFFLINE_SECRET, captured.getvalue())
        if not configuration_error:
            mocked_store.assert_called_once_with(root / "data/index/papers.sqlite3", read_only=True)
            mocked_qdrant.assert_called_once_with(path=str(root / "data/index/qdrant"))
            self.assertTrue(store.closed and qdrant.closed and vectors.closed)
        return SimpleNamespace(report=report, exit_code=exit_code, search=search,
                               generation=expected_generation, budget=budget, chat=chat,
                               mocked_chat=mocked_chat, mocked_generate=mocked_generate,
                               mocked_store=mocked_store, mocked_vectors=mocked_vectors)

    def assert_retrieval_close_failure(self, resource):
        result = self.run_scenario(fail_exit=resource)
        report = result.report
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(report["status"], "tool_error")
        self.assertEqual(report["error"]["code"], "local_error")
        self.assertEqual(report["failure_stage"], "retrieval")
        self.assertEqual(report["search"], result.search)
        self.assertEqual(report["embedding_requests"], 1)
        self.assertEqual(report["network_requests"], 1)
        self.assertEqual(report["llm_requests"], 0)
        self.assertIsNone(report["generation"])
        self.assertEqual(report["chat_attempts"], [])
        result.mocked_chat.assert_not_called()
        result.mocked_generate.assert_not_called()

    def test_sqlite_exit_failure_keeps_successful_search_and_embedding_charge(self):
        self.assert_retrieval_close_failure("sqlite")

    def test_qdrant_close_failure_keeps_successful_search_and_embedding_charge(self):
        self.assert_retrieval_close_failure("qdrant")

    def test_vector_exit_failure_keeps_successful_search_and_embedding_charge(self):
        self.assert_retrieval_close_failure("vectors")

    def test_chat_exit_failure_is_tool_error_and_keeps_draft_messages_responses_and_budget(self):
        result = self.run_scenario(fail_exit="chat")
        report = result.report
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(report["status"], "tool_error")
        self.assertEqual(report["failure_stage"], "generation")
        self.assertEqual(report["citation_validation_status"], "not_performed")
        self.assertEqual(report["generation"], result.generation)
        self.assertEqual(report["chat_attempts"], result.budget.records)
        self.assertEqual(report["chat_statistics"], result.budget.statistics())
        self.assertEqual(report["embedding_requests"], 1)
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(report["network_requests"], 2)
        self.assertEqual(report["chat_statistics"]["total_tokens"], 25)
        self.assertTrue(result.chat.closed)

    def test_normal_path_retains_search_context_generation_and_budget(self):
        result = self.run_scenario()
        report = result.report
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(report["status"], "draft_valid")
        self.assertIsNone(report["failure_stage"])
        self.assertEqual(report["generation"], result.generation)
        self.assertEqual(report["search"], result.search)
        self.assertEqual(report["context"]["allowed_citation_ids"], ["offline-chunk"])
        self.assertEqual(report["chat_attempts"], result.budget.records)
        self.assertEqual(report["network_requests"], 2)
        self.assertEqual(report["citation_validation_status"], "pending")
        self.assertFalse(report["is_answer_accuracy"])

    def test_search_error_keeps_failed_embedding_charge_without_chat(self):
        result = self.run_scenario(search_error=True)
        report = result.report
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(report["status"], "tool_error")
        self.assertEqual(report["error"]["code"], "search_error")
        self.assertEqual(report["error"]["stage"], "embedding")
        self.assertEqual(report["embedding_requests"], 1)
        self.assertEqual(report["search_error_statistics"]["failed_requests"], 1)
        self.assertEqual(report["network_requests"], 1)
        self.assertIsNone(report["search"])
        result.mocked_generate.assert_not_called()

    def test_generation_crash_keeps_already_consumed_attempt_and_actual_usage(self):
        result = self.run_scenario(generation_error=True)
        report = result.report
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(report["status"], "tool_error")
        self.assertEqual(report["failure_stage"], "generation")
        self.assertIsNone(report["generation"])
        self.assertEqual(report["chat_attempts"], result.budget.records)
        self.assertEqual(report["chat_statistics"]["total_tokens"], 25)
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(report["network_requests"], 2)

    def test_configuration_failure_stays_safe_and_counts_zero_external_attempts(self):
        result = self.run_scenario(configuration_error=True)
        report = result.report
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(report["status"], "tool_error")
        self.assertEqual(report["failure_stage"], "configuration")
        self.assertEqual(report["network_requests"], 0)
        self.assertEqual(report["embedding_requests"], 0)
        self.assertEqual(report["llm_requests"], 0)
        self.assertEqual(report["chat_attempts"], [])
        result.mocked_store.assert_not_called()
        result.mocked_generate.assert_not_called()


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
