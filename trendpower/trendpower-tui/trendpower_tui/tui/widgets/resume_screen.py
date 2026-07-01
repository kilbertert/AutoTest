"""Modal screen for `/resume` — pick a saved conversation to reload."""

from __future__ import annotations

import time
from dataclasses import dataclass

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from ...sessions import SessionMeta


@dataclass(frozen=True)
class ResumeAction:
    """Result handed back to the App on dismiss.

    ``kind`` is one of ``"resume"`` (load ``payload`` session id),
    ``"delete"`` (remove ``payload`` session id) or ``"none"`` (Esc).
    """

    kind: str
    payload: str | None = None


class ResumeScreen(ModalScreen[ResumeAction]):
    BINDINGS = [
        ("up", "move(-1)", "Up"),
        ("down", "move(1)", "Down"),
        ("enter", "resume", "Resume"),
        ("d", "delete", "Delete"),
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ResumeScreen {
        align: center middle;
    }
    ResumeScreen #resume-box {
        width: 80%;
        max-width: 110;
        max-height: 80%;
        padding: 1 2;
        border: round #6fd6ff;
        background: #121822;
        color: #f4fbff;
    }
    ResumeScreen #resume-body {
        height: auto;
        overflow-y: auto;
    }
    ResumeScreen .hint {
        color: #8fa0ad;
        margin-top: 1;
    }
    """

    def __init__(self, sessions: list[SessionMeta]) -> None:
        super().__init__()
        self.sessions = sessions
        self.index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="resume-box"):
            yield Static("[bold cyan]Trendpower · /resume[/bold cyan]", id="resume-title")
            yield Static(self._body(), id="resume-body")
            yield Static(self._hint(), id="resume-hint", classes="hint")

    def _refresh(self) -> None:
        self.query_one("#resume-body", Static).update(self._body())

    def _body(self) -> str:
        if not self.sessions:
            return "[dim]还没有任何已保存的对话。先聊几句，会自动保存。[/dim]"
        lines: list[str] = ["[bold]选择要恢复的对话：[/bold]", ""]
        for i, meta in enumerate(self.sessions):
            focused = i == self.index
            marker = "❯ " if focused else "  "
            color = "cyan" if focused else "white"
            when = _relative_time(meta.updated)
            detail = f"{meta.message_count} msgs · {when}"
            if meta.model:
                detail += f" · {meta.model}"
            lines.append(
                f"[{color}]{marker}{_escape(meta.title)}[/{color}]\n"
                f"     [dim]{_escape(detail)}[/dim]"
            )
        return "\n".join(lines)

    def _hint(self) -> str:
        return "↑/↓ 选择 · Enter 恢复 · d 删除 · Esc 关闭"

    def action_move(self, delta: int) -> None:
        if not self.sessions:
            return
        self.index = (self.index + delta) % len(self.sessions)
        self._refresh()

    def action_resume(self) -> None:
        if not self.sessions:
            self.dismiss(ResumeAction(kind="none"))
            return
        self.dismiss(ResumeAction(kind="resume", payload=self.sessions[self.index].id))

    def action_delete(self) -> None:
        if not self.sessions:
            return
        self.dismiss(ResumeAction(kind="delete", payload=self.sessions[self.index].id))

    def action_cancel(self) -> None:
        self.dismiss(ResumeAction(kind="none"))

    def on_key(self, event: events.Key) -> None:
        # Swallow stray characters so they do not leak into the InputBox once we
        # close. Named bindings above cover the real actions.
        pass


def _escape(text: str) -> str:
    return text.replace("[", r"\[")


def _relative_time(timestamp: float) -> str:
    if not timestamp:
        return "unknown"
    delta = max(0, int(time.time() - timestamp))
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    if delta < 7 * 86400:
        return f"{delta // 86400}d ago"
    return time.strftime("%Y-%m-%d", time.localtime(timestamp))
