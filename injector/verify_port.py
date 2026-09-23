#!/usr/bin/env python3
"""Verify new IDA MCP port after restart."""
import urllib.request, json, sys, time

# Try both old and new ports
for port in [13338, 13337]:
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "verify", "version": "0.1"}}
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=3)
        data = json.loads(resp.read().decode())
        server_name = data.get("result", {}).get("serverInfo", {}).get("name", "unknown")
        print(f"✅ Port {port}: OK ({server_name})")
    except Exception as e:
        err_msg = str(e)
        if "Connection refused" in err_msg or "Errno 111" in err_msg:
            print(f"❌ Port {port}: not listening")
        else:
            print(f"❌ Port {port}: {err_msg[:60]}")
