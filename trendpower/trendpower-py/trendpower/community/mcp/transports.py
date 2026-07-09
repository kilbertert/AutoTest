"""Unified transport opener.

Three transports converge on the same (read_stream, write_stream) pair that
``mcp.ClientSession`` consumes. This module hides the transport-specific
context managers behind a single ``open_transport(cfg)`` async ctx manager
so the rest of the package can stay transport-agnostic.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Tuple

from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from .config import (
    MCPServerConfig,
    SSEServerConfig,
    StdioServerConfig,
    StreamableHTTPServerConfig,
)


@asynccontextmanager
async def open_transport(cfg: MCPServerConfig) -> AsyncIterator[Tuple[object, object]]:
    """Open the transport for ``cfg`` and yield ``(read, write)`` streams.

    Cleanup (subprocess termination, socket close) is handled by the
    underlying SDK context managers on exit.
    """
    if isinstance(cfg, StdioServerConfig):
        params = StdioServerParameters(
            command=cfg.command,
            args=list(cfg.args),
            env=dict(cfg.env) if cfg.env else None,
            cwd=cfg.cwd,
        )
        async with stdio_client(params) as (read, write):
            yield read, write
        return

    if isinstance(cfg, SSEServerConfig):
        async with sse_client(cfg.url, headers=dict(cfg.headers) or None) as (read, write):
            yield read, write
        return

    if isinstance(cfg, StreamableHTTPServerConfig):
        # streamablehttp_client yields (read, write, _session_id_callback)
        async with streamablehttp_client(
            cfg.url, headers=dict(cfg.headers) or None
        ) as (read, write, _):
            yield read, write
        return

    raise TypeError(f"Unsupported MCP server config: {type(cfg).__name__}")
