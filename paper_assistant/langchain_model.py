"""LangChain chat-model adapter over the existing RecordedLLM.

The adapter only translates messages, tool schemas and responses.  The original
RecordedLLM remains the single owner of HTTP, retries, purposes, timeouts, the
shared budget and recorded usage.
"""

from copy import deepcopy
import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr


MODEL_PROTOCOL = "langchain-core-1.7.3/BaseChatModel"
ADAPTER_VERSION = "recorded-chat-model-v1"
INVALID_TOOL_ARGS = "__d4_invalid_tool_arguments__"


def _attach_raw(message, raw):
    return message.model_copy(update={
        "additional_kwargs": {**message.additional_kwargs,
                              "recorded_openai_message": deepcopy(raw)}})


def to_langchain_messages(messages):
    """Convert the current OpenAI-style history without changing its content."""
    converted = []
    for raw in messages:
        role = raw.get("role")
        content = raw.get("content")
        if role == "system":
            message = SystemMessage(content=content or "")
        elif role == "user":
            message = HumanMessage(content=content or "")
        elif role == "assistant":
            tool_calls = []
            for call in raw.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments"))
                except (TypeError, ValueError):
                    arguments = None
                if isinstance(arguments, dict):
                    tool_calls.append({"name": function.get("name"), "args": arguments,
                                       "id": call.get("id"), "type": "tool_call"})
            message = AIMessage(content=content or "", tool_calls=tool_calls)
        elif role == "tool":
            message = ToolMessage(content=content or "",
                                  tool_call_id=raw.get("tool_call_id"))
        else:
            raise ValueError("unsupported_message_role")
        converted.append(_attach_raw(message, raw))
    return converted


def to_openai_messages(messages):
    """Return exact recorded messages for the current loop; support future messages."""
    converted = []
    for message in messages:
        raw = message.additional_kwargs.get("recorded_openai_message")
        if isinstance(raw, dict):
            converted.append(deepcopy(raw))
            continue
        if isinstance(message, SystemMessage):
            converted.append({"role": "system", "content": str(message.content)})
        elif isinstance(message, HumanMessage):
            converted.append({"role": "user", "content": str(message.content)})
        elif isinstance(message, ToolMessage):
            converted.append({"role": "tool", "content": str(message.content),
                              "tool_call_id": message.tool_call_id})
        elif isinstance(message, AIMessage):
            raw_response = message.additional_kwargs.get("recorded_response")
            raw_calls = message.additional_kwargs.get("raw_tool_calls")
            if isinstance(raw_response, dict) and isinstance(raw_calls, list):
                item = {"role": "assistant", "content": raw_response.get("content")}
                if raw_calls:
                    item["tool_calls"] = deepcopy(raw_calls)
                converted.append(item)
                continue
            tool_calls = [{"id": call.get("id"), "type": "function",
                           "function": {"name": call.get("name"),
                                        "arguments": json.dumps(call.get("args") or {},
                                            ensure_ascii=False, allow_nan=False)}}
                          for call in message.tool_calls]
            item = {"role": "assistant", "content": message.content or ""}
            if tool_calls:
                item["tool_calls"] = tool_calls
            converted.append(item)
        else:
            raise ValueError("unsupported_langchain_message")
    return converted


def response_to_ai_message(response):
    """Carry the complete raw response beside a standard AIMessage."""
    raw_calls = deepcopy(response.get("tool_calls") or [])
    tool_calls = []
    for call in raw_calls:
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments"))
        except (TypeError, ValueError):
            arguments = None
        if isinstance(arguments, dict):
            tool_calls.append({"name": function.get("name"), "args": arguments,
                               "id": call.get("id"), "type": "tool_call"})
        else:
            # Keep malformed calls dispatchable with their original id/order;
            # the graph wrapper returns the project's invalid_arguments
            # observation and never executes the business tool.
            tool_calls.append({"name": function.get("name"),
                               "args": {INVALID_TOOL_ARGS: function.get("arguments")},
                               "id": call.get("id"), "type": "tool_call"})
    message = AIMessage(
        content=response.get("content") or "",
        tool_calls=tool_calls,
        additional_kwargs={"recorded_response": deepcopy(response),
                           "raw_tool_calls": raw_calls},
        response_metadata={"status": response.get("status"),
                           "finish_reason": response.get("finish_reason"),
                           "model_name": response.get("model_name")},
    )
    return message


def recorded_response(message):
    """Bridge the raw response belonging to this exact AIMessage."""
    if not isinstance(message, AIMessage):
        raise TypeError("recorded_response_requires_AIMessage")
    raw = message.additional_kwargs.get("recorded_response")
    if not isinstance(raw, dict):
        raise ValueError("recorded_response_missing")
    return deepcopy(raw)


class RecordedChatModel(BaseChatModel):
    """Synchronous LangChain chat model delegating to one existing RecordedLLM."""

    _client: Any = PrivateAttr()
    _purpose: str = PrivateAttr(default="answer")

    def __init__(self, client, **kwargs):
        super().__init__(**kwargs)
        self._client = client

    @property
    def _llm_type(self):
        return "recorded-chat-model"

    @property
    def _identifying_params(self):
        settings = getattr(self._client, "settings", None)
        return {"provider": getattr(settings, "provider", None),
                "model": getattr(settings, "model_id", None)}

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        converted = [convert_to_openai_tool(tool) for tool in tools]
        return self.bind(tools=converted, tool_choice=tool_choice, **kwargs)

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        response = self._client.invoke(
            to_openai_messages(messages),
            purpose=kwargs.get("purpose") or self._purpose or "answer",
            require_json=False,
            tools=kwargs.get("tools"),
            tool_choice=kwargs.get("tool_choice"),
            request_timeout=kwargs.get("request_timeout"),
        )
        return ChatResult(generations=[ChatGeneration(message=response_to_ai_message(response))])
