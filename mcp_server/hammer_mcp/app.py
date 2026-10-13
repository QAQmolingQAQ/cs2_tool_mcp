"""MCP composition root and CLI. The only module that imports FastMCP."""
from __future__ import annotations
import argparse
from functools import wraps
import sys
from mcp.server.fastmcp import FastMCP
from .scopes import SCOPES, select_tools
from .operation_lock import operation_lock
from .session import BridgeSession
from .settings import DEFAULT_PIPE


def _bind_session(function, session):
    @wraps(function)
    def invoke(*args, **kwargs):
        with operation_lock(session.pipe.pipe_name), session.activate():
            return function(*args, **kwargs)
    return invoke


def create_server(session: BridgeSession | None = None, scope: str = "all") -> FastMCP:
    session = session or BridgeSession()
    functions = select_tools(scope)
    server = FastMCP("cs2_tool" if scope == "all" else "cs2_" + scope, instructions=(
        f"Module scope: {scope}. "
        "CS2 editor tools via the injected cs2_tool.dll named-pipe bridge. "
        "Load the bridge before live operations. Addresses support 0x... and hammer.dll+0x... ."
    ))
    for function in functions:
        server.add_tool(_bind_session(function, session))
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="CS2 Tool MCP Server")
    parser.add_argument("--pipe", default=DEFAULT_PIPE, help="Shared CS2 bridge named pipe")
    parser.add_argument("--stdio", action="store_true", help="Use MCP stdio transport")
    parser.add_argument("--scope", choices=SCOPES, default="all", help="Module-specific tool inventory")
    args = parser.parse_args()
    session = BridgeSession(args.pipe)
    print(f"[cs2_tool_mcp] scope={args.scope} pipe={args.pipe}", file=sys.stderr)
    try:
        create_server(session, scope=args.scope).run(transport="stdio")
    finally:
        session.close()
