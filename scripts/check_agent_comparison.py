"""D8 E: offline paired-run checks through the actual SDK and local PDFs.

This suite does not load .env, open production stores or call model APIs. It
preserves separate E reports and never rewrites the existing B/C/D evidence.
"""

from copy import deepcopy
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

import httpx

from paper_assistant.answer_export import atomic_text, exclusive_json
from paper_assistant.context import ContextError
from paper_assistant.config import EmbeddingSettings, RerankSettings
from paper_assistant.hybrid_search import HybridEvidenceSearcher
from paper_assistant.rerank_client import RerankClient
from paper_assistant.indexing import make_index_profile
from paper_assistant.llm_client import ChatBudget, ChatPolicy, LLMCallError
from paper_assistant.search import SearchError
from scripts import check_agent
from scripts.check_agent import (
    AgentFixture, QUESTION, RETRY_QUERY, SequencedSearcher, answer_action,
    encoded, insufficient_action, response, retry_action,
)
from scripts.check_llm import completion, http_error


ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    "paper_assistant/agent_comparison.py", "paper_assistant/agent_runtime.py",
    "paper_assistant/agent_evaluation.py",
    "paper_assistant/agent.py", "paper_assistant/agent_context.py",
    "paper_assistant/agent_actions.py", "paper_assistant/agent_prompt.py",
    "paper_assistant/agent_export.py", "paper_assistant/agent_records.py",
    "paper_assistant/answer_export.py", "paper_assistant/rag.py",
    "paper_assistant/evaluation.py", "paper_assistant/context.py",
    "paper_assistant/config.py", "paper_assistant/indexing.py", "paper_assistant/search.py",
    "paper_assistant/citations.py", "paper_assistant/generation.py",
    "paper_assistant/llm_client.py", "paper_assistant/schemas.py",
    "scripts/answer_question_agent.py", "scripts/run_agent_comparison.py",
    "scripts/run_retrieval_comparison.py", "scripts/check_generation.py",
    "scripts/check_agent_comparison.py", "scripts/check_agent.py",
    "scripts/check_rag.py", "scripts/check_llm.py",
]


class PairedFixture(AgentFixture):
    def factory(self, *, fixed=None, agent=None, setup_seconds=None,
                close_seconds=None, setup_error=None, close_error=None):
        outcomes = {
            "fixed_rag": fixed if fixed is not None else [response(self.draft())],
            "agent": agent if agent is not None else [response(answer_action())],
        }
        self.mode_clients, self.mode_requests, self.factory_calls = {}, {}, []
        setup_seconds, close_seconds = setup_seconds or {}, close_seconds or {}

        def create(mode, budget):
            self.factory_calls.append({"mode": mode, "budget": budget,
                                       "remaining_at_factory": budget.remaining_seconds()})
            self.clock.advance(setup_seconds.get(mode, 0))
            if setup_error and mode in setup_error:
                raise setup_error[mode]
            client, requests = self.client(*outcomes[mode], budget=budget)
            self.mode_clients[mode], self.mode_requests[mode] = client, requests
            original_close = client.close

            def close():
                if not client._closed:
                    self.clock.advance(close_seconds.get(mode, 0))
                    original_close()
                    if close_error and mode in close_error:
                        raise close_error[mode]

            client.close = close
            return client

        return create

    def paired(self, *, searcher=None, factory=None, query=QUESTION, pairs=None,
               policy=None, **kwargs):
        from paper_assistant.agent_comparison import run_paired_case
        self.searcher = searcher or SequencedSearcher([self.row])
        return run_paired_case(query, [("p1", "r1")] if pairs is None else pairs,
                               self.searcher, self.store, factory or self.factory(),
                               project_root=self.root, policy=policy, clock=self.clock, **kwargs)

    def mode_result(self, pair, mode):
        return pair["modes"][mode]["result"]

    def assert_no_paid_mode(self):
        self.assertEqual(self.factory_calls, [])
        self.assertEqual(self.mode_requests, {})


