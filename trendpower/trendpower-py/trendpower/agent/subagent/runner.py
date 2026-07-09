"""Drive an isolated inner ``Agent`` to completion and return its final text.

This is the generic primitive behind delegated sub-agents: a parent agent hands
a focused task to a fresh ``Agent`` instance with its own transcript, lets it run
its ReAct loop to a final (tool-call-free) answer, and gets back only that answer
plus light telemetry. The inner transcript — all the search/read noise — is
discarded, which is the whole point: it never pollutes the parent's context.

Lives in the ``agent`` layer because it is task-agnostic; the concrete toolset,
prompt, and model are the caller's concern (see ``coding/tools/task.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

from ...foundation import AbortSignal, AssistantMessage, UserMessage

if TYPE_CHECKING:  # avoid an import cycle at runtime (Agent imports this package)
    from ..agent import Agent


@dataclass
class SubagentResult:
    """Outcome of a completed sub-agent run."""

    text: str  # the sub-agent's final answer (its last tool-call-free message)
    steps: int  # how many ReAct steps it took
    prompt_tokens: int  # promptTokens of the final model response (0 if unknown)


def _final_text(message: AssistantMessage) -> str:
    parts = [
        block.get("text", "")
        for block in message.get("content", []) or []
        if block.get("type") == "text"
    ]
    return "\n".join(p for p in parts if p).strip()


async def run_subagent(
    inner: "Agent",
    prompt: str,
    *,
    signal: Optional[AbortSignal] = None,
) -> SubagentResult:
    """Run ``inner`` on ``prompt`` to completion and return its final answer.

    Cancellation is forwarded: when ``signal`` aborts, the inner agent's own
    loop is aborted too (so its in-flight model/tool calls unwind). An
    ``AbortError`` from the inner loop propagates to the caller unchanged.
    """
    remove_listener = None
    if signal is not None:
        # Forward parent cancellation into the inner agent's controller.
        remove_listener = signal.add_listener(inner.abort)

    user_message: UserMessage = {"role": "user", "content": [{"type": "text", "text": prompt}]}

    last_assistant: Optional[AssistantMessage] = None
    steps = 0
    try:
        async for event in inner.stream(user_message):
            if event["type"] == "message" and event["message"].get("role") == "assistant":
                last_assistant = event["message"]  # type: ignore[assignment]
                steps += 1
    finally:
        if remove_listener is not None:
            remove_listener()

    if last_assistant is None:
        return SubagentResult(text="(sub-agent produced no output)", steps=steps, prompt_tokens=0)

    usage = last_assistant.get("usage") or {}
    return SubagentResult(
        text=_final_text(last_assistant) or "(sub-agent finished without a textual answer)",
        steps=steps,
        prompt_tokens=int(usage.get("promptTokens", 0) or 0),
    )
