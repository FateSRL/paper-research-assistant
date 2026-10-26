"""D9 B offline source-scope orchestration regressions.

The real D2-003 first retrieval is replayed through a fake searcher/store.
Scripted SDK responses are delivered only by httpx.MockTransport: these are
regression fixtures, never new model answers or a quality experiment. No .env,
production SQLite/Qdrant, acceptance questions, or real network is used.
Every invocation retains an independent history, including failures.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

import httpx

from paper_assistant.config import LLMSettings
from paper_assistant.rag import answer_question
from paper_assistant.agent import answer_question_agent
from paper_assistant.agent_comparison import run_paired_case, COMPARISON_VERSION, SCOPED_COMPARISON_VERSION
from paper_assistant.retrieval import point_id
from paper_assistant.source_scope import Registry
from scripts import check_agent
from scripts.check_agent import AgentFixture, answer_action, response, retry_action
from scripts.check_llm import FakeClock
from scripts.check_rag import FakeStore
from scripts.check_source_scope import SourceScopeFixture


ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = "artifacts/d8/comparison/d8_f_dev4_20261005/D2-003.json"
REGISTRY_PATH = "artifacts/d9/source_regions.json"
CHUNKS_PATH = "data/chunks/arxiv_2210.03629v3/r_22af23d03fcb87a8/chunks.jsonl"
PAPER_PATH = "data/chunks/arxiv_2210.03629v3/r_22af23d03fcb87a8/paper.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def fixed_answer(*identifiers):
    return answer_action(*identifiers)["answer"]


def knowledge_answer():
    return {"status": "answered", "claims": [{"claim": "摘要通常概括研究问题、主要方法和核心结果，可按这三点组织阅读。",
            "basis": "model_knowledge", "citation_ids": []}],
            "reason": "这里提供通用阅读思路，不将其作为论文报告的具体事实。"}


class ScopedSequencedSearcher:
    """Observable fake retrieval; scope is passed through, never reimplemented.

    Outcomes are the actual raw snapshots (or explicitly prepared fixture
    rows). The production scope selector has to validate and exclude them.
    """

    def __init__(self, *outcomes, profile="offline-profile", on_search=None):
        self.outcomes = list(outcomes)
        self.profile = profile
        self.on_search = on_search
        self.calls = []

    def search_evidence(self, query, selected_versions, top_k=5, *,
                        allowed_point_ids=None, remaining_seconds=None):
        call = {"query": query, "selected_versions": deepcopy(selected_versions),
                "top_k": top_k, "allowed_point_ids": deepcopy(allowed_point_ids),
                "remaining_seconds": remaining_seconds}
        self.calls.append(call)
        if self.on_search:
            self.on_search(len(self.calls))
        if not self.outcomes:
            raise AssertionError("Retrieval exceeded the offline fixture's outcomes")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome(query, selected_versions, top_k, allowed_point_ids)
        rows = deepcopy(outcome)
        result = {"status": "success" if rows else "no_hits", "query": query,
                  "selected_versions": [{"paper_id": p, "parse_revision": r}
                                        for p, r in selected_versions],
                  "top_k": top_k, "results": rows, "returned_count": len(rows),
                  "index_profile_id": self.profile, "statistics": {
                      "embedding_requests": 1, "failed_requests": 0,
                      "total_tokens": 7}}
        if allowed_point_ids is not None:
            result["allowed_point_ids"] = deepcopy(allowed_point_ids)
        return result


class RealD2Fixture(unittest.TestCase):
    client = AgentFixture.client
    request_data = AgentFixture.request_data

    def setUp(self):
        self.root = ROOT
        self.clock = FakeClock()
        self.settings = LLMSettings(provider="deepseek", model_id="offline-model",
                                    api_key=check_agent.SECRET,
                                    base_url="https://example.invalid/v1", timeout=30.0)
        self.case = json.loads((ROOT / CASE_PATH).read_text(encoding="utf-8"))
        self.search_snapshot = deepcopy(self.case["pair"]["shared_first_retrieval"]["search"])
        self.question = self.search_snapshot["query"]
        self.pairs = [(x["paper_id"], x["parse_revision"])
                      for x in self.search_snapshot["selected_versions"]]
        self.profile = self.search_snapshot["index_profile_id"]
        self.initial_rows = self.search_snapshot["results"]
        paper = json.loads((ROOT / PAPER_PATH).read_text(encoding="utf-8"))
        raw = [json.loads(line) for line in (ROOT / CHUNKS_PATH).read_text(
            encoding="utf-8").splitlines() if line.strip()]
        self.all_rows = [{**row, **{k: paper[k] for k in
                                  ("title", "arxiv_version", "source_url", "local_path")}}
                         for row in raw]
        self.store = FakeStore({x["chunk_id"]: x for x in self.all_rows})
        self.registry = Registry(self.root, self.store, self.pairs)
        allowed = set(self.registry.abstract_point_ids(self.profile, self.pairs))
        self.abstract_rows = []
        for row in self.all_rows:
            identifier = point_id(self.profile, row["chunk_id"])
            if identifier in allowed:
                self.abstract_rows.append({**deepcopy(row), "point_id": identifier,
                                           "index_profile_id": self.profile,
                                           "rank": len(self.abstract_rows) + 1, "score": 0.9})
        self.assertTrue(self.abstract_rows, "The verified real registry must supply abstract candidates")
        self.abstract_rows = self.abstract_rows[:5]

    def core(self, mode, client, searcher, *, query=None, registry=True):
        function = answer_question if mode == "fixed_rag" else answer_question_agent
        options = {"source_registry": self.registry} if registry else {}
        return function(self.question if query is None else query, self.pairs,
                        searcher, self.store, client, project_root=self.root, **options)

    def searcher(self, *outcomes):
        return ScopedSequencedSearcher(*outcomes, profile=self.profile)

    def abstract_plus_body(self):
        rows = deepcopy([self.abstract_rows[0], self.initial_rows[0]])
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
        return rows

    def assert_failed(self, result, status):
        self.assertEqual(result["status"], status)
        self.assertIsNone(result["answer"])
        self.assertNotIn(check_agent.SECRET, encoded(result))


class RealFirstRetrievalChecks(RealD2Fixture):
    def test_fixed_real_first_retrieval_answers_without_qualified_paper_citations(self):
        draft = knowledge_answer()
        client, requests = self.client(response(draft))
        searcher = self.searcher(self.initial_rows)
        result = self.core("fixed_rag", client, searcher)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(searcher.calls), 1)
        self.assertEqual(result["search"]["status"], "success")
        self.assertEqual(result["search"]["results"], self.initial_rows)
        self.assertEqual(result["context"]["shown_evidence"], [])
        self.assertEqual(result["answer"]["claims"], draft["claims"])
        self.assertEqual(result["answer"]["evidence_status"], "none")
        self.assertEqual(result["answer"]["evidence_sources"], [])

    def test_agent_real_first_retrieval_can_retry_with_scope_and_original_question(self):
        identifier = self.abstract_rows[0]["chunk_id"]
        raw_retry = "  ReAct abstract benchmarks\n  "
        client, requests = self.client(response(retry_action(raw_retry)),
                                       response(answer_action(identifier)))
        searcher = self.searcher(self.initial_rows, self.abstract_rows)
        result = self.core("agent", client, searcher)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(len(searcher.calls), 2)
        self.assertEqual(len(requests), 2)
        self.assertEqual(searcher.calls[0]["query"], self.question)
        self.assertIsNone(searcher.calls[0]["allowed_point_ids"])
        self.assertEqual(searcher.calls[1]["query"], raw_retry)
        self.assertEqual(set(searcher.calls[1]["allowed_point_ids"]),
                         set(self.registry.abstract_point_ids(self.profile, self.pairs)))
        initial = json.loads(self.request_data(requests[0])[1]["content"])
        final = json.loads(self.request_data(requests[1])[1]["content"])
        self.assertEqual(initial["question"], self.question)
        self.assertEqual(initial["shown_evidence"], [])
        self.assertIn("answer", initial["allowed_actions"])
        self.assertEqual(final["question"], self.question)
        self.assertNotIn("retry_search", final["allowed_actions"])
        self.assertEqual(result["answer"]["evidence_refs"][0]["chunk_id"], identifier)
        self.assertNotIn(self.initial_rows[0]["chunk_id"], result["context"]["allowed_citation_ids"])

    def test_old_body_answer_with_empty_qualified_context_is_terminal_source_repair(self):
        identifier = self.initial_rows[0]["chunk_id"]
        repairs = [({"action": "answer", "answer": knowledge_answer()}, "answered"),
                   (retry_action("ReAct abstract benchmarks"), "invalid_output")]
        for repaired_action, expected_status in repairs:
            with self.subTest(repaired_action=repaired_action["action"]):
                client, requests = self.client(response(answer_action(identifier)),
                                               response(repaired_action))
                searcher = self.searcher(self.initial_rows)
                result = self.core("agent", client, searcher)
                self.assertEqual(result["status"], expected_status)
                if expected_status == "invalid_output":
                    self.assertIsNone(result["answer"])
                else:
                    self.assertEqual(result["answer"]["claims"], repaired_action["answer"]["claims"])
                    self.assertEqual(result["answer"]["evidence_status"], "none")
                    self.assertEqual(result["answer"]["evidence_sources"], [])
                self.assertEqual(len(searcher.calls), 1)
                self.assertEqual(len(requests), 2)
                self.assertEqual(result["statistics"]["chat"]["repairs"], 1)
                repair_step = result["action_steps"][-1]
                self.assertTrue(repair_step["terminal_only"])
                self.assertEqual(repair_step["repair_kind"], "citation")
                payload = json.loads(self.request_data(requests[-1])[1]["content"])
                self.assertEqual(payload["question"], self.question)
                self.assertEqual(payload["shown_evidence"], [])
                self.assertNotIn("retry_search", payload["allowed_actions"])

    def test_legacy_opt_out_still_allows_the_old_body_citation(self):
        identifier = self.initial_rows[0]["chunk_id"]
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                action = fixed_answer(identifier) if mode == "fixed_rag" else answer_action(identifier)
                client, requests = self.client(response(action))
                result = self.core(mode, client, self.searcher(self.initial_rows), registry=False)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(len(requests), 1)
                self.assertEqual(result["answer"]["evidence_refs"][0]["chunk_id"], identifier)

    def test_ordinary_question_with_registry_keeps_body_evidence(self):
        identifier = self.initial_rows[0]["chunk_id"]
        question = "What benchmark names are listed in the shown body evidence?"
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                action = fixed_answer(identifier) if mode == "fixed_rag" else answer_action(identifier)
                client, requests = self.client(response(action))
                result = self.core(mode, client, self.searcher(self.initial_rows), query=question)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(len(requests), 1)
                self.assertIn(identifier, result["context"]["allowed_citation_ids"])
                if mode == "agent":
                    payload = json.loads(self.request_data(requests[0])[1]["content"])
                    paper = payload["selected_papers"][0]
                    self.assertEqual(paper["title"], self.all_rows[0]["title"])
                    abstract_ids = set(self.registry.qualified_chunk_ids(self.pairs))
                    self.assertEqual({row["chunk_id"] for row in paper["abstract_passages"]}, abstract_ids)
                    self.assertTrue(abstract_ids)
                    self.assertEqual(payload["allowed_citation_ids"], result["context"]["allowed_citation_ids"])
                    for row in paper["abstract_passages"]:
                        self.assertEqual(row["text"], self.store.chunks[row["chunk_id"]]["text"])

    def test_every_citation_must_be_eligible_and_terminal_repair_keeps_current_scope(self):
        abstract_id = self.abstract_rows[0]["chunk_id"]
        body_id = self.initial_rows[0]["chunk_id"]
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                action = fixed_answer if mode == "fixed_rag" else answer_action
                client, requests = self.client(response(action(abstract_id, body_id)),
                                               response(action(abstract_id)))
                searcher = self.searcher(self.abstract_plus_body())
                result = self.core(mode, client, searcher)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(len(searcher.calls), 1)
                self.assertEqual(len(requests), 2)
                self.assertEqual(result["statistics"]["chat"]["repairs"], 1)
                self.assertEqual(result["context"]["allowed_citation_ids"], [abstract_id])
                self.assertEqual(result["answer"]["claims"][0]["citation_ids"], [abstract_id])
                repaired_payload = json.loads(self.request_data(requests[-1])[1]["content"])
                self.assertEqual(repaired_payload["question"], self.question)
                self.assertEqual(repaired_payload["allowed_citation_ids"], [abstract_id])
                if mode == "agent":
                    self.assertTrue(result["action_steps"][-1]["terminal_only"])
                    self.assertEqual(result["action_steps"][-1]["repair_kind"], "citation")
                    self.assertNotIn("retry_search", repaired_payload["allowed_actions"])

    def test_citation_repair_cannot_reopen_a_tool(self):
        abstract_id = self.abstract_rows[0]["chunk_id"]
        body_id = self.initial_rows[0]["chunk_id"]
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                action = fixed_answer if mode == "fixed_rag" else answer_action
                client, requests = self.client(response(action(abstract_id, body_id)),
                                               response(retry_action("abstract extra facts")))
                searcher = self.searcher(self.abstract_plus_body())
                result = self.core(mode, client, searcher)
                self.assert_failed(result, "invalid_output")
                self.assertEqual(len(searcher.calls), 1)
                self.assertEqual(len(requests), 2)
                self.assertEqual(result["statistics"]["chat"]["repairs"], 1)

    def test_citation_store_failure_is_tool_error_without_model_repair(self):
        abstract_id = self.abstract_rows[0]["chunk_id"]
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                self.store.error = None
                action = fixed_answer if mode == "fixed_rag" else answer_action

                def corrupt_store(request):
                    self.store.error = RuntimeError(check_agent.SECRET)
                    status, body = response(action(abstract_id))
                    return httpx.Response(status, json=body, request=request)

                client, requests = self.client(corrupt_store)
                searcher = self.searcher(self.abstract_rows)
                result = self.core(mode, client, searcher)
                self.assert_failed(result, "tool_error")
                self.assertEqual(len(searcher.calls), 1)
                self.assertEqual(len(requests), 1)
                self.assertEqual(result["statistics"]["chat"]["repairs"], 0)

    def test_format_and_source_citation_failures_share_one_repair(self):
        abstract_id = self.abstract_rows[0]["chunk_id"]
        body_id = self.initial_rows[0]["chunk_id"]
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                action = fixed_answer if mode == "fixed_rag" else answer_action
                client, requests = self.client(response("not JSON"),
                                               response(action(abstract_id, body_id)))
                searcher = self.searcher(self.abstract_plus_body())
                result = self.core(mode, client, searcher)
                self.assert_failed(result, "invalid_output")
                self.assertEqual(len(searcher.calls), 1)
                self.assertEqual(len(requests), 2)
                self.assertEqual(result["statistics"]["chat"]["repairs"], 1)

    def test_scoped_retry_does_not_allow_a_third_search_or_fourth_chat(self):
        client, requests = self.client(response(retry_action("ReAct abstract benchmarks")),
                                       response(retry_action("another abstract query")),
                                       response(retry_action("still another query")))
        searcher = self.searcher(self.initial_rows, self.abstract_rows)
        result = self.core("agent", client, searcher)
        self.assert_failed(result, "invalid_output")
        self.assertEqual(len(searcher.calls), 2)
        self.assertEqual(len(requests), 3)
        self.assertEqual(result["statistics"]["chat"]["repairs"], 1)
        for request in requests[1:]:
            payload = json.loads(self.request_data(request)[1]["content"])
            self.assertEqual(payload["question"], self.question)
            self.assertNotIn("retry_search", payload["allowed_actions"])

    def test_real_paired_cores_share_initial_scope_and_charge_first_search_once(self):
        identifier = self.abstract_rows[0]["chunk_id"]
        terminal_actions = [answer_action(identifier), {"action": "answer", "answer": knowledge_answer()}]
        for terminal_action in terminal_actions:
            with self.subTest(basis=terminal_action["answer"]["claims"][0].get("basis", "paper_evidence")):
                requests_by_mode = {}

                def client_factory(mode, budget):
                    outcomes = ((response(knowledge_answer()),) if mode == "fixed_rag" else
                                (response(retry_action("ReAct abstract benchmarks")),
                                 response(terminal_action)))
                    client, requests = self.client(*outcomes, policy=budget.policy, budget=budget)
                    requests_by_mode[mode] = requests
                    return client

                searcher = self.searcher(self.initial_rows, self.abstract_rows)
                pair = run_paired_case(self.question, self.pairs, searcher, self.store,
                                       client_factory, project_root=self.root,
                                       clock=self.clock, source_registry=self.registry)
                self.assertEqual(pair["status"], "completed")
                self.assertEqual(pair["task"], "D9")
                self.assertEqual(pair["comparison_version"], SCOPED_COMPARISON_VERSION)
                self.assertNotEqual(pair["comparison_version"], COMPARISON_VERSION)
                self.assertEqual(pair["registry_sha256"], self.registry.registry_sha256)
                self.assertEqual(pair["required_source_scope"], "abstract")
                self.assertEqual(pair["shared_first_retrieval"]["actual_search_calls"], 1)
                self.assertEqual(len(searcher.calls), 2)
                self.assertIsNone(searcher.calls[0]["allowed_point_ids"])
                self.assertEqual(set(searcher.calls[1]["allowed_point_ids"]),
                                 set(self.registry.abstract_point_ids(self.profile, self.pairs)))
                fixed = pair["modes"]["fixed_rag"]
                agent = pair["modes"]["agent"]
                self.assertEqual(fixed["status"], "answered")
                self.assertEqual(agent["status"], "answered")
                self.assertEqual(len(requests_by_mode["fixed_rag"]), 1)
                self.assertEqual(len(requests_by_mode["agent"]), 2)
                self.assertEqual(fixed["result"]["context"]["shown_evidence"], [])
                self.assertEqual(fixed["answer"]["evidence_status"], "none")
                self.assertEqual(fixed["answer"]["evidence_sources"], [])
                for report in (fixed, agent):
                    core_result = report["result"]
                    self.assertEqual(core_result["context"]["question"], self.question)
                    self.assertEqual(core_result["source_qualification"]["registry_sha256"],
                                     self.registry.registry_sha256)
                    self.assertEqual(report["registry_sha256"], self.registry.registry_sha256)
                    self.assertEqual(core_result["registry_sha256"], self.registry.registry_sha256)
                    self.assertEqual(report["required_source_scope"], "abstract")
                    self.assertEqual(core_result["required_source_scope"], "abstract")
                    self.assertEqual(report["task"], "D9")
                    self.assertEqual(core_result["task"], "D9")
                    self.assertEqual(report["comparison_version"], SCOPED_COMPARISON_VERSION)
                    self.assertEqual(core_result["comparison_version"], SCOPED_COMPARISON_VERSION)
                costs = pair["costs"]
                self.assertEqual(pair["shared_first_retrieval"]["statistics"]["embedding_requests"], 1)
                self.assertEqual(costs["actual_batch"]["embedding"]["embedding_requests"], 2)
                self.assertEqual(costs["standalone_logical"]["fixed_rag"]["embedding"]["embedding_requests"], 1)
                self.assertEqual(costs["standalone_logical"]["agent"]["embedding"]["embedding_requests"], 2)
                self.assertEqual(costs["actual_batch"]["chat"]["sdk_request_attempts"], 3)
                for request in requests_by_mode["agent"]:
                    payload = json.loads(self.request_data(request)[1]["content"])
                    self.assertEqual(payload["question"], self.question)


class SyntheticSourceFlowChecks(unittest.TestCase):
    client = AgentFixture.client
    request_data = AgentFixture.request_data
    assert_failed = RealD2Fixture.assert_failed

    def setUp(self):
        self.f = self.enterContext(SourceScopeFixture())
        self.root, self.store, self.pairs = self.f.root, self.f.store, self.f.pairs
        self.registry = self.f.registry
        self.clock = FakeClock()
        self.settings = LLMSettings(provider="deepseek", model_id="offline-model",
                                    api_key=check_agent.SECRET,
                                    base_url="https://example.invalid/v1", timeout=30.0)
        # Real citation validation also requires paper metadata. These temporary
        # store extras do not alter the immutable CHUNK_FIELDS snapshot.
        metadata = {"title": "Offline source-scope fixture", "arxiv_version": "v1",
                    "source_url": "https://example.invalid/source",
                    "local_path": "data/papers/fixture.pdf"}
        for mapping in (self.f.chunks, self.store.chunks):
            for row in mapping.values():
                row.update(metadata)

    def searcher(self, ids):
        return ScopedSequencedSearcher(self.f.search(ids)["results"],
                                       profile="synthetic_profile")

    def core(self, mode, client, searcher):
        function = answer_question if mode == "fixed_rag" else answer_question_agent
        return function(self.f.question, self.pairs, searcher, self.store, client,
                        project_root=self.root, source_registry=self.registry)

    def test_page_one_body_and_mixed_chunk_are_excluded_before_both_modes_answer(self):
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                action = fixed_answer if mode == "fixed_rag" else answer_action
                client, requests = self.client(response(action(self.f.abstract_id)))
                ids = [self.f.body_id, self.f.abstract_id, self.f.mixed_id]
                searcher = self.searcher(ids)
                result = self.core(mode, client, searcher)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(len(requests), 1)
                self.assertEqual(len(searcher.calls), 1)
                self.assertEqual(result["context"]["allowed_citation_ids"], [self.f.abstract_id])
                qualification = result["source_qualification"]
                decisions = {x["chunk_id"]: x for x in qualification["decisions"]}
                self.assertEqual(decisions[self.f.body_id]["coverage"], "body")
                self.assertEqual(decisions[self.f.mixed_id]["coverage"], "mixed")
                self.assertFalse(decisions[self.f.body_id]["included"])
                self.assertFalse(decisions[self.f.mixed_id]["included"])
                self.assertEqual(result["answer"]["evidence_refs"][0]["pdf_page"], 2)
                payload = json.loads(self.request_data(requests[0])[1]["content"])
                self.assertEqual(payload["allowed_citation_ids"], [self.f.abstract_id])

    def test_unknown_unverified_scope_answers_without_search_or_paper_citations(self):
        self.registry = self.f.set_region(verification_status="candidate")
        row = self.f.search([self.f.abstract_id])["results"][0]
        self.assertEqual(self.registry.qualify(row)["coverage"], "unknown")
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                draft = {"status": "answered", "claims": [{"claim": "摘要通常交代研究问题、主要方法和核心结果，可按这三点分析。",
                         "basis": "model_knowledge", "citation_ids": []}]}
                client, requests = self.client(response(draft if mode == "fixed_rag" else
                                                       {"action": "answer", "answer": draft}))
                searcher = self.searcher([self.f.abstract_id])
                result = self.core(mode, client, searcher)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(result["answer"]["claims"], draft["claims"])
                self.assertEqual(result["answer"]["evidence_status"], "none")
                self.assertEqual(result["answer"]["evidence_sources"], [])
                self.assertEqual(result["stop_reason"], "source_scope_unavailable")
                self.assertTrue(result["answer"]["reason"])
                self.assertEqual(searcher.calls, [])
                self.assertEqual(len(requests), 1)
                self.assertEqual(result["statistics"]["chat"]["sdk_request_attempts"], 1)
                self.assertEqual(result["statistics"]["embedding"]["embedding_requests"], 0)
                self.assertEqual(result["statistics"]["chat"]["repairs"], 0)
                self.assertEqual(result["source_scope_checks"][-1]["status"], "valid")
        requests_by_mode = {}

        def client_factory(mode, budget):
            content = draft if mode == "fixed_rag" else {"action": "answer", "answer": draft}
            client, requests = self.client(response(content), policy=budget.policy, budget=budget)
            requests_by_mode[mode] = requests
            return client

        searcher = self.searcher([self.f.abstract_id])
        pair = run_paired_case(self.f.question, self.pairs, searcher, self.store,
                               client_factory, project_root=self.root,
                               clock=self.clock, source_registry=self.registry)
        self.assertEqual(pair["status"], "completed")
        self.assertEqual(searcher.calls, [])
        self.assertEqual(pair["shared_first_retrieval"]["actual_search_calls"], 0)
        self.assertIsNone(pair["shared_first_retrieval"]["search"])
        self.assertEqual(pair["costs"]["actual_batch"]["embedding"]["embedding_requests"], 0)
        for mode in ("fixed_rag", "agent"):
            self.assertEqual(pair["modes"][mode]["status"], "answered")
            self.assertEqual(pair["modes"][mode]["answer"]["evidence_status"], "none")
            self.assertEqual(len(requests_by_mode[mode]), 1)



def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
