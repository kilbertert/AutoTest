from __future__ import annotations

from typing import Literal, TypedDict

TodoStatus = Literal["pending", "in_progress", "completed", "cancelled"]


class TodoItem(TypedDict):
    id: str
    content: str
    status: TodoStatus
