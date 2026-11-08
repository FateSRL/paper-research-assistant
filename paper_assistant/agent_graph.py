"""Current create_agent autonomous run assembly.

The graph itself is in langchain_agent.py.  This module keeps the current run
entry (evidence setup, one no-tool synthesis and failure finalization) separate
from the historical action/facts branches in agent.py.
"""

from copy import deepcopy
from dataclasses import dataclass
import json
import re
from typing import Any, Callable

from paper_assistant.agent_current import (
    AUTONOMOUS_SYSTEM_PROMPT, build_react_messages,
)
from paper_assistant.agent_state import AgentEvidenceState
from paper_assistant.agent_tools import build_agent_tools
from paper_assistant.citations import validate_prose_citations
from paper_assistant.deadline import FINALIZE_RESERVE_SECONDS
from paper_assistant.langchain_agent import GraphHooks, run_evidence_graph
from paper_assistant.langchain_model import recorded_response, to_langchain_messages
from paper_assistant.llm_client import LLMCallError
from paper_assistant.prose import normalize_citation_markers, source_refs
from paper_assistant.source_scope import validate_prose_citation_scope


_TERMINAL_PUNCTUATION = (".", "!", "?", "。", "！", "？", "…")
_CITATION_SUFFIX = re.compile(r"(?:\s*\[ID:\d+\])+\s*$")
_NUMERIC_ANSWER = re.compile(
    r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:\s*(?:%|percent|points?|reviews?|docs?|documents?))?$",
    re.IGNORECASE)
_SHORT_ANSWERS = {
    "yes", "no", "yes.", "no.", "none", "none.", "unknown", "unknown.",
    "not reported", "not stated", "not available", "not given", "not mentioned",
    "insufficient evidence", "insufficient information", "no evidence",
    "cannot determine", "can't determine", "unable to determine",
    "not enough evidence", "no answer", "n/a", "na", "unclear",
}


def final_text_issue(text):
    """Reject an obvious delivery fragment without judging answer correctness.

    A complete short answer and a numeric answer are allowed. Otherwise prose
    must end in sentence punctuation; a dangling determiner or noun phrase such
    as ``The`` or ``The authors`` is a fragment even when the provider labels
    the response as a successful stop.
    """
    if not isinstance(text, str) or not text.strip():
        return "empty_output"
    body = _CITATION_SUFFIX.sub("", text.strip()).strip()
    if not body:
        # Keep the existing citation-only normalization contract; a text
        # fragment with any prose ("The [ID:1]") still fails below.
        return None if re.search(r"\[ID:\d+\]", text) else "incomplete_text"
    lowered = body.lower().strip().rstrip("*_` ")
    if lowered in _SHORT_ANSWERS or lowered.rstrip(".") in _SHORT_ANSWERS:
        return None
    if _NUMERIC_ANSWER.fullmatch(body.strip().rstrip("*_` ")):
        return None
    # A determiner plus a noun phrase without a predicate is still a fragment
    # when the provider appends a period (for example "The authors.").
    short_words = body.strip().rstrip("*_` ").split()
    if (len(short_words) <= 2 and short_words[0].lower() in {
            "the", "a", "an", "this", "that", "these", "those"}
            and not any(word.strip(".,;:!?()[]\"'").lower() in {
                "is", "are", "was", "were", "be", "been", "being", "has", "have",
                "had", "do", "does", "did", "can", "could", "may", "might",
                "must", "should", "would", "will", "shall", "reports", "reported",
                "shows", "showed", "states", "stated", "provides", "provided",
                "uses", "used", "includes", "included", "contains", "contained",
                "remains", "appears", "seems", "describes", "explains", "presents",
                "proposes", "argues", "means", "makes", "found", "gives"}
                for word in short_words)):
        return "incomplete_text"
    tail = body.rstrip("*_` \t\r\n\"'”’)]}")
    if tail and tail[-1] in _TERMINAL_PUNCTUATION:
        return None
    # A short numeric phrase (for example "3,209 reviews") is a useful
    # delivery even without a final period; it is not an open sentence.
    words = body.split()
    if len(words) <= 8 and any(ch.isdigit() for ch in body) and words[-1].lower() not in {
            "the", "a", "an", "and", "or", "of", "to", "in", "for", "with",
            "by", "as", "that", "which", "who", "is", "are", "was", "were"}:
        return None
    return "incomplete_text"


