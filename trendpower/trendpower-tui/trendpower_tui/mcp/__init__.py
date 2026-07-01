"""TUI-side MCP integration: config loading + Textual lifecycle binding."""

from .config_loader import (
    DEFAULT_MCP_CONFIG_FILENAME,
    default_mcp_config_path,
    load_configured_servers,
)
from .lifecycle import MCPLifecycle

__all__ = [
    "DEFAULT_MCP_CONFIG_FILENAME",
    "default_mcp_config_path",
    "load_configured_servers",
    "MCPLifecycle",
]
