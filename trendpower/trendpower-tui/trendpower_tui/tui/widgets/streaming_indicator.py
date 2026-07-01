"""Spinner + hint line between the transcript and the input."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

IDLE_HINT = "[dim]⏎ submit  ·  ↑/↓ history  ·  /help[/dim]"
RUN_HINT = "[dim]esc abort  ·  ^C exit[/dim]"


class StreamingIndicator(Horizontal):
    streaming: reactive[bool] = reactive(False)
    progress_text: reactive[str] = reactive("")

    _frame_index = 0

    def compose(self) -> ComposeResult:
        yield Static(self._left_text(), id="streaming-left")
        yield Static(IDLE_HINT, id="streaming-right")

    def on_mount(self) -> None:
        # 80ms gives the braille spinner ~12fps — fast enough to feel live but
        # not so fast that the terminal redraw flickers.
        self.set_interval(0.08, self._tick)
        self._refresh()

    def _tick(self) -> None:
        if not self.streaming:
            return
        self._frame_index = (self._frame_index + 1) % len(SPINNER_FRAMES)
        self.query_one("#streaming-left", Static).update(self._left_text())

    def watch_streaming(self, _streaming: bool) -> None:
        self._refresh()

    def watch_progress_text(self, _text: str) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            left = self.query_one("#streaming-left", Static)
            right = self.query_one("#streaming-right", Static)
        except Exception:
            return
        left.update(self._left_text())
        right.update(RUN_HINT if self.streaming else IDLE_HINT)

    def _left_text(self) -> str:
        if not self.streaming:
            return ""
        frame = SPINNER_FRAMES[self._frame_index]
        msg = self.progress_text or "thinking…"
        return f"[#f3c969]{frame}[/#f3c969]  [dim]{_escape(msg)}[/dim]"


def _escape(text: str) -> str:
    return text.replace("[", r"\[")
