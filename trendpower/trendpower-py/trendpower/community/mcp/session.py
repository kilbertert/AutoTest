"""MCPSession — a thin shim over ``mcp.ClientSession``.

Owns the transport context-manager + the ClientSession context-manager and
exposes the bits Trendpower cares about: ``initialize()``, ``list_tools()``,
``call_tool()``, and ``aclose()``. Lifetimes are managed explicitly (open /
close), not via ``async with``, so a higher layer (``MCPToolset``) can hold a
long-lived session for the duration of an agent run.

Implementation note: we cannot ``async with`` inside one coroutine and exit
in another (anyio task-scope rules). To support long-lived sessions we use
``contextlib.AsyncExitStack`` and enter the two CMs explicitly.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.types import Tool as MCPTool

from .config import MCPServerConfig
from .transports import open_transport


class MCPSession:
    def __init__(self, cfg: MCPServerConfig) -> None:
        self.cfg = cfg
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        self._tools: List[MCPTool] = []

    @property
    def tools(self) -> List[MCPTool]:
        return list(self._tools)

    @property
    def is_open(self) -> bool:
        return self._session is not None

    async def open(self) -> None:
        """Open transport, initialize, and cache the tool list."""
        if self._session is not None:
            raise RuntimeError(f"MCPSession {self.cfg.name} already open")
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(open_transport(self.cfg))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
            self._tools = list(listed.tools)
            self._session = session
            self._stack = stack
        except BaseException:
            await stack.aclose()
            raise

    async def call_tool(
        self, name: str, arguments: Dict[str, Any]
    ) -> Any:
        if self._session is None:
            raise RuntimeError(
                f"MCPSession {self.cfg.name} is not open; call open() first"
            )
        return await self._session.call_tool(name, arguments=arguments)

    async def aclose(self) -> None:
        stack, self._stack = self._stack, None
        self._session = None
        self._tools = []
        if stack is not None:
            await stack.aclose()
