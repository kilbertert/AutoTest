"""Bridge the async agent stream into Textual messages.

Mirrors the behavior of `src/cli/tui/hooks/use-agent-loop.ts`:

- Buffers transcript messages and flushes them in 50ms windows so the UI does
  not get redrawn for every snapshot the model produces.
- Drops the streaming flag and clears the requested skill when the run ends.
- Surfaces model/tool errors as assistant messages instead of crashing.
- Swallows AbortError (the agent loop raises it when the user hits Ctrl+C
  while a tool is still in flight).
"""

from __future__ import annotations

import time
from typing import Any

from textual.message import Message

try:
    from trendpower.foundation import AbortError
except Exception:  # pragma: no cover - foundation always ships AbortError
    AbortError = ()  # type: ignore[assignment]


FLUSH_INTERVAL_SECONDS = 0.05


class AgentMessageEvent(Message):
    """Posted when the agent emits a transcript message."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__()


class AgentProgressEvent(Message):
    """Posted for lightweight streaming/progress updates."""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class StreamingChanged(Message):
    """Posted when an agent run starts or stops."""

    def __init__(self, streaming: bool) -> None:
        self.streaming = streaming
        super().__init__()


class AgentRunner:
    """Own the core agent and translate its events for the UI."""

    def __init__(self, agent: Any, target: Any) -> None:
        self.agent = agent
        self.target = target

    async def submit(self, text: str, requested_skill: str | None = None) -> None:
        user_message = {"role": "user", "content": [{"type": "text", "text": text}]}
        self.target.post_message(AgentMessageEvent(user_message))
        self.agent.set_requested_skill_name(requested_skill)

        self.target.post_message(StreamingChanged(True))
        pending: list[dict[str, Any]] = []
        last_flush = time.monotonic()

        def flush() -> None:
            nonlocal last_flush
            if not pending:
                return
            for snapshot in pending:
                self.target.post_message(AgentMessageEvent(snapshot))
            pending.clear()
            last_flush = time.monotonic()

        try:
            async for event in self.agent.stream(user_message):
                event_type = event.get("type")
                if event_type == "message":
                    pending.append(event["message"])
                    if time.monotonic() - last_flush >= FLUSH_INTERVAL_SECONDS:
                        flush()
                elif event_type == "progress":
                    self.target.post_message(AgentProgressEvent(_progress_text(event)))
        except Exception as error:
            if AbortError and isinstance(error, AbortError):
                # User-requested abort; do not surface as an error message.
                pass
            else:
                flush()
                self.target.post_message(
                    AgentMessageEvent(
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Error: {error}\n\nYou can try again.",
                                }
                            ],
                        }
                    )
                )
        finally:
            flush()
            try:
                self.agent.set_requested_skill_name(None)
            except Exception:  # pragma: no cover - defensive
                pass
            self.target.post_message(StreamingChanged(False))

    def abort(self) -> None:
        try:
            self.agent.abort()
        except Exception:  # pragma: no cover - defensive
            pass


def _progress_text(event: dict[str, Any]) -> str:
    if event.get("subtype") == "tool":
        name = event.get("name") or "tool"
        return f"Running {name}..."
    return "Thinking..."
