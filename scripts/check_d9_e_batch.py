"""D9 E isolated stage, freeze, paired execution, resume and export checks.

Only synthetic dev labels, temporary PDFs/stores and SDK MockTransport are
used. No formal batch is prepared, no .env or production database is opened.
D8 compatibility classes are reused without running their historical mains.
"""
import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

import httpx

from paper_assistant import agent_export, d9_runtime
from paper_assistant.agent_comparison import run_paired_case
from paper_assistant.answer_export import atomic_text, exclusive_json
from paper_assistant.config import EmbeddingSettings, LLMSettings
from paper_assistant.indexing import make_index_profile
from paper_assistant.llm_client import ChatPolicy
from paper_assistant.retrieval import point_id
from scripts import check_agent, check_agent_export_modes as export_fixtures, run_agent_comparison as runner
from scripts.check_agent import AgentFixture, answer_action, encoded, response, retry_action
from scripts.check_llm import FakeClock, completion, http_error
from scripts.check_rag import FakeStore
from scripts.check_scoped_answering import ScopedSequencedSearcher
from scripts.check_source_scope import SourceScopeFixture

ROOT = Path(__file__).resolve().parents[1]


class TimedScopedSearcher(ScopedSequencedSearcher):
    supports_remaining_time = True


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class D9BatchChecks(unittest.TestCase):
    client = AgentFixture.client

    def setUp(self):
        self.fixture = SourceScopeFixture()
        self.addCleanup(self.fixture.temp.cleanup)
        self.root = self.fixture.root
        self.clock = FakeClock()
        self.settings = LLMSettings("deepseek", "offline-model", check_agent.SECRET,
                                    "https://example.invalid/v1", 30.0)
        self.embedding = EmbeddingSettings("dashscope", "offline-embedding", "offline-key",
                                            "https://example.invalid/embeddings", 8)
        self.profile = make_index_profile(self.embedding)
        self.store = FakeStore({identifier: {**row, "title": "Offline structural fixture",
                                "arxiv_version": "v1", "source_url": "https://example.invalid/paper",
                                "local_path": "data/papers/fixture.pdf"}
                                for identifier, row in self.fixture.chunks.items()})
        self.case_ids = ["synthetic-A", "synthetic-B"]
        self.question = self.fixture.question
        self.opened_resources = 0
        self.mode_requests = {}
        contract = json.loads((ROOT / "artifacts/d9/agent_config.json").read_text(encoding="utf-8"))
        contract["chat"] = {"provider": self.settings.provider, "model_id": self.settings.model_id,
                            "base_url": self.settings.base_url, "configured_timeout_seconds": self.settings.timeout}
        contract["index_profile"] = deepcopy(self.profile)
        contract["ready_versions"] = [{"paper_id": self.fixture.paper_id,
                                        "parse_revision": self.fixture.parse_revision, "status": "ready",
                                        "index_profile_id": self.profile["index_profile_id"]}]
        contract_path = self.root / "artifacts/d9/agent_config.json"
        atomic_text(contract_path, encoded(contract))
        self.contract_sha = sha(contract_path)
        strategy = d9_runtime.build_runtime_configuration(contract, contract_sha256=self.contract_sha,
                                                          registry_sha256=sha(self.root / self.fixture.registry_path))
        atomic_text(self.root / d9_runtime.STRATEGY_PATH, encoded(strategy))
        atomic_text(self.root / "artifacts/d8/agent_config.json", "immutable historical D8 fixture\n")
        atomic_text(self.root / "data/index/current_profile.json", encoded(self.profile))
        atomic_text(self.root / ("data/index/profiles/" + self.profile["index_profile_id"] + ".json"), encoded(self.profile))
        abstract = self.fixture.chunks[self.fixture.abstract_id]
        cases = [{"case_id": identifier, "split": "dev", "review_status": "human_verified",
                  "question": self.question, "paper_ids": [self.fixture.paper_id], "answerable": True,
                  "question_type": "synthetic_fact", "annotation_marker": "DO_NOT_SEND_EXPECTED_" + identifier,
                  "expected_points": ["DO_NOT_SEND_EXPECTED_POINT"],
                  "expected_evidence": [{"paper_id": self.fixture.paper_id, "pdf_page": 2,
                                         "pdf_sha256": abstract["pdf_sha256"], "quote": abstract["text"]}]}
                 for identifier in self.case_ids]
        atomic_text(self.root / "eval/dev.jsonl", "\n".join(encoded(case) for case in cases) + "\n")
        atomic_text(self.root / "eval/holdout.jsonl", "not JSON; fixture holdout is hashed only\n")

    def read(self, relative):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def path(self, batch_id="offline-d9"):
        return self.root / "artifacts/d9/comparison" / batch_id

    def prepare(self, batch_id="offline-d9", case_ids=None):
        return runner.prepare_batch(batch_id, self.case_ids[:1] if case_ids is None else case_ids,
                                    project_root=self.root, stage="d9")

    def factory(self, fixed=None, agent=None):
        outcomes = {"fixed_rag": fixed if fixed is not None else [response(answer_action(self.fixture.abstract_id)["answer"])],
                    "agent": agent if agent is not None else [response(answer_action(self.fixture.abstract_id))]}
        self.mode_requests, self.clients = {}, {}

        def create(mode, budget):
            client, requests = self.client(*outcomes[mode], budget=budget)
            self.mode_requests[mode], self.clients[mode] = requests, client
            return client
        return create

    def execute(self, batch_id="offline-d9", *, searcher=None, factory=None, resume=False,
                close_error=None, on_close=None):
        rows = self.fixture.search([self.fixture.abstract_id])["results"]
        self.searcher = searcher or TimedScopedSearcher(*[rows for _ in self.case_ids],
                                                           profile=self.profile["index_profile_id"])
        self.searcher.closed = False

        @contextmanager
        def resources(*args):
            self.opened_resources += 1
            try:
                yield self.store, self.searcher
            finally:
                self.store.close()
                self.searcher.closed = True
                if on_close:
                    on_close()
                if close_error:
                    raise close_error

        # The production function still receives the actual validated Registry.
        def paired(*args, **kwargs):
            return run_paired_case(*args, **kwargs, clock=self.clock)

        with patch.object(runner, "run_paired_case", side_effect=paired):
            return runner.execute_batch(batch_id, stage="d9", project_root=self.root, resume=resume,
                configuration_loader=lambda: (self.embedding, self.settings), resources_factory=resources,
                client_factory=factory or self.factory())

    def test_prepare_binds_distinct_runtime_contract_registry_sources_with_zero_requests(self):
        with patch.object(runner, "load_embedding_settings", side_effect=AssertionError("env forbidden")), \
                patch.object(runner, "load_llm_settings", side_effect=AssertionError("env forbidden")), \
                patch.object(runner, "open_retrieval_resources", side_effect=AssertionError("stores forbidden")):
            prepared = self.prepare()
        self.assertEqual(prepared["real_api_calls"], 0)
        self.assertEqual(prepared["path"], "artifacts/d9/comparison/offline-d9")
        manifest = self.read(prepared["path"] + "/manifest.json")
        self.assertEqual(manifest["task"], "D9-E")
        self.assertEqual(manifest["strategy_binding"]["schema_revision"], "d9-runtime-policy-v1")
        self.assertNotIn("binding", manifest)
        self.assertFalse((self.root / "artifacts/d8/comparison").exists())

    def test_stage_is_controlled_and_d8_manifest_cannot_be_migrated(self):
        for stage in (None, "D9", "../d9", "d10", True):
            with self.subTest(stage=stage), self.assertRaises(ValueError):
                runner.prepare_batch("invalid", self.case_ids[:1], project_root=self.root, stage=stage)
        prepared = self.prepare()
        d9_path = self.path()
        original = (d9_path / "manifest.json").read_bytes()
        with self.assertRaises(FileNotFoundError):
            runner.execute_batch("offline-d9", project_root=self.root)
        manifest = json.loads(original)
        manifest.update(task="D8-E", runner_version=runner.RUNNER_VERSION, stage="d8")
        manifest.pop("freeze_sha256")
        manifest["freeze_sha256"] = runner._digest(manifest)
        atomic_text(d9_path / "manifest.json", encoded(manifest))
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.opened_resources, 0)
        self.assertEqual(self.mode_requests, {})
        self.assertEqual(prepared["real_api_calls"], 0)

    def test_duplicate_prepare_and_execution_lock_preserve_first_manifest(self):
        self.prepare()
        original = (self.path() / "manifest.json").read_bytes()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual((self.path() / "manifest.json").read_bytes(), original)
        (self.path() / ".execution.lock").write_text("reserved", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(self.opened_resources, 0)
        self.assertEqual(self.searcher.calls, [])

    def test_unrelated_review_and_configuration_whitespace_do_not_block_execution(self):
        self.prepare()
        for name in ("artifacts/d9/agent_config.json", d9_runtime.STRATEGY_PATH, self.fixture.registry_path):
            path = self.root / name
            path.write_bytes(path.read_bytes() + b" ")
        self.assertEqual(self.execute()["status"], "completed")

    def test_two_modes_use_actual_registry_remaining_budget_and_posthoc_labels(self):
        self.prepare()
        summary = self.execute()
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(len(self.searcher.calls), 1)
        self.assertTrue(callable(self.searcher.calls[0]["remaining_seconds"]))
        self.assertIsNone(self.searcher.calls[0]["allowed_point_ids"])
        self.assertEqual(summary["actual_batch_cost"]["embedding"]["embedding_requests"], 1)
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 2)
        for mode, report in summary["records"][0]["pair"]["modes"].items():
            self.assertEqual(report["task"], "D9")
            self.assertEqual(report["status"], "answered")
            self.assertEqual(report["business_commit"]["status"], "answered")
            self.assertIsNone(report["registry_sha256"])
            self.assertEqual(report["result"]["source_scope_checks"][-1]["status"], "valid")
            self.assertTrue(report["history_report"].startswith("archive/run_logs/d9/" + mode + "_"))
            markdown = (self.root / report["history_markdown"]).read_text(encoding="utf-8")
            self.assertTrue(markdown.startswith("# D9 问答运行记录"))
            self.assertIn("来源范围与提交", markdown)
            for request in self.mode_requests[mode]:
                messages = encoded(json.loads(request.content)["messages"])
                for marker in (self.case_ids[0], "DO_NOT_SEND_EXPECTED", "answerable", "expected_evidence"):
                    self.assertNotIn(marker, messages)
        self.assertTrue(self.store.closed and self.searcher.closed)
        self.assertTrue(all(client._closed for client in self.clients.values()))
        self.assertFalse((self.root / "artifacts/d8/agent_result.json").exists())

    def test_agent_retry_passes_original_scope_whitelist_profile_and_remaining_budget(self):
        self.prepare()
        body = self.fixture.search([self.fixture.body_id])["results"]
        abstract = self.fixture.search([self.fixture.abstract_id])["results"]
        abstract[0].update(point_id=point_id(self.profile["index_profile_id"], self.fixture.abstract_id),
                           index_profile_id=self.profile["index_profile_id"])
        searcher = TimedScopedSearcher(body, abstract, profile=self.profile["index_profile_id"])
        summary = self.execute(searcher=searcher, factory=self.factory(agent=[response(retry_action()),
                                                               response(answer_action(self.fixture.abstract_id))]))
        self.assertEqual(summary["status"], "completed")
        pair = summary["records"][0]["pair"]
        self.assertEqual(pair["modes"]["fixed_rag"]["status"], "insufficient_evidence")
        self.assertEqual(pair["modes"]["agent"]["status"], "answered")
        self.assertEqual(len(self.mode_requests["fixed_rag"]), 0)
        self.assertEqual(len(self.mode_requests["agent"]), 2)
        self.assertEqual(len(searcher.calls), 2)
        second = searcher.calls[1]
        self.assertEqual(second["selected_versions"], self.fixture.pairs)
        self.assertEqual(second["top_k"], 5)
        self.assertEqual(second["allowed_point_ids"], [point_id(self.profile["index_profile_id"], self.fixture.abstract_id)])
        self.assertTrue(callable(second["remaining_seconds"]))
        self.assertEqual(pair["costs"]["actual_batch"]["embedding"]["embedding_requests"], 2)

    def test_loaded_registry_snapshot_survives_whitespace_during_chat(self):
        self.prepare()
        def changed(request):
            path = self.root / self.fixture.registry_path
            path.write_bytes(path.read_bytes() + b" ")
            return httpx.Response(200, json=completion(encoded(answer_action(self.fixture.abstract_id)["answer"])), request=request)
        summary = self.execute(factory=self.factory(fixed=[changed]))
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 2)

    def assert_committed_modes_preserved(self, summary):
        self.assertEqual(summary["status"], "attention_required")
        self.assertEqual(len(summary["records"]), 1)
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 2)
        for mode, report in summary["records"][0]["pair"]["modes"].items():
            self.assertEqual(report["status"], "answered")
            self.assertEqual(report["result"]["business_commit"]["status"], "answered")
            self.assertEqual(self.read(report["history_report"])["status"], "answered")
            self.assertEqual(self.read("artifacts/d9/" + mode + "_result.json")["status"], "answered")
        self.assertTrue((self.path() / summary["state"]["recovery_report"]).exists())

    def test_shared_resource_close_failure_is_independent_of_committed_modes(self):
        self.prepare()
        self.assert_committed_modes_preserved(self.execute(close_error=RuntimeError("offline-private-close")))

    def test_unrelated_file_change_after_modes_does_not_discard_answers(self):
        self.prepare()
        def changed_after_modes():
            path = self.root / self.fixture.registry_path
            path.write_bytes(path.read_bytes() + b" ")
        self.assertEqual(self.execute(on_close=changed_after_modes)["status"], "completed")

    def test_resume_only_unattempted_case_preserves_first_failure_history(self):
        self.prepare(case_ids=self.case_ids)
        first = self.execute(factory=self.factory(fixed=[http_error(401)]))
        self.assertEqual(first["status"], "attention_required")
        first_path = self.path() / (self.case_ids[0] + ".json")
        first_bytes = first_path.read_bytes()
        history = {name: (self.root / name).read_bytes() for report in first["records"][0]["pair"]["modes"].values()
                   for name in (report["history_report"], report["history_markdown"])}
        with self.assertRaises(ValueError):
            self.execute()
        resumed = self.execute(resume=True)
        self.assertEqual(resumed["status"], "attention_required")
        self.assertEqual(resumed["remaining_case_ids"], [])
        self.assertEqual(len(self.searcher.calls), 1)
        self.assertEqual(first_path.read_bytes(), first_bytes)
        self.assertEqual(history, {name: (self.root / name).read_bytes() for name in history})
        complete = self.execute(resume=True)
        self.assertEqual(len(self.searcher.calls), 0)
        self.assertEqual(complete["actual_batch_cost"], resumed["actual_batch_cost"])

    def test_attempt_reservation_without_final_record_cannot_replay(self):
        self.prepare()
        manifest = self.read("artifacts/d9/comparison/offline-d9/manifest.json")
        exclusive_json(self.path() / (self.case_ids[0] + ".attempt.json"),
                       {"case_id": self.case_ids[0], "freeze_sha256": manifest["freeze_sha256"]})
        with self.assertRaises(ValueError):
            self.execute(resume=True)
        self.assertEqual(self.opened_resources, 0)
        self.assertEqual(self.searcher.calls, [])


