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
)
from paper_assistant.agent_context import (
    AGENT_SELECTION_VERSION, merge_agent_context, merge_planned_context, validate_search_round,
)
from paper_assistant.agent_prompt import (
    AGENT_PROMPT_VERSION, AUTONOMOUS_PROMPT_VERSION, SCOPED_AGENT_PROMPT_VERSION,
    build_action_repair_messages, build_agent_messages, build_prepared_final_messages,
)
from paper_assistant.agent_records import diagnostic_snapshot
from paper_assistant.citations import validate_citations
from paper_assistant.context import ContextError, restore_conversation_evidence, token_context_options, fit_autonomous_context
from paper_assistant.conversation import normalize_planned_queries
from paper_assistant.evidence_reading import (read_evidence_context, parent_children, reading_directory,
    retain_explicit_context)
from paper_assistant.paper_information import load_paper_information
from paper_assistant.llm_client import LLMCallError
from paper_assistant.schemas import answer_evidence_status
from paper_assistant.search import SearchError
from paper_assistant.rerank_statistics import empty_rerank_statistics, sum_rerank_statistics
from paper_assistant.deadline import DeadlineExceeded, final_deadline, search_with_budget
from paper_assistant.source_scope import (
    Registry, SourceScopeError, identify_source_requirement, merge_scoped_context, merge_planned_scoped_context,
    prepare_scoped_context, prepare_unavailable_source_context, validate_citation_scope,
)


