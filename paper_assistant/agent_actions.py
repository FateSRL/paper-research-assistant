"""D12: answer/retry phase contract, retaining legacy insufficiency records.

Parsing proves structure and phase only. Query repetition, citation identity,
semantic support and shared request budgets belong to the later orchestration.
"""

import json
from math import isfinite
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

from paper_assistant.schemas import AnswerDraft, Claim


ACTION_SCHEMA_VERSION = "d12-agent-actions-v1"
AUTONOMOUS_ACTION_SCHEMA_VERSION = "v2.15-gap-driven-evidence-actions-v1"
MISSING_INFORMATION_MAX_CHARS = 500
RETRY_QUERY_MAX_CHARS = 1000
REASON_MAX_CHARS = 1000


class ActionParseError(ValueError):
    """Safe fixed code; never include model text or Pydantic input in errors."""

    def __init__(self, code: str, *, field_issues=None):
        super().__init__("模型动作未通过结构或阶段检查，请核对安全错误代码")
        self.code = code
        self.field_issues = field_issues or []


def _action_field_issues(error):
    issues = []
    for issue in error.errors(include_input=False, include_context=False, include_url=False):
        location = issue["loc"]
        if location and location[0] == "answer":
            location = location[1:]  # Discriminated union branch, not an output field.
        if issue["type"] == "missing" and location == ("answer", "status"):
            issues.append({"path": "answer.status", "type": "missing", "message": "Required field is missing."})
        elif issue["type"] == "extra_forbidden" and location == ("reason",):
            issues.append({"path": "reason", "type": "extra_forbidden",
                "message": "reason belongs inside answer.reason, not at the action top level."})
        elif (issue["type"] == "value_error" and len(location) == 3
              and location[:2] == ("answer", "claims") and type(location[2]) is int
              and issue["msg"] == "Value error, paper_evidence 必须提供 citation_ids"):
            issues.append({"path": f"answer.claims[{location[2]}].citation_ids",
                "type": "paper_evidence_without_citations",
                "message": "paper_evidence requires nonempty citation_ids from allowed_citation_ids; do not invent IDs or relabel unsupported paper facts."})
    return issues


class _StrictAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True,
                              str_strip_whitespace=False, frozen=True)


class AnswerAction(_StrictAction):
    action: Literal["answer"]
    answer: AnswerDraft

    @field_validator("answer", mode="before")
    @classmethod
    def recheck_existing_draft(cls, value):
        # A dict may also contain constructed/mutated Claim instances. First
        # hydrate it, then expand all nested fields so the annotated field's
        # validation checks plain Claim data again instead of trusting instances.
        plain = value.model_dump(mode="python") if isinstance(value, AnswerDraft) else value
        return AnswerDraft.model_validate(plain).model_dump(mode="python")

    @model_validator(mode="after")
    def require_answered(self):
        if self.answer.status != "answered":
            raise ValueError("answer 动作必须携带 answered 草稿")
        return self


class PrepareAnswerAction(_StrictAction):
    action: Literal["prepare_answer"]
    facts: list[Claim]
    answerable: bool
    missing_information: str


class RetrySearchAction(_StrictAction):
    action: Literal["retry_search"]
    missing_information: str = Field(min_length=1, max_length=MISSING_INFORMATION_MAX_CHARS)
    retry_query: str = Field(min_length=1, max_length=RETRY_QUERY_MAX_CHARS)

    @field_validator("missing_information", "retry_query")
    @classmethod
    def nonblank_raw_text(cls, value):
        if not value.strip():
            raise ValueError("补查字段必须包含非空白文本")
        return value


class SelectedVersion(_StrictAction):
    paper_id: str = Field(min_length=1)
    parse_revision: str = Field(min_length=1)


