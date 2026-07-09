# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# -*- coding: utf-8 -*-
"""excelio-mcp-server entry point.

Thin MCP server for reading/writing .xlsx test-case blueprints.

Why it exists: the example 测试用例.xlsx has a broken stylesheet node that
crashes openpyxl on read. This server reads via zipfile + xml.etree (stable)
and writes via openpyxl (we control the files we write, so no broken styles).

Two responsibilities:
  1. READ the example template — header structure + module map (sheet 2).
  2. WRITE a fresh blueprint .xlsx — create, append design-time rows,
     update execute-time result cells (column-whitelist protected).
"""

import argparse
import logging

from mcp.server.fastmcp import FastMCP

from tools.read_tool import register_read_tools
from tools.write_tool import register_write_tools
from tools.diag_tool import register_diag_tools
from utils.logger import get_mcp_logger

logger = get_mcp_logger()


def _filter_mcp_lowlevel_logs():
    logging.getLogger('mcp.server.lowlevel.server').setLevel(logging.WARNING)


def main():
    _filter_mcp_lowlevel_logs()

    parser = argparse.ArgumentParser(description="excelio-mcp-server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    args = parser.parse_args()

    mcp = FastMCP("excelio-mcp-server", log_level="INFO")

    register_diag_tools(mcp)
    register_read_tools(mcp)
    register_write_tools(mcp)

    logger.info(
        "excelio-mcp-server starting "
        f"(transport={args.transport})"
    )

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
