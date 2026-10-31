"""Whole-request token budgeting for chat calls.

This is a small Python adaptation of RAGFlow's message fitting policy: count
the assembled request (messages and tool definitions), reserve the configured
output budget, and apply the existing 97% context margin. Evidence-aware
trimming remains in the Agent caller so JSON payloads and tool pairs stay valid.
"""

from functools import lru_cache
import json
from math import floor

from paper_assistant.context import _token_counter


DEFAULT_CONTEXT_LENGTH = 8192
CONTEXT_MARGIN = 0.97


def effective_context_length(value):
    """Use the configured positive length, otherwise RAGFlow's 8192 fallback."""
    return value if type(value) is int and value > 0 else DEFAULT_CONTEXT_LENGTH


def context_fit_budget(context_length, output_tokens):
    """Input budget after the 97% margin and the actual output reservation."""
    length = effective_context_length(context_length)
    output = output_tokens if type(output_tokens) is int and output_tokens > 0 else 0
    return max(1, min(floor(length * CONTEXT_MARGIN), max(0, length - output)))


@lru_cache(maxsize=1)
def _counter():
    return _token_counter()


def count_text(value):
    if not isinstance(value, str) or not value:
        return 0
    return _counter()(value)


def count_request_tokens(messages, tools=None):
    """Conservative count of the complete request text and tool scaffolding."""
    total = 0
    for message in messages:
        total += 8
        for key in ("content", "tool_call_id", "name"):
            total += count_text(message.get(key))
        tool_calls = message.get("tool_calls")
        if tool_calls:
            total += count_text(json.dumps(tool_calls, ensure_ascii=False))
    if tools:
        total += count_text(json.dumps(tools, ensure_ascii=False))
    return total
