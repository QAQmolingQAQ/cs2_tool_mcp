#!/usr/bin/env python3
"""Correctly parse IDA MCP responses and decompile CHammerApp vtable."""
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
        resp = urllib.request.urlopen(req, timeout=60)
        sid = resp.headers.get("Mcp-Session-Id")
        if sid: session_id = sid
        return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return None, str(e)

print("=== Initialize ===")
r, e = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0.1"}})
print(f"  OK, session={session_id}")

def mcp_tool(name, arguments):
    """Call an IDA MCP tool and return parsed result text."""
    r, e = call("tools/call", {"name": name, "arguments": arguments})
    if not r:
        return None, e
    result = r.get("result", {})
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        return content[0]["text"], None
    return result, None

# Vtable RVAs (skip duplicates and non-functions)
vtable_rvas = {
    0: 0x117940, 1: 0x118670, 2: 0x1364c20, 3: 0x1364be0, 4: 0x1363dc0,
    8: 0x11f450, 11: 0x1360690, 12: 0x11f400, 13: 0x1363e60, 14: 0x135f940,
}

imagebase = 0x180000000

for idx, rva in sorted(vtable_rvas.items()):
    addr = f"0x{imagebase + rva:x}"
    print(f"\n{'='*70}")
    print(f"vtable[{idx}] {addr} (RVA 0x{rva:x})")

    # Decompile
    text, err = mcp_tool("decompile", {"addr": addr})
    if err:
        print(f"  Decompile ERROR: {err}")
        continue

    # Output first 2000 chars
    print(f"{'─'*50}")
    print(text[:2500])
    if len(text) > 2500:
        print(f"\n... (truncated, total {len(text)} chars)")

print("\n\n=== DONE ===")
