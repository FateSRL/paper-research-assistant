"""D8 E offline standalone CLI checks, with actual Agent and SDK MockTransport.

All sources/data are copied into temporary projects. No .env or production
SQLite/Qdrant is opened. The command itself only saves a new check history;
the D186 acceptance report and earlier task records remain untouched.
"""

from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import sqlite3
import unittest
from unittest.mock import Mock, patch

from paper_assistant import agent_runtime as runtime
from paper_assistant.answer_export import atomic_text, file_link
from paper_assistant.config import EmbeddingSettings
from paper_assistant.indexing import atomic_json, digest, make_index_profile
from paper_assistant.llm_client import ChatBudget, ChatPolicy
from scripts import answer_question_agent as cli
from scripts import check_agent as fixtures
from scripts.check_agent import (
    AgentFixture, QUESTION, SECRET, SequencedSearcher, answer_action,
    insufficient_action, response, retry_action,
)
from scripts.check_llm import completion


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AgentRuntimeFixture(AgentFixture):
    def setUp(self):
        super().setUp()
        for name in runtime.SOURCES:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / name).read_bytes())
        self.embedding = EmbeddingSettings(backend="dashscope", model="offline-embedding", api_key=SECRET,
                        base_url="https://example.invalid/v1", dimension=2)
        self.profile = make_index_profile(self.embedding)
        self.strategy = json.loads((ROOT / runtime.STRATEGY_PATH).read_text(encoding="utf-8"))
        self.strategy["chat"] = {"provider": self.settings.provider, "model_id": self.settings.model_id,
            "base_url": self.settings.base_url, "configured_timeout_seconds": self.settings.timeout}
        self.strategy["index_profile"] = self.profile
        self.strategy["rules"]["budget"]["chat_policy"] = runtime.asdict(ChatPolicy())
        self.strategy["policy_sha256"] = digest(self.strategy["rules"])
        for name, value in (
            ("data/index/current_profile.json", self.profile),
            ("data/index/profiles/" + self.profile["index_profile_id"] + ".json", self.profile),
            ("data/index/qdrant/meta.json", {"fixture": True}),
            (runtime.STRATEGY_PATH, self.strategy),
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")
        for name in ("data/chunks/fixture.json", "eval/dev.jsonl", "eval/acceptance.jsonl",
                     "artifacts/d5/answer_result.json", "artifacts/d6/web_answer_result.json",
                     "archive/run_logs/d5/first-run.json", "archive/run_logs/d6/first-run.json"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"unchanged fixture bytes\n")

    def argv(self, *, query=QUESTION, json_output=True):
        args = ["--query", query, "--paper-id", "p1", "--parse-revision", "r1"]
        return args + (["--json"] if json_output else [])

    def execute(self, *outcomes, rows=None, change=None, cleanup_fault=False,
                cleanup_deadline=False, config_fault=False, export_fault=False,
                export_setup_fault=False, core_fault=False, verification_fault=False,
                chat_construct_fault=False, config_deadline=False,
                verification_deadline=False, export_setup_deadline=False,
                core_noise=False, json_output=True):
        budget = ChatBudget(ChatPolicy(), clock=self.clock)
        client, requests = self.client(*outcomes, budget=budget)
        previous_close = client.close
        def close_chat():
            previous_close()
            if cleanup_deadline:
                self.clock.advance(121)
            if cleanup_fault:
                raise RuntimeError(SECRET)
        searcher = SequencedSearcher([self.row] if rows is None else rows)
        def change_input(_number):
            if change == "source":
                (self.root / "paper_assistant/agent.py").write_bytes(b"changed source")
            elif change == "input":
                (self.root / "data/chunks/fixture.json").write_bytes(b"changed input")
            elif change == "added":
                (self.root / "eval/new-fixture.json").write_bytes(b"added input")
            elif change == "deleted":
                (self.root / "data/chunks/fixture.json").unlink()
        searcher.on_search = change_input
        @contextmanager
        def resources(*args):
            try:
                yield self.store, searcher
            finally:
                self.store.close()
                searcher.close()
        output, errors = io.StringIO(), io.StringIO()
        original_core = runtime.answer_question_agent
        def configuration_failure():
            if config_deadline:
                self.clock.advance(121)
            raise RuntimeError(SECRET)
        def verification_failure(*args):
            if verification_deadline:
                self.clock.advance(121)
            raise RuntimeError(SECRET)
        def export_setup_failure(*args, **kwargs):
            if export_setup_deadline:
                self.clock.advance(121)
            raise RuntimeError(SECRET)
        def exploding_core(*args, **kwargs):
            original_core(*args, **kwargs)
            raise RuntimeError(SECRET)
        def noisy_core(*args, **kwargs):
            print("offline diagnostic before Agent")
            value = original_core(*args, **kwargs)
            print("offline diagnostic after Agent")
            return value
        with ExitStack() as stack:
            stack.enter_context(patch.object(cli, "ROOT", self.root))
            stack.enter_context(patch.object(runtime, "ChatBudget", return_value=budget))
            stack.enter_context(patch.object(runtime, "load_embedding_settings", return_value=self.embedding))
            stack.enter_context(patch.object(runtime, "load_llm_settings", side_effect=configuration_failure)
                                if config_fault else patch.object(runtime, "load_llm_settings", return_value=self.settings))
            stack.enter_context(patch.object(runtime, "open_retrieval_resources", side_effect=resources))
            stack.enter_context(patch.object(runtime, "RecordedLLM", side_effect=RuntimeError(SECRET))
                                if chat_construct_fault else patch.object(runtime, "RecordedLLM", return_value=client))
            stack.enter_context(patch.object(client, "close", side_effect=close_chat))
            if export_fault:
                stack.enter_context(patch("paper_assistant.agent_export.atomic_text", side_effect=OSError(SECRET)))
            if export_setup_fault:
                stack.enter_context(patch.object(runtime, "save_agent_run", side_effect=export_setup_failure))
            if verification_fault:
                stack.enter_context(patch.object(runtime, "changed_inputs", side_effect=verification_failure))
            if core_fault:
                stack.enter_context(patch.object(runtime, "answer_question_agent", side_effect=exploding_core))
            elif core_noise:
                stack.enter_context(patch.object(runtime, "answer_question_agent", side_effect=noisy_core))
            with redirect_stdout(output), redirect_stderr(errors):
                code = cli.main(self.argv(json_output=json_output))
        report = json.loads(output.getvalue()) if json_output else None
        self.last_searcher = searcher
        return code, report, output.getvalue(), errors.getvalue(), requests, client


class AgentCliArgumentChecks(unittest.TestCase):
    def test_invalid_parameters_never_enter_runtime_or_load_configuration(self):
        cases = [[], ["--query", " "], ["--query", "q", "--paper-id", "p"],
                 ["--query", "q", "--version", "p", "r", "--top-k", "10"],
                 ["--query", "q", "--version", "p", "r", "--max-chars", "0"],
                 ["--query", "q", "--version", "p", "r", "--max-chars", "8001"],
                 ["--query", "q", "--version", "p", "r", "--version", "p", "r"],
                 ["--query", "q", "--version", "p", "r", "--paper-id", "p", "--parse-revision", "r"],
                 ["--query", "q", "--version", "../p", "r"],
                 ["--query", "q", "--version", "p1", "r", "--version", "p2", "r",
                  "--version", "p3", "r", "--version", "p4", "r"]]
        with patch.object(runtime, "run_question_agent", side_effect=AssertionError("runtime forbidden")) as run, \
             patch.object(runtime, "load_llm_settings", side_effect=AssertionError("env forbidden")) as load:
            for argv in cases:
                with self.subTest(argv=argv), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        cli.main(argv)
                    self.assertEqual(raised.exception.code, 2)
            run.assert_not_called()
            load.assert_not_called()

    def test_help_exits_zero_without_runtime(self):
        output = io.StringIO()
        with patch.object(runtime, "run_question_agent", side_effect=AssertionError("runtime forbidden")) as run, \
             redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--version", output.getvalue())
        run.assert_not_called()

    def test_one_to_three_pairs_preserve_original_question_and_exact_pairs(self):
        args = cli.parse_args(["--query", QUESTION, "--version", "p1", "r1", "--version", "p2", "r2",
                               "--version", "p3", "r3", "--max-chars", "1"])
        self.assertEqual(args.query, QUESTION)
        self.assertEqual(args.pairs, [("p1", "r1"), ("p2", "r2"), ("p3", "r3")])
        self.assertEqual(args.max_chars, 1)


class AgentRuntimeChecks(AgentRuntimeFixture):
    def test_actual_core_mock_sdk_produces_pure_json_and_d8_only_records(self):
        old = {str(path): sha(path) for directory in ("artifacts/d5", "artifacts/d6", "archive/run_logs/d5", "archive/run_logs/d6")
               for path in (self.root / directory).rglob("*") if path.is_file()}
        code, report, output, errors, requests, client = self.execute(response(answer_action()))
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "answered")
        self.assertEqual(report["task"], "D8")
        self.assertEqual(report["mode"], "agent")
        self.assertEqual(report["query"], QUESTION)
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(report["embedding_requests"], 1)
        self.assertEqual(report["network_requests"], 2)
        self.assertTrue(client._closed)
        self.assertTrue(self.store.closed)
        self.assertTrue(self.last_searcher.closed)
        self.assertEqual(json.loads(output), report)
        self.assertNotIn(SECRET, output + errors)
        self.assertEqual(report["export"]["status"], "completed")
        self.assertNotIn("source_sha256", report)
        self.assertEqual(json.loads((self.root / "artifacts/d8/agent_result.json").read_text()), report)
        self.assertEqual(old, {name: sha(name) for name in old})

    def test_model_insufficient_is_normal_zero_exit(self):
        code, report, *_ = self.execute(response(insufficient_action()))
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "insufficient_evidence")

    def test_invalid_output_is_one_exit_after_only_one_shared_repair(self):
        code, report, *_ = self.execute(response("bad output"), response("still bad"))
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "invalid_output")
        self.assertEqual(report["llm_requests"], 2)
        self.assertEqual(report["chat_statistics"]["repairs"], 1)
        self.assertEqual(report["embedding_requests"], 1)

    def test_json_stdout_stays_pure_when_core_prints_diagnostics(self):
        code, report, output, errors, *_ = self.execute(response(answer_action()), core_noise=True)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), report)
        self.assertNotIn("offline diagnostic", output)
        self.assertIn("offline diagnostic before Agent", errors)
        self.assertIn("offline diagnostic after Agent", errors)

    def test_markdown_output_uses_saved_agent_result(self):
        code, report, output, errors, requests, client = self.execute(response(answer_action()), json_output=False)
        self.assertEqual(code, 0)
        self.assertIsNone(report)
        self.assertIn("D8 问答运行记录", output)
        self.assertNotIn(SECRET, output + errors)

    def test_configuration_fault_is_safe_recorded_one_exit_and_zero_calls(self):
        code, report, output, errors, requests, client = self.execute(config_fault=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "tool_error")
        self.assertEqual(report["failure_stage"], "configuration")
        self.assertEqual(report["embedding_requests"], 0)
        self.assertEqual(report["llm_requests"], 0)
        self.assertNotIn(SECRET, output + errors)
        self.assertEqual(requests, [])

    def test_chat_constructor_failure_closes_retrieval_resources(self):
        code, report, *_ = self.execute(chat_construct_fault=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["failure_stage"], "resources")
        self.assertTrue(self.store.closed)
        self.assertTrue(self.last_searcher.closed)
        self.assertEqual(report["embedding_requests"], 0)

    def test_configuration_failure_over_deadline_is_budget_with_interrupted_failure(self):
        code, report, *_ = self.execute(config_fault=True, config_deadline=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "budget_exceeded")
        self.assertEqual(report["failure_stage"], "configuration")
        self.assertEqual(report["interrupted_failure"]["error"]["code"], "local_error")
        self.assertEqual(report["llm_requests"], 0)

    def test_cleanup_failure_over_deadline_is_budget_and_keeps_actual_cost(self):
        code, report, *_ = self.execute(response(answer_action()), cleanup_fault=True, cleanup_deadline=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "budget_exceeded")
        self.assertEqual(report["failure_stage"], "resource_cleanup")
        self.assertEqual(report["interrupted_failure"]["error"]["code"], "local_error")
        self.assertEqual(report["embedding_requests"], 1)
        self.assertEqual(report["llm_requests"], 1)



    def test_chat_cleanup_failure_removes_answer_and_retains_consumed_usage(self):
        code, report, output, errors, requests, client = self.execute(response(answer_action()), cleanup_fault=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["failure_stage"], "resource_cleanup")
        self.assertIsNone(report["answer"])
        self.assertEqual(report["pre_failure_result"]["status"], "answered")
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(report["embedding_requests"], 1)
        self.assertEqual(len(report["chat_attempts"]), 1)
        self.assertTrue(client._closed)
        self.assertTrue(self.store.closed)
        self.assertNotIn(SECRET, output + errors)

    def test_cleanup_deadline_blocks_success_without_repeating_work(self):
        code, report, *_ = self.execute(response(answer_action()), cleanup_deadline=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "budget_exceeded")
        self.assertEqual(report["failure_stage"], "resource_cleanup")
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(report["embedding_requests"], 1)

    def test_core_unexpected_exception_keeps_chat_attempts_and_unknown_embedding_count(self):
        code, report, output, errors, requests, client = self.execute(response(answer_action()), core_fault=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["failure_stage"], "pipeline")
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(len(report["chat_attempts"]), 1)
        self.assertIsNone(report["embedding_requests"])
        self.assertIsNone(report["network_requests"])
        self.assertNotIn(SECRET, output + errors)

    def test_missing_chat_usage_is_null_with_actual_attempts(self):
        code, report, *_ = self.execute((200, completion(json.dumps(answer_action()), usage=None)))
        self.assertEqual(code, 0)
        self.assertIsNone(report["chat_statistics"]["total_tokens"])
        self.assertEqual(report["chat_statistics"]["known_total_tokens"], 0)
        self.assertEqual(report["sdk_request_attempts"], 1)
        self.assertEqual(report["llm_requests"], 1)

    def test_export_disk_failure_retains_pre_export_core_and_actual_usage(self):
        code, report, *_ = self.execute(response(answer_action()), export_fault=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "tool_error")
        self.assertEqual(report["error"]["code"], "export_error")
        self.assertEqual(report["export"]["status"], "failed")
        self.assertEqual(report["pre_export_result"]["status"], "answered")
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(report["embedding_requests"], 1)

    def test_export_setup_exception_still_returns_safe_complete_cli_json(self):
        code, report, output, errors, requests, client = self.execute(response(answer_action()), export_setup_fault=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["export"]["failed_step"], "export_setup")
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(report["embedding_requests"], 1)
        self.assertIsNone(report["answer"])
        self.assertNotIn(SECRET, output + errors)

    def test_export_setup_exception_after_commit_is_export_error_and_preserves_usage(self):
        code, report, *_ = self.execute(response(answer_action()), export_setup_fault=True, export_setup_deadline=True)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "tool_error")
        self.assertEqual(report["failure_stage"], "export")
        self.assertEqual(report["error"]["code"], "export_error")
        self.assertEqual(report["pre_export_result"]["status"], "answered")
        self.assertEqual(report["business_commit"]["status"], "answered")
        self.assertEqual(report["llm_requests"], 1)
        self.assertEqual(report["embedding_requests"], 1)
        self.assertEqual(report["chat_statistics"]["elapsed_seconds"], report["business_commit"]["elapsed_seconds"])


    def test_runtime_invalid_input_is_rejected_before_environment_or_snapshot(self):
        with patch.object(runtime, "load_llm_settings", side_effect=AssertionError("env forbidden")) as load:
            for kwargs in ({"query": " "}, {"selected_versions": []}, {"top_k": 10},
                           {"max_chars": True}, {"selected_versions": [("../p", "r")]},
                           {"selected_versions": [("p", "r"), ("p", "r")]}):
                values = {"query": QUESTION, "selected_versions": [("p1", "r1")], "project_root": self.root}
                values.update(kwargs)
                with self.subTest(kwargs=kwargs), self.assertRaises(runtime.InvalidQuestion):
                    runtime.run_question_agent(**values)
            load.assert_not_called()

    def test_public_configuration_excludes_credentials_and_rejects_auth_urls(self):
        public = runtime.public_configuration(self.embedding, self.settings, self.profile, ChatPolicy())
        self.assertNotIn(SECRET, json.dumps(public))
        self.assertEqual(public["chat"]["model_id"], self.settings.model_id)
        bad = type(self.settings)(provider="deepseek", model_id="offline", api_key=SECRET,
                    base_url="https://user:password@example.invalid/v1", timeout=30)
        with self.assertRaises(ValueError):
            runtime.public_configuration(self.embedding, bad, self.profile, ChatPolicy())

    def test_profile_pointer_mismatch_is_rejected_without_configuration_loading(self):
        saved = self.root / "data/index/profiles" / (self.profile["index_profile_id"] + ".json")
        saved.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            runtime.load_current_profile(self.root)


    def test_missing_persisted_index_prevents_resource_creation(self):
        (self.root / "data/index/qdrant/meta.json").unlink()
        with patch.object(runtime, "PaperStore", side_effect=AssertionError("no store")) as store, \
             patch.object(runtime, "QdrantClient", side_effect=AssertionError("no vector client")) as qdrant:
            with self.assertRaises(ValueError):
                with runtime.open_retrieval_resources(self.root, self.embedding, self.profile):
                    self.fail("unexpected resources")
            store.assert_not_called()
            qdrant.assert_not_called()

    def test_missing_collection_never_constructs_vector_store_and_closes_opened_resources(self):
        events = []
        class Store:
            def __enter__(self):
                events.append("store_enter")
                return self
            def __exit__(self, *args):
                events.append("store_close")
        qdrant = Mock()
        qdrant.collection_exists.return_value = False
        qdrant.close.side_effect = lambda: events.append("qdrant_close")
        with patch.object(runtime, "PaperStore", return_value=Store()) as store, \
             patch.object(runtime, "QdrantClient", return_value=qdrant), \
             patch.object(runtime, "QdrantStore", side_effect=AssertionError("no construction")) as vectors:
            with self.assertRaises(ValueError):
                with runtime.open_retrieval_resources(self.root, self.embedding, self.profile):
                    self.fail("unexpected resources")
            store.assert_called_once_with(self.root / "data/index/papers.sqlite3", read_only=True)
            vectors.assert_not_called()
        self.assertEqual(events, ["store_enter", "qdrant_close", "store_close"])

    def test_vector_constructor_failure_closes_both_previously_opened_resources(self):
        events = []
        class Store:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                events.append("store_close")
        qdrant = Mock()
        qdrant.collection_exists.return_value = True
        qdrant.close.side_effect = lambda: events.append("qdrant_close")
        with patch.object(runtime, "PaperStore", return_value=Store()), \
             patch.object(runtime, "QdrantClient", return_value=qdrant), \
             patch.object(runtime, "QdrantStore", side_effect=ValueError("dimension mismatch")):
            with self.assertRaises(ValueError):
                with runtime.open_retrieval_resources(self.root, self.embedding, self.profile):
                    self.fail("unexpected resources")
        self.assertEqual(events, ["qdrant_close", "store_close"])

    def test_frozen_public_configuration_accepts_actual_offline_profile_and_policy(self):
        public = runtime.validate_frozen_configuration(self.strategy, self.embedding, self.settings,
                                                       self.profile, ChatPolicy())
        self.assertEqual(public, runtime.public_configuration(self.embedding, self.settings, self.profile, ChatPolicy()))



