"""Per-question evidence state for the current native tool loop.

This is deliberately not a graph or persistence layer.  One instance belongs to
one answer_question_agent call; tools share it while the caller keeps the client,
budget and loop control.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Callable

from paper_assistant.agent_actions import (
    ActionParseError, parse_read_context_call, parse_run_javascript_call, parse_search_tool_call,
    query_comparison_key,
)
from paper_assistant.context import ContextError, fit_autonomous_context, restore_conversation_evidence
from paper_assistant.evidence_reading import parent_children, read_evidence_context, retain_explicit_context
from paper_assistant.js_runtime import JavaScriptError, run_javascript
from paper_assistant.search import SearchError
from paper_assistant.source_scope import (
    SourceScopeError, merge_planned_context, merge_planned_scoped_context,
)


_HELD_TOOL_FIELDS = {"visible_chunks", "candidate_locations"}
STATE_VERSION = "agent-evidence-state-v1"


@dataclass
class AgentEvidenceState:
    query: str
    pairs: list
    store: object
    version_chunks: dict
    paper_information: list
    source_registry: object | None
    requirement: dict | None
    source_issue: tuple | None
    top_k: int
    max_chars: int | None
    context_options: dict
    conversation_context: dict | None
    result: dict
    evidence_registry: object
    search_fn: Callable
    set_stage: Callable
    deadline: Callable
    searches: list = field(default_factory=list)
    query_indices: list = field(default_factory=list)
    seen_queries: set = field(default_factory=set)
    recalled_ids: set = field(default_factory=set)
    explicit_rows: dict = field(default_factory=dict)
    known_candidates: dict = field(default_factory=dict)
    required_rows: list = field(default_factory=list)
    target_ids: list = field(default_factory=list)
    accessible_parents: set = field(default_factory=set)
    context: dict | None = None
    qualification: dict | None = None
    current_round: int = 0
    tools: dict = field(default_factory=dict)
    last_observation: dict | None = None
    last_parsed_action: dict | None = None
    saved_chunks: dict = field(init=False)

    def __post_init__(self):
        self.saved_chunks = {row["chunk_id"]: row
                             for rows in self.version_chunks.values() for row in rows}

    def merge_current(self):
        """Merge tool-updated candidates and retain only actually visible originals."""
        merged = (merge_planned_scoped_context(
            self.searches, self.query, self.pairs, self.source_registry,
            max_chars=self.max_chars, **self.context_options, max_chunks=None,
            requirement=self.requirement, query_indices=self.query_indices,
            round_kind="adaptive") if self.source_registry is not None else
            merge_planned_context(
                self.searches, self.query, self.pairs, max_chars=self.max_chars,
                **self.context_options, max_chunks=None, query_indices=self.query_indices,
                round_kind="adaptive"))
        context = restore_conversation_evidence(
            merged["context"], self.conversation_context, self.version_chunks,
            max_chunks=None, source_registry=self.source_registry,
            source_requirement=self.requirement)
        context = read_evidence_context(
            context, self.version_chunks, store=self.store, max_chunks=None,
            anchors_first=True, source_registry=self.source_registry,
            source_requirement=self.requirement)
        if self.explicit_rows or self.required_rows:
            context = retain_explicit_context(
                context, list(self.explicit_rows.values()),
                source_registry=self.source_registry, target_ids=self.target_ids,
                required_rows=self.required_rows)
        omission_reasons = {row["chunk_id"]: row["reason"] for row in
            [*merged["trace"].get("count_omitted", []),
             *merged["context"]["omitted_evidence"], *context["omitted_evidence"]]}
        if (self.requirement is not None
                and self.requirement["required_scope"] == "abstract"
                and self.source_registry is not None):
            omission_reasons.update({
                identifier: "source_scope" for identifier, row in self.known_candidates.items()
                if not self.source_registry.qualify(row)["eligible"]})
        context = fit_autonomous_context(
            context, self.paper_information, list(self.known_candidates.values()),
            omission_reasons=omission_reasons, evidence_registry=self.evidence_registry)
        for row in context["shown_evidence"]:
            self.known_candidates.setdefault(
                row["chunk_id"], {**deepcopy(row), "text": row["shown_text"]})
        if self.source_issue:
            context["evidence_limitation"] = self.source_issue[1]
        elif not context["shown_evidence"]:
            context["evidence_limitation"] = "当前没有可展示的论文证据，不能编造论文事实或引用。"
        merged["trace"].update(final_shown_ids=deepcopy(context["allowed_citation_ids"]),
                               reading_origins=deepcopy(context["reading_origins"]))
        self.context = context
        self.result.update(context=deepcopy(context), merge_trace=deepcopy(merged["trace"]))
        if self.source_registry is not None:
            qualification = merged["qualification"]
            qualification["shown_ids"] = deepcopy(context["allowed_citation_ids"])
            self.qualification = qualification
            self.result["source_qualification"] = deepcopy(qualification)
        return context

    def execute_search(self, action, number):
        search_pairs = [(row.paper_id, row.parse_revision) for row in action.selected_versions]
        key = (query_comparison_key(action.query), frozenset(search_pairs))
        observation = {"status": "duplicate", "returned_ids": [], "new_returned_ids": [],
                       "shown_ids": deepcopy(self.context["allowed_citation_ids"]),
                       "new_shown_ids": []}
        if key in self.seen_queries:
            observation["message"] = "同查询与同版本范围已执行，未重复检索；可调整查询或论文范围。"
        else:
            self.seen_queries.add(key)
            before_shown = set(self.context["allowed_citation_ids"])
            self.set_stage("adaptive_retrieval")
            round_number = len(self.result["search_rounds"]) + 1
            try:
                search, _, _ = self.search_fn(
                    action.query, round_number, selected_pairs=search_pairs,
                    kind="adaptive", prepare=False)
            except (SearchError, ContextError):
                observation.update(
                    status="tool_error",
                    error=deepcopy(self.result["search_rounds"][-1]["error"]),
                    message="本次检索失败，已有证据保留；可调整方向或基于现有证据回答。")
            else:
                self.searches.append(search)
                self.known_candidates.update({
                    row["chunk_id"]: deepcopy(row) for row in search["results"]})
                self.query_indices.append(round_number)
                self.set_stage("adaptive_merge_context")
                self.context = self.merge_current()
                if self.result["search"] is None:
                    self.result["search"] = deepcopy(search)
                returned = [row["chunk_id"] for row in search["results"]]
                shown = self.context["allowed_citation_ids"]
                new_shown = [identifier for identifier in shown if identifier not in before_shown]
                observation.update(
                    status=("no_hits" if not returned else
                            "success" if new_shown else "no_new_shown_evidence"),
                    returned_ids=returned,
                    new_returned_ids=[identifier for identifier in returned
                                      if identifier not in self.recalled_ids],
                    shown_ids=deepcopy(shown), new_shown_ids=new_shown)
                observation["candidate_locations"] = [
                    deepcopy(row) for row in self.context.get("candidate_locations", [])
                    if row["chunk_id"] in returned]
                self.recalled_ids.update(returned)
            row = self.result["search_rounds"][-1]
            row.update(autonomous_step=number, observation=deepcopy(observation),
                       new_returned_ids=deepcopy(observation["new_returned_ids"]),
                       new_shown_ids=deepcopy(observation["new_shown_ids"]))
        return observation

    def execute_read(self, action):
        self.set_stage("read_context")
        observation = {**action.model_dump(mode="json", exclude_none=True),
                       "status": "tool_error", "returned_ids": [], "shown_ids": [],
                       "new_shown_ids": [], "not_shown_ids": [], "visible_chunks": []}
        self.result["context_reads"].append(observation)
        try:
            if action.chunk_id is not None:
                if (action.chunk_id not in self.known_candidates
                        or action.chunk_id not in self.saved_chunks):
                    raise ValueError("unavailable_chunk")
                children = [deepcopy(self.saved_chunks[action.chunk_id])]
                source = children[0]
            else:
                if action.parent_id not in self.accessible_parents:
                    raise ValueError("unavailable_parent")
                source, children = parent_children(
                    action.parent_id, self.version_chunks, self.store)
            if self.source_issue:
                raise ValueError("source_scope_unavailable")
            eligible = [row for row in children
                        if self.requirement is None
                        or self.requirement["required_scope"] != "abstract"
                        or self.source_registry.qualify(row)["eligible"]]
            if not eligible:
                raise ValueError("source_scope_unavailable")
            before = set(self.context["allowed_citation_ids"])
            self.target_ids = [row["chunk_id"] for row in eligible]
            for row in eligible:
                origin = {"kind": "explicit_chunk_read" if action.chunk_id is not None
                          else "explicit_parent_read", "chunk_id": row["chunk_id"]}
                if row.get("parent_id"):
                    origin["parent_id"] = row["parent_id"]
                if action.missing_information is not None:
                    origin["missing_information"] = action.missing_information
                row["reading_origins"] = [origin]
                self.explicit_rows.pop(row["chunk_id"], None)
                self.explicit_rows[row["chunk_id"]] = row
                self.known_candidates[row["chunk_id"]] = deepcopy(row)
            self.context = self.merge_current()
            shown = {row["chunk_id"]: row for row in self.context["shown_evidence"]}
            shown_ids = [identifier for identifier in self.target_ids if identifier in shown]
            new_ids = [identifier for identifier in shown_ids if identifier not in before]
            observation.update(
                status="success" if new_ids else "no_new_shown_evidence",
                paper_id=source["paper_id"], parse_revision=source["parse_revision"],
                section_path=deepcopy(source.get("section_path", [])),
                returned_ids=self.target_ids, shown_ids=shown_ids, new_shown_ids=new_ids,
                not_shown_ids=[row["chunk_id"] for row in children
                               if row["chunk_id"] not in shown],
                candidate_locations=[deepcopy(row) for row in self.context.get("candidate_locations", [])
                                     if row["chunk_id"] in self.target_ids],
                visible_chunks=[deepcopy(shown[identifier]) for identifier in shown_ids])
            unshown_ids = observation["not_shown_ids"]
            if action.chunk_id is not None:
                if unshown_ids:
                    message = ("该 chunk 的正文未在当前上下文中展示，本次未完整提供；"
                               "不能据此认为论文未报告。已有原文保留，请结合现有目录、候选或实际结果判断下一步。")
                elif new_ids:
                    message = ("本次读取取得并展示了该 chunk 的正文；本次只覆盖该块，"
                               "不代表相邻内容或整节/整表已读取。是否足以回答仍需结合原问题判断。")
                else:
                    message = ("该 chunk 的正文已在当前上下文中，因此没有新增；本次只覆盖该块，"
                               "其他相关位置请结合现有目录判断，这不代表相邻内容或整节已读取。")
            elif unshown_ids and new_ids:
                message = ("本次读取取得并展示了该 parent 的部分子块；该 parent 仍有正文未在当前上下文中展示，"
                           "不能视为该读取范围已完整提供，也不能据此认为论文未报告。"
                           "已有原文保留，请结合现有目录、候选或实际结果判断下一步。")
            elif unshown_ids:
                message = ("本次没有新增展示，且该 parent 仍有正文未在当前上下文中展示；"
                           "不能据此认为全部正文已提供，也不能据此认为论文未报告。"
                           "已有原文保留，请结合现有目录、候选或实际结果判断下一步。")
            elif new_ids:
                message = ("本次读取取得并展示了该 parent 保存的子块；本次只覆盖该 parent，"
                           "不代表同章节其他正文或表格已读取。是否足以回答仍需结合原问题判断。")
            else:
                message = ("该 parent 保存的子块正文已在当前上下文中，因此没有新增；"
                           "本次只覆盖该 parent，其他相关位置请结合现有目录判断，"
                           "这不代表同章节其他正文或表格已经读取。")
            observation["message"] = message
        except (ValueError, KeyError, SourceScopeError) as error:
            code = getattr(error, "code", None)
            if code is None:
                code = (str(error) if str(error) in
                        ("unavailable_chunk", "unavailable_parent", "source_scope_unavailable")
                        else "unavailable_read_target")
            if code == "source_scope_unavailable":
                message = "该阅读目标不符合当前来源范围，未读取；已有原文保留。这不表示论文没有报告所问内容。"
            elif code == "unavailable_chunk":
                message = "该 chunk 不在当前已知候选或已保存正文中，未读取；已有原文保留。这不表示论文没有报告所问内容。"
            elif code == "unavailable_parent":
                message = "该 parent 不在当前已展示的阅读目录中，未读取；已有原文保留。这不表示论文没有报告所问内容。"
            else:
                message = "阅读目标不可用，未取得正文；已有原文保留。这不表示论文没有报告所问内容。"
            observation["message"] = message
            observation["error"] = {
                "code": code,
                "message": "阅读目标不可用或不符合当前来源范围，已有证据保留。"}
        return observation

    def execute_javascript(self, call):
        try:
            parsed = parse_run_javascript_call(call)
            call["parsed_action"] = {"action": "run_javascript", "code": parsed.code}
            try:
                outcome = run_javascript(parsed.code)
                self.result["javascript_calls"].append({
                    "status": "success", "elapsed_seconds": outcome["elapsed_seconds"],
                    "stdout_chars": outcome["stdout_chars"],
                    "v8_version": outcome.get("v8_version")})
                return {"status": "success", **outcome}
            except JavaScriptError as error:
                observation = {"status": "tool_error",
                               "error": {"code": error.code, "message": str(error)}}
                self.result["javascript_calls"].append(deepcopy(observation))
                return observation
        except ActionParseError as error:
            return {"status": "invalid_arguments", "error": {
                "code": error.code,
                "message": "工具参数无效；run_javascript 只接受非空 code。"}}

    def _reply(self, observation, parsed_action):
        if "shown_ids" in observation:
            wanted = set(observation["shown_ids"])
            observation["shown_refs"] = [
                {"ref": row["ref"], "chunk_id": row["chunk_id"]}
                for row in self.context["shown_evidence"] if row["chunk_id"] in wanted]
        self.last_observation = deepcopy(observation)
        self.last_parsed_action = deepcopy(parsed_action)
        reply = {key: deepcopy(value) for key, value in observation.items()
                 if key not in _HELD_TOOL_FIELDS}
        return json.dumps(reply, ensure_ascii=False, allow_nan=False)

    def invoke_search(self, arguments):
        try:
            call = {"function": {"name": "search", "arguments": json.dumps(
                arguments, ensure_ascii=False, allow_nan=False)}}
            parsed = parse_search_tool_call(
                call, selected_versions=self.result["selected_versions"])
            return self._reply(self.execute_search(parsed, self.current_round),
                               parsed.model_dump(mode="json"))
        except ActionParseError as error:
            return self._reply({"status": "invalid_arguments", "error": {
                "code": error.code,
                "message": "工具字段或所选版本范围无效，请修正参数。"}}, None)

    def invoke_read(self, arguments):
        try:
            call = {"function": {"name": "read_context", "arguments": json.dumps(
                arguments, ensure_ascii=False, allow_nan=False)}}
            parsed = parse_read_context_call(call)
            return self._reply(self.execute_read(parsed),
                               {"action": "read_context", **parsed.model_dump(mode="json", exclude_none=True)})
        except ActionParseError as error:
            return self._reply({"status": "invalid_arguments", "error": {
                "code": error.code,
                "message": "阅读字段或目标无效，请修正参数。"}}, None)

    def invoke_javascript(self, arguments):
        call = {"function": {"name": "run_javascript", "arguments": json.dumps(
            arguments, ensure_ascii=False, allow_nan=False)}}
        observation = self.execute_javascript(call)
        return self._reply(observation, call.get("parsed_action"))
