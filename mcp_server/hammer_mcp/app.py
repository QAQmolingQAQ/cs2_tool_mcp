"""MCP composition root and CLI. The only module that imports FastMCP."""
from __future__ import annotations
import argparse
from functools import wraps
import sys
from mcp.server.fastmcp import FastMCP
from .registry import TOOL_FUNCTIONS
from .session import BridgeSession
from .settings import DEFAULT_PIPE


def _bind_session(function, session):
    @wraps(function)
    def invoke(*args, **kwargs):
        with session.activate():
            return function(*args, **kwargs)
    return invoke


def create_server(session: BridgeSession | None = None) -> FastMCP:
    session = session or BridgeSession()
    server = FastMCP("cs2_tool", instructions=(
        "CS2 Hammer tools via the injected cs2_tool.dll named-pipe bridge. "
        "Load the bridge before live operations. Addresses support 0x... and hammer.dll+0x... ."
    ))
    for function in TOOL_FUNCTIONS:
        server.add_tool(_bind_session(function, session))
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="CS2 Tool MCP Server")
    parser.add_argument("--pipe", default=DEFAULT_PIPE, help="Hammer bridge named pipe")
    parser.add_argument("--stdio", action="store_true", help="Use MCP stdio transport")
    args = parser.parse_args()
    session = BridgeSession(args.pipe)
    print(f"[cs2_tool_mcp] pipe={args.pipe}", file=sys.stderr)
    try:
        create_server(session).run(transport="stdio")
    finally:
        session.close()
