"""D5 C：生成和解析草稿；合法引用与事实支持须由后续层判断。"""

from copy import deepcopy
import json
from math import isfinite

from pydantic import ValidationError

from paper_assistant.context import ContextError, PROMPT_VERSION, SHORT_REPAIR_INSTRUCTION, build_messages
from paper_assistant.llm_client import LLMCallError
from paper_assistant.message_fit import context_fit_budget, count_request_tokens, effective_context_length
from paper_assistant.schemas import AnswerDraft
from paper_assistant.source_scope import SourceScopeError, attach_source_requirement


FULL_REQUEST_POLICY_VERSION = "d14-fixed-full-request-capacity-v1"


class DraftParseError(ValueError):
    def __init__(self, code, *, field_issues=None):
        super().__init__("模型草稿未通过结构检查，请核对安全错误代码")
        self.code = code
        self.field_issues = deepcopy(field_issues or [])


def _draft_field_issues(error):
    issues = []
    known_fields = {"status", "claims", "claim", "basis", "citation_ids", "reason", "direct_answer"}
    for detail in error.errors(include_input=False, include_context=False, include_url=False):
        location, category = detail["loc"], detail["type"]
        if not location or any(part not in known_fields if isinstance(part, str)
                               else type(part) is not int for part in location):
            continue
        if category == "missing":
            message = "Required field is missing."
        elif category == "extra_forbidden":
            message = "Unexpected field; use only the documented AnswerDraft fields."
        elif (category == "value_error" and len(location) == 2 and location[0] == "claims"
                and type(location[1]) is int
                and detail["msg"] == "Value error, paper_evidence 必须提供 citation_ids"):
            location = (*location, "citation_ids")
            category = "paper_evidence_without_citations"
            message = ("paper_evidence requires nonempty citation_ids from allowed_citation_ids; "
                       "do not invent IDs or relabel unsupported paper facts.")
        else:
            continue
        path = ""
        for part in location:
            path += f"[{part}]" if type(part) is int else ("." if path else "") + part
        issues.append({"path": path, "type": category, "message": message})
    return issues


def parse_answer_draft(content: str) -> AnswerDraft:
    """拒绝重复键、非有限数、围栏和任意额外文本；不复制原输入到错误。"""
    if not isinstance(content, str) or not content.strip():
        raise DraftParseError("empty_output")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise DraftParseError("duplicate_json_key")
            value[key] = item
        return value

    def constant(_):
        raise DraftParseError("non_finite_json")

    def number(raw):
        value = float(raw)
        if not isfinite(value):
            raise DraftParseError("non_finite_json")
        return value

    try:
        value = json.loads(content, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)
    except DraftParseError:
        raise
    except (ValueError, RecursionError):
        raise DraftParseError("invalid_json") from None
    try:
        return AnswerDraft.model_validate(value)
    except ValidationError as error:
        raise DraftParseError("invalid_draft_schema", field_issues=_draft_field_issues(error)) from None
    except (ValueError, RecursionError):
        raise DraftParseError("invalid_draft_schema") from None


def _fit_record(context, client, *, before, budget):
    settings = getattr(client, "settings", None)
    configured = getattr(settings, "context_length", None)
    policy = client.policy
    return {
        "policy_version": FULL_REQUEST_POLICY_VERSION,
        "capacity_mode": "full_request",
        "configured_context_length": configured,
        "model_context_length": effective_context_length(configured),
        "context_length_source": ("configured" if type(configured) is int and configured > 0
                                  else "message_fit_fallback"),
        "output_reserve_tokens": policy.max_tokens,
        "context_margin": 0.97,
        "input_budget_tokens": budget,
        "request_tokens_before": before,
        "trim_reason": "model_context_budget",
        "trimmed_chunk_ids": [row["chunk_id"] for row in context.get("omitted_evidence", [])
                              if row.get("reason") == "token_budget"],
        "shown_chars": context.get("shown_chars"),
        "candidate_count": context.get("candidate_count"),
    }


