"""A minimal stdio MCP server used by the manager e2e test.

Run as: ``python -m trendpower.community.mcp.tests._fake_stdio_server``
Exposes two tools (echo, add) and an optional flag to fail to start.
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP


def main() -> None:
    if "--die" in sys.argv:
        sys.stderr.write("intentional failure\n")
        sys.exit(2)

    server = FastMCP("fake")

    @server.tool(description="Echo the input string")
    def echo(text: str) -> str:
        return text

    @server.tool(description="Add two numbers")
    def add(a: int, b: int) -> int:
        return a + b

    server.run("stdio")


if __name__ == "__main__":
    main()
