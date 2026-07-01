"""Todo panel for the latest todo_write snapshot."""

from __future__ import annotations

from textual.widgets import Static

from ..todo_view import TodoItemView


STATUS_ICON = {
    "completed": "✓",
    "in_progress": "◐",
    "cancelled": "✗",
    "pending": "○",
}

STATUS_COLOR = {
    "completed": "#7cd992",
    "in_progress": "#f3c969",
    "cancelled": "#8fa0ad",
    "pending": "#8fa0ad",
}


class TodoPanel(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__("", *args, markup=True, **kwargs)
        self.display = False

    def set_todos(self, todos: list[TodoItemView] | None) -> None:
        if not todos:
            self.display = False
            self.update("")
            return

        self.display = True
        completed = sum(1 for todo in todos if todo.status == "completed")
        pending = sum(1 for todo in todos if todo.status == "pending")
        in_progress = sum(1 for todo in todos if todo.status == "in_progress")
        cancelled = sum(1 for todo in todos if todo.status == "cancelled")

        header_segments = [f"[bold #c8a8ff]TODO[/bold #c8a8ff]"]
        if completed:
            header_segments.append(f"[#7cd992]{completed} done[/#7cd992]")
        if in_progress:
            header_segments.append(f"[#f3c969]{in_progress} active[/#f3c969]")
        if pending:
            header_segments.append(f"[#8fa0ad]{pending} pending[/#8fa0ad]")
        if cancelled:
            header_segments.append(f"[#8fa0ad]{cancelled} cancelled[/#8fa0ad]")
        lines = ["  ·  ".join(header_segments), ""]

        for todo in todos:
            icon = STATUS_ICON.get(todo.status, "·")
            color = STATUS_COLOR.get(todo.status, "#d9e1e8")
            content = _escape(todo.content)
            if todo.status == "in_progress":
                lines.append(f"  [{color}]{icon}[/{color}]  [bold]{content}[/bold]")
            elif todo.status == "completed":
                lines.append(f"  [{color}]{icon}[/{color}]  [dim]{content}[/dim]")
            elif todo.status == "cancelled":
                lines.append(f"  [{color}]{icon}[/{color}]  [dim strike]{content}[/dim strike]")
            else:
                lines.append(f"  [{color}]{icon}[/{color}]  {content}")

        self.update("\n".join(lines))


def _escape(text: str) -> str:
    return text.replace("[", r"\[")
