"""Anthropic ModelProvider implementation."""

from __future__ import annotations

import math
from typing import Any, AsyncGenerator, Dict, Optional

from anthropic import AsyncAnthropic

from ...foundation import AssistantMessage, ModelProviderInvokeParams, TokenUsage
from .stream_utils import StreamAccumulator
from .utils import (
    convert_to_anthropic_messages,
    convert_to_anthropic_tools,
    extract_system_prompt,
    parse_assistant_message,
)


_EPHEMERAL = {"type": "ephemeral"}


def _to_token_usage(usage: Any) -> Optional[TokenUsage]:
    if usage is None:
        return None

    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    # With prompt caching, `input_tokens` counts only the *uncached* tokens;
    # the cached portion is reported separately. Fold both back into
    # `promptTokens` so it keeps meaning "size of the prompt we sent" — which
    # is what the compaction middleware relies on to decide when to compact.
    input_tokens = _get(usage, "input_tokens") or 0
    cache_read = _get(usage, "cache_read_input_tokens") or 0
    cache_creation = _get(usage, "cache_creation_input_tokens") or 0
    prompt_tokens = input_tokens + cache_read + cache_creation
    output_tokens = _get(usage, "output_tokens") or 0
    return {
        "promptTokens": prompt_tokens,
        "completionTokens": output_tokens,
        "totalTokens": prompt_tokens + output_tokens,
    }


class AnthropicModelProvider:
    """A provider for the Anthropic API (Claude models)."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        enable_prompt_caching: bool = True,
    ) -> None:
        is_default_url = (not base_url) or base_url == "https://api.anthropic.com"
        kwargs: Dict[str, Any] = {}
        if api_key is not None:
            kwargs["api_key"] = api_key
        if not is_default_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)
        self._prompt_caching = enable_prompt_caching

    async def invoke(self, params: ModelProviderInvokeParams) -> AssistantMessage:
        request = self._base_params(params)
        response = await self._client.messages.create(**request)
        return parse_assistant_message(response, _to_token_usage(response.usage))

    async def stream(self, params: ModelProviderInvokeParams) -> AsyncGenerator[AssistantMessage, None]:
        request = self._base_params(params)
        request["stream"] = True
        response = await self._client.messages.create(**request)

        acc = StreamAccumulator()
        async for event in response:
            acc.push(event)
            yield acc.snapshot()

    def _base_params(self, params: ModelProviderInvokeParams) -> Dict[str, Any]:
        messages = params["messages"]
        tools = params.get("tools")
        options: Dict[str, Any] = dict(params.get("options") or {})

        system = extract_system_prompt(messages)
        anthropic_messages = convert_to_anthropic_messages(messages)
        anthropic_tools = convert_to_anthropic_tools(tools) if tools else None

        # When thinking is enabled, Anthropic requires `budget_tokens`.
        # Default to max_tokens * 0.8 if not provided.
        thinking = options.get("thinking")
        if isinstance(thinking, dict) and thinking.get("type") == "enabled" and not thinking.get("budget_tokens"):
            max_tokens = options.get("max_tokens", 8192)
            thinking["budget_tokens"] = math.floor(max_tokens * 0.8)
            options["thinking"] = thinking

        if self._prompt_caching:
            self._apply_cache_control(system, anthropic_tools, anthropic_messages)

        base: Dict[str, Any] = {
            "model": params["model"],
            "max_tokens": 8192,
            "messages": anthropic_messages,
        }
        if system:
            # When caching, hand `system` as a structured block so it can carry
            # `cache_control`; otherwise the plain string is fine.
            base["system"] = (
                [{"type": "text", "text": system, "cache_control": _EPHEMERAL}]
                if self._prompt_caching
                else system
            )
        if anthropic_tools:
            base["tools"] = anthropic_tools
        base.update(options)
        return base

    @staticmethod
    def _apply_cache_control(
        system: Optional[str],
        anthropic_tools: Optional[list],
        anthropic_messages: list,
    ) -> None:
        """Place ephemeral cache breakpoints on the stable request prefix.

        Anthropic caches the prefix up to and including each marked block, in
        request order ``tools → system → messages`` (max 4 breakpoints). We mark:

        1. the last tool — caches the whole (run-stable) tool schema array;
        2. the system block — done by the caller (see ``base["system"]``);
        3. the last block of the last message — extends the cached prefix to
           cover the growing transcript, so the next turn reads it from cache.
        """
        if anthropic_tools:
            anthropic_tools[-1]["cache_control"] = _EPHEMERAL

        if anthropic_messages:
            last_content = anthropic_messages[-1].get("content")
            if isinstance(last_content, list) and last_content and isinstance(last_content[-1], dict):
                last_content[-1]["cache_control"] = _EPHEMERAL
