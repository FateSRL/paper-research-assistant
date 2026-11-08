"""create_agent graph for the autonomous paper-evidence loop.

The graph owns model/tool scheduling.  Paper evidence, stable refs and the
three tools remain the per-question objects assembled by agent.py.
"""

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any, Callable, NotRequired

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES, RemoveMessage

from paper_assistant.deadline import FINALIZE_RESERVE_SECONDS
from paper_assistant.langchain_model import (
    INVALID_TOOL_ARGS, recorded_response, to_langchain_messages, to_openai_messages,
)


GRAPH_VERSION = "d4-create-agent-evidence-v1"
SYNTHESIS_TIMEOUT = 90.0


class EvidenceGraphState(AgentState):
    model_rounds: NotRequired[int]
    provided_ids: NotRequired[list[str]]
    correction: NotRequired[str | None]
    limit_finalize: NotRequired[bool]
    accepted_text: NotRequired[str | None]
    accepted_check: NotRequired[dict | None]
    accepted_context: NotRequired[dict | None]


@dataclass
class GraphHooks:
    state: Any
    model: Any
    tools: dict
    system_prompt: str
    max_rounds: int
    result: dict
    budget: Any
    build_evidence: Callable
    fit_messages: Callable
    validate_final: Callable
    set_stage: Callable


def _payload_ids(message):
    if not isinstance(message, dict) or message.get("role") != "user":
        return []
    try:
        payload = json.loads(message.get("content") or "")
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    ids = [row.get("chunk_id") for row in payload.get("shown_evidence") or []
           if isinstance(row, dict)]
    for section in payload.get("evidence_sections") or []:
        for row in section.get("chunks") or []:
            if isinstance(row, dict):
                ids.append(row.get("chunk_id"))
    for row in payload.get("sources") or []:
        if isinstance(row, dict):
            ids.append(row.get("chunk_id"))
    return [value for value in ids if isinstance(value, str) and value]


def _parent_ids(message):
    if not isinstance(message, dict) or message.get("role") != "user":
        return []
    try:
        payload = json.loads(message.get("content") or "")
    except (TypeError, ValueError):
        return []
    parents = []
    for paper in payload.get("selected_papers") or [] if isinstance(payload, dict) else []:
        if not isinstance(paper, dict):
            continue
        for row in paper.get("reading_directory") or []:
            if isinstance(row, dict) and isinstance(row.get("parent_id"), str):
                parents.append(row["parent_id"])
    return parents


def _tool_definitions(tools):
    from langchain_core.utils.function_calling import convert_to_openai_tool
    return [convert_to_openai_tool(tool) for tool in tools]


