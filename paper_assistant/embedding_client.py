"""通过百炼 OpenAI 兼容接口获取稠密文本向量。"""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
import re
from time import perf_counter
from typing import Sequence

import httpx

from paper_assistant.config import EmbeddingSettings
from paper_assistant.deadline import DeadlineExceeded, remaining


class EmbeddingAPIError(RuntimeError):
    """Safe failure with actual send-attempt/usage evidence."""

    def __init__(self, message, *, code="embedding_error", status="tool_error", statistics=None):
        super().__init__(message)
        self.code, self.status = code, status
        self.statistics = deepcopy(statistics or {"embedding_requests": 0, "failed_requests": 0,
                                                  "total_tokens": None, "request_started": False,
                                                  "timeout_seconds": None})


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    elapsed_seconds: float
    total_tokens: int | None
    request_started: bool = True
    request_attempts: int = 1
    timeout_seconds: float | None = 30.0
    accounting_basis: str = "legacy_batch"


def embed_texts(texts: Sequence[str], settings: EmbeddingSettings, *, remaining_seconds=None,
                request_timeout=30.0, transport=None, http_client=None) -> EmbeddingBatch:
    """将一批文本转换为向量，保持返回顺序与输入顺序一致。

    此兼容接口使用默认的稠密向量输出；它的请求示例未提供 text_type，
    因此 D2 连通实验对文档和问题使用同一默认输入方式。
    传入 http_client 时仅借用；创建者负责关闭，单批 hook 不留在客户端上。
    """
    if settings.backend != "dashscope" or not settings.api_key or not settings.base_url:
        raise EmbeddingAPIError("当前客户端需要完整的 dashscope 配置")
    if not texts or any(not isinstance(value, str) or not value.strip() for value in texts):
        raise ValueError("texts 必须包含至少一条非空文本")

    payload: dict[str, object] = {
        "model": settings.model,
        "input": list(texts),
        "encoding_format": "float",
    }
    if settings.dimension is not None:
        payload["dimensions"] = settings.dimension

    if type(request_timeout) not in (int, float) or not isfinite(request_timeout) or not 0 < request_timeout <= 30:
        raise ValueError("request_timeout must be within (0, 30]")
    statistics = {"embedding_requests": 0, "failed_requests": 0, "total_tokens": None,
                  "request_started": False, "timeout_seconds": None}
    def check():
        return remaining(remaining_seconds)
    def fail(message, *, code="embedding_error", status="tool_error"):
        if status != "budget_exceeded":
            statistics["failed_requests"] = statistics["embedding_requests"]
            try:
                remaining(remaining_seconds)
            except DeadlineExceeded:
                statistics["interrupted_failure"] = {"code": code}
                status, code = "budget_exceeded", "deadline_exceeded"
        return EmbeddingAPIError(message, code=code, status=status, statistics=statistics)
    def before_send(request):
        left = check()
        timeout = min(float(request_timeout), left) if left is not None else float(request_timeout)
        # httpx's request hook runs immediately before the transport attempt.
        request.extensions["timeout"] = dict.fromkeys(("connect", "read", "write", "pool"), timeout)
        statistics.update(request_started=True, embedding_requests=1, timeout_seconds=timeout)
    endpoint = settings.base_url.rstrip("/") + "/embeddings"
    start = perf_counter()
    response = None
    def capture_response_usage():
        # A close failure can occur after a complete, charged response arrived.
        if response is not None:
            try:
                body = response.json()
            except ValueError:
                return
            usage = body.get("usage") if isinstance(body, dict) else None
            tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
            statistics["total_tokens"] = tokens if type(tokens) is int and tokens >= 0 else None
    try:
        check()
        scope = (httpx.Client(timeout=request_timeout, transport=transport, follow_redirects=False)
                 if http_client is None else nullcontext(http_client))
        with scope as client:
            hooks = client.event_hooks["request"]
            hooks.append(before_send)
            try:
                response = client.post(endpoint, headers={"Authorization": f"Bearer {settings.api_key}"},
                                       json=payload, timeout=request_timeout)
            finally:
                hooks.remove(before_send)
    except DeadlineExceeded:
        raise fail("向量发送前截止预算已到", code="deadline_exceeded", status="budget_exceeded") from None
    except httpx.HTTPError as exc:
        capture_response_usage()
        statistics["failed_requests"] = statistics["embedding_requests"]
        try:
            check()
        except DeadlineExceeded:
            statistics["interrupted_failure"] = {"code": "embedding_http_error", "type": type(exc).__name__}
            raise fail("向量请求失败时已超过截止预算", code="deadline_exceeded", status="budget_exceeded") from None
        raise fail(f"向量请求未完成：{type(exc).__name__}", code="embedding_http_error") from None
    except Exception:
        capture_response_usage()
        statistics["failed_requests"] = statistics["embedding_requests"]
        raise fail("向量客户端或发送步骤未完成", code="embedding_setup_error") from None
    elapsed = perf_counter() - start

    try:
        body = response.json()
    except ValueError as exc:
        raise fail(f"HTTP {response.status_code}，响应不是 JSON") from exc
    usage = body.get("usage") if isinstance(body, dict) else None
    tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    statistics["total_tokens"] = tokens if type(tokens) is int and tokens >= 0 else None
    try:
        check()
    except DeadlineExceeded:
        if response.is_error:
            statistics["failed_requests"] = statistics["embedding_requests"]
            statistics["interrupted_failure"] = {"code": "embedding_http_status", "http_status": response.status_code}
        raise fail("向量响应返回时截止预算已到", code="deadline_exceeded", status="budget_exceeded") from None
    if response.is_error:
        error = body.get("error") if isinstance(body, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        # 不打印完整响应，以免供应商把请求内容或凭据回显到日志中。
        # 错误码只接受短标识，不能把供应商的任意回显字符串放入报告。
        suffix = f"，错误码 {code}" if isinstance(code, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", code) else ""
        raise fail(f"向量请求失败：HTTP {response.status_code}{suffix}")
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise fail("向量响应缺少 data 列表")

    data = body["data"]
    if len(data) != len(texts):
        raise fail(f"向量数量不符：输入 {len(texts)} 条，返回 {len(data)} 条")
    vectors: list[list[float] | None] = [None] * len(texts)
    for item in data:
        if not isinstance(item, dict):
            raise fail("data 条目不是对象")
        index = item.get("index")
        embedding = item.get("embedding")
        if type(index) is not int or not 0 <= index < len(texts) or vectors[index] is not None:
            raise fail("data 的 index 无效或重复")
        if not isinstance(embedding, list) or not embedding:
            raise fail("data 条目缺少非空 embedding")
        if any(type(value) not in (float, int) or not isfinite(value) for value in embedding):
            raise fail("向量含有非有限数值")
        vectors[index] = [float(value) for value in embedding]

    ordered_vectors = [vector for vector in vectors if vector is not None]
    dimensions = {len(vector) for vector in ordered_vectors}
    if len(dimensions) != 1 or (settings.dimension is not None and dimensions != {settings.dimension}):
        raise fail(f"向量维度不一致或不等于配置值：{sorted(dimensions)}")
    usage = body.get("usage")
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    try:
        check()
    except DeadlineExceeded:
        raise fail("向量解析结束时截止预算已到", code="deadline_exceeded", status="budget_exceeded") from None
    return EmbeddingBatch(
        vectors=ordered_vectors,
        elapsed_seconds=elapsed,
        total_tokens=total_tokens if type(total_tokens) is int and total_tokens >= 0 else None,
        request_started=statistics["request_started"], request_attempts=statistics["embedding_requests"],
        timeout_seconds=statistics["timeout_seconds"], accounting_basis="http_send_hook",
    )


embed_texts.supports_remaining_time = True


class LegacyEmbedderAdapter:
    """Explicit two-argument compatibility; hidden HTTP counts stay unknown.

    This adapter checks stages but cannot shorten the legacy callable's HTTP
    timeout. Use native embed_texts for actual remaining request timeouts.
    """
    supports_remaining_time = True

    def __init__(self, embedder):
        if not callable(embedder):
            raise ValueError("legacy embedder must be callable")
        self.embedder = embedder

    def __call__(self, texts, settings, *, remaining_seconds=None, request_timeout=30.0):
        remaining(remaining_seconds)
        try:
            batch = self.embedder(texts, settings)
        except Exception:
            raise EmbeddingAPIError("旧向量接口执行失败", statistics={
                "embedding_requests": None, "failed_requests": None, "total_tokens": None,
                "request_started": None, "timeout_seconds": None,
                "accounting_basis": "opaque_legacy_callable"}) from None
        statistics = {"embedding_requests": None, "failed_requests": None,
                      "total_tokens": batch.total_tokens, "request_started": None,
                      "timeout_seconds": None, "accounting_basis": "opaque_legacy_callable"}
        try:
            remaining(remaining_seconds)
        except DeadlineExceeded:
            raise EmbeddingAPIError("旧向量接口返回时截止预算已到", code="deadline_exceeded",
                                    status="budget_exceeded", statistics=statistics) from None
        return EmbeddingBatch(batch.vectors, batch.elapsed_seconds, batch.total_tokens,
                              request_started=None, request_attempts=None, timeout_seconds=None,
                              accounting_basis="opaque_legacy_callable")