class PairedExecutionChecks(PairedFixture):
    def test_actual_shared_retrieval_once_and_two_independent_closed_clients(self):
        pair = self.paired()
        self.assertEqual(len(self.searcher.calls), 1)
        self.assertEqual(self.searcher.calls[0], (QUESTION, [("p1", "r1")], 5))
        self.assertEqual(set(pair["modes"]), {"fixed_rag", "agent"})
        for mode in ("fixed_rag", "agent"):
            self.assertEqual(self.mode_result(pair, mode)["status"], "answered")
            self.assertEqual(len(self.mode_requests[mode]), 1)
            self.assertTrue(self.mode_clients[mode]._closed)
        self.assertIsNot(self.factory_calls[0]["budget"], self.factory_calls[1]["budget"])
        self.assertFalse(self.searcher.closed)
        self.assertFalse(self.store.closed)
        fixed = self.mode_result(pair, "fixed_rag")["context"]["shown_evidence"]
        first = self.mode_result(pair, "agent")["initial_context"]["shown_evidence"]
        self.assertEqual(fixed, first)

    def test_retry_adds_one_actual_search_without_repeating_shared_search(self):
        new = self.add_chunk()
        factory = self.factory(agent=[response(retry_action()), response(answer_action(new["chunk_id"]))])
        dense = SequencedSearcher([self.row], [new])
        requests = []

        def rerank_response(request):
            requests.append(request)
            documents = json.loads(request.content)["documents"]
            return httpx.Response(200, json={"results": [
                {"index": index, "relevance_score": 1.0 / (index + 1)}
                for index in range(len(documents))], "usage": {"total_tokens": 13}})

        with RerankClient(RerankSettings("qwen3-rerank", "offline-rerank-key",
            "https://example.invalid/compatible-api/v1"), transport=httpx.MockTransport(rerank_response)) as reranker:
            pair = self.paired(searcher=HybridEvidenceSearcher(dense, self.store, reranker), factory=factory)
        self.assertEqual(dense.calls, [(QUESTION, [("p1", "r1")], 20),
                                      (RETRY_QUERY, [("p1", "r1")], 20)])
        self.assertEqual(self.mode_result(pair, "agent")["status"], "answered")
        self.assertEqual(self.mode_result(pair, "agent")["statistics"]["embedding"]["embedding_requests"], 2)
        self.assertEqual(len(self.mode_requests["fixed_rag"]), 1)
        self.assertEqual(len(self.mode_requests["agent"]), 2)
        self.assertEqual(len(requests), 2)
        self.assertEqual(pair["costs"]["actual_batch"]["rerank"]["requests"], 2)
        self.assertEqual(pair["costs"]["standalone_logical"]["fixed_rag"]["rerank"]["requests"], 1)
        self.assertEqual(pair["costs"]["standalone_logical"]["agent"]["rerank"]["requests"], 2)
        self.assertEqual(pair["modes"]["fixed_rag"]["network_requests"], 3)
        self.assertEqual(pair["modes"]["agent"]["network_requests"], 6)
        self.assertEqual(self.mode_result(pair, "agent")["context"]["ranking_method"], "retry_then_initial")

    def test_shared_elapsed_is_charged_to_both_but_other_mode_wait_is_excluded(self):
        def delayed_fixed(request):
            self.clock.advance(25)
            return httpx.Response(200, json=completion(encoded(self.draft())), request=request)

        factory = self.factory(fixed=[delayed_fixed])
        searcher = SequencedSearcher([self.row], on_search=lambda _: self.clock.advance(20))
        pair = self.paired(searcher=searcher, factory=factory)
        self.assertEqual(pair["shared_first_retrieval"]["elapsed_seconds"], 20)
        self.assertEqual([call["remaining_at_factory"] for call in self.factory_calls], [100, 100])
        self.assertEqual(self.factory_calls[1]["budget"].started - self.factory_calls[0]["budget"].started, 25)
        self.assertEqual(self.mode_result(pair, "agent")["status"], "answered")

    def test_shared_deadline_prevents_both_chat_clients(self):
        factory = self.factory()
        pair = self.paired(searcher=SequencedSearcher([self.row], on_search=lambda _: self.clock.advance(120)),
                           factory=factory)
        self.assert_no_paid_mode()
        for mode in ("fixed_rag", "agent"):
            self.assertEqual(self.mode_result(pair, mode)["status"], "budget_exceeded")
            self.assertIsNone(self.mode_result(pair, mode)["answer"])

    def test_shared_search_failure_preserves_statistics_and_does_not_start_modes(self):
        factory = self.factory()
        stats = {"embedding_requests": 1, "failed_requests": 1, "total_tokens": 7}
        pair = self.paired(searcher=SequencedSearcher(SearchError("synthetic failure", stage="query", statistics=stats)),
                           factory=factory)
        self.assert_no_paid_mode()
        self.assertEqual(pair["status"], "tool_error")
        self.assertEqual(pair["shared_first_retrieval"]["statistics"], stats)
        self.assertEqual(len(self.searcher.calls), 1)

    def test_fixed_failure_does_not_prevent_agent_first_output(self):
        pair = self.paired(factory=self.factory(fixed=[http_error(401)]))
        self.assertEqual(self.mode_result(pair, "fixed_rag")["status"], "tool_error")
        self.assertEqual(self.mode_result(pair, "agent")["status"], "answered")
        self.assertEqual(len(self.searcher.calls), 1)
        self.assertTrue(all(client._closed for client in self.mode_clients.values()))

    def test_initialization_time_consumes_mode_budget_before_chat(self):
        pair = self.paired(factory=self.factory(setup_seconds={"fixed_rag": 121}))
        self.assertEqual(self.mode_result(pair, "fixed_rag")["status"], "budget_exceeded")
        self.assertEqual(self.mode_requests["fixed_rag"], [])
        self.assertTrue(self.mode_clients["fixed_rag"]._closed)
        self.assertEqual(self.mode_result(pair, "agent")["status"], "answered")
        self.assertEqual(self.factory_calls[1]["remaining_at_factory"], 120)

    def test_client_close_time_rechecks_terminal_and_keeps_consumed_calls(self):
        pair = self.paired(factory=self.factory(close_seconds={"fixed_rag": 121}))
        fixed = self.mode_result(pair, "fixed_rag")
        self.assertEqual(fixed["status"], "budget_exceeded")
        self.assertIsNone(fixed["answer"])
        self.assertEqual(fixed["statistics"]["chat"]["http_request_attempts"], 1)
        self.assertEqual(fixed["statistics"]["chat"]["total_tokens"], 25)
        self.assertTrue(self.mode_clients["fixed_rag"]._closed)
        self.assertEqual(self.mode_result(pair, "agent")["status"], "answered")

    def test_factory_error_is_safe_and_other_mode_still_runs(self):
        factory = self.factory(setup_error={"fixed_rag": LLMCallError(
            "tool_error", "client_setup_error", "Synthetic client setup failed")})
        pair = self.paired(factory=factory)
        self.assertEqual(self.mode_result(pair, "fixed_rag")["status"], "tool_error")
        self.assertIsNone(self.mode_result(pair, "fixed_rag")["answer"])
        self.assertEqual(self.mode_result(pair, "agent")["status"], "answered")
        self.assertEqual(len(self.mode_requests["agent"]), 1)

    def test_client_close_error_preserves_consumed_usage_and_clears_answer(self):
        pair = self.paired(factory=self.factory(close_error={"fixed_rag": OSError("private close failure")}))
        fixed = self.mode_result(pair, "fixed_rag")
        self.assertEqual(fixed["status"], "tool_error")
        self.assertIsNone(fixed["answer"])
        self.assertEqual(fixed["statistics"]["chat"]["http_request_attempts"], 1)
        self.assertEqual(fixed["statistics"]["chat"]["total_tokens"], 25)
        self.assertTrue(self.mode_clients["fixed_rag"]._closed)
        self.assertNotIn("private close failure", encoded(pair))
        self.assertEqual(self.mode_result(pair, "agent")["status"], "answered")

    def test_shared_failure_after_deadline_keeps_embedding_cost_and_wins_as_budget(self):
        stats = {"embedding_requests": 1, "failed_requests": 1, "total_tokens": 7}
        searcher = SequencedSearcher(SearchError("synthetic", stage="query", statistics=stats),
                                    on_search=lambda _: self.clock.advance(121))
        pair = self.paired(searcher=searcher, factory=self.factory())
        self.assert_no_paid_mode()
        self.assertEqual(pair["status"], "budget_exceeded")
        self.assertEqual(pair["shared_first_retrieval"]["statistics"], stats)

    def test_stale_shared_search_envelope_never_reaches_either_model(self):
        for field, value in (("query", "different original question"),
                             ("selected_versions", [{"paper_id": "p2", "parse_revision": "r2"}]),
                             ("top_k", 4)):
            with self.subTest(field=field):
                def outcome(query, selected_versions, top_k):
                    envelope = SequencedSearcher([self.row]).search_evidence(query, selected_versions, top_k)
                    envelope[field] = value
                    return envelope
                pair = self.paired(searcher=SequencedSearcher(outcome), factory=self.factory())
                self.assert_no_paid_mode()
                self.assertEqual(pair["status"], "tool_error")
                self.assertEqual(len(self.searcher.calls), 1)

    def test_invalid_scope_is_refused_before_initial_embedding_or_client(self):
        for query, pairs in ((None, [("p1", "r1")]), (" \n", [("p1", "r1")]),
                             (QUESTION, []), (QUESTION, [("p1", "r1"), ("p1", "r1")]),
                             (QUESTION, [(" p1", "r1")])):
            with self.subTest(query=query, pairs=pairs):
                pair = self.paired(query=query, pairs=pairs, factory=self.factory())
                self.assert_no_paid_mode()
                self.assertEqual(self.searcher.calls, [])
                self.assertEqual(pair["status"], "tool_error")


