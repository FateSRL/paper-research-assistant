"""D9 C necessary offline remaining-time/send-accounting/commit checks.

No environment or production stores are opened; real network is blocked.
The report preserves each run, including failures, without rewriting old ones.
"""
from contextlib import ExitStack, contextmanager
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

from paper_assistant.config import EmbeddingSettings
from paper_assistant.deadline import DeadlineExceeded, commit_result, final_deadline, search_with_budget
from paper_assistant import agent_comparison, web_runtime
from paper_assistant.agent_comparison import FrozenFirstSearcher
from paper_assistant import agent_runtime
from paper_assistant.embedding_client import EmbeddingAPIError, LegacyEmbedderAdapter, embed_texts
from paper_assistant.llm_client import ChatBudget
from paper_assistant.rag import answer_question
from paper_assistant.agent import answer_question_agent
from paper_assistant.search import SearchError
from scripts import check_agent, check_retrieval, check_agent_cli
from scripts import answer_question as fixed_cli
from scripts.check_agent import AgentFixture, SequencedSearcher, answer_action, response
from scripts.check_agent_comparison import PairedFixture
from scripts.check_llm import FakeClock

ROOT = Path(__file__).resolve().parents[1]
EMBEDDING_MOCK_SENDS = 0


def vector_body(tokens=17):
    return {"data": [{"index": 0, "embedding": [1.0, 0.0]}],
            "usage": {"total_tokens": tokens}}