class D9ExportChecks(export_fixtures.FixedModeExportChecks):
    # Inherit the two existing D8 checks as explicit compatibility evidence.
    def test_same_id_isolated_by_stage_and_mode_and_duplicate_keeps_latest(self):
        old = agent_export.save_agent_run(self.agent_report("same-id"), project_root=self.root)
        old_paths = (old["history_report"], old["history_markdown"], "artifacts/d8/agent_result.json", "artifacts/d8/agent_result.md")
        before = {name: (self.root / name).read_bytes() for name in old_paths}
        report = self.agent_report("same-id")
        report["task"] = "D9"
        saved = agent_export.save_agent_run(report, project_root=self.root)
        self.assertEqual(saved["export_version"], agent_export.D9_AGENT_EXPORT_VERSION)
        fixed = {"task": "D9", "mode": "fixed_rag", "run_id": "same-id", "result": self.fixed_result()}
        fixed_saved = agent_export.save_agent_run(fixed, project_root=self.root)
        self.assertNotEqual(saved["history_report"], fixed_saved["history_report"])
        latest = (self.root / "artifacts/d9/agent_result.json").read_bytes()
        duplicate = agent_export.save_agent_run(report, project_root=self.root)
        self.assertEqual(duplicate["error"]["code"], "history_exists")
        self.assertEqual((self.root / "artifacts/d9/agent_result.json").read_bytes(), latest)
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in old_paths})

    def test_d9_export_failure_keeps_committed_result_usage_in_d9_recovery(self):
        report = self.agent_report("failure")
        report["task"] = "D9"
        report["result"]["business_commit"] = {"status": "answered", "committed": True}
        with patch.object(agent_export, "_exclusive_text", side_effect=OSError("private-export-fault")):
            failed = agent_export.save_agent_run(report, project_root=self.root)
        self.assertEqual(failed["status"], "tool_error")
        self.assertIsNone(failed["answer"])
        self.assertEqual(failed["pre_export_result"], report["result"])
        self.assertEqual(failed["result"]["statistics"], report["result"]["statistics"])
        self.assertTrue(failed["export"]["recovery_saved"])
        self.assertTrue(failed["export"]["recovery_history_report"].startswith("archive/run_logs/d9/"))
        self.assertFalse((self.root / "artifacts/d8").exists())
        self.assertNotIn("private-export-fault", encoded(failed))

    def test_d9_renderer_top_failure_hides_nested_success_without_mutating_diagnostics(self):
        report = self.agent_report("render-failed")
        report["task"] = "D9"
        saved = agent_export.save_agent_run(report, project_root=self.root)
        saved.update(status="tool_error", answer=None, error={"code": "renderer_top_error"}, stop_reason="renderer_top_error")
        before = deepcopy(saved)
        markdown = agent_export.render_agent_run(saved)
        self.assertIn("本轮没有可发布答案", markdown)
        self.assertIn("renderer_top_error", markdown)
        for claim in saved["result"]["answer"]["claims"]:
            self.assertNotIn(claim["claim"], markdown)
            self.assertIn(claim["claim"], encoded(saved))
        self.assertEqual(saved, before)






def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
