"""Todo snapshot helpers ported from the TS TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TodoItemView:
    id: str
    content: str
    status: str


@dataclass(frozen=True)
class TodoViewState:
    latest_todos: list[TodoItemView] | None
    tool_uses: dict[str, dict[str, Any]]
    todo_snapshots: dict[str, list[TodoItemView]]


def snapshot_key(message_index: int, content_index: int) -> str:
    return f"{message_index}:{content_index}"


def build_todo_view_state(messages: list[dict[str, Any]]) -> TodoViewState:
    snapshots: dict[str, list[TodoItemView]] = {}
    tool_uses: dict[str, dict[str, Any]] = {}
    store: list[TodoItemView] = []
    latest_todos: list[TodoItemView] | None = None

    for message_index, message in enumerate(messages):
        if message.get("role") == "user":
            latest_todos = None
            continue
        if message.get("role") != "assistant":
            continue
        for content_index, content in enumerate(message.get("content") or []):
            if not isinstance(content, dict) or content.get("type") != "tool_use":
                continue
            tool_id = content.get("id")
            if isinstance(tool_id, str):
                tool_uses[tool_id] = content
            if content.get("name") != "todo_write":
                continue
            store = _apply_todo_write(store, _to_todo_write_input(content.get("input")))
            snapshots[snapshot_key(message_index, content_index)] = store
            latest_todos = store

    return TodoViewState(latest_todos=latest_todos, tool_uses=tool_uses, todo_snapshots=snapshots)


def get_current_todo(todos: list[TodoItemView] | None) -> TodoItemView | None:
    return next((todo for todo in todos or [] if todo.status == "in_progress"), None)


def get_next_todo(todos: list[TodoItemView] | None) -> TodoItemView | None:
    return next((todo for todo in todos or [] if todo.status == "pending"), None)


def _to_todo_write_input(value: Any) -> tuple[bool, list[TodoItemView]]:
    if not isinstance(value, dict):
        return False, []
    todos: list[TodoItemView] = []
    for item in value.get("todos") if isinstance(value.get("todos"), list) else []:
        if not isinstance(item, dict):
            continue
        todo_id = item.get("id")
        content = item.get("content")
        status = item.get("status")
        if isinstance(todo_id, str) and isinstance(content, str) and isinstance(status, str):
            todos.append(TodoItemView(id=todo_id, content=content, status=status))
    return value.get("merge") is True, todos


def _apply_todo_write(store: list[TodoItemView], data: tuple[bool, list[TodoItemView]]) -> list[TodoItemView]:
    merge, todos = data
    if not merge:
        return [*todos]
    next_items = [*store]
    for item in todos:
        index = next((i for i, existing in enumerate(next_items) if existing.id == item.id), -1)
        if index >= 0:
            next_items[index] = item
        else:
            next_items.append(item)
    return next_items