class HTTPChecks(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.budget = ChatBudget(clock=self.clock)
        self.settings = EmbeddingSettings("dashscope", "offline-vector", "offline-credential",
                                          "https://example.invalid/v1", 2)
        self.requests = []

    def transport(self, callback=None):
        def send(request):
            global EMBEDDING_MOCK_SENDS
            EMBEDDING_MOCK_SENDS += 1
            self.requests.append(request)
            return callback(request) if callback else httpx.Response(200, json=vector_body())
        return httpx.MockTransport(send)

    def invoke(self, callback=None, **options):
        return embed_texts(["question"], self.settings,
                           remaining_seconds=self.budget.remaining_seconds,
                           transport=self.transport(callback), **options)

    def test_expired_before_send_is_zero_attempts(self):
        self.clock.advance(120)
        with self.assertRaises(EmbeddingAPIError) as caught:
            self.invoke()
        error = caught.exception
        self.assertEqual((error.status, error.code), ("budget_exceeded", "deadline_exceeded"))
        self.assertEqual(error.statistics["embedding_requests"], 0)
        self.assertEqual(error.statistics["failed_requests"], 0)
        self.assertFalse(error.statistics["request_started"])
        self.assertEqual(self.requests, [])

    def test_hook_rechecks_after_client_setup_and_uses_one_remaining_second(self):
        client_type = httpx.Client
        def construct(*args, **kwargs):
            self.clock.advance(119)
            return client_type(*args, **kwargs)
        with patch("paper_assistant.embedding_client.httpx.Client", side_effect=construct):
            batch = self.invoke()
        self.assertEqual(batch.timeout_seconds, 1)
        self.assertEqual(self.requests[0].extensions["timeout"],
                         dict.fromkeys(("connect", "read", "write", "pool"), 1.0))
        self.assertEqual((batch.request_attempts, batch.total_tokens), (1, 17))

    def test_hook_expiry_after_client_setup_does_not_enter_transport(self):
        client_type = httpx.Client
        def construct(*args, **kwargs):
            self.clock.advance(120)
            return client_type(*args, **kwargs)
        with patch("paper_assistant.embedding_client.httpx.Client", side_effect=construct):
            with self.assertRaises(EmbeddingAPIError) as caught:
                self.invoke()
        self.assertEqual(caught.exception.statistics["embedding_requests"], 0)
        self.assertEqual(self.requests, [])

    def test_late_success_keeps_one_attempt_and_known_tokens(self):
        def late(request):
            self.clock.advance(121)
            return httpx.Response(200, json=vector_body())
        with self.assertRaises(EmbeddingAPIError) as caught:
            self.invoke(late)
        error = caught.exception
        self.assertEqual(error.status, "budget_exceeded")
        self.assertEqual(error.statistics["embedding_requests"], 1)
        self.assertEqual(error.statistics["failed_requests"], 0)
        self.assertEqual(error.statistics["total_tokens"], 17)

    def test_sent_timeout_has_one_attempt_no_retry_and_unknown_tokens(self):
        def timeout(request):
            raise httpx.ReadTimeout("private provider text", request=request)
        with self.assertRaises(EmbeddingAPIError) as caught:
            self.invoke(timeout)
        self.assertEqual(caught.exception.status, "tool_error")
        self.assertEqual(caught.exception.statistics["embedding_requests"], 1)
        self.assertEqual(caught.exception.statistics["failed_requests"], 1)
        self.assertIsNone(caught.exception.statistics["total_tokens"])
        self.assertNotIn("private provider", str(caught.exception))
        self.assertEqual(len(self.requests), 1)

    def test_timeout_and_expiry_keep_original_fault(self):
        def timeout(request):
            self.clock.advance(121)
            raise httpx.ReadTimeout("private", request=request)
        with self.assertRaises(EmbeddingAPIError) as caught:
            self.invoke(timeout)
        error = caught.exception
        self.assertEqual(error.status, "budget_exceeded")
        self.assertEqual(error.statistics["failed_requests"], 1)
        self.assertEqual(error.statistics["interrupted_failure"]["code"], "embedding_http_error")

    def test_bad_response_preserves_usage_without_extra_request(self):
        def bad(request):
            return httpx.Response(200, json={"data": [], "usage": {"total_tokens": 17}})
        with self.assertRaises(EmbeddingAPIError) as caught:
            self.invoke(bad)
        self.assertEqual(caught.exception.statistics["total_tokens"], 17)
        self.assertEqual(caught.exception.statistics["failed_requests"], 1)
        self.assertEqual(len(self.requests), 1)

    def test_client_close_fault_and_expiry_preserve_received_usage(self):
        transport = self.transport()
        def close():
            self.clock.advance(121)
            raise RuntimeError("private cleanup fault")
        with patch.object(transport, "close", side_effect=close):
            with self.assertRaises(EmbeddingAPIError) as caught:
                embed_texts(["question"], self.settings, transport=transport,
                            remaining_seconds=self.budget.remaining_seconds)
        error = caught.exception
        self.assertEqual(error.status, "budget_exceeded")
        self.assertEqual(error.statistics["total_tokens"], 17)
        self.assertEqual(error.statistics["embedding_requests"], 1)
        self.assertEqual(error.statistics["interrupted_failure"]["code"], "embedding_setup_error")
        self.assertEqual(len(self.requests), 1)

    def test_default_two_argument_call_still_uses_30_seconds(self):
        with patch("paper_assistant.embedding_client.httpx.Client", wraps=httpx.Client) as ctor:
            # transport is only an offline injection; no remaining callback.
            batch = embed_texts(["question"], self.settings, transport=self.transport())
        self.assertEqual(ctor.call_args.kwargs["timeout"], 30)
        self.assertEqual(batch.timeout_seconds, 30)

    def test_reused_client_keeps_requests_independent_and_closes_owned_client(self):
        owner_requests = []
        owner_hook = lambda request: owner_requests.append(request)
        transport = self.transport(lambda request: httpx.Response(
            200, json=vector_body(11 if len(self.requests) == 1 else 29)))
        with patch.object(transport, "close", wraps=transport.close) as close:
            with httpx.Client(timeout=60, transport=transport, follow_redirects=False,
                              event_hooks={"request": [owner_hook]}) as shared:
                self.clock.advance(117)
                first = embed_texts(["first batch"], self.settings, http_client=shared,
                                    remaining_seconds=self.budget.remaining_seconds)
                self.assertFalse(shared.is_closed)
                self.assertEqual(shared.event_hooks["request"], [owner_hook])
                close.assert_not_called()
                # A stale first-batch deadline hook would prevent this second request.
                self.clock.advance(4)
                second = embed_texts(["second batch"], self.settings, http_client=shared)
                self.assertFalse(shared.is_closed)
                self.assertEqual(shared.event_hooks["request"], [owner_hook])
                close.assert_not_called()
                self.assertEqual((first.request_attempts, first.total_tokens, first.timeout_seconds), (1, 11, 3))
                self.assertEqual((second.request_attempts, second.total_tokens, second.timeout_seconds), (1, 29, 30))
                self.assertEqual([json.loads(request.content)["input"] for request in self.requests],
                                 [["first batch"], ["second batch"]])
                self.assertEqual([request.extensions["timeout"]["read"] for request in self.requests], [3, 30])
                self.assertEqual(owner_requests, self.requests)
            self.assertTrue(shared.is_closed)
            close.assert_called_once_with()

        client_type, owned_clients = httpx.Client, []

        def construct(*args, **kwargs):
            client = client_type(*args, **kwargs)
            owned_clients.append(client)
            return client

        owned_transport = self.transport()
        with patch("paper_assistant.embedding_client.httpx.Client", side_effect=construct), \
             patch.object(owned_transport, "close", wraps=owned_transport.close) as close:
            owned = embed_texts(["standalone batch"], self.settings, transport=owned_transport)
        self.assertEqual(len(owned_clients), 1)
        self.assertTrue(owned_clients[0].is_closed)
        self.assertEqual(owned_clients[0].event_hooks["request"], [])
        close.assert_called_once_with()
        self.assertEqual((owned.request_attempts, owned.total_tokens, owned.timeout_seconds), (1, 17, 30))


class SearchChecks(unittest.TestCase):
    def setUp(self):
        self.f = check_retrieval.RetrievalChecks("test_no_hits_is_distinct_from_a_service_error")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.clock = FakeClock()
        self.budget = ChatBudget(clock=self.clock)
        self.requests = []

    def searcher(self):
        def send(request):
            global EMBEDDING_MOCK_SENDS
            EMBEDDING_MOCK_SENDS += 1
            self.requests.append(request)
            return httpx.Response(200, json=vector_body())
        def embed(texts, settings, **kwargs):
            return embed_texts(texts, settings, transport=httpx.MockTransport(send), **kwargs)
        embed.supports_remaining_time = True
        return self.f.searcher(embedder=embed)

    def run_search(self, searcher):
        return searcher.search_evidence("question", [self.f.pairs[0]],
                                       remaining_seconds=self.budget.remaining_seconds)

    def test_ready_uses_up_budget_before_embedding_is_zero_attempts(self):
        searcher = self.searcher()
        original = searcher._ready_filter
        def ready(pairs):
            result = original(pairs)
            self.clock.advance(120)
            return result
        with patch.object(searcher, "_ready_filter", side_effect=ready):
            with self.assertRaises(SearchError) as caught:
                self.run_search(searcher)
        self.assertEqual((caught.exception.status, caught.exception.stage), ("budget_exceeded", "ready"))
        self.assertEqual(caught.exception.statistics["embedding_requests"], 0)
        self.assertEqual(self.requests, [])

    def test_ready_119_seconds_forwards_one_second(self):
        searcher = self.searcher()
        original = searcher._ready_filter
        def ready(pairs):
            result = original(pairs)
            self.clock.advance(119)
            return result
        with patch.object(searcher, "_ready_filter", side_effect=ready):
            result = self.run_search(searcher)
        self.assertEqual(result["statistics"]["timeout_seconds"], 1)
        self.assertEqual(result["statistics"]["embedding_requests"], 1)
        self.assertEqual(result["statistics"]["total_tokens"], 17)

    def test_late_qdrant_reply_stops_before_reading_sqlite(self):
        searcher = self.searcher()
        original = self.f.vectors.client.query_points
        def query(**kwargs):
            result = original(**kwargs)
            self.clock.advance(121)
            return result
        with patch.object(self.f.vectors.client, "query_points", side_effect=query), \
             patch.object(self.f.reader, "get_chunk", side_effect=AssertionError("must not read")) as lookup:
            with self.assertRaises(SearchError) as caught:
                self.run_search(searcher)
        self.assertEqual(caught.exception.status, "budget_exceeded")
        self.assertEqual(caught.exception.statistics["total_tokens"], 17)
        self.assertEqual(lookup.call_count, 0)

    def test_sqlite_fault_and_expiry_retain_known_embedding_usage(self):
        searcher = self.searcher()
        def lookup(_):
            self.clock.advance(121)
            raise RuntimeError("private text")
        with patch.object(self.f.reader, "get_chunk", side_effect=lookup):
            with self.assertRaises(SearchError) as caught:
                self.run_search(searcher)
        error = caught.exception
        self.assertEqual(error.status, "budget_exceeded")
        self.assertEqual(error.statistics["total_tokens"], 17)
        self.assertEqual(error.statistics["interrupted_failure"]["stage"], "evidence")

    def test_unadapted_legacy_embedder_is_rejected_without_a_call(self):
        searcher = self.f.searcher()
        with self.assertRaises(SearchError) as caught:
            self.run_search(searcher)
        self.assertEqual(caught.exception.stage, "configuration")
        self.assertEqual(caught.exception.statistics["embedding_requests"], 0)
        self.assertEqual(self.f.embedding.calls, [])

    def test_explicit_legacy_adapter_calls_once_and_marks_http_counts_unknown(self):
        searcher = self.f.searcher(embedder=LegacyEmbedderAdapter(self.f.embedding))
        result = self.run_search(searcher)
        self.assertEqual(len(self.f.embedding.calls), 1)
        self.assertIsNone(result["statistics"]["embedding_requests"])
        self.assertIsNone(result["statistics"]["timeout_seconds"])

    def test_legacy_searcher_typeerror_is_not_retried(self):
        calls = []
        class Legacy:
            def search_evidence(self, query, pairs, top_k=5):
                calls.append(query)
                raise TypeError("inside old searcher")
        with self.assertRaises(TypeError):
            search_with_budget(Legacy(), "question", [self.f.pairs[0]],
                               remaining_seconds=self.budget.remaining_seconds)
        self.assertEqual(calls, ["question"])


class CoreChecks(AgentFixture):
    def test_expired_before_first_retrieval_records_zero_embedding_attempts(self):
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                self.clock = FakeClock()
                client, requests = self.client(response(answer_action()))
                self.clock.advance(120)
                searcher = SequencedSearcher([self.row])
                core = answer_question if mode == "fixed_rag" else answer_question_agent
                result = core("question", [("p1", "r1")], searcher, self.store, client,
                              project_root=self.root, enforce_remaining_budget=True)
                self.assertEqual(result["status"], "budget_exceeded")
                self.assertEqual(result["statistics"]["embedding"]["embedding_requests"], 0)
                self.assertEqual(result["statistics"]["embedding"]["failed_requests"], 0)
                self.assertEqual(searcher.calls, [])
                self.assertEqual(requests, [])

    def test_late_citation_fault_expires_both_modes_and_preserves_original_error(self):
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                self.clock = FakeClock()
                payload = self.draft() if mode == "fixed_rag" else answer_action()
                client, requests = self.client(response(payload))
                def lookup(_):
                    self.clock.advance(121)
                    raise RuntimeError("private lookup error")
                core = answer_question if mode == "fixed_rag" else answer_question_agent
                with patch.object(self.store, "get_chunk", side_effect=lookup):
                    result = core("question", [("p1", "r1")], SequencedSearcher([self.row]),
                                  self.store, client, project_root=self.root, enforce_remaining_budget=True)
                self.assertEqual(result["status"], "budget_exceeded")
                self.assertIsNone(result["answer"])
                self.assertEqual(result["interrupted_failure"]["status"], "tool_error")
                self.assertEqual(len(requests), 1)

    def test_remaining_budget_survives_network_retry_and_does_not_reset(self):
        searcher = SequencedSearcher([self.row])
        original = searcher.search_evidence
        observed = []
        def search(query, pairs, top_k=5, *, remaining_seconds=None):
            observed.append(remaining_seconds())
            self.clock.advance(119)
            return original(query, pairs, top_k=top_k)
        searcher.supports_remaining_time = True
        searcher.search_evidence = search
        def late_reply(request):
            self.clock.advance(2)
            code, body = response(answer_action())
            return httpx.Response(code, json=body, request=request)
        from scripts.check_llm import http_error
        client, requests = self.client(http_error(500), late_reply)
        original_deadline = client.budget.deadline
        result = answer_question_agent("question", [("p1", "r1")], searcher, self.store, client,
                                       project_root=self.root, enforce_remaining_budget=True)
        self.assertEqual(observed, [120])
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertEqual(result["statistics"]["chat"]["network_retries"], 1)
        self.assertEqual(len(requests), 2)
        self.assertEqual(client.budget.deadline, original_deadline)
        self.assertTrue(all(r.extensions["timeout"]["read"] <= 1 for r in requests))

    def test_all_terminal_failures_expire_at_business_commit(self):
        for status in ("answered", "insufficient_evidence", "tool_error", "invalid_output"):
            with self.subTest(status=status):
                clock = FakeClock()
                budget = ChatBudget(clock=clock)
                result = {"status": status, "answer": {"status": status}, "failure_stage": "lookup",
                          "error": {"code": "observed_fault"} if status in ("tool_error", "invalid_output") else None}
                clock.advance(120)
                commit_result(result, budget, "cleanup_and_verification")
                self.assertEqual(result["status"], "budget_exceeded")
                if status in ("tool_error", "invalid_output"):
                    self.assertEqual(result["interrupted_failure"]["status"], status)
                self.assertIsNone(result["answer"])


class PairChecks(PairedFixture):
    def test_timed_preflight_faults_have_zero_known_attempts_and_unknown_tokens(self):
        def broken_guard():
            raise RuntimeError("private preflight failure")
        for kind in ("invalid_input",):
            with self.subTest(kind=kind):
                pair = self.paired(query="" if kind == "invalid_input" else "question",
                                  enforce_remaining_budget=True)
                self.assertEqual(pair["status"], "tool_error")
                self.assertEqual(self.searcher.calls, [])
                self.assertEqual(self.factory_calls, [])
                cost = pair["costs"]["actual_batch"]["embedding"]
                self.assertEqual((cost["embedding_requests"], cost["failed_requests"]), (0, 0))
                self.assertIsNone(cost["total_tokens"])
                for mode in ("fixed_rag", "agent"):
                    self.assertEqual(pair["modes"][mode]["embedding_requests"], 0)


    def test_expired_mode_before_replay_retains_shared_logical_usage(self):
        pair = self.paired(factory=self.factory(setup_seconds={"fixed_rag": 121}),
                           enforce_remaining_budget=True)
        first = pair["modes"]["fixed_rag"]
        self.assertEqual(first["status"], "budget_exceeded")
        self.assertEqual(first["embedding_statistics"], pair["shared_first_retrieval"]["statistics"])
        self.assertEqual(first["embedding_requests"], 1)
        self.assertEqual(first["llm_requests"], 0)
        self.assertEqual(pair["costs"]["actual_batch"]["embedding"]["embedding_requests"], 1)


    def test_expired_frozen_replay_does_not_consume_a_round(self):
        snapshot = SequencedSearcher([self.row]).search_evidence("question", [("p1", "r1")])
        replay = FrozenFirstSearcher(snapshot, "question", [("p1", "r1")],
                                     SequencedSearcher([self.row]), allow_retry=True)
        budget = ChatBudget(clock=self.clock)
        self.clock.advance(120)
        with self.assertRaises(DeadlineExceeded):
            replay.search_evidence("question", [("p1", "r1")],
                                   remaining_seconds=budget.remaining_seconds)
        self.assertEqual(replay.calls, 0)
        self.assertEqual(replay.actual_retry_rounds, [])

    def test_shared_119_seconds_leaves_each_mode_one_second(self):
        searcher = SequencedSearcher([self.row])
        original = searcher.search_evidence
        callbacks = []
        def search(query, pairs, top_k=5, *, remaining_seconds=None):
            callbacks.append(remaining_seconds())
            self.clock.advance(119)
            return original(query, pairs, top_k=top_k)
        searcher.supports_remaining_time = True
        searcher.search_evidence = search
        pair = self.paired(searcher=searcher, enforce_remaining_budget=True)
        self.assertEqual(callbacks, [120])
        self.assertEqual([r["remaining_at_factory"] for r in self.factory_calls], [1, 1])
        self.assertEqual(pair["shared_first_retrieval"]["actual_search_calls"], 1)
        self.assertEqual(pair["costs"]["actual_batch"]["embedding"]["embedding_requests"], 1)

    def test_later_mode_time_does_not_expire_already_committed_first_mode(self):
        def late(request):
            self.clock.advance(121)
            code, body = response(answer_action())
            return httpx.Response(code, json=body, request=request)
        pair = self.paired(factory=self.factory(agent=[late]), enforce_remaining_budget=True)
        self.assertEqual(self.mode_result(pair, "fixed_rag")["status"], "answered")
        self.assertEqual(self.mode_result(pair, "fixed_rag")["business_commit"]["status"], "answered")
        self.assertEqual(self.mode_result(pair, "agent")["status"], "budget_exceeded")
        self.assertEqual(self.factory_calls[1]["remaining_at_factory"], 120)


    def test_client_close_fault_and_expiry_keeps_calls(self):
        pair = self.paired(factory=self.factory(close_seconds={"fixed_rag": 121},
                                               close_error={"fixed_rag": RuntimeError("private")}),
                           enforce_remaining_budget=True)
        first = self.mode_result(pair, "fixed_rag")
        self.assertEqual(first["status"], "budget_exceeded")
        self.assertEqual(first["interrupted_failure"]["error"]["code"], "client_close_error")
        self.assertEqual(pair["modes"]["fixed_rag"]["llm_requests"], 1)


class OwnedRuntimeChecks(unittest.TestCase):
    def test_export_failure_preserves_committed_answer_or_fault_in_fixed_cli_and_web(self):
        for module in (fixed_cli, web_runtime):
            for status in ("answered", "tool_error"):
                with self.subTest(module=module.__name__, status=status):
                    clock = FakeClock()
                    budget = ChatBudget(clock=clock)
                    report = {"status": status, "answer": {"status": "answered"} if status == "answered" else None,
                              "error": None if status == "answered" else {"code": "observed_cleanup_fault"},
                              "failure_stage": None if status == "answered" else "resource_cleanup",
                              "result": {"status": "answered", "answer": {"status": "answered"}},
                              "embedding_requests": 1, "llm_requests": 1, "network_requests": 2,
                              "chat_statistics": {"total_tokens": 17},
                              "history_report": "archive/run_logs/offline-commit.json", "run_id": "offline-commit"}
                    commit_result(report, budget, "verification")
                    committed = deepcopy(report)
                    writes = []
                    def write(path, value):
                        if not writes:
                            writes.append("first_attempt")
                            clock.advance(121)
                            raise OSError("private export failure")
                        writes.append(deepcopy(value))
                    with ExitStack() as patches:
                        patches.enter_context(patch.object(module, "exclusive_json", side_effect=write))
                        patches.enter_context(patch.object(module, "atomic_json"))
                        patches.enter_context(patch.object(module, "atomic_text"))
                        patches.enter_context(patch.object(module, "render" if module is fixed_cli else "_render", return_value="offline"))
                        saved = module.save_report(report) if module is fixed_cli else module._save_report(report, ROOT)
                    self.assertFalse(saved)
                    self.assertEqual(report["error"]["code"], "export_error")
                    self.assertEqual(report["pre_export_result"], committed)
                    self.assertEqual(report["business_commit"]["status"], status)
                    self.assertEqual(report["network_requests"], 2)
                    self.assertEqual(report["chat_statistics"]["total_tokens"], 17)
                    self.assertEqual(writes[1]["pre_export_result"], committed)

    def test_late_verification_fault_retains_first_expiry_and_original_fault(self):
        for kind in ("fixed_cli", "web", "agent", "paired"):
            with self.subTest(kind=kind):
                clock = FakeClock()
                budget = ChatBudget(clock=clock)
                core = {"status": "tool_error", "answer": None, "failure_stage": "resource_cleanup",
                        "error": {"code": "original_cleanup_fault"}}
                clock.advance(120)
                final_deadline(core, budget, "resource_cleanup")
                nested = kind in ("agent", "paired")
                report = {"task": "D9", "result": core} if nested else core
                if kind == "fixed_cli":
                    fixed_cli.fail(report, "tool_error", "inputs_changed", "late input fault", "verification")
                elif kind == "web":
                    web_runtime._fail(report, "tool_error", "inputs_changed", "late input fault", "verification")
                elif kind == "agent":
                    agent_runtime._fail(report, "tool_error", "inputs_changed", "late input fault", "verification")
                else:
                    agent_comparison._replace_failure(report, "tool_error", "inputs_changed", "verification")
                commit_result(core, budget, "verification")
                self.assertEqual(core["status"], "budget_exceeded")
                self.assertEqual(core["failure_stage"], "resource_cleanup")
                self.assertEqual(core["interrupted_failure"]["error"]["code"], "original_cleanup_fault")
                self.assertEqual(core["post_deadline_failures"][0]["error"]["code"], "inputs_changed")

    def test_resource_open_expiry_closes_resources_without_constructing_chat_client(self):
        f = check_agent_cli.AgentRuntimeFixture()
        f.setUp()
        self.addCleanup(f.doCleanups)
        budget = ChatBudget(clock=f.clock)
        searcher = SequencedSearcher([f.row])
        closed = []
        @contextmanager
        def resources(*args):
            try:
                f.clock.advance(120)
                yield f.store, searcher
            finally:
                f.store.close()
                searcher.close()
                closed.append(True)
        with patch.object(agent_runtime, "ChatBudget", return_value=budget), \
             patch.object(agent_runtime, "load_embedding_settings", return_value=f.embedding), \
             patch.object(agent_runtime, "load_llm_settings", return_value=f.settings), \
             patch.object(agent_runtime, "open_retrieval_resources", side_effect=resources), \
             patch.object(agent_runtime, "RecordedLLM", side_effect=AssertionError("client forbidden")) as factory:
            report = agent_runtime.run_question_agent("question", [("p1", "r1")],
                         project_root=f.root, enforce_remaining_budget=True)
        self.assertEqual(report["status"], "budget_exceeded")
        self.assertEqual(report["failure_stage"], "resources")
        self.assertEqual((report["embedding_requests"], report["llm_requests"]), (0, 0))
        self.assertEqual(closed, [True])
        factory.assert_not_called()


CASES = (HTTPChecks, SearchChecks, CoreChecks, PairChecks, OwnedRuntimeChecks)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
