# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# -*- coding: utf-8 -*-
"""apifox-mcp-server entry point.

Thin MCP shell around the `apifox` CLI. Two responsibilities:
  1. Documentation layer — let the agent discover Apifox endpoints (oas view).
  2. Regression layer — run QA-prepared scenarios (apifox run).

The actual HTTP test execution (send request + assert) is handled by the
sibling `api-mcp-server`; this server only bridges the agent to Apifox's
stored API definitions and pre-arranged scenarios.
"""

import argparse
import logging

from mcp.server.fastmcp import FastMCP

from apifox_cli import ApifoxCliRunner
from tools.endpoint_tool import register_endpoint_tools
from tools.scenario_tool import register_scenario_tools
from tools.diag_tool import register_diag_tools
from utils.logger import get_mcp_logger

logger = get_mcp_logger()


def _filter_mcp_lowlevel_logs():
    logging.getLogger('mcp.server.lowlevel.server').setLevel(logging.WARNING)


def main():
    _filter_mcp_lowlevel_logs()

    parser = argparse.ArgumentParser(description="apifox-mcp-server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    args = parser.parse_args()

    mcp = FastMCP("apifox-mcp-server", log_level="INFO")
    cli = ApifoxCliRunner()

    if not cli.has_token():
        logger.warning(
            "APIFOX_ACCESS_TOKEN not set — documentation/scenario tools will fail "
            "until it is configured in mcp_servers.json env."
        )

    register_diag_tools(mcp, cli)
    register_endpoint_tools(mcp, cli)
    register_scenario_tools(mcp, cli)

    logger.info(
        f"apifox-mcp-server starting (transport={args.transport}, "
        f"token_configured={cli.has_token()}, "
        f"default_project_id={cli.default_project_id or 'unset'})"
    )

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
