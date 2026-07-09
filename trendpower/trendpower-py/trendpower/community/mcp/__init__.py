"""MCP (Model Context Protocol) integration.

Exposes external MCP servers as Trendpower tools. Supports three transports:
stdio (local subprocess), SSE (legacy remote), and Streamable HTTP (modern remote).

Typical use:

    from trendpower.community.mcp import MCPManager, load_servers_from_dict

    configs = load_servers_from_dict({"mcpServers": {...}})
    manager = MCPManager(configs)
    tools = await manager.connect_all()       # list[Tool]
    try:
        agent = await create_coding_agent(model=..., extra_tools=tools)
        ...
    finally:
        await manager.aclose()
"""

from .config import (
    MCPServerConfig,
    StdioServerConfig,
    SSEServerConfig,
    StreamableHTTPServerConfig,
    load_servers_from_dict,
    load_servers_from_file,
)
from .manager import MCPManager, MCPServerStatus
from .toolset import MCPToolset

__all__ = [
    "MCPServerConfig",
    "StdioServerConfig",
    "SSEServerConfig",
    "StreamableHTTPServerConfig",
    "load_servers_from_dict",
    "load_servers_from_file",
    "MCPManager",
    "MCPServerStatus",
    "MCPToolset",
]
