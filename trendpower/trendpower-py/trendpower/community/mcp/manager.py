"""``MCPManager`` — orchestrate N MCP servers for one agent process.

Responsibilities:
- Connect to every configured server in parallel.
- Isolate failures: a single bad server is logged but does not break the rest.
- Aggregate adapted tools across all healthy servers.
- Provide a status snapshot for the ``/mcp list`` slash command.
- Tear down all sessions cleanly on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from ...foundation.tools import Tool
from .config import MCPServerConfig
from .toolset import MCPToolset

_log = logging.getLogger(__name__)

StatusKind = Literal["connected", "failed", "not_connected"]


@dataclass
class MCPServerStatus:
    name: str
    transport: str
    status: StatusKind
    tool_count: int
    error: Optional[str] = None


class MCPManager:
    def __init__(self, configs: List[MCPServerConfig]) -> None:
        self._configs = list(configs)
        self._toolsets: Dict[str, MCPToolset] = {
            cfg.name: MCPToolset(cfg) for cfg in self._configs
        }
        self._connected = False

    @property
    def toolsets(self) -> List[MCPToolset]:
        return list(self._toolsets.values())

    async def connect_all(self) -> List[Tool]:
        """Connect every server in parallel. Returns the aggregated tool list.

        Failed servers are logged and their error is exposed via ``status()``.
        Other servers continue to work normally.
        """
        if self._connected:
            raise RuntimeError("MCPManager already connected")

        async def _connect_one(ts: MCPToolset) -> None:
            try:
                await ts.connect()
            except BaseException as exc:  # noqa: BLE001
                ts.error = exc
                _log.warning(
                    "MCP server %r failed to start: %s", ts.cfg.name, exc
                )

        await asyncio.gather(
            *(_connect_one(ts) for ts in self._toolsets.values()),
            return_exceptions=False,
        )
        self._connected = True

        tools: List[Tool] = []
        for ts in self._toolsets.values():
            if ts.connected:
                tools.extend(ts.tools)
        return tools

    def status(self) -> List[MCPServerStatus]:
        out: List[MCPServerStatus] = []
        for ts in self._toolsets.values():
            if ts.connected:
                kind: StatusKind = "connected"
                err: Optional[str] = None
            elif ts.error is not None:
                kind = "failed"
                err = str(ts.error)
            else:
                kind = "not_connected"
                err = None
            out.append(
                MCPServerStatus(
                    name=ts.cfg.name,
                    transport=ts.cfg.transport,
                    status=kind,
                    tool_count=len(ts.tools),
                    error=err,
                )
            )
        return out

    async def aclose(self) -> None:
        await asyncio.gather(
            *(ts.aclose() for ts in self._toolsets.values()),
            return_exceptions=True,
        )
        self._connected = False

    async def reload(self) -> List[Tool]:
        """Tear down and re-connect using the same configs."""
        await self.aclose()
        self._toolsets = {cfg.name: MCPToolset(cfg) for cfg in self._configs}
        return await self.connect_all()
