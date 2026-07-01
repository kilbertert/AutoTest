"""Adapter that exposes Settings* helpers via the `ApprovalPersistence` protocol shape."""

from __future__ import annotations

from typing import Set

from .settings_loader import SettingsLoader
from .settings_writer import SettingsWriter


class SettingsApprovalPersistence:
    """Bridges `SettingsLoader`/`SettingsWriter` into the names the agent expects.

    The core (`coding_approval_middleware`) reads attributes named
    `load_allow_list` and `persist_allowed_tool` off whatever object is passed
    as ``approval_persistence``. The TS frontend supplied closures with those
    exact names; here we keep the loader/writer split and expose adapters.
    """

    def __init__(self, loader: SettingsLoader | None = None, writer: SettingsWriter | None = None) -> None:
        self._loader = loader or SettingsLoader()
        self._writer = writer or SettingsWriter(self._loader)

    async def load_allow_list(self, cwd: str) -> Set[str]:
        return await self._loader.load_allow_list(cwd)

    async def persist_allowed_tool(self, cwd: str, tool_name: str) -> None:
        await self._writer.append_allowed_tool(cwd, tool_name)
