"""Locate and parse ``mcp_servers.json``.

Resolution order:
1. ``$TRENDPOWER_HOME/mcp_servers.json`` if ``TRENDPOWER_HOME`` is set
2. ``~/.trendpower/mcp_servers.json`` otherwise

Missing file → empty list (no MCP servers configured, not an error).
Malformed file → empty list + log warning (don't crash TUI startup).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from trendpower.community.mcp import MCPServerConfig, load_servers_from_file

from ..settings.settings_loader import _default_trendpower_home

DEFAULT_MCP_CONFIG_FILENAME = "mcp_servers.json"

_log = logging.getLogger(__name__)


def default_mcp_config_path() -> Path:
    return _default_trendpower_home() / DEFAULT_MCP_CONFIG_FILENAME


def load_configured_servers(path: Optional[Path] = None) -> List[MCPServerConfig]:
    target = path or default_mcp_config_path()
    if not target.exists():
        return []
    try:
        return load_servers_from_file(target)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Could not parse %s: %s", target, exc)
        return []