class RuntimeDeadlineChecks(AgentFixture):
    def test_configuration_error_after_deadline_keeps_failure_and_returns_budget(self):
        from paper_assistant import agent_runtime as runtime
        strategy = self.root / runtime.STRATEGY_PATH
        strategy.parent.mkdir(parents=True, exist_ok=True)
        strategy.write_text('{"schema_revision":"offline-runtime-strategy"}', encoding="utf-8")
        binding = {"source_sha256": {}, "protected_sha256": {
            runtime.STRATEGY_PATH: hashlib.sha256(strategy.read_bytes()).hexdigest()}}

        def configuration_error():
            self.clock.advance(121)
            raise ValueError("private configuration failure")

        changes = {"changed_source_paths": [], "changed_paths": [], "added_paths": [], "inventory_error": False}
        with patch.object(runtime, "ChatBudget", side_effect=lambda policy: ChatBudget(policy, clock=self.clock)), \
                patch.object(runtime, "load_embedding_settings", side_effect=configuration_error), \
                patch.object(runtime, "load_llm_settings", side_effect=AssertionError("env must not load")), \
                patch.object(runtime, "open_retrieval_resources", side_effect=AssertionError("stores must not open")):
            report = runtime.run_question_agent(QUESTION, [("p1", "r1")], project_root=self.root)
        self.assertEqual(report["status"], "budget_exceeded")
        self.assertEqual(report["error"]["code"], "deadline_exceeded")
        self.assertIsNone(report["answer"])
        self.assertEqual(report["chat_statistics"]["http_request_attempts"], 0)
        self.assertEqual(report["embedding_requests"], 0)
        self.assertNotIn("private configuration failure", encoded(report))
        self.assertEqual(report["export"]["status"], "completed")


class FrozenRetrievalChecks(AgentFixture):
    def envelope(self):
        return SequencedSearcher([self.row]).search_evidence(QUESTION, [("p1", "r1")], 5)

    def test_snapshot_and_each_modes_return_are_isolated_deep_copies(self):
        from paper_assistant.agent_comparison import FrozenFirstSearcher
        snapshot = self.envelope()
        first = FrozenFirstSearcher(snapshot, QUESTION, [("p1", "r1")], SequencedSearcher())
        second = FrozenFirstSearcher(snapshot, QUESTION, [("p1", "r1")], SequencedSearcher())
        snapshot["results"][0]["text"] = "tampered caller snapshot"
        replay = first.search_evidence(QUESTION, [("p1", "r1")], 5)
        self.assertEqual(replay["results"][0]["text"], self.row["text"])
        replay["results"][0]["text"] = "tampered first mode"
        self.assertEqual(second.search_evidence(QUESTION, [("p1", "r1")], 5)["results"][0]["text"], self.row["text"])

    def test_scope_mismatch_is_refused_without_consuming_replay_or_request(self):
        from paper_assistant.agent_comparison import FrozenFirstSearcher
        live = SequencedSearcher([self.row])
        adapter = FrozenFirstSearcher(self.envelope(), QUESTION, [("p1", "r1")], live, allow_retry=True)
        for query, pairs, top_k in (("other question", [("p1", "r1")], 5),
                                    (QUESTION, [("p2", "r2")], 5),
                                    (QUESTION, [("p1", "r1")], True)):
            with self.subTest(query=query, pairs=pairs, top_k=top_k):
                with self.assertRaises((SearchError, ContextError)):
                    adapter.search_evidence(query, pairs, top_k)
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(live.calls, [])
        self.assertEqual(adapter.search_evidence(QUESTION, [("p1", "r1")], 5)["query"], QUESTION)

    def test_third_retrieval_is_refused_before_live_search(self):
        from paper_assistant.agent_comparison import FrozenFirstSearcher
        live = SequencedSearcher([self.row])
        adapter = FrozenFirstSearcher(self.envelope(), QUESTION, [("p1", "r1")], live, allow_retry=True)
        adapter.search_evidence(QUESTION, [("p1", "r1")], 5)
        adapter.search_evidence(RETRY_QUERY, [("p1", "r1")], 5)
        with self.assertRaises((SearchError, ContextError)):
            adapter.search_evidence("third query", [("p1", "r1")], 5)
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(len(live.calls), 1)
        self.assertEqual(len(adapter.actual_retry_rounds), 1)

    def test_fixed_adapter_cannot_open_live_retry(self):
        from paper_assistant.agent_comparison import FrozenFirstSearcher
        live = SequencedSearcher([self.row])
        adapter = FrozenFirstSearcher(self.envelope(), QUESTION, [("p1", "r1")], live)
        adapter.search_evidence(QUESTION, [("p1", "r1")], 5)
        with self.assertRaises((SearchError, ContextError)):
            adapter.search_evidence(RETRY_QUERY, [("p1", "r1")], 5)
        self.assertEqual(live.calls, [])

    def test_mismatched_historical_snapshot_itself_is_refused(self):
        from paper_assistant.agent_comparison import FrozenFirstSearcher
        for field, value in (("query", "stale question"),
                             ("selected_versions", [{"paper_id": "p2", "parse_revision": "r2"}]),
                             ("top_k", 4)):
            with self.subTest(field=field):
                snapshot = self.envelope()
                snapshot[field] = value
                live = SequencedSearcher()
                with self.assertRaises((SearchError, ContextError)):
                    adapter = FrozenFirstSearcher(snapshot, QUESTION, [("p1", "r1")], live)
                    adapter.search_evidence(QUESTION, [("p1", "r1")], 5)
                self.assertEqual(live.calls, [])


