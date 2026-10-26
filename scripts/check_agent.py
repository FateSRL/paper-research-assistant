"""D8 C: offline orchestration checks with real local citation validation.

Uses temporary PDFs, synthetic chunks, sequenced fake retrieval and the actual
RecordedLLM/OpenAI SDK through httpx.MockTransport. No .env or production data
is loaded. These checks cover C's execution contract, not the full task D suite.
Every run preserves a separate history report, including failed runs.
"""

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

from paper_assistant.agent import answer_question_agent
from paper_assistant.agent_actions import parse_agent_action
from paper_assistant.config import LLMSettings
from paper_assistant.conversation import prepare_conversation
from paper_assistant.llm_client import ChatPolicy, RecordedLLM
from paper_assistant.search import SearchError
from scripts.check_llm import completion, http_error
from scripts.check_rag import FakeStore, Fixture


ROOT = Path(__file__).resolve().parents[1]
QUESTION = "  What does the evidence say?\n  "
RETRY_QUERY = "  missing factual evidence\n  "
SECRET = "offline-agent-credential-do-not-log"
MOCK_HTTP_SENDS = 0


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def response(value):
    return 200, completion(value if isinstance(value, str) else encoded(value))


def tool_response(*actions):
    body = completion(None, finish_reason="tool_calls")
    body["choices"][0]["message"]["tool_calls"] = [
        {"id": f"call-{index}", "type": "function", "function": {"name": "search",
         "arguments": action if isinstance(action, str) else encoded({k: v for k, v in action.items() if k != "action"})}}
        for index, action in enumerate(actions)]
    return 200, body


def answer_action(*ids):
    return {"action": "answer", "answer": {"status": "answered", "claims": [
        {"claim": "The shown evidence combines reasoning and action.",
         "citation_ids": list(ids) or ["p1_r1_p2_c1"]}]}}


def retry_action(query=RETRY_QUERY):
    return {"action": "retry_search", "missing_information": "The second requested fact.", "retry_query": query}


def insufficient_action():
    return {"action": "insufficient_evidence", "reason": "This run lacks the second requested fact."}


def knowledge_action():
    return {"action": "answer", "answer": {"status": "answered", "claims": [
        {"claim": "检索增强生成通过检索相关文档，为语言模型的生成提供上下文。",
         "basis": "model_knowledge", "citation_ids": []}]}}


class SequencedSearcher:
    """One observable retrieval attempt per outcome; never calls embedding APIs."""

    def __init__(self, *outcomes, on_search=None):
        self.outcomes, self.calls, self.closed = list(outcomes), [], False
        self.on_search = on_search

    def search_evidence(self, query, selected_versions, top_k=5):
        self.calls.append((query, deepcopy(selected_versions), top_k))
        if self.on_search:
            self.on_search(len(self.calls))
        if not self.outcomes:
            raise AssertionError("Retrieval exceeded the offline fixture's outcomes")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome(query, selected_versions, top_k)
        rows = deepcopy(outcome)
        return {"status": "success" if rows else "no_hits", "query": query,
                "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in selected_versions],
                "results": rows, "returned_count": len(rows), "top_k": top_k,
                "index_profile_id": "offline-profile", "statistics": {
                    "embedding_requests": 1, "failed_requests": 0, "total_tokens": 7}}

    def close(self):
        self.closed = True


class AgentFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.settings = LLMSettings(provider="deepseek", model_id="offline-model", api_key=SECRET,
                                    base_url="https://example.invalid/v1", timeout=30.0)

    def client(self, *outcomes, policy=None, budget=None):
        requests, remaining = [], list(outcomes)

        def handle(request):
            global MOCK_HTTP_SENDS
            MOCK_HTTP_SENDS += 1
            requests.append(request)
            if not remaining:
                raise AssertionError("SDK request exceeded the offline fixture's outcomes")
            outcome = remaining.pop(0)
            if callable(outcome):
                return outcome(request)
            status, body = outcome
            return httpx.Response(status, json=body, request=request)

        client = RecordedLLM(self.settings, policy=policy, budget=budget,
                             transport=httpx.MockTransport(handle), clock=self.clock)
        self.addCleanup(client.close)
        return client, requests

    def add_chunk(self, identifier="p1_r1_p1_new", *, text="New supporting evidence.", page=1, rank=1):
        row = self.chunk(identifier, text=text, page=page, rank=rank)
        self.store.chunks[identifier] = deepcopy(row)
        return row

    def run_agent(self, client, *, searcher=None, store=None, query=QUESTION, versions=None, **options):
        self.searcher = searcher or SequencedSearcher([self.row])
        return answer_question_agent(query, [("p1", "r1")] if versions is None else versions,
                                     self.searcher, store or self.store, client, project_root=self.root, **options)

    def counts(self, result, requests, *, chats, searches, repairs=0, retries=0):
        self.assertEqual(len(requests), chats)
        stats = result["statistics"]["chat"]
        self.assertEqual(stats["sdk_request_attempts"], chats)
        self.assertEqual(stats["http_request_attempts"], chats)
        self.assertEqual(stats["repairs"], repairs)
        self.assertEqual(stats["network_retries"], retries)
        self.assertEqual(len(self.searcher.calls), searches)
        self.assertEqual(result["statistics"]["embedding"]["embedding_requests"], searches)

    def failed(self, result, status):
        self.assertEqual(result["status"], status)
        self.assertIsNone(result["answer"])
        self.assertTrue(result["error"]["code"])
        self.assertNotIn(SECRET, encoded(result))

    def request_data(self, request):
        return json.loads(request.content)["messages"]


