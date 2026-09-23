#!/usr/bin/env python3
"""Test IDA MCP connection via raw HTTP/SSE on port 13337."""
import urllib.request
import json
import sys

BASE = "http://127.0.0.1:13337"

def get(path):
    try:
        req = urllib.request.Request(f"{BASE}{path}")
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, resp.read().decode()
    except Exception as e:
        return None, str(e)

def post(path, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(f"{BASE}{path}", data=body, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, resp.read().decode()
    except Exception as e:
        return None, str(e)

# Try common MCP endpoints
paths = ["/", "/health", "/sse", "/tools", "/mcp", "/initialize"]

for p in paths:
    status, body = get(p)
    print(f"GET {p} -> {status}: {body[:200] if body else '(empty)'}")

# Try MCP initialize via POST
print("\n--- POST /initialize ---")
status, body = post("/initialize", {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "test", "version": "0.1"}
})
print(f"POST /initialize -> {status}: {body[:500] if body else '(empty)'}")

# Try /tools/list
print("\n--- POST /tools/list ---")
status, body = post("/tools/list", {})
print(f"POST /tools/list -> {status}: {body[:2000] if body else '(empty)'}")
