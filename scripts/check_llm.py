"""D5 任务 B：经过真实 SDK 和本地 MockTransport 的聊天边界检查。

运行：python -X utf8 -m scripts.check_llm

使用假的模型配置、httpx.MockTransport 和可控时钟；不读取 .env、不访问
付费模型、不打开正式数据库。MockTransport 会接收真正的 SDK HTTP 请求，
因而计数检查能发现 SDK 隐式重试，而非只验证被替换的 create() 方法。
"""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

from paper_assistant.config import LLMSettings
from paper_assistant.llm_client import (
    ChatBudget, ChatPolicy, LLMCallError, RecordedLLM, invoke_llm,
)


MOCK_HTTP_SENDS = 0
_MISSING = object()


class FakeClock:
    """只由测试明确推进，避免 sleep 和对真实机器速度的假设。"""

    def __init__(self, now: float = 10.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def completion(content="{\"ok\": true}", *, finish_reason="stop", usage=_MISSING):
    body = {
        "id": "offline-completion",
        "object": "chat.completion",
        "created": 1,
        "model": "offline-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        }],
    }
    if usage is _MISSING:
        body["usage"] = {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}
    elif usage is not None:
        body["usage"] = usage
    return body


def http_error(status: int, *, message="offline provider failure"):
    return status, {"error": {"type": "offline_error", "code": "offline", "message": message}}


class LLMChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = LLMSettings(
            provider="deepseek", model_id="offline-model", api_key="offline-credential-do-not-log",
            base_url="https://example.invalid/v1", timeout=30.0,
        )
        self.clock = FakeClock()
        self.messages = [{"role": "user", "content": "Return a short JSON object."}]

    def client(self, *outcomes, policy=None, budget=None, clock=None):
        """每个 outcome 是 (HTTP状态, JSON) 或接收 request 的故障函数。"""
        requests = []
        remaining = list(outcomes)

        def handle(request):
            global MOCK_HTTP_SENDS
            MOCK_HTTP_SENDS += 1
            requests.append(request)
            if not remaining:
                raise AssertionError("SDK 发出了超出测试预期的请求")
            outcome = remaining.pop(0)
            if callable(outcome):
                return outcome(request)
            status, body = outcome
            return httpx.Response(status, json=body, request=request)

        client = RecordedLLM(
            self.settings, policy=policy, budget=budget,
            transport=httpx.MockTransport(handle), clock=clock or self.clock,
        )
        self.addCleanup(client.close)
        return client, requests

    def assert_counts(self, result, requests, expected):
        statistics = result.statistics if isinstance(result, LLMCallError) else result["statistics"]
        self.assertEqual(len(requests), expected)
        self.assertEqual(statistics["sdk_request_attempts"], expected)
        self.assertEqual(statistics["http_request_attempts"], expected)
        return statistics

    def test_complete_response_has_real_usage_finish_reason_and_explicit_payload(self):
        client, requests = self.client((200, completion()))
        result = client.invoke(self.messages, require_json=True)
        self.assertEqual(result["status"], "success")
        self.assertIsNone(result["output_issue"])
        self.assertEqual(json.loads(result["content"]), {"ok": True})
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["usage"]["total_tokens"], 25)
        stats = self.assert_counts(result, requests, 1)
        self.assertTrue(stats["usage_complete"])
        self.assertEqual(stats["total_tokens"], 25)
        self.assertEqual(len(result["attempts"]), 1)
        attempt = result["attempts"][0]
        self.assertEqual(attempt["number"], 1)
        self.assertEqual(attempt["purpose"], "answer")
        self.assertFalse(attempt["is_network_retry"])
        self.assertEqual(attempt["http_request_attempts"], 1)
        payload = json.loads(requests[0].content)
        self.assertEqual(payload["model"], self.settings.model_id)
        self.assertEqual(payload["messages"], self.messages)
        self.assertEqual(payload["max_tokens"], 1200)
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["thinking"], {"type": "disabled"})

        from paper_assistant.agent_actions import search_tool_definition
        calls = [{"id": f"call-{i}", "type": "function", "function": {"name": "search", "arguments": "{}"}}
                 for i in range(2)]
        body = completion(None, finish_reason="tool_calls")
        body["choices"][0]["message"]["tool_calls"] = calls
        client, requests = self.client((200, body), (200, completion()))
        tools = [search_tool_definition()]
        first = client.invoke(self.messages, tools=tools, tool_choice="auto", require_json=True)
        self.assertEqual(first["status"], "success")
        self.assertIsNone(first["content"])
        self.assertEqual(first["tool_calls"], calls)
        self.assertEqual(first["attempts"][0]["tool_calls"], calls)
        messages = [*self.messages, {"role": "assistant", "content": None, "tool_calls": calls},
                    *[{"role": "tool", "tool_call_id": c["id"], "content": "no_hits"} for c in calls]]
        result = client.invoke(messages, require_json=True)
        self.assertEqual(json.loads(requests[0].content)["tools"], tools)
        self.assertEqual(json.loads(requests[0].content)["tool_choice"], "auto")
        self.assertEqual(json.loads(requests[1].content)["messages"], messages)
        self.assertNotIn("tools", json.loads(requests[1].content))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["statistics"]["total_tokens"], 50)
        self.assert_counts(result, requests, 2)

    def test_explicit_parameters_are_sent_and_timeout_uses_smallest_limit(self):
        policy = ChatPolicy(max_tokens=240, temperature=0.0, request_timeout=7.0)
        client, requests = self.client((200, completion()), policy=policy)
        result = client.invoke(self.messages)
        payload = json.loads(requests[0].content)
        self.assertEqual(payload["max_tokens"], 240)
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(result["attempts"][0]["timeout_seconds"], 7.0)
        for value in requests[0].extensions["timeout"].values():
            self.assertEqual(value, 7.0)

    def test_usage_missing_is_none_and_does_not_claim_zero_tokens(self):
        client, requests = self.client((200, completion(usage=None)))
        result = client.invoke(self.messages)
        self.assertIsNone(result["usage"])
        self.assertIsNone(result["attempts"][0]["usage"])
        stats = self.assert_counts(result, requests, 1)
        self.assertFalse(stats["usage_complete"])
        self.assertIsNone(stats["total_tokens"])

    def test_shared_usage_stays_incomplete_when_one_response_has_no_usage(self):
        client, requests = self.client((200, completion(usage=None)), (200, completion()))
        first = client.invoke(self.messages)
        second = client.invoke(self.messages, purpose="repair")
        self.assertIsNone(first["statistics"]["total_tokens"])
        self.assertIsNone(second["statistics"]["total_tokens"])
        self.assertFalse(second["statistics"]["usage_complete"])
        self.assert_counts(second, requests, 2)

    def test_available_usage_is_summed_across_explicit_repair(self):
        client, requests = self.client((200, completion("not JSON")), (200, completion()))
        first = client.invoke(self.messages, require_json=True)
        self.assertEqual(first["output_issue"], "invalid_json")
        second = client.invoke(self.messages, purpose="repair", require_json=True)
        self.assertEqual(second["statistics"]["total_tokens"], 50)
        self.assertEqual(second["statistics"]["repairs"], 1)
        self.assertEqual(len(second["attempts"]), 1)
        self.assertEqual(second["attempts"][0]["purpose"], "repair")
        self.assert_counts(second, requests, 2)

    def test_invalid_json_is_recorded_without_automatic_format_repair(self):
        client, requests = self.client((200, completion("```json\n{}\n```")))
        result = client.invoke(self.messages, require_json=True)
        self.assertEqual(result["status"], "invalid_output")
        self.assertEqual(result["output_issue"], "invalid_json")
        self.assertEqual(result["content"], "```json\n{}\n```")
        self.assert_counts(result, requests, 1)
        self.assertEqual(result["statistics"]["repairs"], 0)

    def test_text_mode_does_not_require_json(self):
        client, requests = self.client((200, completion("A short explanation.")))
        result = client.invoke(self.messages)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["content"], "A short explanation.")
        self.assert_counts(result, requests, 1)

    def test_empty_output_is_distinct_from_truncation_and_json_failure(self):
        for content in [None, "", "   \n\t"]:
            with self.subTest(content=content):
                client, requests = self.client((200, completion(content)))
                result = client.invoke(self.messages, require_json=True)
                self.assertEqual(result["status"], "invalid_output")
                self.assertEqual(result["output_issue"], "empty_output")
                self.assert_counts(result, requests, 1)

    def test_length_finish_reason_rejects_even_parseable_json(self):
        client, requests = self.client((200, completion("{}", finish_reason="length")))
        result = client.invoke(self.messages, require_json=True)
        self.assertEqual(result["status"], "invalid_output")
        self.assertEqual(result["output_issue"], "truncated")
        self.assertEqual(result["finish_reason"], "length")
        self.assertEqual(result["content"], "{}")
        self.assert_counts(result, requests, 1)

    def test_unexpected_finish_reason_is_not_success(self):
        for reason in ["content_filter", "tool_calls", None]:
            with self.subTest(reason=reason):
                client, requests = self.client((200, completion("{}", finish_reason=reason)))
                result = client.invoke(self.messages, require_json=True)
                self.assertEqual(result["status"], "invalid_output")
                self.assertIn(result["output_issue"], ["unexpected_finish_reason", "malformed_response"])
                self.assert_counts(result, requests, 1)

    def test_sdk_accepted_missing_choice_is_classified_as_malformed_response(self):
        body = completion()
        body["choices"] = []
        client, requests = self.client((200, body))
        result = client.invoke(self.messages, require_json=True)
        self.assertEqual(result["status"], "invalid_output")
        self.assertEqual(result["output_issue"], "malformed_response")
        self.assert_counts(result, requests, 1)

    def test_authentication_and_other_nonretryable_http_errors_send_once(self):
        for status in [400, 401, 403, 404, 422]:
            with self.subTest(status=status):
                client, requests = self.client(http_error(status))
                with self.assertRaises(LLMCallError) as caught:
                    client.invoke(self.messages)
                error = caught.exception
                self.assertEqual(error.status, "tool_error")
                self.assert_counts(error, requests, 1)
                self.assertEqual(error.statistics["network_retries"], 0)
                self.assertEqual(error.attempts[0]["http_status"], status)

    def test_retryable_http_error_retries_once_and_preserves_both_attempts(self):
        for status in [408, 409, 429, 500, 503]:
            with self.subTest(status=status):
                client, requests = self.client(http_error(status), (200, completion()))
                result = client.invoke(self.messages)
                self.assertEqual(result["status"], "success")
                self.assert_counts(result, requests, 2)
                self.assertEqual(result["statistics"]["network_retries"], 1)
                self.assertEqual(len(result["attempts"]), 2)
                self.assertEqual(result["attempts"][0]["http_status"], status)
                self.assertTrue(result["attempts"][1]["is_network_retry"])

        from dataclasses import replace
        from paper_assistant.d9_runtime import INTERACTIVE_AGENT_POLICY
        self.settings = replace(self.settings, timeout=300.0)
        budget = ChatBudget(INTERACTIVE_AGENT_POLICY, clock=self.clock)
        client, requests = self.client(http_error(503), (200, completion()),
                                       http_error(429), (200, completion()), budget=budget)
        first = client.invoke(self.messages)
        second = client.invoke(self.messages, purpose="synthesis", request_timeout=90.0)
        self.assertEqual(len(requests), 4)
        self.assertEqual(budget.network_retries, 2)
        self.assertEqual([r["is_network_retry"] for r in budget.records], [False, True, False, True])
        self.assertEqual([r["purpose"] for r in budget.records], ["answer", "answer", "synthesis", "synthesis"])
        self.assertEqual([r["timeout_seconds"] for r in budget.records], [300, 300, 90, 90])
        for request, timeout in zip(requests, (300,300,90,90)):
            self.assertTrue(all(value == timeout for value in request.extensions["timeout"].values()))
        self.assertEqual(first["attempts"][0]["http_status"], 503)
        self.assertEqual(second["attempts"][0]["http_status"], 429)
        self.assertEqual(budget.statistics()["known_total_tokens"], 50)
        self.assertIsNone(budget.statistics()["total_tokens"])

        budget = ChatBudget(INTERACTIVE_AGENT_POLICY, clock=self.clock)
        client, requests = self.client(http_error(500), http_error(503),
            http_error(500), (200, completion()), budget=budget)
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages)
        self.assertEqual(len(requests), 2)  # no third hidden send in this invoke
        self.assertEqual(len(caught.exception.attempts), 2)
        result = client.invoke(self.messages, purpose="repair")
        self.assertEqual(len(requests), 4)
        self.assertEqual(result["statistics"]["network_retries"], 2)
        self.assertEqual(result["statistics"]["repairs"], 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(ChatPolicy(max_attempts=8, max_repairs=7).max_attempts, 8)
        client, requests = self.client(http_error(401), policy=INTERACTIVE_AGENT_POLICY)
        with self.assertRaises(LLMCallError):
            client.invoke(self.messages)
        self.assertEqual(len(requests), 1)

    def test_second_retryable_failure_stops_without_sdk_hidden_retry(self):
        client, requests = self.client(http_error(500), http_error(503))
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages)
        self.assertEqual(caught.exception.status, "tool_error")
        self.assert_counts(caught.exception, requests, 2)
        self.assertEqual(caught.exception.statistics["network_retries"], 1)
        self.assertEqual(len(caught.exception.attempts), 2)

    def test_transport_timeout_retries_once(self):
        def timeout(request):
            raise httpx.ReadTimeout("offline transport timeout", request=request)

        client, requests = self.client(timeout, (200, completion()))
        result = client.invoke(self.messages)
        self.assert_counts(result, requests, 2)
        self.assertEqual(result["statistics"]["network_retries"], 1)

    def test_transport_connection_failure_retries_once(self):
        def failed_connection(request):
            raise httpx.ConnectError("offline connection failure", request=request)

        client, requests = self.client(failed_connection, (200, completion()))
        result = client.invoke(self.messages)
        self.assert_counts(result, requests, 2)
        self.assertEqual(result["statistics"]["network_retries"], 1)

    def test_network_retry_and_external_format_repair_share_three_request_budget(self):
        client, requests = self.client(http_error(500), (200, completion("not JSON")), (200, completion()))
        first = client.invoke(self.messages, require_json=True)
        self.assertEqual(first["output_issue"], "invalid_json")
        second = client.invoke(self.messages, purpose="repair", require_json=True)
        stats = self.assert_counts(second, requests, 3)
        self.assertEqual(stats["network_retries"], 1)
        self.assertEqual(stats["repairs"], 1)
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages)
        self.assertEqual(caught.exception.status, "budget_exceeded")
        self.assert_counts(caught.exception, requests, 3)

    def test_network_retry_cannot_be_reset_by_external_citation_repair(self):
        client, requests = self.client(http_error(500), (200, completion()), http_error(503))
        # B 不检查引用；C/D 可以把一份 JSON 合法但引用无效的草稿交回修复。
        first = client.invoke(self.messages, require_json=True)
        self.assertEqual(first["status"], "success")
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages, purpose="repair", require_json=True)
        self.assertEqual(caught.exception.status, "tool_error")
        stats = self.assert_counts(caught.exception, requests, 3)
        self.assertEqual(stats["network_retries"], 1)
        self.assertEqual(stats["repairs"], 1)

    def test_reopened_client_preserves_the_same_shared_request_budget(self):
        budget = ChatBudget(clock=self.clock)
        first_client, first_requests = self.client(http_error(500), (200, completion("bad JSON")), budget=budget)
        first = first_client.invoke(self.messages, require_json=True)
        self.assertEqual(first["output_issue"], "invalid_json")
        first_client.close()
        second_client, second_requests = self.client((200, completion()), budget=budget)
        second = second_client.invoke(self.messages, purpose="repair", require_json=True)
        self.assertEqual(second["statistics"]["sdk_request_attempts"], 3)
        self.assertEqual(second["statistics"]["http_request_attempts"], 3)
        self.assertEqual(second["statistics"]["network_retries"], 1)
        self.assertEqual(second["statistics"]["repairs"], 1)
        self.assertEqual(len(first_requests) + len(second_requests), 3)
        with self.assertRaises(LLMCallError) as caught:
            second_client.invoke(self.messages)
        self.assertEqual(caught.exception.status, "budget_exceeded")
        self.assertEqual(len(second_requests), 1)

    def test_second_explicit_repair_is_rejected_without_another_request(self):
        client, requests = self.client((200, completion("bad")), (200, completion("still bad")))
        client.invoke(self.messages, require_json=True)
        second = client.invoke(self.messages, purpose="repair", require_json=True)
        self.assertEqual(second["status"], "invalid_output")
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages, purpose="repair", require_json=True)
        self.assertEqual(caught.exception.status, "budget_exceeded")
        self.assert_counts(caught.exception, requests, 2)

    def test_lower_request_budget_blocks_network_retry(self):
        policy = ChatPolicy(max_attempts=1)
        client, requests = self.client(http_error(500), policy=policy)
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages)
        self.assertEqual(caught.exception.status, "budget_exceeded")
        self.assert_counts(caught.exception, requests, 1)

    def test_expired_deadline_sends_no_request(self):
        budget = ChatBudget(clock=self.clock, deadline=self.clock())
        client, requests = self.client(budget=budget)
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages)
        self.assertEqual(caught.exception.status, "budget_exceeded")
        self.assert_counts(caught.exception, requests, 0)

    def test_request_timeout_is_shrunk_to_remaining_deadline(self):
        budget = ChatBudget(clock=self.clock, deadline=self.clock() + 2.5)
        client, requests = self.client((200, completion()), budget=budget)
        result = client.invoke(self.messages)
        self.assertEqual(result["attempts"][0]["timeout_seconds"], 2.5)
        for value in requests[0].extensions["timeout"].values():
            self.assertEqual(value, 2.5)

    def test_late_success_is_budget_exceeded_and_still_records_usage(self):
        def late_response(request):
            self.clock.advance(121.0)
            return httpx.Response(200, json=completion(), request=request)

        client, requests = self.client(late_response)
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages)
        self.assertEqual(caught.exception.status, "budget_exceeded")
        self.assert_counts(caught.exception, requests, 1)
        self.assertEqual(caught.exception.attempts[0]["usage"]["total_tokens"], 25)

    def test_deadline_expiring_after_failure_prevents_retry(self):
        def late_failure(request):
            self.clock.advance(121.0)
            return httpx.Response(503, json={"error": {"message": "offline late failure"}}, request=request)

        client, requests = self.client(late_failure)
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages)
        self.assertEqual(caught.exception.status, "budget_exceeded")
        self.assert_counts(caught.exception, requests, 1)

    def test_invalid_messages_and_purpose_are_rejected_before_request(self):
        bad_messages = [None, [], "question", [{}], [{"role": "unknown", "content": "x"}],
                        [{"role": "user", "content": " "}], [{"role": "user", "content": 3}]]
        for messages in bad_messages:
            with self.subTest(messages=messages):
                client, requests = self.client()
                with self.assertRaises((ValueError, TypeError, LLMCallError)):
                    client.invoke(messages)
                self.assertEqual(len(requests), 0)
        client, requests = self.client()
        with self.assertRaises((ValueError, TypeError, LLMCallError)):
            client.invoke(self.messages, purpose="unbounded_retry")
        self.assertEqual(len(requests), 0)

    def test_invalid_policy_values_are_rejected_before_request(self):
        invalid = [
            {"max_tokens": 0}, {"max_tokens": True}, {"max_tokens": 1.5},
            {"temperature": float("nan")}, {"temperature": float("inf")},
            {"temperature": -0.1}, {"temperature": True},
            {"request_timeout": 0}, {"request_timeout": float("inf")},
            {"total_timeout": 0}, {"total_timeout": float("nan")},
            {"max_attempts": 0}, {"max_attempts": True}, {"max_attempts": 4},
            {"max_network_retries": -1}, {"max_repairs": -1},
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises((ValueError, TypeError, LLMCallError)):
                    policy = ChatPolicy(**kwargs)
                    client, requests = self.client(policy=policy)
                    client.invoke(self.messages)

    def test_provider_credential_and_authorization_echo_do_not_leak_to_error_record(self):
        leaked = f"api_key={self.settings.api_key}; Authorization: Bearer provider-echo-token"
        client, requests = self.client(http_error(401, message=leaked))
        with self.assertRaises(LLMCallError) as caught:
            client.invoke(self.messages)
        error = caught.exception
        safe = json.dumps({"message": str(error), "code": error.code,
                           "attempts": error.attempts, "statistics": error.statistics}, ensure_ascii=False)
        self.assertNotIn(self.settings.api_key, safe)
        self.assertNotIn("provider-echo-token", safe)
        self.assertNotIn("Authorization:", safe)
        self.assertIsNone(error.__cause__)
        self.assert_counts(error, requests, 1)

    def test_response_credential_echo_is_redacted_before_returning_and_recording(self):
        body = completion(f'{{"echo": "{self.settings.api_key}"}}')
        client, requests = self.client((200, body))
        result = client.invoke(self.messages, require_json=True)
        self.assertNotIn(self.settings.api_key, json.dumps(result, ensure_ascii=False))
        self.assert_counts(result, requests, 1)

    def test_response_authorization_echo_is_redacted_before_recording(self):
        body = completion('{"echo": "Authorization: Bearer provider-echo-token"}')
        client, requests = self.client((200, body))
        result = client.invoke(self.messages, require_json=True)
        self.assertNotIn("provider-echo-token", json.dumps(result, ensure_ascii=False))
        self.assert_counts(result, requests, 1)

    def test_nonstring_content_cannot_copy_arbitrary_provider_objects_into_logs(self):
        body = completion({"Authorization": "Bearer provider-echo-token", "api_key": self.settings.api_key})
        client, requests = self.client((200, body))
        result = client.invoke(self.messages, require_json=True)
        self.assertEqual(result["status"], "invalid_output")
        safe = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(self.settings.api_key, safe)
        self.assertNotIn("provider-echo-token", safe)
        self.assert_counts(result, requests, 1)

    def test_usage_extra_keys_cannot_echo_credentials_into_logs(self):
        usage = {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25,
                 self.settings.api_key: 1, "Authorization: Bearer provider-echo-token": 2}
        client, requests = self.client((200, completion(usage=usage)))
        result = client.invoke(self.messages)
        safe = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(self.settings.api_key, safe)
        self.assertNotIn("provider-echo-token", safe)
        self.assertEqual(result["usage"]["total_tokens"], 25)
        self.assert_counts(result, requests, 1)

    def test_context_manager_closes_transport(self):
        client, requests = self.client((200, completion()))
        with client:
            client.invoke(self.messages)
        with self.assertRaises((RuntimeError, LLMCallError)):
            client.invoke(self.messages)
        self.assertEqual(len(requests), 1)

    def test_legacy_d2_string_entry_remains_available_without_network(self):
        with patch("paper_assistant.llm_client.HelloAgentsLLM") as cls:
            cls.return_value.invoke.return_value = "legacy response"
            output = invoke_llm(self.messages, self.settings)
        self.assertEqual(output, "legacy response")
        self.assertEqual(cls.call_args.kwargs["max_tokens"], 128)
        cls.return_value.invoke.assert_called_once_with(self.messages)


def main():
    program = unittest.main(module=__name__, exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    main()