class AgentFlowChecks(AgentFixture):
    def test_direct_answer_is_one_search_and_one_decision_then_real_pdf_validation(self):
        heading = self.add_chunk("p1_r1_p1_c1", text="1\nIntroduction", page=1)
        heading.update(segment_id="heading", source_block_index=0)
        body = self.add_chunk("p1_r1_p1_c2", page=1,
                              text="The method retrieves external passages and combines their information "
                                   "with a generator to answer knowledge-intensive questions.")
        body.update(segment_id="body", source_block_index=1)
        self.store.chunks[heading["chunk_id"]] = deepcopy(heading)
        self.store.chunks[body["chunk_id"]] = deepcopy(body)
        client, requests = self.client(response(answer_action(body["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher([heading]))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"]["evidence_refs"][0]["pdf_page"], 1)
        self.assertEqual(result["answer"]["evidence_sources"][0]["text"], body["text"])
        self.assertEqual(result["search"]["results"][0]["chunk_id"], heading["chunk_id"])
        self.assertEqual(result["context"]["reading_origins"][0]["chunk_id"], body["chunk_id"])
        self.assertEqual(result["context"]["reading_origins"][0]["anchor_chunk_id"], heading["chunk_id"])
        self.assertEqual(result["answer"]["semantic_support_status"], "not_reviewed")
        self.counts(result, requests, chats=1, searches=1)
        self.assertEqual(len(result["citation_checks"]), 1)

    def test_first_decision_may_answer_with_model_knowledge_without_reading_pdf(self):
        client, requests = self.client(response(knowledge_action()))
        result = self.run_agent(client)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"]["claims"], knowledge_action()["answer"]["claims"])
        self.assertEqual(result["answer"]["evidence_sources"], [])
        self.assertEqual(self.store.calls, [])
        self.counts(result, requests, chats=1, searches=1)

    def test_empty_first_context_can_retry_then_answer_from_new_evidence(self):
        new = self.add_chunk()
        client, requests = self.client(response(retry_action()), response(answer_action(new["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher([], [new]))
        self.assertEqual(result["status"], "answered")
        self.counts(result, requests, chats=2, searches=2)
        first = json.loads(self.request_data(requests[0])[1]["content"])
        self.assertEqual(first["shown_evidence"], [])
        self.assertIn("answer", first["allowed_actions"])

    def test_empty_context_citation_is_repaired_to_a_useful_knowledge_answer(self):
        client, requests = self.client(response(answer_action()), response(knowledge_action()))
        result = self.run_agent(client, searcher=SequencedSearcher([]))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"]["claims"], knowledge_action()["answer"]["claims"])
        self.assertEqual(result["answer"]["evidence_refs"], [])
        self.assertEqual(self.store.calls, [])
        self.counts(result, requests, chats=2, searches=1, repairs=1)

    def test_retry_keeps_raw_query_original_question_scope_and_fixed_top_five(self):
        author = self.add_chunk("p1_r1_p1_c1", text="Patrick Lewis, Ethan Perez", page=1)
        new = self.add_chunk()
        client, requests = self.client(response(retry_action()), response(answer_action(new["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher([author], [new]))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(self.searcher.calls, [(QUESTION, [("p1", "r1")], 5),
                                             (RETRY_QUERY, [("p1", "r1")], 5)])
        self.assertEqual(result["query"], QUESTION)
        self.assertEqual(result["context"]["question"], QUESTION)
        self.assertIn(author["chunk_id"], result["initial_context"]["allowed_citation_ids"])
        self.assertIn(author["chunk_id"], result["context"]["allowed_citation_ids"])
        for request in requests:
            payload = json.loads(self.request_data(request)[1]["content"])
            self.assertEqual(payload["question"], QUESTION)
            self.assertEqual(payload["selected_papers"][0]["title"], "Offline test paper")
            self.assertEqual(payload["selected_papers"][0]["abstract_passages"], [])

    def test_retry_can_answer_remaining_question_with_model_knowledge(self):
        new = self.add_chunk()
        client, requests = self.client(response(retry_action()), response(knowledge_action()))
        result = self.run_agent(client, searcher=SequencedSearcher([self.row], [new]))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"]["claims"], knowledge_action()["answer"]["claims"])
        self.counts(result, requests, chats=2, searches=2)

    def test_same_query_stops_second_retrieval_but_still_produces_a_useful_answer(self):
        client, requests = self.client(response(retry_action("WHAT DOES THE EVIDENCE SAY?")),
                                       response(knowledge_action()))
        result = self.run_agent(client)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["stop_reason"], "retry_query_unchanged")
        self.counts(result, requests, chats=2, searches=1)

    def test_duplicate_retry_results_still_produce_useful_final_answer(self):
        useful = {"action": "answer", "answer": {"status": "answered", "claims": [
            {"claim": "这里可以先分析问题所需的概念与信息，再据此定位相关论文内容。",
             "basis": "analysis", "citation_ids": []}]}}
        for rows, retry_query, stop_reason, searches in (
                ([self.row], RETRY_QUERY, "no_new_shown_evidence", 2),
                ([], RETRY_QUERY, "no_new_shown_evidence", 2),
                ([self.row], "WHAT DOES THE EVIDENCE SAY?", "retry_query_unchanged", 1)):
            with self.subTest(stop_reason=stop_reason, rows=len(rows)):
                client, requests = self.client(response(retry_action(retry_query)), response(useful))
                result = self.run_agent(client, searcher=SequencedSearcher(rows, rows))
                self.assertEqual(result["status"], "answered")
                self.assertEqual(result["stop_reason"], stop_reason)
                self.assertEqual(result["answer"]["claims"], useful["answer"]["claims"])
                self.assertEqual(result["answer"]["evidence_status"], "none")
                self.assertTrue(result["answer"]["reason"])
                self.assertEqual(result["answer"]["evidence_sources"], [])
                self.counts(result, requests, chats=2, searches=searches)
                payload = json.loads(self.request_data(requests[-1])[1]["content"])
                self.assertEqual(payload["allowed_actions"], ["answer"])
                self.assertEqual(payload["question"], QUESTION)
                self.assertIn("evidence_limitation", payload)

    def test_new_returned_chunk_too_large_to_show_still_produces_a_useful_final_answer(self):
        initial = self.add_chunk("short-initial", text="old")
        oversized = self.add_chunk("new-too-large", text="x" * 11)
        client, requests = self.client(response(retry_action()), response(knowledge_action()))
        result = self.run_agent(client, searcher=SequencedSearcher([initial], [oversized]), max_chars=10)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["stop_reason"], "no_new_shown_evidence")
        self.counts(result, requests, chats=2, searches=2)

    def test_previously_returned_but_omitted_evidence_can_be_newly_shown(self):
        initial = self.add_chunk("initial-five", text="first", rank=1)
        omitted = self.add_chunk("initial-omitted", text="new", rank=2)
        replayed = {**omitted, "rank": 1}
        client, requests = self.client(response(retry_action()), response(answer_action(omitted["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher([initial, omitted], [replayed]), max_chars=5)
        self.assertEqual(result["status"], "answered")
        self.assertIn(omitted["chunk_id"], result["context"]["allowed_citation_ids"])
        self.counts(result, requests, chats=2, searches=2)

    def test_second_retry_action_is_repaired_to_terminal_without_third_search(self):
        new = self.add_chunk()
        client, requests = self.client(response(retry_action()), response(retry_action("forbidden third query")),
                                       response(answer_action(new["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher([self.row], [new]))
        self.assertEqual(result["status"], "answered")
        self.counts(result, requests, chats=3, searches=2, repairs=1)
        repaired = json.loads(self.request_data(requests[-1])[1]["content"])
        self.assertNotIn("retry_search", repaired["allowed_actions"])

    def test_second_retry_with_disabled_repair_is_invalid_not_a_third_search(self):
        new = self.add_chunk()
        client, requests = self.client(response(retry_action()), response(retry_action("third query")), policy=ChatPolicy(max_repairs=0))
        result = self.run_agent(client, searcher=SequencedSearcher([self.row], [new]))
        self.failed(result, "invalid_output")
        self.counts(result, requests, chats=2, searches=2)

    def test_repaired_second_retry_still_requesting_tool_is_rejected(self):
        new = self.add_chunk()
        client, requests = self.client(response(retry_action()), response(retry_action("third query")), response(retry_action("fourth query")))
        result = self.run_agent(client, searcher=SequencedSearcher([self.row], [new]))
        self.failed(result, "invalid_output")
        self.counts(result, requests, chats=3, searches=2, repairs=1)

    def test_format_error_can_be_repaired_once_to_direct_answer(self):
        client, requests = self.client(response("malformed JSON"), response(answer_action()))
        result = self.run_agent(client)
        self.assertEqual(result["status"], "answered")
        self.counts(result, requests, chats=2, searches=1, repairs=1)

        from paper_assistant.agent_prompt import build_action_repair_messages

        interactive = ChatPolicy(max_attempts=None)
        versions = [{"paper_id": "p1", "parse_revision": "r1"}]
        actual_query = "Find the paper's mechanism evidence"
        search = {"action": "search", "query": actual_query, "selected_versions": versions,
                  "missing_information": "The paper fact needs a current supporting passage."}
        unsupported = {"action": "answer", "answer": {"status": "answered", "claims": [
            {"claim": "The paper reports this mechanism.", "basis": "paper_evidence", "citation_ids": []}]}}
        issue = {"path": "answer.claims[0].citation_ids", "type": "paper_evidence_without_citations",
                 "message": "paper_evidence requires nonempty citation_ids from allowed_citation_ids; do not invent IDs or relabel unsupported paper facts."}

        def payload(request, index=1):
            return json.loads(self.request_data(request)[index]["content"])

        client, requests = self.client(response(unsupported), response(search), response(answer_action()),
                                       policy=interactive)
        result = self.run_agent(client, autonomous_steps=5, searcher=SequencedSearcher([self.row]))
        self.assertEqual(result["status"], "answered")
        self.counts(result, requests, chats=3, searches=1, repairs=1)
        self.assertEqual(self.searcher.calls, [(actual_query, [("p1", "r1")], 5)])
        self.assertEqual(result["autonomous_steps_used"], 2)
        self.assertEqual([step["autonomous_step"] for step in result["action_steps"]], [1, 1, 2])
        self.assertEqual(result["action_steps"][0]["parse_error_code"], "invalid_action_schema")
        self.assertEqual(result["action_steps"][0]["parse_error_fields"], [issue])
        self.assertEqual(result["action_steps"][1]["repair_kind"], "format")
        self.assertEqual(result["action_steps"][1]["parsed_action"]["action"], "search")
        first, repair_context, feedback, final = payload(requests[0]), payload(requests[1]), payload(requests[1], -1), payload(requests[2])
        for current in (first, repair_context, final):
            self.assertEqual(current["question"], QUESTION)
            self.assertEqual(current["selected_versions"], versions)
            self.assertEqual(current["phase"], "autonomous_decision")
        self.assertEqual(first["shown_evidence"], [])
        self.assertEqual(first["allowed_citation_ids"], [])
        self.assertEqual(repair_context["shown_evidence"], [])
        self.assertEqual(repair_context["allowed_citation_ids"], [])
        self.assertEqual(repair_context["remaining_steps"], first["remaining_steps"])
        self.assertEqual(feedback["field_issues"], [issue])
        self.assertEqual(set(feedback["allowed_actions"]), {"search", "answer"})
        self.assertFalse(feedback["terminal_only"])
        self.assertEqual(final["allowed_citation_ids"], [self.row["chunk_id"]])
        self.assertEqual(result["context"]["allowed_citation_ids"], [self.row["chunk_id"]])
        self.assertEqual(result["answer"]["claims"][0]["citation_ids"], [self.row["chunk_id"]])
        terminal = build_action_repair_messages(QUESTION, result["context"], encoded(unsupported),
            phase="limit_final_decision", error_code="invalid_action_schema", field_issues=[issue],
            loop_state={"autonomous_step": 5, "remaining_steps": 0, "limit_finalize": True})
        terminal_feedback = json.loads(terminal[-1]["content"])
        self.assertEqual(terminal_feedback["allowed_actions"], ["answer"])
        self.assertTrue(terminal_feedback["terminal_only"])
        with self.assertRaises(ValueError) as rejected:
            parse_agent_action(encoded(search), phase="limit_final_decision", has_shown_evidence=True,
                               terminal_only=True, selected_versions=versions)
        self.assertEqual(rejected.exception.code, "action_not_allowed")

        misplaced = answer_action()
        misplaced["reason"] = "This note belongs inside the answer."
        repaired = answer_action()
        repaired["answer"]["reason"] = misplaced["reason"]
        client, requests = self.client(response(search), response(misplaced), response(repaired), policy=interactive)
        result = self.run_agent(client, autonomous_steps=5, searcher=SequencedSearcher([self.row]))
        self.assertEqual(result["status"], "answered")
        self.counts(result, requests, chats=3, searches=1, repairs=1)
        self.assertEqual(result["autonomous_steps_used"], 2)
        self.assertEqual([step["autonomous_step"] for step in result["action_steps"]], [1, 2, 2])
        self.assertEqual(result["action_steps"][1]["parse_error_fields"], [{"path": "reason",
            "type": "extra_forbidden", "message": "reason belongs inside answer.reason, not at the action top level."}])
        repair_context, feedback = payload(requests[-1]), payload(requests[-1], -1)
        self.assertEqual(feedback["field_issues"], result["action_steps"][1]["parse_error_fields"])
        self.assertEqual(repair_context["question"], QUESTION)
        self.assertEqual(repair_context["selected_versions"], versions)
        self.assertEqual(repair_context["allowed_citation_ids"], [self.row["chunk_id"]])
        self.assertEqual(repair_context["phase"], "autonomous_decision")
        self.assertEqual(result["answer"]["reason"], misplaced["reason"])

        scope_question = "What is the project's release date?"
        scope_answer = {"action": "answer", "answer": {"status": "answered", "claims": [
            {"claim": "The selected papers cannot establish this project's release date; consult the project's release announcement.",
             "basis": "analysis", "citation_ids": []}]}}
        client, requests = self.client(response(scope_answer), policy=interactive)
        result = self.run_agent(client, query=scope_question, autonomous_steps=5, searcher=SequencedSearcher())
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["autonomous_steps_used"], 1)
        self.assertEqual(result["search_rounds"], [])
        self.assertEqual(result["answer"]["claims"][0]["basis"], "analysis")
        self.assertEqual(payload(requests[0])["question"], scope_question)
        self.assertEqual(payload(requests[0])["allowed_citation_ids"], [])
        self.counts(result, requests, chats=1, searches=0)

    def test_citation_repair_can_fix_id_using_only_current_context(self):
        client, requests = self.client(response(answer_action("fabricated-id")), response(answer_action()))
        result = self.run_agent(client)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(len(result["citation_checks"]), 2)
        self.counts(result, requests, chats=2, searches=1, repairs=1)
        repaired = json.loads(self.request_data(requests[-1])[1]["content"])
        self.assertNotIn("retry_search", repaired["allowed_actions"])
        self.assertEqual(repaired["allowed_citation_ids"], [self.row["chunk_id"]])

    def test_citation_repair_cannot_request_a_tool(self):
        client, requests = self.client(response(answer_action("fabricated-id")), response(retry_action()))
        result = self.run_agent(client)
        self.failed(result, "invalid_output")
        self.counts(result, requests, chats=2, searches=1, repairs=1)

    def test_citation_repair_may_return_useful_knowledge_without_bad_references(self):
        client, requests = self.client(response(answer_action("fabricated-id")), response(knowledge_action()))
        result = self.run_agent(client)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["answer"]["evidence_refs"], [])
        self.counts(result, requests, chats=2, searches=1, repairs=1)

    def test_format_and_citation_errors_share_one_repair_allowance(self):
        client, requests = self.client(response("not JSON"), response(answer_action("fabricated-id")))
        result = self.run_agent(client)
        self.failed(result, "invalid_output")
        self.counts(result, requests, chats=2, searches=1, repairs=1)

    def test_format_repair_then_retry_then_bad_citation_does_not_send_fourth_chat(self):
        new = self.add_chunk()
        client, requests = self.client(response("not JSON"), response(retry_action()), response(answer_action("fabricated-id")))
        result = self.run_agent(client, searcher=SequencedSearcher([self.row], [new]))
        self.failed(result, "invalid_output")
        self.counts(result, requests, chats=3, searches=2, repairs=1)

        old = self.add_chunk("previous-answer-source", text="Only the earlier answer used this source.")
        history = [{"turn": 1, "user_question": "Explain the previous method.", "claims": [
            {"claim": "The previous method has a stopping condition.",
             "basis": "paper_evidence", "citation_ids": [old["chunk_id"]]}]}]
        user_question = "解释刚才第一条，说明它的停止条件。"
        prepared_output = {"standalone_question": QUESTION, "clarification_question": None,
                           "referenced_evidence_ids": []}
        client, requests = self.client(response(prepared_output), response(retry_action()),
                                       response(answer_action(old["chunk_id"])))
        conversation = prepare_conversation(user_question, history, client,
            conversation_id="offline-conversation", selected_versions=[("p1", "r1")])
        self.assertEqual(client.budget.attempts, 1)
        self.assertEqual(conversation["planned_queries"], [{"query": QUESTION.strip(),
            "selected_versions": [{"paper_id": "p1", "parse_revision": "r1"}]}])
        result = self.run_agent(client, query=conversation["standalone_question"],
            searcher=SequencedSearcher([self.row], [new]), conversation_context=conversation)
        self.failed(result, "budget_exceeded")
        self.assertEqual(result["error"]["code"], "request_limit")
        self.counts(result, requests, chats=3, searches=2)
        self.assertNotIn(old["chunk_id"], result["context"]["allowed_citation_ids"])
        self.assertEqual(result["citation_checks"][-1]["status"], "invalid_output")
        for request in requests[1:]:
            payload = json.loads(self.request_data(request)[1]["content"])
            self.assertEqual(payload["question"], conversation["standalone_question"])
            self.assertEqual(payload["conversation_context"]["user_question"], user_question)
            self.assertEqual(payload["conversation_context"]["history"], history)
            self.assertNotIn(old["chunk_id"], payload["allowed_citation_ids"])

        # A specifically selected old reference is read again from the actual
        # selected version and only then becomes current answer evidence.
        prepared_output["referenced_evidence_ids"] = [old["chunk_id"]]
        client, requests = self.client(response(prepared_output), response(answer_action(old["chunk_id"])))
        conversation = prepare_conversation(user_question, history, client,
            conversation_id="offline-conversation", selected_versions=[("p1", "r1")])
        result = self.run_agent(client, query=conversation["standalone_question"],
            searcher=SequencedSearcher([self.row]), conversation_context=conversation)
        self.assertEqual(result["status"], "answered")
        self.counts(result, requests, chats=2, searches=1)
        self.assertIn(old["chunk_id"], result["context"]["allowed_citation_ids"])
        self.assertEqual(result["answer"]["evidence_sources"][0]["text"], old["text"])
        self.assertLessEqual(len(result["context"]["shown_evidence"]), 5)
        self.assertLessEqual(result["context"]["shown_chars"], 8000)

    def test_network_retry_first_decision_and_final_decision_share_three_attempts(self):
        new = self.add_chunk()
        client, requests = self.client(http_error(503), response(retry_action()), response(answer_action(new["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher([self.row], [new]))
        self.assertEqual(result["status"], "answered")
        self.counts(result, requests, chats=3, searches=2, retries=1)

    def test_no_final_request_allowance_stops_before_retry_embedding(self):
        client, requests = self.client(http_error(503), response("not JSON"), response(retry_action()))
        result = self.run_agent(client)
        self.failed(result, "budget_exceeded")
        self.counts(result, requests, chats=3, searches=1, repairs=1, retries=1)

    def test_smaller_shared_attempt_limit_also_stops_before_retry_embedding(self):
        client, requests = self.client(response("not JSON"), response(retry_action()), policy=ChatPolicy(max_attempts=2))
        result = self.run_agent(client)
        self.failed(result, "budget_exceeded")
        self.counts(result, requests, chats=2, searches=1, repairs=1)

    def test_nonretryable_chat_auth_fault_is_safe_and_preserves_attempts(self):
        client, requests = self.client(http_error(401, message=SECRET))
        result = self.run_agent(client)
        self.failed(result, "tool_error")
        self.counts(result, requests, chats=1, searches=1)

    def test_failed_retry_retrieval_preserves_first_and_failed_embedding_usage(self):
        error = SearchError(SECRET, stage="embedding", statistics={"embedding_requests": 1, "failed_requests": 1, "total_tokens": None})
        client, requests = self.client(response(retry_action()))
        result = self.run_agent(client, searcher=SequencedSearcher([self.row], error))
        self.failed(result, "tool_error")
        self.counts(result, requests, chats=1, searches=2)
        self.assertEqual(result["statistics"]["embedding"]["failed_requests"], 1)
        self.assertIsNone(result["statistics"]["embedding"]["total_tokens"])
        self.assertEqual(len(result["search_rounds"]), 2)

    def test_failed_initial_retrieval_is_safe_and_retains_failed_attempt(self):
        error = SearchError(SECRET, stage="embedding", statistics={"embedding_requests": 1, "failed_requests": 1, "total_tokens": None})
        client, requests = self.client()
        result = self.run_agent(client, searcher=SequencedSearcher(error))
        self.failed(result, "tool_error")
        self.counts(result, requests, chats=0, searches=1)
        self.assertEqual(result["statistics"]["embedding"]["failed_requests"], 1)
        self.assertIsNone(result["statistics"]["embedding"]["total_tokens"])

    def test_same_id_conflict_between_rounds_fails_before_final_decision(self):
        changed = self.chunk(self.row["chunk_id"], text="Conflicting same-ID source.")
        client, requests = self.client(response(retry_action()))
        result = self.run_agent(client, searcher=SequencedSearcher([self.row], [changed]))
        self.failed(result, "tool_error")
        self.assertEqual(result["error"]["code"], "conflicting_duplicate")
        self.counts(result, requests, chats=1, searches=2)

    def test_actual_messages_context_and_sdk_attempt_trace_are_recorded(self):
        new = self.add_chunk()
        client, requests = self.client(http_error(503), response(retry_action()), response(answer_action(new["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher([self.row], [new]))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(len(result["action_steps"]), 2)
        for index, (step, context) in enumerate(zip(result["action_steps"], (result["initial_context"], result["context"]))):
            with self.subTest(step=index):
                self.assertEqual(step["allowed_citation_ids"], context["allowed_citation_ids"])
                self.assertEqual(step["messages"], self.request_data(requests[1 if index == 0 else 2]))
        self.assertEqual(result["action_steps"][0]["sdk_attempt_numbers"], [1, 2])
        self.assertEqual(result["action_steps"][1]["sdk_attempt_numbers"], [3])

    def test_ten_unique_candidates_produce_eight_retry_first_whole_chunks(self):
        initial = [self.add_chunk("initial-" + str(index), text="old " + str(index), rank=index + 1) for index in range(5)]
        retry_rows = [self.add_chunk("retry-" + str(index), text="new " + str(index), rank=index + 1) for index in range(5)]
        client, requests = self.client(response(retry_action()), response(answer_action(retry_rows[0]["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher(initial, retry_rows))
        self.assertEqual(result["status"], "answered")
        expected = [item["chunk_id"] for item in retry_rows + initial[:3]]
        self.assertEqual(result["context"]["allowed_citation_ids"], expected)
        self.assertEqual([item["rank"] for item in result["context"]["shown_evidence"]], list(range(1, 9)))
        self.assertEqual(len(result["merge_trace"]["count_omitted"]), 2)
        self.assertEqual(len(result["merge_trace"]["merged_candidates"]), 10)
        self.assertEqual(result["merge_trace"]["rounds"][0]["search"]["results"], initial)
        self.assertEqual(result["merge_trace"]["rounds"][1]["search"]["results"], retry_rows)
        self.counts(result, requests, chats=2, searches=2)

        versions = [{"paper_id": "p1", "parse_revision": "r1"}]
        queries = ["Study the paper's core mechanism", "Study the paper's evaluation"]
        conversation = {"user_question": QUESTION, "standalone_question": QUESTION,
                        "clarification_question": None, "history": [], "referenced_evidence_ids": [],
                        "planned_queries": [{"query": query, "selected_versions": versions} for query in queries]}
        client, requests = self.client(response(answer_action(initial[0]["chunk_id"], retry_rows[0]["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher(initial, retry_rows),
                                conversation_context=conversation)
        self.assertEqual(result["status"], "answered")
        expected_rows = [row for pair in zip(initial, retry_rows) for row in pair][:8]
        self.assertEqual(result["context"]["allowed_citation_ids"], [row["chunk_id"] for row in expected_rows])
        self.assertEqual([row["shown_text"] for row in result["context"]["shown_evidence"]],
                         [row["text"] for row in expected_rows])
        self.assertEqual([row["shown_char_end"] for row in result["context"]["shown_evidence"]],
                         [len(row["text"]) for row in expected_rows])
        self.assertEqual(len(result["merge_trace"]["count_omitted"]), 2)
        self.assertEqual(result["context"]["question"], QUESTION)
        self.assertEqual(self.searcher.calls, [(query, [("p1", "r1")], 5) for query in queries])
        self.assertEqual([row["query"] for row in result["search_rounds"]], queries)
        self.assertEqual([row["kind"] for row in result["search_rounds"]], ["planned", "planned"])
        self.assertIsNone(result["retry_decision"])
        self.assertEqual([step["phase"] for step in result["action_steps"]], ["final_decision"])
        payload = json.loads(self.request_data(requests[0])[1]["content"])
        self.assertEqual(payload["question"], QUESTION)
        self.assertEqual(len(payload["shown_evidence"]), 8)
        self.assertEqual(payload["allowed_actions"], ["answer"])
        self.counts(result, requests, chats=1, searches=2)

        shared = {**initial[0], "rank": 1}
        distinct = {**retry_rows[0], "rank": 2}
        client, requests = self.client(response(answer_action(shared["chunk_id"], distinct["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher(initial[:2], [shared, distinct]),
                                conversation_context=conversation)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["context"]["allowed_citation_ids"],
                         [initial[0]["chunk_id"], initial[1]["chunk_id"], distinct["chunk_id"]])
        self.assertEqual([row["chunk_id"] for row in result["merge_trace"]["duplicates"]], [shared["chunk_id"]])
        self.counts(result, requests, chats=1, searches=2)

        second_paper = self.chunk("p2_r2_evaluation", paper_id="p2", revision="r2", text="Second paper evaluation.")
        self.store.chunks[second_paper["chunk_id"]] = deepcopy(second_paper)
        comparison = deepcopy(conversation)
        comparison["planned_queries"][1]["selected_versions"] = [{"paper_id": "p2", "parse_revision": "r2"}]
        selected = [("p1", "r1"), ("p2", "r2")]
        client, requests = self.client(response(answer_action(initial[0]["chunk_id"], second_paper["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher(initial[:1], [second_paper]),
                                versions=selected, conversation_context=comparison)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(self.searcher.calls, [(queries[0], selected[:1], 5), (queries[1], selected[1:], 5)])
        self.assertEqual(result["context"]["selected_versions"], [
            {"paper_id": p, "parse_revision": r} for p, r in selected])
        self.assertEqual([row["search"]["selected_versions"] for row in result["merge_trace"]["rounds"]],
                         [plan["selected_versions"] for plan in comparison["planned_queries"]])
        self.assertEqual([row["paper_id"] for row in result["answer"]["evidence_sources"]], ["p1", "p2"])
        self.counts(result, requests, chats=1, searches=2)

        old = self.chunk("explicit-old-reference", text="The previous answer's explicitly selected source.")
        first_heading = self.chunk("mechanism-heading", text="1 Introduction", page=1)
        first_body = self.chunk("mechanism-body", text="The mechanism reads passages and reasons over them. " * 3, page=1)
        second_heading = self.chunk("evaluation-heading", text="2 Methods", page=1)
        second_body = self.chunk("evaluation-body", text="The evaluation measures answer quality in a stated setting. " * 3, page=1)
        for index, row in enumerate((first_heading, first_body, second_heading, second_body)):
            row.update(segment_id=row["chunk_id"], source_block_index=index)
        reading_store = FakeStore({row["chunk_id"]: row for row in
                                   (old, first_heading, first_body, second_heading, second_body)})
        reread = deepcopy(conversation)
        reread["referenced_evidence_ids"] = [old["chunk_id"]]
        client, requests = self.client(response(answer_action(old["chunk_id"], second_body["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher([first_heading], [second_heading]),
                                store=reading_store, conversation_context=reread)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["context"]["allowed_citation_ids"], [row["chunk_id"] for row in
                         (old, first_heading, second_heading, first_body, second_body)])
        self.assertEqual([row["chunk_id"] for row in result["context"]["reading_origins"]],
                         [first_body["chunk_id"], second_body["chunk_id"]])
        self.assertEqual(result["answer"]["evidence_sources"][0]["text"], old["text"])
        self.counts(result, requests, chats=1, searches=2)

        failed_stats = {"embedding_requests": 1, "failed_requests": 1, "total_tokens": None}
        for failure_index in (0, 1):
            with self.subTest(planned_failure=failure_index + 1):
                error = SearchError(SECRET, stage="embedding", statistics=failed_stats)
                outcomes = [initial[:1], initial[:1]]
                outcomes[failure_index] = error
                client, requests = self.client(response(answer_action(initial[0]["chunk_id"])))
                result = self.run_agent(client, searcher=SequencedSearcher(*outcomes),
                                        conversation_context=conversation)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(result["context"]["allowed_citation_ids"], [initial[0]["chunk_id"]])
                self.assertEqual(result["search_rounds"][failure_index]["statistics"], failed_stats)
                self.assertEqual(result["statistics"]["embedding"]["failed_requests"], 1)
                self.assertIsNone(result["statistics"]["embedding"]["total_tokens"])
                self.assertEqual(result["statistics"]["embedding"]["known_total_tokens"], 7)
                self.assertEqual(result["merge_trace"]["rounds"][0]["query_index"], 2 - failure_index)
                self.assertIn(queries[failure_index], result["answer"]["reason"])
                payload = json.loads(self.request_data(requests[0])[1]["content"])
                self.assertIn(queries[failure_index], payload["evidence_limitation"])
                self.assertEqual(payload["phase"], "final_decision")
                self.counts(result, requests, chats=1, searches=2)

        single = deepcopy(conversation)
        single["planned_queries"] = single["planned_queries"][:1]
        client, requests = self.client(response(retry_action()), response(answer_action(second_paper["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher(initial[:2], [second_paper]),
                                versions=selected, conversation_context=single)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(self.searcher.calls, [(queries[0], selected[:1], 5), (RETRY_QUERY, selected, 5)])
        self.assertEqual(result["context"]["question"], QUESTION)
        self.assertEqual(result["merge_trace"]["merge_order"], "retry_rank_then_initial_rank")
        self.assertEqual(result["merge_trace"]["rounds"][0]["search"]["query"], queries[0])
        self.assertEqual(result["context"]["allowed_citation_ids"],
                         [second_paper["chunk_id"], initial[0]["chunk_id"], initial[1]["chunk_id"]])
        self.assertEqual([step["phase"] for step in result["action_steps"]], ["initial_decision", "final_decision"])
        self.counts(result, requests, chats=2, searches=2)

        def search_action(query, pairs):
            return {"action": "search", "query": query,
                    "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in pairs],
                    "missing_information": "Evidence for the original question's remaining part."}

        def payload(request):
            value = next(value for message in reversed(self.request_data(request)) if message["role"] == "user"
                        and "evidence_sections" in (value := json.loads(message["content"])))
            value["shown_evidence"] = [row for group in value["evidence_sections"] for row in group["chunks"]]
            return value

        interactive = ChatPolicy(max_attempts=None)
        client, requests = self.client(response(knowledge_action()), policy=interactive)
        result = self.run_agent(client, searcher=SequencedSearcher(), autonomous_steps=5,
                                conversation_context=conversation)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["retrieval_strategy"], "autonomous")
        self.assertEqual(result["autonomous_step_limit"], 5)
        self.assertEqual(result["autonomous_steps_used"], 1)
        self.assertFalse(result["limit_finalize"])
        self.assertEqual(result["stop_reason"], "answered")
        self.assertEqual(result["search_rounds"], [])
        first = payload(requests[0])
        self.assertEqual(first["question"], QUESTION)
        self.assertEqual(first["planned_queries"], conversation["planned_queries"])
        self.assertEqual(first["shown_evidence"], [])
        self.assertEqual(first["executed_actions"], [])
        self.assertEqual(set(first["allowed_actions"]), {"search", "read_context", "answer"})
        self.assertEqual(first["autonomous_step_limit"], 5)
        self.assertEqual(first["autonomous_step"], 1)
        self.assertEqual(first["remaining_steps"], 4)
        self.counts(result, requests, chats=1, searches=0)

        actual_query = "Study the shared mechanism"
        changed_query = "Find the evaluation setting"
        next_query = "Locate the concrete mechanism result"

        def change_after_observation(request):
            current = payload(request)
            self.assertEqual(current["question"], QUESTION)
            self.assertEqual(current["autonomous_step"], 4)
            self.assertEqual(current["executed_actions"][-1]["tool_calls"][0]["tool_observation"]["new_shown_ids"], [])
            return httpx.Response(200, json=tool_response(search_action(next_query, selected[:1]))[1],
                                  request=request)

        client, requests = self.client(
            tool_response(search_action(actual_query, selected[:1])),
            tool_response(search_action(actual_query, selected[1:])),
            tool_response(search_action(changed_query, selected[1:])),
            change_after_observation,
            response(answer_action(initial[0]["chunk_id"], retry_rows[0]["chunk_id"])),
            policy=interactive)
        result = self.run_agent(client, versions=selected, autonomous_steps=5,
                                searcher=SequencedSearcher(initial, [second_paper], [second_paper], retry_rows),
                                conversation_context=comparison)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(self.searcher.calls, [(actual_query, selected[:1], 5),
                                             (actual_query, selected[1:], 5),
                                             (changed_query, selected[1:], 5),
                                             (next_query, selected[:1], 5)])
        self.assertEqual(result["autonomous_steps_used"], 5)
        self.assertFalse(result["limit_finalize"])
        self.assertEqual(result["stop_reason"], "answered")
        self.assertEqual([step["autonomous_step"] for step in result["action_steps"]], [1, 2, 3, 4, 5])
        self.assertEqual([step["remaining_steps"] for step in result["action_steps"]], [4, 3, 2, 1, 0])
        self.assertEqual([step["phase"] for step in result["action_steps"]], ["autonomous_decision"] * 5)
        self.assertEqual([row["kind"] for row in result["search_rounds"]], ["adaptive"] * 4)
        self.assertEqual(result["search_rounds"][2]["new_returned_ids"], [])
        self.assertEqual(result["search_rounds"][2]["new_shown_ids"], [])
        self.assertTrue(result["search_rounds"][2]["observation"])
        self.assertEqual(len(result["context"]["shown_evidence"]), 8)
        final = payload(requests[-1])
        self.assertEqual(final["question"], QUESTION)
        self.assertEqual(final["allowed_citation_ids"], result["context"]["allowed_citation_ids"])
        self.assertEqual(len(final["executed_actions"]), 4)
        self.assertEqual(final["executed_actions"][1]["tool_calls"][0]["parsed_action"]["selected_versions"],
                         [{"paper_id": "p2", "parse_revision": "r2"}])
        self.counts(result, requests, chats=5, searches=4)

        client, requests = self.client(
            tool_response(search_action(actual_query, selected[:1])),
            tool_response(search_action("  STUDY THE SHARED MECHANISM  ", selected[:1])),
            tool_response(search_action(changed_query, selected[:1])),
            response(knowledge_action()), policy=interactive)
        result = self.run_agent(client, autonomous_steps=5, searcher=SequencedSearcher(initial[:1], []))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(self.searcher.calls, [(actual_query, selected[:1], 5),
                                             (changed_query, selected[:1], 5)])
        self.assertEqual(result["autonomous_steps_used"], 4)
        self.assertEqual(result["stop_reason"], "answered")
        self.assertEqual(result["search_rounds"][-1]["status"], "no_hits")
        self.assertEqual(result["search_rounds"][-1]["new_shown_ids"], [])
        duplicate = payload(requests[2])["executed_actions"][-1]["tool_calls"][0]["tool_observation"]
        self.assertTrue(duplicate)
        self.assertEqual(duplicate["new_shown_ids"], [])
        self.assertEqual(result["context"]["allowed_citation_ids"], [initial[0]["chunk_id"]])
        self.counts(result, requests, chats=4, searches=2)

        long_rows = [self.add_chunk("autonomous-long-" + str(index), text=str(index) * 1001,
                                    rank=index % 5 + 1) for index in range(10)]
        capped_queries = ["Evidence direction " + str(index) for index in range(5)]
        client, requests = self.client(
            *(tool_response(search_action(query, selected[:1])) for query in capped_queries),
            response(answer_action(long_rows[4]["chunk_id"])),
            response(answer_action(long_rows[0]["chunk_id"])), policy=interactive)
        result = self.run_agent(client, autonomous_steps=5,
                                searcher=SequencedSearcher(long_rows[:5], long_rows[5:], [], [], []))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["autonomous_steps_used"], 5)
        self.assertTrue(result["limit_finalize"])
        self.assertEqual(result["stop_reason"], "step_limit_answered")
        self.assertEqual([step["autonomous_step"] for step in result["action_steps"]],
                         [1, 2, 3, 4, 5, 5, 5])
        self.assertEqual([step["phase"] for step in result["action_steps"]],
                         ["autonomous_decision"] * 5 + ["limit_final_decision"] * 2)
        self.assertTrue(result["action_steps"][-2]["limit_finalize"])
        self.assertTrue(result["action_steps"][-1]["limit_finalize"])
        self.assertEqual(result["action_steps"][-1]["repair_kind"], "citation")
        final_context = result["context"]
        self.assertEqual(len(final_context["shown_evidence"]), 7)
        self.assertEqual(sum(len(row["shown_text"]) for row in final_context["shown_evidence"]), 7007)
        for row in final_context["shown_evidence"]:
            self.assertEqual(row["shown_text"], self.store.chunks[row["chunk_id"]]["text"])
            self.assertEqual(row["shown_char_end"], len(row["shown_text"]))
        self.assertIn(long_rows[4]["chunk_id"], payload(requests[1])["allowed_citation_ids"])
        self.assertNotIn(long_rows[4]["chunk_id"], final_context["allowed_citation_ids"])
        self.assertEqual(result["citation_checks"][0]["status"], "invalid_output")
        self.assertEqual(result["citation_checks"][1]["status"], "valid")
        self.assertEqual(result["answer"]["claims"][0]["citation_ids"], [long_rows[0]["chunk_id"]])
        for request in requests[-2:]:
            terminal = payload(request)
            self.assertEqual(terminal["allowed_actions"], ["answer"])
            self.assertEqual(terminal["allowed_citation_ids"], final_context["allowed_citation_ids"])
            self.assertEqual(terminal["autonomous_step"], 5)
            self.assertEqual(terminal["remaining_steps"], 0)
        self.counts(result, requests, chats=7, searches=5, repairs=1)

        batch = [search_action(actual_query, selected[:1]), search_action(changed_query, selected[1:])]
        client, requests = self.client(tool_response(*batch),
            response(answer_action(initial[0]["chunk_id"], second_paper["chunk_id"])), policy=interactive)
        result = self.run_agent(client, versions=selected, autonomous_steps=5,
            searcher=SequencedSearcher(initial[:1], [second_paper]))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(self.searcher.calls, [(actual_query, selected[:1], 5), (changed_query, selected[1:], 5)])
        self.assertEqual(self.request_data(requests[1])[1]["role"], "user")
        returned = [m for m in self.request_data(requests[1]) if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in returned], ["call-0", "call-1"])
        self.assertEqual([json.loads(m["content"])["status"] for m in returned], ["success", "success"])
        self.assertEqual({r["paper_id"] for r in result["answer"]["evidence_sources"]}, {"p1", "p2"})
        self.counts(result, requests, chats=2, searches=2)

        error = SearchError(SECRET, stage="embedding", statistics={"embedding_requests": 1,
            "failed_requests": 1, "total_tokens": None})
        outside = search_action("outside", [("unselected", "r9")])
        client, requests = self.client(tool_response("{bad", *batch),
            tool_response(search_action(next_query, selected[:1])),
            response(answer_action(initial[0]["chunk_id"])), policy=interactive)
        result = self.run_agent(client, versions=selected, autonomous_steps=5,
            searcher=SequencedSearcher(initial[:1], error, []))
        self.assertEqual(result["status"], "answered")
        returned = [json.loads(m["content"]) for m in self.request_data(requests[1]) if m["role"] == "tool"]
        self.assertEqual([m["status"] for m in returned], ["invalid_arguments", "success", "tool_error"])
        self.assertIn(initial[0]["chunk_id"], payload(requests[1])["allowed_citation_ids"])
        returned = [json.loads(m["content"]) for m in self.request_data(requests[2]) if m["role"] == "tool"]
        self.assertEqual(returned[-1]["status"], "no_hits")
        self.counts(result, requests, chats=3, searches=3)
        self.assertEqual(result["statistics"]["embedding"]["failed_requests"], 1)

        client, requests = self.client(tool_response(*(search_action(f"batch {i}", selected[:1]) for i in range(7))),
            response(answer_action(initial[0]["chunk_id"])), policy=interactive)
        result = self.run_agent(client, autonomous_steps=5,
            searcher=SequencedSearcher(initial[:1], [], [], [], []))
        self.assertEqual(result["status"], "answered")
        self.assertTrue(result["limit_finalize"])
        self.assertNotIn("tools", json.loads(requests[-1].content))
        returned = [json.loads(m["content"]) for m in self.request_data(requests[-1]) if m["role"] == "tool"]
        self.assertEqual([m["status"] for m in returned[-2:]], ["evidence_limit", "evidence_limit"])
        self.counts(result, requests, chats=2, searches=5)

        client, requests = self.client(response(search_action(actual_query, selected[:1])),
            response(knowledge_action()), policy=interactive)
        result = self.run_agent(client, autonomous_steps=5, searcher=SequencedSearcher())
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["action_steps"][0]["parse_error_code"], "action_not_allowed")
        self.counts(result, requests, chats=2, searches=0, repairs=1)

        local = self.add_chunk("local-method", text="Original stage definition on this page.")
        local.update(parent_id="method-parent", section_path=["2.1 Original method"])
        self.store.chunks[local["chunk_id"]] = deepcopy(local)
        parent = {"parent_id": "method-parent", "paper_id": "p1", "parse_revision": "r1",
                  "content_type": "body", "section_path": ["2.1 Original method"],
                  "child_ids": [local["chunk_id"]], "source_spans": [{"pdf_page": 1}]}
        self.store.get_parent = lambda identifier: deepcopy(parent) if identifier == parent["parent_id"] else None
        self.store.get_version_parents = lambda *pair: [deepcopy(parent)] if pair == ("p1", "r1") else []
        read = tool_response({})[1]
        read["choices"][0]["message"]["tool_calls"][0]["function"] = {
            "name": "read_context", "arguments": encoded({"parent_id": "method-parent"})}
        client, requests = self.client((200, read), tool_response(search_action(actual_query, selected[:1])),
            response(answer_action(local["chunk_id"], initial[0]["chunk_id"])), policy=interactive)
        result = self.run_agent(client, autonomous_steps=5, searcher=SequencedSearcher(initial[:1]))
        self.assertEqual(result["status"], "answered", result.get("error"))
        self.assertEqual(result["evidence_calls_used"], 2)
        self.assertIn(local["chunk_id"], result["context"]["allowed_citation_ids"])
        self.assertEqual(result["context_reads"][0]["visible_chunks"][0]["shown_text"], local["text"])
        self.assertEqual(result["context_reads"][0]["section_path"], parent["section_path"])
        self.assertEqual(result["context_reads"][0]["not_shown_ids"], [])
        self.assertNotIn("method-parent", result["context"]["allowed_citation_ids"])
        self.assertEqual(encoded(self.request_data(requests[-1])).count(local["text"]), 1)
        self.counts(result, requests, chats=3, searches=1)

        many = deepcopy(read)
        calls = many["choices"][0]["message"]["tool_calls"]
        calls[:] = [{**deepcopy(calls[0]), "id": f"read-{i}"} for i in range(6)]
        client, requests = self.client((200, many), response(answer_action(local["chunk_id"])), policy=interactive)
        result = self.run_agent(client, autonomous_steps=5, searcher=SequencedSearcher())
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["evidence_calls_used"], 5)
        self.assertEqual(len(result["context_reads"]), 5)
        self.assertEqual(result["action_steps"][0]["tool_calls"][-1]["tool_observation"]["status"], "evidence_limit")
        self.counts(result, requests, chats=2, searches=0)

        missing = deepcopy(read)
        missing["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = encoded({"parent_id": "not-exposed"})
        client, requests = self.client((200, missing), response(knowledge_action()), policy=interactive)
        result = self.run_agent(client, autonomous_steps=5, searcher=SequencedSearcher())
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["context_reads"][0]["status"], "tool_error")
        self.assertEqual(result["context"]["allowed_citation_ids"], [])
        self.counts(result, requests, chats=2, searches=0)

    def test_missing_chat_usage_remains_unknown(self):
        client, requests = self.client((200, completion(encoded(answer_action()), usage=None)))
        result = self.run_agent(client)
        self.assertEqual(result["status"], "answered")
        self.assertIsNone(result["statistics"]["chat"]["total_tokens"])
        self.assertFalse(result["statistics"]["chat"]["usage_complete"])
        self.counts(result, requests, chats=1, searches=1)

    def test_final_omitted_first_round_id_is_not_a_valid_citation(self):
        initial = self.add_chunk("initial-dropped", text="first")
        new = self.add_chunk("new-priority", text="new!!")
        client, requests = self.client(response(retry_action()), response(answer_action(initial["chunk_id"])),
                                       response(answer_action(initial["chunk_id"])))
        result = self.run_agent(client, searcher=SequencedSearcher([initial], [new]), max_chars=5)
        self.failed(result, "invalid_output")
        self.assertEqual(result["context"]["allowed_citation_ids"], [new["chunk_id"]])
        self.counts(result, requests, chats=3, searches=2, repairs=1)

    def test_corrupted_pdf_is_tool_error_without_citation_repair(self):
        self.pdf.write_bytes(b"corrupt temporary test PDF")
        client, requests = self.client(response(answer_action()))
        result = self.run_agent(client)
        self.failed(result, "tool_error")
        self.counts(result, requests, chats=1, searches=1)

    def test_input_and_fixed_first_top_k_reject_before_model_and_retrieval(self):
        for options in ({"top_k": 10}, {"top_k": True}, {"max_chars": 8001}, {"max_chars": True},
                        {"versions": []}, {"query": "   "}):
            with self.subTest(options=options):
                client, requests = self.client()
                result = self.run_agent(client, **options)
                self.failed(result, "tool_error")
                self.assertEqual(requests, [])
                self.assertEqual(self.searcher.calls, [])

    def test_resources_remain_owned_by_caller(self):
        client, requests = self.client(response(answer_action()))
        result = self.run_agent(client)
        self.assertEqual(result["status"], "answered")
        self.assertFalse(self.searcher.closed)
        self.assertFalse(self.store.closed)
        self.assertFalse(client._closed)


class DeadlineChecks(AgentFixture):
    def test_expired_initial_search_error_keeps_failure_but_deadline_wins(self):
        failed_stats = {"embedding_requests": 1, "failed_requests": 1, "total_tokens": None}
        error = SearchError(SECRET, stage="embedding", statistics=failed_stats)
        client, requests = self.client()
        result = self.run_agent(client, searcher=SequencedSearcher(error, on_search=lambda _: self.clock.advance(121)))
        self.failed(result, "budget_exceeded")
        self.assertEqual(result["error"]["code"], "deadline_exceeded")
        self.assertEqual(result["stop_reason"], "deadline_exceeded")
        self.assertEqual(result["interrupted_failure"]["status"], "tool_error")
        self.assertEqual(result["interrupted_failure"]["error"]["code"], "search_error")
        self.assertEqual(result["search_rounds"][0]["status"], "tool_error")
        self.assertEqual(result["search_rounds"][0]["statistics"], failed_stats)
        self.assertIsNone(result["statistics"]["embedding"]["total_tokens"])
        self.counts(result, requests, chats=0, searches=1)

    def test_expired_retry_search_error_keeps_both_rounds_and_no_final_chat(self):
        failed_stats = {"embedding_requests": 1, "failed_requests": 1, "total_tokens": None}
        error = SearchError(SECRET, stage="embedding", statistics=failed_stats)
        searcher = SequencedSearcher([self.row], error, on_search=lambda n: self.clock.advance(121) if n == 2 else None)
        client, requests = self.client(response(retry_action()))
        result = self.run_agent(client, searcher=searcher)
        self.failed(result, "budget_exceeded")
        self.assertEqual(result["error"]["code"], "deadline_exceeded")
        self.assertEqual(result["interrupted_failure"]["status"], "tool_error")
        self.assertEqual(result["interrupted_failure"]["failure_stage"], "retry_retrieval")
        self.assertEqual(result["search_rounds"][1]["statistics"], failed_stats)
        self.assertEqual(result["statistics"]["embedding"]["failed_requests"], 1)
        self.assertIsNone(result["statistics"]["embedding"]["total_tokens"])
        self.assertEqual(result["statistics"]["embedding"]["known_total_tokens"], 7)
        self.counts(result, requests, chats=1, searches=2)

    def test_expired_untyped_retrieval_error_keeps_unknown_usage_and_safe_failure(self):
        client, requests = self.client()
        searcher = SequencedSearcher(RuntimeError(SECRET), on_search=lambda _: self.clock.advance(121))
        result = self.run_agent(client, searcher=searcher)
        self.failed(result, "budget_exceeded")
        self.assertEqual(result["error"]["code"], "deadline_exceeded")
        self.assertEqual(result["interrupted_failure"]["status"], "tool_error")
        self.assertEqual(result["interrupted_failure"]["error"]["code"], "local_search_error")
        self.assertEqual(result["search_rounds"][0]["status"], "tool_error")
        self.assertIsNone(result["search_rounds"][0]["statistics"])
        self.assertIsNone(result["statistics"]["embedding"]["embedding_requests"])
        self.assertEqual(result["statistics"]["chat"]["sdk_request_attempts"], 0)
        self.assertEqual(len(self.searcher.calls), 1)
        self.assertEqual(requests, [])

    def test_deadline_after_initial_search_stops_before_chat(self):
        searcher = SequencedSearcher([self.row], on_search=lambda _: self.clock.advance(121))
        client, requests = self.client()
        result = self.run_agent(client, searcher=searcher)
        self.failed(result, "budget_exceeded")
        self.counts(result, requests, chats=0, searches=1)

    def test_deadline_after_model_response_prevents_publication(self):
        def slow_response(request):
            self.clock.advance(121)
            return httpx.Response(200, json=completion(encoded(answer_action())), request=request)
        client, requests = self.client(slow_response)
        result = self.run_agent(client)
        self.failed(result, "budget_exceeded")
        self.counts(result, requests, chats=1, searches=1)

    def test_deadline_after_retry_retrieval_prevents_final_chat(self):
        new = self.add_chunk()
        searcher = SequencedSearcher([self.row], [new], on_search=lambda n: self.clock.advance(121) if n == 2 else None)
        client, requests = self.client(response(retry_action()))
        result = self.run_agent(client, searcher=searcher)
        self.failed(result, "budget_exceeded")
        self.counts(result, requests, chats=1, searches=2)

    def test_deadline_after_parsing_prevents_even_retry_retrieval(self):
        def delayed_parse(content, **options):
            action = parse_agent_action(content, **options)
            self.clock.advance(121)
            return action
        client, requests = self.client(response(retry_action()))
        with patch("paper_assistant.agent.parse_agent_action", side_effect=delayed_parse):
            result = self.run_agent(client)
        self.failed(result, "budget_exceeded")
        self.counts(result, requests, chats=1, searches=1)

    def test_deadline_during_pdf_source_read_never_publishes_validated_answer(self):
        self.store.on_read = lambda: self.clock.advance(121)
        client, requests = self.client(response(answer_action()))
        result = self.run_agent(client)
        self.failed(result, "budget_exceeded")
        self.counts(result, requests, chats=1, searches=1)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
