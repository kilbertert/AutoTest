"""One MCP server, one toolset.

The MCP SDK's transport context managers (especially ``stdio_client``) are
backed by anyio task scopes that **must be entered and exited from the same
task**. To support a long-lived session (open during agent start-up, closed
during shutdown — usually in different awaiters), we run the entire
session lifecycle inside one dedicated background task and synchronize via
``asyncio.Event`` flags.

This makes ``connect()`` and ``aclose()`` safe to call from any task.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from ...foundation.tools import Tool
from .config import MCPServerConfig
from .session import MCPSession
from .tool_adapter import adapt_all

_log = logging.getLogger(__name__)


class MCPToolset:
    def __init__(self, cfg: MCPServerConfig) -> None:
        self.cfg = cfg
        self.session = MCPSession(cfg)
        self._tools: Optional[List[Tool]] = None
        self.error: Optional[BaseException] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._ready: Optional[asyncio.Event] = None
        self._closing: Optional[asyncio.Event] = None

    @property
    def name(self) -> str:
        return self.cfg.name

    @property
    def connected(self) -> bool:
        return self.session.is_open

    @property
    def tools(self) -> List[Tool]:
        return list(self._tools or [])

    async def connect(self) -> List[Tool]:
        if self._task is not None:
            raise RuntimeError(f"MCPToolset {self.cfg.name} already connecting")
        self._ready = asyncio.Event()
        self._closing = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name=f"mcp[{self.cfg.name}]")
        await self._ready.wait()
        if self.error is not None:
            raise self.error
        return list(self._tools or [])

    async def _run(self) -> None:
        assert self._ready is not None
        assert self._closing is not None
        try:
            await self.session.open()
            self._tools = adapt_all(self.cfg.name, self.session)
        except BaseException as exc:  # connection / handshake failure
            self.error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            await self._closing.wait()
        finally:
            try:
                await self.session.aclose()
            except BaseException:  # noqa: BLE001
                _log.exception("MCPToolset %s failed to close cleanly", self.cfg.name)

    async def aclose(self) -> None:
        if self._closing is not None:
            self._closing.set()
        if self._task is not None:
            try:
                await self._task
            finally:
                self._task = None
                self._ready = None
                self._closing = None
                self._tools = None
