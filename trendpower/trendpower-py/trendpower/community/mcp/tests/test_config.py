import os

import pytest

from trendpower.community.mcp.config import (
    SSEServerConfig,
    StdioServerConfig,
    StreamableHTTPServerConfig,
    load_servers_from_dict,
)


def test_parses_three_transports() -> None:
    doc = {
        "mcpServers": {
            "fs": {
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@x/fs"],
            },
            "legacy": {"transport": "sse", "url": "https://a/sse"},
            "modern": {"transport": "streamable_http", "url": "https://a/mcp"},
        }
    }
    cfgs = load_servers_from_dict(doc)
    assert [c.name for c in cfgs] == ["fs", "legacy", "modern"]
    assert isinstance(cfgs[0], StdioServerConfig)
    assert isinstance(cfgs[1], SSEServerConfig)
    assert isinstance(cfgs[2], StreamableHTTPServerConfig)


def test_infers_stdio_when_transport_omitted() -> None:
    doc = {"mcpServers": {"fs": {"command": "echo", "args": ["hi"]}}}
    cfgs = load_servers_from_dict(doc)
    assert isinstance(cfgs[0], StdioServerConfig)


def test_infers_streamable_http_for_url_only() -> None:
    doc = {"mcpServers": {"x": {"url": "https://a/mcp"}}}
    cfgs = load_servers_from_dict(doc)
    assert isinstance(cfgs[0], StreamableHTTPServerConfig)


def test_env_interpolation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_xyz")
    doc = {
        "mcpServers": {
            "gh": {
                "transport": "stdio",
                "command": "echo",
                "env": {"TOKEN": "${GITHUB_TOKEN}"},
            }
        }
    }
    (cfg,) = load_servers_from_dict(doc)
    assert isinstance(cfg, StdioServerConfig)
    assert cfg.env["TOKEN"] == "ghp_xyz"


def test_missing_env_var_becomes_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOPE", raising=False)
    doc = {"mcpServers": {"x": {"transport": "sse", "url": "https://a/${NOPE}/sse"}}}
    (cfg,) = load_servers_from_dict(doc)
    assert isinstance(cfg, SSEServerConfig)
    assert cfg.url == "https://a//sse"


def test_unknown_transport_raises() -> None:
    doc = {"mcpServers": {"x": {"transport": "carrier-pigeon", "url": "https://a"}}}
    with pytest.raises(ValueError, match="unknown transport"):
        load_servers_from_dict(doc)


def test_missing_command_and_url_raises() -> None:
    doc = {"mcpServers": {"x": {}}}
    with pytest.raises(ValueError, match="missing both"):
        load_servers_from_dict(doc)


def test_empty_document() -> None:
    assert load_servers_from_dict({"mcpServers": {}}) == []
    assert load_servers_from_dict({}) == []
