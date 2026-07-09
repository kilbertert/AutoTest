"""Model, ModelProvider, ModelContext — provider-facing contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol, TypedDict

from .abort_signal import AbortSignal
from .messages import AssistantMessage, Message, NonSystemMessage
from .tools import Tool


class ModelContext(TypedDict, total=False):
    prompt: str  # required
    messages: List[NonSystemMessage]  # required
    tools: Optional[List[Tool]]
    signal: Optional[AbortSignal]


class ModelProviderInvokeParams(TypedDict, total=False):
    model: str
    messages: List[Message]
    tools: Optional[List[Tool]]
    options: Optional[Dict[str, Any]]
    signal: Optional[AbortSignal]


class ModelProvider(Protocol):
    """A provider that knows how to invoke a model."""

    async def invoke(self, params: ModelProviderInvokeParams) -> AssistantMessage: ...

    def stream(self, params: ModelProviderInvokeParams) -> AsyncGenerator[AssistantMessage, None]: ...


@dataclass
class Model:
    """Represents a model that can be invoked through a provider."""

    name: str
    provider: ModelProvider
    options: Optional[Dict[str, Any]] = None

    async def invoke(self, context: ModelContext) -> AssistantMessage:
        params = self._build_provider_params(context)
        return await self.provider.invoke(params)

    def stream(self, context: ModelContext) -> AsyncGenerator[AssistantMessage, None]:
        params = self._build_provider_params(context)
        return self.provider.stream(params)

    def _build_provider_params(self, context: ModelContext) -> ModelProviderInvokeParams:
        messages: List[Message] = []
        prompt = context.get("prompt") or ""
        if prompt:
            messages.append({"role": "system", "content": [{"type": "text", "text": prompt}]})
        messages.extend(context.get("messages") or [])
        return {
            "model": self.name,
            "options": self.options,
            "messages": messages,
            "tools": context.get("tools"),
            "signal": context.get("signal"),
        }