class SearchAction(_StrictAction):
    action: Literal["search"]
    query: str = Field(min_length=1, max_length=RETRY_QUERY_MAX_CHARS)
    selected_versions: list[SelectedVersion] = Field(min_length=1, max_length=3)
    missing_information: str = Field(min_length=1, max_length=MISSING_INFORMATION_MAX_CHARS)

    @field_validator("query", "missing_information")
    @classmethod
    def nonblank_text(cls, value):
        if not value.strip():
            raise ValueError("检索字段必须包含非空白文本")
        return value


class InsufficientEvidenceAction(_StrictAction):
    action: Literal["insufficient_evidence"]
    reason: str = Field(min_length=1, max_length=REASON_MAX_CHARS)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value):
        if not value.strip():
            raise ValueError("资料不足必须提供非空白理由")
        return value


AgentAction = Annotated[AnswerAction | PrepareAnswerAction | SearchAction | RetrySearchAction | InsufficientEvidenceAction,
                        Field(discriminator="action")]
_ACTION_ADAPTER = TypeAdapter(AgentAction)


def allowed_actions(*, phase: str, has_shown_evidence: bool,
                    terminal_only: bool = False, prepare_answer: bool = False) -> tuple[str, ...]:
    """Program-controlled phase; citation repair may only return terminal actions."""
    if type(phase) is not str or phase not in (
            "initial_decision", "final_decision", "autonomous_decision", "gap_evidence_decision", "limit_final_decision", "prepared_final_decision"):
        raise ActionParseError("invalid_phase")
    if type(has_shown_evidence) is not bool:
        raise ActionParseError("invalid_evidence_flag")
    if type(terminal_only) is not bool:
        raise ActionParseError("invalid_terminal_option")
    if phase == "gap_evidence_decision":
        return ("insufficient_evidence",) if terminal_only else ("insufficient_evidence", "search")
    actions = ["prepare_answer"] if prepare_answer else ["answer"]
    if prepare_answer and not has_shown_evidence:
        actions.insert(0, "answer")
    if phase == "initial_decision" and not terminal_only:
        actions.append("retry_search")
    elif phase == "autonomous_decision" and not terminal_only:
        actions.append("search")
    return tuple(actions)


