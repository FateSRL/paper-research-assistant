"""D9 E owned entry/CLI checks: temporary sources, actual cores, SDK MockTransport."""
from contextlib import ExitStack, contextmanager, redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import socket
import sqlite3
import unittest
from unittest.mock import patch

import httpx
from paper_assistant import config, d9_runtime as runtime
from paper_assistant.answer_export import atomic_text, exclusive_json
from paper_assistant.llm_client import ChatBudget
from paper_assistant.hybrid_search import HybridEvidenceSearcher
from paper_assistant.config import RerankSettings
from paper_assistant.rerank_client import RerankClient
from scripts import answer_question_d9 as cli, check_agent, check_d9_e_batch as batch_fixtures
from scripts.check_agent import AgentFixture, answer_action, insufficient_action, response
from scripts.check_d9_e_batch import TimedScopedSearcher, sha

ROOT = Path(__file__).resolve().parents[1]


def prepare_action(action, *, answerable=True, missing_information=""):
    return {"action": "prepare_answer", "facts": deepcopy(action["answer"]["claims"]),
            "answerable": answerable, "missing_information": missing_information}


def prepare_ref_action(action, *, answerable=True, missing_information="", refs=None):
    facts = deepcopy(action["answer"]["claims"])
    # Generic fixture defaults to its first displayed source; structured cases
    # explicitly supply their known display mapping.
    mapping = refs or {chunk: number for number, chunk in enumerate(dict.fromkeys(
        chunk for fact in facts for chunk in fact.get("citation_ids", [])), 1)}
    for fact in facts:
        fact.setdefault("basis", "paper_evidence")
        fact["citation_refs"] = [mapping[chunk] for chunk in fact.pop("citation_ids", [])]
        for quote in fact.get("evidence_quotes", []):
            quote["ref"] = mapping[quote.pop("chunk_id")]
    return {"action": "prepare_answer", "facts": facts,
            "answerable": answerable, "missing_information": missing_information}


