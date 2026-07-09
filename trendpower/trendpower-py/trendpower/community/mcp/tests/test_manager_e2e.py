"""End-to-end test using a real stdio subprocess.

Spawns ``_fake_stdio_server.py`` as a subprocess via ``MCPManager``, lists its
tools, calls them through Trendpower ``FunctionTool.invoke``, and verifies the
results round-trip cleanly. Also covers error isolation: one failing server
must not break others.
"""

from __future__ import annotations

import sys

import pytest

from trendpower.community.mcp.config import StdioServerConfig, load_servers_from_dict
from trendpower.community.mcp.manager import MCPManager

PY = sys.executable
SERVER_MOD = "trendpower.community.mcp.tests._fake_stdio_server"


def _ok_config(name: str = "fake") -> dict:
    return {
        name: {
            "transport": "stdio",
            "command": PY,
            "args": ["-m", SERVER_MOD],
        }
    }


def _bad_config(name: str = "bad") -> dict:
    return {
        name: {
            "transport": "stdio",
            "command": PY,
            "args": ["-m", SERVER_MOD, "--die"],
        }
    }


async def test_connect_list_call_close() -> None:
    cfgs = load_servers_from_dict({"mcpServers": _ok_config("fake")})
    mgr = MCPManager(cfgs)
    try:
        tools = await mgr.connect_all()
        names = {t.name for t in tools}
        assert "fake__echo" in names
        assert "fake__add" in names

        echo_tool = next(t for t in tools if t.name == "fake__echo")
        result = await echo_tool.invoke({"text": "hello"}, None)
        assert result == "hello"

        add_tool = next(t for t in tools if t.name == "fake__add")
        result = await add_tool.invoke({"a": 2, "b": 3}, None)
        # FastMCP serializes int returns as text — accept either string or int.
        assert str(result).strip() == "5"

        status = mgr.status()
        assert status[0].status == "connected"
        assert status[0].tool_count >= 2
    finally:
        await mgr.aclose()


async def test_error_isolation_one_bad_server() -> None:
    cfgs = load_servers_from_dict(
        {"mcpServers": {**_ok_config("good"), **_bad_config("bad")}}
    )
    mgr = MCPManager(cfgs)
    try:
        tools = await mgr.connect_all()
        # Good server's tools are present even though the bad one died.
        assert any(t.name.startswith("good__") for t in tools)
        assert not any(t.name.startswith("bad__") for t in tools)
        status_by_name = {s.name: s for s in mgr.status()}
        assert status_by_name["good"].status == "connected"
        assert status_by_name["bad"].status == "failed"
        assert status_by_name["bad"].error
    finally:
        await mgr.aclose()


async def test_reload_reconnects() -> None:
    cfgs = load_servers_from_dict({"mcpServers": _ok_config("fake")})
    mgr = MCPManager(cfgs)
    try:
        first = await mgr.connect_all()
        assert first
        second = await mgr.reload()
        assert {t.name for t in first} == {t.name for t in second}
    finally:
        await mgr.aclose()
