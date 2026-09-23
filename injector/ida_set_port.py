#!/usr/bin/env python3
"""Use IDA MCP py_eval to change the persisted port, then restart MCP."""
import urllib.request, json, sys, time

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
    resp = urllib.request.urlopen(req, timeout=30)
    sid = resp.headers.get("Mcp-Session-Id")
    if sid: session_id = sid
    return json.loads(resp.read().decode())

def py_eval(code):
    r = call("tools/call", {"name": "py_eval", "arguments": {"code": code}})
    return r.get("result", {}).get("content", [{}])[0].get("text", "")

TARGET_PORT = 13338  # change to whatever you want

print(f"=== Changing IDA MCP port to {TARGET_PORT} ===")

# Step 1: Check current config
print("\n[1] Current netnode config:")
code = '''
import ida_netnode
node = ida_netnode.netnode("$ ida_mcp.config")
port = node.altval(0)
host = node.supstr(0)
persist = node.altval(1)
print(f"port={port} host={host!r} persist={persist}")
'''
print(py_eval(code))

# Step 2: Set new port
print(f"\n[2] Setting port to {TARGET_PORT}...")
code = f'''
import ida_netnode
node = ida_netnode.netnode("$ ida_mcp.config", 0, True)
node.altset(0, {TARGET_PORT})  # _ALT_PORT
node.supset(0, "127.0.0.1")    # _SUP_HOST = host
node.altset(1, 2)              # _ALT_PERSIST = persist on
print(f"Persisted port={node.altval(0)}, persist={node.altval(1)}")
'''
print(py_eval(code))

# Step 3: Also update the autostart node to ensure it starts
print("\n[3] Ensuring autostart enabled...")
code = '''
import ida_netnode
node = ida_netnode.netnode("$ ida_mcp.autostart", 0, True)
node.altset(0, 2)  # 2 = on (1 = off, 0 = not set/default on)
print(f"autostart={node.altval(0)}")
'''
print(py_eval(code))

print(f"\n[4] Done! Now in IDA press Ctrl+Alt+M to stop, then Ctrl+Alt+M to restart.")
print(f"    MCP server will bind to port {TARGET_PORT} on next start.")
print(f"    After restart, I'll test connectivity.")
