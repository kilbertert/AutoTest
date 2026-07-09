"""The ReAct-style agent loop. Faithful port of `src/agent/agent.ts`."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional, TypedDict

from ..foundation import (
    AbortController,
    AssistantMessage,
    Model,
    ModelContext,
    NonSystemMessage,
    Tool,
    ToolMessage,
    ToolUseContent,
    UserMessage,
)
from .agent_event import AgentEvent
from .agent_middleware import AgentMiddleware
from .tool_result import format_tool_result_for_message


_STEP_LIMIT_PROMPT = (
    "You have reached the maximum number of steps for this task and cannot call "
    "any more tools. Stop now and give your final response: summarize what you "
    "accomplished, what remains unfinished, and the concrete next steps to "
    "continue. Base it only on what you already know."
)


class AgentContext(TypedDict, total=False):
    """Mutable context shared across the agent run + all middlewares."""

    prompt: str  # required
    messages: List[NonSystemMessage]  # required
    tools: Optional[List[Tool]]
    skills: Optional[List[Dict[str, Any]]]
    requestedSkillName: Optional[str]


@dataclass
class AgentOptions:
    maxSteps: int = 100


class Agent:
    """An agent loop using the ReAct pattern."""

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        model: Model,
        prompt: str,
        messages: Optional[List[NonSystemMessage]] = None,
        tools: Optional[List[Tool]] = None,
        middlewares: Optional[List[AgentMiddleware]] = None,
        maxSteps: int = 100,
    ) -> None:
        self.name = name
        self.model = model
        self._context: AgentContext = {
            "prompt": prompt,
            "messages": list(messages) if messages else [],
            "tools": tools,
        }
        self.middlewares: List[AgentMiddleware] = list(middlewares) if middlewares else []
        self.options = AgentOptions(maxSteps=maxSteps)
        self._streaming = False
        self._abort_controller: Optional[AbortController] = None

    # --- properties ---------------------------------------------------------

    @property
    def messages(self) -> List[NonSystemMessage]:
        return self._context["messages"]

    @property
    def prompt(self) -> str:
        return self._context.get("prompt", "")

    @prompt.setter
    def prompt(self, value: str) -> None:
        self._context["prompt"] = value

    @property
    def tools(self) -> Optional[List[Tool]]:
        return self._context.get("tools")

    @property
    def streaming(self) -> bool:
        return self._streaming

    def set_requested_skill_name(self, requested_skill_name: Optional[str]) -> None:
        self._context["requestedSkillName"] = requested_skill_name

    def clear_messages(self) -> None:
        self._context["messages"].clear()

    def load_messages(self, messages: List[NonSystemMessage]) -> None:
        """Replace the transcript wholesale (e.g. when resuming a session)."""
        self._context["messages"][:] = list(messages)

    def abort(self) -> None:
        if self._abort_controller is not None:
            self._abort_controller.abort()

    # --- main loop ----------------------------------------------------------

    async def stream(self, message: UserMessage) -> AsyncGenerator[AgentEvent, None]:
        if self._streaming:
            raise RuntimeError("Agent is already streaming")

        self._abort_controller = AbortController()
        self._append_message(message)
        await self._before_agent_run()
        self._streaming = True
        try:
            for step in range(1, self.options.maxSteps + 1):
                self._abort_controller.signal.throw_if_aborted()
                await self._before_agent_step(step)
                assistant_message = yield_value = None
                async for ev in self._think():
                    if ev["type"] == "_think_done":
                        assistant_message = ev["message"]
                        break
                    else:
                        yield ev  # type: ignore[misc]
                assert assistant_message is not None

                await self._after_model(assistant_message)
                yield {"type": "message", "message": assistant_message}

                tool_uses = self._extract_tool_uses(assistant_message)
                if not tool_uses:
                    await self._after_agent_run()
                    return

                async for ev in self._act(tool_uses):
                    yield ev
                await self._after_agent_step(step)
            # Step budget exhausted. Rather than crash and discard the work done
            # so far, ask the model for a final wrap-up (with tools disabled so
            # it cannot keep going) and return that as the answer.
            async for ev in self._emit_step_limit_summary():
                yield ev
            return
        finally:
            self._streaming = False
            self._abort_controller = None

    async def _emit_step_limit_summary(self) -> AsyncGenerator[AgentEvent, None]:
        """Soft-landing when ``maxSteps`` is reached: one final text-only turn.

        Injects a nudge telling the model to stop calling tools and summarize
        progress, then runs a single ``_think`` with the toolset forced to
        ``None`` so the response cannot contain further tool calls.
        """
        self._append_message(
            {
                "role": "user",
                "content": [{"type": "text", "text": _STEP_LIMIT_PROMPT}],
            }
        )
        saved_tools = self._context.get("tools")
        self._context["tools"] = None  # force a text-only final response
        try:
            assistant_message: Optional[AssistantMessage] = None
            async for ev in self._think():
                if ev["type"] == "_think_done":
                    assistant_message = ev["message"]
                    break
                else:
                    yield ev  # type: ignore[misc]
        finally:
            self._context["tools"] = saved_tools

        if assistant_message is not None:
            await self._after_model(assistant_message)
            yield {"type": "message", "message": assistant_message}
        await self._after_agent_run()

    # _think yields AgentEvent items for progress, and finally a sentinel
    # {"type": "_think_done", "message": AssistantMessage} so the caller can
    # extract the final assistant message. This emulates the TS pattern of
    # `yield*` + final `return value`.
    async def _think(self) -> AsyncGenerator[Dict[str, Any], None]:
        assert self._abort_controller is not None
        model_context: ModelContext = {
            "prompt": self.prompt,
            "messages": self.messages,
            "tools": self.tools,
            "signal": self._abort_controller.signal,
        }
        await self._before_model(model_context)

        latest: Optional[AssistantMessage] = None
        async for snapshot in self.model.stream(model_context):
            latest = snapshot
            if snapshot.get("streaming"):
                yield self._derive_progress(snapshot)
        if latest is None:
            raise RuntimeError("Model stream ended without producing a message")
        # Defensive: ensure the final message is not flagged as streaming.
        if latest.get("streaming"):
            latest.pop("streaming", None)
        self._append_message(latest)
        yield {"type": "_think_done", "message": latest}

    def _derive_progress(self, snapshot: AssistantMessage) -> AgentEvent:
        tool_uses = [c for c in snapshot.get("content", []) if c.get("type") == "tool_use"]
        if not tool_uses:
            return {"type": "progress", "subtype": "thinking"}
        last = tool_uses[-1]
        return {"type": "progress", "subtype": "tool", "name": last["name"], "input": last["input"]}

    def _extract_tool_uses(self, message: AssistantMessage) -> List[ToolUseContent]:
        return [c for c in message.get("content", []) if c.get("type") == "tool_use"]  # type: ignore[misc]

    async def _act(self, tool_uses: List[ToolUseContent]) -> AsyncGenerator[AgentEvent, None]:
        assert self._abort_controller is not None
        signal = self._abort_controller.signal

        async def run_one(index: int, tool_use: ToolUseContent) -> Dict[str, Any]:
            try:
                tool = None
                for t in self.tools or []:
                    if t.name == tool_use["name"]:
                        tool = t
                        break
                if tool is None:
                    raise RuntimeError(f"Tool {tool_use['name']} not found")
                before_result = await self._before_tool_use(tool_use)
                if before_result["skip"]:
                    return {
                        "index": index,
                        "toolUseId": tool_use["id"],
                        "toolName": tool_use["name"],
                        "result": before_result["result"],
                    }
                result = await tool.invoke(tool_use["input"], signal)
                await self._after_tool_use(tool_use, result)
                return {
                    "index": index,
                    "toolUseId": tool_use["id"],
                    "toolName": tool_use["name"],
                    "result": result,
                }
            except Exception as error:
                msg = str(error)
                return {
                    "index": index,
                    "toolUseId": tool_use["id"],
                    "toolName": tool_use["name"],
                    "result": f"Error: {msg}",
                }

        tasks: List[asyncio.Task[Dict[str, Any]]] = [
            asyncio.create_task(run_one(i, tu)) for i, tu in enumerate(tool_uses)
        ]

        # Race against abort signal so we surface cancellation quickly.
        abort_task: Optional[asyncio.Task[None]] = None
        if signal is not None:
            abort_task = asyncio.create_task(signal.wait())

        pending = set(tasks)
        try:
            while pending:
                wait_set: set = set(pending)
                if abort_task is not None:
                    wait_set.add(abort_task)
                done, _ = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)
                if abort_task is not None and abort_task in done:
                    signal.throw_if_aborted()  # raises AbortError
                # Drain any completed tool tasks (preserving completion order).
                for d in done:
                    if d is abort_task:
                        continue
                    pending.discard(d)
                    resolved = d.result()
                    tool_message: ToolMessage = {
                        "role": "tool",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": resolved["toolUseId"],
                                "content": format_tool_result_for_message(
                                    resolved["toolName"], resolved["result"]
                                ),
                            }
                        ],
                    }
                    self._append_message(tool_message)
                    yield {"type": "message", "message": tool_message}
        finally:
            if abort_task is not None and not abort_task.done():
                abort_task.cancel()

    def _append_message(self, message: NonSystemMessage) -> None:
        self._context["messages"].append(message)

    # --- middleware dispatch -----------------------------------------------

    async def _before_model(self, model_context: ModelContext) -> None:
        for mw in self.middlewares:
            hook = getattr(mw, "beforeModel", None)
            if hook is None:
                continue
            result = await hook({"modelContext": model_context, "agentContext": self._context})
            if result:
                model_context.update(result)  # type: ignore[typeddict-item]

    async def _after_model(self, message: AssistantMessage) -> None:
        for mw in self.middlewares:
            hook = getattr(mw, "afterModel", None)
            if hook is None:
                continue
            result = await hook({"agentContext": self._context, "message": message})
            if result:
                message.update(result)  # type: ignore[typeddict-item]

    async def _before_agent_run(self) -> None:
        for mw in self.middlewares:
            hook = getattr(mw, "beforeAgentRun", None)
            if hook is None:
                continue
            result = await hook({"agentContext": self._context})
            if result:
                self._context.update(result)  # type: ignore[typeddict-item]

    async def _after_agent_run(self) -> None:
        for mw in self.middlewares:
            hook = getattr(mw, "afterAgentRun", None)
            if hook is None:
                continue
            result = await hook({"agentContext": self._context})
            if result:
                self._context.update(result)  # type: ignore[typeddict-item]

    async def _before_agent_step(self, step: int) -> None:
        for mw in self.middlewares:
            hook = getattr(mw, "beforeAgentStep", None)
            if hook is None:
                continue
            result = await hook({"agentContext": self._context, "step": step})
            if result:
                self._context.update(result)  # type: ignore[typeddict-item]

    async def _after_agent_step(self, step: int) -> None:
        for mw in self.middlewares:
            hook = getattr(mw, "afterAgentStep", None)
            if hook is None:
                continue
            result = await hook({"agentContext": self._context, "step": step})
            if result:
                self._context.update(result)  # type: ignore[typeddict-item]

    async def _before_tool_use(self, tool_use: ToolUseContent) -> Dict[str, Any]:
        for mw in self.middlewares:
            hook = getattr(mw, "beforeToolUse", None)
            if hook is None:
                continue
            result = await hook({"agentContext": self._context, "toolUse": tool_use})
            if isinstance(result, dict) and result.get("__skip"):
                return {"skip": True, "result": result.get("result")}
            if result:
                self._context.update(result)  # type: ignore[typeddict-item]
        return {"skip": False}

    async def _after_tool_use(self, tool_use: ToolUseContent, tool_result: Any) -> None:
        for mw in self.middlewares:
            hook = getattr(mw, "afterToolUse", None)
            if hook is None:
                continue
            result = await hook(
                {"agentContext": self._context, "toolUse": tool_use, "toolResult": tool_result}
            )
            if result:
                self._context.update(result)  # type: ignore[typeddict-item]
