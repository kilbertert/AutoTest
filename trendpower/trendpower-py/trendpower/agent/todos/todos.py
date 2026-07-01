"""Todo write tool + middleware that injects reminders if the agent forgets."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field

from ...foundation import Tool, define_tool
from .types import TodoItem, TodoStatus

TODO_WRITE_TOOL_NAME = "todo_write"

_STEPS_SINCE_WRITE = 10
_STEPS_BETWEEN_REMINDERS = 10

_TOOL_DESCRIPTION = """Create and manage a structured task list for the current session. This helps track progress, organize complex tasks, and demonstrate thoroughness.

## When to Use

1. Complex multi-step tasks requiring 3 or more distinct steps
2. Non-trivial tasks requiring careful planning or multiple operations
3. User explicitly requests a todo list
4. User provides multiple tasks (numbered or comma-separated)
5. After receiving new instructions — capture requirements as todos (use merge=false to add new ones)
6. After completing tasks — mark complete with merge=true and add follow-ups
7. When starting new tasks — mark as in_progress (ideally only one at a time)

## When NOT to Use

1. Single, straightforward tasks
2. Trivial tasks with no organizational benefit
3. Tasks completable in fewer than 3 trivial steps
4. Purely conversational or informational requests

## Task States

- pending: Not yet started
- in_progress: Currently working on (limit to ONE at a time)
- completed: Finished successfully
- cancelled: No longer needed

## Task Management Rules

- Update status in real-time as you work
- Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
- Only ONE task should be in_progress at any time
- Complete current tasks before starting new ones
- If blocked, keep the task as in_progress and create a new task for the blocker

## Merge Behavior

- merge=true: Merges by id — existing ids are updated, new ids are appended. You can send only the changed items.
- merge=false: Replaces the entire list with the provided todos."""


class _TodoItemSchema(BaseModel):
    id: str = Field(description="Unique identifier for this todo item.")
    content: str = Field(description="Description of the task.")
    status: TodoStatus = Field(description="Current status.")


class _TodoWriteParams(BaseModel):
    todos: List[_TodoItemSchema] = Field(description="Array of todo items to create or update.")
    merge: bool = Field(
        description=(
            "If true, merges into the existing list by id (existing ids updated, "
            "new ids appended). If false, replaces the entire list."
        )
    )


def _format_summary(todos: List[TodoItem]) -> str:
    counts: Dict[str, int] = {"pending": 0, "in_progress": 0, "completed": 0, "cancelled": 0}
    for t in todos:
        counts[t["status"]] += 1
    parts: List[str] = []
    if counts["pending"] > 0:
        parts.append(f"{counts['pending']} pending")
    if counts["in_progress"] > 0:
        parts.append(f"{counts['in_progress']} in_progress")
    if counts["completed"] > 0:
        parts.append(f"{counts['completed']} completed")
    if counts["cancelled"] > 0:
        parts.append(f"{counts['cancelled']} cancelled")
    return f"Todo list updated. {len(todos)} items: {', '.join(parts)}."


def _format_reminder(todos: List[TodoItem]) -> str:
    lines = "\n".join(f"{i + 1}. [{t['status']}] {t['content']}" for i, t in enumerate(todos))
    return (
        "\n<todo_reminder>\n"
        "The todo_write tool hasn't been used recently. If you're working on tasks that benefit "
        "from tracking, consider updating your todo list. Only use it if relevant to the current work. "
        "Here are the current items:\n\n"
        f"{lines}\n"
        "</todo_reminder>"
    )


def create_todo_system() -> Tuple[Tool, Any]:
    """Returns (tool, middleware) — the tool the model invokes, plus a middleware
    that periodically reminds the model to use it."""

    store: List[TodoItem] = []
    state = SimpleNamespace(
        steps_since_last_write=math.inf,
        steps_since_last_reminder=math.inf,
    )

    async def invoke(params: _TodoWriteParams, signal=None) -> str:  # noqa: ARG001
        if params.merge:
            for item in params.todos:
                idx = next((i for i, t in enumerate(store) if t["id"] == item.id), -1)
                payload: TodoItem = {"id": item.id, "content": item.content, "status": item.status}
                if idx >= 0:
                    store[idx] = payload
                else:
                    store.append(payload)
        else:
            store.clear()
            for item in params.todos:
                store.append({"id": item.id, "content": item.content, "status": item.status})

        state.steps_since_last_write = 0
        return _format_summary(store)

    tool = define_tool(
        name=TODO_WRITE_TOOL_NAME,
        description=_TOOL_DESCRIPTION,
        parameters=_TodoWriteParams,
        invoke=invoke,
    )

    async def before_model(params):
        state.steps_since_last_write += 1
        state.steps_since_last_reminder += 1

        if (
            len(store) > 0
            and state.steps_since_last_write >= _STEPS_SINCE_WRITE
            and state.steps_since_last_reminder >= _STEPS_BETWEEN_REMINDERS
        ):
            state.steps_since_last_reminder = 0
            return {"prompt": params["modelContext"]["prompt"] + _format_reminder(store)}
        return None

    async def after_tool_use(params):
        if params["toolUse"]["name"] == TODO_WRITE_TOOL_NAME:
            state.steps_since_last_write = 0
        return None

    middleware = SimpleNamespace(beforeModel=before_model, afterToolUse=after_tool_use)
    return tool, middleware