def fit_fixed_request(context, messages, client, *, source_requirement=None, conversation_context=None):
    """Fit a fixed-RAG complete request by dropping whole low-priority evidence.

    The public fixed-RAG call still accepts its historical ``max_chars``
    contract. Only a context marked ``full_request`` is trimmed here; explicit
    token/character contexts retain their old selection and prompt behavior.
    The first two messages are the base system/user pair; repair tails stay
    attached while the base is rebuilt from the surviving evidence.
    """
    if not isinstance(context, dict) or context.get("context_capacity_mode") != "full_request":
        return messages, None
    if (not isinstance(messages, list) or len(messages) < 2
            or messages[0].get("role") != "system" or messages[1].get("role") != "user"):
        raise ContextError("invalid_context", "固定请求消息结构无效")
    context["max_chars"] = None
    context.pop("max_tokens", None)
    context.pop("shown_tokens", None)
    context.pop("tokenizer", None)
    settings = getattr(client, "settings", None)
    configured = getattr(settings, "context_length", None)
    policy = client.policy
    budget = context_fit_budget(configured, policy.max_tokens)
    before = count_request_tokens(messages)
    tail = deepcopy(messages[2:])

    def rebuild():
        base = build_messages(context["question"], context, conversation_context=conversation_context)
        if source_requirement is not None:
            base = attach_source_requirement(base, context["question"], source_requirement)
        return [*base, *deepcopy(tail)]

    dropped = []
    while count_request_tokens(messages) > budget:
        shown = context.get("shown_evidence")
        if not shown:
            raise ContextError("request_too_large", "完整请求在裁剪后仍超过模型上下文容量")
        removed = shown[-1]
        dropped.append(removed["chunk_id"])
        kept = shown[:-1]
        omitted = [*deepcopy(context.get("omitted_evidence", [])),
                   {"chunk_id": removed["chunk_id"], "rank": removed["rank"], "reason": "token_budget"}]
        retained = {row["chunk_id"] for row in kept}
        context.update(
            shown_evidence=kept,
            allowed_citation_ids=[row["chunk_id"] for row in kept],
            shown_chars=sum(len(row["shown_text"]) for row in kept),
            omitted_evidence=omitted,
            candidate_count=len(kept) + len(omitted),
            reading_origins=[deepcopy(origin) for origin in context.get("reading_origins", [])
                             if origin.get("chunk_id") in retained],
            empty_selection_reason=None if kept else "token_budget",
        )
        messages = rebuild()

    result = _fit_record(context, client, before=before, budget=budget)
    result["request_tokens_after"] = count_request_tokens(messages)
    result["trimmed_chunk_ids"] = list(dict.fromkeys(
        [*result["trimmed_chunk_ids"], *dropped]))
    return messages, result


