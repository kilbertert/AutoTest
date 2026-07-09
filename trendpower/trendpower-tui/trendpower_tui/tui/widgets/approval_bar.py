"""Inline approval bar — sits in the input slot, not a modal.

The earlier `ApprovalScreen` (ModalScreen overlay) felt visually disconnected
from the conversation flow. This widget is rendered in place of the input box
when the agent asks for approval, the same way the TS Ink frontend handles it.
"""

from __future__ import annotations

import json
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static


WARN_COLOR = "#f3c969"
ACCEPT_COLOR = "#7cd992"
DENY_COLOR = "#ff8b8b"
DIM_COLOR = "#8fa0ad"


class ApprovalDecided(Message):
    def __init__(self, decision: str) -> None:
        self.decision = decision
        super().__init__()


class ApprovalBar(Vertical):
    """Approval prompt as an inline bottom-bar widget."""

    can_focus = True

    BINDINGS = [
        Binding("up", "move(-1)", "up", show=False),
        Binding("down", "move(1)", "down", show=False),
        Binding("enter", "confirm", "confirm"),
        Binding("y", "decide('allow_once')", "yes once", show=False),
        Binding("a", "decide('allow_always_project')", "always", show=False),
        Binding("n", "decide('deny')", "no", show=False),
        Binding("escape", "decide('deny')", "deny", show=False),
        Binding("1", "decide('allow_once')", "1", show=False),
        Binding("2", "decide('allow_always_project')", "2", show=False),
        Binding("3", "decide('deny')", "3", show=False),
    ]

    DEFAULT_CSS = """
    ApprovalBar {
        display: none;
        height: auto;
        padding: 0 2;
        margin: 0;
        border: round #f3c969;
        background: #1c1812;
        color: #f4ecd6;
    }
    ApprovalBar.-active { display: block; }
    ApprovalBar:focus-within { border: round #ffd17a; }
    """

    OPTIONS = [
        ("allow_once",         "y", "Yes — this time only",                ACCEPT_COLOR),
        ("allow_always_project","a", "Yes, always allow in this project",  ACCEPT_COLOR),
        ("deny",               "n", "No",                                  DENY_COLOR),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.tool_use: dict[str, Any] | None = None
        self.index = 0

    def compose(self) -> ComposeResult:
        yield Static("", id="approval-title", markup=True)
        yield Static("", id="approval-args", markup=True)
        yield Static("", id="approval-options", markup=True)

    def show_for(self, tool_use: dict[str, Any]) -> None:
        self.tool_use = tool_use
        self.index = 0
        self.add_class("-active")
        self._refresh()
        self.focus()

    def hide(self) -> None:
        self.tool_use = None
        self.remove_class("-active")

    def _refresh(self) -> None:
        tu = self.tool_use or {}
        name = str(tu.get("name", "tool"))
        self.query_one("#approval-title", Static).update(
            f"[bold {WARN_COLOR}]⚠ Agent wants to run:[/bold {WARN_COLOR}]  "
            f"[bold white]{_escape(name)}[/bold white]"
        )

        args = tu.get("input")
        try:
            args_text = json.dumps(args, indent=2, ensure_ascii=False)
        except TypeError:
            args_text = str(args)
        if len(args_text) > 400:
            args_text = args_text[:400] + "\n… (truncated)"
        self.query_one("#approval-args", Static).update(f"[dim]{_escape(args_text)}[/dim]")

        option_lines: list[str] = []
        for i, (_decision, shortcut, label, color) in enumerate(self.OPTIONS):
            marker = "❯" if i == self.index else " "
            highlight = f"bold {color}" if i == self.index else color
            option_lines.append(
                f"  {marker}  [{color}][{shortcut}][/{color}]  [{highlight}]{label}[/{highlight}]"
            )
        option_lines.append("")
        option_lines.append(
            f"  [{DIM_COLOR}]↑/↓ select  ·  Enter confirm  ·  y / a / n shortcuts  ·  Esc denies[/{DIM_COLOR}]"
        )
        self.query_one("#approval-options", Static).update("\n".join(option_lines))

    def action_move(self, delta: int) -> None:
        if not self.has_class("-active"):
            return
        self.index = (self.index + delta) % len(self.OPTIONS)
        self._refresh()

    def action_confirm(self) -> None:
        if not self.has_class("-active"):
            return
        decision = self.OPTIONS[self.index][0]
        self.post_message(ApprovalDecided(decision))

    def action_decide(self, decision: str) -> None:
        if not self.has_class("-active"):
            return
        self.post_message(ApprovalDecided(decision))


def _escape(text: str) -> str:
    return text.replace("[", r"\[")
