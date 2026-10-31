"""Autonomous search/answer or legacy retrieval, shared budgets and citations.

The caller owns searcher/store/client. No environment, client or library opens
here; no answer is published until the current context's citations pass.
"""

from copy import deepcopy
import json
from math import isfinite
from pathlib import Path

from paper_assistant.agent_actions import (
    ACTION_SCHEMA_VERSION, AUTONOMOUS_ACTION_SCHEMA_VERSION, ActionParseError, AnswerAction, PrepareAnswerAction, InsufficientEvidenceAction, RetrySearchAction, SearchAction,
    action_to_answer_draft, parse_agent_action, query_comparison_key,
    search_tool_definition, parse_search_tool_call, read_context_tool_definition, parse_read_context_call,
    run_javascript_tool_definition, parse_run_javascript_call,
)
from paper_assistant.agent_context import (
    AGENT_SELECTION_VERSION, merge_agent_context, merge_planned_context, validate_search_round,
)
from paper_assistant.agent_prompt import (
    AGENT_PROMPT_VERSION, AUTONOMOUS_PROMPT_VERSION, PROSE_FINAL_PROMPT_VERSION, SCOPED_AGENT_PROMPT_VERSION,
    build_action_repair_messages, build_agent_messages, build_react_messages,
    build_prose_final_messages, build_prose_repair_messages,
)
from paper_assistant.agent_records import diagnostic_snapshot
from paper_assistant.citations import validate_citations, validate_prose_citations
from paper_assistant.js_runtime import JavaScriptError, RUNTIME_VERSION, run_javascript
from paper_assistant.prose import EvidenceRegistry, normalize_citation_markers, parse_markers, prompt_sources, source_refs
from paper_assistant.context import ContextError, restore_conversation_evidence, token_context_options, fit_autonomous_context
from paper_assistant.conversation import normalize_planned_queries
from paper_assistant.evidence_reading import (read_evidence_context, parent_children, reading_directory,
    retain_explicit_context)
from paper_assistant.paper_information import load_paper_information
from paper_assistant.llm_client import LLMCallError
from paper_assistant.message_fit import context_fit_budget, count_request_tokens
from paper_assistant.schemas import answer_evidence_status
from paper_assistant.search import SearchError
from paper_assistant.rerank_statistics import empty_rerank_statistics, sum_rerank_statistics
from paper_assistant.deadline import DeadlineExceeded, final_deadline, search_with_budget
from paper_assistant.source_scope import (
    Registry, SourceScopeError, identify_source_requirement, merge_scoped_context, merge_planned_scoped_context,
    prepare_scoped_context, prepare_unavailable_source_context, validate_citation_scope,
    validate_prose_citation_scope,
)


AGENT_VERSION = "d13-prose-compute-agent-v1"
SCOPED_AGENT_VERSION = "d13-prose-compute-source-scope-budget-agent-v1"
TIMED_AGENT_VERSION = "d13-prose-compute-budget-agent-v1"


def _embedding_totals(rounds):
    """Sum independent actual round statistics; unknown usage remains null."""
    stats = [row["statistics"] if isinstance(row.get("statistics"), dict) else {} for row in rounds]
    result = {"retrieval_rounds": len(rounds)}
    for field in ("embedding_requests", "failed_requests", "total_tokens"):
        values = [row.get(field) for row in stats]
        valid = [type(v) is int and v >= 0 for v in values]
        result[field] = sum(values) if all(valid) and values else (0 if not values and field != "total_tokens" else None)
        result["known_" + field] = sum(v for v, ok in zip(values, valid) if ok)
    result["usage_complete"] = bool(stats) and all(type(row.get("total_tokens")) is int
                                                   and row["total_tokens"] >= 0 for row in stats)
    for field in ("provider_elapsed_seconds", "embedding_elapsed_seconds",
                  "query_elapsed_seconds", "total_elapsed_seconds"):
        values = [row.get(field) for row in stats]
        valid = [type(v) in (int, float) and isfinite(v) and v >= 0 for v in values]
        total = sum(values) if values and all(valid) else None
        result[field] = round(total, 6) if total is not None and isfinite(total) else None
    return result


def fit_agent_request(context, messages, *, context_length, max_tokens,
                      native_search=False, native_javascript=False, protect_groups=1):
    """Trim complete history groups or whole evidence chunks to fit capacity."""
    tools = []
    if native_search:
        tools.extend([search_tool_definition(), read_context_tool_definition()])
    if native_javascript:
        tools.append(run_javascript_tool_definition())
    tools = tools or None
    budget = context_fit_budget(context_length, max_tokens)

    def payload_of(message):
        if not isinstance(message, dict) or message.get("role") != "user":
            return None
        try:
            payload = json.loads(message["content"])
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def payload_ids(payload):
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

    def sync(payloads_to_sync):
        retained = []
        for message in messages[1:]:
            payload = payload_of(message)
            for identifier in payload_ids(payload):
                if identifier not in retained:
                    retained.append(identifier)
        shown = [row for row in context["shown_evidence"] if row["chunk_id"] in retained]
        allowed = [row["chunk_id"] for row in shown]
        existing = [row for row in context.get("omitted_evidence", [])
                    if row.get("chunk_id") not in retained]
        dropped = [{"chunk_id": row["chunk_id"], "rank": row["rank"], "reason": "token_budget"}
                   for row in context["shown_evidence"] if row["chunk_id"] not in retained]
        omitted = existing + dropped
        context.update(shown_evidence=shown, allowed_citation_ids=allowed,
                       shown_chars=sum(len(row["shown_text"]) for row in shown),
                       omitted_evidence=omitted, candidate_count=len(shown) + len(omitted),
                       max_chars=None,
                       reading_origins=[origin for origin in context.get("reading_origins", [])
                           if origin.get("chunk_id") in retained],
                       empty_selection_reason=None if shown else
                           ("no_hits" if not shown and not omitted else "character_budget"))
        if "allowed_refs" in context:
            context["allowed_refs"] = [row["ref"] for row in shown]
        for message in messages:
            payload = payload_of(message)
            if payload is not None and ("allowed_citation_ids" in payload or "allowed_refs" in payload):
                if "allowed_citation_ids" in payload:
                    payload["allowed_citation_ids"] = list(allowed)
                if "allowed_refs" in payload:
                    payload["allowed_refs"] = [row["ref"] for row in shown]
                message["content"] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        return shown, dropped

    def remove_original(identifier):
        # Evict the same original from replay and final sources together; a
        # leftover duplicate must not silently keep an evicted ref authorized.
        for message in messages[1:]:
            payload = payload_of(message)
            if payload is None:
                continue
            for field in ("shown_evidence", "sources"):
                if isinstance(payload.get(field), list):
                    payload[field] = [row for row in payload[field] if row.get("chunk_id") != identifier]
            if isinstance(payload.get("evidence_sections"), list):
                for section in payload["evidence_sections"]:
                    section["chunks"] = [row for row in section.get("chunks", []) if row.get("chunk_id") != identifier]
                payload["evidence_sections"] = [section for section in payload["evidence_sections"] if section["chunks"]]
            message["content"] = json.dumps(payload, ensure_ascii=False, allow_nan=False)

    dropped_ids = []

    def sync_and_record():
        _shown, dropped = sync([])
        for row in dropped:
            if row["chunk_id"] not in dropped_ids:
                dropped_ids.append(row["chunk_id"])

    def user_groups():
        starts = [index for index, message in enumerate(messages)
                  if index > 0 and message.get("role") == "user"]
        return [(start, starts[index + 1] if index + 1 < len(starts) else len(messages))
                for index, start in enumerate(starts)]

    while count_request_tokens(messages, tools) > budget:
        groups = user_groups()
        if len(groups) > protect_groups:
            drop = set(range(groups[0][0], groups[0][1]))
            messages[:] = [message for index, message in enumerate(messages) if index == 0 or index not in drop]
            sync_and_record()
            continue
        changed = False
        for message in messages[1:]:
            payload = payload_of(message)
            if payload is None:
                continue
            sections = payload.get("evidence_sections")
            if isinstance(sections, list) and sections:
                for section in sections:
                    chunks = section.get("chunks") if isinstance(section, dict) else None
                    if chunks:
                        remove_original(chunks[0]["chunk_id"])
                        changed = True
                        break
                if changed:
                    break
            rows = payload.get("shown_evidence") or payload.get("sources")
            if isinstance(rows, list) and rows:
                remove_original(rows[0]["chunk_id"])
                changed = True
                break
        if not changed:
            for message in messages[1:]:
                payload = payload_of(message)
                if payload is None:
                    continue
                locations = payload.get("candidate_locations")
                if isinstance(locations, list) and locations:
                    locations.pop(0)
                    message["content"] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
                    changed = True
                    break
                for paper in payload.get("selected_papers") or []:
                    directory = paper.get("reading_directory") if isinstance(paper, dict) else None
                    if directory:
                        directory.pop(0)
                        message["content"] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
                        changed = True
                        break
                if changed:
                    break
        if not changed:
            raise ContextError("request_too_large", "完整请求在裁剪后仍超过模型上下文容量")
        sync_and_record()
    sync_and_record()
    return messages, dropped_ids