def _frozen_mismatch_test(kind):
    def test(self):
        strategy = deepcopy(self.strategy)
        if kind == "model":
            strategy["chat"]["model_id"] = "different-model"
        elif kind == "endpoint":
            strategy["chat"]["base_url"] = "https://other.invalid/v1"
        elif kind == "timeout":
            strategy["chat"]["configured_timeout_seconds"] = 31.0
        elif kind == "profile":
            strategy["index_profile"]["index_profile_id"] = "different-profile"
        elif kind == "policy":
            strategy["rules"]["budget"]["chat_policy"]["max_attempts"] = 2
            strategy["policy_sha256"] = digest(strategy["rules"])
        elif kind == "hash":
            strategy["policy_sha256"] = "0" * 64
        elif kind == "retrieval":
            strategy["rules"]["retrieval"]["retry_top_k"] = 7
            strategy["policy_sha256"] = digest(strategy["rules"])
        (self.root / runtime.STRATEGY_PATH).write_text(json.dumps(strategy), encoding="utf-8")
        code, report, output, errors, requests, _ = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(report["error"]["code"], "configuration_mismatch")
        self.assertEqual(report["llm_requests"], 0)
        self.assertEqual(report["embedding_requests"], 0)
        self.assertEqual(requests, [])
        self.assertNotIn(SECRET, output + errors)
    return test


for _kind in ("policy",):
    setattr(AgentRuntimeChecks, "test_frozen_" + _kind + "_mismatch_blocks_all_calls", _frozen_mismatch_test(_kind))


CLI_BOUNDARY_CASES = (AgentCliArgumentChecks, AgentRuntimeChecks)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
