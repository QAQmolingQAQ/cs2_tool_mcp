#!/usr/bin/env python3
"""Test IDA MCP connection - correct endpoints."""
import urllib.request, json, sys

BASE = "http://127.0.0.1:13337"

def send(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(f"{BASE}{path}", data=body, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, resp.headers, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()
    except Exception as e:
        return None, None, str(e)

# Try POST /mcp
print("=== POST /mcp initialize ===")
status, headers, body = send("/mcp", {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0.1"}
    }
})
print(f"Status: {status}")
print(f"Headers: {dict(headers) if headers else {}}")
print(f"Body: {body[:1000] if body else '(empty)'}")

# Try /mcp with tools/list
print("\n=== POST /mcp tools/list ===")
status, headers, body = send("/mcp", {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
})
print(f"Status: {status}")
print(f"Body: {body[:3000] if body else '(empty)'}")