def generate_draft(context: dict, client, *, repair=True, source_requirement=None, conversation_context=None) -> dict:
    """借用 B 客户端及预算；只修一次格式，成功仍是待引用校验草稿。"""
    attempts = []
    result = {"status": "tool_error", "draft": None, "error": None,
              "prompt_version": "v2.13-question-intent-retrieval-direct-answer-source-scoped-v1" if source_requirement is not None else PROMPT_VERSION,
              "citation_validation_status": "not_performed", "generation_attempts": attempts,
              "request_fits": [], "statistics": None}
    try:
        if type(repair) is not bool:
            raise ContextError("invalid_repair_option", "repair 必须为布尔值")
        if not isinstance(context, dict):
            raise ContextError("invalid_context", "本轮上下文无效")
        messages = build_messages(context.get("question"), context, conversation_context=conversation_context)
        if source_requirement is not None:
            messages = attach_source_requirement(messages, context.get("question"), source_requirement)
        messages, fit = fit_fixed_request(context, messages, client,
                                          source_requirement=source_requirement,
                                          conversation_context=conversation_context)
        if fit is not None:
            result["request_fits"].append(fit)
    except (ContextError, SourceScopeError) as error:
        result["error"] = {"code": error.code, "message": str(error)}
        result["statistics"] = deepcopy(client.budget.statistics())
        return result

    def finish():
        result["request_fit"] = result["request_fits"][-1] if result["request_fits"] else None
        if result["status"] == "draft_valid" and client.budget.remaining_seconds() <= 0:
            result.update(status="budget_exceeded", draft=None, citation_validation_status="not_performed",
                          error={"code": "deadline_exceeded", "message": "草稿解析结束时已超过截止预算"})
        result["statistics"] = deepcopy(client.budget.statistics())
        return result

    if client.budget.remaining_seconds() <= 0:
        result.update(status="budget_exceeded", error={"code": "deadline_exceeded", "message": "生成阶段截止预算已到"})
        return finish()

    for turn in range(2 if repair else 1):
        # 预算属于整轮。C 已用修复后，D 引用修复也不能重新获得额度。
        if turn and client.budget.repairs >= client.budget.policy.max_repairs:
            result.update(status="invalid_output", error={"code": "repair_unavailable", "message": "本轮修复额度已耗尽"})
            return finish()
        entry = {"purpose": "answer" if turn == 0 else "repair", "messages": deepcopy(messages),
                 "response": None, "parse_error_code": None, "parse_error_fields": []}
        attempts.append(entry)
        try:
            response = client.invoke(messages, purpose=entry["purpose"], require_json=True)
        except LLMCallError as error:
            entry["error"] = {"status": error.status, "code": error.code, "message": str(error),
                              "attempts": deepcopy(error.attempts)}
            result.update(status=error.status, error={"code": error.code, "message": str(error)})
            return finish()
        entry["response"] = deepcopy(response)
        try:
            if response["status"] != "success":
                raise DraftParseError(response.get("output_issue") or "invalid_output")
            draft = parse_answer_draft(response["content"])
            if draft.status != "answered":
                raise DraftParseError("answer_required")
        except DraftParseError as error:
            entry["parse_error_code"] = error.code
            entry["parse_error_fields"] = deepcopy(error.field_issues)
            result.update(status="invalid_output", error={"code": error.code, "message": str(error)})
            if not repair or turn:
                return finish()
            # 修复沿用原始 system/user 数据；错误摘要不包含 Pydantic 输入。
            # B 的 content 已脱敏。只发送原来生成文本，不添加库外材料。
            instruction = "Return a complete AnswerDraft with status answered and nonempty claims under the original rules. Complete the current request with supported paper facts or a clear statement of the requested evidence gap. A gap claim using analysis can be the entire answer, with no unrelated citations or invented quotes and requested direct_answer Unanswerable. Explain mechanisms, concepts or analysis fully when the user requests them. Keep the original question and source scope; do not invent paper facts or IDs or add other findings to replace a missing fact."
            if error.code == "truncated":
                instruction += "\n" + SHORT_REPAIR_INSTRUCTION
            messages = [*deepcopy(messages),
                        {"role": "assistant", "content": response.get("content") or "[empty response]"},
                        {"role": "user", "content": json.dumps({"action": "repair_json_draft",
                         "error_code": error.code, "field_issues": deepcopy(error.field_issues),
                         "instruction": instruction})}]
            try:
                messages, fit = fit_fixed_request(context, messages, client,
                                                  source_requirement=source_requirement,
                                                  conversation_context=conversation_context)
                if fit is not None:
                    result["request_fits"].append(fit)
            except ContextError as fit_error:
                result.update(status="tool_error", error={"code": fit_error.code,
                                                           "message": str(fit_error)})
                return finish()
            continue
        result.update(status="draft_valid", draft=draft.model_dump(mode="json"), error=None,
                      citation_validation_status="pending" if draft.status == "answered" else "not_applicable")
        return finish()
    return finish()
