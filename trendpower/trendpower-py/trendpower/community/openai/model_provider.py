"""OpenAI ModelProvider implementation."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from openai import AsyncOpenAI

from ...foundation import (
    AssistantMessage,
    Message,
    ModelProviderInvokeParams,
    Tool,
)
from .stream_utils import StreamAccumulator
from .utils import convert_to_openai_messages, convert_to_openai_tools, parse_assistant_message


def _to_token_usage(usage: Any):
    if usage is None:
        return None

    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    return {
        "promptTokens": _get(usage, "prompt_tokens") or 0,
        "completionTokens": _get(usage, "completion_tokens") or 0,
        "totalTokens": _get(usage, "total_tokens") or 0,
    }


class OpenAIModelProvider:
    """A provider for the OpenAI API (or any OpenAI-compatible endpoint)."""

    def __init__(self, *, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        kwargs: Dict[str, Any] = {}
        if base_url is not None:
            kwargs["base_url"] = base_url
        if api_key is not None:
            kwargs["api_key"] = api_key
        self._client = AsyncOpenAI(**kwargs)

    async def invoke(self, params: ModelProviderInvokeParams) -> AssistantMessage:
        request_params = self._base_params(params)
        response = await self._client.chat.completions.create(**request_params)
        return parse_assistant_message(response.choices[0].message, _to_token_usage(response.usage))

    async def stream(self, params: ModelProviderInvokeParams) -> AsyncGenerator[AssistantMessage, None]:
        request_params = self._base_params(params)
        request_params["stream"] = True
        request_params["stream_options"] = {"include_usage": True}
        response = await self._client.chat.completions.create(**request_params)

        acc = StreamAccumulator()
        async for chunk in response:
            acc.push(chunk)
            yield acc.snapshot()

    def _base_params(self, params: ModelProviderInvokeParams) -> Dict[str, Any]:
        messages: List[Message] = params["messages"]
        tools: Optional[List[Tool]] = params.get("tools")
        options: Dict[str, Any] = dict(params.get("options") or {})
        base: Dict[str, Any] = {
            "model": params["model"],
            "messages": convert_to_openai_messages(messages),
            "temperature": 0,
        }
        if tools:
            base["tools"] = convert_to_openai_tools(tools)
        base.update(options)
        return base
