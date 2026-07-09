# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Diagnostic tools: verify the apifox CLI is installed and the token works.

Cheap calls the agent (or a first-time user) can run to confirm the
environment is healthy before attempting a real query.
"""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from apifox_cli import ApifoxCliRunner
from utils.logger import log_tool_call
from utils.response_format import format_tool_response, init_tool_response


def register_diag_tools(mcp: FastMCP, cli: ApifoxCliRunner):

    @mcp.tool()
    @log_tool_call
    async def apifox_cli_version():
        """Check whether the apifox CLI is installed and return its version.

        Run this first if anything else fails — it confirms the CLI binary is
        on PATH. Returns the version string on success, or an install hint on
        failure.
        """
        try:
            # --version doesn't need auth; pass inject_token=False to keep it clean.
            result = await cli.run(["--version"], timeout=15.0, inject_token=False)
        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = str(e)
            return format_tool_response(resp)

        data = {
            "installed": result.ok,
            "version": result.stdout.strip() or None,
        }
        if not result.ok:
            data["hint"] = "Install with: npm i -g apifox-cli (Node.js >= 14.20.1 required)"

        resp = init_tool_response()
        resp["status"] = "success" if result.ok else "error"
        resp["data"] = data
        if not result.ok:
            resp["error"] = "apifox CLI not installed or not on PATH"
        return format_tool_response(resp)

    @mcp.tool()
    @log_tool_call
    async def apifox_check_token(project_id: Optional[str] = None):
        """Verify the Apifox access token works against a project.

        Runs a minimal `apifox endpoint list --page-size 1` to confirm the token
        is valid and the project is reachable. Use this after apifox_cli_version
        to make sure queries against the project will succeed.

        Args:
            project_id: Apifox project ID. If omitted, uses APIFOX_PROJECT_ID env var.

        Returns:
            {token_configured, project_id, reachable} on success, or an error
            explaining what's missing (token / project_id / network).
        """
        pid = project_id or cli.default_project_id
        data = {
            "token_configured": cli.has_token(),
            "project_id": pid,
        }

        if not cli.has_token():
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = (
                "APIFOX_ACCESS_TOKEN env var not set. Generate a token in Apifox "
                "(个人设置 → API 访问令牌, prefix APS-) and set it in mcp_servers.json env."
            )
            resp["data"] = data
            return format_tool_response(resp)

        if not pid:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = "project_id not provided and APIFOX_PROJECT_ID env var not set."
            resp["data"] = data
            return format_tool_response(resp)

        try:
            result = await cli.run(
                ["endpoint", "list", "--project", pid, "--page", "1", "--page-size", "1"],
                timeout=30.0,
            )
        except Exception as e:
            resp = init_tool_response()
            resp["status"] = "error"
            resp["error"] = f"Failed to run apifox endpoint list: {e}"
            resp["data"] = data
            return format_tool_response(resp)

        data["reachable"] = result.ok
        if result.ok:
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = data
            return format_tool_response(resp)

        # Failure: surface the CLI's error message (e.g. AUTHENTICATION_FAILED).
        resp = init_tool_response()
        resp["status"] = "error"
        resp["error"] = (
            result.error_message()
            or f"apifox endpoint list failed (exit {result.exit_code}). "
            f"The token may be invalid/expired or the project ID is wrong."
        )
        resp["data"] = data
        return format_tool_response(resp)
