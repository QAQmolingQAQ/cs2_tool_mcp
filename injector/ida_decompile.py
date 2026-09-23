#!/usr/bin/env python3
"""Direct IDA MCP client for decompiling CHammerApp vtable functions."""
import urllib.request, json, sys

BASE = "http://127.0.0.1:13337"
session_id = None
msg_id = 0

def call(method, params):
    global msg_id, session_id
    msg_id += 1
    payload = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
    req = urllib.request.Request(BASE + "/mcp",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 **({"Mcp-Session-Id": session_id} if session_id else {})})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        sid = resp.headers.get("Mcp-Session-Id")
        if sid: session_id = sid
        data = json.loads(resp.read().decode())
        return data.get("result"), data.get("error")
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return None, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, str(e)

print("=== Initialize ===")
r, e = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0.1"}})
print(f"OK: {r['serverInfo']['name']} v{r['serverInfo']['version']}, session={session_id}")

print("\n=== server_health ===")
r, e = call("tools/call", {"name": "server_health", "arguments": {}})
if r:
    c = json.loads(r["content"][0]["text"]) if "content" in r else {}
    print(json.dumps(c, indent=2))

# Vtable RVAs from our live test
vtable_rvas = {
    0: 0x117940, 1: 0x118670, 2: 0x1364c20, 3: 0x1364be0, 4: 0x1363dc0,
    5: 0x753a0, 6: 0x1156a0, 7: 0xe7e50, 8: 0x11f450, 9: 0xa12e0,
    10: 0xa3f10, 11: 0x1360690, 12: 0x11f400, 13: 0x1363e60, 14: 0x135f940,
}

imagebase = 0x180000000  # hammer.dll default imagebase

for idx, rva in sorted(vtable_rvas.items()):
    addr = f"0x{imagebase + rva:x}"
    print(f"\n{'='*60}")
    print(f"vtable[{idx}] addr={addr} (RVA 0x{rva:x})")

    r, e = call("tools/call", {"name": "lookup_funcs", "arguments": {"queries": addr}})
    if r and "content" in r:
        txt = r["content"][0]["text"]
        try:
            func_info = json.loads(txt)
            fn = func_info["result"][0].get("fn")
            if fn:
                print(f"  Function: {fn['name']}  size={fn['size']}")
            else:
                print(f"  No function found at this address")
                continue
        except:
            print(f"  parse err: {txt[:200]}")
            continue

    # Decompile
    r, e = call("tools/call", {"name": "decompile", "arguments": {"addr": addr}})
    if r and "content" in r:
        text = r["content"][0]["text"]
        print(f"{'─'*40}")
        print(text[:1200])
    else:
        print(f"  Decompile error: {e}")

print("\n\n=== DONE ===")
