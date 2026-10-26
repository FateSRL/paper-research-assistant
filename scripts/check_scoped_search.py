"""D9 B: offline point-scope and paired-preflight interface checks.

Only temporary SQLite/Qdrant fixtures and in-memory core doubles are used.
Run with ``python -B -X utf8 -m scripts.check_scoped_search``. This entry does
not regenerate D4/D8 reports or load production stores, .env or evaluation.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from qdrant_client import models

from paper_assistant.agent_comparison import (
    COMPARISON_VERSION, SCOPED_COMPARISON_VERSION, FrozenFirstSearcher, run_paired_case,
)
from paper_assistant.context import prepare_context
from paper_assistant.retrieval import PAYLOAD_FIELDS, point_id
from paper_assistant.search import SearchError
from paper_assistant.hybrid_search import HybridEvidenceSearcher
from scripts import check_retrieval as _retrieval_fixture


class ScopedRetrievalChecks(unittest.TestCase):
    # Reuse the existing temporary fixture without inheriting its test methods.
    setUp = _retrieval_fixture.RetrievalChecks.setUp
    close_resources = _retrieval_fixture.RetrievalChecks.close_resources
    searcher = _retrieval_fixture.RetrievalChecks.searcher
    search = _retrieval_fixture.RetrievalChecks.search
    actual_hits = _retrieval_fixture.RetrievalChecks.actual_hits
    assert_rejected_without_request = _retrieval_fixture.RetrievalChecks.assert_rejected_without_request

    def point(self, chunk):
        return point_id(self.profile["index_profile_id"], chunk["chunk_id"])

    def test_real_point_filter_returns_only_allowed_original_text(self):
        selected = self.bundles[0].chunks[1]
        allowed = [self.point(selected)]
        with patch.object(self.vectors.client, "count", wraps=self.vectors.client.count) as counter:
            result = self.search(allowed_point_ids=allowed)
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["results"][0]["chunk_id"], selected["chunk_id"])
        self.assertEqual(result["results"][0]["text"], selected["text"])
        self.assertEqual(result["results"][0]["rank"], 1)
        self.assertEqual(result["allowed_point_ids"], allowed)
        self.assertEqual(result["statistics"]["embedding_requests"], 1)
        # The ready check sees the whole version (two points), not one allowed point.
        scope = counter.call_args.kwargs["count_filter"]
        self.assertNotIn("has_id", json.dumps(scope.model_dump(exclude_none=True)))
        self.assertEqual(self.vectors.client.count(collection_name=self.vectors.collection_name,
                                                  count_filter=scope, exact=True).count, 2)

    def test_point_filter_intersects_selected_full_pair_not_other_versions(self):
        current, old, foreign = (self.bundles[i].chunks[0] for i in range(3))
        allowed = [self.point(current), self.point(old), self.point(foreign)]
        result = HybridEvidenceSearcher(self.searcher(), self.reader).search_evidence(
            "检索第一块", [self.pairs[0]], allowed_point_ids=allowed)
        self.assertEqual([row["chunk_id"] for row in result["results"]], [current["chunk_id"]])
        self.assertEqual(result["selected_versions"], [{"paper_id": self.pairs[0][0],
                                                       "parse_revision": self.pairs[0][1]}])
        self.assertEqual(result["statistics"]["embedding_requests"], 1)
        trace = result["retrieval_trace"]
        for route in ("dense_candidates", "bm25_candidates", "fused_candidates"):
            self.assertEqual([row["chunk_id"] for row in trace[route]], [current["chunk_id"]])
        self.assertEqual(result["allowed_point_ids"], sorted(allowed))

    def test_point_filter_preserves_profile_intersection(self):
        current = self.bundles[0].chunks[0]
        foreign_id = point_id("other-profile", current["chunk_id"])
        payload = {field: current[field] for field in PAYLOAD_FIELDS}
        payload["index_profile_id"] = "other-profile"
        self.vectors.client.upsert(collection_name=self.vectors.collection_name,
                                   points=[models.PointStruct(id=foreign_id, vector=[1.0, 0.0], payload=payload)],
                                   wait=True)
        result = self.search(allowed_point_ids=[self.point(current), foreign_id])
        self.assertEqual([row["point_id"] for row in result["results"]], [self.point(current)])

    def test_point_filter_preserves_pair_or_scope_for_multiple_selected_versions(self):
        first, second = self.bundles[0].chunks[1], self.bundles[2].chunks[0]
        result = self.search([self.pairs[0], self.pairs[2]],
                             allowed_point_ids={self.point(first), self.point(second)})
        self.assertEqual({row["chunk_id"] for row in result["results"]},
                         {first["chunk_id"], second["chunk_id"]})
        self.assertEqual(result["returned_count"], 2)

    def test_missing_unselected_point_still_fails_full_ready_before_embedding(self):
        allowed = self.point(self.bundles[0].chunks[0])
        other = self.point(self.bundles[0].chunks[1])
        self.vectors.client.delete(collection_name=self.vectors.collection_name,
                                   points_selector=models.PointIdsList(points=[other]), wait=True)
        error = self.assert_rejected_without_request(lambda: self.search(allowed_point_ids=[allowed]))
        self.assertEqual(error.stage, "ready")

    def test_empty_noncanonical_duplicate_or_invalid_white_lists_never_request(self):
        valid = self.point(self.bundles[0].chunks[0])
        invalid = [[], (), set(), frozenset(), valid, {}, [valid, valid],
                   [valid.upper()], [valid.replace("-", "")], ["{" + valid + "}"],
                   ["urn:uuid:" + valid], [" " + valid], ["not-a-uuid"], [True], [UUID(valid)]]
        for allowed in invalid:
            with self.subTest(allowed=repr(allowed)):
                error = self.assert_rejected_without_request(lambda: self.search(allowed_point_ids=allowed))
                self.assertEqual(error.stage, "input")
                self.assertEqual(error.statistics["failed_requests"], 0)
                self.assertIsNone(error.statistics["total_tokens"])

    def test_bad_qdrant_candidate_outside_whitelist_is_tool_error_not_silently_dropped(self):
        hits = self.actual_hits()
        with patch.object(self.vectors.client, "query_points", return_value=SimpleNamespace(points=[hits[1]])), \
             patch.object(self.reader, "get_chunk", wraps=self.reader.get_chunk) as reads:
            with self.assertRaises(SearchError) as caught:
                self.search(allowed_point_ids=[str(hits[0].id)])
        self.assertEqual(caught.exception.stage, "evidence")
        self.assertEqual(caught.exception.statistics["embedding_requests"], 1)
        self.assertEqual(caught.exception.statistics["failed_requests"], 0)
        self.assertEqual(caught.exception.statistics["total_tokens"], 7)
        reads.assert_not_called()

    def test_caller_mutation_during_embedding_cannot_widen_whitelist(self):
        selected, other = self.bundles[0].chunks
        allowed = [self.point(selected)]

        def embedding(texts, settings):
            allowed.append(self.point(other))
            return self.embedding(texts, settings)

        result = self.searcher(embedder=embedding).search_evidence("检索第一块", [self.pairs[0]],
                                                                  allowed_point_ids=allowed)
        self.assertEqual([row["chunk_id"] for row in result["results"]], [selected["chunk_id"]])
        self.assertEqual(result["allowed_point_ids"], [self.point(selected)])

    def test_default_and_explicit_none_preserve_legacy_envelope(self):
        for options in ({}, {"allowed_point_ids": None}):
            result = self.search(**options)
            self.assertEqual(result["returned_count"], 2)
            self.assertNotIn("allowed_point_ids", result)
            self.assertEqual(set(result), {"status", "query", "index_profile_id", "selected_versions",
                                           "top_k", "results", "returned_count", "statistics"})


def snapshot(query="original question"):
    text = "Complete source evidence."
    row = {"chunk_id": "p_r_p1_c1", "paper_id": "p", "parse_revision": "r", "pdf_page": 1,
           "rank": 1, "score": 0.9, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "index_profile_id": "offline-profile", "point_id": point_id("offline-profile", "p_r_p1_c1")}
    return {"status": "success", "query": query, "selected_versions": [{"paper_id": "p", "parse_revision": "r"}],
            "top_k": 5, "index_profile_id": "offline-profile", "results": [row], "returned_count": 1,
            "statistics": {"embedding_requests": 1, "failed_requests": 0, "total_tokens": 7}}


class LiveSearcher:
    def __init__(self):
        self.calls = []

    def search_evidence(self, query, pairs, top_k=5, **options):
        self.calls.append((query, deepcopy(pairs), top_k, deepcopy(options)))
        result = snapshot(query)
        if options:
            result.update(deepcopy(options))
        return result


class FrozenScopeChecks(unittest.TestCase):
    def setUp(self):
        self.first, self.live = snapshot(), LiveSearcher()
        self.allowed = [self.first["results"][0]["point_id"]]

    def replay(self, **options):
        return FrozenFirstSearcher(self.first, self.first["query"], [("p", "r")], self.live, **options)

    def test_first_replay_is_isolated_and_never_filtered_or_live(self):
        replay = self.replay(allow_retry=True)
        for supplied in [self.allowed, [], set()]:
            with self.assertRaises(SearchError) as caught:
                replay.search_evidence(self.first["query"], [("p", "r")], allowed_point_ids=supplied)
            self.assertEqual(caught.exception.statistics["embedding_requests"], 0)
            self.assertIsNone(caught.exception.statistics["total_tokens"])
        self.assertEqual(replay.calls, 0)
        first = replay.search_evidence(self.first["query"], [("p", "r")])
        self.assertEqual(first, self.first)
        first["results"][0]["text"] = "modified"
        self.assertEqual(replay.snapshot, self.first)
        self.assertEqual(self.live.calls, [])

    def test_filtered_snapshot_cannot_be_claimed_as_original_shared_first(self):
        for supplied in [self.allowed, []]:
            first = deepcopy(self.first)
            first["allowed_point_ids"] = supplied
            with self.assertRaises(SearchError):
                FrozenFirstSearcher(first, first["query"], [("p", "r")], self.live)
        self.assertEqual(self.live.calls, [])

    def test_retry_whitelist_is_passed_once_and_recorded_independently(self):
        replay = self.replay(allow_retry=True)
        replay.search_evidence(self.first["query"], [("p", "r")])
        result = replay.search_evidence("retry question", [("p", "r")], allowed_point_ids=self.allowed)
        self.assertEqual(self.live.calls, [("retry question", [("p", "r")], 5,
                                           {"allowed_point_ids": self.allowed})])
        self.assertEqual(result["allowed_point_ids"], self.allowed)
        self.allowed.append(str(uuid4()))
        self.assertEqual(len(replay.actual_retry_rounds[0]["allowed_point_ids"]), 1)
        with self.assertRaises(SearchError):
            replay.search_evidence("third question", [("p", "r")], allowed_point_ids=self.allowed)
        self.assertEqual(len(self.live.calls), 1)

    def test_fixed_mode_or_invalid_retry_filter_cannot_start_live_search(self):
        fixed = self.replay()
        fixed.search_evidence(self.first["query"], [("p", "r")])
        with self.assertRaises(SearchError):
            fixed.search_evidence("retry", [("p", "r")], allowed_point_ids=self.allowed)
        agent = self.replay(allow_retry=True)
        agent.search_evidence(self.first["query"], [("p", "r")])
        for invalid in [[], ["bad"], [self.allowed[0], self.allowed[0]]]:
            with self.assertRaises(SearchError):
                agent.search_evidence("retry", [("p", "r")], allowed_point_ids=invalid)
        self.assertEqual(agent.calls, 1)
        self.assertEqual(agent.actual_retry_rounds, [])
        self.assertEqual(self.live.calls, [])

    def test_none_retry_still_accepts_legacy_three_argument_searcher(self):
        class Legacy:
            def __init__(self):
                self.calls = []

            def search_evidence(self, query, pairs, top_k=5):
                self.calls.append((query, pairs, top_k))
                return snapshot(query)

        legacy = Legacy()
        replay = FrozenFirstSearcher(self.first, self.first["query"], [("p", "r")], legacy, allow_retry=True)
        replay.search_evidence(self.first["query"], [("p", "r")])
        replay.search_evidence("retry", [("p", "r")], allowed_point_ids=None)
        self.assertEqual(legacy.calls, [("retry", [("p", "r")], 5)])
        self.assertNotIn("allowed_point_ids", replay.actual_retry_rounds[0])

    def test_unsupported_filtered_legacy_searcher_is_not_retried_unfiltered(self):
        class Legacy:
            def search_evidence(self, query, pairs, top_k=5):
                raise AssertionError("must not fall back to this body")

        replay = FrozenFirstSearcher(self.first, self.first["query"], [("p", "r")], Legacy(), allow_retry=True)
        replay.search_evidence(self.first["query"], [("p", "r")])
        with self.assertRaises(TypeError):
            replay.search_evidence("retry", [("p", "r")], allowed_point_ids=self.allowed)
        self.assertEqual(replay.calls, 2)
        self.assertEqual(len(replay.actual_retry_rounds), 1)
        self.assertEqual(replay.actual_retry_rounds[0]["error"]["code"], "retrieval_error")


class SyntheticRegistry:
    def __init__(self, *, qualified=True, error=None, pairs=None):
        self.pairs = pairs if pairs is not None else [("p", "r"), ("other", "r2")]
        self.qualified, self.error, self.rechecks, self.scope_calls = qualified, error, 0, []
        self.registry_sha256 = hashlib.sha256(b"explicit offline registry fixture").hexdigest()

    def revalidate(self):
        self.rechecks += 1
        if self.error:
            raise self.error
        return self.registry_sha256

    def has_qualified_abstract(self, pairs=None):
        self.scope_calls.append(deepcopy(pairs))
        return self.qualified


class PairedScopeInterfaceChecks(unittest.TestCase):
    def setUp(self):
        self.live, self.clients, self.core_calls = LiveSearcher(), [], []
        self.fake_scope = ModuleType("paper_assistant.source_scope")
        self.fake_scope.Registry = SyntheticRegistry
        self.fake_scope.identify_source_requirement = lambda question: {
            "rule_version": "offline-scope-v1", "original_question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "resolution": "explicit", "required_scope": "abstract", "matched_expression": "abstract"}

    def client_factory(self, mode, budget):
        client = SimpleNamespace(policy=budget.policy, budget=budget, closed=False)
        client.close = lambda: setattr(client, "closed", True)
        self.clients.append(client)
        return client

    def core(self, query, pairs, searcher, store, client, *, project_root, top_k, max_chars, **options):
        self.core_calls.append(deepcopy(options) if not options else {"source_registry": options["source_registry"]})
        registry = options.get("source_registry")
        requirement = self.fake_scope.identify_source_requirement(query) if registry is not None else None
        if requirement is not None and (requirement["resolution"] == "ambiguous" or
                (requirement["required_scope"] == "abstract" and not registry.qualified)):
            reason = ("source_constraint_ambiguous" if requirement["resolution"] == "ambiguous"
                      else "source_scope_unavailable")
            return {"status": "answered", "query": query,
                    "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in pairs],
                    "answer": {"status": "answered", "claims": [{"claim": "摘要通常介绍研究问题、方法和结果。",
                               "basis": "model_knowledge", "citation_ids": []}], "reason": "当前摘要范围不可用于确认论文细节。",
                               "evidence_status": "none", "evidence_sources": []},
                    "error": None, "failure_stage": None, "stop_reason": reason, "search": None,
                    "context": {"question": query, "shown_evidence": [], "allowed_citation_ids": []},
                    "statistics": {"embedding": {"embedding_requests": 0, "failed_requests": 0,
                                                 "total_tokens": None}, "chat": None}}
        first = searcher.search_evidence(query, pairs, top_k=top_k)
        return {"status": "insufficient_evidence", "query": query, "selected_versions": first["selected_versions"],
                "answer": {"status": "insufficient_evidence", "claims": [], "reason": "offline core"},
                "error": None, "failure_stage": None, "stop_reason": "offline_core",
                "search": first, "context": prepare_context(first, max_chars=max_chars),
                "statistics": {"embedding": first["statistics"], "chat": None}}

    def paired(self, registry=None, pairs=None):
        with patch.dict(sys.modules, {"paper_assistant.source_scope": self.fake_scope}), \
             patch("paper_assistant.agent_comparison.answer_question", side_effect=self.core), \
             patch("paper_assistant.agent_comparison.answer_question_agent", side_effect=self.core):
            return run_paired_case("original question", [("p", "r")] if pairs is None else pairs,
                                   self.live, object(), self.client_factory,
                                   project_root=Path("."), source_registry=registry)

    def assert_preflight_stopped(self, pair, *, status, reason):
        self.assertEqual(self.live.calls, [])
        self.assertEqual(self.clients, [])
        self.assertEqual(self.core_calls, [])
        shared = pair["shared_first_retrieval"]
        self.assertIsNone(shared["search"])
        self.assertEqual(shared["actual_search_calls"], 0)
        self.assertEqual(shared["statistics"], {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None})
        self.assertEqual(pair["task"], "D9")
        self.assertEqual(pair["comparison_version"], SCOPED_COMPARISON_VERSION)
        for mode in ("fixed_rag", "agent"):
            result = pair["modes"][mode]["result"]
            self.assertEqual(pair["modes"][mode]["task"], "D9")
            self.assertEqual(pair["modes"][mode]["comparison_version"], SCOPED_COMPARISON_VERSION)
            self.assertEqual(result["task"], "D9")
            self.assertEqual(result["comparison_version"], SCOPED_COMPARISON_VERSION)
            self.assertEqual(result["registry_sha256"], pair["registry_sha256"])
            self.assertEqual(result["required_source_scope"], pair["required_source_scope"])
            self.assertEqual(result["status"], status)
            self.assertEqual(result["stop_reason"], reason)
            self.assertEqual(pair["modes"][mode]["llm_requests"], 0)
            self.assertEqual(pair["modes"][mode]["embedding_requests"], 0)

    def test_registry_opt_in_covers_selected_subset_and_is_passed_to_both_cores(self):
        registry = SyntheticRegistry()
        pair = self.paired(registry)
        self.assertEqual(pair["status"], "completed")
        self.assertEqual(pair["task"], "D9")
        self.assertEqual(pair["comparison_version"], SCOPED_COMPARISON_VERSION)
        self.assertEqual(pair["registry_sha256"], registry.registry_sha256)
        self.assertEqual(pair["required_source_scope"], "abstract")
        for report in pair["modes"].values():
            self.assertEqual(report["task"], "D9")
            self.assertEqual(report["comparison_version"], SCOPED_COMPARISON_VERSION)
            self.assertEqual(report["registry_sha256"], registry.registry_sha256)
            self.assertEqual(report["result"]["comparison_version"], SCOPED_COMPARISON_VERSION)
            self.assertEqual(report["result"]["registry_sha256"], registry.registry_sha256)
        self.assertEqual(registry.rechecks, 0)
        self.assertEqual(registry.scope_calls, [[("p", "r")]])
        self.assertEqual(len(self.live.calls), 1)
        self.assertEqual(self.live.calls[0][3], {})
        self.assertEqual(len(self.core_calls), 2)
        self.assertTrue(all(call["source_registry"] is registry for call in self.core_calls))
        self.assertEqual(len(self.clients), 2)
        self.assertTrue(all(client.closed for client in self.clients))

    def test_ambiguous_requirement_stops_both_modes_without_fake_retrieval(self):
        self.fake_scope.identify_source_requirement = lambda _: {
            "resolution": "ambiguous", "required_scope": None}
        registry = SyntheticRegistry()
        pair = self.paired(registry)
        self.assertEqual(self.live.calls, [])
        self.assertEqual(len(self.clients), 2)
        self.assertTrue(all(client.closed for client in self.clients))
        self.assertEqual(len(self.core_calls), 2)
        self.assertTrue(all(call["source_registry"] is registry for call in self.core_calls))
        self.assertIsNone(pair["shared_first_retrieval"]["search"])
        self.assertEqual(pair["shared_first_retrieval"]["actual_search_calls"], 0)
        self.assertEqual(pair["status"], "completed")
        self.assertIsNone(pair["error"])
        self.assertEqual(pair["registry_sha256"], registry.registry_sha256)
        self.assertIsNone(pair["required_source_scope"])
        for report in pair["modes"].values():
            self.assertEqual(report["status"], "answered")
            self.assertEqual(report["result"]["stop_reason"], "source_constraint_ambiguous")
            self.assertIsNone(report["result"]["error"])
            self.assertTrue(report["answer"]["reason"])
            self.assertEqual(report["answer"]["evidence_status"], "none")
            self.assertEqual(report["embedding_requests"], 0)
            self.assertIsNone(report["result"]["search"])

    def test_no_qualified_abstract_stops_before_shared_embedding(self):
        registry = SyntheticRegistry(qualified=False)
        pair = self.paired(registry)
        self.assertEqual(self.live.calls, [])
        self.assertEqual(len(self.clients), 2)
        self.assertTrue(all(client.closed for client in self.clients))
        self.assertEqual(len(self.core_calls), 2)
        self.assertTrue(all(call["source_registry"] is registry for call in self.core_calls))
        self.assertIsNone(pair["shared_first_retrieval"]["search"])
        self.assertEqual(pair["shared_first_retrieval"]["actual_search_calls"], 0)
        self.assertEqual(pair["status"], "completed")
        self.assertEqual(pair["shared_first_retrieval"]["program_stop"], "source_scope_unavailable")
        self.assertEqual(pair["registry_sha256"], registry.registry_sha256)
        self.assertEqual(pair["required_source_scope"], "abstract")
        for report in pair["modes"].values():
            self.assertEqual(report["status"], "answered")
            self.assertEqual(report["result"]["stop_reason"], "source_scope_unavailable")
            self.assertEqual(report["answer"]["evidence_status"], "none")
            self.assertEqual(report["embedding_requests"], 0)
            self.assertIsNone(report["result"]["search"])


    def test_registry_without_selected_pair_is_tool_error_before_shared_search(self):
        pair = self.paired(SyntheticRegistry(pairs=[("other", "r2")]))
        self.assert_preflight_stopped(pair, status="tool_error", reason="source_preflight_error")

    def test_invalid_scoped_selected_pairs_keep_zero_request_statistics(self):
        pair = self.paired(SyntheticRegistry(), pairs=[])
        self.assert_preflight_stopped(pair, status="tool_error", reason="invalid_paired_input")
        self.assertIsNone(pair["registry_sha256"])

    def test_unconstrained_question_does_not_require_qualified_abstract(self):
        self.fake_scope.identify_source_requirement = lambda _: {
            "resolution": "none", "required_scope": None}
        registry = SyntheticRegistry(qualified=False)
        pair = self.paired(registry)
        self.assertEqual(pair["status"], "completed")
        self.assertEqual(registry.scope_calls, [])
        self.assertEqual(len(self.live.calls), 1)

    def test_default_d8_cores_receive_no_registry_keyword_or_source_preflight(self):
        self.fake_scope.identify_source_requirement = lambda _: (_ for _ in ()).throw(AssertionError("must not load"))
        pair = self.paired()
        self.assertEqual(pair["status"], "completed")
        self.assertEqual(pair["task"], "D8")
        self.assertEqual(pair["comparison_version"], COMPARISON_VERSION)
        self.assertEqual(self.core_calls, [{}, {}])
        self.assertEqual(len(self.live.calls), 1)
        self.assertNotIn("source_requirement", pair["shared_first_retrieval"])
        self.assertNotIn("registry_sha256", pair)
        self.assertNotIn("required_source_scope", pair)
        for report in pair["modes"].values():
            self.assertEqual(report["task"], "D8")
            self.assertEqual(report["comparison_version"], COMPARISON_VERSION)
            self.assertNotIn("registry_sha256", report)
            self.assertNotIn("required_source_scope", report)
            self.assertNotIn("comparison_version", report["result"])


SCOPED_SEARCH_CASES = (ScopedRetrievalChecks, FrozenScopeChecks, PairedScopeInterfaceChecks)


if __name__ == "__main__":
    with patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")), \
         patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
        unittest.main(verbosity=2)
