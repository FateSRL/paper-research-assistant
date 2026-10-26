"""通过百炼兼容接口对候选原文进行语义重排。"""

from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from typing import Sequence

import httpx

from paper_assistant.config import RerankSettings
from paper_assistant.deadline import DeadlineExceeded, remaining


@dataclass(frozen=True)
class RerankBatch:
    results: list[dict]
    requests: int
    elapsed_seconds: float
    usage: dict | None


class RerankError(RuntimeError):
    """保留实际请求次数和耗时，错误消息不包含凭据或响应正文。"""

    def __init__(self, message, *, code, requests=0, elapsed_seconds=0.0, usage=None):
        super().__init__(message)
        self.code = code
        self.requests = requests
        self.elapsed_seconds = elapsed_seconds
        self.usage = usage


class RerankClient:
    """每轮候选一次批量请求，没有网络重试。"""

    supports_remaining_time = True

    def __init__(self, settings: RerankSettings, *, transport=None):
        self.settings = settings
        self._client = httpx.Client(
            timeout=settings.timeout,
            transport=transport,
            follow_redirects=False,
            event_hooks={"request": [self._before_send]},
        )

    @staticmethod
    def _before_send(request):
        request.extensions.pop("rerank_accounting")["requests"] = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def close(self):
        self._client.close()

    def rerank(self, query: str, documents: Sequence[str], *, remaining_seconds=None) -> RerankBatch:
        start = perf_counter()
        accounting = {"requests": 0}
        usage = None

        def fail(message, code):
            return RerankError(message, code=code, requests=accounting["requests"],
                               elapsed_seconds=perf_counter() - start, usage=usage)

        if not documents:
            return RerankBatch([], 0, 0.0, None)
        try:
            left = remaining(remaining_seconds)
            timeout = min(self.settings.timeout, left) if left is not None else self.settings.timeout
            response = self._client.post(
                self.settings.base_url.rstrip("/") + "/reranks",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                json={"model": self.settings.model, "query": query, "documents": list(documents),
                      "top_n": len(documents), "return_documents": False},
                timeout=timeout,
                extensions={"rerank_accounting": accounting},
            )
        except (httpx.TimeoutException, DeadlineExceeded):
            raise fail("重排请求超过本轮时限", "timeout") from None
        except httpx.HTTPError:
            raise fail("重排请求未完成", "http") from None

        try:
            body = response.json()
        except ValueError:
            if response.is_error:
                raise fail(f"重排请求失败：HTTP {response.status_code}", "http") from None
            raise fail("重排响应不是 JSON", "invalid_response") from None
        if isinstance(body, dict) and isinstance(body.get("usage"), dict):
            usage = body["usage"]
        if response.is_error:
            raise fail(f"重排请求失败：HTTP {response.status_code}", "http") from None
        try:
            remaining(remaining_seconds)
        except DeadlineExceeded:
            raise fail("重排响应返回时本轮时限已耗尽", "timeout") from None

        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list) or len(results) != len(documents):
            raise fail("重排响应未覆盖全部候选", "invalid_response")
        indexes = set()
        ordered = []
        for result in results:
            if not isinstance(result, dict):
                raise fail("重排结果条目格式错误", "invalid_response")
            index, score = result.get("index"), result.get("relevance_score")
            if type(index) is not int or not 0 <= index < len(documents) or index in indexes:
                raise fail("重排结果位置无效或重复", "invalid_response")
            if type(score) not in (int, float) or not isfinite(score) or not 0 <= score <= 1:
                raise fail("重排相关性分数无效", "invalid_response")
            indexes.add(index)
            ordered.append({"index": index, "relevance_score": float(score)})
        return RerankBatch(ordered, accounting["requests"], perf_counter() - start, usage)