class RuntimeChecks(unittest.TestCase):
    setUp = batch_fixtures.D9BatchChecks.setUp
    client = AgentFixture.client

    def invoke(self, mode="fixed_rag", *, token="offline-submit", outcomes=None, rows=None,
               query=None, on_search=None, on_close=None, close_error=None, resource_error=None,
               override_core=None, export=None, hybrid=False, rerank=False,
               conversation_id=None, conversation_history=None, library_mode=False, pairs=None,
               search_outcomes=None, answer_instructions=None, iterations=None):
        f = self.fixture
        rows = f.search([f.abstract_id])["results"] if rows is None else rows
        self.searcher = TimedScopedSearcher(*(search_outcomes if search_outcomes is not None else [rows]),
                                           profile=self.profile["index_profile_id"], on_search=on_search)
        self.searcher.closed = False
        budget = ChatBudget((runtime.INTERACTIVE_AGENT_POLICY if mode == "agent" else runtime.INTERACTIVE_CHAT_POLICY) if library_mode else None, clock=self.clock)
        self.budget = budget
        if outcomes is None:
            draft = answer_action(f.abstract_id)
            if mode == "fixed_rag":
                outcomes = [response(draft["answer"])]
            elif library_mode:
                outcomes = [response("The provided evidence supports the requested answer."
                                     + (" [ID:1]" if rows else ""))]
            else:
                outcomes = [response(draft)]
            if library_mode and not conversation_history:
                outcomes.insert(0, response({"standalone_question": f.question if query is None else query,
                    "clarification_question": None, "referenced_evidence_ids": [], "planned_queries": []}))
        client, self.requests = self.client(*outcomes, budget=budget)
        self.chat_client = client
        self.rerank_requests = []

        def rerank_response(request):
            self.rerank_requests.append(request)
            documents = json.loads(request.content)["documents"]
            return httpx.Response(200, json={"results": [
                {"index": index, "relevance_score": 1.0 / (index + 1)}
                for index in range(len(documents))], "usage": {"total_tokens": 19}})

        self.reranker = (RerankClient(RerankSettings("qwen3-rerank", "offline-rerank-key",
            "https://example.invalid/compatible-api/v1"), transport=httpx.MockTransport(rerank_response))
            if rerank else None)

        @contextmanager
        def resources(*args):
            if resource_error:
                raise resource_error
            try:
                yield self.store, (HybridEvidenceSearcher(self.searcher, self.store, self.reranker) if hybrid else self.searcher)
            finally:
                if self.reranker:
                    self.reranker.close()
                self.store.close()
                self.searcher.closed = True
                if on_close:
                    on_close()
                if close_error:
                    raise close_error

        with ExitStack() as stack:
            stack.enter_context(patch.object(runtime, "ChatBudget", return_value=budget))
            stack.enter_context(patch.object(runtime, "load_agent_max_iterations", return_value=120))
            self.load_embedding = stack.enter_context(patch.object(runtime, "load_embedding_settings", return_value=self.embedding))
            stack.enter_context(patch.object(runtime, "load_llm_settings", return_value=self.settings))
            self.client_factory = stack.enter_context(patch.object(runtime, "RecordedLLM", return_value=client))
            stack.enter_context(patch.object(runtime, "open_retrieval_resources", side_effect=resources))
            if override_core:
                stack.enter_context(patch.object(runtime, "answer_question" if mode == "fixed_rag" else "answer_question_agent", side_effect=override_core))
            if export:
                stack.enter_context(patch.object(runtime, "save_agent_run", side_effect=export))
            result = runtime.run_question(f.question if query is None else query, f.pairs if pairs is None else pairs,
                mode=mode, project_root=self.root, submission_id=token,
                conversation_id=conversation_id, conversation_history=conversation_history, library_mode=library_mode,
                **({"answer_instructions": answer_instructions} if answer_instructions else {}),
                **({"max_iterations": iterations} if iterations is not None else {}))
        self.assertNotIn(check_agent.SECRET, json.dumps(result, ensure_ascii=False))
        return result

    def test_actual_cores_citations_closed_resources_and_stage_records(self):
        from dataclasses import replace
        self.settings = replace(self.settings, context_length=1048576, timeout=300.0)
        for mode in runtime.MODES:
            with self.subTest(mode=mode):
                r = self.invoke(mode, token=mode, hybrid=True, rerank=True)
                self.assertEqual(r["status"], "answered")
                from paper_assistant.context import ANSWER_ORGANIZATION_INSTRUCTION
                actual_system = json.loads(self.requests[0].content)["messages"][0]["content"]
                self.assertIn(ANSWER_ORGANIZATION_INSTRUCTION, actual_system)
                self.assertNotIn("tools", json.loads(self.requests[0].content))
                self.assertIsNone(r["answer"].get("direct_answer"))
                self.assertEqual(r["answer"]["claims"][0]["evidence_quotes"], [])
                self.assertTrue(r["stop_reason"])
                self.assertEqual(r["answer"]["evidence_refs"][0]["pdf_page"], 2)
                self.assertEqual(r["registry_binding"]["path"], runtime.REGISTRY_PATH)
                self.assertEqual(r["embedding_requests"], 1)
                self.assertEqual(r["llm_requests"], 1)
                self.assertEqual(r["result"]["search"]["retrieval_method"], "bm25_dense_rrf_rerank")
                self.assertEqual(r["rerank_requests"], 1)
                self.assertEqual(r["network_requests"], 3)
                self.assertEqual(len(self.rerank_requests), 1)
                self.assertEqual(r["result"]["statistics"]["rerank"]["requests"], 1)
                self.assertEqual(r["result"]["context"]["score_kind"], "rrf")
                user_payload = json.loads(json.loads(self.requests[0].content)["messages"][1]["content"])
                self.assertEqual(user_payload["score_kind"], "rrf")
                self.assertEqual(user_payload["ranking_method"], "rerank")
                self.assertEqual(r["result"]["search"]["top_k"], 5)
                self.assertEqual(self.searcher.calls[0]["top_k"], 20)
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(r["business_commit"]["status"], "answered")
                self.assertTrue(self.store.closed and self.searcher.closed)
                self.assertTrue(self.chat_client._closed and self.chat_client.client.is_closed())
                self.assertTrue(self.reranker._client.is_closed)
                self.assertTrue(r["history_report"].startswith("archive/run_logs/d9/" + mode))
                self.assertEqual(r["export"]["status"], "completed")
                self.assertTrue((self.root / "artifacts/d9" / (mode + "_result.json")).is_file())
                self.assertIn("重排请求：1", (self.root / r["history_markdown"]).read_text(encoding="utf-8"))
                self.assertFalse((self.root / "artifacts/d8/agent_result.json").exists())

                action = answer_action(self.fixture.abstract_id)
                action["answer"]["direct_answer"] = "Yes"
                malformed = deepcopy(action)
                malformed["answer"]["unsupported_field"] = True
                repaired = self.invoke(mode, token=mode + "-direct-repair", outcomes=[
                    response(malformed["answer"] if mode == "fixed_rag" else malformed),
                    response(action["answer"] if mode == "fixed_rag" else action)])
                self.assertEqual(repaired["status"], "answered")
                self.assertEqual(repaired["answer"]["direct_answer"], "Yes")
                self.assertEqual(repaired["chat_statistics"]["repairs"], 1)
                saved = json.loads((self.root / repaired["history_report"]).read_text(encoding="utf-8"))
                self.assertEqual(saved["result"]["answer"]["direct_answer"], "Yes")

        from paper_assistant.context import ANSWER_ORGANIZATION_INSTRUCTION
        self.assertIn(ANSWER_ORGANIZATION_INSTRUCTION,
                      json.loads(self.requests[-1].content)["messages"][0]["content"])
        self.assertIn("only when necessary to answer", ANSWER_ORGANIZATION_INSTRUCTION)
        self.assertIn("not an automatic explanation of the entire system", ANSWER_ORGANIZATION_INSTRUCTION)
        f = self.fixture

        from paper_assistant.prose import normalize_citation_markers, parse_markers
        raw = "Book [1]; first [ID: 1], second [ID: 2], first again [ID:1], second again [ID:۲]."
        normalized = "Book [1]; first [ID:1], second [ID:2], first again [ID:1], second again [ID:2]."
        self.assertEqual(normalize_citation_markers(raw), normalized)
        self.assertEqual(normalize_citation_markers(normalized), normalized)
        self.assertEqual(normalize_citation_markers("Arabic ١ remains prose; [ID: ٠١] [۱۲] [ID: ۱۲]."),
                         "Arabic ١ remains prose; [ID:01] [۱۲] [ID:12].")
        unsupported = "No handles: [1,2] [99] ref1 chunk_x."
        self.assertEqual(normalize_citation_markers(unsupported), unsupported)
        variants = "[ID: 1] (ID:2) 【ID：۲】 (**ID:1**) [ID:1, ID:2]"
        self.assertEqual(normalize_citation_markers(variants), "[ID:1] [ID:2] [ID:2] [ID:1] [ID:1][ID:2]")
        for number, (original, delivered) in enumerate(((raw, normalized),
                (variants, normalize_citation_markers(variants)),
                (normalized, normalized), ("Ordinary bibliography [1] [99] [۲].",
                                           "Ordinary bibliography [1] [99] [۲]."),
                ("A local analysis without citations.",
                                           "A local analysis without citations."))):
            with self.subTest(prose_format=number), patch.object(runtime.web_runtime, "_ready_versions", return_value=[{
                    "paper_id": f.paper_id, "parse_revision": f.parse_revision, "title": "Offline fixture"}]):
                query = "What do the selected passages report?"
                compatible = self.invoke("agent", token=f"prose-format-{number}", library_mode=True,
                    query=query, rows=f.search([f.abstract_id, f.body_id])["results"], outcomes=[
                        response({"standalone_question": query, "clarification_question": None,
                                  "referenced_evidence_ids": [], "planned_queries": []}),
                        check_agent.tool_response({"query": query, "selected_versions": [
                            {"paper_id": f.paper_id, "parse_revision": f.parse_revision}],
                            "missing_information": "Read the selected evidence."}),
                        response(original)])
            self.assertEqual(compatible["status"], "answered", compatible.get("error"))
            self.assertEqual(compatible["llm_requests"], 3)
            self.assertEqual(compatible["chat_statistics"]["repairs"], 0)
            self.assertEqual(compatible["answer"]["text"], delivered)
            self.assertEqual(compatible["result"]["action_steps"][-1]["response"]["content"], original)
            self.assertEqual(compatible["chat_attempts"][-1]["content"], original)
            markers = parse_markers(delivered)
            self.assertEqual([{k: c[k] for k in ("index", "position", "ref")}
                              for c in compatible["answer"]["citations"]], markers)
            expected_ids = {1: f.abstract_id, 2: f.body_id}
            self.assertEqual([c["chunk_id"] for c in compatible["answer"]["citations"]],
                             [expected_ids[m["ref"]] for m in markers])
            self.assertEqual([c["chunk_id"] for c in compatible["answer"]["evidence_sources"]],
                             [f.abstract_id, f.body_id] if markers else [])
            self.assertEqual([c["chunk_id"] for c in compatible["answer"]["evidence_refs"]],
                             [f.abstract_id, f.body_id] if markers else [])
            saved_compatible = json.loads((self.root / compatible["history_report"]).read_text(encoding="utf-8"))
            self.assertEqual(saved_compatible["answer"], compatible["answer"])
            self.assertEqual(saved_compatible["result"]["action_steps"][-1]["response"]["content"], original)
            self.assertTrue(self.store.closed and self.searcher.closed and self.chat_client._closed)

        # Stable registration is independent of copies/order and grants no
        # authority to registered but currently invisible chunks.
        from paper_assistant.prose import EvidenceRegistry, source_refs
        from paper_assistant.agent import fit_agent_request
        from paper_assistant.message_fit import count_request_tokens
        registry = EvidenceRegistry()
        context = deepcopy(compatible["result"]["context"])
        third = deepcopy(context["shown_evidence"][0])
        third.update(chunk_id="offline-third", shown_text="Third original passage. " * 20)
        context["shown_evidence"].append(third)
        registry.stamp(context)
        original_map = {row["chunk_id"]: row["ref"] for row in context["shown_evidence"]}
        reordered = deepcopy(context)
        reordered["shown_evidence"].reverse()
        registry.stamp(reordered)
        self.assertEqual({row["chunk_id"]: row["ref"] for row in reordered["shown_evidence"]}, original_map)
        self.assertEqual([row["ref"] for row in source_refs(reordered, registry)], [3, 2, 1])
        isolated = EvidenceRegistry()
        isolated.stamp(reordered)
        self.assertEqual(reordered["shown_evidence"][0]["ref"], 1)
        registry.stamp(reordered)
        context["shown_evidence"] = [context["shown_evidence"][0], third]
        registry.stamp(context)
        self.assertEqual(context["allowed_refs"], [1, 3])
        self.assertEqual(registry.resolve(3, context), third["chunk_id"])
        for number, code in ((2, "citation_not_shown"), (99, "citation_unknown_ref")):
            with self.assertRaises(ValueError) as caught:
                registry.resolve(number, context)
            self.assertEqual(str(caught.exception), code)
        # Whole-request fitting removes originals, keeps non-positional refs,
        # and synchronizes permissions. Redisplay recovers the original number.
        context["allowed_citation_ids"] = [row["chunk_id"] for row in context["shown_evidence"]]
        messages = [{"role": "system", "content": "Answer using originals."}, {"role": "user",
            "content": json.dumps({"sources": source_refs(context, registry), "allowed_refs": [1, 3]})}]
        messages.insert(1, {"role": "user", "content": json.dumps({"evidence_sections": [{
            "chunks": deepcopy(context["shown_evidence"])}], "allowed_refs": [1, 3]})})
        capacity = count_request_tokens(messages) - 1
        with patch("paper_assistant.agent.context_fit_budget", return_value=capacity):
            fitted, dropped = fit_agent_request(context, messages, context_length=1048576, max_tokens=4096, protect_groups=3)
        self.assertIn(f.abstract_id, dropped)
        self.assertEqual([row["ref"] for section in json.loads(fitted[1]["content"])["evidence_sections"]
                          for row in section["chunks"]], [3])
        self.assertEqual(json.loads(fitted[-1]["content"])["allowed_refs"], [3])
        self.assertEqual([row["ref"] for row in source_refs(context, registry)], [3])
        context["shown_evidence"].insert(0, deepcopy(compatible["result"]["context"]["shown_evidence"][0]))
        registry.stamp(context)
        self.assertEqual(context["allowed_refs"], [1, 3])

        def text_count(messages, text):
            total = 0

            def walk(value):
                nonlocal total
                if isinstance(value, str):
                    total += value.count(text)
                elif isinstance(value, dict):
                    for item in value.values():
                        walk(item)
                elif isinstance(value, list):
                    for item in value:
                        walk(item)

            for message in messages:
                content = message.get("content")
                try:
                    walk(json.loads(content))
                except (TypeError, ValueError):
                    if isinstance(content, str):
                        total += content.count(text)
            return total

        search = {"query": f.question, "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in f.pairs],
                  "missing_information": "Read the selected paper evidence."}

        with patch.object(runtime.web_runtime, "_ready_versions", return_value=[{
                **search["selected_versions"][0], "title": "Offline structural fixture"}]):
            stable = self.invoke("agent", token="stable-two-searches", library_mode=True, query="Explain both selected passages.",
                search_outcomes=[f.search([f.abstract_id])["results"],
                                 f.search([f.body_id, f.abstract_id])["results"]], outcomes=[
                    response({"clarification_question": None, "planned_queries": []}),
                    check_agent.tool_response(search),
                    check_agent.tool_response({**search, "query": "Read another requested detail"}),
                    response("The original detail is supported. [ID:2]")])
        self.assertEqual(stable["status"], "answered", [(step.get("parse_error_code"), step.get("response")) for step in stable["result"]["action_steps"]])
        self.assertEqual(stable["chat_statistics"]["repairs"], 0)
        self.assertEqual({row["chunk_id"]: row["ref"] for row in stable["result"]["evidence_registry"]},
                         {f.abstract_id: 1, f.body_id: 2})
        for step in stable["result"]["action_steps"]:
            for call in step.get("tool_calls") or []:
                for row in call["tool_observation"].get("shown_refs", []):
                    self.assertEqual(row["ref"], 1 if row["chunk_id"] == f.abstract_id else 2)
            for message in step["messages"]:
                if message["role"] == "user":
                    payload = json.loads(message["content"])
                    for section in payload.get("evidence_sections", []):
                        for row in section["chunks"]:
                            self.assertEqual(row["ref"], 1 if row["chunk_id"] == f.abstract_id else 2)
        self.assertFalse(any((step.get("parsed_action") or {}).get("action") == "prepare_answer"
                             for step in stable["result"]["action_steps"]))
        self.assertEqual(stable["agent_max_iterations"], 120)
        self.assertEqual(stable["answer"]["citations"][0]["chunk_id"], f.body_id)

        from paper_assistant.js_runtime import JavaScriptError, run_javascript
        self.assertEqual(run_javascript("console.log([3,1,2].sort().join(','))")["stdout"], "1,2,3")
        self.assertEqual(run_javascript("var leak=1; console.log(leak)")["stdout"], "1")
        self.assertEqual(run_javascript("console.log(typeof leak)")["stdout"], "undefined")
        with self.assertRaises(JavaScriptError):
            run_javascript("while(true){}")
        with self.assertRaises(JavaScriptError):
            run_javascript('console.log("x".repeat(1048577))')

        with patch.object(config, "_read_env", return_value={}):
            self.assertEqual(config.load_agent_max_iterations(), 120)
        with patch.object(config, "_read_env", return_value={"AGENT_MAX_ITERATIONS": "9"}):
            self.assertEqual(config.load_agent_max_iterations(), 9)
        with patch.object(config, "_read_env", return_value={"AGENT_MAX_ITERATIONS": "0"}):
            with self.assertRaises(config.ConfigError):
                config.load_agent_max_iterations()
        planning = response({"clarification_question": None, "planned_queries": []})
        def native(name, arguments, content=None):
            tool = check_agent.tool_response({})[1]
            message = tool["choices"][0]["message"]
            message["content"] = content
            message["tool_calls"][0]["function"] = {"name": name, "arguments": json.dumps(arguments)}
            return 200, tool

        def run_case(token, outcomes, **kwargs):
            with patch.object(runtime.web_runtime, "_ready_versions", return_value=[{
                    **search["selected_versions"][0], "title": "Offline structural fixture"}]):
                return self.invoke("agent", token=token, library_mode=True, query="Explain the selected evidence.",
                    outcomes=[planning, *outcomes], **kwargs)

        direct = run_case("react-direct", [response("A complete general explanation without citations.")])
        self.assertEqual(direct["status"], "answered", direct.get("error"))
        self.assertEqual(direct["llm_requests"], 2)
        self.assertEqual(direct["embedding_requests"], 0)
        self.assertEqual(direct["answer"]["citations"], [])
        self.assertIsNone(direct["result"]["synthesis"])
        from paper_assistant.agent_prompt import AUTONOMOUS_PROMPT_VERSION, PROSE_FINAL_PROMPT_VERSION
        self.assertEqual(direct["result"]["final_prompt_version"], AUTONOMOUS_PROMPT_VERSION)
        system = direct["result"]["action_steps"][0]["messages"][0]["content"]
        self.assertNotIn("prepare_answer", system)
        self.assertNotIn("At most five", system)
        self.assertEqual(direct["policy"]["request_timeout"], 300)
        self.assertIsNone(direct["policy"]["max_repairs"])

        # Six real local retrievals / seven model rounds: no five-call gate.
        many = run_case("react-over-five", [
            *[native("search", {**search, "query": "Original detail " + str(i)}) for i in range(6)],
            response("The requested fact is supported. [ID:1]")],
            search_outcomes=[f.search([f.abstract_id])["results"] for _ in range(6)])
        self.assertEqual(many["status"], "answered", many.get("error"))
        self.assertEqual(many["result"]["autonomous_steps_used"], 7)
        self.assertEqual(many["result"]["evidence_calls_used"], 6)
        self.assertEqual(many["embedding_requests"], 6)
        self.assertEqual(many["llm_requests"], 8)
        self.assertEqual([row["ref"] for row in many["result"]["evidence_registry"]], [1])

        # Recoverable tool/output/citation failures stay in one loop. Neither
        # process narration nor an old action envelope can become recovered prose.
        corrected = run_case("react-multiple-corrections", [
            native("not_available", {}, "I will continue looking."),
            native("search", {"wrong": "field"}), native("read_context", {"chunk_id": "unknown"}),
            native("search", search), response("Unknown handle. [ID:99]"),
            response("Unknown again. 【ID：99】"),
            response({"action": "prepare_answer", "facts": [], "answerable": True, "missing_information": ""}),
            response("Correct final. [ID: 1] Book [99] [1,2].")])
        self.assertEqual(corrected["status"], "answered", corrected.get("error"))
        self.assertGreater(corrected["chat_statistics"]["repairs"], 1)
        self.assertEqual(corrected["result"]["autonomous_steps_used"], 8)
        self.assertEqual(corrected["answer"]["text"], "Correct final. [ID:1] Book [99] [1,2].")
        self.assertEqual(len(corrected["answer"]["citations"]), 1)
        self.assertTrue(any(step.get("purpose") == "repair" for step in corrected["result"]["action_steps"]))
        self.assertIsNone(corrected["result"]["recovery"])
        self.assertIsNone(corrected["result"]["synthesis"])
        for invalid in ("",):
            empty = run_case("react-empty", [response(invalid), response("A complete evidence-gap explanation.")])
            self.assertEqual(empty["status"], "answered")
            self.assertEqual(empty["chat_statistics"]["repairs"], 1)

        for case, final in (("ok", "Supported at the explicit limit. [ID:1]"), ("invalid", "Unknown. [ID:99]")):
            limited = run_case("react-limit-" + case, [native("search", search), response(final)], iterations=1)
            self.assertEqual(limited["llm_requests"], 3)
            self.assertEqual(limited["chat_attempts"][-1]["purpose"], "synthesis")
            self.assertEqual(limited["chat_attempts"][-1]["timeout_seconds"], 90)
            self.assertNotIn("tools", json.loads(self.requests[-1].content))
            self.assertEqual(limited["status"], "answered" if case == "ok" else "invalid_output")
            self.assertEqual(limited["result"]["synthesis"]["status"], "completed" if case == "ok" else "invalid_output")
            self.assertEqual(limited["result"]["autonomous_steps_used"], 1)
            if case == "ok":
                self.assertEqual(limited["result"]["final_prompt_version"], PROSE_FINAL_PROMPT_VERSION)

        with patch("paper_assistant.agent.validate_prose_citations", side_effect=RuntimeError("offline synthesis failure")):
            synthesis_failed = run_case("react-single-synthesis-failure", [native("search", search),
                response("A candidate final answer. [ID:1]")], iterations=1)
        self.assertEqual(synthesis_failed["status"], "tool_error")
        self.assertEqual(synthesis_failed["llm_requests"], 3)
        self.assertEqual(synthesis_failed["result"]["synthesis"]["status"], "failed")

        # Normal JS is a native tool and does not force another preparation.
        js = run_case("react-native-js", [native("search", search),
            native("run_javascript", {"code": "console.log([1,2,3].reduce((a,b)=>a+b,0)/3)"}),
            response("The mean calculated from the supplied values is 2. [ID:1]")])
        self.assertEqual(js["status"], "answered")
        self.assertEqual(js["result"]["javascript_calls"][0]["status"], "success")
        self.assertEqual(js["result"]["evidence_calls_used"], 1)
        self.assertEqual(js["llm_requests"], 4)
        self.assertIn('"stdout": "2"', json.dumps(js["result"]["action_steps"], ensure_ascii=False))

        # An exhausted transient logical invoke gets one no-tool synthesis;
        # authentication failures are not sent through that fallback.
        from scripts.check_llm import http_error
        network = run_case("react-network-synthesis", [native("search", search), http_error(503), http_error(503),
            response("Recovered supported evidence. [ID:1]")])
        self.assertEqual(network["status"], "answered", network.get("error"))
        self.assertEqual(network["result"]["stop_reason"], "error_synthesized")
        self.assertEqual(network["chat_statistics"]["network_retries"], 1)
        self.assertEqual(network["chat_attempts"][-1]["purpose"], "synthesis")
        denied = run_case("react-auth-stop", [http_error(401)])
        self.assertEqual(denied["status"], "tool_error")
        self.assertEqual(denied["llm_requests"], 2)
        self.assertIsNone(denied["result"]["synthesis"])

        # Already validated prose survives cleanup failure with its bound source
        # snapshot, without another invoke or an invented historical answer.
        recovered = run_case("react-validated-recovery", [native("search", search),
            response("The complete original final answer. [ID:1]")], close_error=RuntimeError("offline cleanup"))
        self.assertEqual(recovered["status"], "answered", recovered.get("error"))
        self.assertEqual(recovered["llm_requests"], 3)
        self.assertEqual(recovered["result"]["recovery"]["kind"], "validated_final")
        self.assertEqual(recovered["result"]["recovery"]["model_requests"], 0)
        self.assertEqual(recovered["answer"]["evidence_sources"][0]["chunk_id"], f.abstract_id)
        self.assertTrue(self.store.closed and self.searcher.closed and self.chat_client._closed)
        saved = json.loads((self.root / recovered["history_report"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["answer"], recovered["answer"])
        downloaded, markdown = runtime.download_payloads(recovered, project_root=self.root)
        self.assertEqual(json.loads(downloaded)["answer"], recovered["answer"])
        self.assertIn(recovered["answer"]["text"], markdown.decode("utf-8"))

        from dataclasses import replace
        import pymupdf
        from paper_assistant.chunking import sha256_bytes
        from paper_assistant.indexing import digest
        from paper_assistant.source_scope import Registry
        from paper_assistant.storage import PaperStore
        from scripts.check_storage import _bundle

        # One stored parent spans two real pages and ten page-local children.
        # Two retrieved anchors share that parent; the remaining children are local reads.
        paper_id = "local_s"
        pdf_path = self.root / "data/papers/structured-runtime.pdf"
        parts = []
        with pymupdf.open() as document:
            for page_number in (1, 2):
                page = document.new_page(width=600, height=800)
                for slot in range(5):
                    number = len(parts) + 1
                    left = (f"Child {number} records the recovered mechanism. "
                            + "Recovered measurements distinguish reliable coordination from independent execution. " * 4)
                    right = "Repeated observations preserve the documented setting and its supporting explanation. " * 5
                    top = 40 + slot * 140
                    rectangles = ((60, top, 270, top + 120), (330, top, 540, top + 120))
                    for rectangle, text in zip(rectangles, (left, right)):
                        page.insert_textbox(rectangle, text, fontsize=6)
                    parts.append((page_number, left + "\n\n" + right, rectangles, len(left)))
            pdf_path.write_bytes(document.tobytes())
            page.get_pixmap(clip=pymupdf.Rect(rectangles[1])).save(self.root / "data/papers/structured-region.png")
        paper = {"paper_id": paper_id, "source_type": "local", "title": "Offline structured runtime",
                 "arxiv_version": "", "source_url": "", "local_path": "data/papers/structured-runtime.pdf",
                 "pdf_sha256": sha(pdf_path), "page_count": 2, "text_selectable": True}
        recipe = {"paper_id": paper_id, "pdf_sha256": paper["pdf_sha256"],
                  "parser": {"name": "mineru", "version": "4.0.12", "tier": "standard", "page_range": "all"},
                  "chunking": {"revision": "structured-pdf-v1", "child_tokens": 512, "parent_tokens": 1536}}
        recipe_hash = digest(recipe)
        revision = "r_" + recipe_hash[:16]
        parent_id = f"{paper_id}_{revision}_parent1"
        children, parent_spans, offset = [], [], 0
        for number, (page_number, text, rectangles, split) in enumerate(parts, start=1):
            spans = []
            for region, ((x0, y0, x1, y1), start, end) in enumerate(
                    zip(rectangles, (0, split + 2), (split, len(text))), start=1):
                spans.append({"block_id": f"p{page_number - 1}:{number}:{region}", "pdf_page": page_number,
                    "bbox": [x0 / 600, y0 / 800, x1 / 600, y1 / 800], "page_size": [600, 800],
                    "coordinate_system": "normalized", "content_type": "text", "source_field": "text",
                    "source_char_start": 0, "source_char_end": end - start, "text_start": start, "text_end": end})
            child = {"chunk_id": f"{paper_id}_{revision}_p{page_number}_c{(number - 1) % 5 + 1}",
                "paper_id": paper_id, "parse_revision": revision, "pdf_sha256": paper["pdf_sha256"],
                "pdf_page": page_number, "text": text, "text_sha256": sha256_bytes(text.encode("utf-8")),
                "parent_id": parent_id, "section_path": ["Method", "Recovered mechanism"],
                "content_type": "body", "content_types": ["text"], "source_spans": spans,
                "token_count": len(text.split()), "assets": []}
            if number == 10:
                child["assets"] = [{"type": "image_body", "image_path": "data/papers/structured-region.png",
                                    "bbox": deepcopy(spans[-1]["bbox"])}]
            children.append(child)
            parent_spans.extend({**deepcopy(span), "text_start": span["text_start"] + offset,
                                 "text_end": span["text_end"] + offset} for span in spans)
            offset += len(text) + 2
        child_ids = [child["chunk_id"] for child in children]
        parent = {"parent_id": parent_id, "paper_id": paper_id, "parse_revision": revision,
                  "text": "\n\n".join(child["text"] for child in children), "child_ids": child_ids,
                  "section_path": ["Method", "Recovered mechanism"], "content_type": "body",
                  "source_spans": parent_spans}
        table_parent_id = f"{paper_id}_{revision}_parent2"
        table_caption = "Table 2: Recovered measurements"
        table_rows = ["<tr><td></td><td>Prec</td><td>Rec</td><td>F1</td></tr>",
                      "<tr><td>BERT</td><td>0.91</td><td>0.92</td><td>0.93</td></tr>"]
        table_children, table_parent_spans, table_offset = [], [], 0
        for number, row_html in enumerate(table_rows, start=6):
            text = table_caption + "\n" + row_html
            span = {"block_id": f"p1:table:{number}", "pdf_page": 2,
                    "bbox": [0.1, 0.2, 0.9, 0.3], "page_size": [600, 800],
                    "coordinate_system": "normalized", "content_type": "table", "source_field": "content",
                    "source_char_start": 0, "source_char_end": len(text), "text_start": 0, "text_end": len(text)}
            table_children.append({
                "chunk_id": f"{paper_id}_{revision}_p2_c{number}",
                "paper_id": paper_id, "parse_revision": revision, "pdf_sha256": paper["pdf_sha256"],
                "pdf_page": 2, "text": text, "text_sha256": sha256_bytes(text.encode("utf-8")),
                "parent_id": table_parent_id, "section_path": ["Results", "Recovered measurements"],
                "content_type": "table", "content_types": ["table"], "source_spans": [span],
                "token_count": len(text.split()), "assets": []})
            table_parent_spans.append({**deepcopy(span), "text_start": table_offset,
                                       "text_end": table_offset + len(text)})
            table_offset += len(text) + 1
        table_parent = {"parent_id": table_parent_id, "paper_id": paper_id, "parse_revision": revision,
                        "text": table_caption + "\n" + "\n".join(table_rows),
                        "child_ids": [child["chunk_id"] for child in table_children],
                        "section_path": ["Results", "Recovered measurements"], "content_type": "table",
                        "content_types": ["table"], "source_spans": table_parent_spans}
        relative = f"data/chunks/{paper_id}/{revision}"
        manifest = {"schema_revision": "structured-pdf-v1", "paper_id": paper_id, "parse_revision": revision,
                    "recipe": recipe, "recipe_sha256": recipe_hash,
                    "source_paths": {"pdf": paper["local_path"], "parents": relative + "/parents.jsonl",
                                     "chunks": relative + "/chunks.jsonl"},
                    "statistics": {"page_count": 2, "parent_count": 2, "source_block_count": 23,
                                   "chunk_count": 12, "chunks_per_page": {"1": 5, "2": 7}}}
        database = self.root / "data/index/structured-runtime.sqlite3"
        with PaperStore(database) as store:
            store.import_version(replace(_bundle(paper, manifest, children + table_children),
                                         parents=[parent, table_parent]))
        pairs = [(paper_id, revision)]
        versions = [{"paper_id": paper_id, "parse_revision": revision}]
        question = "Explain how the recovered mechanism continues across both pages."
        preparation = {"standalone_question": question, "clarification_question": None,
                       "referenced_evidence_ids": [], "planned_queries": []}
        anchors = [{**deepcopy(children[index]), "rank": rank, "score": 0.8 - rank * 0.05}
                   for rank, index in enumerate((0, 2), start=1)]
        for mode in runtime.MODES:
            with self.subTest(structured_mode=mode):
                self.store = PaperStore(database, read_only=True)
                self.addCleanup(self.store.close)
                registry = Registry(self.root, self.store, pairs)
                self.assertTrue(registry.structured)
                self.assertEqual(registry.get_parent(parent_id), parent)
                self.store.get_parent = unittest.mock.Mock(wraps=self.store.get_parent)
                action = answer_action(child_ids[-1])
                action["answer"]["direct_answer"] = "The recovered mechanism continues across both pages."
                quote = {"chunk_id": child_ids[-1], "quote": children[-1]["text"].split(". ")[0] + "."}
                action["answer"]["claims"][0]["evidence_quotes"] = [quote]
                outcomes = [response(preparation)]
                if mode == "agent":
                    tool = check_agent.tool_response({})[1]
                    tool["choices"][0]["message"]["tool_calls"][0]["function"] = {
                        "name": "read_context", "arguments": json.dumps({"parent_id": parent_id})}
                    outcomes.append((200, tool))
                if mode == "agent":
                    outcomes.append(response("The recovered mechanism continues across both pages. [ID:10]"))
                else:
                    outcomes.append(response(action["answer"]))
                with patch.object(runtime.web_runtime, "_ready_versions", return_value=[{**versions[0], "title": paper["title"]}]):
                    r = self.invoke(mode, token=mode + "-structured", query=question, pairs=pairs,
                                    rows=anchors, library_mode=True, outcomes=outcomes)
                self.assertEqual(r["status"], "answered", (r.get("error"), r["result"].get("failure_stage"),
                    (r["result"].get("context") or {}).get("omitted_evidence")))
                if mode == "agent":
                    self.assertEqual(r["answer"]["text"],
                                     "The recovered mechanism continues across both pages. [ID:10]")
                    self.assertEqual(r["answer"]["citations"][0]["chunk_id"], child_ids[-1])
                else:
                    self.assertEqual(r["answer"]["direct_answer"], action["answer"]["direct_answer"])
                self.assertEqual(r["embedding_requests"], 0 if mode == "agent" else 1)
                self.assertEqual(r["llm_requests"], 2 if mode == "fixed_rag" else 3)
                self.assertEqual(self.store.get_parent.call_count, 1)
                self.assertTrue(self.store._closed and self.searcher.closed and self.chat_client._closed)
                context = r["result"]["context"]
                if mode == "fixed_rag":
                    self.assertEqual(context["max_tokens"], 8192)
                    self.assertEqual(context["tokenizer"], "Qwen3-Embedding-0.6B")
                    self.assertLessEqual(context["shown_tokens"], 8192)
                else:
                    self.assertIsNone(context["max_chars"])
                    self.assertNotIn("max_tokens", context)
                self.assertGreater(sum(len(row["shown_text"]) for row in context["shown_evidence"]), 8000)
                self.assertEqual(len(context["shown_evidence"]), 10)
                self.assertEqual(set(context["allowed_citation_ids"]), set(child_ids))
                self.assertNotIn(parent_id, context["allowed_citation_ids"])
                if mode == "fixed_rag":
                    self.assertEqual([row["chunk_id"] for row in r["result"]["search"]["results"]], [child_ids[0], child_ids[2]])
                else:
                    self.assertIsNone(r["result"]["search"])
                    self.assertEqual(r["result"]["context_reads"][0]["shown_ids"], child_ids)
                    self.assertEqual(r["rerank_requests"], 0)
                    self.assertEqual(r["result"]["evidence_calls_used"], 1)
                self.assertEqual({row["pdf_page"] for row in context["shown_evidence"]}, {1, 2})
                origins = context["reading_origins"]
                self.assertEqual(len(origins), 10 if mode == "agent" else 8)
                self.assertEqual(len({row["chunk_id"] for row in origins}), 10 if mode == "agent" else 8)
                self.assertTrue(all(row["kind"] == ("explicit_parent_read" if mode == "agent" else "parent_context_read") and row["parent_id"] == parent_id
                                    for row in origins))
                for row in context["shown_evidence"]:
                    original = next(child for child in children if child["chunk_id"] == row["chunk_id"])
                    self.assertEqual(row["shown_text"], original["text"])
                    self.assertEqual(row["source_spans"], original["source_spans"])
                    self.assertEqual(row["parent_id"], parent_id)
                    if row["chunk_id"] not in (child_ids[0], child_ids[2]):
                        self.assertIsNone(row["score"])
                evidence = r["answer"]["evidence_sources"][0]
                self.assertEqual(r["answer"]["evidence_refs"][0]["chunk_id"], child_ids[-1])
                self.assertEqual(evidence["pdf_page"], 2)
                self.assertEqual(evidence["text"], children[-1]["text"])
                for key in ("parent_id", "section_path", "content_type", "content_types", "source_spans", "assets"):
                    self.assertEqual(evidence[key], children[-1][key])
                self.assertEqual(evidence["reading_origins"][0]["parent_id"], parent_id)
                if mode == "agent":
                    final_messages = json.loads(self.requests[-1].content)["messages"]
                    final_input = json.loads(final_messages[-1]["content"])
                    actual_input = final_input
                    self.assertEqual(final_input["allowed_refs"], list(range(1, 11)))
                    self.assertEqual([row["ref"] for section in final_input["evidence_sections"]
                                      for row in section["chunks"]], list(range(1, 11)))
                    self.assertNotIn("prepared_answer", final_input)
                    self.assertNotIn("allowed_actions", final_input)
                    self.assertFalse(any(step.get("phase") == "prepared_final_decision"
                                         for step in r["result"]["action_steps"]))
                else:
                    actual_input = json.loads(json.loads(self.requests[-1].content)["messages"][-1]["content"])
                    self.assertEqual(actual_input["allowed_citation_ids"], context["allowed_citation_ids"])
                visible = ([row for group in actual_input["evidence_sections"] for row in group["chunks"]]
                           if mode == "agent" else actual_input["shown_evidence"])
                self.assertEqual(len(visible), 10)
                if mode == "agent":
                    self.assertEqual(text_count(final_messages, children[-1]["text"]), 1)
                    self.assertEqual(actual_input["evidence_sections"][0]["section_path"], parent["section_path"])
                    self.assertNotIn("context_budget", actual_input)
                else:
                    self.assertEqual(actual_input["context_budget"]["max_tokens"], 8192)
                json_bytes, markdown_bytes = runtime.download_payloads(r, project_root=self.root)
                downloaded = json.loads(json_bytes)
                if mode == "agent":
                    self.assertEqual(downloaded["answer"]["text"],
                                     "The recovered mechanism continues across both pages. [ID:10]")
                    self.assertEqual(downloaded["answer"]["citations"], r["answer"]["citations"])
                    self.assertEqual(downloaded["answer"]["evidence_sources"], r["answer"]["evidence_sources"])
                    self.assertNotIn("claims", downloaded["answer"])
                else:
                    self.assertEqual(downloaded["answer"]["direct_answer"], action["answer"]["direct_answer"])
                    self.assertEqual(downloaded["answer"]["evidence_sources"], r["answer"]["evidence_sources"])
                    self.assertEqual(downloaded["answer"]["claims"][0]["evidence_quotes"], [quote])
                saved = json.loads((self.root / r["history_report"]).read_text(encoding="utf-8"))
                if mode == "agent":
                    self.assertEqual(saved["answer"]["text"], r["answer"]["text"])
                else:
                    self.assertEqual(saved["answer"]["claims"][0]["evidence_quotes"], [quote])
                markdown = markdown_bytes.decode("utf-8")
                if mode == "agent":
                    self.assertIn("The recovered mechanism continues across both pages. [ID:10]", markdown)
                    self.assertNotIn("本项原文短引句", markdown)
                else:
                    self.assertIn("本项原文短引句", markdown)
                    self.assertIn(quote["quote"], markdown)
                self.assertIn(parent_id, markdown)
                self.assertIn('"source_spans"', markdown)
                self.assertIn('"coordinate_system": "normalized"', markdown)
                self.assertIn('"pdf_page": 2', markdown)
                self.assertIn("data/papers/structured-region.png", markdown)
                for span in children[-1]["source_spans"]:
                    self.assertIn(span["block_id"], markdown)

        # The actual directory exposes saved tables next to body sections.
        # Search returns only body anchors; the mock chooses the table parent,
        # and the native read supplies its real header and row.
        with self.subTest(structured_table="agent"):
            self.store = PaperStore(database, read_only=True)
            self.addCleanup(self.store.close)
            Registry(self.root, self.store, pairs)
            table_question = "What absolute F1 did BERT report in the recovered results?"
            table_preparation = {"standalone_question": table_question, "clarification_question": None,
                                 "referenced_evidence_ids": [], "planned_queries": []}
            table_action = answer_action(table_children[-1]["chunk_id"])
            table_action["answer"]["direct_answer"] = "BERT reported F1 0.93."
            table_action["answer"]["claims"][0]["claim"] = "BERT reported detection F1 0.93."
            table_action["answer"]["claims"][0]["evidence_quotes"] = [
                {"chunk_id": table_children[-1]["chunk_id"], "quote": table_rows[-1]}]
            tool = check_agent.tool_response({})[1]
            tool["choices"][0]["message"]["tool_calls"][0]["function"] = {
                "name": "read_context", "arguments": json.dumps({"parent_id": table_parent_id})}
            outcomes = [response(table_preparation), (200, tool),
                        response("BERT reported detection F1 0.93. [ID:2]")]
            with patch.object(runtime.web_runtime, "_ready_versions",
                              return_value=[{**versions[0], "title": paper["title"]}]):
                r = self.invoke("agent", token="agent-table-directory", query=table_question, pairs=pairs,
                                rows=anchors, library_mode=True, outcomes=outcomes)
            self.assertEqual(r["status"], "answered", (r.get("error"), r["result"].get("failure_stage")))
            decision = json.loads(self.requests[1].content)
            decision_payload = json.loads(decision["messages"][1]["content"])
            directory = decision_payload["selected_papers"][0]["reading_directory"]
            self.assertIn(parent_id, [entry["parent_id"] for entry in directory])
            table_entry = next(entry for entry in directory if entry["parent_id"] == table_parent_id)
            self.assertEqual(table_entry["content_type"], "table")
            self.assertEqual(table_entry["caption"], table_caption)
            self.assertEqual(table_entry["pdf_pages"], [2])
            self.assertEqual(table_entry["section_path"], ["Results", "Recovered measurements"])
            self.assertNotIn(table_rows[-1], json.dumps(decision_payload, ensure_ascii=False))
            self.assertFalse(any(row.get("content_type") == "table"
                                 for group in decision_payload["evidence_sections"] for row in group["chunks"]))
            reads = r["result"]["context_reads"]
            self.assertEqual(len(reads), 1)
            self.assertEqual(reads[0]["status"], "success")
            self.assertEqual(reads[0]["returned_ids"], [child["chunk_id"] for child in table_children])
            self.assertEqual(reads[0]["section_path"], table_parent["section_path"])
            visible = {row["chunk_id"]: row["shown_text"] for row in reads[0]["visible_chunks"]}
            self.assertIn(table_rows[0], visible[table_children[0]["chunk_id"]])
            self.assertIn(table_rows[1], visible[table_children[1]["chunk_id"]])
            context = r["result"]["context"]
            self.assertIn(table_children[-1]["chunk_id"], context["allowed_citation_ids"])
            self.assertNotIn(table_parent_id, context["allowed_citation_ids"])
            final_messages = json.loads(self.requests[2].content)["messages"]
            final_input = json.loads(final_messages[-1]["content"])
            self.assertEqual(final_input["allowed_refs"], [1, 2])
            self.assertEqual([row["chunk_id"] for section in final_input["evidence_sections"]
                              for row in section["chunks"]][-1], table_children[-1]["chunk_id"])
            self.assertNotIn("allowed_actions", final_input)
            self.assertEqual(text_count(final_messages, table_children[-1]["text"]), 1)
            self.assertEqual(r["answer"]["text"], "BERT reported detection F1 0.93. [ID:2]")
            self.assertEqual(r["answer"]["citations"][0]["chunk_id"], table_children[-1]["chunk_id"])
            self.assertEqual(r["answer"]["evidence_refs"][0]["chunk_id"], table_children[-1]["chunk_id"])
            self.assertEqual(r["answer"]["evidence_sources"][0]["text"], table_children[-1]["text"])
            self.assertTrue(r["answer"]["evidence_sources"][0]["reading_origins"][0]["parent_id"] == table_parent_id)

        # Real 8192-token selection omits a returned target. The only new
        # operation is a local anchored read; no wider retrieval or paid client.
        from paper_assistant.context import select_context
        large_children = deepcopy(children)
        for index, child in enumerate(large_children):
            child["parent_id"] = parent_id + "_isolated_" + str(index)
        background, target, oversize = large_children[0], large_children[-1], large_children[-2]
        for repeat in range(1000, 2300, 50):
            background["text"] = "Earlier background observation. " * repeat
            background["text_sha256"] = sha256_bytes(background["text"].encode())
            trial_rows = [{**deepcopy(row), "rank": rank, "score": 0.8} for rank, row in enumerate((background, target), 1)]
            trial = select_context(trial_rows, pairs, max_tokens=8192)
            if trial["allowed_citation_ids"] == [background["chunk_id"]] and any(
                    row["chunk_id"] == target["chunk_id"] and row["reason"] == "token_budget" for row in trial["omitted_evidence"]):
                break
        else:
            self.fail("Fixture must actually omit its second returned chunk under 8192 tokens")
        oversize["text"] = "This complete original cannot fit the reading window. " * 4000
        oversize["text_sha256"] = sha256_bytes(oversize["text"].encode())
        large_parents = [{**deepcopy(parent), "parent_id": child["parent_id"], "text": child["text"],
                          "child_ids": [child["chunk_id"]], "source_spans": deepcopy(child["source_spans"])} for child in large_children]
        large_manifest = deepcopy(manifest)
        large_manifest["statistics"]["parent_count"] = len(large_parents)
        large_database = self.root / "data/index/anchored-runtime.sqlite3"
        with PaperStore(large_database) as store:
            store.import_version(replace(_bundle(paper, large_manifest, large_children), parents=large_parents))
        rows = [{**deepcopy(row), "rank": rank, "score": 0.8} for rank, row in enumerate((background, target, oversize), 1)]
        search = {"query": "Find the requested mechanism condition", "selected_versions": versions,
                  "missing_information": "The requested original condition"}
        from paper_assistant.agent_prompt import NORMAL_ANSWER_INSTRUCTION
        from paper_assistant.context import prepare_context
        from paper_assistant.fixed_evidence import run_two_stage
        search = self.fixture.search([self.fixture.abstract_id, self.fixture.body_id])
        fixed_context = prepare_context(search)
        sections = [{"paper_id": self.fixture.paper_id,
                     "parse_revision": self.fixture.parse_revision,
                     "title": "Offline structural fixture",
                     "section_path": shown.get("section_path") or ["Body"],
                     "chunks": [{key: deepcopy(shown[key]) for key in
                         ("chunk_id", "pdf_page", "rank", "score", "parent_id", "shown_text",
                          "source_spans", "reading_origins") if key in shown}]}
                    for shown in fixed_context["shown_evidence"]]
        conversation = {"user_question": self.fixture.question,
                        "standalone_question": self.fixture.question, "history": [],
                        "answer_instructions": NORMAL_ANSWER_INSTRUCTION}
        fixed_material = {
            "question": self.fixture.question, "pair": (self.fixture.paper_id, self.fixture.parse_revision),
            "selected_versions": [{"paper_id": self.fixture.paper_id, "parse_revision": self.fixture.parse_revision}],
            "evidence_sections": sections, "allowed_citation_ids": fixed_context["allowed_citation_ids"],
            "selected_papers": [{"paper_id": self.fixture.paper_id, "parse_revision": self.fixture.parse_revision,
                                 "title": "Offline structural fixture"}],
            "context": fixed_context, "context_budget": {"max_tokens": 8192, "shown_tokens": 20,
                "tokenizer": "offline"}, "conversation_context": conversation, "source_requirement": None}
        from scripts.check_rag import FakeStore
        fixed_store = FakeStore({identifier: {
            **deepcopy(self.fixture.chunks[identifier]), "title": "Offline structural fixture",
            "arxiv_version": "v1", "source_url": "https://example.invalid/paper",
            "local_path": "data/papers/fixture.pdf"}
            for identifier in (self.fixture.abstract_id, self.fixture.body_id)})
        fixed_budget = ChatBudget(runtime.INTERACTIVE_CHAT_POLICY, clock=self.clock)
        fixed_client, fixed_requests = self.client(
            response(prepare_action(answer_action(self.fixture.abstract_id))),
            response(answer_action(self.fixture.body_id)), budget=fixed_budget)
        fixed = run_two_stage(fixed_material, fixed_client, fixed_store, project_root=self.root)
        self.assertEqual(fixed["status"], "answered", fixed.get("error"))
        self.assertEqual(len(fixed_requests), 2)
        self.assertEqual(fixed["statistics"]["chat"]["sdk_request_attempts"], 2)
        self.assertEqual(fixed["prepared_answer"]["facts"][0]["claim"],
                         answer_action(self.fixture.abstract_id)["answer"]["claims"][0]["claim"])
        self.assertEqual(fixed["answer"]["evidence_refs"][0]["chunk_id"], self.fixture.body_id)
        self.assertEqual(fixed["answer"]["evidence_sources"][0]["text"],
                         self.fixture.chunks[self.fixture.body_id]["text"])
        for number, request in enumerate(fixed_requests):
            sent = json.loads(request.content)
            self.assertNotIn("tools", sent)
            self.assertNotIn("direct_answer", sent["messages"][0]["content"])
            self.assertNotIn("Unanswerable", sent["messages"][0]["content"])
            if number == 0:
                self.assertIn("fixed for this run", sent["messages"][0]["content"])
                self.assertEqual(json.loads(sent["messages"][1]["content"])["allowed_actions"], ["prepare_answer"])
            else:
                self.assertEqual([m["role"] for m in sent["messages"]],
                                 ["system", "user", "assistant", "user"])
                prepare_payload = json.loads(sent["messages"][1]["content"])
                self.assertEqual(prepare_payload["allowed_actions"], ["prepare_answer"])
                self.assertNotIn("read_context", prepare_payload.get("allowed_actions", []))
                self.assertIn("evidence_sections", prepare_payload)
                self.assertEqual(json.loads(sent["messages"][2]["content"])["action"], "prepare_answer")
                final_payload = json.loads(sent["messages"][-1]["content"])
                self.assertEqual(final_payload["phase"], "prepared_final_decision")
                self.assertEqual(final_payload["allowed_actions"], ["answer"])
                self.assertEqual(final_payload["allowed_citation_ids"],
                                 fixed_context["allowed_citation_ids"])
                self.assertNotIn("prepared_answer", final_payload)
                self.assertIn("the originals govern", sent["messages"][0]["content"])
                self.assertNotIn("direct_answer",
                                 final_payload["action_contracts"]["answer"]["shape"]["answer"])
                self.assertEqual(text_count(sent["messages"], self.fixture.chunks[self.fixture.abstract_id]["text"]), 1)
                self.assertEqual(text_count(sent["messages"], self.fixture.chunks[self.fixture.body_id]["text"]), 1)
        from paper_assistant.agent_export import render_agent_run
        markdown = render_agent_run({"task": "D9", "mode": "agent", "run_id": "fixed-offline",
            "result": fixed, "policy": {}, "configuration": {}, "index_profile": {},
            "strategy_binding": {}, "history_report": "offline"})
        self.assertIn("固定证据两阶段", markdown)
        self.assertIn("事实准备", markdown)
        self.assertIn("独立最终生成", markdown)

    def test_original_query_and_complete_pairs_preserved(self):
        from dataclasses import replace
        self.settings = replace(self.settings, context_length=1048576)

        def text_count(messages, text):
            return sum((message.get("content") or "").count(text) for message in messages)

        query = "  摘要中提到了什么？\n "
        r = self.invoke(query=query)
        self.assertEqual(r["query"], query)
        self.assertEqual(r["selected_versions"], [{"paper_id": self.fixture.paper_id, "parse_revision": self.fixture.parse_revision}])
        self.assertEqual(self.searcher.calls[0]["query"], query)
        message = json.loads(self.requests[0].content)["messages"][-1]["content"]
        self.assertIn(query, json.loads(message)["question"])
        self.assertNotIn("DO_NOT_SEND_EXPECTED", message)
        legacy_report = deepcopy(r)
        for key in ("conversation_id", "conversation_history", "user_question", "standalone_question", "clarification_question"):
            legacy_report.pop(key, None)
        _, legacy_markdown = runtime.download_payloads(legacy_report, project_root=self.root)
        self.assertIn(query, legacy_markdown.decode("utf-8"))
        self.assertNotIn("本轮完整问题：", legacy_markdown.decode("utf-8"))

        history = [{"turn": 1, "status": "answered", "user_question": "论文方法是什么？",
                    "standalone_question": "论文方法是什么？", "claims": [
                        {"claim": "方法一与方法二需要分别讨论。", "basis": "paper_evidence",
                         "citation_ids": [self.fixture.body_id]}]}]
        followup = "它的摘要怎么说？"
        standalone = self.fixture.question
        for mode in runtime.MODES:
            with self.subTest(mode=mode):
                action = answer_action(self.fixture.abstract_id)
                answer_response = response(action["answer"] if mode == "fixed_rag" else action)
                prepared = {"standalone_question": standalone, "clarification_question": None,
                            "referenced_evidence_ids": []}
                r = self.invoke(mode, token=mode + "-followup", query=followup,
                    conversation_id="current-conversation", conversation_history=history,
                    outcomes=[response(prepared), answer_response])
                self.assertEqual(r["status"], "answered")
                self.assertEqual(r["user_question"], followup)
                self.assertEqual(r["standalone_question"], standalone)
                self.assertEqual(r["query"], standalone)
                self.assertEqual(r["conversation_history"], history)
                self.assertEqual(r["conversation_id"], "current-conversation")
                self.assertEqual(self.searcher.calls[0]["query"], standalone)
                self.assertEqual(r["result"]["context"]["question"], standalone)
                self.assertEqual(r["result"]["source_requirement"]["required_scope"], "abstract")
                self.assertEqual(r["llm_requests"], 2)
                payload = json.loads(json.loads(self.requests[1].content)["messages"][-1]["content"])
                self.assertEqual(payload["conversation_context"]["user_question"], followup)
                self.assertEqual(payload["conversation_context"]["history"], history)
                self.assertNotIn(self.fixture.body_id, payload["allowed_citation_ids"])
                request_count = len(self.requests)
                json_bytes, markdown_bytes = runtime.download_payloads(r, project_root=self.root)
                downloaded = json.loads(json_bytes)
                for key in ("conversation_id", "user_question", "standalone_question", "conversation_history", "answer"):
                    self.assertEqual(downloaded[key], r[key])
                markdown = markdown_bytes.decode("utf-8")
                self.assertIn("用户原问题：", markdown)
                self.assertIn(followup, markdown)
                self.assertIn("本轮完整问题：", markdown)
                self.assertIn(standalone, markdown)
                self.assertIn("current-conversation", markdown)
                self.assertIn("本轮使用的近期历史：", markdown)
                self.assertIn(self.fixture.paper_id, markdown)
                self.assertIn(self.fixture.parse_revision, markdown)
                self.assertIn(r["answer"]["evidence_sources"][0]["text"], markdown)
                self.assertEqual(len(self.requests), request_count)
                self.assertEqual((self.root / r["history_markdown"]).read_text(encoding="utf-8"), markdown)
                saved_json = json.loads((self.root / r["history_report"]).read_text(encoding="utf-8"))
                self.assertEqual(saved_json["user_question"], followup)
                self.assertEqual(saved_json["standalone_question"], standalone)
                first_followup = deepcopy(r)

                clarification = "你指的是方法一还是方法二？"
                r = self.invoke(mode, token=mode + "-clarification-fallback", query="它怎样停止？",
                    conversation_id="current-conversation", conversation_history=history,
                    outcomes=[response({"standalone_question": None,
                        "clarification_question": clarification, "referenced_evidence_ids": []}),
                        answer_response])
                self.assertEqual(r["status"], "answered", r.get("error"))
                self.assertEqual(r["user_question"], "它怎样停止？")
                self.assertEqual(r["standalone_question"], "它怎样停止？")
                self.assertEqual(r["query"], "它怎样停止？")
                self.assertEqual(self.searcher.calls[0]["query"], "它怎样停止？")
                self.assertEqual(r["result"]["context"]["question"], "它怎样停止？")
                self.assertEqual(r["llm_requests"], 2)
                self.assertEqual(r["export"]["status"], "completed")
                json_bytes, markdown_bytes = runtime.download_payloads(r, project_root=self.root)
                downloaded = json.loads(json_bytes)
                self.assertEqual(downloaded["status"], "answered")
                self.assertEqual(downloaded["standalone_question"], "它怎样停止？")
                self.assertIn("它怎样停止？", markdown_bytes.decode("utf-8"))

                clarified_history = [*history, {"turn": 2, "status": "needs_clarification",
                    "user_question": "它怎样停止？", "standalone_question": None,
                    "clarification_question": clarification}]
                r = self.invoke(mode, token=mode + "-old-clarification-history", query="方法一",
                    conversation_id="current-conversation", conversation_history=clarified_history,
                    outcomes=[response(prepared), answer_response])
                self.assertEqual(r["status"], "answered", r.get("error"))
                self.assertEqual(r["user_question"], "方法一")
                self.assertEqual(r["standalone_question"], standalone)
                preparation_payload = json.loads(json.loads(self.requests[0].content)["messages"][-1]["content"])
                self.assertEqual(preparation_payload["history"][-1]["clarification_question"], clarification)
                json_bytes, markdown_bytes = runtime.download_payloads(first_followup, project_root=self.root)
                self.assertEqual(json.loads(json_bytes)["user_question"], followup)
                self.assertEqual(json.loads(json_bytes)["answer"], first_followup["answer"])
                self.assertIn(followup, markdown_bytes.decode("utf-8"))

        restored_question = "解释上一轮正文结论所引用的原文。"
        r = self.invoke(token="fixed-old-evidence", query="这条结论的原文是什么意思？",
            conversation_id="current-conversation", conversation_history=history,
            outcomes=[response({"standalone_question": restored_question, "clarification_question": None,
                                "referenced_evidence_ids": [self.fixture.body_id]}),
                      response(answer_action(self.fixture.body_id)["answer"])])
        self.assertEqual(r["status"], "answered")
        self.assertIn(self.fixture.body_id, r["result"]["context"]["allowed_citation_ids"])
        self.assertEqual(r["answer"]["evidence_sources"][0]["text"], self.fixture.chunks[self.fixture.body_id]["text"])

        r = self.invoke(token="invalid-followup", query=followup, conversation_history=history,
            outcomes=[response("not JSON")])
        self.assertEqual(r["status"], "invalid_output")
        self.assertEqual(r["failure_stage"], "conversation_preparation")
        self.assertEqual(r["llm_requests"], 1)
        self.assertEqual(self.searcher.calls, [])
        self.assertIsNone(r["standalone_question"])
        _, markdown_bytes = runtime.download_payloads(r, project_root=self.root)
        self.assertIn("本轮未形成完整问题。", markdown_bytes.decode("utf-8"))

        # Page Agent decisions choose actual searches; preparation is advisory.
        versions = [{"paper_id": self.fixture.paper_id, "parse_revision": self.fixture.parse_revision}]
        ready = [{**versions[0], "title": "Offline structural fixture"}]

        def search_action(query):
            return {"action": "search", "query": query, "selected_versions": versions,
                    "missing_information": "Find the requested paper fact."}

        output_rules = "Answer in English and provide direct_answer with explanatory claims."
        long_question = ("Compare the proposed and baseline procedures under the stated held-out setting. " * 20
                         + "What data selection condition and result are reported?")
        with patch.object(runtime.web_runtime, "_ready_versions", return_value=ready):
            for name, question, plans, actual_queries in (
                    ("translated", "这篇论文如何比较两种压缩方法？", [
                        {"query": "compression comparison evaluation procedure", "selected_versions": versions}],
                        ["compression comparison evaluation procedure"]),
                    ("generic", "这篇论文主要做了什么？", [
                        {"query": "Offline structural fixture research goal and contribution", "selected_versions": versions}],
                        ["Offline structural fixture research goal and contribution"]),
                    ("long", long_question, [
                        {"query": "proposed baseline held-out data selection condition and result", "selected_versions": versions}],
                        ["proposed baseline held-out data selection condition and result"]),
                    ("simple", "What problem does this paper address?", [
                        {"query": "Offline structural fixture research problem", "selected_versions": versions}],
                        ["Offline structural fixture research problem"]),
                    ("overview", "Explain the research problem and the core mechanism.", [
                        {"query": "Offline structural fixture research problem", "selected_versions": versions},
                        {"query": "Offline structural fixture reasoning and action mechanism", "selected_versions": versions}],
                        ["Offline structural fixture combined reasoning and action",
                         "Offline structural fixture mechanism observations"])):
                with self.subTest(planning=name):
                    rows = self.fixture.search([self.fixture.abstract_id])["results"]
                    expanded = question + " Also add a different comparison."
                    r = self.invoke("agent", token="planning-" + name, query=question, library_mode=True,
                        search_outcomes=[rows for _ in actual_queries], hybrid=True, rerank=True,
                        answer_instructions=output_rules,
                        outcomes=[response({"standalone_question": expanded, "clarification_question": None,
                            "referenced_evidence_ids": [], "planned_queries": plans}),
                            *[check_agent.tool_response(search_action(text)) for text in actual_queries],
                            response(prepare_action(answer_action(self.fixture.abstract_id))), response(answer_action(self.fixture.abstract_id))])
                    self.assertEqual(r["status"], "answered", r.get("error"))
                    self.assertEqual(r["planned_queries"], plans)
                    self.assertEqual(r["standalone_question"], question)
                    self.assertEqual(r["user_question"], question)
                    prepared_response = json.loads(r["conversation_preparation"]["response"]["content"])
                    self.assertEqual(prepared_response["standalone_question"], expanded)
                    self.assertEqual(r["result"]["query"], question)
                    self.assertNotIn(output_rules, json.dumps(r["conversation_preparation"]["messages"], ensure_ascii=False))
                    if name == "long":
                        self.assertGreater(len(question), 1000)
                        self.assertLess(len(actual_queries[0]), 1000)
                    self.assertEqual([call["query"] for call in self.searcher.calls], actual_queries)
                    self.assertTrue(all(call["selected_versions"] == self.fixture.pairs for call in self.searcher.calls))
                    self.assertTrue(all(row["kind"] == "adaptive" and row["top_k"] == 5
                                        for row in r["result"]["search_rounds"]))
                    self.assertEqual(r["result"]["retrieval_strategy"], "autonomous")
                    self.assertEqual(r["result"]["autonomous_step_limit"], 5)
                    self.assertEqual(r["result"]["autonomous_steps_used"], len(actual_queries) + 1)
                    self.assertFalse(r["result"]["limit_finalize"])
                    self.assertEqual(r["stop_reason"], "answered")
                    self.assertEqual(r["embedding_requests"], len(actual_queries))
                    self.assertEqual(r["rerank_requests"], len(actual_queries))
                    self.assertEqual(len(self.rerank_requests), len(actual_queries))
                    self.assertEqual(r["network_requests"], 3 + 3 * len(actual_queries))
                    self.assertIsNone(r["result"]["retry_decision"])
                    self.assertEqual(r["result"]["action_steps"][0]["phase"], "autonomous_decision")
                    self.assertEqual(r["llm_requests"], 3 + len(actual_queries))
                    self.assertEqual(self.budget.repairs, 0)
                    preparation = json.loads(json.loads(self.requests[0].content)["messages"][-1]["content"])
                    self.assertEqual(preparation["selected_versions"], versions)
                    self.assertEqual(preparation["selected_papers"][0]["title"], ready[0]["title"])
                    self.assertEqual(preparation["selected_papers"][0]["abstract_passages"][0]["chunk_id"],
                                     self.fixture.abstract_id)
                    first = json.loads(json.loads(self.requests[1].content)["messages"][-1]["content"])
                    self.assertEqual(first["allowed_citation_ids"], [])
                    self.assertCountEqual(first["allowed_actions"], ["search", "read_context", "answer", "prepare_answer"])
                    self.assertEqual(first["planned_queries"], plans)
                    self.assertEqual(first["executed_actions"], [])
                    final = json.loads(json.loads(self.requests[-2].content)["messages"][-1]["content"])
                    self.assertEqual(final["question"], question)
                    self.assertEqual(final["conversation_context"]["answer_instructions"], output_rules)
                    for index, step in enumerate(final["executed_actions"]):
                        call = step["tool_calls"][0]
                        self.assertEqual(call["parsed_action"]["query"], actual_queries[index])
                        self.assertEqual(call["parsed_action"]["missing_information"], "Find the requested paper fact.")
                    native = [m for m in json.loads(self.requests[-2].content)["messages"] if m["role"] == "assistant" and m.get("tool_calls")]
                    self.assertEqual(len(native), len(actual_queries))
                    self.assertTrue(all(json.loads(m["tool_calls"][0]["function"]["arguments"])["missing_information"]
                                        == "Find the requested paper fact." for m in native))
                    self.assertEqual(final["conversation_context"]["planned_queries"], plans)
                    self.assertEqual(len(final["executed_actions"]), len(actual_queries))
                    saved = json.loads((self.root / r["history_report"]).read_text(encoding="utf-8"))
                    self.assertEqual(saved["planned_queries"], plans)
                    downloaded, markdown = runtime.download_payloads(r, project_root=self.root)
                    self.assertEqual(json.loads(downloaded)["planned_queries"], plans)
                    self.assertEqual(json.loads(downloaded)["result"]["search_rounds"], r["result"]["search_rounds"])
                    self.assertEqual(json.loads(downloaded)["chat_statistics"], r["chat_statistics"])
                    self.assertEqual(saved["result"]["action_steps"], r["result"]["action_steps"])
                    for text in actual_queries:
                        self.assertIn(text, markdown.decode("utf-8"))
                    self.assertNotIn("### 补查", markdown.decode("utf-8"))

            # Full-question source restrictions apply even when a child query
            # omits the section name and the model forgets it in the rewrite.
            scoped_question = "仅根据摘要中内容，说明研究问题和机制。"
            completed = "Offline structural fixture 的研究问题和机制是什么？"
            plans = [{"query": "Offline structural fixture research problem", "selected_versions": versions},
                     {"query": "Offline structural fixture reasoning mechanism", "selected_versions": versions}]
            abstract_history = [{**history[0], "claims": [{"claim": "Previously cited abstract.",
                "basis": "paper_evidence", "citation_ids": [self.fixture.abstract_id]}]}]
            r = self.invoke("agent", token="planning-abstract-followup", query=scoped_question,
                library_mode=True, conversation_history=abstract_history,
                search_outcomes=[self.fixture.search([self.fixture.body_id, self.fixture.abstract_id])["results"], []],
                outcomes=[response({"standalone_question": completed, "clarification_question": None,
                    "referenced_evidence_ids": [self.fixture.abstract_id], "planned_queries": plans}),
                    *[check_agent.tool_response(search_action(plan["query"])) for plan in plans],
                    response(prepare_action(answer_action(self.fixture.abstract_id))), response(answer_action(self.fixture.abstract_id))])
            self.assertEqual(r["status"], "answered")
            self.assertEqual(r["planned_queries"], plans)
            self.assertEqual(r["result"]["source_requirement"]["required_scope"], "abstract")
            final = json.loads(json.loads(self.requests[-2].content)["messages"][-1]["content"])
            self.assertEqual(final["conversation_context"]["source_requirement"]["required_scope"], "abstract")
            self.assertEqual(final["conversation_context"]["history"], abstract_history)
            self.assertNotIn(self.fixture.body_id, final["allowed_citation_ids"])
            self.assertEqual(final["allowed_citation_ids"][0], self.fixture.abstract_id)
            self.assertEqual(r["result"]["context"]["question"], completed + "\n仅根据摘要中内容。")
            self.assertEqual([call["query"] for call in self.searcher.calls], [plan["query"] for plan in plans])
            self.assertTrue(all(self.fixture.body_id not in json.loads(json.loads(request.content)["messages"][-1]["content"])
                                ["allowed_citation_ids"] for request in self.requests[1:]))
            self.assertTrue(all(row["observation"] for row in r["result"]["search_rounds"]))
            self.assertEqual(r["result"]["autonomous_steps_used"], 3)
            self.assertEqual(r["llm_requests"], 5)

            failed_stats = {"embedding_requests": 1, "failed_requests": 1, "total_tokens": None}
            error = check_agent.SearchError("simulated failure", stage="embedding", statistics=failed_stats)
            r = self.invoke("agent", token="planning-partial-failure", query=completed, library_mode=True,
                search_outcomes=[error, self.fixture.search([self.fixture.abstract_id])["results"]],
                outcomes=[response({"standalone_question": completed, "clarification_question": None,
                    "referenced_evidence_ids": [], "planned_queries": plans}),
                    *[check_agent.tool_response(search_action(plan["query"])) for plan in plans],
                    response(prepare_action(answer_action(self.fixture.abstract_id))), response(answer_action(self.fixture.abstract_id))])
            self.assertEqual(r["status"], "answered")
            self.assertEqual(r["embedding_requests"], 2)
            self.assertEqual(r["embedding_statistics"]["failed_requests"], 1)
            self.assertIsNone(r["embedding_statistics"]["total_tokens"])
            self.assertEqual(r["result"]["search_rounds"][0]["statistics"], failed_stats)
            self.assertEqual(r["result"]["merge_trace"]["rounds"][0]["query_index"], 2)
            self.assertEqual(r["answer"]["evidence_sources"][0]["chunk_id"], self.fixture.abstract_id)
            downloaded, markdown = runtime.download_payloads(r, project_root=self.root)
            self.assertEqual(json.loads(downloaded)["result"]["search_rounds"][0]["error"]["code"], "search_error")
            self.assertIn('"code": "search_error"', markdown.decode("utf-8"))

            for name, plans in (("missing", None), ("empty", []), ("blank-query", [{"query": " ", "selected_versions": versions}]),
                                ("unselected", [{"query": "some other paper", "selected_versions": [
                                    {"paper_id": "unselected", "parse_revision": "r1"}]}])):
                prepared = {"standalone_question": completed, "clarification_question": None, "referenced_evidence_ids": []}
                if plans is not None:
                    prepared["planned_queries"] = plans
                general = {"action": "answer", "answer": {"status": "answered", "claims": [{
                    "claim": "A mechanism explanation can separate the problem, steps and outcomes.",
                    "basis": "model_knowledge", "citation_ids": []}]}}
                r = self.invoke("agent", token="planning-fallback-" + name, query=completed, library_mode=True,
                    outcomes=[response(prepared), response(general)])
                self.assertEqual(r["status"], "answered")
                self.assertEqual(r["planned_queries"], [{"query": completed, "selected_versions": versions}])
                self.assertEqual(r["llm_requests"], 2)
                self.assertEqual(self.searcher.calls, [])
                self.assertEqual(r["result"]["autonomous_steps_used"], 1)
                self.assertEqual(self.budget.repairs, 0)

            r = self.invoke("agent", token="planning-first-original", query="  Only the requested fact?\n ", library_mode=True,
                outcomes=[response({"clarification_question": None, "planned_queries": plans}), response(general)])
            self.assertEqual(r["standalone_question"], "  Only the requested fact?\n ")
            self.assertEqual(r["result"]["query"], "  Only the requested fact?\n ")
            self.assertEqual(r["llm_requests"], 2)
            self.assertEqual(self.searcher.calls, [])

            r = self.invoke("agent", token="planning-first-no-clarification", query="它呢？", library_mode=True,
                outcomes=[response({"standalone_question": None, "clarification_question": "你指哪一个方法？",
                    "referenced_evidence_ids": [self.fixture.body_id], "planned_queries": plans}),
                    response(general)])
            self.assertEqual(r["status"], "answered", r.get("error"))
            self.assertEqual(r["standalone_question"], "它呢？")
            self.assertEqual(r["result"]["query"], "它呢？")
            self.assertEqual(r["llm_requests"], 2)
            self.assertEqual(self.searcher.calls, [])

            r = self.invoke("agent", token="planning-first-invalid", query="它呢？", library_mode=True,
                outcomes=[response("not JSON")])
            self.assertEqual(r["status"], "invalid_output")
            self.assertEqual(r["failure_stage"], "conversation_preparation")
            self.assertIsNone(r["standalone_question"])
            self.assertEqual(self.searcher.calls, [])
            self.assertEqual(r["llm_requests"], 1)

            # A preparation gap is a real routing decision, not a final-answer review.
            final_action = answer_action(self.fixture.abstract_id)
            final_action["answer"]["claims"][0]["evidence_quotes"] = [{
                "chunk_id": self.fixture.abstract_id,
                "quote": self.fixture.chunks[self.fixture.abstract_id]["text"][:100]}]
            first_prep = {"action": "prepare_answer", "facts": [], "answerable": False,
                          "missing_information": "The requested source and filtering condition remain absent."}
            conversation = response({"clarification_question": None, "planned_queries": []})

            performance_question = "What is the performance of BERT on the task?"
            performance = self.invoke("agent", token="planning-performance-normal", query=performance_question,
                library_mode=True, rows=self.fixture.search([self.fixture.abstract_id])["results"],
                outcomes=[conversation, check_agent.tool_response(search_action("BERT performance")),
                    response(prepare_action(final_action)), response(final_action)])
            self.assertEqual(performance["status"], "answered", performance.get("error"))
            self.assertEqual(performance["user_question"], performance_question)
            self.assertEqual(performance["standalone_question"], performance_question)
            self.assertEqual(self.searcher.calls[0]["query"], "BERT performance")
            self.assertEqual([step["phase"] for step in performance["result"]["action_steps"]],
                             ["autonomous_decision", "autonomous_decision", "prepared_final_decision"])
            self.assertEqual(performance["embedding_requests"], 1)
            self.assertEqual(performance["llm_requests"], 4)

            r = self.invoke("agent", token="prepare-gap-search", library_mode=True,
                search_outcomes=[[], self.fixture.search([self.fixture.abstract_id])["results"]],
                outcomes=[conversation, check_agent.tool_response(search_action("initial topic")),
                    response(first_prep), check_agent.tool_response(search_action("source filtering condition")),
                    response(prepare_action(final_action)), response(final_action)])
            self.assertEqual(r["status"], "answered", r.get("error"))
            self.assertEqual(r["llm_requests"], 6)
            self.assertEqual(r["result"]["autonomous_steps_used"], 4)
            self.assertEqual(r["result"]["evidence_calls_used"], 2)
            next_decision = json.loads(json.loads(self.requests[3].content)["messages"][-1]["content"])
            self.assertEqual(next_decision["executed_actions"][-1]["parsed_action"], first_prep)
            self.assertEqual(next_decision["remaining_evidence_calls"], 4)
            gap_search_final = json.loads(self.requests[-1].content)["messages"]
            self.assertEqual(json.loads(gap_search_final[-2]["content"])["facts"][0]["evidence_quotes"],
                             final_action["answer"]["claims"][0]["evidence_quotes"])
            self.assertEqual(json.loads(gap_search_final[-1]["content"])["allowed_citation_ids"],
                             r["result"]["context"]["allowed_citation_ids"])

            gap_answer = {"action": "answer", "answer": {"status": "answered", "direct_answer": "Unanswerable",
                "claims": [{"claim": first_prep["missing_information"], "basis": "analysis", "citation_ids": []}]}}
            # Five tool calls share the existing cap, then a counted preparation
            # and one final generation complete a specific gap without new tools.
            r = self.invoke("agent", token="prepare-gap-cap", library_mode=True,
                search_outcomes=[[]] * 5,
                outcomes=[conversation, check_agent.tool_response(*[search_action("gap " + str(i)) for i in range(5)]),
                    response(first_prep), response(gap_answer)])
            self.assertEqual(r["status"], "answered", r.get("error"))
            self.assertEqual(r["result"]["evidence_calls_used"], 5)
            self.assertEqual(r["result"]["autonomous_steps_used"], 2)
            self.assertTrue(r["result"]["limit_finalize"])
            self.assertEqual(r["answer"]["direct_answer"], "Unanswerable")
            self.assertEqual(r["llm_requests"], 4)
            self.assertNotIn("tools", json.loads(self.requests[-2].content))
            self.assertNotIn("tools", json.loads(self.requests[-1].content))

            no_direction = {"action": "insufficient_evidence",
                "reason": "The scoped tools have no returned unread candidates or accessible passages identifying this fact, and the available searches provide no reliable new lead."}
            # Only an explicit no-direction decision consumes the saved fact package.
            r = self.invoke("agent", token="prepare-gap-no-direction", library_mode=True,
                outcomes=[conversation, response(first_prep), response(no_direction), response(gap_answer)])
            self.assertEqual(r["status"], "answered")
            self.assertEqual(r["result"]["autonomous_steps_used"], 2)
            self.assertEqual(r["result"]["evidence_calls_used"], 0)
            self.assertEqual(r["result"]["action_steps"][-1]["phase"], "prepared_final_decision")
            self.assertEqual(r["result"]["action_steps"][-2]["phase"], "gap_evidence_decision")
            final_messages = json.loads(self.requests[-1].content)["messages"]
            final_payload = json.loads(final_messages[-1]["content"])
            self.assertEqual(json.loads(final_messages[-2]["content"])["facts"], first_prep["facts"])
            self.assertIn(first_prep["missing_information"], final_payload["missing_information"])
            self.assertIn(no_direction["reason"], final_payload["missing_information"])
            self.assertEqual(final_messages[1]["content"],
                             json.loads(self.requests[1].content)["messages"][-1]["content"])
            self.assertEqual(r["stop_reason"], "no_reliable_evidence_direction")
            for repeat_invalid in (False, True):
                r = self.invoke("agent", token="prepare-gap-repeat-" + str(repeat_invalid), library_mode=True,
                    outcomes=[conversation, response(first_prep), response(first_prep),
                        response(first_prep if repeat_invalid else no_direction), *([] if repeat_invalid else [response(gap_answer)])])
                self.assertEqual(r["status"], "invalid_output" if repeat_invalid else "answered")
                self.assertEqual(r["chat_statistics"]["repairs"], 1)
                self.assertEqual(r["result"]["autonomous_steps_used"], 2)
                rejected = r["result"]["action_steps"][1]
                self.assertEqual(rejected["parse_error_code"], "action_not_allowed")
                repair_payload = json.loads(r["result"]["action_steps"][2]["messages"][-1]["content"])
                self.assertEqual(repair_payload["allowed_actions"], ["insufficient_evidence", "search", "read_context"])
                if repeat_invalid:
                    self.assertFalse(any(s["phase"] == "prepared_final_decision" for s in r["result"]["action_steps"]))

            # Final-generation format/citation failures use the same single repair.
            for failure in ("format", "citation", "unrepaired"):
                broken = deepcopy(final_action)
                if failure == "citation":
                    broken["answer"]["claims"][0]["citation_ids"] = ["not-visible"]
                else:
                    broken["answer"]["extra"] = True
                r = self.invoke("agent", token="prepare-final-" + failure, library_mode=True,
                    outcomes=[conversation, check_agent.tool_response(search_action("requested fact")),
                        response(prepare_action(final_action)), response(broken),
                        response(broken if failure == "unrepaired" else final_action)])
                self.assertEqual(r["status"], "invalid_output" if failure == "unrepaired" else "answered")
                self.assertEqual(r["chat_statistics"]["repairs"], 1)
                self.assertEqual(r["llm_requests"], 5)
                self.assertEqual(r["result"]["action_steps"][-1]["phase"], "prepared_final_decision")
                self.assertNotIn("tools", json.loads(self.requests[-1].content))
                original_messages = json.loads(self.requests[-2].content)["messages"]
                repaired_messages = json.loads(self.requests[-1].content)["messages"]
                self.assertEqual(repaired_messages[1:-2], original_messages[1:])
                self.assertEqual(repaired_messages[-4]["content"], original_messages[-2]["content"])
                self.assertEqual(json.loads(repaired_messages[-2]["content"])["action"], "answer")
                self.assertEqual(json.loads(repaired_messages[-1]["content"])["allowed_actions"], ["answer"])
                self.assertGreaterEqual(
                    text_count(repaired_messages, self.fixture.chunks[self.fixture.abstract_id]["text"]), 1)
                self.assertTrue(self.store.closed and self.searcher.closed and self.chat_client._closed)

            # A chunk actually provided in evidence_sections stays citable even
            # when the preparation facts did not cite it; a claim that needs two
            # chunks keeps both sources. An unshown chunk does not become visible.
            provided_question = "Explain the paper's recovered method and the body-only fact."
            provided_rows = self.fixture.search(
                [self.fixture.abstract_id, self.fixture.body_id])["results"]
            abstract_text = self.fixture.chunks[self.fixture.abstract_id]["text"]
            body_text = self.fixture.chunks[self.fixture.body_id]["text"]
            provided_preparation = {"action": "prepare_answer",
                "facts": [{"claim": abstract_text,
                           "basis": "paper_evidence", "citation_ids": [self.fixture.abstract_id],
                           "evidence_quotes": [{"chunk_id": self.fixture.abstract_id,
                               "quote": abstract_text}]},
                          {"claim": ("The abstract chunk identifies an offline structural source and "
                                     "the body chunk reports a page-one fact."),
                           "basis": "paper_evidence",
                           "citation_ids": [self.fixture.abstract_id, self.fixture.body_id],
                           "evidence_quotes": [
                               {"chunk_id": self.fixture.abstract_id, "quote": abstract_text},
                               {"chunk_id": self.fixture.body_id, "quote": body_text}]}],
                "answerable": True, "missing_information": ""}
            provided_answer = {"action": "answer", "answer": {"status": "answered", "claims": [
                {"claim": body_text,
                 "basis": "paper_evidence", "citation_ids": [self.fixture.body_id],
                 "evidence_quotes": [{"chunk_id": self.fixture.body_id,
                     "quote": body_text}]},
                {"claim": ("The abstract evidence identifies an offline structural source, and "
                           "the body evidence reports a page-one fact."),
                 "basis": "paper_evidence",
                 "citation_ids": [self.fixture.abstract_id, self.fixture.body_id],
                 "evidence_quotes": [
                     {"chunk_id": self.fixture.abstract_id, "quote": abstract_text},
                     {"chunk_id": self.fixture.body_id, "quote": body_text}]}]}}
            with patch.object(runtime.web_runtime, "_ready_versions", return_value=[{
                    **versions[0], "title": "Offline structural fixture"}]):
                provided = self.invoke("agent", token="prepared-unshown-source", library_mode=True,
                    query=provided_question, rows=provided_rows,
                    outcomes=[response({"clarification_question": None, "planned_queries": []}),
                        check_agent.tool_response(search_action(provided_question)),
                        response(provided_preparation), response(provided_answer)])
            self.assertEqual(provided["status"], "answered",
                             (provided.get("error"), [(s.get("phase"), s.get("parse_error_code"),
                              (s.get("error") or {}).get("code")) for s in provided["result"]["action_steps"]],
                              provided["result"].get("citation_checks"), len(self.requests)))
            self.assertEqual(set(provided["result"]["context"]["allowed_citation_ids"]),
                             {self.fixture.abstract_id, self.fixture.body_id})
            self.assertEqual([source["chunk_id"] for source in provided["answer"]["evidence_sources"]],
                             [self.fixture.body_id, self.fixture.abstract_id])
            self.assertEqual(provided["answer"]["evidence_sources"][0]["text"], body_text)
            self.assertEqual(provided["answer"]["evidence_sources"][1]["text"], abstract_text)
            self.assertEqual(len(provided["answer"]["claims"]), 2)
            self.assertEqual(len(provided["answer"]["evidence_refs"]), 2)
            self.assertEqual(provided["llm_requests"], 4)
            self.assertEqual(provided["embedding_requests"], 1)
            self.assertEqual(provided["chat_statistics"]["repairs"], 0)
            self.assertEqual([step["phase"] for step in provided["result"]["action_steps"]],
                             ["autonomous_decision", "autonomous_decision", "prepared_final_decision"])
            provided_final = json.loads(self.requests[-1].content)["messages"]
            provided_payload = json.loads(provided_final[-1]["content"])
            self.assertEqual(provided_payload["allowed_citation_ids"],
                             [self.fixture.abstract_id, self.fixture.body_id])
            self.assertNotIn(self.fixture.mixed_id, provided_payload["allowed_citation_ids"])
            self.assertNotIn(self.fixture.chunks[self.fixture.mixed_id]["text"],
                             json.dumps(provided_final))
            self.assertGreaterEqual(text_count(provided_final, body_text), 1)
            self.assertGreaterEqual(text_count(provided_final, abstract_text), 1)
            self.assertIn(abstract_text, json.dumps(provided_final))
            self.assertIn(body_text, json.dumps(provided_final))
            self.assertEqual(provided["result"]["context"]["max_chars"], None)
            from paper_assistant.message_fit import context_fit_budget
            self.assertEqual(self.settings.context_length, 1048576)
            self.assertEqual(context_fit_budget(self.settings.context_length, 4096),
                             min(1048576 * 97 // 100, 1048576 - 4096))
            self.assertEqual(context_fit_budget(None, 4096), 4096)
            prepared_response = json.loads(provided_final[-2]["content"])
            self.assertEqual(prepared_response["facts"][1]["citation_ids"],
                             [self.fixture.abstract_id, self.fixture.body_id])
            self.assertEqual([quote["chunk_id"] for quote in prepared_response["facts"][1]["evidence_quotes"]],
                             [self.fixture.abstract_id, self.fixture.body_id])
            provided_system = " ".join(provided_final[0]["content"].lower().split())
            self.assertIn("whole merged claim", provided_system)
            self.assertIn("prepared citations are not audited conclusions", provided_system)
            provided_json, provided_markdown = runtime.download_payloads(
                provided, project_root=self.root)
            provided_saved = json.loads(provided_json)
            self.assertEqual({ref["chunk_id"] for ref in provided_saved["answer"]["evidence_refs"]},
                             {self.fixture.abstract_id, self.fixture.body_id})
            for text in (abstract_text, body_text):
                self.assertIn(text, provided_markdown.decode("utf-8"))
            self.assertEqual(provided["result"]["action_steps"][-1]["phase"], "prepared_final_decision")

            r = self.invoke("agent", token="prepare-fifth-step", library_mode=True,
                search_outcomes=[[]] * 4,
                outcomes=[conversation, *[check_agent.tool_response(search_action("gap step " + str(i))) for i in range(4)],
                    response(first_prep), response(gap_answer)])
            self.assertEqual(r["status"], "answered")
            self.assertEqual(r["result"]["autonomous_steps_used"], 5)
            self.assertEqual(r["result"]["evidence_calls_used"], 4)
            self.assertEqual(r["llm_requests"], 7)
            self.assertNotIn("tools", json.loads(self.requests[-2].content))
            fifth = json.loads(json.loads(self.requests[-2].content)["messages"][-1]["content"])
            self.assertEqual(fifth["remaining_steps"], 0)
            self.assertNotIn("search", fifth["allowed_actions"])

            from paper_assistant.agent_actions import parse_read_context_call, ActionParseError, parse_agent_action
            def read_tool(arguments):
                body = check_agent.tool_response({})[1]
                body["choices"][0]["message"]["tool_calls"][0]["function"] = {
                    "name": "read_context", "arguments": json.dumps(arguments)}
                return (200, body)
            for arguments in ({"parent_id": "p", "chunk_id": "c", "missing_information": "need the fact"},
                              {"chunk_id": "c"}, {}, {"chunk_id": "c", "missing_information": " "}):
                with self.assertRaises(ActionParseError):
                    parse_read_context_call(read_tool(arguments)[1]["choices"][0]["message"]["tool_calls"][0])
            for phase in ("autonomous_decision", "prepared_final_decision", "limit_final_decision"):
                with self.assertRaises(ActionParseError):
                    parse_agent_action(json.dumps(no_direction), phase=phase, has_shown_evidence=True,
                                       prepare_answer=phase != "prepared_final_decision")
            # Unknown chunk and unchanged/duplicate tool results keep the gap state.
            r = self.invoke("agent", token="gap-read-unavailable", library_mode=True,
                outcomes=[conversation, response(first_prep),
                    read_tool({"chunk_id": "outside-this-run", "missing_information": "needed source"}),
                    response(no_direction), response(gap_answer)])
            self.assertEqual(r["status"], "answered")
            self.assertEqual(r["result"]["context_reads"][0]["error"]["code"], "unavailable_chunk")
            self.assertEqual([s["phase"] for s in r["result"]["action_steps"]],
                             ["autonomous_decision", "gap_evidence_decision", "gap_evidence_decision", "prepared_final_decision"])
            self.assertEqual(r["result"]["evidence_calls_used"], 1)

            restricted_question = "仅根据摘要说明所问机制条件。"
            scoped_rows = self.fixture.search([self.fixture.body_id, self.fixture.abstract_id])["results"]
            r = self.invoke("agent", token="gap-read-source-scope", query=restricted_question, library_mode=True,
                rows=scoped_rows, outcomes=[conversation, check_agent.tool_response(search_action("mechanism condition")),
                    response(first_prep), read_tool({"chunk_id": self.fixture.body_id, "missing_information": "the requested condition"}),
                    response(no_direction), response(gap_answer)])
            self.assertEqual(r["status"], "answered", r.get("error"))
            self.assertEqual(r["result"]["context_reads"][0]["error"]["code"], "source_scope_unavailable")
            self.assertEqual(r["result"]["context_reads"][0]["shown_ids"], [])
            self.assertEqual(r["result"]["source_requirement"]["required_scope"], "abstract")
            self.assertEqual(r["standalone_question"], restricted_question)
            self.assertTrue(all(self.fixture.body_id not in step["allowed_citation_ids"] for step in r["result"]["action_steps"]))
            self.assertEqual(r["result"]["evidence_calls_used"], 2)

            r = self.invoke("agent", token="gap-duplicate-search", library_mode=True, rows=[],
                outcomes=[conversation, check_agent.tool_response(search_action("unchanged gap query")), response(first_prep),
                    check_agent.tool_response(search_action("unchanged gap query")), response(no_direction), response(gap_answer)])
            self.assertEqual(r["status"], "answered")
            self.assertEqual(len(self.searcher.calls), 1)
            self.assertEqual(r["result"]["action_steps"][2]["tool_calls"][0]["tool_observation"]["status"], "duplicate")
            self.assertEqual(r["result"]["action_steps"][3]["phase"], "gap_evidence_decision")
            self.assertEqual(r["result"]["evidence_calls_used"], 2)

    def test_same_token_cannot_replay_and_new_explicit_token_can(self):
        first = self.invoke()
        old = (self.root / first["history_report"]).read_bytes()
        with self.assertRaises(runtime.InvalidQuestion):
            self.invoke("agent")
        self.assertEqual(self.load_embedding.call_count, 0)
        self.assertEqual(self.requests, [])
        again = self.invoke("agent", token="new-explicit-submit")
        self.assertEqual(again["status"], "answered")
        self.assertEqual((self.root / first["history_report"]).read_bytes(), old)
        self.assertNotEqual(first["run_id"], again["run_id"])

    def test_reservation_survives_paid_core_exception(self):
        def core(*args, **kwargs):
            args[4].invoke([{"role": "user", "content": "offline"}], purpose="answer", require_json=True)
            raise RuntimeError("exception after paid request")
        r = self.invoke(override_core=core)
        self.assertEqual(r["status"], "tool_error")
        self.assertEqual(r["llm_requests"], 1)
        self.assertIsNone(r["embedding_requests"])
        self.assertIsNone(r["network_requests"])
        self.assertIsNone(r["answer"])
        self.assertTrue(self.store.closed and self.searcher.closed)
        with self.assertRaises(runtime.InvalidQuestion):
            self.invoke()

    def test_invalid_input_and_mode_reject_before_attempt_or_configuration(self):
        with patch.object(runtime, "load_embedding_settings", side_effect=AssertionError("must not load")) as load:
            for query, pairs, mode in ((" ", self.fixture.pairs, "agent"), ("q", [], "fixed_rag"),
                                       ("q", [("p",)], "agent"), ("q", self.fixture.pairs, "unexpected")):
                with self.subTest(query=query, pairs=pairs, mode=mode), self.assertRaises(runtime.InvalidQuestion):
                    runtime.run_question(query, pairs, mode=mode, project_root=self.root)
        self.assertEqual(load.call_count, 0)
        self.assertFalse((self.root / "archive/run_logs/d9/submissions").exists())

    def test_invalid_runtime_schema_fails_before_requests(self):
        path = self.root / runtime.STRATEGY_PATH
        value = json.loads(path.read_text(encoding="utf-8"))
        value["schema_revision"] = "damaged-schema"
        path.write_text(json.dumps(value), encoding="utf-8")
        r = self.invoke()
        self.assertEqual(r["status"], "tool_error")
        self.assertEqual(r["network_requests"], 0)

    def test_historical_contract_and_whitespace_are_not_runtime_guards(self):
        (self.root / runtime.CONTRACT_PATH).unlink()
        path = self.root / runtime.STRATEGY_PATH
        path.write_bytes(path.read_bytes() + b" ")
        self.assertEqual(self.invoke()["status"], "answered")

    def test_unfrozen_full_pair_is_zero_requests(self):
        from paper_assistant.context import SHORT_REPAIR_INSTRUCTION
        with patch.object(runtime, "load_embedding_settings", side_effect=AssertionError("must not load")) as load:
            r = runtime.run_question("q", [("synthetic_paper", "another_revision")],
                                     project_root=self.root, submission_id="wrong-revision")
        self.assertEqual(r["status"], "tool_error")
        self.assertEqual(r["network_requests"], 0)
        self.assertEqual(load.call_count, 0)
        self.assertEqual(r["policy"]["max_attempts"], 3)
        self.assertEqual(r["policy"]["total_timeout"], 120.0)
        self.assertEqual(r["policy"]["max_tokens"], 1200)

        from paper_assistant.source_scope import detect_abstract_regions
        f = self.fixture
        paper_id, revision = "local_paper", "local_revision"
        pairs = [(paper_id, revision)]

        def page_search(query):
            return response({"action": "search", "query": query,
                "selected_versions": [{"paper_id": paper_id, "parse_revision": revision}],
                "missing_information": "Find the requested local paper fact."})

        filtered = [json.loads(line) for line in (self.root / "filtered.jsonl").read_text(encoding="utf-8").splitlines()]
        for page in filtered:
            page["paper_id"] = paper_id
        regions = detect_abstract_regions(filtered)
        self.assertTrue(regions)
        self.assertNotIn("text_sha256", regions[0])
        merged = deepcopy(filtered[1])
        merged["segments"] = [deepcopy(merged["segments"][1])]
        merged["segments"][0]["text"] = "Abstract\nAn exact abstract passage.\n1 Introduction\nBody-only fact."
        located = detect_abstract_regions([merged])
        self.assertEqual(merged["segments"][0]["text"][located[0]["segment_char_start"]:located[0]["segment_char_end"]],
                         "An exact abstract passage.")
        self.assertEqual(detect_abstract_regions([{"pdf_page": 1, "segments": [
            {**merged["segments"][0], "text": "No recognizable abstract boundary."}]}]), [])
        local_chunks = []
        for identifier, chunk in f.chunks.items():
            local = {**deepcopy(chunk), "chunk_id": "local_" + identifier,
                     "paper_id": paper_id, "parse_revision": revision, "title": "Uploaded paper",
                     "arxiv_version": "", "source_url": "", "source_type": "local",
                     "local_path": "data/papers/fixture.pdf"}
            local_chunks.append(local)
            self.store.chunks[local["chunk_id"]] = local
        abstract_id, body_id = "local_" + f.abstract_id, "local_" + f.body_id
        folder = self.root / "data/chunks" / paper_id / revision
        folder.mkdir(parents=True)
        filtered_path, chunks_path = folder / "filtered.pages.jsonl", folder / "chunks.jsonl"
        filtered_path.write_text("\n".join(json.dumps(row) for row in filtered), encoding="utf-8")
        chunks_path.write_text("\n".join(json.dumps(row) for row in local_chunks), encoding="utf-8")
        paper = {"paper_id": paper_id, "title": "Uploaded paper", "arxiv_version": "",
                 "source_type": "local", "pdf_sha256": local_chunks[0]["pdf_sha256"]}
        manifest = {"source_paths": {"filtered": filtered_path.relative_to(self.root).as_posix(),
                                     "chunks": chunks_path.relative_to(self.root).as_posix()},
                    "source_regions": regions}
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE papers(paper_id, title, arxiv_version, pdf_sha256, paper_json)")
        connection.execute("CREATE TABLE parse_versions(paper_id, parse_revision, manifest_json)")
        connection.execute("INSERT INTO papers VALUES(?,?,?,?,?)", (
            paper_id, paper["title"], "", paper["pdf_sha256"], json.dumps(paper)))
        connection.execute("INSERT INTO parse_versions VALUES(?,?,?)", (paper_id, revision, json.dumps(manifest)))
        self.store.connection = connection
        self.store.list_versions = lambda: [{"paper_id": paper_id, "parse_revision": revision,
            "chunk_count": len(local_chunks), "pdf_sha256": paper["pdf_sha256"]}]
        ready_imports = [{"paper_id": paper_id, "parse_revision": revision,
                          "completed_count": len(local_chunks)}]
        self.store.list_index_imports = lambda **kwargs: ready_imports
        historical_registry = (self.root / runtime.REGISTRY_PATH).read_text(encoding="utf-8")
        for mode in runtime.MODES:
            with self.subTest(library_mode=mode):
                for name, identifier, query in (("abstract", abstract_id, f.question),
                                                 ("body", body_id, "What body-only fact is reported?")):
                    draft = answer_action(identifier)
                    row = {**self.store.chunks[identifier], "rank": 1, "score": 0.8}
                    decisions = ([page_search(query), response(draft)] if mode == "agent"
                                 else [response(draft["answer"])])
                    r = self.invoke(mode, token=mode + "-library-" + name, library_mode=True, pairs=pairs,
                        query=query, rows=[row], outcomes=[response({"standalone_question": query,
                            "clarification_question": None, "referenced_evidence_ids": [], "planned_queries": []}),
                            *decisions])
                    self.assertEqual(r["status"], "answered")
                    self.assertEqual(r["selected_versions"], [{"paper_id": paper_id, "parse_revision": revision}])
                    self.assertEqual(r["selected_version_metadata"][0]["source_type"], "local")
                    self.assertEqual(r["answer"]["evidence_sources"][0]["paper_id"], paper_id)
                    self.assertEqual(r["answer"]["evidence_sources"][0]["text"], row["text"])
                    self.assertEqual(r["embedding_requests"], 1)
                    self.assertEqual(r["policy"]["max_tokens"], 4096)
                    self.assertIsNone(r["policy"]["max_attempts"])
                    self.assertIsNone(r["policy"]["total_timeout"])
                    self.assertEqual(r["configuration"]["policy"], r["policy"])
                history = [{"turn": 1, "status": "answered", "user_question": f.question,
                            "standalone_question": f.question,
                            "claims": [{"number": 1, "claim": "Previous abstract fact.", "basis": "paper_evidence",
                                        "citation_ids": [abstract_id]}]}]
                prepared = {"standalone_question": "Explain the previously cited original passage.",
                            "clarification_question": None, "referenced_evidence_ids": [abstract_id]}
                draft = answer_action(abstract_id)
                r = self.invoke(mode, token=mode + "-library-followup", library_mode=True, pairs=pairs,
                    query="What does that passage mean?", rows=[], conversation_id="local-chat", conversation_history=history,
                    outcomes=[response(prepared), response(draft["answer"] if mode == "fixed_rag" else draft)])
                self.assertEqual(r["status"], "answered")
                self.assertEqual(r["llm_requests"], 2)
                self.assertIn(abstract_id, r["result"]["context"]["allowed_citation_ids"])
                self.assertEqual(r["answer"]["evidence_sources"][0]["text"], self.store.chunks[abstract_id]["text"])

                # Preparation, network retry and short repair exceed the old three-request default.
                decisions = ([page_search(prepared["standalone_question"])] if mode == "agent" else [])
                r = self.invoke(mode, token=mode + "-library-fourth-request", library_mode=True, pairs=pairs,
                    query="Explain that original passage.", rows=[], conversation_history=history,
                    on_search=lambda _: self.clock.advance(121), outcomes=[response(prepared),
                        *decisions,
                        check_agent.http_error(500), (200, check_agent.completion('{"unfinished":', finish_reason="length")),
                        response(draft["answer"] if mode == "fixed_rag" else draft)])
                self.assertEqual(r["status"], "answered")
                self.assertEqual(r["llm_requests"], 5 if mode == "agent" else 4)
                self.assertEqual(r["chat_statistics"]["network_retries"], 1)
                self.assertEqual(r["chat_statistics"]["repairs"], 1)
                self.assertGreater(r["chat_statistics"]["elapsed_seconds"], 120)
                self.assertFalse(r["business_commit"]["deadline_checked"])
                self.assertTrue(all(record["timeout_seconds"] == 30 for record in self.budget.records))
                self.assertEqual(r["answer"]["evidence_sources"][0]["chunk_id"], abstract_id)
                self.assertTrue(all(json.loads(request.content)["max_tokens"] == 4096 for request in self.requests))
                repair_messages = json.loads(self.requests[-1].content)["messages"]
                self.assertIn(SHORT_REPAIR_INSTRUCTION, json.loads(repair_messages[-1]["content"])["instruction"])
                self.assertIn("compact JSON", repair_messages[0]["content"])
                downloaded, _ = runtime.download_payloads(r, project_root=self.root)
                self.assertEqual(json.loads(downloaded)["policy"], r["policy"])
                if mode == "agent":
                    row = {**self.store.chunks[abstract_id], "rank": 1, "score": 0.8}
                    r = self.invoke(mode, token="agent-library-final-decision-repair", library_mode=True,
                        pairs=pairs, query="Explain that passage in more detail.", conversation_history=history,
                        search_outcomes=[[row]], outcomes=[response(prepared),
                            page_search("Offline structural fixture original passage details"),
                            (200, check_agent.completion('{"action":"answer","answer":', finish_reason="length")),
                            response(draft)])
                    self.assertEqual(r["status"], "answered")
                    self.assertEqual(r["llm_requests"], 4)
                    self.assertEqual(r["embedding_requests"], 1)
                    self.assertEqual(len(self.searcher.calls), 1)
                    self.assertIsNone(r["result"]["retry_decision"])
                    self.assertEqual(r["result"]["autonomous_steps_used"], 2)
                    self.assertEqual(r["chat_statistics"]["network_retries"], 0)
                    self.assertEqual(r["chat_statistics"]["repairs"], 1)
                    steps = r["result"]["action_steps"]
                    self.assertEqual([(step["phase"], step["purpose"]) for step in steps],
                                     [("autonomous_decision", "answer"), ("autonomous_decision", "answer"),
                                      ("autonomous_decision", "repair")])
                    self.assertEqual(steps[1]["parse_error_code"], "truncated")
                    self.assertIn(SHORT_REPAIR_INSTRUCTION,
                                  json.loads(steps[2]["messages"][-1]["content"])["instruction"])
                    self.assertEqual(r["result"]["citation_checks"][-1]["status"], "valid")
                    self.assertEqual(r["answer"]["evidence_sources"][0]["chunk_id"], abstract_id)
                    self.assertEqual(r["answer"]["evidence_sources"][0]["text"], row["text"])
        self.assertEqual((self.root / runtime.REGISTRY_PATH).read_text(encoding="utf-8"), historical_registry)

        # A temporary local-only library does not require the historical table.
        (self.root / runtime.REGISTRY_PATH).unlink()
        manifest["source_regions"] = []
        connection.execute("UPDATE parse_versions SET manifest_json=?", (json.dumps(manifest),))
        general = {"status": "answered", "claims": [{"claim": "The abstract boundary is unavailable in this upload.",
                   "basis": "model_knowledge", "citation_ids": []}]}
        r = self.invoke(token="library-abstract-unavailable", library_mode=True, pairs=pairs,
            outcomes=[response({"standalone_question": f.question, "clarification_question": None,
                "referenced_evidence_ids": [], "planned_queries": []}), response(general)])
        self.assertEqual(r["status"], "answered")
        self.assertEqual(r["stop_reason"], "source_scope_unavailable")
        self.assertEqual(r["embedding_requests"], 0)
        self.assertEqual(r["answer"]["evidence_sources"], [])
        body_row = {**self.store.chunks[body_id], "rank": 1, "score": 0.8}
        r = self.invoke(token="library-body-without-abstract", library_mode=True, pairs=pairs,
                        query="What body-only fact is reported?", rows=[body_row],
            outcomes=[response({"standalone_question": "What body-only fact is reported?", "clarification_question": None,
                "referenced_evidence_ids": [], "planned_queries": []}), response(answer_action(body_id)["answer"])])
        self.assertEqual(r["status"], "answered")
        self.assertEqual(r["answer"]["evidence_sources"][0]["chunk_id"], body_id)
        ready_imports.clear()
        r = self.invoke(token="library-not-ready", library_mode=True, pairs=pairs)
        self.assertEqual(r["status"], "tool_error")
        self.assertEqual(r["network_requests"], 0)
        self.assertEqual(self.client_factory.call_count, 0)

    def test_chat_model_can_change_without_rebuilding_the_embedding_index(self):
        from dataclasses import replace
        self.settings = replace(self.settings, model_id="changed-model")
        r = self.invoke()
        self.assertEqual(r["status"], "answered")
        self.assertEqual(r["configuration"]["chat"]["model_id"], "changed-model")

    def test_occupied_resources_fail_before_client_and_paid_request(self):
        r = self.invoke(resource_error=RuntimeError("storage is already accessed"))
        self.assertEqual(r["status"], "tool_error")
        self.assertEqual(r["failure_stage"], "resources")
        self.assertEqual(r["network_requests"], 0)
        self.assertEqual(self.client_factory.call_count, 0)

    def test_zero_remaining_after_settings_prevents_resource_payment(self):
        original = runtime.load_current_profile
        def expire(root):
            value = original(root)
            self.clock.advance(121)
            return value
        with patch.object(runtime, "load_current_profile", side_effect=expire):
            r = self.invoke()
        self.assertEqual(r["status"], "budget_exceeded")
        self.assertEqual(r["network_requests"], 0)
        self.assertEqual(self.client_factory.call_count, 0)

    def test_late_cleanup_expires_success_and_keeps_costs(self):
        r = self.invoke(on_close=lambda: self.clock.advance(121))
        self.assertEqual(r["status"], "budget_exceeded")
        self.assertEqual(r["failure_stage"], "resource_cleanup")
        self.assertIsNone(r["answer"])
        self.assertEqual(r["embedding_requests"], 1)
        self.assertEqual(r["llm_requests"], 1)
        self.assertEqual(r["business_commit"]["status"], "budget_exceeded")

    def test_cleanup_error_and_late_cleanup_combine_without_publish(self):
        r = self.invoke(on_close=lambda: self.clock.advance(121), close_error=RuntimeError("close fault"))
        self.assertEqual(r["status"], "budget_exceeded")
        self.assertEqual(r["result"]["interrupted_failure"]["failure_stage"], "resource_cleanup")
        self.assertEqual(r["llm_requests"], 1)
        self.assertIsNone(r["answer"])

    def test_registry_whitespace_after_loading_does_not_discard_answer(self):
        def drift():
            path = self.root / runtime.REGISTRY_PATH
            path.write_bytes(path.read_bytes() + b" ")
        r = self.invoke(on_close=drift)
        self.assertEqual(r["status"], "answered")
        self.assertEqual(r["llm_requests"], 1)
        self.assertNotIn("protected_files", r)

    def test_no_repository_snapshot_is_required_to_answer(self):
        self.assertFalse(hasattr(runtime, "snapshot_inputs"))
        self.assertFalse(hasattr(runtime, "changed_inputs"))
        self.assertEqual(self.invoke()["status"], "answered")

    def test_fixed_model_insufficient_is_repaired_to_useful_answer(self):
        draft = {"status": "answered", "claims": [{"claim": "解释所问问题的通用概念。",
                 "basis": "model_knowledge", "citation_ids": []}]}
        r = self.invoke(outcomes=[response({"status": "insufficient_evidence", "reason": "offline evidence insufficient"}),
                                  response(draft)])
        self.assertEqual(r["status"], "answered")
        self.assertEqual(r["stop_reason"], "fixed_citations_valid")
        self.assertEqual(r["llm_requests"], 2)
        self.assertEqual(r["answer"]["evidence_status"], "none")

    def test_ambiguous_source_answers_without_search_or_paper_citations(self):
        draft = {"status": "answered", "claims": [{"claim": "摘要概括研究问题和结论，正文展开方法与证据。",
                 "basis": "model_knowledge", "citation_ids": []}]}
        r = self.invoke(query="摘要还是正文？", outcomes=[response(draft)])
        self.assertEqual(r["status"], "answered")
        self.assertEqual(r["stop_reason"], "source_constraint_ambiguous")
        self.assertEqual(self.searcher.calls, [])
        self.assertEqual(r["network_requests"], 1)

    def test_post_commit_export_fault_is_independent_and_cost_preserved(self):
        def fail(report, **kwargs):
            self.clock.advance(121)
            raise OSError("offline export fault")
        r = self.invoke(export=fail)
        self.assertEqual(r["status"], "tool_error")
        self.assertEqual(r["failure_stage"], "export")
        self.assertEqual(r["stop_reason"], "export_error")
        self.assertEqual(r["pre_export_result"]["status"], "answered")
        self.assertEqual(r["business_commit"]["status"], "answered")
        self.assertIsNone(r["answer"])
        self.assertEqual(r["llm_requests"], 1)
        self.assertEqual(r["embedding_requests"], 1)
        self.assertEqual(r["export"]["status"], "failed")

    def test_download_is_pure_session_snapshot_with_source_and_frozen_mode(self):
        r = self.invoke()
        previous = deepcopy(r)
        with patch.object(runtime, "load_embedding_settings", side_effect=AssertionError("no IO")), \
             patch.object(runtime, "run_question", side_effect=AssertionError("no rerun")):
            raw, markdown = runtime.download_payloads(r, project_root=self.root)
        self.assertEqual(json.loads(raw), previous)
        self.assertEqual(r, previous)
        self.assertIn("fixed_rag", markdown.decode())
        self.assertIn("abstract_full", markdown.decode())

    def test_download_failure_keeps_diagnostics_and_never_publishes_prior_success(self):
        def fail(*args, **kwargs):
            raise OSError("offline export fault")
        r = self.invoke(export=fail)
        raw, markdown = runtime.download_payloads(r)
        self.assertIsNone(json.loads(raw)["history_report"])
        self.assertIn("本轮没有可发布答案", markdown.decode())
        # Simulate the page's recovery diagnostic retaining nested prior success.
        r["result"] = deepcopy(r["pre_export_result"])
        raw, markdown = runtime.download_payloads(r)
        self.assertEqual(json.loads(raw)["pre_export_result"]["status"], "answered")
        self.assertIn("本轮没有可发布答案", markdown.decode())
        self.assertNotIn("The shown evidence combines reasoning and action.", markdown.decode())

    def test_cli_help_invalid_input_and_both_modes_have_zero_live_calls(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as help_result:
                cli.parse_args(["--help"])
            self.assertEqual(help_result.exception.code, 0)
            with self.assertRaises(SystemExit) as invalid:
                cli.parse_args(["--query", " ", "--version", "p", "r"])
            self.assertEqual(invalid.exception.code, 2)
        for mode in runtime.MODES:
            report = {"status": "answered", "export": {"status": "completed"}}
            with patch.object(runtime, "run_question", return_value=report) as run, redirect_stdout(io.StringIO()):
                result = cli.main(["--mode", mode, "--query", "original", "--version", "p", "r", "--json"])
            self.assertEqual(result, 0)
            self.assertEqual(run.call_args.args, ("original", [("p", "r")]))
            self.assertEqual(run.call_args.kwargs["mode"], mode)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
