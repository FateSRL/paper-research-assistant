"""D5 D：引用回查与固定 RAG 流程的离线边界检查。

运行：python -X utf8 -m scripts.check_rag
使用临时真实 PDF、合成 chunk、借用 fake store/searcher、真实 SDK 的
MockTransport；不读取 .env、不访问正式库、不发送真实网络请求。
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
import httpx

from paper_assistant.citations import validate_citations
from paper_assistant.config import LLMSettings
from paper_assistant.context import prepare_context
from paper_assistant.generation import DraftParseError, parse_answer_draft
from paper_assistant.llm_client import ChatBudget, ChatPolicy, RecordedLLM
from paper_assistant.rag import answer_question
from paper_assistant.schemas import AnswerDraft, Claim
from paper_assistant.search import SearchError
from scripts.check_generation import answered, encoded
from scripts.check_llm import FakeClock, completion, http_error


MOCK_HTTP_SENDS = 0
OFFLINE_SECRET = "offline-rag-credential-do-not-log"


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


class FakeStore:
    def __init__(self, chunks):
        self.chunks, self.calls, self.closed = deepcopy(chunks), [], False
        self.error, self.on_read = None, None

    def get_chunk(self, chunk_id):
        self.calls.append(chunk_id)
        if self.on_read:
            self.on_read()
        if self.error:
            raise self.error
        return deepcopy(self.chunks.get(chunk_id))

    def get_version_chunks(self, paper_id, parse_revision):
        return sorted((deepcopy(row) for row in self.chunks.values()
                       if (row["paper_id"], row["parse_revision"]) == (paper_id, parse_revision)),
                      key=lambda row: (row["pdf_page"], row["source_block_index"], row["char_start"], row["chunk_id"]))

    def close(self):
        self.closed = True


class FakeSearcher:
    def __init__(self, rows, *, mutate=None, error=None, on_search=None):
        self.rows, self.calls = deepcopy(rows), []
        self.mutate, self.error, self.on_search, self.closed = mutate, error, on_search, False

    def search_evidence(self, query, selected_versions, top_k=5):
        self.calls.append((query, deepcopy(selected_versions), top_k))
        if self.on_search:
            self.on_search()
        if self.error:
            raise self.error
        result = {"status": "success" if self.rows else "no_hits", "query": query,
                  "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in selected_versions],
                  "results": deepcopy(self.rows), "returned_count": len(self.rows), "top_k": top_k,
                  "index_profile_id": "offline-profile", "statistics": {
                      "embedding_requests": 1, "failed_requests": 0, "total_tokens": 7}}
        if self.mutate:
            self.mutate(result)
        return result

    def close(self):
        self.closed = True


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="d5-rag-offline-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pdf = self.root / "data/papers/offline.pdf"
        self.pdf.parent.mkdir(parents=True)
        with fitz.open() as document:
            for number in range(2):
                page = document.new_page()
                page.insert_text((50, 50), "Synthetic evidence page " + str(number + 1))
            document.save(self.pdf)
        self.pdf_hash = digest(self.pdf.read_bytes())
        self.row = self.chunk()
        self.context = self.context_for([self.row])
        self.store = FakeStore({self.row["chunk_id"]: self.row})
        self.clock = FakeClock()
        self.settings = LLMSettings(provider="deepseek", model_id="offline-model", api_key=OFFLINE_SECRET,
                                    base_url="https://example.invalid/v1", timeout=30.0)

    def chunk(self, identifier="p1_r1_p2_c1", *, text="Original reasoning and action evidence.\nExact whitespace  preserved.",
              page=2, rank=1, paper_id="p1", revision="r1"):
        return {"chunk_id": identifier, "paper_id": paper_id, "parse_revision": revision,
                "pdf_page": page, "pdf_sha256": self.pdf_hash, "text": text, "text_sha256": digest(text),
                "segment_id": "segment-1", "char_start": 0, "char_end": len(text),
                "filter_revision": "offline-filter", "source_block_index": 0, "source_line_indices": [0],
                "segment_bbox": [50.0, 40.0, 400.0, 100.0], "title": "Offline test paper",
                "arxiv_version": "v1", "source_url": "https://arxiv.org/abs/0000.00000v1",
                "local_path": "data/papers/offline.pdf", "rank": rank, "score": 0.8}

    def context_for(self, rows, *, versions=None, max_chars=8000):
        result = {"status": "success" if rows else "no_hits", "query": "What does the evidence say?",
                  "selected_versions": versions or [{"paper_id": "p1", "parse_revision": "r1"}],
                  "results": rows, "returned_count": len(rows), "top_k": 5, "statistics": {}}
        return prepare_context(result, max_chars=max_chars)

    def draft(self, *identifiers):
        return answered(list(identifiers) or [self.row["chunk_id"]])

    def citations(self, draft=None, context=None, store=None):
        return validate_citations(draft or self.draft(), context or self.context,
                                  store or self.store, project_root=self.root)

    def client(self, *outcomes, policy=None, budget=None):
        requests, remaining = [], list(outcomes)

        def handle(request):
            global MOCK_HTTP_SENDS
            MOCK_HTTP_SENDS += 1
            requests.append(request)
            if not remaining:
                raise AssertionError("SDK 请求超出测试预期")
            outcome = remaining.pop(0)
            if callable(outcome):
                return outcome(request)
            status, body = outcome
            return httpx.Response(status, json=body, request=request)

        client = RecordedLLM(self.settings, policy=policy, budget=budget,
                             transport=httpx.MockTransport(handle), clock=self.clock)
        self.addCleanup(client.close)
        return client, requests


class CitationChecks(Fixture):
    def assert_failure(self, result, status):
        self.assertEqual(result["status"], status)
        self.assertEqual(result["evidence_refs"], [])
        self.assertEqual(result["evidence_sources"], [])
        self.assertTrue(result["error"]["code"])
        self.assertNotIn(OFFLINE_SECRET, encoded(result))

    def test_real_pdf_located_and_refs_are_program_derived(self):
        result = self.citations(AnswerDraft.model_validate(self.draft()))
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["evidence_refs"], [{key: self.row[key] for key in
                                                  ("chunk_id", "paper_id", "parse_revision", "pdf_page")}])
        source = result["evidence_sources"][0]
        self.assertEqual(source["text"], self.row["text"])
        self.assertEqual(source["pdf_absolute_path"], str(self.pdf.resolve()))
        self.assertEqual(source["actual_page_count"], 2)
        self.assertEqual(self.store.calls, [self.row["chunk_id"]])

    def test_repeated_ids_keep_each_check_but_deduplicate_sources_by_first_use(self):
        second = self.chunk("p1_r1_p1_c1", text="Second chunk.", page=1, rank=2)
        context = self.context_for([self.row, second])
        store = FakeStore({self.row["chunk_id"]: self.row, second["chunk_id"]: second})
        draft = {"status": "answered", "claims": [
            {"claim": "First", "citation_ids": [second["chunk_id"], self.row["chunk_id"]]},
            {"claim": "Second", "citation_ids": [self.row["chunk_id"], second["chunk_id"]]}]}
        result = self.citations(draft, context, store)
        self.assertEqual(result["status"], "valid")
        self.assertEqual(len(result["checks"]), 4)
        self.assertEqual([row["chunk_id"] for row in result["evidence_refs"]],
                         [second["chunk_id"], self.row["chunk_id"]])
        self.assertEqual([(row["claim_index"], row["citation_index"]) for row in result["checks"]],
                         [(0, 0), (0, 1), (1, 0), (1, 1)])
        self.assertEqual(store.calls, [second["chunk_id"], self.row["chunk_id"]])

    def test_same_pdf_is_opened_once_for_multiple_distinct_sources(self):
        second = self.chunk("p1_r1_p1_c1", text="Second chunk.", page=1, rank=2)
        context = self.context_for([self.row, second])
        store = FakeStore({self.row["chunk_id"]: self.row, second["chunk_id"]: second})
        with patch("paper_assistant.citations.fitz.open", wraps=fitz.open) as opened:
            result = self.citations(self.draft(self.row["chunk_id"], second["chunk_id"]), context, store)
        self.assertEqual(result["status"], "valid")
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(len(result["evidence_sources"]), 2)

    def test_fabricated_and_database_only_ids_reject_before_any_lookup(self):
        hidden = self.chunk("hidden")
        self.store.chunks["hidden"] = hidden
        for identifier in ["fabricated", "hidden"]:
            with self.subTest(identifier=identifier):
                self.store.calls.clear()
                self.assert_failure(self.citations(self.draft(identifier)), "invalid_output")
                self.assertEqual(self.store.calls, [])

    def test_omitted_candidate_is_not_allowed_even_when_present_in_store(self):
        hidden = self.chunk("hidden", text="This chunk will be omitted.", rank=2)
        context = self.context_for([self.row, hidden], max_chars=len(self.row["text"]))
        self.store.chunks["hidden"] = hidden
        self.assert_failure(self.citations(self.draft("hidden"), context), "invalid_output")
        self.assertEqual(self.store.calls, [])

    def test_mixed_valid_and_bad_citation_never_publishes_partial_sources(self):
        result = self.citations(self.draft(self.row["chunk_id"], "fabricated"))
        self.assert_failure(result, "invalid_output")
        self.assertTrue(any(row["chunk_id"] == "fabricated" for row in result["checks"]))

    def test_source_fault_takes_priority_over_model_fault_for_whole_draft(self):
        self.store.chunks.clear()
        result = self.citations(self.draft("fabricated", self.row["chunk_id"]))
        self.assert_failure(result, "tool_error")
        self.assertEqual([row["status"] for row in result["checks"]], ["invalid_output", "tool_error"])
        self.assertEqual(self.store.calls, [self.row["chunk_id"]])

    def test_missing_chunk_or_lookup_exception_is_system_failure(self):
        for error in [None, RuntimeError(OFFLINE_SECRET)]:
            with self.subTest(error=type(error).__name__):
                store = FakeStore({})
                store.error = error
                self.assert_failure(self.citations(store=store), "tool_error")

    def test_store_identity_page_or_text_mismatch_is_system_failure(self):
        updates = [{"paper_id": "other"}, {"parse_revision": "r2"}, {"pdf_page": 1},
                   {"chunk_id": "other"}, {"text_sha256": "0" * 64},
                   {"text": "Changed", "text_sha256": digest("Changed")}]
        for update in updates:
            with self.subTest(update=update):
                store = FakeStore({self.row["chunk_id"]: {**self.row, **update}})
                self.assert_failure(self.citations(store=store), "tool_error")

    def test_exact_selected_pairs_cannot_become_cross_product(self):
        context = self.context_for([self.row], versions=[{"paper_id": "p1", "parse_revision": "r1"},
                                                       {"paper_id": "p2", "parse_revision": "r2"}])
        store = FakeStore({self.row["chunk_id"]: {**self.row, "parse_revision": "r2"}})
        self.assert_failure(self.citations(context=context, store=store), "tool_error")

    def test_context_allowlist_and_snapshot_tamper_fail_before_store(self):
        for change in [lambda ctx: ctx["allowed_citation_ids"].append("fake"),
                       lambda ctx: ctx["shown_evidence"][0].update(shown_text="tampered")]:
            with self.subTest(change=change.__name__):
                context = deepcopy(self.context)
                change(context)
                self.assert_failure(self.citations(context=context), "tool_error")
                self.assertEqual(self.store.calls, [])

    def test_model_cannot_supply_source_metadata_or_program_status(self):
        for draft in [{**self.draft(), "evidence_refs": []}, {**self.draft(), "status": "tool_error"},
                      {"status": "answered", "claims": [{"claim": "x", "citation_ids": [self.row["chunk_id"]],
                                                            "pdf_page": 1}]}]:
            with self.subTest(draft=draft):
                self.assert_failure(self.citations(draft), "invalid_output")
                self.assertEqual(self.store.calls, [])

    def test_model_construct_and_nested_claim_instance_cannot_bypass_strict_schema(self):
        claim = Claim.model_construct(claim="Invalid unvalidated claim", citation_ids=[])
        values = [AnswerDraft.model_construct(status="answered", claims=[claim]),
                  {"status": "answered", "claims": [claim]}]
        for value in values:
            with self.subTest(model_instance=isinstance(value, AnswerDraft)):
                self.assert_failure(self.citations(value), "invalid_output")
                self.assertEqual(self.store.calls, [])

    def test_store_cannot_mutate_external_context_to_expand_frozen_shown_ids(self):
        context = deepcopy(self.context)
        original_text = self.row["text"]

        def mutate_context():
            context["allowed_citation_ids"].append("fabricated")
            context["shown_evidence"][0]["shown_text"] = "mutated externally"

        self.store.on_read = mutate_context
        result = self.citations(self.draft(self.row["chunk_id"], "fabricated"), context)
        self.assert_failure(result, "invalid_output")
        self.assertEqual(result["checks"][0]["status"], "valid")
        self.assertEqual(result["checks"][1]["code"], "citation_not_shown")
        self.assertEqual(self.store.chunks[self.row["chunk_id"]]["text"], original_text)
        self.assertEqual(self.store.calls, [self.row["chunk_id"]])

    def test_missing_pdf_hash_mismatch_or_unreadable_pdf_is_system_failure(self):
        for mode in ["missing", "wrong_hash", "invalid_pdf"]:
            with self.subTest(mode=mode):
                row = deepcopy(self.row)
                if mode == "missing":
                    row["local_path"] = "data/papers/missing.pdf"
                elif mode == "wrong_hash":
                    row["pdf_sha256"] = "0" * 64
                else:
                    bad = self.pdf.parent / "broken.pdf"
                    bad.write_bytes(b"Not a PDF document")
                    row.update(local_path="data/papers/broken.pdf", pdf_sha256=digest(bad.read_bytes()))
                self.assert_failure(self.citations(store=FakeStore({self.row["chunk_id"]: row})), "tool_error")

    def test_page_past_actual_pdf_extent_is_system_failure(self):
        row = self.chunk(page=3)
        context = self.context_for([row])
        self.assert_failure(self.citations(context=context, store=FakeStore({row["chunk_id"]: row})), "tool_error")

    def test_pdf_path_must_resolve_inside_real_papers_directory(self):
        for local_path in ["../outside.pdf", "data/papers/../../outside.pdf", str(self.pdf.resolve()),
                           "data/elsewhere/offline.pdf", "data/papers/missing-dir/../../outside.pdf"]:
            with self.subTest(local_path=local_path):
                row = {**self.row, "local_path": local_path}
                self.assert_failure(self.citations(store=FakeStore({self.row["chunk_id"]: row})), "tool_error")

    def test_insufficient_decision_reads_no_source_and_inputs_are_not_mutated(self):
        before_context, before_draft = deepcopy(self.context), deepcopy(self.draft())
        result = self.citations({"status": "insufficient_evidence", "reason": "This run lacks evidence."})
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["evidence_refs"], [])
        self.assertEqual(self.store.calls, [])
        self.citations(before_draft)
        self.assertEqual(self.context, before_context)
        self.assertEqual(before_draft, self.draft())


class RAGChecks(Fixture):
    def run_rag(self, client, *, searcher=None, store=None, **options):
        self.searcher = searcher or FakeSearcher([self.row])
        return answer_question("What does the evidence say?", [("p1", "r1")], self.searcher,
                               store or self.store, client, project_root=self.root, **options)

    def assert_chat_counts(self, result, requests, expected, *, repairs=0, retries=0):
        self.assertEqual(len(requests), expected)
        stats = result["statistics"]["chat"]
        self.assertEqual(stats["sdk_request_attempts"], expected)
        self.assertEqual(stats["http_request_attempts"], expected)
        self.assertEqual(stats["repairs"], repairs)
        self.assertEqual(stats["network_retries"], retries)
        return stats

    def assert_no_answer(self, result, status):
        self.assertEqual(result["status"], status)
        self.assertIsNone(result["answer"])
        self.assertTrue(result["error"]["code"])
        self.assertNotIn(OFFLINE_SECRET, encoded(result))

    def test_success_is_one_fixed_search_then_generation_then_citation_validation(self):
        client, requests = self.client((200, completion(encoded(self.draft()))))
        result = self.run_rag(client)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"]["claims"], self.draft()["claims"])
        self.assertEqual(result["answer"]["semantic_support_status"], "not_reviewed")
        self.assertEqual(result["answer"]["evidence_refs"][0]["pdf_page"], 2)
        self.assertEqual(self.searcher.calls, [("What does the evidence say?", [("p1", "r1")], 5)])
        self.assertEqual(len(result["citation_checks"]), 1)
        self.assertEqual(result["statistics"]["embedding"]["embedding_requests"], 1)
        self.assert_chat_counts(result, requests, 1)
        self.assertIsNone(result["failure_stage"])

    def test_borrowed_resources_remain_open_on_success_and_failure(self):
        for draft in [self.draft(), self.draft("fabricated")]:
            with self.subTest(identifier=draft["claims"][0]["citation_ids"][0]):
                client, requests = self.client((200, completion(encoded(draft))),
                                               (200, completion(encoded(self.draft("still bad")))))
                result = self.run_rag(client)
                self.assertIn(result["status"], ["answered", "invalid_output"])
                self.assertFalse(client._closed)
                self.assertFalse(self.store.closed)
                self.assertFalse(self.searcher.closed)

    def test_no_hits_and_character_budget_empty_context_answer_without_paper_sources(self):
        draft = {"status": "answered", "claims": [{"claim": "检索增强生成先检索外部资料，再结合资料生成回答。",
                 "basis": "model_knowledge", "citation_ids": []}], "reason": "本轮没有论文原文支持；这里解释通用概念。"}
        for rows, options in [([], {}), ([self.row], {"max_chars": 1})]:
            with self.subTest(rows=len(rows)):
                self.store.calls.clear()
                client, requests = self.client((200, completion(encoded(draft))))
                result = self.run_rag(client, searcher=FakeSearcher(rows), **options)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(result["answer"]["claims"], draft["claims"])
                self.assertEqual(result["answer"]["evidence_status"], "none")
                self.assertEqual(result["answer"]["evidence_sources"], [])
                self.assertEqual(self.store.calls, [])
                self.assertEqual(len(self.searcher.calls), 1)
                self.assert_chat_counts(result, requests, 1)
                payload = json.loads(requests[0].content)["messages"]
                self.assertEqual(json.loads(payload[1]["content"])["shown_evidence"], [])
        mixed = self.draft()
        mixed["claims"][0]["basis"] = "paper_evidence"
        mixed["claims"].extend(deepcopy(draft["claims"]))
        mixed["claims"].append({"claim": "由这些原文可以推测该方法需要合理选择检索资料。",
                                "basis": "analysis", "citation_ids": [self.row["chunk_id"]]})
        client, requests = self.client((200, completion(encoded(mixed))))
        result = self.run_rag(client)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"]["evidence_status"], "mixed")
        self.assertEqual(len(result["answer"]["evidence_sources"]), 1)
        self.assertEqual(self.store.calls, [self.row["chunk_id"]])
        self.assert_chat_counts(result, requests, 1)

    def test_model_insufficient_decision_is_repaired_to_knowledge_without_source_lookup(self):
        draft = {"status": "insufficient_evidence", "reason": "Shown evidence does not answer this question."}
        useful = {"status": "answered", "claims": [{"claim": "可以先说明所问概念，再分析需要哪些信息。",
                  "basis": "analysis", "citation_ids": []}]}
        client, requests = self.client((200, completion(encoded(draft))), (200, completion(encoded(useful))))
        result = self.run_rag(client)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"]["claims"], useful["claims"])
        self.assertEqual(self.store.calls, [])
        self.assertEqual(result["citation_repairs"], [])
        self.assert_chat_counts(result, requests, 2, repairs=1)

    def test_invalid_inputs_fail_before_search_and_chat(self):
        cases = [(" ", [("p1", "r1")], {}), ("question", [], {}),
                 ("question", [("p1", "r1")] * 2, {}),
                 ("question", [("p1", "r1"), ("p2", "r1"), ("p3", "r1"), ("p4", "r1")], {}),
                 ("question", [("p1", "r1")], {"top_k": 4}),
                 ("question", [("p1", "r1")], {"top_k": True}),
                 ("question", [("p1", "r1")], {"max_chars": 8001}),
                 ("question", [("p1", "r1")], {"max_chars": 0})]
        for question, versions, options in cases:
            with self.subTest(question=question, versions=versions, options=options):
                client, requests = self.client()
                searcher = FakeSearcher([self.row])
                result = answer_question(question, versions, searcher, self.store, client,
                                         project_root=self.root, **options)
                self.assert_no_answer(result, "tool_error")
                self.assertEqual(searcher.calls, [])
                self.assert_chat_counts(result, requests, 0)

    def test_expired_global_budget_prevents_even_search(self):
        budget = ChatBudget(clock=self.clock)
        self.clock.advance(121)
        client, requests = self.client(budget=budget)
        result = self.run_rag(client)
        self.assert_no_answer(result, "budget_exceeded")
        self.assertEqual(self.searcher.calls, [])
        self.assert_chat_counts(result, requests, 0)

    def test_search_failure_preserves_embedding_counts_and_safe_failure(self):
        for error in [SearchError(OFFLINE_SECRET, stage="embedding", statistics={
                "embedding_requests": 1, "failed_requests": 1, "total_tokens": None}),
                RuntimeError(OFFLINE_SECRET)]:
            with self.subTest(kind=type(error).__name__):
                client, requests = self.client()
                result = self.run_rag(client, searcher=FakeSearcher([], error=error))
                self.assert_no_answer(result, "tool_error")
                self.assert_chat_counts(result, requests, 0)
                if isinstance(error, SearchError):
                    self.assertEqual(result["statistics"]["embedding"], error.statistics)
                    self.assertEqual(result["search_error"]["stage"], "embedding")

    def test_untrusted_search_error_stage_is_replaced_with_fixed_stage(self):
        error = SearchError(OFFLINE_SECRET, stage=OFFLINE_SECRET, statistics={"embedding_requests": 0})
        client, requests = self.client()
        result = self.run_rag(client, searcher=FakeSearcher([], error=error))
        self.assert_no_answer(result, "tool_error")
        self.assertEqual(result["search_error"]["stage"], "retrieval")
        self.assert_chat_counts(result, requests, 0)

    def test_search_envelope_cannot_change_query_versions_top_k_or_scope(self):
        changes = [lambda r: r.update(query="other"), lambda r: r.update(top_k=4),
                   lambda r: r.update(top_k=True), lambda r: r.update(selected_versions=[
                       {"paper_id": "p1", "parse_revision": "r2"}]),
                   lambda r: r.update(returned_count=0),
                   lambda r: r["results"][0].update(paper_id="foreign")]
        for number, mutate in enumerate(changes):
            with self.subTest(number=number):
                client, requests = self.client()
                result = self.run_rag(client, searcher=FakeSearcher([self.row], mutate=mutate))
                self.assert_no_answer(result, "tool_error")
                self.assertEqual(self.store.calls, [])
                self.assert_chat_counts(result, requests, 0)

    def test_envelope_must_preserve_entire_pair_list_not_just_candidate_paper(self):
        client, requests = self.client()
        searcher = FakeSearcher([self.row], mutate=lambda r: r.update(selected_versions=[
            {"paper_id": "p1", "parse_revision": "r1"}]))
        result = answer_question("What does the evidence say?", [("p1", "r1"), ("p2", "r2")],
                                 searcher, self.store, client, project_root=self.root)
        self.assert_no_answer(result, "tool_error")
        self.assert_chat_counts(result, requests, 0)

    def test_search_that_crosses_deadline_keeps_search_but_sends_no_chat(self):
        client, requests = self.client()
        result = self.run_rag(client, searcher=FakeSearcher([self.row], on_search=lambda: self.clock.advance(121)))
        self.assert_no_answer(result, "budget_exceeded")
        self.assertIsNotNone(result["search"])
        self.assertEqual(result["statistics"]["embedding"]["embedding_requests"], 1)
        self.assert_chat_counts(result, requests, 0)

    def test_bad_citation_repairs_once_with_original_evidence_and_records_both_checks(self):
        client, requests = self.client((200, completion(encoded(self.draft("fabricated")))),
                                       (200, completion(encoded(self.draft()))))
        result = self.run_rag(client)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(len(result["citation_checks"]), 2)
        self.assertEqual([r["status"] for r in result["citation_checks"]], ["invalid_output", "valid"])
        self.assertEqual(len(result["citation_repairs"]), 1)
        first, second = [json.loads(request.content)["messages"] for request in requests]
        self.assertEqual(first, second[:2])
        self.assertEqual(result["citation_repairs"][0]["messages"], second)
        self.assertEqual(result["citation_repairs"][0]["draft"]["claims"], self.draft()["claims"])
        self.assertEqual(len(self.searcher.calls), 1)
        self.assert_chat_counts(result, requests, 2, repairs=1)

    def test_repeated_bad_citation_fails_entire_answer_without_dropping_claim(self):
        draft = {"status": "answered", "claims": [self.draft()["claims"][0],
                                                   {"claim": "Unsupported", "citation_ids": ["fake"]}]}
        client, requests = self.client((200, completion(encoded(draft))), (200, completion(encoded(draft))))
        result = self.run_rag(client)
        self.assert_no_answer(result, "invalid_output")
        self.assertEqual(len(result["citation_checks"]), 2)
        self.assertEqual(result["generation"]["draft"]["claims"], draft["claims"])
        self.assert_chat_counts(result, requests, 2, repairs=1)

    def test_c_format_repair_uses_only_shared_repair_so_d_cannot_repair_again(self):
        client, requests = self.client((200, completion("not JSON")),
                                       (200, completion(encoded(self.draft("fake")))))
        result = self.run_rag(client)
        self.assert_no_answer(result, "invalid_output")
        self.assertEqual(len(result["generation"]["generation_attempts"]), 2)
        self.assertEqual(result["citation_repairs"], [])
        self.assert_chat_counts(result, requests, 2, repairs=1)

    def test_network_retry_and_citation_repair_share_three_total_attempts(self):
        client, requests = self.client(http_error(503), (200, completion(encoded(self.draft("fake")))),
                                       (200, completion(encoded(self.draft()))))
        result = self.run_rag(client)
        self.assertEqual(result["status"], "answered")
        stats = self.assert_chat_counts(result, requests, 3, repairs=1, retries=1)
        self.assertIsNone(stats["total_tokens"])
        self.assertEqual(stats["known_total_tokens"], 50)

    def test_retry_is_not_reset_when_citation_repair_hits_transient_failure(self):
        client, requests = self.client(http_error(503), (200, completion(encoded(self.draft("fake")))),
                                       http_error(503, message=OFFLINE_SECRET))
        result = self.run_rag(client)
        self.assert_no_answer(result, "tool_error")
        self.assertEqual(len(result["citation_repairs"]), 1)
        self.assert_chat_counts(result, requests, 3, repairs=1, retries=1)

    def test_citation_repair_invalid_json_or_truncation_is_terminal_invalid_output(self):
        for content, finish in [("bad", "stop"), (encoded(self.draft()), "length")]:
            with self.subTest(finish=finish):
                client, requests = self.client((200, completion(encoded(self.draft("fake")))),
                                               (200, completion(content, finish_reason=finish)))
                result = self.run_rag(client)
                self.assert_no_answer(result, "invalid_output")
                self.assert_chat_counts(result, requests, 2, repairs=1)

    def test_repair_can_choose_knowledge_answer_without_publishing_old_bad_refs(self):
        useful = {"status": "answered", "claims": [{"claim": "用通用知识解释本问题。",
                  "basis": "model_knowledge", "citation_ids": []}]}
        client, requests = self.client((200, completion(encoded(self.draft("fake")))),
                                       (200, completion(encoded(useful))))
        result = self.run_rag(client)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"]["evidence_refs"], [])
        self.assert_chat_counts(result, requests, 2, repairs=1)

    def test_missing_source_is_tool_error_without_model_repair(self):
        for store in [FakeStore({}), FakeStore({self.row["chunk_id"]: {**self.row, "pdf_sha256": "0" * 64}})]:
            with self.subTest(empty=not store.chunks):
                client, requests = self.client((200, completion(encoded(self.draft()))))
                result = self.run_rag(client, store=store)
                self.assert_no_answer(result, "tool_error")
                self.assertEqual(result["citation_repairs"], [])
                self.assert_chat_counts(result, requests, 1)

    def test_request_limit_reached_prevents_citation_repair(self):
        client, requests = self.client((200, completion(encoded(self.draft("fake")))),
                                       policy=ChatPolicy(max_attempts=1))
        result = self.run_rag(client)
        self.assert_no_answer(result, "budget_exceeded")
        self.assert_chat_counts(result, requests, 1)

    def test_deadline_crossed_during_source_validation_clears_answer(self):
        client, requests = self.client((200, completion(encoded(self.draft()))))
        self.store.on_read = lambda: self.clock.advance(121)
        result = self.run_rag(client)
        self.assert_no_answer(result, "budget_exceeded")
        self.assertEqual(result["citation_checks"][0]["status"], "valid")
        self.assert_chat_counts(result, requests, 1)

    def test_deadline_crossed_during_citation_repair_parse_preempts_success_or_parse_error(self):
        for parse_succeeds in [True, False]:
            with self.subTest(parse_succeeds=parse_succeeds):
                # 独立预算与时钟，避免上一子项超时污染下一项。
                self.clock = FakeClock()
                client, requests = self.client((200, completion(encoded(self.draft("fake")))),
                                               (200, completion(encoded(self.draft()))))

                def delayed_parse(content):
                    self.clock.advance(121)
                    if not parse_succeeds:
                        raise DraftParseError("invalid_draft_schema")
                    return parse_answer_draft(content)

                with patch("paper_assistant.rag.parse_answer_draft", side_effect=delayed_parse):
                    result = self.run_rag(client)
                self.assert_no_answer(result, "budget_exceeded")
                self.assertEqual(result["failure_stage"], "citation_repair")
                self.assertEqual(len(result["citation_checks"]), 1)
                self.assertEqual(len(result["citation_repairs"]), 1)
                self.assert_chat_counts(result, requests, 2, repairs=1)

    def test_model_auth_error_and_timeout_remain_program_failure(self):
        def timeout(request):
            raise httpx.ReadTimeout(OFFLINE_SECRET, request=request)
        for outcomes in [(http_error(401, message=OFFLINE_SECRET),), (timeout, timeout)]:
            with self.subTest(outcomes=len(outcomes)):
                client, requests = self.client(*outcomes)
                result = self.run_rag(client)
                self.assert_no_answer(result, "tool_error")
                self.assertEqual(self.store.calls, [])
                self.assert_chat_counts(result, requests, len(outcomes), retries=len(outcomes) - 1)

    def test_generation_structure_repair_failure_is_not_repaired_by_d_again(self):
        client, requests = self.client((200, completion("bad")), (200, completion("still bad")))
        result = self.run_rag(client)
        self.assert_no_answer(result, "invalid_output")
        self.assertEqual(result["citation_checks"], [])
        self.assertEqual(result["citation_repairs"], [])
        self.assert_chat_counts(result, requests, 2, repairs=1)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
