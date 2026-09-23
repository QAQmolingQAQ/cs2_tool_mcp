#!/usr/bin/env python3
"""Set IDA MCP port via single-block py_eval."""
import urllib.request, json

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
    content = r.get("result", {}).get("content", [{}])
    text = content[0].get("text", "") if content else ""
    try:
        p = json.loads(text)
        return p.get("stdout", text) if isinstance(p, dict) else text
    except:
        return text

TARGET_PORT = 13338

code = f'''
import ida_netnode
n = ida_netnode.netnode("$ ida_mcp.config", 0, True)
old_port = n.altval(0)
old_host = n.supstr(0)
old_persist = n.altval(1)

n.altset(0, {TARGET_PORT})
n.supset(0, "127.0.0.1")
n.altset(1, 2)

print(f"OLD: port={old_port} host={old_host!r} persist={old_persist}")
print(f"NEW: port={n.altval(0)} host={n.supstr(0)!r} persist={n.altval(1)}")
'''

print(f"Setting IDA MCP port to {TARGET_PORT}...")
result = py_eval(code)
print(result)
print()
print("=== 下一步 ===")
print("请在 IDA 中按 Ctrl+Alt+M 停止 MCP server")
print("然后再次按 Ctrl+Alt+M 重新启动")
print(f"重启后 MCP 将绑定到端口 {TARGET_PORT}")