class PairedCostChecks(PairedFixture):
    def test_shared_actual_count_is_once_but_logical_each_mode_count_is_one(self):
        pair = self.paired()
        actual = pair["costs"]["actual_batch"]
        logical = pair["costs"]["standalone_logical"]
        self.assertEqual(actual["embedding"]["embedding_requests"], 1)
        self.assertEqual(actual["embedding"]["total_tokens"], 7)
        self.assertEqual(actual["chat"]["http_request_attempts"], 2)
        self.assertEqual(actual["chat"]["total_tokens"], 50)
        for mode in ("fixed_rag", "agent"):
            self.assertEqual(logical[mode]["embedding"]["embedding_requests"], 1)
            self.assertEqual(logical[mode]["embedding"]["total_tokens"], 7)
            self.assertEqual(pair["modes"][mode]["network_requests"], 2)
            self.assertEqual(pair["modes"][mode]["llm_requests"], 1)

    def test_retry_actual_embedding_is_two_and_logical_counts_are_one_and_two(self):
        new = self.add_chunk()
        pair = self.paired(searcher=SequencedSearcher([self.row], [new]),
                           factory=self.factory(agent=[response(retry_action()), response(answer_action(new["chunk_id"]))]))
        actual, logical = pair["costs"]["actual_batch"], pair["costs"]["standalone_logical"]
        self.assertEqual(actual["embedding"]["embedding_requests"], 2)
        self.assertEqual(actual["chat"]["http_request_attempts"], 3)
        self.assertEqual(logical["fixed_rag"]["embedding"]["embedding_requests"], 1)
        self.assertEqual(logical["agent"]["embedding"]["embedding_requests"], 2)
        self.assertEqual(pair["modes"]["agent"]["network_requests"], 4)

    def test_missing_usage_has_null_batch_total_and_explicit_known_subtotals(self):
        fixed = [(200, completion(encoded(self.draft()), usage=None))]
        pair = self.paired(factory=self.factory(fixed=fixed))
        actual = pair["costs"]["actual_batch"]
        self.assertIsNone(actual["chat"]["total_tokens"])
        self.assertEqual(actual["chat"]["known_total_tokens"], 25)
        self.assertIsNone(pair["costs"]["standalone_logical"]["fixed_rag"]["chat"]["total_tokens"])
        self.assertEqual(actual["chat"]["http_request_attempts"], 2)

        from paper_assistant.agent_comparison import run_current_case, summarize_current_costs

        # Current runtime ledgers include preparation and every decision/repair.
        configuration = {"chat": {"provider": "offline", "model_id": "offline-model"},
                         "policy": {"max_tokens": 4096, "max_attempts": None}}
        fixed = {"mode": "fixed_rag", "status": "tool_error", "configuration": configuration,
            "conversation_preparation": {"status": "completed"},
            "embedding_statistics": {"embedding_requests": 1, "failed_requests": 1,
                "total_tokens": None, "known_total_tokens": 5, "provider_elapsed_seconds": None,
                "known_provider_elapsed_seconds": 0.2, "embedding_elapsed_seconds": 0.4,
                "query_elapsed_seconds": 0.2, "total_elapsed_seconds": 0.6},
            "chat_statistics": {"sdk_request_attempts": 2, "http_request_attempts": 2,
                "network_retries": 0, "repairs": 0, "total_tokens": None,
                "known_total_tokens": 15, "elapsed_seconds": 1.5},
            "rerank_statistics": {"requests": 1, "elapsed_seconds": 0.2,
                "rounds": [{"requests": 1, "elapsed_seconds": 0.2, "usage": {"total_tokens": 11}}]},
            "network_requests": 4, "result": {"status": "tool_error", "search_rounds": [{"round": 1}],
                "stop_reason": "search_error"}}
        agent = {"mode": "agent", "status": "answered", "configuration": deepcopy(configuration),
            "conversation_preparation": {"status": "completed"},
            "embedding_statistics": {"embedding_requests": 5, "failed_requests": 0,
                "total_tokens": 35, "provider_elapsed_seconds": 1.0, "embedding_elapsed_seconds": 1.4,
                "query_elapsed_seconds": 0.6, "total_elapsed_seconds": 2.0},
            "chat_statistics": {"sdk_request_attempts": 9, "http_request_attempts": 9,
                "network_retries": 1, "repairs": 1, "total_tokens": None,
                "known_total_tokens": 150, "elapsed_seconds": 6.0},
            "rerank_statistics": {"requests": 5, "elapsed_seconds": 1.0, "rounds": [
                {"requests": 1, "elapsed_seconds": 0.2,
                 "usage": {"total_tokens": 2} if number < 5 else None} for number in range(1, 6)]},
            "network_requests": 19, "result": {"status": "answered", "autonomous_steps_used": 5,
                "limit_finalize": True, "stop_reason": "step_limit_answered",
                "search_rounds": [{"round": number, "kind": "adaptive"} for number in range(1, 6)]}}
        calls, completed = [], []

        def runtime_runner(question, versions, **kwargs):
            calls.append((question, deepcopy(versions), kwargs))
            return deepcopy(fixed if kwargs["mode"] == "fixed_rag" else agent)

        current = run_current_case(QUESTION, [("p1", "r1")], project_root=self.root,
            runtime_runner=runtime_runner, on_mode_result=lambda mode, report: completed.append((mode, report["status"])))
        self.assertEqual([call[2]["mode"] for call in calls], ["fixed_rag", "agent"])
        self.assertTrue(all(call[0] == QUESTION and call[1] == [("p1", "r1")]
                            and call[2]["library_mode"] for call in calls))
        self.assertEqual(completed, [("fixed_rag", "tool_error"), ("agent", "answered")])
        self.assertEqual(current["status"], "tool_error")
        self.assertNotIn("shared_first_retrieval", current)
        self.assertEqual(current["modes"]["fixed_rag"]["configuration"], configuration)
        self.assertEqual(current["modes"]["agent"]["result"]["autonomous_steps_used"], 5)
        self.assertTrue(current["modes"]["agent"]["result"]["limit_finalize"])
        costs = summarize_current_costs([current])
        self.assertEqual(costs, current["costs"])
        actual = costs["actual_batch"]
        self.assertEqual(actual["embedding"]["embedding_requests"], 6)
        self.assertEqual(actual["embedding"]["failed_requests"], 1)
        self.assertIsNone(actual["embedding"]["total_tokens"])
        self.assertEqual(actual["embedding"]["known_total_tokens"], 40)
        self.assertEqual(actual["embedding"]["total_elapsed_seconds"], 2.6)
        self.assertIsNone(actual["embedding"]["provider_elapsed_seconds"])
        self.assertEqual(actual["embedding"]["known_provider_elapsed_seconds"], 1.2)
        self.assertEqual(actual["chat"]["sdk_request_attempts"], 11)
        self.assertEqual(actual["chat"]["http_request_attempts"], 11)
        self.assertEqual(actual["chat"]["network_retries"], 1)
        self.assertEqual(actual["chat"]["repairs"], 1)
        self.assertIsNone(actual["chat"]["total_tokens"])
        self.assertEqual(actual["chat"]["known_total_tokens"], 165)
        self.assertEqual(actual["chat"]["elapsed_seconds"], 7.5)
        self.assertEqual(actual["rerank"]["requests"], 6)
        self.assertIsNone(actual["rerank"]["total_tokens"])
        self.assertEqual(actual["rerank"]["known_total_tokens"], 19)
        self.assertEqual(actual["rerank"]["elapsed_seconds"], 1.2)
        self.assertEqual(actual["runtime"]["network_requests"], 23)
        self.assertEqual(costs["per_mode"]["agent"]["chat"]["http_request_attempts"], 9)
        self.assertEqual(costs["per_mode"]["fixed_rag"]["embedding"]["known_total_tokens"], 5)

        # An escaped runtime failure has unknown costs; it still permits the other mode.
        calls.clear()

        def failed_runtime(question, versions, **kwargs):
            calls.append(kwargs["mode"])
            if kwargs["mode"] == "fixed_rag":
                raise OSError("offline runtime failure")
            return deepcopy(agent)

        failed = run_current_case(QUESTION, [("p1", "r1")], project_root=self.root, runtime_runner=failed_runtime)
        self.assertEqual(calls, ["fixed_rag", "agent"])
        self.assertIsNone(failed["costs"]["actual_batch"]["embedding"]["embedding_requests"])
        self.assertEqual(failed["costs"]["actual_batch"]["embedding"]["known_embedding_requests"], 5)
        self.assertIsNone(failed["costs"]["actual_batch"]["rerank"]["requests"])
        batch = summarize_current_costs([current, failed])
        self.assertIsNone(batch["actual_batch"]["embedding"]["embedding_requests"])
        self.assertEqual(batch["actual_batch"]["embedding"]["known_embedding_requests"], 11)
        partial = summarize_current_costs([{"modes": {"fixed_rag": current["modes"]["fixed_rag"]}}])
        self.assertEqual(partial["actual_batch"]["chat"]["components"], 1)
        self.assertEqual(partial["per_mode"]["agent"]["chat"]["components"], 0)

        calls.clear()

        def interrupted_save(mode, report):
            raise OSError("offline progress save failure")

        with self.assertRaises(OSError):
            run_current_case(QUESTION, [("p1", "r1")], project_root=self.root,
                             runtime_runner=failed_runtime, on_mode_result=interrupted_save)
        self.assertEqual(calls, ["fixed_rag"])

    def test_partial_usage_inside_one_mode_contributes_its_known_chat_subtotal(self):
        pair = self.paired(factory=self.factory(fixed=[http_error(503), response(self.draft())]))
        fixed = pair["costs"]["standalone_logical"]["fixed_rag"]["chat"]
        actual = pair["costs"]["actual_batch"]["chat"]
        self.assertIsNone(fixed["total_tokens"])
        self.assertEqual(fixed["known_total_tokens"], 25)
        self.assertIsNone(actual["total_tokens"])
        self.assertEqual(actual["known_total_tokens"], 50)
        self.assertEqual(actual["http_request_attempts"], 3)

    def test_failed_retry_preserves_actual_paid_embedding_and_partial_usage(self):
        fault = SearchError("synthetic retry fault", stage="query", statistics={
            "embedding_requests": 1, "failed_requests": 1, "total_tokens": None})
        pair = self.paired(searcher=SequencedSearcher([self.row], fault),
                           factory=self.factory(agent=[response(retry_action())]))
        actual = pair["costs"]["actual_batch"]["embedding"]
        self.assertEqual(actual["embedding_requests"], 2)
        self.assertEqual(actual["failed_requests"], 1)
        self.assertIsNone(actual["total_tokens"])
        self.assertEqual(actual["known_total_tokens"], 7)
        self.assertEqual(self.mode_result(pair, "agent")["status"], "tool_error")
        self.assertIsNone(self.mode_result(pair, "agent")["answer"])
        self.assertEqual(pair["costs"]["standalone_logical"]["agent"]["embedding"]["known_total_tokens"], 7)


