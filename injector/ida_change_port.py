#!/usr/bin/env python3
"""Change IDA MCP port by calling IDA's HTTP API via IDAPython eval."""
import urllib.request, json, sys

BASE = "http://127.0.0.1:13337"
session_id = None
msg_id = 0

def call(method, params):
    global msg_id, session_id
    msg_id += 1
    payload = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session_id: headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(BASE + "/mcp", data=json.dumps(payload).encode(), headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        sid = resp.headers.get("Mcp-Session-Id")
        if sid: session_id = sid
        return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return None, str(e)

def mcp_tool(name, arguments):
    r, e = call("tools/call", {"name": name, "arguments": arguments})
    if not r:
        return None, e
    content = r.get("result", {}).get("content", [])
    if content and content[0].get("type") == "text":
        return content[0]["text"], None
    return r.get("result"), None

# Initialize
r, e = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0.1"}})
print(f"Connected: session={session_id}")

# Get current port
r, e = mcp_tool("server_health", {})
print(f"\nCurrent server_health:")
print(r[:500] if r else f"ERROR: {e}")

# List available tools
print("\n=== Trying py_eval to change port ===")
# First, let's check what port-setting tools exist
r, e = call("tools/list", {})
if r:
    tools = r.get("result", {}).get("tools", [])
    tool_names = [t["name"] for t in tools]
    print(f"Available tools ({len(tool_names)}):")
    for name in tool_names:
        if "config" in name.lower() or "port" in name.lower() or "set" in name.lower():
            print(f"  * {name}")
    if "set_config" in tool_names or "config" in tool_names:
        # try config setting
        r, e = mcp_tool("config", {})
        print(f"\nconfig result: {r}")
