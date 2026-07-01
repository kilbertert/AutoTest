# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Diagnostic tools: self-check."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from utils.logger import log_tool_call
from utils.response_format import format_tool_response, init_tool_response

VERSION = "excelio-mcp-server 0.1.0"


def register_diag_tools(mcp: FastMCP):

    @mcp.tool()
    @log_tool_call
    async def version() -> str:
        """Return the server version. Use as a health check."""
        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {"version": VERSION}
        return format_tool_response(resp)