@dataclass
class GraphRunContext:
    query: str
    pairs: list
    store: Any
    client: Any
    chat_model: Any
    project_root: Any
    source_registry: Any
    requirement: Any
    source_issue: Any
    paper_information: list
    version_chunks: dict
    context_options: dict
    conversation_context: Any
    autonomous_steps: int
    result: dict
    budget: Any
    evidence_registry: Any
    retrieve: Callable
    fit_request: Callable
    deadline: Callable
    fail: Callable
    publish_prose: Callable
    set_stage: Callable
    stage: Callable


def run_autonomous_path(ctx: GraphRunContext):
    """Run the graph and the one allowed no-tool synthesis outside it."""
    evidence_state = AgentEvidenceState(
        query=ctx.query, pairs=ctx.pairs, store=ctx.store,
        version_chunks=ctx.version_chunks, paper_information=ctx.paper_information,
        source_registry=ctx.source_registry, requirement=ctx.requirement,
        source_issue=ctx.source_issue, top_k=5, max_chars=None,
        context_options=ctx.context_options, conversation_context=ctx.conversation_context,
        result=ctx.result, evidence_registry=ctx.evidence_registry,
        search_fn=ctx.retrieve, set_stage=ctx.set_stage, deadline=ctx.deadline)
    evidence_state.tools = build_agent_tools(evidence_state)
    context = evidence_state.merge_current()
    ctx.result["initial_context"] = deepcopy(context)
    if ctx.source_registry is not None:
        ctx.result["initial_source_qualification"] = deepcopy(evidence_state.qualification)

    def build_evidence(new_ids, remaining_rounds):
        current = evidence_state.context
        ctx.evidence_registry.stamp(current)
        messages = build_react_messages(
            ctx.query, current, paper_information=ctx.paper_information,
            conversation_context=ctx.conversation_context, history=[],
            remaining_rounds=remaining_rounds, new_evidence_ids=new_ids,
            source_requirement=ctx.requirement)
        return messages[-1]["content"]

    def fit_graph_messages(current, messages, tools):
        system = {"role": "system", "content": AUTONOMOUS_SYSTEM_PROMPT}
        fitted, dropped = ctx.fit_request(
            current, [system, *messages], tools=tools)
        return fitted[1:], dropped

    def validate_final(response, current):
        if response.get("status") != "success":
            return response.get("output_issue") or "invalid_output"
        if response.get("tool_calls"):
            return "unexpected_tool_calls"
        text = normalize_citation_markers(response.get("content") or "")
        try:
            structured = json.loads(text)
        except ValueError:
            structured = None
        if isinstance(structured, (dict, list)):
            return "unexpected_action_json"
        issue = final_text_issue(text)
        if issue:
            ctx.result["final_text_check"] = {"version": "d7-final-text-v1",
                                               "status": issue, "chars": len(text)}
            return issue
        ctx.result["final_text_check"] = {"version": "d7-final-text-v1",
                                           "status": "valid", "chars": len(text)}
        checked = validate_prose_citations(
            text, source_refs(current, ctx.evidence_registry), current, ctx.store,
            project_root=ctx.project_root)
        ctx.result["citation_checks"].append(deepcopy(checked))
        if ctx.source_registry is not None:
            scoped = validate_prose_citation_scope(
                checked.get("citations") or [], current,
                evidence_state.qualification, ctx.source_registry,
                requirement=ctx.requirement)
            ctx.result["source_scope_checks"].append(deepcopy(scoped))
            if scoped["status"] != "valid":
                checked = scoped
        if checked["status"] != "valid":
            return (checked.get("error") or {}).get("code") or "citation_invalid"
        return text, checked, deepcopy(current)

    def synthesize(trigger):
        ctx.set_stage("synthesis")
        current = evidence_state.context
        ctx.evidence_registry.stamp(current)
        messages = build_react_messages(
            ctx.query, current, paper_information=ctx.paper_information,
            conversation_context=ctx.conversation_context, history=[],
            remaining_rounds=0, synthesis=True,
            source_requirement=ctx.requirement)
        calculations = [call["tool_observation"] for step in ctx.result["action_steps"]
            for call in step.get("tool_calls", [])
            if (call.get("function") or {}).get("name") == "run_javascript"
            and (call.get("tool_observation") or {}).get("status") == "success"]
        payload = json.loads(messages[-1]["content"])
        payload["completed_calculations"] = calculations
        messages[-1]["content"] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        messages, dropped = ctx.fit_request(current, messages, [])
        ctx.result["context"] = deepcopy(current)
        entry = {"phase": "synthesis", "purpose": "synthesis",
            "repair_kind": None, "autonomous_step": ctx.result["autonomous_steps_used"],
            "remaining_steps": 0, "limit_finalize": True,
            "messages": deepcopy(messages), "allowed_refs": list(current["allowed_refs"]),
            "allowed_citation_ids": list(current["allowed_citation_ids"]),
            "response": None, "parsed_action": None, "parse_error_code": None,
            "error": None, "sdk_attempt_numbers": []}
        ctx.result["action_steps"].append(entry)
        remaining_seconds = ctx.budget.remaining_seconds()
        timeout_seconds = max(0.001, min(90.0, remaining_seconds))
        entry["timeout_seconds"] = timeout_seconds
        start = len(ctx.budget.records)
        try:
            response = recorded_response(ctx.chat_model.invoke(
                to_langchain_messages(messages), purpose="synthesis",
                request_timeout=timeout_seconds))
            entry["response"] = deepcopy(response)
            return response, entry
        except LLMCallError as error:
            entry["error"] = {"status": error.status, "code": error.code,
                "attempts": deepcopy(error.attempts)}
            raise
        finally:
            entry["sdk_attempt_numbers"] = [
                row["number"] for row in ctx.budget.records[start:]]

    def finalize(trigger, error=None):
        if error is not None and (getattr(error, "code", "") in
                ("configuration_error", "client_closed", "invalid_input",
                 "deadline_exceeded", "request_limit")
                or any(a.get("http_status") in (401, 403)
                       for a in getattr(error, "attempts", []))):
            return ctx.fail(error.status, error.code, str(error))
        if ctx.budget.remaining_seconds() <= 0:
            return ctx.fail("budget_exceeded", "deadline_exceeded",
                            "问答截止预算已到，停止无工具综合")
        ctx.result["limit_finalize"] = trigger == "iteration_limit"
        remaining_seconds = ctx.budget.remaining_seconds()
        ctx.result["synthesis"] = {"trigger": trigger, "status": "attempted",
                                   "timeout_seconds": max(0.001, min(90.0, remaining_seconds))}
        try:
            response, entry = synthesize(trigger)
            accepted = validate_final(response, evidence_state.context)
            if isinstance(accepted, str):
                entry["parse_error_code"] = accepted
                ctx.result["synthesis"]["status"] = "invalid_output"
                return ctx.fail("invalid_output", accepted, "无工具综合未产生有效正文或引用")
            ctx.result["synthesis"]["status"] = "completed"
            ctx.result["stop_reason"] = ("iteration_limit_synthesized"
                if trigger == "iteration_limit" else "incomplete_final_synthesized"
                if trigger == "incomplete_text" else "deadline_reserve_synthesized"
                if trigger == "deadline_reserve" else "error_synthesized")
            return ctx.publish_prose(*accepted, "synthesis")
        except LLMCallError as failure:
            ctx.result["synthesis"]["status"] = "failed"
            return ctx.fail(failure.status, failure.code, str(failure))
        except Exception as failure:
            ctx.result["synthesis"]["status"] = "failed"
            return ctx.fail("tool_error",
                getattr(failure, "code", "synthesis_local_error"), "无工具综合未完成")

    try:
        hooks = GraphHooks(
            state=evidence_state, model=ctx.chat_model, tools=evidence_state.tools,
            system_prompt=AUTONOMOUS_SYSTEM_PROMPT, max_rounds=ctx.autonomous_steps,
            result=ctx.result, budget=ctx.budget, build_evidence=build_evidence,
            fit_messages=fit_graph_messages, validate_final=validate_final,
            set_stage=ctx.set_stage)
        graph_state = run_evidence_graph(hooks)
        ctx.result["autonomous_steps_used"] = int(graph_state.get("model_rounds") or 0)
        if graph_state.get("accepted_text") is not None:
            ctx.result["limit_finalize"] = False
            return ctx.publish_prose(graph_state["accepted_text"],
                graph_state["accepted_check"], graph_state["accepted_context"],
                "react_loop")
        ctx.result["limit_finalize"] = bool(graph_state.get("limit_finalize"))
        trigger = (ctx.result.get("finalize_trigger")
                   or ("iteration_limit" if ctx.result["limit_finalize"] else "graph_stopped"))
        return finalize(trigger)
    except LLMCallError as error:
        ctx.result["interrupted_failure"] = {
            "status": error.status, "code": error.code, "stage": ctx.stage()}
        return finalize(error.code, error)
    except Exception as error:
        ctx.result["interrupted_failure"] = {
            "status": "tool_error", "code": getattr(error, "code", "local_error"),
            "stage": ctx.stage()}
        return finalize(getattr(error, "code", "local_error"))