class PairedScoringChecks(AgentFixture):
    def case(self, row=None, **changes):
        row = row or self.row
        return {"case_id": "offline-paired-target", "split": "dev", "question": QUESTION,
                "paper_ids": ["p1"], "answerable": True, "question_type": "synthetic_fact",
                "expected_evidence": [{"paper_id": row["paper_id"], "pdf_page": row["pdf_page"],
                                       "pdf_sha256": row["pdf_sha256"], "quote": row["text"]}], **changes}

    def report(self, result):
        return {"task": "D8", "mode": "agent", "status": result["status"],
                "selected_versions": deepcopy(result["selected_versions"]),
                "answer": deepcopy(result["answer"]), "result": deepcopy(result)}

    def scored(self, result, case=None):
        from paper_assistant.agent_evaluation import score_agent_case
        return score_agent_case(case or self.case(), self.report(result))

    def test_actual_retry_target_stages_and_pure_scoring(self):
        from paper_assistant.agent_evaluation import score_agent_case
        new = self.add_chunk(text="The exact second target from the supplementary source.")
        client, _ = self.client(response(retry_action()), response(answer_action(new["chunk_id"])))
        with client:
            result = self.run_agent(client, searcher=SequencedSearcher([self.row], [new]))
        case, report = self.case(new), self.report(result)
        originals = deepcopy((case, report))
        score = score_agent_case(case, report)
        self.assertEqual((case, report), originals)
        stages = score["stage_metrics"]
        self.assertFalse(stages["initial_returned"]["all_targets_hit"])
        self.assertFalse(stages["initial_shown"]["all_targets_hit"])
        for name in ("retry_returned", "retry_shown", "merged_returned", "final_shown"):
            self.assertTrue(stages[name]["all_targets_hit"], name)
        self.assertEqual(score["evidence_changes"]["new_recalled_shown_ids"], [new["chunk_id"]])
        self.assertEqual(score["citation_location"], {"numerator": 1, "denominator": 1, "ratio": 1.0})
        self.assertIsNone(score["qa_accuracy"])
        self.assertEqual(score["semantic_support_status"], "not_reviewed")
        self.assertEqual(score["human_review_status"], "pending")

    def test_returned_target_omitted_from_final_display_is_a_shown_miss(self):
        initial = self.add_chunk("target-initial", text="initialtarget")
        retry = self.add_chunk("supplement-cap", text="nexttarget!")
        client, _ = self.client(response(retry_action()), response(insufficient_action()))
        with client:
            result = self.run_agent(client, searcher=SequencedSearcher([initial], [retry]), max_chars=13)
        score = self.scored(result, self.case(initial))
        self.assertTrue(score["stage_metrics"]["initial_shown"]["all_targets_hit"])
        self.assertTrue(score["stage_metrics"]["merged_returned"]["all_targets_hit"])
        self.assertFalse(score["stage_metrics"]["final_shown"]["all_targets_hit"])
        self.assertFalse(score["exact_all_targets_hit_shown"])

    def test_conflicting_pdf_identity_cannot_be_joined_into_final_shown(self):
        client, _ = self.client(response(answer_action()))
        with client:
            result = self.run_agent(client)
        conflicting = deepcopy(result["search_rounds"][0])
        conflicting["round"] = 2
        conflicting["search"]["results"][0]["pdf_sha256"] = "f" * 64
        result["search_rounds"].append(conflicting)
        score = self.scored(result)
        self.assertIn(self.row["chunk_id"], score["identity_conflicts"])
        self.assertFalse(score["stage_metrics"]["final_shown"]["all_targets_hit"])

    def test_truncated_or_forged_final_shown_text_does_not_establish_target_hit(self):
        client, _ = self.client(response(answer_action()))
        with client:
            original = self.run_agent(client)
        for field, value in (("shown_text", self.row["text"][:-1]),
                             ("shown_text_sha256", "f" * 64),
                             ("shown_char_end", len(self.row["text"]) - 1),
                             ("pdf_sha256", "f" * 64)):
            with self.subTest(field=field):
                result = deepcopy(original)
                result["context"]["shown_evidence"][0][field] = value
                score = self.scored(result)
                self.assertFalse(score["stage_metrics"]["final_shown"]["all_targets_hit"])

    def test_failed_attempt_is_kept_in_initial_and_final_denominators(self):
        from paper_assistant.agent_evaluation import summarize_agent_cases
        client, _ = self.client()
        with client:
            failed = self.run_agent(client, searcher=SequencedSearcher(SearchError("synthetic query fault")))
        score = self.scored(failed)
        self.assertEqual(score["status"], "tool_error")
        self.assertFalse(score["stage_metrics"]["initial_returned"]["all_targets_hit"])
        summary = summarize_agent_cases([score])
        self.assertEqual(summary["attempted_count"], 1)
        self.assertEqual(summary["stage_metrics"]["initial_returned"]["all_targets_hit"]["denominator"], 1)
        self.assertEqual(summary["stage_metrics"]["final_shown"]["all_targets_hit"]["denominator"], 1)
        self.assertEqual(summary["stage_metrics"]["retry_returned"]["all_targets_hit"]["denominator"], 0)

    def test_parse_intercept_and_unknown_usage_are_not_imputed_as_success_or_zero(self):
        client, _ = self.client(response("bad"), (200, completion(encoded(insufficient_action()), usage=None)))
        with client:
            result = self.run_agent(client)
        score = self.scored(result)
        self.assertEqual(score["raw_parse_intercepts"], 1)
        self.assertEqual(score["status"], "insufficient_evidence")
        self.assertIsNone(score["tokens"]["chat"])
        self.assertEqual(score["tokens"]["known_chat"], 25)