def answer_question_agent(query, selected_versions, searcher, store, client, *,
                          project_root: Path, top_k=5, max_chars=8000, source_registry=None, enforce_remaining_budget=False,
                          conversation_context=None, autonomous_steps=None) -> dict:
    """Opt into autonomous decisions, or retain the caller's legacy retrieval.

    Create the caller's ChatBudget before initial retrieval. The same budget
    must cover this entire run. D9 opt-in forwards its live remaining time.
    """
    timed = bool(enforce_remaining_budget or source_registry is not None)
    result = {"status": "tool_error", "query": query if isinstance(query, str) else None,
              "selected_versions": [], "top_k": top_k if type(top_k) is int else None,
              "max_chars": max_chars if type(max_chars) is int else None,
              "agent_version": SCOPED_AGENT_VERSION if source_registry is not None else (TIMED_AGENT_VERSION if timed else AGENT_VERSION),
              "action_schema_version": ACTION_SCHEMA_VERSION,
              "prompt_version": SCOPED_AGENT_PROMPT_VERSION if source_registry is not None else AGENT_PROMPT_VERSION,
              "selection_version": AGENT_SELECTION_VERSION,
              "search": None, "context": None, "initial_context": None,
              "search_rounds": [], "action_steps": [], "merge_trace": None,
              "citation_checks": [], "answer": None, "error": None,
              "failure_stage": "input", "stop_reason": None, "interrupted_failure": None,
              "retry_decision": None, "paper_information": [], "semantic_support_status": "not_reviewed",
              "javascript_calls": [], "javascript_runtime": RUNTIME_VERSION,
              "statistics": {"embedding": None, "chat": None, "rerank": empty_rerank_statistics()}}
    stage = "input"
    budget = client.budget
    requirement, qualification, source_issue = None, None, None
    paper_information, version_chunks = [], {}
    accessible_parents = set()
    seen_evidence_ids = set()
    full_context = autonomous_steps is not None
    evidence_registry = EvidenceRegistry()
    if full_context and source_registry is not None:
        source_registry.full_context_mode = True
    context_options = {} if full_context else token_context_options(registry=source_registry)
    if autonomous_steps is not None:
        result.update(retrieval_strategy="autonomous", autonomous_step_limit=autonomous_steps,
                      autonomous_steps_used=0, limit_finalize=False, evidence_calls_used=0, context_reads=[],
                      prompt_version=AUTONOMOUS_PROMPT_VERSION, action_schema_version=AUTONOMOUS_ACTION_SCHEMA_VERSION,
                      loop_version="react-native-tools-v1", agent_version="d14-native-tool-loop-agent-v1",
                      corrections=[], synthesis=None, recovery=None)
    if source_registry is not None:
        result.update(source_requirement=None, source_qualification=None,
                      initial_source_qualification=None, source_scope_checks=[])

    if timed:
        result["budget_implementation_version"] = "react-iteration-and-invoke-retry-v1" if full_context else "d9-remaining-budget-v1"
        result["deadline_enforcement"] = "remaining_chat_timeout_and_retrieval_budget_adapter_and_stage_checks; hard_process_abort_unverified"

    def deadline():
        if budget.remaining_seconds() <= 0:
            raise LLMCallError("budget_exceeded", "deadline_exceeded", "本轮截止预算已到，停止后续步骤")

    def capacity():
        deadline()
        if budget.policy.max_attempts is not None and budget.attempts >= budget.policy.max_attempts:
            raise LLMCallError("budget_exceeded", "request_limit", "本轮没有剩余聊天请求额度")

    def finish():
        if full_context:
            result["evidence_registry"] = evidence_registry.snapshot()
        if budget.remaining_seconds() <= 0:
            if result["error"] and result["error"]["code"] != "deadline_exceeded":
                result["interrupted_failure"] = {"status": result["status"],
                                                 "failure_stage": result["failure_stage"],
                                                 "error": deepcopy(result["error"])}
            result.update(status="budget_exceeded", answer=None, failure_stage=stage,
                          stop_reason="deadline_exceeded",
                          error={"code": "deadline_exceeded", "message": "本轮步骤结束时截止预算已到"})
        result["statistics"]["embedding"] = _embedding_totals(result["search_rounds"])
        result["statistics"]["rerank"] = sum_rerank_statistics(
            row.get("rerank_statistics") for row in result["search_rounds"])
        result["statistics"]["chat"] = deepcopy(budget.statistics())
        return result

    def fail(status, code, message):
        result.update(status=status, answer=None, error={"code": code, "message": message},
                      failure_stage=stage, stop_reason=code)
        return finish()

    def failed_retrieval_deadline(entry):
        if budget.remaining_seconds() <= 0:
            result["interrupted_failure"] = {"status": "tool_error", "failure_stage": stage,
                                             "error": deepcopy(entry["error"])}
        deadline()

    def retrieve(text, number, *, allowed_point_ids=None, selected_pairs=None, kind=None, prepare=True):
        deadline()
        search_pairs = pairs if selected_pairs is None else selected_pairs
        entry = {"round": number, "kind": kind or ("initial" if number == 1 else "retry"),
                 "query": text, "selected_versions": [{"paper_id": p, "parse_revision": r} for p, r in search_pairs],
                 "top_k": top_k, "status": "pending", "search": None,
                 "statistics": None, "rerank_statistics": empty_rerank_statistics(),
                 "error": None, "diagnostic_replacements": []}
        result["search_rounds"].append(entry)
        try:
            search = search_with_budget(searcher, text, deepcopy(search_pairs), top_k=top_k,
                         allowed_point_ids=allowed_point_ids,
                         remaining_seconds=budget.remaining_seconds if timed else None)
        except SearchError as error:
            safe_statistics, replacements = diagnostic_snapshot(error.statistics)
            entry.update(status=error.status, statistics=safe_statistics,
                         rerank_statistics=deepcopy(getattr(error, "rerank_statistics", empty_rerank_statistics())),
                         diagnostic_replacements=[{"source": "statistics", **row} for row in replacements],
                         error={"code": error.code, "message": "本轮证据检索失败",
                                "stage": error.stage if error.stage in
                                ("input", "configuration", "ready", "embedding", "query", "evidence") else "retrieval"})
            failed_retrieval_deadline(entry)
            raise
        except DeadlineExceeded:
            entry.update(status="budget_exceeded",
                         statistics={"embedding_requests": 0, "failed_requests": 0, "total_tokens": None},
                         error={"code": "deadline_exceeded", "message": "本轮检索发送前截止预算已到"})
            raise
        except Exception:
            entry.update(status="tool_error", error={"code": "local_search_error", "message": "本轮证据检索失败"})
            failed_retrieval_deadline(entry)
            raise ContextError("local_search_error", "本轮证据检索失败") from None
        safe_search, replacements = diagnostic_snapshot(search)
        entry["search"] = safe_search
        entry["diagnostic_replacements"] = [{"source": "search", **row} for row in replacements]
        if isinstance(search, dict):
            entry["statistics"], stats_replacements = diagnostic_snapshot(search.get("statistics"))
            entry["rerank_statistics"] = deepcopy(search.get("rerank_statistics") or empty_rerank_statistics())
            entry["diagnostic_replacements"].extend({"source": "statistics", **row} for row in stats_replacements)
            entry["status"] = search.get("status") if search.get("status") in ("success", "no_hits") else "invalid_response"
        deadline()
        try:
            context = validate_search_round(search, text, search_pairs, top_k=top_k, max_chars=max_chars, **context_options)
        except ContextError as error:
            entry.update(status="tool_error", error={"code": error.code, "message": str(error)})
            raise
        scoped_qualification = None
        if not prepare:
            return safe_search, context, None
        if source_registry is not None and number == 1:
            scoped = prepare_scoped_context(search, requirement, source_registry, max_chars=max_chars, **context_options)
            context, scoped_qualification = scoped["context"], scoped["qualification"]
            entry["source_qualification"] = deepcopy(scoped_qualification)
        if number == 1:
            context = restore_conversation_evidence(context, conversation_context, version_chunks,
                max_chunks=None, source_registry=source_registry, source_requirement=requirement)
            context = read_evidence_context(context, version_chunks, store=store, max_chunks=None,
                source_registry=source_registry, source_requirement=requirement)
            entry["reading_origins"] = deepcopy(context["reading_origins"])
            if scoped_qualification is not None:
                scoped_qualification["shown_ids"] = deepcopy(context["allowed_citation_ids"])
                entry["source_qualification"] = deepcopy(scoped_qualification)
        deadline()
        if not context["shown_evidence"]:
            context["evidence_limitation"] = ("本轮没有可展示的核定摘要证据。" if requirement is not None
                and requirement["required_scope"] == "abstract" else "本轮没有可展示的论文证据。")
        # Validation above used original values. Only the recorded envelope
        # uses markers for noncanonical metadata, never the evidence context.
        return safe_search, context, scoped_qualification

    def fit_request(context, messages, native_search, *, native_javascript=False, protect_groups=1):
        return fit_agent_request(
            context, messages,
            context_length=getattr(client.settings, "context_length", None),
            max_tokens=client.policy.max_tokens,
            native_search=native_search, native_javascript=native_javascript,
            protect_groups=protect_groups)
    def request_action(context, phase, *, repair_kind=None, previous=None, error_code=None,
                       field_issues=None):
        """Legacy Action/Claim entry; interactive native prose never enters here."""
        nonlocal stage
        kind, repair_base = repair_kind, None
        while True:
            stage = ("citation_repair" if kind == "citation" else "action_repair") if kind else phase
            capacity()
            if kind and budget.repairs >= budget.policy.max_repairs:
                raise LLMCallError("invalid_output", "repair_unavailable", "本轮共享修复额度已耗尽")
            terminal_only = kind == "citation"
            messages = (build_action_repair_messages(query, context, previous, phase=phase,
                error_code=error_code, repair_kind=kind, field_issues=field_issues,
                paper_information=paper_information, conversation_context=conversation_context,
                base_messages=repair_base,
                **({"source_requirement": requirement} if requirement is not None else {})) if kind else
                build_agent_messages(query, context, phase=phase, terminal_only=terminal_only,
                    paper_information=paper_information, conversation_context=conversation_context,
                    **({"source_requirement": requirement} if requirement is not None else {})))
            entry = {"phase": phase, "purpose": "repair" if kind else "answer", "repair_kind": kind,
                "terminal_only": terminal_only, "messages": deepcopy(messages),
                "allowed_citation_ids": deepcopy(context["allowed_citation_ids"]),
                "response": None, "parsed_action": None, "parse_error_code": None,
                "parse_error_fields": [], "error": None, "sdk_attempt_numbers": []}
            result["action_steps"].append(entry)
            start = len(budget.records)
            try:
                response = client.invoke(messages, purpose=entry["purpose"], require_json=True)
            except LLMCallError as error:
                entry["error"] = {"status": error.status, "code": error.code,
                    "message": str(error), "attempts": deepcopy(error.attempts)}
                raise
            finally:
                entry["sdk_attempt_numbers"] = [row["number"] for row in budget.records[start:]]
            entry["response"] = deepcopy(response)
            deadline()
            try:
                if response.get("status") != "success":
                    raise ActionParseError(response.get("output_issue") or "invalid_output")
                action = parse_agent_action(response.get("content"), phase=phase,
                    has_shown_evidence=bool(context["shown_evidence"]), terminal_only=terminal_only,
                    selected_versions=result["selected_versions"])
            except ActionParseError as error:
                entry.update(parse_error_code=error.code, parse_error_fields=deepcopy(error.field_issues))
                if kind or budget.repairs >= budget.policy.max_repairs:
                    raise LLMCallError("invalid_output", error.code, "模型动作在共享修复后仍未通过检查") from None
                capacity()
                repair_base = deepcopy(messages)
                kind = "action" if error.code == "action_not_allowed" else "format"
                error_code, field_issues, previous = error.code, error.field_issues, response.get("content")
                continue
            entry["parsed_action"] = action.model_dump(mode="json")
            deadline()
            return action

    def publish(action, context, phase):
        nonlocal stage
        for turn in range(2):
            stage = "citations" if not turn else "citation_recheck"
            deadline()
            draft = action_to_answer_draft(action).model_dump(mode="json")
            checked = validate_citations(draft, context, store, project_root=project_root)
            result["citation_checks"].append(deepcopy(checked))
            source_invalid = False
            if source_registry is not None:
                scoped_check = validate_citation_scope(draft, context, qualification, source_registry,
                                                       requirement=requirement)
                result["source_scope_checks"].append(deepcopy(scoped_check))
                if scoped_check["status"] == "tool_error" or (checked["status"] == "valid" and scoped_check["status"] != "valid"):
                    checked = scoped_check
                    source_invalid = True
            if checked["status"] != "valid" and budget.remaining_seconds() <= 0:
                result["interrupted_failure"] = {"status": checked["status"], "failure_stage": stage,
                                                 "error": deepcopy(checked.get("error"))}
            deadline()
            if checked["status"] == "valid":
                limitation = context.get("evidence_limitation")
                if limitation and result.get("retrieval_strategy") == "planned_queries":
                    draft["reason"] = "\n".join(part for part in (draft.get("reason"), limitation) if part)
                elif limitation and not draft.get("reason"):
                    draft["reason"] = limitation
                result.update(status=draft["status"], failure_stage=None, error=None,
                              answer={**draft, "evidence_refs": deepcopy(checked["evidence_refs"]),
                                      "evidence_sources": deepcopy(checked["evidence_sources"]),
                                      "evidence_status": answer_evidence_status(draft),
                                      "semantic_support_status": "not_reviewed"})
                if result["stop_reason"] is None:
                    result["stop_reason"] = (("step_limit_answered" if result["limit_finalize"] else "answered")
                        if autonomous_steps is not None else
                        ("answer_validated" if draft["status"] == "answered" else "model_insufficient_evidence"))
                return finish()
            if checked["status"] == "tool_error":
                error = checked["error"]
                return fail("tool_error", error["code"], error["message"])
            if turn:
                return fail("invalid_output", "source_scope_invalid" if source_invalid else "citation_invalid",
                            "修复后引用或来源检查仍未通过")
            if budget.repairs >= budget.policy.max_repairs:
                return fail("invalid_output", "source_scope_invalid" if source_invalid else "citation_invalid",
                            "引用或来源检查未通过，且本轮没有剩余修复额度")
            capacity()
            action = request_action(context, phase, repair_kind="citation",
                                    previous=result["action_steps"][-1]["response"]["content"],
                                    error_code="source_scope_invalid" if source_invalid else "citation_invalid")
        return fail("invalid_output", "citation_invalid", "引用检查未通过")

    def publish_prose(text, checked, context, phase):
        nonlocal stage
        stage = "citations"
        citations = deepcopy(checked.get("citations") or [])
        answer = {"text": text, "citations": citations,
                  "evidence_refs": deepcopy(checked.get("evidence_refs") or []),
                  "evidence_sources": deepcopy(checked.get("evidence_sources") or []),
                  "evidence_status": "paper_only" if citations else "none",
                  "semantic_support_status": "not_reviewed"}
        result.update(status="answered", failure_stage=None, error=None, answer=answer,
                      answer_format="prose_citations_v1", final_prompt_version=(AUTONOMOUS_PROMPT_VERSION
                          if phase in ("react_loop", "recovery") else PROSE_FINAL_PROMPT_VERSION))
        if result["stop_reason"] is None:
            result["stop_reason"] = ("step_limit_answered" if result["limit_finalize"] else "answered")
        return finish()

    def _final_sources(messages, refs):
        payload = {}
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            try:
                candidate = json.loads(message["content"])
            except (TypeError, ValueError):
                continue
            if isinstance(candidate, dict) and "sources" in candidate:
                payload = candidate
                break
        kept = {row.get("ref") for row in payload.get("sources") or [] if isinstance(row, dict)}
        return [row for row in refs if row["ref"] in kept], sorted(kept)

    def execute_javascript(call):
        try:
            parsed = parse_run_javascript_call(call)
            call["parsed_action"] = {"action": "run_javascript", "code": parsed.code}
            try:
                outcome = run_javascript(parsed.code)
                result["javascript_calls"].append({
                    "status": "success", "elapsed_seconds": outcome["elapsed_seconds"],
                    "stdout_chars": outcome["stdout_chars"],
                    "v8_version": outcome.get("v8_version")})
                return {"status": "success", **outcome}
            except JavaScriptError as error:
                observation = {"status": "tool_error",
                               "error": {"code": error.code, "message": str(error)}}
                result["javascript_calls"].append(deepcopy(observation))
                return observation
        except ActionParseError as error:
            return {"status": "invalid_arguments", "error": {"code": error.code,
                "message": "工具参数无效；run_javascript 只接受非空 code。"}}

    def request_prose_final(context, phase, *, prepared_messages=None, prepared_response=None,
                            preparation=None):
        evidence_registry.stamp(context)
        refs = source_refs(context, evidence_registry)
        sources = prompt_sources(refs)
        missing = ((preparation or {}).get("missing_information")
                   or context.get("evidence_limitation"))
        base = build_prose_final_messages(query, context, sources=sources, phase=phase,
            prepared_messages=prepared_messages, prepared_response=prepared_response,
            conversation_context=conversation_context, source_requirement=requirement,
            missing_information=missing)
        previous, error_code, actual_refs, actual_numbers = None, None, refs, [row["ref"] for row in refs]
        attempt = 0
        while True:
            if attempt:
                if budget.repairs >= budget.policy.max_repairs:
                    raise LLMCallError("invalid_output", "repair_unavailable", "本轮共享修复额度已耗尽")
                messages = build_prose_repair_messages(
                    fitted, previous, error_code=error_code, allowed_refs=actual_numbers)
            else:
                messages = deepcopy(base)
            native_javascript = (full_context and not attempt
                                 and result["autonomous_steps_used"] < autonomous_steps)
            if not native_javascript:
                messages[0]["content"] += "\nNo tools are available in this request. Return the final answer using the provided originals and any completed calculations."
            if full_context:
                messages, dropped_ids = fit_request(context, messages, False,
                    native_javascript=native_javascript, protect_groups=3)
                if dropped_ids:
                    seen_evidence_ids.difference_update(dropped_ids)
                result["context"] = deepcopy(context)
            actual_refs, actual_numbers = _final_sources(messages, refs)
            deadline()
            entry = {"phase": phase, "purpose": "repair" if attempt else "answer",
                     "repair_kind": "citation" if attempt and error_code in
                         ("citation_unknown_ref", "citation_not_shown", "source_constraint_ambiguous",
                          "citation_source_scope_mismatch") else ("format" if attempt else None),
                     "terminal_only": not native_javascript, "final_prose": True,
                     "messages": deepcopy(messages), "allowed_refs": list(actual_numbers),
                     "allowed_citation_ids": [row["chunk_id"] for row in actual_refs],
                     "response": None, "parsed_action": None, "parse_error_code": error_code,
                     "parse_error_fields": [], "error": None, "sdk_attempt_numbers": []}
            result["action_steps"].append(entry)
            start = len(budget.records)
            try:
                response = client.invoke(messages, purpose=entry["purpose"], require_json=False,
                    **({"tools": [run_javascript_tool_definition()], "tool_choice": "auto"}
                       if native_javascript else {}))
            except LLMCallError as error:
                entry["error"] = {"status": error.status, "code": error.code,
                                  "message": str(error), "attempts": deepcopy(error.attempts)}
                raise
            finally:
                entry["sdk_attempt_numbers"] = [row["number"] for row in budget.records[start:]]
            entry["response"] = deepcopy(response)
            deadline()
            if response.get("status") != "success":
                error_code = response.get("output_issue") or "invalid_output"
                previous = response.get("content") or ""
                if attempt or budget.repairs >= budget.policy.max_repairs:
                    raise LLMCallError("invalid_output", error_code, "最终正文生成未产生完整结果")
                fitted = deepcopy(messages)
                attempt = 1
                continue
            if response.get("tool_calls") and native_javascript:
                result["autonomous_steps_used"] += 1
                entry.update(autonomous_step=result["autonomous_steps_used"],
                             remaining_steps=autonomous_steps - result["autonomous_steps_used"],
                             tool_calls=deepcopy(response["tool_calls"]))
                base = deepcopy(messages)
                base.append({"role": "assistant", "content": response.get("content"),
                             "tool_calls": deepcopy(response["tool_calls"])})
                for call in entry["tool_calls"]:
                    observation = execute_javascript(call)
                    call["tool_observation"] = deepcopy(observation)
                    base.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(observation, ensure_ascii=False, allow_nan=False)})
                    deadline()
                if result["autonomous_steps_used"] >= autonomous_steps:
                    result["limit_finalize"] = True
                continue
            text = normalize_citation_markers(response.get("content") or "")
            checked = validate_prose_citations(text, actual_refs, context, store,
                                               project_root=project_root)
            result["citation_checks"].append(deepcopy(checked))
            if source_registry is not None:
                scoped = validate_prose_citation_scope(checked.get("citations") or [], context,
                                                       qualification, source_registry, requirement=requirement)
                result["source_scope_checks"].append(deepcopy(scoped))
                if scoped["status"] != "valid":
                    checked = scoped
            if checked["status"] == "valid":
                return text, checked
            error_code = (checked.get("error") or {}).get("code") or "citation_invalid"
            previous = text
            if attempt or budget.repairs >= budget.policy.max_repairs:
                raise LLMCallError("invalid_output", error_code,
                                   "最终正文引用或来源检查未通过")
            fitted = deepcopy(messages)
            attempt = 1

    def answer_with_limitation(context, reason, stop_reason):
        nonlocal qualification
        deadline()
        if context is None:
            scoped = prepare_unavailable_source_context(query, pairs, requirement, source_registry,
                                                       reason, max_chars=max_chars, **context_options)
            context, qualification = scoped["context"], scoped["qualification"]
            result["source_qualification"] = deepcopy(qualification)
        else:
            context = {**deepcopy(context), "evidence_limitation": reason}
        result.update(context=deepcopy(context), stop_reason=stop_reason)
        text, checked = request_prose_final(context, "final_decision")
        return publish_prose(text, checked, context, "final_decision")

    def run_autonomous():
        nonlocal stage, qualification
        searches, query_indices, seen_queries, recalled_ids = [], [], set(), set()
        explicit_rows, known_candidates = {}, {}
        required_rows, target_ids = [], []
        saved_chunks = {row["chunk_id"]: row for rows in version_chunks.values() for row in rows}

        def merge_current():
            nonlocal qualification
            merged = (merge_planned_scoped_context(searches, query, pairs, source_registry,
                        max_chars=max_chars, **context_options, max_chunks=None, requirement=requirement,
                        query_indices=query_indices, round_kind="adaptive") if source_registry is not None else
                      merge_planned_context(searches, query, pairs, max_chars=max_chars, **context_options,
                                            max_chunks=None, query_indices=query_indices, round_kind="adaptive"))
            context = restore_conversation_evidence(merged["context"], conversation_context, version_chunks,
                max_chunks=None, source_registry=source_registry, source_requirement=requirement)
            context = read_evidence_context(context, version_chunks, store=store, max_chunks=None, anchors_first=True,
                source_registry=source_registry, source_requirement=requirement)
            if explicit_rows or required_rows:
                context = retain_explicit_context(context, list(explicit_rows.values()), source_registry=source_registry,
                    target_ids=target_ids, required_rows=required_rows)
            omission_reasons = {row["chunk_id"]: row["reason"] for row in
                [*merged["trace"].get("count_omitted", []), *merged["context"]["omitted_evidence"], *context["omitted_evidence"]]}
            if requirement is not None and requirement["required_scope"] == "abstract":
                omission_reasons.update({identifier: "source_scope" for identifier, row in known_candidates.items()
                                         if not source_registry.qualify(row)["eligible"]})
            context = fit_autonomous_context(context, paper_information, list(known_candidates.values()),
                                             omission_reasons=omission_reasons, evidence_registry=evidence_registry)
            # Only actual displayed originals and real tool returns grant chunk-reading access.
            for row in context["shown_evidence"]:
                known_candidates.setdefault(row["chunk_id"], {**deepcopy(row), "text": row["shown_text"]})
            if source_issue:
                context["evidence_limitation"] = source_issue[1]
            elif not context["shown_evidence"]:
                context["evidence_limitation"] = "当前没有可展示的论文证据，不能编造论文事实或引用。"
            merged["trace"].update(final_shown_ids=deepcopy(context["allowed_citation_ids"]),
                                   reading_origins=deepcopy(context["reading_origins"]))
            result.update(context=deepcopy(context), merge_trace=deepcopy(merged["trace"]))
            if source_registry is not None:
                qualification = merged["qualification"]
                qualification["shown_ids"] = deepcopy(context["allowed_citation_ids"])
                result["source_qualification"] = deepcopy(qualification)
            return context

        def execute_search(action, number):
            nonlocal stage, context
            search_pairs = [(row.paper_id, row.parse_revision) for row in action.selected_versions]
            key = (query_comparison_key(action.query), frozenset(search_pairs))
            observation = {"status": "duplicate", "returned_ids": [], "new_returned_ids": [],
                           "shown_ids": deepcopy(context["allowed_citation_ids"]), "new_shown_ids": []}
            if key in seen_queries:
                observation["message"] = "同查询与同版本范围已执行，未重复检索；可调整查询或论文范围。"
            else:
                seen_queries.add(key)
                before_shown = set(context["allowed_citation_ids"])
                stage = "adaptive_retrieval"
                round_number = len(result["search_rounds"]) + 1
                try:
                    search, _, _ = retrieve(action.query, round_number, selected_pairs=search_pairs,
                                            kind="adaptive", prepare=False)
                except (SearchError, ContextError):
                    # The existing retrieval record owns the failure and actual
                    # usage. Keep the current evidence for the next decision.
                    observation.update(status="tool_error",
                        error=deepcopy(result["search_rounds"][-1]["error"]),
                        message="本次检索失败，已有证据保留；可调整方向或基于现有证据回答。")
                else:
                    searches.append(search)
                    known_candidates.update({row["chunk_id"]: deepcopy(row) for row in search["results"]})
                    query_indices.append(round_number)
                    stage = "adaptive_merge_context"
                    context = merge_current()
                    if result["search"] is None:
                        result["search"] = deepcopy(search)
                    returned = [row["chunk_id"] for row in search["results"]]
                    shown = context["allowed_citation_ids"]
                    new_shown = [identifier for identifier in shown if identifier not in before_shown]
                    observation.update(status=("no_hits" if not returned else
                                               "success" if new_shown else "no_new_shown_evidence"),
                                       returned_ids=returned,
                                       new_returned_ids=[identifier for identifier in returned
                                                         if identifier not in recalled_ids],
                                       shown_ids=deepcopy(shown), new_shown_ids=new_shown)
                    observation["candidate_locations"] = [deepcopy(row) for row in context.get("candidate_locations", [])
                                                          if row["chunk_id"] in returned]
                    recalled_ids.update(returned)
                row = result["search_rounds"][-1]
                row.update(autonomous_step=number, observation=deepcopy(observation),
                           new_returned_ids=deepcopy(observation["new_returned_ids"]),
                           new_shown_ids=deepcopy(observation["new_shown_ids"]))
            return observation

        def execute_read(action):
            nonlocal context, stage, target_ids
            stage = "read_context"
            observation = {**action.model_dump(mode="json", exclude_none=True), "status": "tool_error",
                           "returned_ids": [], "shown_ids": [], "new_shown_ids": [],
                           "not_shown_ids": [], "visible_chunks": []}
            result["context_reads"].append(observation)
            try:
                if action.chunk_id is not None:
                    if action.chunk_id not in known_candidates or action.chunk_id not in saved_chunks:
                        raise ValueError("unavailable_chunk")
                    children = [deepcopy(saved_chunks[action.chunk_id])]
                    source = children[0]
                else:
                    if action.parent_id not in accessible_parents:
                        raise ValueError("unavailable_parent")
                    source, children = parent_children(action.parent_id, version_chunks, store)
                if source_issue:
                    raise ValueError("source_scope_unavailable")
                eligible = [row for row in children if requirement is None or requirement["required_scope"] != "abstract"
                            or source_registry.qualify(row)["eligible"]]
                if not eligible:
                    raise ValueError("source_scope_unavailable")
                before = set(context["allowed_citation_ids"])
                target_ids = [row["chunk_id"] for row in eligible]
                for row in eligible:
                    origin = {"kind": "explicit_chunk_read" if action.chunk_id is not None else "explicit_parent_read",
                              "chunk_id": row["chunk_id"]}
                    if row.get("parent_id"):
                        origin["parent_id"] = row["parent_id"]
                    if action.missing_information is not None:
                        origin["missing_information"] = action.missing_information
                    row["reading_origins"] = [origin]
                    explicit_rows.pop(row["chunk_id"], None)
                    explicit_rows[row["chunk_id"]] = row
                    known_candidates[row["chunk_id"]] = deepcopy(row)
                context = merge_current()
                shown = {r["chunk_id"]: r for r in context["shown_evidence"]}
                shown_ids = [identifier for identifier in target_ids if identifier in shown]
                new_ids = [identifier for identifier in shown_ids if identifier not in before]
                observation.update(status="success" if new_ids else "no_new_shown_evidence",
                    paper_id=source["paper_id"], parse_revision=source["parse_revision"],
                    section_path=deepcopy(source.get("section_path", [])), returned_ids=target_ids,
                    shown_ids=shown_ids, new_shown_ids=new_ids,
                    not_shown_ids=[r["chunk_id"] for r in children if r["chunk_id"] not in shown],
                    candidate_locations=[deepcopy(row) for row in context.get("candidate_locations", [])
                                         if row["chunk_id"] in target_ids],
                    visible_chunks=[deepcopy(shown[identifier]) for identifier in shown_ids])
            except (ValueError, KeyError, SourceScopeError) as error:
                code = getattr(error, "code", None)
                if code is None:
                    code = str(error) if str(error) in ("unavailable_chunk", "unavailable_parent", "source_scope_unavailable") else "unavailable_read_target"
                observation["error"] = {"code": code,
                    "message": "阅读目标不可用或不符合当前来源范围，已有证据保留。"}
            return observation

        context = merge_current()
        result["initial_context"] = deepcopy(context)
        if source_registry is not None:
            result["initial_source_qualification"] = deepcopy(qualification)
        # RAGFlow agentic_rag/agent.go: one native tool/prose loop. Tool
        # failures are observations; only a completed tool-free output is final.
        history, correction, validated_final = [], None, None

        def accept(response, entry):
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
            checked = validate_prose_citations(text, source_refs(context, evidence_registry), context, store,
                                               project_root=project_root)
            result["citation_checks"].append(deepcopy(checked))
            if source_registry is not None:
                scoped = validate_prose_citation_scope(checked.get("citations") or [], context,
                    qualification, source_registry, requirement=requirement)
                result["source_scope_checks"].append(deepcopy(scoped))
                if scoped["status"] != "valid":
                    checked = scoped
            if checked["status"] != "valid":
                return (checked.get("error") or {}).get("code") or "citation_invalid"
            entry.update(final_prose=True, parsed_action={"action": "final_answer"})
            return text, checked, deepcopy(context)

        def invoke_turn(number, *, synthesis=False):
            nonlocal stage
            stage = "synthesis" if synthesis else "react_loop"
            evidence_registry.stamp(context)
            new_ids = [row["chunk_id"] for row in context["shown_evidence"] if row["chunk_id"] not in seen_evidence_ids]
            messages = build_react_messages(query, context, paper_information=paper_information,
                conversation_context=conversation_context, history=[] if synthesis else history,
                remaining_rounds=max(0, autonomous_steps - number),
                new_evidence_ids=new_ids, synthesis=synthesis, source_requirement=requirement)
            if synthesis:
                # Keep completed local calculations; never recover process text,
                # a preparation envelope or an answer from input history.
                calculations = [call["tool_observation"] for step in result["action_steps"]
                    for call in step.get("tool_calls", [])
                    if (call.get("function") or {}).get("name") == "run_javascript"
                    and (call.get("tool_observation") or {}).get("status") == "success"]
                payload = json.loads(messages[-1]["content"])
                payload["completed_calculations"] = calculations
                messages[-1]["content"] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            elif correction:
                messages.append({"role": "user", "content": json.dumps({
                    "request": "correct_current_turn", "error": correction,
                    "instruction": "Correct this output or tool error within the same loop. Use native tools or a complete prose answer; no action/facts JSON. Keep the original question and current allowed_refs."},
                    ensure_ascii=False)})
            messages, dropped = fit_request(context, messages, not synthesis, native_javascript=not synthesis)
            seen_evidence_ids.update(new_ids)
            seen_evidence_ids.difference_update(dropped)
            result["context"] = deepcopy(context)
            for message in messages[1:]:
                if message.get("role") != "user":
                    continue
                payload = json.loads(message["content"])
                accessible_parents.update(d["parent_id"] for p in payload.get("selected_papers", [])
                                          for d in p.get("reading_directory", []))
            accessible_parents.update(row["parent_id"] for row in context["shown_evidence"] if row.get("parent_id"))
            entry = {"phase": stage, "purpose": "synthesis" if synthesis else "repair" if correction else "answer",
                "repair_kind": correction, "autonomous_step": number,
                "remaining_steps": max(0, autonomous_steps - number), "limit_finalize": synthesis,
                "messages": deepcopy(messages), "allowed_refs": list(context["allowed_refs"]),
                "allowed_citation_ids": list(context["allowed_citation_ids"]),
                "response": None, "parsed_action": None, "parse_error_code": None,
                "error": None, "sdk_attempt_numbers": []}
            result["action_steps"].append(entry)
            start = len(budget.records)
            try:
                response = client.invoke(messages, purpose=entry["purpose"], require_json=False,
                    **({"request_timeout": 90.0} if synthesis else {"tools": [search_tool_definition(),
                        read_context_tool_definition(), run_javascript_tool_definition()], "tool_choice": "auto"}))
                entry["response"] = deepcopy(response)
                return response, entry, messages
            except LLMCallError as error:
                entry["error"] = {"status": error.status, "code": error.code,
                    "attempts": deepcopy(error.attempts)}
                raise
            finally:
                entry["sdk_attempt_numbers"] = [row["number"] for row in budget.records[start:]]

        def finalize(trigger, error=None):
            if validated_final is not None:
                result["recovery"] = {"kind": "validated_final", "trigger": trigger, "model_requests": 0}
                result["stop_reason"] = "recovered_final_answer"
                return publish_prose(*validated_final, "recovery")
            # Nonretryable authentication/configuration failures cannot be cured
            # by another model call. A stopped/expired caller is not detached.
            if error is not None and (getattr(error, "code", "") in
                    ("configuration_error", "client_closed", "invalid_input", "deadline_exceeded", "request_limit")
                    or any(a.get("http_status") in (401, 403) for a in getattr(error, "attempts", []))):
                return fail(error.status, error.code, str(error))
            result["limit_finalize"] = trigger == "iteration_limit"
            result["synthesis"] = {"trigger": trigger, "status": "attempted", "timeout_seconds": 90.0}
            try:
                response, entry, _ = invoke_turn(result["autonomous_steps_used"], synthesis=True)
                accepted = accept(response, entry)
                if isinstance(accepted, str):
                    entry["parse_error_code"] = accepted
                    result["synthesis"]["status"] = "invalid_output"
                    return fail("invalid_output", accepted, "无工具综合未产生有效正文或引用")
                result["synthesis"]["status"] = "completed"
                result["stop_reason"] = "iteration_limit_synthesized" if trigger == "iteration_limit" else "error_synthesized"
                return publish_prose(*accepted, "synthesis")
            except LLMCallError as failure:
                result["synthesis"]["status"] = "failed"
                return fail(failure.status, failure.code, str(failure))
            except Exception as failure:
                result["synthesis"]["status"] = "failed"
                return fail("tool_error", getattr(failure, "code", "synthesis_local_error"), "无工具综合未完成")

        try:
            for number in range(1, autonomous_steps + 1):
                result["autonomous_steps_used"] = number
                response, entry, messages = invoke_turn(number)
                history[:] = deepcopy(messages[1:])
                calls = response.get("tool_calls") or []
                if response.get("status") == "success" and calls:
                    entry["tool_calls"] = deepcopy(calls)
                    history.append({"role": "assistant", "content": response.get("content"), "tool_calls": deepcopy(calls)})
                    correction = None
                    for call in entry["tool_calls"]:
                        name = (call.get("function") or {}).get("name")
                        try:
                            if name == "run_javascript":
                                observation = execute_javascript(call)
                            elif name == "read_context":
                                result["evidence_calls_used"] += 1
                                parsed = parse_read_context_call(call)
                                call["parsed_action"] = {"action": name, **parsed.model_dump(mode="json", exclude_none=True)}
                                observation = execute_read(parsed)
                            elif name == "search":
                                result["evidence_calls_used"] += 1
                                parsed = parse_search_tool_call(call, selected_versions=result["selected_versions"])
                                call["parsed_action"] = parsed.model_dump(mode="json")
                                observation = execute_search(parsed, number)
                            else:
                                observation = {"status": "unknown_tool", "message": "工具不可用；使用当前已提供工具或根据现有原文回答。"}
                        except ActionParseError as failure:
                            observation = {"status": "invalid_arguments", "error": {"code": failure.code,
                                "message": "工具字段或所选版本范围无效，请修正参数。"}}
                        except Exception as failure:
                            observation = {"status": "tool_error", "error": {"code": getattr(failure, "code", "tool_execution_error"),
                                "message": "本次工具未完成，已有原文保留；可修正请求或利用已有材料回答。"}}
                        if "shown_ids" in observation:
                            wanted = set(observation["shown_ids"])
                            observation["shown_refs"] = [{"ref": row["ref"], "chunk_id": row["chunk_id"]}
                                for row in context["shown_evidence"] if row["chunk_id"] in wanted]
                        if observation.get("status") in ("tool_error", "invalid_arguments", "unknown_tool"):
                            correction = "tool_error"
                            result["corrections"].append({"round": number, "kind": correction, "tool": name})
                        call["tool_observation"] = deepcopy(observation)
                        reply = {k: deepcopy(v) for k, v in observation.items() if k not in ("visible_chunks", "candidate_locations")}
                        history.append({"role": "tool", "tool_call_id": call["id"],
                            "content": json.dumps(reply, ensure_ascii=False, allow_nan=False)})
                    continue
                accepted = accept(response, entry)
                if not isinstance(accepted, str):
                    validated_final = accepted
                    return publish_prose(*accepted, "react_loop")
                correction = accepted
                entry["parse_error_code"] = accepted
                result["corrections"].append({"round": number, "kind": accepted})
                if response.get("content"):
                    history.append({"role": "assistant", "content": response["content"]})
            return finalize("iteration_limit")
        except LLMCallError as error:
            result["interrupted_failure"] = {"status": error.status, "code": error.code, "stage": stage}
            return finalize(error.code, error)
        except Exception as error:
            result["interrupted_failure"] = {"status": "tool_error", "code": getattr(error, "code", "local_error"), "stage": stage}
            return finalize(getattr(error, "code", "local_error"))

    try:
        if not isinstance(query, str) or not query.strip():
            raise ContextError("invalid_question", "问题必须为非空字符串")
        if type(top_k) is not int or top_k != 5:
            raise ContextError("invalid_top_k", "D8 首轮与补轮 top_k 必须为 5")
        if type(max_chars) is not int or not 1 <= max_chars <= 8000:
            raise ContextError("invalid_character_budget", "正文字符预算必须为 1–8000 的整数")
        if autonomous_steps is not None and (type(autonomous_steps) is not int or autonomous_steps <= 0):
            raise ContextError("invalid_autonomous_steps", "自主循环轮数必须为正整数")
        if full_context:
            max_chars = None
            result["max_chars"] = None
            result["context_capacity_mode"] = "full_request"
        if not isinstance(selected_versions, list) or not 1 <= len(selected_versions) <= 3:
            raise ContextError("invalid_versions", "必须选择 1–3 个完整论文/处理版本配对")
        pairs = []
        for pair in selected_versions:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or any(not isinstance(v, str) or not v.strip() or v != v.strip() for v in pair)
                    or tuple(pair) in pairs):
                raise ContextError("invalid_versions", "论文/处理版本配对非法或重复")
            pairs.append(tuple(pair))
        result["selected_versions"] = [{"paper_id": p, "parse_revision": r} for p, r in pairs]
        planned_queries = (normalize_planned_queries(conversation_context["planned_queries"], query,
                           result["selected_versions"]) if conversation_context is not None
                           and "planned_queries" in conversation_context else [])
        if planned_queries:
            result["planned_queries"] = deepcopy(planned_queries)
            if autonomous_steps is None:
                result["retrieval_strategy"] = "planned_queries" if len(planned_queries) > 1 else "single_query"
        if not full_context and ((budget.policy.max_attempts is not None and budget.policy.max_attempts > 3) or (budget.policy.max_repairs is None or budget.policy.max_repairs > 1)
                or budget.policy.max_network_retries > 1 or budget.policy.request_timeout > 30
                or (budget.policy.total_timeout is not None and
                    (budget.policy.total_timeout > 120 or budget.deadline - budget.started > 120))):
            raise ContextError("invalid_agent_budget", "Agent 调用预算超过 D8 冻结上限")
        if source_registry is not None:
            stage = "source_scope"
            if not isinstance(source_registry, Registry) or not set(pairs).issubset(set(source_registry.pairs)):
                raise SourceScopeError("source_registry_scope_mismatch", "来源表与所选完整版本不一致")
            source_registry.revalidate()
            requirement = identify_source_requirement(query)
            result["source_requirement"] = deepcopy(requirement)
            deadline()
            if requirement["resolution"] == "ambiguous":
                source_issue = ("source_constraint_ambiguous", "原问题的摘要限定存在歧义，当前没有可用于该限定的论文证据。")
            elif requirement["required_scope"] == "abstract" and not source_registry.has_qualified_abstract(pairs):
                source_issue = ("source_scope_unavailable", "所选版本尚无核定且完整可用的摘要证据范围。")
        stage = "paper_information"
        version_chunks = {pair: store.get_version_chunks(*pair) for pair in pairs}
        context_options = token_context_options(registry=source_registry,
            candidates=[row for chunks in version_chunks.values() for row in chunks])
        paper_information = load_paper_information(store, pairs, source_registry,
                                                  version_chunks=version_chunks)
        if autonomous_steps is not None:
            directory = reading_directory(store, pairs)
            for paper in paper_information:
                pair = (paper["paper_id"], paper["parse_revision"])
                paper["reading_directory"] = directory[pair]
                paper["_chunk_order"] = [row["chunk_id"] for row in version_chunks[pair]]
        result["paper_information"] = deepcopy(paper_information)
        deadline()
        if autonomous_steps is not None:
            return run_autonomous()
        if source_issue:
            return answer_with_limitation(None, source_issue[1], source_issue[0])
        if len(planned_queries) > 1:
            searches, gaps, query_indices = [], [], []
            stage = "planned_retrieval"
            for number, plan in enumerate(planned_queries, 1):
                plan_pairs = [(v["paper_id"], v["parse_revision"]) for v in plan["selected_versions"]]
                try:
                    search, _, _ = retrieve(plan["query"], number, selected_pairs=plan_pairs,
                                            kind="planned", prepare=False)
                except (SearchError, ContextError):
                    # The round already owns its actual failure and usage. Keep
                    # other queries' evidence and continue within this budget.
                    gaps.append(f"计划查询 {number}（{plan['query']}）检索失败。")
                    continue
                searches.append(search)
                query_indices.append(number)
            stage = "planned_merge_context"
            merged = (merge_planned_scoped_context(searches, query, pairs, source_registry,
                        max_chars=max_chars, **context_options, max_chunks=None, requirement=requirement,
                        query_indices=query_indices) if source_registry is not None else
                        merge_planned_context(searches, query, pairs, max_chars=max_chars, **context_options,
                                              max_chunks=None, query_indices=query_indices))
            context = restore_conversation_evidence(merged["context"], conversation_context, version_chunks,
                max_chunks=None, source_registry=source_registry, source_requirement=requirement)
            context = read_evidence_context(context, version_chunks, store=store, max_chunks=None, anchors_first=True,
                source_registry=source_registry, source_requirement=requirement)
            shown = set(context["allowed_citation_ids"])
            for row in result["search_rounds"]:
                search = row.get("search")
                if row["status"] in ("success", "no_hits") and search is not None:
                    if not any(item["chunk_id"] in shown for item in search["results"]):
                        gaps.append(f"计划查询 {row['round']}（{row['query']}）没有进入最终上下文的原文证据。")
            if gaps:
                context["evidence_limitation"] = "本轮部分信息需求未取得可用原文，不能声称完整查证：\n" + "\n".join(gaps)
            merged["trace"].update(final_shown_ids=deepcopy(context["allowed_citation_ids"]),
                                   reading_origins=deepcopy(context["reading_origins"]))
            result.update(search=deepcopy(searches[0]) if searches else None,
                          context=deepcopy(context), merge_trace=deepcopy(merged["trace"]))
            if source_registry is not None:
                qualification = merged["qualification"]
                qualification["shown_ids"] = deepcopy(context["allowed_citation_ids"])
                result["source_qualification"] = deepcopy(qualification)
            deadline()
            action = request_action(context, "final_decision")
            return publish(action, context, "final_decision")
        stage = "initial_retrieval"
        if planned_queries:
            plan = planned_queries[0]
            plan_pairs = [(v["paper_id"], v["parse_revision"]) for v in plan["selected_versions"]]
            search, _, _ = retrieve(plan["query"], 1, selected_pairs=plan_pairs, kind="planned", prepare=False)
            prepared = (merge_planned_scoped_context([search], query, pairs, source_registry,
                max_chars=max_chars, **context_options, max_chunks=None, requirement=requirement) if source_registry is not None else
                merge_planned_context([search], query, pairs, max_chars=max_chars, **context_options, max_chunks=None))
            context = restore_conversation_evidence(prepared["context"], conversation_context, version_chunks,
                max_chunks=None, source_registry=source_registry, source_requirement=requirement)
            context = read_evidence_context(context, version_chunks, store=store, max_chunks=None,
                source_registry=source_registry, source_requirement=requirement)
            qualification = prepared.get("qualification")
            if qualification is not None:
                qualification["shown_ids"] = deepcopy(context["allowed_citation_ids"])
            result["search_rounds"][0]["reading_origins"] = deepcopy(context["reading_origins"])
            if not context["shown_evidence"]:
                context["evidence_limitation"] = "本轮没有可展示的论文证据。"
        else:
            search, context, qualification = retrieve(query, 1)
        result.update(search=deepcopy(search), context=deepcopy(context), initial_context=deepcopy(context))
        if source_registry is not None:
            result.update(source_qualification=deepcopy(qualification), initial_source_qualification=deepcopy(qualification))
        action = request_action(context, "initial_decision")
        if not isinstance(action, RetrySearchAction):
            return publish(action, context, "initial_decision")
        stage = "retry_gate"
        result["retry_decision"] = {"missing_information": action.missing_information,
                                    "retry_query": action.retry_query, "executed": False}
        deadline()
        if query_comparison_key(action.retry_query) == query_comparison_key(search["query"]):
            return answer_with_limitation(context, "补查查询与已执行问题相同，未执行重复检索。", "retry_query_unchanged")
        # A successful retry must still be followed by a final model decision.
        capacity()
        allowed_points = None
        if requirement is not None and requirement["required_scope"] == "abstract":
            stage = "source_retry_gate"
            allowed_points = source_registry.abstract_point_ids(search["index_profile_id"], pairs)
            deadline()
            if not allowed_points:
                return answer_with_limitation(context, "所选版本没有可检索的完整核定摘要片段。", "source_scope_unavailable")
        stage = "retry_retrieval"
        result["retry_decision"]["executed"] = True
        retried, _, _ = retrieve(action.retry_query, 2, allowed_point_ids=allowed_points)
        stage = "merge_context"
        deadline()
        if planned_queries:
            merged = (merge_planned_scoped_context([search, retried], query, pairs, source_registry,
                        max_chars=max_chars, **context_options, max_chunks=None, requirement=requirement, retry_first=True) if source_registry is not None else
                        merge_planned_context([search, retried], query, pairs,
                            max_chars=max_chars, **context_options, max_chunks=None, retry_first=True))
        else:
            merged = (merge_scoped_context(search, retried, query, pairs, source_registry,
                    max_chars=max_chars, **context_options, max_chunks=None, requirement=requirement) if source_registry is not None else
                    merge_agent_context(search, retried, query, pairs, max_chars=max_chars, **context_options, max_chunks=None))
        context = restore_conversation_evidence(merged["context"], conversation_context, version_chunks,
            max_chunks=None, source_registry=source_registry, source_requirement=requirement)
        context = read_evidence_context(context, version_chunks, store=store, max_chunks=None,
            source_registry=source_registry, source_requirement=requirement)
        merged["trace"].update(initial_shown_ids=deepcopy(result["initial_context"]["allowed_citation_ids"]),
                               final_shown_ids=deepcopy(context["allowed_citation_ids"]),
                               reading_origins=deepcopy(context["reading_origins"]),
                               new_shown_ids=[v for v in context["allowed_citation_ids"]
                                              if v not in result["initial_context"]["allowed_citation_ids"]])
        result.update(context=deepcopy(context), merge_trace=deepcopy(merged["trace"]))
        if source_registry is not None:
            qualification = merged["qualification"]
            qualification["shown_ids"] = deepcopy(context["allowed_citation_ids"])
            result["source_qualification"] = deepcopy(qualification)
        deadline()
        if not merged["trace"]["new_shown_ids"]:
            return answer_with_limitation(context, "补查未增加最终可展示证据，补充回答或分析须与论文结论区分。", "no_new_shown_evidence")
        action = request_action(context, "final_decision")
        return publish(action, context, "final_decision")
    except SearchError as error:
        return fail(error.status, error.code, "本轮证据检索失败")
    except DeadlineExceeded:
        return fail("budget_exceeded", "deadline_exceeded", "本轮检索前截止预算已到")
    except ContextError as error:
        return fail("tool_error", error.code, str(error))
    except SourceScopeError as error:
        return fail("tool_error", error.code, str(error))
    except ActionParseError as error:
        return fail("invalid_output", error.code, str(error))
    except LLMCallError as error:
        return fail(error.status, error.code, str(error))
    except Exception:
        return fail("tool_error", "local_error", "本轮 Agent 步骤未完成，详情见安全阶段记录")
