"""Message and content TypedDicts — the conversation transcript types.

Mirrors `src/foundation/messages/types/*.ts`. Uses TypedDict so messages remain
plain dicts at runtime (matching the TS interface shape one-to-one).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, TypedDict, Union

Role = Literal["system", "user", "assistant", "tool"]


# --- content blocks ---------------------------------------------------------


class TextContent(TypedDict):
    type: Literal["text"]
    text: str


class _ImageURLData(TypedDict, total=False):
    url: str
    detail: Literal["auto", "high", "low"]


class ImageURLContent(TypedDict):
    type: Literal["image_url"]
    image_url: _ImageURLData


class ThinkingContent(TypedDict, total=False):
    type: Literal["thinking"]
    thinking: str
    # Optional, Anthropic-specific signature preserved across turns.
    _anthropicSignature: str


class ToolUseContent(TypedDict):
    type: Literal["tool_use"]
    id: str
    name: str
    input: Dict[str, Any]


class ToolResultContent(TypedDict):
    type: Literal["tool_result"]
    tool_use_id: str
    content: str


# Content unions per role
SystemMessageContent = List[TextContent]
UserMessageContent = List[Union[TextContent, ImageURLContent]]
AssistantMessageContent = List[Union[TextContent, ThinkingContent, ToolUseContent]]
ToolMessageContent = List[ToolResultContent]


# --- token usage ------------------------------------------------------------


class TokenUsage(TypedDict):
    promptTokens: int
    completionTokens: int
    totalTokens: int


# --- messages ---------------------------------------------------------------


class SystemMessage(TypedDict):
    role: Literal["system"]
    content: SystemMessageContent


class UserMessage(TypedDict):
    role: Literal["user"]
    content: UserMessageContent


class AssistantMessage(TypedDict, total=False):
    role: Literal["assistant"]  # required
    content: AssistantMessageContent  # required
    usage: TokenUsage
    streaming: bool


class ToolMessage(TypedDict):
    role: Literal["tool"]
    content: ToolMessageContent


NonSystemMessage = Union[UserMessage, AssistantMessage, ToolMessage]
Message = Union[SystemMessage, NonSystemMessage]
