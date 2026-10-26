"""D9 D focused offline source/fault combination tests using temporary fixtures."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

import httpx

from paper_assistant.agent import answer_question_agent
from paper_assistant.retrieval import point_id
from paper_assistant.search import SearchError
from paper_assistant.source_scope import Registry, SourceScopeError
from scripts import check_agent, check_d9_c_deadline, check_scoped_answering as scoped_fixtures
from scripts.check_agent import answer_action, response, retry_action
from scripts.check_llm import FakeClock
from scripts.check_scoped_answering import ScopedSequencedSearcher, fixed_answer
from scripts.check_source_scope import SourceScopeFixture


class SourceFaultCombinationChecks(unittest.TestCase):
    # Reuse the actual PDF/Registry/SDK fixture without inheriting its tests.
    setUp = scoped_fixtures.SyntheticSourceFlowChecks.setUp
    client = scoped_fixtures.SyntheticSourceFlowChecks.client
    request_data = scoped_fixtures.SyntheticSourceFlowChecks.request_data
    searcher = scoped_fixtures.SyntheticSourceFlowChecks.searcher
    core = scoped_fixtures.SyntheticSourceFlowChecks.core

    def assert_expired_fault(self, result, code):
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["error"]["code"], "deadline_exceeded")
        self.assertEqual(result["interrupted_failure"]["status"], "tool_error")
        self.assertEqual(result["interrupted_failure"]["error"]["code"], code)
        self.assertNotIn(check_agent.SECRET, json.dumps(result))

    def test_bound_input_text_range_and_version_damage_are_not_normal_unavailability(self):
        corruptions = {
            "wrong_version": lambda d: d["documents"][0].update(parse_revision="wrong_revision"),
            "pdf_identity": lambda d: d["documents"][0].update(pdf_sha256="0" * 64),
            "range_text_hash": lambda d: d["documents"][0]["regions"][0].update(text_sha256="0" * 64),
            "range_outside_segment": lambda d: d["documents"][0]["regions"][0].update(segment_char_end=1000000),
        }
        for name, corrupt in corruptions.items():
            with self.subTest(damage=name), SourceScopeFixture() as f:
                corrupt(f.document)
                f._write_registry()
                with self.assertRaises(SourceScopeError) as caught:
                    Registry(f.root, f.store, f.pairs)
                self.assertTrue(caught.exception.code)
                self.assertNotEqual(caught.exception.code, "source_scope_unavailable")


    def test_ineligible_raw_candidate_damage_plus_expiry_keeps_paid_first_round(self):
        original = self.registry.qualify
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                self.clock = FakeClock()
                client, requests = self.client()
                searcher = self.searcher([self.f.body_id, self.f.abstract_id])
                def damaged_body(candidate):
                    if candidate["chunk_id"] == self.f.body_id:
                        self.store.chunks[self.f.body_id]["text"] = "corrupted raw body candidate"
                        self.clock.advance(121)
                    return original(candidate)
                with patch.object(self.registry, "qualify", side_effect=damaged_body):
                    result = self.core(mode, client, searcher)
                self.store.chunks[self.f.body_id] = deepcopy(self.f.chunks[self.f.body_id])
                self.assert_expired_fault(result, "source_store_snapshot_mismatch")
                self.assertEqual(len(searcher.calls), 1)
                self.assertEqual(requests, [])
                self.assertEqual(result["statistics"]["embedding"]["embedding_requests"], 1)
                self.assertEqual(result["statistics"]["embedding"]["total_tokens"], 7)


    def test_valid_abstract_terminal_repair_arriving_late_never_publishes(self):
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                self.clock = FakeClock()
                action = fixed_answer if mode == "fixed_rag" else answer_action
                def late_repair(request):
                    self.clock.advance(121)
                    status, body = response(action(self.f.abstract_id))
                    return httpx.Response(status, json=body, request=request)
                client, requests = self.client(
                    response(action(self.f.abstract_id, self.f.body_id)), late_repair)
                original_deadline = client.budget.deadline
                searcher = self.searcher([self.f.body_id, self.f.abstract_id])
                result = self.core(mode, client, searcher)
                self.assertEqual(result["status"], "budget_exceeded")
                self.assertIsNone(result["answer"])
                self.assertEqual(len(requests), 2)
                self.assertEqual(len(searcher.calls), 1)
                self.assertEqual(result["statistics"]["chat"]["repairs"], 1)
                self.assertEqual(result["statistics"]["chat"]["total_tokens"], 50)
                self.assertEqual(client.budget.deadline, original_deadline)
                if mode == "agent":
                    repair_payload = json.loads(self.request_data(requests[-1])[1]["content"])
                    self.assertNotIn("retry_search", repair_payload["allowed_actions"])
                    self.assertTrue(result["action_steps"][-1]["terminal_only"])

    def test_source_citation_repair_still_citing_body_is_rejected_without_more_work(self):
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                self.clock = FakeClock()
                action = fixed_answer if mode == "fixed_rag" else answer_action
                invalid = response(action(self.f.abstract_id, self.f.body_id))
                client, requests = self.client(invalid, invalid)
                searcher = self.searcher([self.f.body_id, self.f.abstract_id])
                result = self.core(mode, client, searcher)
                self.assertEqual(result["status"], "invalid_output")
                self.assertIsNone(result["answer"])
                self.assertEqual(len(requests), 2)
                self.assertEqual(len(searcher.calls), 1)
                self.assertEqual(result["statistics"]["chat"]["repairs"], 1)
                self.assertEqual(result["context"]["allowed_citation_ids"], [self.f.abstract_id])
                self.assertEqual(len(result["source_scope_checks"]), 2)
                self.assertEqual(result["source_scope_checks"][-1]["status"], "invalid_output")
                self.assertEqual([c["chunk_id"] for c in result["source_scope_checks"][-1]["checks"]],
                                 [self.f.abstract_id, self.f.body_id])

    def test_late_pdf_open_fault_with_valid_abstract_keeps_fault_and_usage(self):
        for mode in ("fixed_rag", "agent"):
            with self.subTest(mode=mode):
                self.clock = FakeClock()
                action = fixed_answer if mode == "fixed_rag" else answer_action
                client, requests = self.client(response(action(self.f.abstract_id)))
                searcher = self.searcher([self.f.abstract_id])
                def pdf_failure(*args, **kwargs):
                    self.clock.advance(121)
                    raise OSError("private PDF error")
                with patch("paper_assistant.citations.fitz.open", side_effect=pdf_failure):
                    result = self.core(mode, client, searcher)
                self.assert_expired_fault(result, "pdf_invalid")
                self.assertEqual(len(requests), 1)
                self.assertEqual(result["statistics"]["chat"]["total_tokens"], 25)
                self.assertEqual(result["statistics"]["chat"]["repairs"], 0)


    def test_new_qualified_raw_retry_chunk_omitted_by_budget_stops_before_final_chat(self):
        # Widen only this temporary reviewed abstract to its complete existing
        # PDF paragraph. The formerly mixed full paragraph now qualifies, but
        # it exceeds the character budget that fits the shorter first chunk.
        complete = self.f.abstract_segment["text"]
        self.registry = self.f.set_region(segment_char_end=len(complete),
            text_sha256=hashlib.sha256(complete.encode("utf-8")).hexdigest())
        self.assertTrue(self.registry.qualify(self.f.chunks[self.f.mixed_id])["eligible"])
        maximum = len(self.f.chunks[self.f.abstract_id]["text"])
        self.assertGreater(len(self.f.chunks[self.f.mixed_id]["text"]), maximum)
        client, requests = self.client(response(retry_action("Find additional abstract evidence")))
        searcher = ScopedSequencedSearcher(
            self.f.search([self.f.abstract_id])["results"],
            self.f.search([self.f.mixed_id])["results"], profile="synthetic_profile")
        result = answer_question_agent(self.f.question, self.pairs, searcher,
            self.store, client, project_root=self.root, source_registry=self.registry,
            max_chars=maximum)
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["stop_reason"], "no_new_shown_evidence")
        self.assertEqual(result["answer"]["claims"], [])
        self.assertEqual(result["merge_trace"]["new_returned_ids"], [self.f.mixed_id])
        self.assertEqual(result["merge_trace"]["new_shown_ids"], [])
        self.assertEqual(result["initial_context"]["allowed_citation_ids"], [self.f.abstract_id])
        # Existing full-chunk selection stops at the first oversized retry
        # candidate. It does not skip forward to fill the remaining budget.
        self.assertEqual(result["context"]["allowed_citation_ids"], [])
        self.assertEqual(result["context"]["empty_selection_reason"], "character_budget")
        self.assertEqual(len(searcher.calls), 2)
        self.assertEqual(len(requests), 1)
        self.assertEqual(result["statistics"]["chat"]["repairs"], 0)
        self.assertEqual(result["statistics"]["embedding"]["embedding_requests"], 2)
        self.assertEqual(searcher.calls[1]["allowed_point_ids"],
            self.registry.abstract_point_ids("synthetic_profile", self.pairs))



class ScopedSearchFaultCombinationChecks(unittest.TestCase):
    setUp = check_d9_c_deadline.SearchChecks.setUp
    searcher = check_d9_c_deadline.SearchChecks.searcher

    def test_scope_ready_consumes_deadline_before_native_embedding_http(self):
        searcher = self.searcher()
        allowed = [point_id(self.f.profile["index_profile_id"], self.f.bundles[0].chunks[0]["chunk_id"])]
        original = searcher._ready_filter
        def ready(pairs):
            result = original(pairs)
            self.clock.advance(120)
            return result
        with patch.object(searcher, "_ready_filter", side_effect=ready):
            with self.assertRaises(SearchError) as caught:
                searcher.search_evidence("question", [self.f.pairs[0]],
                    allowed_point_ids=allowed, remaining_seconds=self.budget.remaining_seconds)
        self.assertEqual(caught.exception.status, "budget_exceeded")
        self.assertEqual(caught.exception.statistics["embedding_requests"], 0)
        self.assertEqual(self.requests, [])

    def test_scoped_qdrant_fault_plus_expiry_keeps_one_native_http_and_known_tokens(self):
        searcher = self.searcher()
        allowed = [point_id(self.f.profile["index_profile_id"], self.f.bundles[0].chunks[0]["chunk_id"])]
        def query_failure(**kwargs):
            self.clock.advance(121)
            raise RuntimeError("private vector store error")
        with patch.object(self.f.vectors.client, "query_points", side_effect=query_failure), \
             patch.object(self.f.reader, "get_chunk", side_effect=AssertionError("no source lookup after failed query")) as lookup:
            with self.assertRaises(SearchError) as caught:
                searcher.search_evidence("question", [self.f.pairs[0]],
                    allowed_point_ids=allowed, remaining_seconds=self.budget.remaining_seconds)
        error = caught.exception
        self.assertEqual(error.status, "budget_exceeded")
        self.assertEqual(error.statistics["embedding_requests"], 1)
        self.assertEqual(error.statistics["total_tokens"], 17)
        self.assertEqual(error.statistics["interrupted_failure"]["stage"], "query")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(lookup.call_count, 0)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