class EvidenceMiddleware(AgentMiddleware):
    state_schema = EvidenceGraphState

    def __init__(self, hooks: GraphHooks):
        super().__init__()
        self.hooks = hooks
        self.current_entry = None
        self.current_request = None
        self.current_allowed_refs = []
        self.current_allowed_ids = []
        self.current_context = None
        self.current_round = 0
        self.current_start = 0
        self.purpose = "answer"
        self.correction = None
        self.tool_error = False

    def before_model(self, state, runtime):
        if self.hooks.budget.remaining_seconds() <= FINALIZE_RESERVE_SECONDS:
            self.hooks.result["finalize_trigger"] = "deadline_reserve"
            self.hooks.result["limit_finalize"] = False
            self.hooks.result["deadline_reserve"] = {
                "stage": "react_loop",
                "remaining_seconds": round(self.hooks.budget.remaining_seconds(), 6),
                "reserve_seconds": FINALIZE_RESERVE_SECONDS,
                "action": "skip_new_exploration",
            }
            return {"jump_to": "end"}
        rounds = int(state.get("model_rounds") or 0) + 1
        if rounds > self.hooks.max_rounds:
            self.hooks.result["autonomous_steps_used"] = self.hooks.max_rounds
            return {"jump_to": "end", "limit_finalize": True}
        self.hooks.set_stage("react_loop")
        self.current_round = rounds
        self.hooks.state.current_round = rounds
        self.hooks.result["autonomous_steps_used"] = rounds
        context = self.hooks.state.context
        self.hooks.state.evidence_registry.stamp(context)
        provided = set(state.get("provided_ids") or [])
        new_ids = [identifier for identifier in context.get("allowed_citation_ids", [])
                   if identifier not in provided]
        messages = list(state.get("messages") or [])
        if not messages or new_ids:
            remaining = max(0, self.hooks.max_rounds - rounds)
            payload = self.hooks.build_evidence(new_ids if messages else None, remaining)
            messages.append(HumanMessage(content=payload))
        openai_messages = to_openai_messages(messages)
        fitted, _dropped = self.hooks.fit_messages(
            context, openai_messages, _tool_definitions(self.hooks.tools.values()))
        retained_ids = []
        for message in fitted:
            for identifier in _payload_ids(message):
                if identifier not in retained_ids:
                    retained_ids.append(identifier)
            for identifier in _parent_ids(message):
                self.hooks.state.accessible_parents.add(identifier)
        context.update(allowed_citation_ids=[row["chunk_id"] for row in context["shown_evidence"]
                                             if row["chunk_id"] in retained_ids])
        context["allowed_refs"] = [row["ref"] for row in context["shown_evidence"]
                                   if row["chunk_id"] in retained_ids]
        self.current_request = deepcopy(fitted)
        self.current_allowed_refs = list(context["allowed_refs"])
        self.current_allowed_ids = list(context["allowed_citation_ids"])
        self.current_context = deepcopy(context)
        self.hooks.result["context"] = deepcopy(context)
        self.purpose = "repair" if (state.get("correction") or self.tool_error) else "answer"
        self.tool_error = False
        self.current_start = len(self.hooks.budget.records)
        graph_messages = to_langchain_messages(fitted)
        return {
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *graph_messages],
            "model_rounds": rounds,
            "provided_ids": retained_ids,
            "correction": None,
            "jump_to": None,
        }

    def after_model(self, state, runtime):
        last = state.get("messages")[-1] if state.get("messages") else None
        if not isinstance(last, AIMessage):
            return {"jump_to": "end", "limit_finalize": True}
        try:
            response = recorded_response(last)
        except (TypeError, ValueError):
            response = {"status": "invalid_output", "content": last.content,
                        "tool_calls": [], "output_issue": "recorded_response_missing"}
        raw_calls = deepcopy(response.get("tool_calls") or [])
        valid_calls = list(last.tool_calls or [])
        entry = self.current_entry
        if entry is None:
            # A model hook without the wrapper entry would be a routing error;
            # keep the original stop path rather than inventing a request.
            return {"jump_to": "end", "limit_finalize": True}
        entry["response"] = deepcopy(response)
        entry["parse_error_code"] = None
        entry["error"] = None
        if raw_calls:
            entry["tool_calls"] = deepcopy(raw_calls)
        if response.get("status") != "success" and raw_calls:
            # A truncated/invalid response is not executed as a tool batch.
            # Every original id still gets one matching error result so the
            # next correction turn has a complete assistant/tool history.
            issue = response.get("output_issue") or "invalid_output"
            entry["parse_error_code"] = issue
            messages = []
            for call in raw_calls:
                observation = {
                    "status": "tool_error",
                    "error": {"code": issue,
                              "message": "本轮模型输出无效，工具调用未执行；请重新给出完整回答或调用。"}}
                call_entry = next((row for row in entry["tool_calls"]
                                   if row.get("id") == call.get("id")), None)
                self._attach_call_result(call_entry, observation, None)
                messages.append(ToolMessage(
                    content=json.dumps(observation, ensure_ascii=False, allow_nan=False),
                    tool_call_id=call.get("id"),
                    name=(call.get("function") or {}).get("name"),
                    status="error"))
                self.hooks.result["corrections"].append({
                    "round": self.current_round, "kind": issue,
                    "tool": (call.get("function") or {}).get("name")})
            if self.current_round >= self.hooks.max_rounds:
                return {"messages": messages, "jump_to": "end", "limit_finalize": True}
            self.purpose = "repair"
            self.correction = issue
            return {"messages": messages, "correction": issue, "jump_to": "model"}
        if response.get("status") == "success" and valid_calls:
            # The adapter makes malformed calls dispatchable with a sentinel
            # argument; wrap_tool_call returns their invalid_arguments result
            # in the original batch order. This fallback only covers a raw
            # call that the adapter could not represent as a tool call.
            invalid = [call for call in raw_calls
                       if call.get("id") not in {row.get("id") for row in valid_calls}]
            if invalid:
                messages = []
                for call in invalid:
                    observation = _invalid_observation(call)
                    self._attach_call_result(call, observation, None)
                    messages.append(ToolMessage(
                        content=json.dumps(observation, ensure_ascii=False, allow_nan=False),
                        tool_call_id=call.get("id"), name=(call.get("function") or {}).get("name"),
                        status="error"))
                    self.hooks.result["corrections"].append({
                        "round": self.current_round, "kind": "tool_error",
                        "tool": (call.get("function") or {}).get("name")})
                self.purpose = "repair"
                self.correction = "tool_error"
                return {"messages": messages, "correction": "tool_error"}
            self.purpose = "answer"
            return None
        if raw_calls and not valid_calls:
            messages = []
            for call in raw_calls:
                observation = _invalid_observation(call)
                self._attach_call_result(call, observation, None)
                messages.append(ToolMessage(
                    content=json.dumps(observation, ensure_ascii=False, allow_nan=False),
                    tool_call_id=call.get("id"), name=(call.get("function") or {}).get("name"),
                    status="error"))
                self.hooks.result["corrections"].append({
                    "round": self.current_round, "kind": "tool_error",
                    "tool": (call.get("function") or {}).get("name")})
            if self.current_round >= self.hooks.max_rounds:
                return {"messages": messages, "jump_to": "end", "limit_finalize": True}
            self.purpose = "repair"
            self.correction = "tool_error"
            return {"messages": messages, "correction": "tool_error", "jump_to": "model"}
        accepted = self.hooks.validate_final(response, self.hooks.state.context)
        if accepted == "incomplete_text":
            # One existing no-tool synthesis, not an open-ended repair loop.
            entry["parse_error_code"] = accepted
            self.hooks.result["finalize_trigger"] = "incomplete_text"
            return {"jump_to": "end"}
        if not isinstance(accepted, str):
            text, checked, context = accepted
            entry.update(final_prose=True, parsed_action={"action": "final_answer"})
            return {"jump_to": "end", "accepted_text": text,
                    "accepted_check": deepcopy(checked),
                    "accepted_context": deepcopy(context)}
        entry["parse_error_code"] = accepted
        self.hooks.result["corrections"].append({"round": self.current_round, "kind": accepted})
        if self.current_round >= self.hooks.max_rounds:
            return {"jump_to": "end", "limit_finalize": True}
        self.purpose = "repair"
        self.correction = accepted
        message = HumanMessage(content=json.dumps({
            "request": "correct_current_turn", "error": accepted,
            "instruction": "Correct this output or tool error within the same loop. Use native tools or a complete prose answer; no action/facts JSON. Keep the original question and current allowed_refs."},
            ensure_ascii=False, allow_nan=False))
        updates = {"messages": [message], "correction": accepted, "jump_to": "model"}
        if not last.content and not last.tool_calls and last.id:
            updates["messages"] = [RemoveMessage(id=last.id), message]
        return updates

    def wrap_model_call(self, request, handler):
        self.hooks.model._purpose = self.purpose
        entry = {
            "phase": "react_loop", "purpose": self.purpose,
            "repair_kind": self.correction,
            "autonomous_step": self.current_round,
            "remaining_steps": max(0, self.hooks.max_rounds - self.current_round),
            "limit_finalize": False,
            "messages": deepcopy(self.current_request),
            "allowed_refs": list(self.current_allowed_refs),
            "allowed_citation_ids": list(self.current_allowed_ids),
            "response": None, "parsed_action": None,
            "parse_error_code": None, "error": None,
            "sdk_attempt_numbers": [],
        }
        self.hooks.result["action_steps"].append(entry)
        self.current_entry = entry
        try:
            return handler(request)
        except Exception as failure:
            entry["error"] = {
                "status": getattr(failure, "status", "tool_error"),
                "code": getattr(failure, "code", "model_call_error"),
                "attempts": deepcopy(getattr(failure, "attempts", [])),
            }
            raise
        finally:
            entry["sdk_attempt_numbers"] = [
                row["number"] for row in
                self.hooks.budget.records[self.current_start:]]

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        name = call.get("name")
        entry = self.current_entry
        call_entry = next((row for row in (entry or {}).get("tool_calls", [])
                           if row.get("id") == call.get("id")), None)
        if request.tool is None:
            observation = {
                "status": "unknown_tool",
                "message": "工具不可用；使用当前已提供工具或根据现有原文回答。"}
            self._attach_call_result(call_entry, observation, {"action": name})
            self.hooks.result["corrections"].append({
                "round": self.current_round, "kind": "tool_error", "tool": name})
            self.purpose = "repair"
            self.correction = "tool_error"
            self.tool_error = True
            return ToolMessage(content=json.dumps(observation, ensure_ascii=False, allow_nan=False),
                               tool_call_id=call.get("id"), name=name, status="error")
        if name in ("search", "read_context"):
            self.hooks.result["evidence_calls_used"] += 1
        args = call.get("args")
        if isinstance(args, dict) and INVALID_TOOL_ARGS in args:
            observation = _invalid_observation({
                "function": {"name": name, "arguments": args[INVALID_TOOL_ARGS]}})
            self._attach_call_result(call_entry, observation, None)
            self.hooks.result["corrections"].append({
                "round": self.current_round, "kind": "tool_error", "tool": name})
            self.purpose = "repair"
            self.correction = "tool_error"
            self.tool_error = True
            return ToolMessage(
                content=json.dumps(observation, ensure_ascii=False, allow_nan=False),
                tool_call_id=call.get("id"), name=name, status="error")
        self.hooks.set_stage("read_context" if name == "read_context" else "react_loop")
        self.hooks.state.current_round = self.current_round
        if self.hooks.budget.remaining_seconds() <= FINALIZE_RESERVE_SECONDS:
            observation = {"status": "budget_exceeded", "error": {
                "code": "deadline_exceeded",
                "message": "本轮已进入收尾窗口，停止新的工具探索。"}}
            self._attach_call_result(call_entry, observation, None)
            self.hooks.result["finalize_trigger"] = "deadline_reserve"
            self.hooks.result["deadline_reserve"] = {
                "stage": "tool",
                "remaining_seconds": round(self.hooks.budget.remaining_seconds(), 6),
                "reserve_seconds": FINALIZE_RESERVE_SECONDS,
                "action": "skip_tool_call",
            }
            return ToolMessage(
                content=json.dumps(observation, ensure_ascii=False, allow_nan=False),
                tool_call_id=call.get("id"), name=name, status="error")
        try:
            result = handler(request)
        except Exception as failure:
            observation = {"status": "tool_error", "error": {
                "code": getattr(failure, "code", "tool_execution_error"),
                "message": "本次工具未完成，已有原文保留；可修正请求或利用已有材料回答。"}}
            self._attach_call_result(call_entry, observation, None)
            self.hooks.result["corrections"].append({
                "round": self.current_round, "kind": "tool_error", "tool": name})
            self.purpose = "repair"
            self.correction = "tool_error"
            self.tool_error = True
            return ToolMessage(content=json.dumps(observation, ensure_ascii=False, allow_nan=False),
                               tool_call_id=call.get("id"), name=name, status="error")
        observation = deepcopy(self.hooks.state.last_observation)
        parsed = deepcopy(self.hooks.state.last_parsed_action)
        if not isinstance(observation, dict):
            try:
                observation = json.loads(result.content) if isinstance(result, ToolMessage) else {}
            except (TypeError, ValueError):
                observation = {}
        self._attach_call_result(call_entry, observation, parsed)
        if observation.get("status") in ("tool_error", "invalid_arguments", "unknown_tool"):
            self.hooks.result["corrections"].append({
                "round": self.current_round, "kind": "tool_error", "tool": name})
            self.purpose = "repair"
            self.correction = "tool_error"
            self.tool_error = True
        self.hooks.result["context"] = deepcopy(self.hooks.state.context)
        return result

    def _attach_call_result(self, call, observation, parsed):
        if call is None:
            return
        if parsed is not None:
            call["parsed_action"] = parsed
        call["tool_observation"] = deepcopy(observation)


EvidenceMiddleware.before_model.__can_jump_to__ = ["end", "model"]


def _invalid_observation(call):
    name = (call.get("function") or {}).get("name")
    return {"status": "invalid_arguments", "error": {
        "code": "invalid_action_schema",
        "message": f"工具 {name or 'unknown'} 参数无效，请使用当前工具字段与可用入口。"}}


def run_evidence_graph(hooks: GraphHooks):
    """Run one create_agent invocation and return its final graph state."""
    middleware = EvidenceMiddleware(hooks)
    graph = create_agent(
        model=hooks.model,
        tools=list(hooks.tools.values()),
        system_prompt=hooks.system_prompt,
        middleware=[middleware],
        state_schema=EvidenceGraphState,
        name=GRAPH_VERSION,
    )
    config = {
        "max_concurrency": 1,
        "recursion_limit": max(1000, (hooks.max_rounds + 2) * 8),
        "metadata": {"d4_graph": GRAPH_VERSION},
    }
    return graph.invoke({"messages": []}, config=config)
