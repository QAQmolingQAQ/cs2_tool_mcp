#!/usr/bin/env python3
"""Use IDA MCP py_eval to change the persisted port."""
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
    resp = urllib.request.urlopen(req, timeout=30)
    sid = resp.headers.get("Mcp-Session-Id")
    if sid: session_id = sid
    return json.loads(resp.read().decode())

def py_eval(code):
    r = call("tools/call", {"name": "py_eval", "arguments": {"code": code}})
    content = r.get("result", {}).get("content", [{}])
    text = content[0].get("text", "") if content else ""
    try:
        parsed = json.loads(text)
        return parsed.get("stdout", text) if isinstance(parsed, dict) else text
    except:
        return text

TARGET_PORT = 13338

print(f"=== Step 1: Read current netnode ===")
print(py_eval('''
import ida_netnode
n = ida_netnode.netnode("$ ida_mcp.config")
print(f"port={n.altval(0)} host={n.supstr(0)!r} persist={n.altval(1)}")
'''))

print(f"\n=== Step 2: Write port={TARGET_PORT} ===")
print(py_eval(f'''
import ida_netnode
n = ida_netnode.netnode("$ ida_mcp.config", 0, True)
n.altset(0, {TARGET_PORT})   # _ALT_PORT
n.supset(0, "127.0.0.1")     # _SUP_HOST
n.altset(1, 2)              # _ALT_PERSIST = on
print(f"SAVED: port={n.altval(0)} host={n.supstr(0)!r} persist={n.altval(1)}")
'''))

print(f"\n=== Step 3: Verify ===")
print(py_eval('''
import ida_netnode
n = ida_netnode.netnode("$ ida_mcp.config")
print(f"VERIFY: port={n.altval(0)} host={n.supstr(0)!r} persist={n.altval(1)}")
'''))

print(f"\n=== DONE ===")
print(f"已将 IDA MCP 持久化端口设置为 {TARGET_PORT}")
print(f"下一步：在 IDA 中按 Ctrl+Alt+M 停止 MCP，再按一次 Ctrl+Alt+M 重新启动")
print(f"重启后 MCP server 将绑定到新端口 {TARGET_PORT}")