def _decode_action_json(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ActionParseError("duplicate_json_key")
            result[key] = value
        return result

    def constant(_):
        raise ActionParseError("non_finite_json")

    def number(raw):
        value = float(raw)
        if not isfinite(value):
            raise ActionParseError("non_finite_json")
        return value

    try:
        return json.loads(content, object_pairs_hook=pairs, parse_constant=constant,
                           parse_float=number)
    except ActionParseError:
        raise
    except (ValueError, RecursionError):
        raise ActionParseError("invalid_json") from None


def parse_agent_action(content: str, *, phase: str, has_shown_evidence: bool,
                       terminal_only: bool = False, selected_versions=None, prepare_answer=False) -> AgentAction:
    """Decode one strict object, validate its branch, then enforce the phase.

    Citation repair must pass terminal_only=True both here and in its prompt.
    A structurally valid same-query retry is intentionally left for C's gate.
    """
    permitted = allowed_actions(phase=phase, has_shown_evidence=has_shown_evidence,
                                terminal_only=terminal_only, prepare_answer=prepare_answer)
    if not isinstance(content, str) or not content.strip():
        raise ActionParseError("empty_output")

    value = _decode_action_json(content)
    try:
        parsed = _ACTION_ADAPTER.validate_python(value, strict=True)
    except ValidationError as error:
        raise ActionParseError("invalid_action_schema", field_issues=_action_field_issues(error)) from None
    except (ValueError, RecursionError):
        raise ActionParseError("invalid_action_schema") from None
    if parsed.action not in permitted:
        raise ActionParseError("action_not_allowed")
    if prepare_answer and isinstance(parsed, AnswerAction) and any(
            claim.basis != "model_knowledge" or claim.citation_ids or claim.evidence_quotes
            for claim in parsed.answer.claims):
        raise ActionParseError("paper_answer_requires_preparation")
    if isinstance(parsed, SearchAction):
        chosen = [(row.paper_id, row.parse_revision) for row in parsed.selected_versions]
        allowed = [(row["paper_id"], row["parse_revision"]) for row in selected_versions or []]
        if len(set(chosen)) != len(chosen) or any(pair not in allowed for pair in chosen):
            raise ActionParseError("search_scope_mismatch")
    return parsed


def query_comparison_key(query: str) -> str:
    """Comparison only: do not send this folded value to the embedding service."""
    if not isinstance(query, str) or not query.strip():
        raise ActionParseError("invalid_query")
    return " ".join(query.split()).casefold()


def action_to_answer_draft(action: AgentAction) -> AnswerDraft:
    """Convert a terminal action without a second model call or citation claim.

    Revalidate fields to prevent a constructed/mutated model bypassing structure.
    This conversion does not publish an answer or check its citations.
    """
    if not isinstance(action, (AnswerAction, SearchAction, RetrySearchAction, InsufficientEvidenceAction)):
        raise ActionParseError("invalid_action_schema")
    try:
        checked = _ACTION_ADAPTER.validate_python(action.model_dump(mode="python"), strict=True)
    except ValidationError as error:
        raise ActionParseError("invalid_action_schema", field_issues=_action_field_issues(error)) from None
    except (ValueError, RecursionError):
        raise ActionParseError("invalid_action_schema") from None
    if isinstance(checked, (RetrySearchAction, SearchAction)):
        raise ActionParseError("non_terminal_action")
    if isinstance(checked, AnswerAction):
        return AnswerDraft.model_validate(checked.answer.model_dump(mode="python"))
    return AnswerDraft(status="insufficient_evidence", claims=[], reason=checked.reason)


def search_tool_definition():
    """Expose the existing SearchAction fields through the native tool protocol."""
    schema = SearchAction.model_json_schema()
    schema["properties"].pop("action")
    schema["required"].remove("action")
    return {"type": "function", "function": {"name": "search",
        "description": "Retrieve evidence from selected paper versions for a missing paper fact.",
        "parameters": schema}}


def parse_search_tool_call(call, *, selected_versions):
    if call["function"]["name"] != "search":
        raise ActionParseError("unknown_tool")
    arguments = _decode_action_json(call["function"]["arguments"])
    if not isinstance(arguments, dict) or "action" in arguments:
        raise ActionParseError("invalid_action_schema")
    return parse_agent_action(json.dumps({"action": "search", **arguments}, allow_nan=False),
        phase="autonomous_decision", has_shown_evidence=False, selected_versions=selected_versions)


class ReadContextAction(_StrictAction):
    parent_id: str | None = Field(default=None, min_length=1)
    chunk_id: str | None = Field(default=None, min_length=1)
    missing_information: str | None = Field(default=None, min_length=1, max_length=MISSING_INFORMATION_MAX_CHARS)

    @model_validator(mode="after")
    def require_one_target(self):
        if (self.parent_id is None) == (self.chunk_id is None):
            raise ValueError("阅读目标必须是 parent_id 或 chunk_id 之一")
        if self.chunk_id is not None and not (self.missing_information or "").strip():
            raise ValueError("定向阅读必须说明 missing_information")
        if not (self.parent_id or self.chunk_id).strip():
            raise ValueError("阅读目标不能为空白")
        return self


def read_context_tool_definition():
    return {"type": "function", "function": {"name": "read_context",
        "description": "Read saved originals locally: either parent_id from the reading directory, or one chunk_id seen in actual tool returns or visible evidence with missing_information stating the needed fact. A chunk read fetches only that target, without neighbors. No network search.",
        "parameters": ReadContextAction.model_json_schema()}}


def parse_read_context_call(call):
    try:
        return ReadContextAction.model_validate(_decode_action_json(call["function"]["arguments"]), strict=True)
    except ValidationError:
        raise ActionParseError("invalid_action_schema") from None
