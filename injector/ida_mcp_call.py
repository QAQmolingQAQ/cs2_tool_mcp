#!/usr/bin/env python3
"""Call an IDA Pro MCP (ida-pro-mcp) HTTP endpoint.

ida-pro-mcp exposes a JSON-RPC 2.0 endpoint at http://127.0.0.1:<port>/mcp for
each running IDA instance. This helper wraps `tools/call` so reverse-engineering
queries can be issued from the shell without hand-writing JSON.

Usage:
    python ida_mcp_call.py <port> --list
    python ida_mcp_call.py <port> <tool> [json-args]

Examples:
    python ida_mcp_call.py 13400 --list
    python ida_mcp_call.py 13400 decompile "{\"addr\":\"0x1812E1B50\"}"
    python ida_mcp_call.py 13400 xrefs_to  "{\"addr\":\"0x1826310E8\"}"
    python ida_mcp_call.py 13400 py_eval   "{\"code\":\"print(1+1)\"}"

Known instance ports (see %APPDATA%/Hex-Rays/IDA Pro/mcp/instances):
    hammer.dll  13400   pet.dll  13332
"""

from __future__ import annotations

import json
import sys
import urllib.request


def call(port: int, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_tools(port: int) -> None:
    result = call(port, "tools/list")
    tools = result.get("result", {}).get("tools", [])
    for tool in tools:
        print(tool.get("name"))


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    port = int(sys.argv[1])

    if sys.argv[2] in ("--list", "-l"):
        list_tools(port)
        return 0

    tool = sys.argv[2]
    args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}

    result = call(port, "tools/call", {"name": tool, "arguments": args})

    if "error" in result:
        print(json.dumps(result["error"], indent=2, ensure_ascii=False))
        return 1

    content = result.get("result", {}).get("content", [])
    for item in content:
        text = item.get("text", "")
        if item.get("type") == "text" and text:
            print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
