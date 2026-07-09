"""Middleware hooks that observe / mutate an Agent's run.

Mirrors `src/agent/agent-middleware.ts`. Hooks are invoked **sequentially** in
middleware array order. Each hook receives the same context object used by the
agent loop. If a hook returns a truthy dict, it will be merged into the shared
context. Returning None means "no change".
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional, Protocol, TypedDict

from ..foundation import AssistantMessage, ModelContext, ToolUseContent

# Forward reference: AgentContext is defined in agent.py to avoid cycles at
# import time. At runtime it's a plain dict.
AgentContext = Dict[str, Any]


class BeforeModelParams(TypedDict):
    modelContext: ModelContext
    agentContext: AgentContext


class AfterModelParams(TypedDict):
    agentContext: AgentContext
    message: AssistantMessage


class BeforeAgentRunParams(TypedDict):
    agentContext: AgentContext


class AfterAgentRunParams(TypedDict):
    agentContext: AgentContext


class BeforeAgentStepParams(TypedDict):
    agentContext: AgentContext
    step: int


class AfterAgentStepParams(TypedDict):
    agentContext: AgentContext
    step: int


class BeforeToolUseParams(TypedDict):
    agentContext: AgentContext
    toolUse: ToolUseContent


class AfterToolUseParams(TypedDict):
    agentContext: AgentContext
    toolUse: ToolUseContent
    toolResult: Any


# A "skip" sentinel returned by beforeToolUse to bypass tool execution and
# substitute a result directly.
class _SkipResult(TypedDict):
    __skip: bool  # always True
    result: Any


BeforeToolUseResult = Optional[Any]  # Partial[AgentContext] | _SkipResult | None


HookFn = Callable[[Any], Awaitable[Optional[Dict[str, Any]]]]


class AgentMiddleware(Protocol):
    """Optional middleware hooks. All attributes are optional."""

    beforeModel: Optional[Callable[[BeforeModelParams], Awaitable[Optional[Dict[str, Any]]]]]
    afterModel: Optional[Callable[[AfterModelParams], Awaitable[Optional[Dict[str, Any]]]]]
    beforeAgentRun: Optional[Callable[[BeforeAgentRunParams], Awaitable[Optional[Dict[str, Any]]]]]
    afterAgentRun: Optional[Callable[[AfterAgentRunParams], Awaitable[Optional[Dict[str, Any]]]]]
    beforeAgentStep: Optional[Callable[[BeforeAgentStepParams], Awaitable[Optional[Dict[str, Any]]]]]
    afterAgentStep: Optional[Callable[[AfterAgentStepParams], Awaitable[Optional[Dict[str, Any]]]]]
    beforeToolUse: Optional[Callable[[BeforeToolUseParams], Awaitable[BeforeToolUseResult]]]
    afterToolUse: Optional[Callable[[AfterToolUseParams], Awaitable[Optional[Dict[str, Any]]]]]
