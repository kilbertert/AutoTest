"""Singleton-style lifecycle binding for the TUI process.

``MCPLifecycle`` owns one ``MCPManager`` instance and gives the Textual app
two simple hooks: ``startup()`` to connect everything and return tool list,
``shutdown()`` to tear it all down. ``reload()`` and ``status()`` are
exposed for the ``/mcp`` slash command.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from trendpower.community.mcp import MCPManager, MCPServerStatus
from trendpower.foundation.tools import Tool

from .config_loader import default_mcp_config_path, load_configured_servers

_log = logging.getLogger(__name__)


class MCPLifecycle:
    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path or default_mcp_config_path()
        self.manager: Optional[MCPManager] = None
        self.startup_summary: str = ""

    async def startup(self) -> List[Tool]:
        configs = load_configured_servers(self.config_path)
        if not configs:
            self.startup_summary = "No MCP servers configured."
            self.manager = MCPManager([])
            return []
        self.manager = MCPManager(configs)
        tools = await self.manager.connect_all()
        self._refresh_summary(tools)
        return tools

    def _refresh_summary(self, tools: List[Tool]) -> None:
        """Recompute ``startup_summary`` from the current manager status."""
        if self.manager is None:
            self.startup_summary = "No MCP servers configured."
            return
        statuses = self.manager.status()
        ok = sum(1 for s in statuses if s.status == "connected")
        failed = sum(1 for s in statuses if s.status == "failed")
        self.startup_summary = (
            f"MCP: {ok} server(s) connected ({len(tools)} tool(s)), "
            f"{failed} failed."
        )

    async def shutdown(self) -> None:
        if self.manager is not None:
            try:
                await self.manager.aclose()
            finally:
                self.manager = None

    async def reload(self) -> List[Tool]:
        if self.manager is None:
            return await self.startup()
        # Re-read the config file so edits take effect on reload.
        configs = load_configured_servers(self.config_path)
        await self.manager.aclose()
        self.manager = MCPManager(configs)
        tools = await self.manager.connect_all()
        self._refresh_summary(tools)
        return tools

    def status(self) -> List[MCPServerStatus]:
        return self.manager.status() if self.manager else []