class BatchExecutionChecks(PairedFixture):
    def setUp(self):
        super().setUp()
        from paper_assistant import agent_runtime as runtime
        from scripts import run_agent_comparison as runner
        self.runner = runner
        self.embedding = EmbeddingSettings("dashscope", "offline-embedding", "offline-embedding-key",
                                           "https://example.invalid/embeddings", 8)
        self.profile = make_index_profile(self.embedding)
        self.case_ids = ["offline-A", "offline-B"]
        cases = [{"case_id": case_id, "split": "dev", "review_status": "human_verified",
                  "question": QUESTION, "paper_ids": ["p1"], "answerable": True,
                  "question_type": "synthetic_fact", "annotation_marker": "DO_NOT_SEND_EXPECTED_" + case_id,
                  "expected_evidence": [{"paper_id": "p1", "pdf_page": 2,
                                         "pdf_sha256": self.pdf_hash, "quote": self.row["text"]}],
                  "expected_points": ["DO_NOT_SEND_EXPECTED_POINT"]} for case_id in self.case_ids]
        dev = self.root / "eval/dev.jsonl"
        dev.parent.mkdir(parents=True, exist_ok=True)
        dev.write_text("\n".join(encoded(case) for case in cases) + "\n", encoding="utf-8")
        (self.root / "eval/holdout.jsonl").write_text("not parsed; only hashed", encoding="utf-8")
        strategy = json.loads((ROOT / "artifacts/d8/agent_config.json").read_text(encoding="utf-8"))
        strategy.update(index_profile=self.profile, ready_versions=[{
            "paper_id": "p1", "parse_revision": "r1", "status": "ready",
            "index_profile_id": self.profile["index_profile_id"]}])
        strategy["chat"] = {"provider": self.settings.provider, "model_id": self.settings.model_id,
                            "base_url": self.settings.base_url, "configured_timeout_seconds": self.settings.timeout}
        path = self.root / runtime.STRATEGY_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded(strategy), encoding="utf-8")
        index = self.root / "data/index"
        (index / "profiles").mkdir(parents=True, exist_ok=True)
        (index / "current_profile.json").write_text(encoded(self.profile), encoding="utf-8")
        (index / "profiles" / (self.profile["index_profile_id"] + ".json")).write_text(encoded(self.profile), encoding="utf-8")
        self.opened_resources = 0

    def load(self, relative):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def prepare(self, batch_id="offline-batch", case_ids=None):
        return self.runner.prepare_batch(batch_id, self.case_ids if case_ids is None else case_ids,
                                         project_root=self.root)

    def execute(self, batch_id="offline-batch", *, factory=None, searcher=None, resume=False,
                close_error=None, configuration_loader=None):
        self.searcher = searcher or SequencedSearcher(*[[self.row] for _ in self.case_ids])

        @contextmanager
        def resources(root, embedding, profile):
            self.opened_resources += 1
            try:
                yield self.store, self.searcher
            finally:
                self.store.close()
                self.searcher.close()
                if close_error:
                    raise close_error

        return self.runner.execute_batch(batch_id, project_root=self.root, resume=resume,
                configuration_loader=configuration_loader or (lambda: (self.embedding, self.settings)),
                resources_factory=resources, client_factory=factory or self.factory())

    def test_prepare_is_unpaid_dev_only_freeze_and_duplicate_preserves_manifest(self):
        with patch.object(self.runner, "load_embedding_settings", side_effect=AssertionError("env forbidden")), \
                patch.object(self.runner, "load_llm_settings", side_effect=AssertionError("env forbidden")), \
                patch.object(self.runner, "open_retrieval_resources", side_effect=AssertionError("stores forbidden")):
            prepared = self.prepare()
        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(prepared["real_api_calls"], 0)
        path = self.root / prepared["path"] / "manifest.json"
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            self.prepare(case_ids=["holdout-A"])
        with self.assertRaises((ValueError, OSError)):
            self.prepare()
        self.assertEqual(path.read_bytes(), original)
        manifest = json.loads(original)
        self.assertEqual(manifest["split"], "dev")
        self.assertFalse(manifest["is_f_paid_validation"])
        self.assertNotIn("binding", manifest)

    def test_actual_batch_saves_both_modes_and_annotations_never_enter_messages(self):
        self.prepare(case_ids=[self.case_ids[0]])
        summary = self.execute()
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(len(self.searcher.calls), 1)
        self.assertEqual(summary["actual_batch_cost"]["embedding"]["embedding_requests"], 1)
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 2)
        self.assertTrue(self.searcher.closed)
        self.assertTrue(self.store.closed)
        case = self.load("artifacts/d8/comparison/offline-batch/" + self.case_ids[0] + ".json")
        for mode in ("fixed_rag", "agent"):
            report = case["pair"]["modes"][mode]
            self.assertEqual(report["export"]["status"], "completed")
            self.assertTrue((self.root / report["history_report"]).exists())
            self.assertNotIn("source_sha256", report)
            for request in self.mode_requests[mode]:
                messages = json.loads(request.content)["messages"]
                serialized = encoded(messages)
                self.assertNotIn(self.case_ids[0], serialized)
                self.assertNotIn("DO_NOT_SEND_EXPECTED", serialized)
                self.assertNotIn("answerable", serialized)
                self.assertEqual(json.loads(messages[1]["content"])["question"], QUESTION)
        self.assertIsNone(summary["qa_accuracy"])
        self.assertFalse((self.root / "artifacts/d5").exists())
        self.assertFalse((self.root / "artifacts/d6").exists())
        self.assertTrue((self.root / "artifacts/d8/fixed_rag_result.json").exists())
        self.assertTrue((self.root / "artifacts/d8/agent_result.json").exists())

        from contextlib import redirect_stdout
        from paper_assistant import d9_runtime as runtime
        from scripts.check_d9_e_runtime import RuntimeChecks

        current = RuntimeChecks("test_original_query_and_complete_pairs_preserved")
        current.setUp()
        self.addCleanup(current.doCleanups)
        fixture = current.fixture
        versions = [{"paper_id": fixture.paper_id, "parse_revision": fixture.parse_revision}]
        ready = [{**versions[0], "title": "Offline structural fixture"}]
        actual_prepare = self.runner.prepare_current_batch
        batch_id = "offline-current-batch"

        def prepare_current(identifier, case_ids, **kwargs):
            return actual_prepare(identifier, case_ids, project_root=current.root)

        output = io.StringIO()
        with patch.object(runtime, "list_ready_versions", return_value=ready), \
                patch.object(self.runner, "prepare_current_batch", side_effect=prepare_current), \
                patch.object(self.runner, "execute_current_batch", side_effect=AssertionError("prepare must not execute")), \
                patch.object(runtime, "RecordedLLM", side_effect=AssertionError("prepare must not create clients")), \
                patch.object(runtime, "open_retrieval_resources", side_effect=AssertionError("prepare must not retrieve")), \
                redirect_stdout(output):
            exit_code = self.runner.main(["--pipeline", "current", "--batch-id", batch_id,
                                          "--case-ids", *current.case_ids])
        self.assertEqual(exit_code, 0)
        prepared = json.loads(output.getvalue())
        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(prepared["real_api_calls"], 0)
        path = current.root / "artifacts/v2/comparison" / batch_id
        inputs = json.loads((path / "input.json").read_text(encoding="utf-8"))
        self.assertEqual(inputs["case_ids"], current.case_ids)
        self.assertFalse((path / "manifest.json").exists())
        self.assertFalse((path / "summary.json").exists())
        self.assertFalse((current.root / "archive/run_logs").exists())
        for case in inputs["cases"]:
            self.assertEqual(case["selected_versions"], versions)
            self.assertIn("DO_NOT_SEND_EXPECTED", encoded(case))

        runs = []
        preparation = {"standalone_question": fixture.question, "clarification_question": None,
                       "referenced_evidence_ids": [], "planned_queries": []}
        search_action = {"action": "search", "query": "Independent current evidence query",
                         "selected_versions": versions, "missing_information": "The requested abstract fact."}

        def run_current(query, selected_versions, *, mode, project_root, library_mode, **kwargs):
            self.assertEqual(query, fixture.question)
            self.assertEqual(list(selected_versions), fixture.pairs)
            self.assertEqual(project_root, current.root)
            self.assertTrue(library_mode)
            # Each call receives its own resources, as the page entry does.
            current.store = type(current.store)(current.store.chunks)
            failed = len(runs) == 2 and mode == "fixed_rag"
            terminal = (http_error(401) if failed else
                        response(answer_action(fixture.abstract_id)["answer"] if mode == "fixed_rag"
                                 else answer_action(fixture.abstract_id)))
            outcomes = [response(preparation)]
            if mode == "agent":
                outcomes.append(response(search_action))
            outcomes.append(terminal)
            report = current.invoke(mode, query=query, pairs=selected_versions, library_mode=library_mode,
                                    token="current-" + str(len(runs)) + "-" + mode, outcomes=outcomes)
            runs.append({"mode": mode, "report": report, "requests": list(current.requests),
                         "searcher": current.searcher, "client": current.chat_client, "store": current.store})
            return report

        with patch.object(runtime.web_runtime, "_ready_versions", return_value=ready), \
                patch.object(runtime, "run_question", wraps=runtime.run_question) as page_entry, \
                patch.object(runtime, "save_agent_run", wraps=runtime.save_agent_run) as save_history:
            summary = self.runner.execute_current_batch(batch_id, project_root=current.root, runtime_runner=run_current)
        self.assertEqual([run["mode"] for run in runs], ["fixed_rag", "agent", "fixed_rag", "agent"])
        self.assertEqual(page_entry.call_count, 4)
        self.assertEqual(save_history.call_count, 4)
        self.assertEqual(summary["status"], "attention_required")
        self.assertEqual(summary["actual_batch_cost"]["embedding"]["embedding_requests"], 4)
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 10)
        self.assertIsNone(summary["qa_accuracy"])
        self.assertTrue((path / "summary.md").is_file())
        self.assertEqual(json.loads((path / "summary.json").read_text(encoding="utf-8"))["status"], "attention_required")
        histories = []
        for index, case_id in enumerate(current.case_ids):
            case = json.loads((path / (case_id + ".json")).read_text(encoding="utf-8"))
            for mode in ("fixed_rag", "agent"):
                report = case["pair"]["modes"][mode]
                self.assertEqual(report["status"], "tool_error" if index == 1 and mode == "fixed_rag" else "answered")
                self.assertTrue((current.root / report["history_report"]).is_file())
                histories.append(report["history_report"])
                self.assertEqual(report["embedding_requests"], 1)
                self.assertEqual(report["policy"]["max_tokens"], 4096)
                self.assertEqual(report["selected_versions"], versions)
                self.assertEqual(report["llm_requests"], 2 if mode == "fixed_rag" else 3)
                if mode == "agent":
                    self.assertEqual(report["result"]["retrieval_strategy"], "autonomous")
                    self.assertEqual(report["result"]["autonomous_step_limit"], 5)
                    self.assertEqual(report["result"]["autonomous_steps_used"], 2)
        self.assertEqual(len(set(histories)), 4)
        for run in runs:
            self.assertTrue(run["client"]._closed and run["store"].closed and run["searcher"].closed)
            self.assertEqual(len(run["searcher"].calls), 1)
            for request in run["requests"]:
                messages = encoded(json.loads(request.content)["messages"])
                self.assertNotIn("DO_NOT_SEND_EXPECTED", messages)
                self.assertNotIn("answerable", messages)
                for case_id in current.case_ids:
                    self.assertNotIn(case_id, messages)
            for call in run["searcher"].calls:
                self.assertEqual(call["selected_versions"], fixture.pairs)
                self.assertNotIn("DO_NOT_SEND_EXPECTED", call["query"])


    def test_public_configuration_drift_stops_before_paid_work(self):
        self.prepare()
        factory = self.factory()
        changed = replace(self.settings, model_id="other-offline-model")
        with self.assertRaises(ValueError):
            self.execute(factory=factory, configuration_loader=lambda: (self.embedding, changed))
        self.assertEqual(self.opened_resources, 0)
        self.assert_no_paid_mode()

    def test_resumption_only_attempts_unattempted_case_and_keeps_first_failure(self):
        self.prepare()
        first = self.execute(factory=self.factory(fixed=[http_error(401)]))
        self.assertEqual(first["status"], "attention_required")
        first_path = self.root / "artifacts/d8/comparison/offline-batch" / (self.case_ids[0] + ".json")
        before = first_path.read_bytes()
        self.assertEqual(len(self.searcher.calls), 1)
        factory = self.factory()
        with self.assertRaises(ValueError):
            self.execute(factory=factory)
        self.assert_no_paid_mode()
        resumed = self.execute(resume=True, factory=self.factory())
        self.assertEqual(resumed["status"], "attention_required")
        self.assertEqual(first_path.read_bytes(), before)
        self.assertEqual(len(self.searcher.calls), 1)
        self.assertEqual(resumed["remaining_case_ids"], [])
        self.assertEqual(len(resumed["records"]), 2)
        self.assertEqual(resumed["records"][0]["pair"]["modes"]["fixed_rag"]["status"], "tool_error")
        self.assertEqual(resumed["actual_batch_cost"]["embedding"]["embedding_requests"], 2)
        self.assertEqual(resumed["actual_batch_cost"]["chat"]["http_request_attempts"], 4)

    def test_interrupted_attempt_without_final_record_is_never_replayed(self):
        prepared = self.prepare()
        path = self.root / prepared["path"]
        manifest = self.load(prepared["path"] + "/manifest.json")
        exclusive_json(path / (self.case_ids[0] + ".attempt.json"), {
            "case_id": self.case_ids[0], "freeze_sha256": manifest["freeze_sha256"],
            "automatic_rerun_allowed": False})
        factory = self.factory()
        with self.assertRaises(ValueError):
            self.execute(resume=True, factory=factory)
        self.assert_no_paid_mode()
        self.assertEqual(self.opened_resources, 0)

    def test_case_record_without_attempt_reservation_is_refused_before_replay(self):
        self.prepare(case_ids=[self.case_ids[0]])
        self.execute()
        base = self.root / "artifacts/d8/comparison/offline-batch"
        original = (base / (self.case_ids[0] + ".json")).read_bytes()
        (base / (self.case_ids[0] + ".attempt.json")).unlink()
        factory = self.factory()
        with self.assertRaises(ValueError):
            self.execute(resume=True, factory=factory)
        self.assert_no_paid_mode()
        self.assertEqual((base / (self.case_ids[0] + ".json")).read_bytes(), original)

    def test_paid_export_failure_keeps_uncommitted_pair_and_blocks_same_case_replay(self):
        self.prepare(case_ids=[self.case_ids[0]])
        actual = self.runner.exclusive_json

        def fail_case_export(path, value):
            if path.name == self.case_ids[0] + ".json":
                raise OSError("private case export failure")
            return actual(path, value)

        with patch.object(self.runner, "exclusive_json", side_effect=fail_case_export):
            summary = self.execute()
        self.assertEqual(summary["status"], "attention_required")
        self.assertEqual(summary["actual_batch_cost"]["embedding"]["embedding_requests"], 1)
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 2)
        self.assertIsNotNone(summary["uncommitted_pair"])
        self.assertEqual(len(summary["records"]), 0)
        self.assertNotIn("private case export failure", encoded(summary))
        factory = self.factory()
        with self.assertRaises(ValueError):
            self.execute(resume=True, factory=factory)
        self.assert_no_paid_mode()

    def test_resource_cleanup_failure_keeps_saved_calls_and_failed_summary(self):
        self.prepare(case_ids=[self.case_ids[0]])
        summary = self.execute(close_error=OSError("private resource close failure"))
        self.assertEqual(summary["status"], "attention_required")
        self.assertEqual(len(summary["records"]), 1)
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 2)
        self.assertEqual(summary["actual_batch_cost"]["embedding"]["embedding_requests"], 1)
        self.assertTrue(self.searcher.closed)
        self.assertTrue(self.store.closed)
        self.assertNotIn("private resource close failure", encoded(summary))

    def test_mode_history_export_failure_keeps_cost_and_pair_terminal_consistent(self):
        from paper_assistant import agent_export as export
        self.prepare(case_ids=[self.case_ids[0]])
        actual = export.exclusive_json
        faulted = []

        def fail_agent_history(path, value):
            if path.name.startswith("agent_") and "_export_failure_" not in path.name and not faulted:
                faulted.append(path)
                raise OSError("private mode history failure")
            return actual(path, value)

        with patch.object(export, "exclusive_json", side_effect=fail_agent_history):
            summary = self.execute()
        self.assertEqual(summary["status"], "attention_required")
        pair = summary["records"][0]["pair"]
        self.assertEqual(pair["modes"]["agent"]["status"], "tool_error")
        self.assertIsNone(pair["modes"]["agent"]["answer"])
        self.assertEqual(pair["status"], "tool_error")
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 2)
        self.assertEqual(summary["actual_batch_cost"]["chat"]["total_tokens"], 50)
        self.assertTrue(pair["modes"]["agent"]["export"]["recovery_saved"])
        self.assertNotIn("private mode history failure", encoded(summary))

    def test_summary_export_failure_returns_consistent_failure_with_consumed_calls(self):
        self.prepare(case_ids=[self.case_ids[0]])
        actual = self.runner.atomic_text
        faulted = []

        def fail_summary_markdown(path, value):
            if path.name == "summary.md" and not faulted:
                faulted.append(path)
                raise OSError("private summary markdown failure")
            return actual(path, value)

        with patch.object(self.runner, "atomic_text", side_effect=fail_summary_markdown):
            summary = self.execute()
        self.assertEqual(summary["status"], "attention_required")
        self.assertEqual(summary["state"]["status"], "attention_required")
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 2)
        self.assertEqual(summary["actual_batch_cost"]["embedding"]["embedding_requests"], 1)
        self.assertEqual(len(summary["records"]), 1)
        self.assertNotIn("private summary markdown failure", encoded(summary))
        self.assertTrue(summary["export"]["recovery_saved"])
        base = self.root / "artifacts/d8/comparison/offline-batch"
        events = list(base.glob("batch_export_failure_*.json"))
        self.assertEqual(len(events), 1)
        recovery = json.loads(events[0].read_text(encoding="utf-8"))
        self.assertEqual(recovery["status"], "attention_required")
        self.assertEqual(recovery["actual_batch_cost"]["chat"]["http_request_attempts"], 2)
        self.assertEqual(self.load("artifacts/d8/comparison/offline-batch/summary.json")["status"], "attention_required")
        self.assertEqual(self.load("artifacts/d8/comparison/offline-batch/state.json")["status"], "attention_required")

    def test_batch_known_usage_includes_known_subtotals_from_incomplete_case(self):
        self.prepare(case_ids=[self.case_ids[0]])
        summary = self.execute(factory=self.factory(fixed=[http_error(503), response(self.draft())]))
        self.assertEqual(summary["status"], "completed")
        self.assertIsNone(summary["actual_batch_cost"]["chat"]["total_tokens"])
        self.assertEqual(summary["actual_batch_cost"]["chat"]["known_total_tokens"], 50)
        self.assertEqual(summary["actual_batch_cost"]["chat"]["http_request_attempts"], 3)



def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