AGENT_VERSION = "d12-basis-aware-agent-v1"
SCOPED_AGENT_VERSION = "d12-basis-aware-source-scope-budget-agent-v1"
TIMED_AGENT_VERSION = "d12-basis-aware-budget-agent-v1"


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
              "statistics": {"embedding": None, "chat": None, "rerank": empty_rerank_statistics()}}
    stage = "input"
    budget = client.budget
    requirement, qualification, source_issue = None, None, None
    paper_information, version_chunks = [], {}
    tool_history, accessible_parents = [], set()
    prepared_answer = None
    prepared_binding = None
    context_options = token_context_options(registry=source_registry)
    if autonomous_steps is not None:
        result.update(retrieval_strategy="autonomous", autonomous_step_limit=autonomous_steps,
                      autonomous_steps_used=0, limit_finalize=False, evidence_calls_used=0, context_reads=[],
                      prompt_version=AUTONOMOUS_PROMPT_VERSION, action_schema_version=AUTONOMOUS_ACTION_SCHEMA_VERSION)
    if source_registry is not None:
        result.update(source_requirement=None, source_qualification=None,
                      initial_source_qualification=None, source_scope_checks=[])

    if timed:
        result["budget_implementation_version"] = "d9-remaining-budget-v1"
        result["deadline_enforcement"] = "remaining_chat_timeout_and_retrieval_budget_adapter_and_stage_checks; hard_process_abort_unverified"

    def deadline():
        if budget.remaining_seconds() <= 0:
            raise LLMCallError("budget_exceeded", "deadline_exceeded", "本轮截止预算已到，停止后续步骤")

    def capacity():
        deadline()
        if budget.policy.max_attempts is not None and budget.attempts >= budget.policy.max_attempts:
            raise LLMCallError("budget_exceeded", "request_limit", "本轮没有剩余聊天请求额度")

    def finish():
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
                max_chunks=5, source_registry=source_registry, source_requirement=requirement)
            context = read_evidence_context(context, version_chunks, store=store, max_chunks=5,
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

    def request_action(context, phase, *, repair_kind=None, previous=None, error_code=None,
                       field_issues=None):
        nonlocal stage
        kind = repair_kind
        while True:
            stage = ("citation_repair" if kind == "citation" else "action_repair") if kind else phase
            capacity()
            if kind and budget.repairs >= budget.policy.max_repairs:
                raise LLMCallError("invalid_output", "repair_unavailable", "本轮共享修复额度已耗尽")
            terminal_only = (kind == "citation" or phase in ("limit_final_decision", "prepared_final_decision")
                             or (autonomous_steps is not None and result["autonomous_steps_used"] >= autonomous_steps))
            loop_state = None
            if autonomous_steps is not None and phase != "prepared_final_decision":
                loop_state = {
                    "autonomous_step_limit": autonomous_steps,
                    "autonomous_step": result["autonomous_steps_used"],
                    "remaining_steps": autonomous_steps - result["autonomous_steps_used"],
                    "limit_finalize": result["limit_finalize"],
                    "planned_queries": result.get("planned_queries", []),
                    "remaining_evidence_calls": max(0, autonomous_steps - result["evidence_calls_used"]),
                    "executed_actions": [{key: deepcopy(step.get(key)) for key in
                        ("autonomous_step", "parsed_action", "tool_observation", "tool_calls", "limit_finalize")}
                        for step in result["action_steps"]
                        if step.get("parsed_action") is not None or step.get("tool_calls")],
                }
            if loop_state is not None:
                for past in loop_state["executed_actions"]:
                    for call in past.get("tool_calls") or []:
                        call.get("tool_observation", {}).pop("visible_chunks", None)
                        call.get("tool_observation", {}).pop("candidate_locations", None)
            prepared_final = None
            if phase == "prepared_final_decision":
                prepared_final = build_prepared_final_messages(query, context, prepared_answer,
                    prepared_messages=(prepared_binding or {}).get("messages"),
                    prepared_response=((prepared_binding or {}).get("response") or {}).get("content"),
                    conversation_context=conversation_context,
                    source_requirement=requirement)
            if kind:
                messages = build_action_repair_messages(query, context, previous, phase=phase,
                    error_code=error_code, repair_kind=kind,
                    field_issues=field_issues,
                    paper_information=paper_information,
                    conversation_context=conversation_context,
                    loop_state=loop_state,
                    prepared_final_messages=prepared_final,
                    **({"source_requirement": requirement} if requirement is not None else {}))
            elif prepared_final is not None:
                messages = prepared_final
            else:
                messages = build_agent_messages(query, context, phase=phase, terminal_only=terminal_only,
                    paper_information=paper_information,
                    conversation_context=conversation_context,
                    loop_state=loop_state,
                    **({"source_requirement": requirement} if requirement is not None else {}))
            if loop_state is not None:
                payload = json.loads(messages[1]["content"])
                accessible_parents.update(entry["parent_id"] for paper in payload["selected_papers"]
                                          for entry in paper.get("reading_directory", []))
                accessible_parents.update(row["parent_id"] for row in context["shown_evidence"] if row.get("parent_id"))
                messages[1:1] = deepcopy(tool_history)
            native_search = (loop_state is not None and not terminal_only
                             and result["evidence_calls_used"] < autonomous_steps)
            deadline()
            entry = {"phase": phase, "purpose": "repair" if kind else "answer",
                     "repair_kind": kind, "terminal_only": terminal_only,
                     "messages": deepcopy(messages),
                     "allowed_citation_ids": deepcopy(context["allowed_citation_ids"]),
                     "response": None, "parsed_action": None, "parse_error_code": None,
                     "parse_error_fields": [],
                     "error": None, "sdk_attempt_numbers": []}
            if loop_state is not None:
                entry.update(autonomous_step=loop_state["autonomous_step"],
                             remaining_steps=loop_state["remaining_steps"],
                             limit_finalize=result["limit_finalize"], tool_observation=None)
            result["action_steps"].append(entry)
            start = len(budget.records)
            try:
                response = client.invoke(messages, purpose=entry["purpose"], require_json=True,
                    **({"tools": [search_tool_definition(), read_context_tool_definition()], "tool_choice": "auto"} if native_search else {}))
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
                if response.get("tool_calls") and native_search:
                    entry["tool_calls"] = deepcopy(response["tool_calls"])
                    return entry["tool_calls"]
                action = parse_agent_action(response.get("content"), phase=phase,
                                            has_shown_evidence=bool(context["shown_evidence"]),
                                            terminal_only=terminal_only or loop_state is not None,
                                            selected_versions=result["selected_versions"],
                                            prepare_answer=loop_state is not None)
            except ActionParseError as error:
                entry["parse_error_code"] = error.code
                entry["parse_error_fields"] = deepcopy(error.field_issues)
                deadline()
                # A completed repair that is still invalid stays invalid_output.
                # Request limits apply before another permitted call, not to
                # overwrite the observed result of the last consumed request.
                if kind or budget.repairs >= budget.policy.max_repairs:
                    raise LLMCallError("invalid_output", error.code, "模型动作在共享修复后仍未通过检查") from None
                capacity()
                kind = "action" if error.code in ("action_not_allowed", "paper_answer_requires_preparation") else "format"
                error_code = error.code
                field_issues = error.field_issues
                previous = response.get("content")
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
        action = request_action(context, "final_decision")
        return publish(action, context, "final_decision")

    def finalize_prepared(action, *, binding, no_direction_reason=None):
        nonlocal prepared_answer, prepared_binding
        prepared_answer = action.model_dump(mode="json")
        prepared_binding = deepcopy(binding)
        if no_direction_reason is not None:
            prepared_answer["missing_information"] = "\n".join(part for part in
                (prepared_answer["missing_information"], "No reliable further evidence direction: " + no_direction_reason) if part)
            result["stop_reason"] = "no_reliable_evidence_direction"
        final_context = deepcopy(binding["context"])
        result["context"] = deepcopy(final_context)
        final = request_action(final_context, "prepared_final_decision")
        return publish(final, final_context, "prepared_final_decision")

    def run_autonomous():
        nonlocal stage, qualification
        searches, query_indices, seen_queries, recalled_ids = [], [], set(), set()
        explicit_rows, known_candidates = {}, {}
        required_rows, target_ids = [], []
        pending_preparation, pending_binding = None, None
        saved_chunks = {row["chunk_id"]: row for rows in version_chunks.values() for row in rows}

        def bind_preparation():
            step = result["action_steps"][-1]
            return {"messages": deepcopy(step["messages"]), "response": deepcopy(step["response"]),
                    "context": deepcopy(context)}

        def merge_current():
            nonlocal qualification
            merged = (merge_planned_scoped_context(searches, query, pairs, source_registry,
                        max_chars=max_chars, **context_options, max_chunks=8, requirement=requirement,
                        query_indices=query_indices, round_kind="adaptive") if source_registry is not None else
                      merge_planned_context(searches, query, pairs, max_chars=max_chars, **context_options,
                                            max_chunks=8, query_indices=query_indices, round_kind="adaptive"))
            context = restore_conversation_evidence(merged["context"], conversation_context, version_chunks,
                max_chunks=8, source_registry=source_registry, source_requirement=requirement)
            context = read_evidence_context(context, version_chunks, store=store, max_chunks=8, anchors_first=True,
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
                                             omission_reasons=omission_reasons)
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
        for number in range(1, autonomous_steps + 1):
            result["autonomous_steps_used"] = number
            phase = ("gap_evidence_decision" if pending_preparation is not None and number < autonomous_steps
                     else "autonomous_decision")
            action = request_action(context, phase)
            if isinstance(action, PrepareAnswerAction):
                required_ids = {identifier for fact in action.facts for identifier in fact.citation_ids}
                required_rows = [{**deepcopy(row), "text": row["shown_text"]} for row in context["shown_evidence"]
                                 if row["chunk_id"] in required_ids]
                binding = bind_preparation()
                if (action.answerable or number >= autonomous_steps
                        or result["evidence_calls_used"] >= autonomous_steps):
                    if not action.answerable:
                        result["limit_finalize"] = True
                    return finalize_prepared(action, binding=binding)
                pending_preparation, pending_binding = action, binding
                continue
            if isinstance(action, InsufficientEvidenceAction):
                return finalize_prepared(pending_preparation, binding=pending_binding,
                                         no_direction_reason=action.reason)
            if isinstance(action, AnswerAction):
                # Autonomous parsing permits only uncited general knowledge here;
                # selected-paper answers must pass through finalize_prepared.
                return publish(action, context, "autonomous_decision")
            action_entry = result["action_steps"][-1]
            tool_history[:] = deepcopy(action_entry["messages"][1:])
            for message in tool_history:
                if message["role"] == "user":
                    old_payload = json.loads(message["content"])
                    if "question" in old_payload:
                        message["content"] = json.dumps({"question": old_payload["question"],
                            "autonomous_step": old_payload.get("autonomous_step")}, ensure_ascii=False)
            tool_history.append({"role": "assistant", "content": action_entry["response"].get("content"),
                                 "tool_calls": deepcopy(action_entry["response"]["tool_calls"])})
            for call in action:
                if result["evidence_calls_used"] >= autonomous_steps:
                    observation = {"status": "evidence_limit", "message": "search/read_context 共用取证额度已耗尽。"}
                else:
                    result["evidence_calls_used"] += 1
                    try:
                        if call["function"]["name"] == "read_context":
                            parsed = parse_read_context_call(call)
                            call["parsed_action"] = {"action": "read_context", **parsed.model_dump(mode="json", exclude_none=True)}
                            observation = execute_read(parsed)
                        else:
                            parsed = parse_search_tool_call(call, selected_versions=result["selected_versions"])
                            call["parsed_action"] = parsed.model_dump(mode="json")
                            observation = execute_search(parsed, number)
                    except ActionParseError as error:
                        observation = {"status": "invalid_arguments", "error": {"code": error.code,
                            "message": "工具参数无效；请使用当前工具字段与可用入口。"}}
                call["tool_observation"] = deepcopy(observation)
                # Original bodies live once in the current evidence_sections; the tool reply retains locations.
                if observation.get("new_shown_ids"):
                    pending_preparation, pending_binding = None, None
                # Candidate locations are budgeted once in the current evidence view.
                reply = {key: deepcopy(value) for key, value in observation.items()
                         if key not in ("visible_chunks", "candidate_locations")}
                tool_history.append({"role": "tool", "tool_call_id": call["id"],
                    "content": json.dumps(reply, ensure_ascii=False, allow_nan=False)})
                deadline()
            if result["evidence_calls_used"] >= autonomous_steps:
                break
        result["limit_finalize"] = True
        context = {**deepcopy(context), "evidence_limitation": "\n".join(part for part in (
            context.get("evidence_limitation"),
            "已达到自主决策或检索额度；请根据现有证据回答完整原问题，并明确尚未取得证据的部分。") if part)}
        result["context"] = deepcopy(context)
        result["autonomous_steps_used"] = min(autonomous_steps, result["autonomous_steps_used"] + 1)
        action = request_action(context, "limit_final_decision")
        if isinstance(action, PrepareAnswerAction):
            return finalize_prepared(action, binding=bind_preparation())
        return publish(action, context, "limit_final_decision")

    try:
        if not isinstance(query, str) or not query.strip():
            raise ContextError("invalid_question", "问题必须为非空字符串")
        if type(top_k) is not int or top_k != 5:
            raise ContextError("invalid_top_k", "D8 首轮与补轮 top_k 必须为 5")
        if type(max_chars) is not int or not 1 <= max_chars <= 8000:
            raise ContextError("invalid_character_budget", "正文字符预算必须为 1–8000 的整数")
        if autonomous_steps is not None and (type(autonomous_steps) is not int or not 1 <= autonomous_steps <= 5):
            raise ContextError("invalid_autonomous_steps", "自主决策步数必须为 1–5 的整数")
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
        if ((budget.policy.max_attempts is not None and budget.policy.max_attempts > 3) or budget.policy.max_repairs > 1
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
                        max_chars=max_chars, **context_options, max_chunks=8, requirement=requirement,
                        query_indices=query_indices) if source_registry is not None else
                        merge_planned_context(searches, query, pairs, max_chars=max_chars, **context_options,
                                              max_chunks=8, query_indices=query_indices))
            context = restore_conversation_evidence(merged["context"], conversation_context, version_chunks,
                max_chunks=8, source_registry=source_registry, source_requirement=requirement)
            context = read_evidence_context(context, version_chunks, store=store, max_chunks=8, anchors_first=True,
                source_registry=source_registry, source_requirement=requirement)
            shown = set(context["allowed_citation_ids"])
            for row in result["search_rounds"]:
                search = row.get("search")
                if row["status"] in ("success", "no_hits") and search is not None:
                    if not any(item["chunk_id"] in shown for item in search["results"]):
                        gaps.append(f"计划查询 {row['round']}（{row['query']}）没有进入最终上下文的原文证据。")
            if gaps:
                context["evidence_limitation"] = "本轮部分信息需求未取得可用原文，不能宣称完整查证：\n" + "\n".join(gaps)
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
                max_chars=max_chars, **context_options, max_chunks=5, requirement=requirement) if source_registry is not None else
                merge_planned_context([search], query, pairs, max_chars=max_chars, **context_options, max_chunks=5))
            context = restore_conversation_evidence(prepared["context"], conversation_context, version_chunks,
                max_chunks=5, source_registry=source_registry, source_requirement=requirement)
            context = read_evidence_context(context, version_chunks, store=store, max_chunks=5,
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
                        max_chars=max_chars, **context_options, max_chunks=8, requirement=requirement, retry_first=True) if source_registry is not None else
                        merge_planned_context([search, retried], query, pairs,
                            max_chars=max_chars, **context_options, max_chunks=8, retry_first=True))
        else:
            merged = (merge_scoped_context(search, retried, query, pairs, source_registry,
                    max_chars=max_chars, **context_options, max_chunks=8, requirement=requirement) if source_registry is not None else
                    merge_agent_context(search, retried, query, pairs, max_chars=max_chars, **context_options, max_chunks=8))
        context = restore_conversation_evidence(merged["context"], conversation_context, version_chunks,
            max_chunks=8, source_registry=source_registry, source_requirement=requirement)
        context = read_evidence_context(context, version_chunks, store=store, max_chunks=8,
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
