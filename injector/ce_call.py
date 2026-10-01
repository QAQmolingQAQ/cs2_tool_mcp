#!/usr/bin/env python3
"""直连 Cheat Engine MCP Bridge（TCP）的调用助手。

协议（见 cheatengine-mcp-tcp-bridge MCP_Server/mcp_cheatengine.py）：
    请求 = <I 长度前缀> + JSON-RPC 2.0 {"jsonrpc","method","params","id"}
    响应 = <I 长度前缀> + JSON

这样无需重启 Trae 即可直接控制 VM 里的 CE。

用法:
    python ce_call.py ping
    python ce_call.py get_process_list
    python ce_call.py open_process '{"pid":1234}'
    python ce_call.py read_memory '{"address":"0x7ff...","size":8}'
    python ce_call.py --host <CE 所在机器 IP> --port 17171 ping

环境变量: CE_HOST（必填）/ CE_PORT（默认 17171）
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import sys
import time

DEFAULT_HOST = os.environ.get("CE_HOST", "")
DEFAULT_PORT = int(os.environ.get("CE_PORT", "17171"))
MAX_RESPONSE = 32 * 1024 * 1024


def ce_call(method: str, params: dict | None = None,
            host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
            timeout: float = 90.0) -> dict:
    """发送一个 JSON-RPC 请求到 CE bridge，返回 result（或 error dict）。"""
    if not host:
        return {"error": "未指定 CE 所在机器：请设置环境变量 CE_HOST 或加 --host 参数"}
    request = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": int(time.time() * 1000),
    }
    payload = json.dumps(request).encode("utf-8")
    frame = struct.pack("<I", len(payload)) + payload

    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(frame)

        def recv_exact(n: int) -> bytes:
            buf = bytearray()
            while len(buf) < n:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("CE bridge closed the connection")
                buf.extend(chunk)
            return bytes(buf)

        resp_len = struct.unpack("<I", recv_exact(4))[0]
        if resp_len > MAX_RESPONSE:
            raise ConnectionError(f"Response too large: {resp_len} bytes")
        body = recv_exact(resp_len)

    resp = json.loads(body.decode("utf-8"))
    if "error" in resp:
        return {"success": False, "error": resp["error"]}
    return resp.get("result", resp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("method", help="CE bridge 方法名，如 ping / get_process_list")
    ap.add_argument("params", nargs="?", default=None, help="JSON 参数对象（可选）")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--raw", action="store_true", help="原样打印 JSON")
    args = ap.parse_args()

    params = json.loads(args.params) if args.params else {}

    try:
        result = ce_call(args.method, params, args.host, args.port, args.timeout)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR {type(e).__name__}: {e}")
        return 1

    if args.raw:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    sys.exit(main())
