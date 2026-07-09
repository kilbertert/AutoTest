"""Middleware that asks the user for approval before tools in `requires_approval` run."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, List, Optional, Set

from ...foundation import ToolUseContent
from .approval_persistence import ApprovalPersistence
from .approval_types import ApprovalDecision

logger = logging.getLogger(__name__)


async def _empty_allow_list(_cwd: str) -> Set[str]:
    return set()


def create_coding_approval_middleware(
    *,
    cwd: str,
    requires_approval: List[str],
    ask_user: Callable[[ToolUseContent], Awaitable[ApprovalDecision]],
    approval_persistence: Optional[ApprovalPersistence] = None,
) -> Any:
    load_allow_list = (
        getattr(approval_persistence, "load_allow_list", None) if approval_persistence else None
    ) or _empty_allow_list
    persist_allowed_tool = (
        getattr(approval_persistence, "persist_allowed_tool", None) if approval_persistence else None
    )

    async def before_tool_use(params):
        tool_use: ToolUseContent = params["toolUse"]
        if tool_use["name"] not in requires_approval:
            return None
        allowed = await load_allow_list(cwd)
        if tool_use["name"] in allowed:
            return None
        decision = await ask_user(tool_use)
        if decision == "deny":
            return {
                "__skip": True,
                "result": (
                    f"User denied execution of tool: {tool_use['name']}. "
                    "You must either find an alternative approach or ask the user for clarification."
                ),
            }
        if decision == "allow_always_project" and persist_allowed_tool is not None:
            try:
                await persist_allowed_tool(cwd, tool_use["name"])
            except Exception as e:
                logger.warning("[trendpower] Could not persist allow for %s: %s", tool_use["name"], e)
        return None

    return SimpleNamespace(beforeToolUse=before_tool_use)
