#!/usr/bin/env python3
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

code = '''
import ida_netnode
n = ida_netnode.netnode("$ ida_mcp.config", 0, True)
old_port = n.altval(0)
old_host = n.supstr(0) or "None"
old_persist = n.altval(1)

n.altset(0, 13338)
n.supset(0, "127.0.0.1")
n.altset(1, 2)

new_port = n.altval(0)
new_host = n.supstr(0) or "None"
new_persist = n.altval(1)
print("OLD port=%d host=%s persist=%d" % (old_port, old_host, old_persist))
print("NEW port=%d host=%s persist=%d" % (new_port, new_host, new_persist))
'''

r = call("tools/call", {"name": "py_eval", "arguments": {"code": code}})
print("=== RAW RESPONSE ===")
print(json.dumps(r, indent=2))
