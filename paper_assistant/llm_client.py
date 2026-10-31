"""D2 连通入口，以及 D5 B 可记录、受预算控制的聊天调用。

本模块只负责服务调用与完整响应，不判断论文证据是否支持结论。
旧 invoke_llm 保持原调用方式；D5 使用 RecordedLLM 共享生成/修复预算。
"""

from copy import deepcopy
from dataclasses import dataclass
import json
from math import isfinite
import re
from time import monotonic
from typing import Callable
from urllib.parse import urlsplit

import httpx
from hello_agents import HelloAgentsLLM
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from .config import LLMSettings, load_llm_settings


def invoke_llm(messages: list[dict[str, str]], settings: LLMSettings | None = None) -> str:
    """读取已校验的配置，调用一次 HelloAgentsLLM.invoke。"""
    settings = settings or load_llm_settings()
    client = HelloAgentsLLM(
        provider=settings.provider,
        model=settings.model_id,
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout,
        max_tokens=128,
    )
    return client.invoke(messages)


class LLMCallError(RuntimeError):
    """仅保留安全摘要与调用记录，不暴露 SDK 异常正文、请求或认证头。"""

    def __init__(self, status: str, code: str, message: str, *, attempts=None, statistics=None):
        super().__init__(message)
        self.status, self.code = status, code
        self.attempts = deepcopy(attempts or [])
        self.statistics = deepcopy(statistics or {})


def _positive(value, name):
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} 必须是有限的正数")


@dataclass(frozen=True)
class ChatPolicy:
    temperature: float = 0.2
    max_tokens: int = 1200
    request_timeout: float = 30.0
    max_attempts: int | None = 3
    max_network_retries: int = 1
    max_repairs: int | None = 1
    retry_per_invoke: bool = False
    total_timeout: float | None = 120.0

    def __post_init__(self):
        if type(self.temperature) not in (int, float) or not isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise ValueError("temperature 必须为 0–2 的有限数值")
        if type(self.max_tokens) is not int or self.max_tokens <= 0:
            raise ValueError("max_tokens 必须为正整数")
        if self.max_attempts is not None:
            if type(self.max_attempts) is not int or self.max_attempts <= 0:
                raise ValueError("max_attempts 必须为正整数或 None")
        if type(self.max_network_retries) is not int or not 0 <= self.max_network_retries <= 1:
            raise ValueError("max_network_retries 必须为 0 或 1")
        if self.max_repairs is not None and (type(self.max_repairs) is not int or self.max_repairs < 0):
            raise ValueError("max_repairs 必须为非负整数或 None")
        if type(self.retry_per_invoke) is not bool:
            raise ValueError("retry_per_invoke 必须为 bool")
        _positive(self.request_timeout, "request_timeout")
        if self.total_timeout is not None:
            _positive(self.total_timeout, "total_timeout")


class ChatBudget:
    """同一问答共享调用统计与策略，None 表示不设置整轮硬上限。"""

    def __init__(self, policy: ChatPolicy | None = None, *, clock: Callable = monotonic, deadline=None):
        self.policy, self.clock = policy or ChatPolicy(), clock
        self.started = clock()
        if deadline is not None and (type(deadline) not in (int, float) or not isfinite(deadline)):
            raise ValueError("deadline 必须是单调时钟上的有限时间点")
        self.deadline = (deadline if deadline is not None else
                         float("inf") if self.policy.total_timeout is None else self.started + self.policy.total_timeout)
        self.attempts = self.network_retries = self.repairs = self.http_requests = 0
        self.records: list[dict] = []

    def remaining_seconds(self):
        return self.deadline - self.clock()

    def reserve(self, *, retry: bool, repair_start: bool):
        if self.remaining_seconds() <= 0:
            raise LLMCallError("budget_exceeded", "deadline_exceeded", "问答截止预算已到，停止后续请求")
        if self.policy.max_attempts is not None and self.attempts >= self.policy.max_attempts:
            raise LLMCallError("budget_exceeded", "request_limit", "聊天请求次数已达上限")
        if retry and not self.policy.retry_per_invoke and self.network_retries >= self.policy.max_network_retries:
            raise LLMCallError("tool_error", "network_retry_limit", "可重试故障额度已耗尽")
        if repair_start and self.policy.max_repairs is not None and self.repairs >= self.policy.max_repairs:
            raise LLMCallError("budget_exceeded", "repair_limit", "格式或引用修复次数已达上限")
        self.attempts += 1
        self.network_retries += int(retry)
        self.repairs += int(repair_start)

    def statistics(self):
        totals = [record["usage"].get("total_tokens") if record.get("usage") else None for record in self.records]
        complete = bool(totals) and all(type(value) is int and value >= 0 for value in totals)
        return {"sdk_request_attempts": self.attempts, "http_request_attempts": self.http_requests,
                "network_retries": self.network_retries, "repairs": self.repairs,
                "usage_complete": complete, "total_tokens": sum(totals) if complete else None,
                "known_total_tokens": sum(value for value in totals if type(value) is int and value >= 0),
                "elapsed_seconds": round(self.clock() - self.started, 6)}


