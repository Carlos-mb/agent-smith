"""Small streamable-HTTP MCP server used only by the client integration test."""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("HTTP test server", instructions="HTTP integration instructions.",
              port=int(sys.argv[1]), log_level="CRITICAL")


@mcp.tool()
def identify(value: str) -> str:
    """Return the supplied value with a fixed prefix."""
    return "identified: " + value


@mcp.resource("test://status")
def status() -> str:
    """Return the server status."""
    return "ready"


@mcp.resource("test://items/{name}")
def item(name: str) -> str:
    """Return a named test item."""
    return "item: " + name


@mcp.prompt()
def discuss(topic: str) -> str:
    """Prepare a short discussion prompt for a topic."""
    return "Discuss " + topic


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
