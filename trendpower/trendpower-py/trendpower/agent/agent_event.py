"""Agent event types — fired by the ReAct loop during streaming."""

from __future__ import annotations

from typing import Any, Literal, TypedDict, Union

from ..foundation import AssistantMessage, ToolMessage


class AgentMessageEvent(TypedDict):
    type: Literal["message"]
    message: Union[AssistantMessage, ToolMessage]


class AgentProgressThinkingEvent(TypedDict):
    type: Literal["progress"]
    subtype: Literal["thinking"]


class AgentProgressToolEvent(TypedDict):
    type: Literal["progress"]
    subtype: Literal["tool"]
    name: str
    input: Any


AgentProgressEvent = Union[AgentProgressThinkingEvent, AgentProgressToolEvent]
AgentEvent = Union[AgentMessageEvent, AgentProgressEvent]