def _numeric_usage(value, *, secret=""):
    """保存供应商实际计数（含缓存细项）；不复制错误正文或未知字符串。"""
    if value is None:
        return None
    raw = value.model_dump(mode="json", exclude_none=True)
    def clean(item):
        if isinstance(item, dict):
            return {key: cleaned for key, val in item.items()
                    if isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
                    and not (secret and secret in key) and (cleaned := clean(val)) is not None}
        if type(item) is int and item >= 0:
            return item
        return None
    result = clean(raw)
    return result or None


class RecordedLLM:
    """串行调用者拥有客户端；退出 with 时关闭。transport 供离线故障注入。"""

    def __init__(self, settings: LLMSettings | None = None, *, policy=None, budget=None,
                 transport=None, clock: Callable = monotonic):
        self.policy = policy or (budget.policy if budget is not None else ChatPolicy())
        self.budget = budget or ChatBudget(self.policy, clock=clock)
        if self.budget.policy != self.policy:
            raise ValueError("调用参数与共享预算的 policy 必须一致")
        self.clock = self.budget.clock
        try:
            self.settings = settings or load_llm_settings()
            endpoint = urlsplit(self.settings.base_url)
            if (endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username
                    or endpoint.password or endpoint.query or endpoint.fragment
                    or not self.settings.api_key.strip() or not self.settings.model_id.strip()):
                raise ValueError("invalid configuration")
            _positive(self.settings.timeout, "configured timeout")
        except Exception:
            raise LLMCallError("tool_error", "configuration_error", "聊天配置无效，请核对本机配置") from None
        self._active_attempt = None
        self._closed = False
        http_client = None
        try:
            # SDK 支持公开注入 httpx 客户端；沿用项目固定的 httpx 版本，
            # 避免默认 httpx2 运行时与离线 MockTransport 的类型混用。
            http_client = httpx.Client(transport=transport, follow_redirects=False,
                                       event_hooks={"request": [self._count_http_request],
                                                    "response": [self._capture_http_status]})
            self.client = OpenAI(api_key=self.settings.api_key, base_url=self.settings.base_url,
                                 timeout=self.settings.timeout, max_retries=0, http_client=http_client)
        except Exception:
            if http_client is not None:
                http_client.close()
            raise LLMCallError("tool_error", "client_setup_error", "无法初始化聊天客户端") from None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if not self._closed:
            self.client.close()
            self._closed = True

    def _count_http_request(self, _request):
        # 只计发送尝试，不存 request、URL 或 headers。SDK 重试和重定向均关闭。
        if self._active_attempt is None:
            raise RuntimeError("request outside recorded invocation")
        self._active_attempt["http_request_attempts"] += 1
        self.budget.http_requests += 1

    def _capture_http_status(self, response):
        if self._active_attempt is not None:
            self._active_attempt["http_status"] = response.status_code

    def _error(self, status, code, message, start):
        return LLMCallError(status, code, message, attempts=self.budget.records[start:],
                            statistics=self.budget.statistics())

    def _redact(self, content):
        if not isinstance(content, str):
            return None
        content = content.replace(self.settings.api_key, "[REDACTED]")
        return re.sub(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", content)

    def invoke(self, messages, *, purpose="answer", require_json=False, tools=None, tool_choice=None, request_timeout=None) -> dict:
        start_index = len(self.budget.records)
        if self._closed:
            raise self._error("tool_error", "client_closed", "聊天客户端已关闭", start_index)
        def valid_message(item):
            if not isinstance(item, dict):
                return False
            role, content = item.get("role"), item.get("content")
            if role == "tool":
                return (set(item) == {"role", "content", "tool_call_id"}
                        and isinstance(content, str) and bool(content.strip())
                        and isinstance(item["tool_call_id"], str) and bool(item["tool_call_id"]))
            if role == "assistant" and item.get("tool_calls"):
                return (set(item) == {"role", "content", "tool_calls"}
                        and (content is None or isinstance(content, str))
                        and isinstance(item["tool_calls"], list))
            return (set(item) == {"role", "content"} and role in ("system", "user", "assistant")
                    and isinstance(content, str) and bool(content.strip()))

        if (purpose not in ("answer", "repair", "synthesis") or type(require_json) is not bool
                or not isinstance(messages, list) or not messages
                or any(not valid_message(item) for item in messages)):
            raise self._error("tool_error", "invalid_input", "聊天消息或调用参数不合法", start_index)
        if request_timeout is not None:
            _positive(request_timeout, "request_timeout")
        call_started, retry, first = self.clock(), False, True
        call_retries = 0
        while True:
            timeout = min(self.policy.request_timeout if request_timeout is None else request_timeout,
                          self.settings.timeout, self.budget.remaining_seconds())
            if timeout <= 0:
                raise self._error("budget_exceeded", "deadline_exceeded", "问答截止预算已到", start_index)
            try:
                self.budget.reserve(retry=retry, repair_start=first and purpose == "repair")
            except LLMCallError as error:
                raise self._error(error.status, error.code, str(error), start_index) from None
            record = {"number": self.budget.attempts, "purpose": purpose, "is_network_retry": retry,
                      "http_request_attempts": 0, "status": "pending", "error_code": None,
                      "http_status": None, "usage": None, "finish_reason": None, "content": None,
                      "timeout_seconds": timeout, "elapsed_seconds": None}
            self.budget.records.append(record)
            self._active_attempt = record
            began = self.clock()
            response, failure, retryable = None, None, False
            try:
                extra = {"thinking": {"type": "disabled"}} if self.settings.provider.lower() == "deepseek" else None
                kwargs = {"model": self.settings.model_id, "messages": deepcopy(messages),
                          "temperature": self.policy.temperature, "max_tokens": self.policy.max_tokens,
                          "stream": False, "timeout": timeout}
                if tools is not None:
                    kwargs["tools"] = deepcopy(tools)
                if tool_choice is not None:
                    kwargs["tool_choice"] = deepcopy(tool_choice)
                if extra is not None:
                    kwargs["extra_body"] = extra
                response = self.client.chat.completions.create(**kwargs)
            except APITimeoutError:
                failure, retryable = "request_timeout", True
            except APIConnectionError:
                failure, retryable = "connection_error", True
            except APIStatusError as error:
                record["http_status"] = error.status_code if type(error.status_code) is int else None
                failure = "http_error"
                retryable = error.status_code in (408, 409, 429) or 500 <= error.status_code < 600
            except Exception:
                failure = "client_error"
            finally:
                record["elapsed_seconds"] = round(self.clock() - began, 6)
                self._active_attempt = None
            if failure:
                record.update(status="tool_error", error_code=failure)
                if self.budget.remaining_seconds() <= 0:
                    raise self._error("budget_exceeded", "deadline_exceeded", "聊天请求结束时已超出截止预算", start_index)
                if retryable and (call_retries if self.policy.retry_per_invoke else self.budget.network_retries) < self.policy.max_network_retries:
                    call_retries += 1
                    retry, first = True, False
                    continue
                raise self._error("tool_error", failure, "聊天服务请求失败，详情见安全错误代码与状态码", start_index) from None
            issue = None
            try:
                record["usage"] = _numeric_usage(response.usage, secret=self.settings.api_key)
                choice = response.choices[0]
                finish = choice.finish_reason
                known = {"stop", "length", "content_filter", "tool_calls", "function_call", "insufficient_system_resource", "aborted"}
                record["finish_reason"] = finish if isinstance(finish, str) and finish in known else "unknown"
                record["content"] = self._redact(choice.message.content)
                record["tool_calls"] = [{"id": self._redact(call.id), "type": call.type,
                    "function": {"name": self._redact(call.function.name),
                                 "arguments": self._redact(call.function.arguments)}}
                    for call in (choice.message.tool_calls or [])]
                record["reasoning_content_received"] = bool(getattr(choice.message, "reasoning_content", None))
                if choice.message.content is not None and not isinstance(choice.message.content, str):
                    issue = "malformed_response"
                elif finish == "length":
                    issue = "truncated"
                elif record["tool_calls"]:
                    if not tools or tool_choice == "none" or finish != "tool_calls":
                        issue = "unexpected_tool_calls"
                elif finish != "stop":
                    issue = "unexpected_finish_reason"
                elif not isinstance(record["content"], str) or not record["content"].strip():
                    issue = "empty_output"
                elif require_json:
                    try:
                        json.loads(record["content"], parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
                    except (json.JSONDecodeError, ValueError):
                        issue = "invalid_json"
            except Exception:
                issue = "malformed_response"
            record.update(status="invalid_output" if issue else "success", error_code=issue)
            if self.budget.remaining_seconds() <= 0:
                raise self._error("budget_exceeded", "deadline_exceeded", "聊天响应返回时已超出截止预算", start_index)
            return {"status": record["status"], "output_issue": issue,
                    "content": record["content"], "finish_reason": record["finish_reason"],
                    "tool_calls": deepcopy(record.get("tool_calls", [])),
                    "usage": deepcopy(record["usage"]), "elapsed_seconds": round(self.clock() - call_started, 6),
                    "attempts": deepcopy(self.budget.records[start_index:]), "statistics": self.budget.statistics()}
