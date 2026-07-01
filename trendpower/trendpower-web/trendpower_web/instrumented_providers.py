"""ModelProvider subclasses that broadcast the real SDK request payload.

The whole point of `trendpower-web`: capture `request_params` right before
`client.chat.completions.create(**request_params)` (OpenAI) or
`client.messages.create(**request)` (Anthropic) and emit it to the
broadcaster. That dict is the canonical "this is what the LLM gets fed."
"""

from __future__ import annotations

import time
import uuid
from typing import Any, AsyncGenerator, Dict

from trendpower.community.anthropic import AnthropicModelProvider
from trendpower.community.anthropic.stream_utils import StreamAccumulator as AnthropicAccumulator
from trendpower.community.anthropic.utils import (
    parse_assistant_message as anthropic_parse_assistant,
)
from trendpower.community.openai import OpenAIModelProvider
from trendpower.community.openai.stream_utils import StreamAccumulator as OpenAIAccumulator
from trendpower.community.openai.utils import (
    parse_assistant_message as openai_parse_assistant,
)
from trendpower.foundation import AssistantMessage, ModelProviderInvokeParams

from .broadcaster import EventBroadcaster


def _json_safe(value: Any) -> Any:
    """Best-effort conversion of a request kwargs dict to JSON-serializable form."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            pass
    return repr(value)


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def _openai_token_usage(usage: Any) -> Dict[str, int] | None:
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


def _anthropic_token_usage(usage: Any) -> Dict[str, int] | None:
    if usage is None:
        return None

    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    input_tokens = _get(usage, "input_tokens") or 0
    output_tokens = _get(usage, "output_tokens") or 0
    return {
        "promptTokens": input_tokens,
        "completionTokens": output_tokens,
        "totalTokens": input_tokens + output_tokens,
    }


class OpenAIWithCapture(OpenAIModelProvider):
    def __init__(self, broadcaster: EventBroadcaster, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._broadcaster = broadcaster

    async def invoke(self, params: ModelProviderInvokeParams) -> AssistantMessage:
        request_params = self._base_params(params)
        req_id = _new_request_id()
        self._broadcaster.publish({
            "type": "llm_request",
            "provider": "openai",
            "mode": "invoke",
            "request_id": req_id,
            "payload": _json_safe(request_params),
            "ts": time.time(),
        })
        response = await self._client.chat.completions.create(**request_params)
        self._broadcaster.publish({
            "type": "llm_response",
            "provider": "openai",
            "request_id": req_id,
            "usage": _openai_token_usage(response.usage),
            "ts": time.time(),
        })
        return openai_parse_assistant(
            response.choices[0].message, _openai_token_usage(response.usage)
        )

    async def stream(
        self, params: ModelProviderInvokeParams
    ) -> AsyncGenerator[AssistantMessage, None]:
        request_params = self._base_params(params)
        request_params["stream"] = True
        request_params["stream_options"] = {"include_usage": True}
        req_id = _new_request_id()
        self._broadcaster.publish({
            "type": "llm_request",
            "provider": "openai",
            "mode": "stream",
            "request_id": req_id,
            "payload": _json_safe(request_params),
            "ts": time.time(),
        })
        response = await self._client.chat.completions.create(**request_params)
        acc = OpenAIAccumulator()
        async for chunk in response:
            acc.push(chunk)
            snapshot = acc.snapshot()
            self._broadcaster.publish({
                "type": "llm_response_chunk",
                "provider": "openai",
                "request_id": req_id,
                "snapshot": _json_safe(snapshot),
                "ts": time.time(),
            })
            yield snapshot


class AnthropicWithCapture(AnthropicModelProvider):
    def __init__(self, broadcaster: EventBroadcaster, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._broadcaster = broadcaster

    async def invoke(self, params: ModelProviderInvokeParams) -> AssistantMessage:
        request = self._base_params(params)
        req_id = _new_request_id()
        self._broadcaster.publish({
            "type": "llm_request",
            "provider": "anthropic",
            "mode": "invoke",
            "request_id": req_id,
            "payload": _json_safe(request),
            "ts": time.time(),
        })
        response = await self._client.messages.create(**request)
        self._broadcaster.publish({
            "type": "llm_response",
            "provider": "anthropic",
            "request_id": req_id,
            "usage": _anthropic_token_usage(response.usage),
            "ts": time.time(),
        })
        return anthropic_parse_assistant(response, _anthropic_token_usage(response.usage))

    async def stream(
        self, params: ModelProviderInvokeParams
    ) -> AsyncGenerator[AssistantMessage, None]:
        request = self._base_params(params)
        request["stream"] = True
        req_id = _new_request_id()
        self._broadcaster.publish({
            "type": "llm_request",
            "provider": "anthropic",
            "mode": "stream",
            "request_id": req_id,
            "payload": _json_safe(request),
            "ts": time.time(),
        })
        response = await self._client.messages.create(**request)
        acc = AnthropicAccumulator()
        async for event in response:
            acc.push(event)
            snapshot = acc.snapshot()
            self._broadcaster.publish({
                "type": "llm_response_chunk",
                "provider": "anthropic",
                "request_id": req_id,
                "snapshot": _json_safe(snapshot),
                "ts": time.time(),
            })
            yield snapshot
