from __future__ import annotations

from typing import Awaitable, Callable, Protocol, Set


class ApprovalPersistence(Protocol):
    load_allow_list: Callable[[str], Awaitable[Set[str]]]
    persist_allowed_tool: Callable[[str, str], Awaitable[None]]
