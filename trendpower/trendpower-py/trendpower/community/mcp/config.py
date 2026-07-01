"""MCP server configuration models.

Mirrors the Claude Desktop ``mcp_servers.json`` shape so users can copy
configs between hosts. Three transports are supported: ``stdio`` (local
subprocess), ``sse`` (legacy remote), and ``streamable_http`` (modern remote).

``${ENV_VAR}`` strings inside ``env``, ``headers``, ``url``, ``command``, and
``args`` are expanded against ``os.environ`` at load time.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# --- env-var interpolation -------------------------------------------------

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value: Any) -> Any:
    """Recursively expand ``${ENV_VAR}`` references inside strings."""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


# --- per-transport config --------------------------------------------------


class _BaseServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Logical name; used as tool-name prefix.")


class StdioServerConfig(_BaseServerConfig):
    transport: Literal["stdio"] = "stdio"
    command: str
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None


class SSEServerConfig(_BaseServerConfig):
    transport: Literal["sse"] = "sse"
    url: str
    headers: Dict[str, str] = Field(default_factory=dict)


class StreamableHTTPServerConfig(_BaseServerConfig):
    transport: Literal["streamable_http"] = "streamable_http"
    url: str
    headers: Dict[str, str] = Field(default_factory=dict)


MCPServerConfig = Annotated[
    Union[StdioServerConfig, SSEServerConfig, StreamableHTTPServerConfig],
    Field(discriminator="transport"),
]


# --- loading ---------------------------------------------------------------


class _ServersFile(BaseModel):
    model_config = ConfigDict(extra="allow")

    mcpServers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


def load_servers_from_dict(document: Dict[str, Any]) -> List[MCPServerConfig]:
    """Parse a ``{"mcpServers": {...}}`` document into typed configs.

    Order is preserved (Python dicts are insertion-ordered). Unknown
    transports raise ``ValueError`` rather than silently dropping the entry —
    a typo in a transport name should be loud.
    """
    parsed = _ServersFile.model_validate(document)
    out: List[MCPServerConfig] = []
    for name, raw in parsed.mcpServers.items():
        expanded = _expand(raw)
        # Default transport for back-compat with Claude Desktop, which omits
        # the field for stdio entries (command + args present).
        if "transport" not in expanded:
            if "command" in expanded:
                expanded["transport"] = "stdio"
            elif "url" in expanded:
                # Prefer the modern transport when the user gave only a URL.
                expanded["transport"] = "streamable_http"
            else:
                raise ValueError(
                    f"MCP server '{name}' is missing both 'command' and 'url'; "
                    "cannot infer transport."
                )
        expanded["name"] = name
        try:
            if expanded["transport"] == "stdio":
                out.append(StdioServerConfig.model_validate(expanded))
            elif expanded["transport"] == "sse":
                out.append(SSEServerConfig.model_validate(expanded))
            elif expanded["transport"] == "streamable_http":
                out.append(StreamableHTTPServerConfig.model_validate(expanded))
            else:
                raise ValueError(
                    f"MCP server '{name}' has unknown transport "
                    f"'{expanded['transport']}'. Valid: stdio, sse, streamable_http."
                )
        except ValidationError as exc:
            raise ValueError(f"MCP server '{name}' config invalid: {exc}") from exc
    return out


def load_servers_from_file(path: Path | str) -> List[MCPServerConfig]:
    """Load and parse a JSON file at ``path``. Returns ``[]`` if missing."""
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MCP servers file {p} is not valid JSON: {exc}") from exc
    return load_servers_from_dict(doc)
