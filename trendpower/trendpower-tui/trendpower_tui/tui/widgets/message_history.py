"""Append-only transcript rendering.

Design notes
------------
- No `YOU` / `trendpower` section headers — each role gets a one-glyph prefix:
    user      ▎ pink
    assistant ◆ cyan  (then markdown, no prefix on continuation lines)
    tool call ⏺ lavender, single line + dim detail
    tool result ↳ dim, single-line summary
- Spacing: one blank line after each user turn and after each assistant turn,
  but tool-use + tool-result are visually fused (no blank line between them).
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog

from trendpower.agent.tool_result import summarize_tool_result_text
from ..todo_view import TodoItemView, get_current_todo, get_next_todo, snapshot_key


USER_BAR = "▎"
ASSISTANT_BAR = "◆"
TOOL_GLYPH = "⏺"
RESULT_GLYPH = "↳"

USER_COLOR = "#ff7eb6"
ASSISTANT_COLOR = "#6fd6ff"
TOOL_COLOR = "#c8a8ff"
DIM_COLOR = "#8fa0ad"
SUCCESS_COLOR = "#7cd992"
DANGER_COLOR = "#ff8b8b"


class MessageHistory(RichLog):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, markup=True, wrap=True, highlight=True, **kwargs)

    def append_message(
        self,
        message: dict[str, Any],
        *,
        message_index: int | None = None,
        todo_snapshots: dict[str, list[TodoItemView]] | None = None,
    ) -> None:
        role = message.get("role", "assistant")
        content = message.get("content") or []
        if not isinstance(content, list):
            self.write(Text(str(content)))
            return

        had_text = False
        had_tool = False
        for content_index, part in enumerate(content):
            if not isinstance(part, dict):
                self.write(Text(str(part)))
                continue
            part_type = part.get("type")
            if part_type == "text":
                self._write_text(role, str(part.get("text") or ""))
                had_text = True
            elif part_type == "tool_use":
                key = snapshot_key(message_index, content_index) if message_index is not None else ""
                todos = todo_snapshots.get(key) if todo_snapshots else None
                self._write_tool_use(part, todos)
                had_tool = True
            elif part_type == "tool_result":
                self._write_tool_result(part)
                had_tool = True
            elif part_type == "thinking":
                thinking = str(part.get("thinking") or "").strip()
                if thinking:
                    snippet = thinking if len(thinking) <= 240 else thinking[:237] + "…"
                    self.write(Text(f"  thinking · {snippet}", style=f"italic {DIM_COLOR}"))

        # Trailing spacing — one blank line per logical turn, not per content
        # part. Tool messages are intentionally tight to their sibling result.
        if had_text or (role == "tool" and not had_tool):
            self.write(Text(""))

    # --- text ----------------------------------------------------------------

    def _write_text(self, role: str, text: str) -> None:
        text = text.rstrip()
        if not text:
            return
        if role == "user":
            self.write(self._user_text(text))
            return
        if role == "assistant":
            self.write(self._assistant_text(text))
            return
        # System / other roles render plain
        self.write(Text(text, style=DIM_COLOR))

    def _user_text(self, text: str) -> Text:
        # Label on its own line so it never drifts past the prompt; content
        # lines share the same color bar so the label and message read as one
        # block.
        lines = text.split("\n")
        parts = [
            Text.from_markup(f"[{USER_COLOR}]{USER_BAR}[/{USER_COLOR}]  [dim]you[/dim]"),
        ]
        for line in lines:
            parts.append(
                Text.from_markup(
                    f"[{USER_COLOR}]{USER_BAR}[/{USER_COLOR}]  {_escape(line) if line else ''}"
                )
            )
        return Text("\n").join(parts)

    def _assistant_text(self, text: str) -> Group:
        header = Text.from_markup(
            f"[{ASSISTANT_COLOR}]{ASSISTANT_BAR}[/{ASSISTANT_COLOR}]  [dim]trendpower[/dim]"
        )
        body = Markdown(text)
        return Group(header, body)

    # --- tool use ------------------------------------------------------------

    def _write_tool_use(self, part: dict[str, Any], todos: list[TodoItemView] | None) -> None:
        name = str(part.get("name") or "tool")
        input_data = part.get("input") if isinstance(part.get("input"), dict) else {}
        description = str(input_data.get("description") or "").strip()

        if name == "bash":
            detail = str(input_data.get("command") or "")
        elif name in {"str_replace", "read_file", "write_file", "list_files", "file_info", "mkdir"}:
            detail = str(input_data.get("path") or "")
        elif name in {"glob_search", "grep_search"}:
            detail = f"{input_data.get('path') or '.'} :: {input_data.get('pattern') or ''}"
        elif name == "move_path":
            detail = f"{input_data.get('from') or ''} → {input_data.get('to') or ''}"
        elif name == "apply_patch":
            detail = "unified diff patch"
        elif name == "ask_user_question":
            questions = input_data.get("questions")
            count = len(questions) if isinstance(questions, list) else 0
            first = (
                questions[0].get("header") if count and isinstance(questions[0], dict) else None
            )
            description = description or (f"Ask user · {count} question(s)" if count else "Ask user")
            detail = str(first or "")
        elif name == "todo_write":
            current = get_current_todo(todos)
            next_todo = get_next_todo(todos)
            summary = current or next_todo
            completed = sum(1 for todo in todos or [] if todo.status == "completed")
            pending = sum(1 for todo in todos or [] if todo.status == "pending")
            description = description or (
                f"Working on · {summary.content}" if summary else "Todo list complete"
            )
            detail = (
                f"{completed} done"
                + (f" · {pending} pending" if pending else "")
            )
        else:
            detail = name

        header_parts = [
            f"[{TOOL_COLOR}]{TOOL_GLYPH}[/{TOOL_COLOR}]",
            f"[bold {TOOL_COLOR}]{_escape(name)}[/bold {TOOL_COLOR}]",
        ]
        if description:
            header_parts.append(f"[{DIM_COLOR}]·[/{DIM_COLOR}]  {_escape(description)}")
        self.write(Text.from_markup("  ".join(header_parts)))
        if detail:
            short_detail = detail if len(detail) <= 200 else detail[:197] + "…"
            self.write(
                Text.from_markup(f"    [dim]{_escape(short_detail)}[/dim]")
            )

    # --- tool result ---------------------------------------------------------

    def _write_tool_result(self, part: dict[str, Any]) -> None:
        raw = _tool_result_content(part)
        summary = summarize_tool_result_text(raw) or raw
        if not summary:
            return
        first_line = summary.splitlines()[0] if summary else ""
        if len(first_line) > 200:
            first_line = first_line[:197] + "…"
        is_error = first_line.lower().startswith("error")
        color = DANGER_COLOR if is_error else SUCCESS_COLOR
        self.write(
            Text.from_markup(
                f"    [{color}]{RESULT_GLYPH}[/{color}]  [dim]{_escape(first_line)}[/dim]"
            )
        )


def _escape(text: str) -> str:
    """Escape Rich markup metacharacters so user/model content renders verbatim."""

    return text.replace("[", r"\[")


def _tool_result_content(part: dict[str, Any]) -> str:
    content = part.get("content")
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content)
