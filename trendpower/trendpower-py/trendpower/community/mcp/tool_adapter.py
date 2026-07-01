"""Bridge MCP tools to Trendpower ``FunctionTool``.

Each MCP tool becomes a ``FunctionTool`` whose ``invoke`` forwards to a
closure-captured ``MCPSession``. The server's exact JSON Schema is preserved
via ``FunctionTool.raw_input_schema`` so provider adapters serialize it
verbatim (no pydantic round-trip).

Tool names are prefixed with the server's logical name to prevent collisions
across multiple servers (e.g. ``filesystem__read_file``).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

from mcp.types import Tool as MCPTool
from pydantic import BaseModel, ConfigDict

from ...foundation.abort_signal import AbortSignal
from ...foundation.tools import FunctionTool, Tool
from .session import MCPSession


# A permissive placeholder pydantic class used only to satisfy
# FunctionTool.parameters' type slot. Providers use raw_input_schema instead.
class _AnyArgs(BaseModel):
    model_config = ConfigDict(extra="allow")


PREFIX_SEPARATOR = "__"

# Strict providers (notably OpenAI) require tool names to match
# ^[A-Za-z0-9_-]{1,64}$. The prefixed name (servername__toolname) can violate
# both rules when a server uses long or non-ASCII names, so we sanitize it.
_MAX_TOOL_NAME_LEN = 64
_INVALID_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_tool_name(name: str) -> str:
    """Coerce ``name`` into ``^[A-Za-z0-9_-]{1,64}$``.

    Invalid characters become ``_``. Over-long names are truncated and given a
    short hash suffix derived from the original so distinct tools stay distinct
    after truncation. Only the LLM-facing name changes; the closure in
    ``adapt_mcp_tool`` still calls the server with the tool's real name.
    """
    safe = _INVALID_NAME_CHARS.sub("_", name)
    if len(safe) <= _MAX_TOOL_NAME_LEN:
        return safe
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    keep = _MAX_TOOL_NAME_LEN - len(digest) - 1  # room for the '_' joiner
    return f"{safe[:keep]}_{digest}"


def prefixed_tool_name(server_name: str, tool_name: str) -> str:
    return _sanitize_tool_name(f"{server_name}{PREFIX_SEPARATOR}{tool_name}")


def _format_call_result(result: Any) -> Any:
    """Convert ``CallToolResult`` to a string or structured-error dict.

    The agent's tool-result formatter accepts any value, so we only need to
    pick a representation that the LLM will find useful:
    - text contents joined by newlines
    - non-text contents fall back to a brief type marker
    - ``isError=True`` becomes a structured error dict
    """
    content = getattr(result, "content", None) or []
    parts: List[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
            continue
        type_name = getattr(item, "type", item.__class__.__name__)
        parts.append(f"[{type_name} content omitted]")
    body = "\n".join(parts) if parts else ""

    if getattr(result, "isError", False):
        return {
            "ok": False,
            "summary": "MCP tool returned an error",
            "error": body or "no error message",
            "code": "mcp_tool_error",
        }
    return body


def adapt_mcp_tool(
    *,
    server_name: str,
    mcp_tool: MCPTool,
    session: MCPSession,
) -> Tool:
    """Wrap one ``MCPTool`` as a Trendpower ``FunctionTool`` bound to ``session``."""
    original_name = mcp_tool.name
    prefixed = prefixed_tool_name(server_name, original_name)
    description = mcp_tool.description or ""
    raw_schema: Dict[str, Any] = dict(mcp_tool.inputSchema or {"type": "object", "properties": {}})

    async def invoke(
        raw_input: Dict[str, Any], signal: Optional[AbortSignal] = None
    ) -> Any:
        # MCP servers validate inputs themselves; we just forward the dict.
        # `signal` cancellation is propagated by the surrounding agent loop —
        # ClientSession doesn't take a signal kwarg directly.
        result = await session.call_tool(original_name, raw_input)
        return _format_call_result(result)

    return FunctionTool(
        name=prefixed,
        description=description,
        parameters=_AnyArgs,
        invoke=invoke,
        raw_input_schema=raw_schema,
    )


def adapt_all(server_name: str, session: MCPSession) -> List[Tool]:
    """Adapt every tool currently cached on ``session``."""
    return [
        adapt_mcp_tool(server_name=server_name, mcp_tool=t, session=session)
        for t in session.tools
    ]
