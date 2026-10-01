#!/usr/bin/env python3
"""cs2_tool_mcp 的真·MCP stdio 冒烟测试。

起一个子进程跑 mcp_server/cs2_mcp_server.py --stdio，走标准 JSON-RPC：
initialize -> notifications/initialized -> tools/list ->（可选）若干 tools/call。

用法：
    python injector/mcp_smoke.py
    python injector/mcp_smoke.py cs2_mesh_get_geometry '{"mesh":"0x5bac7ba0000","max_faces":1}'
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "mcp_server", "cs2_mcp_server.py")
TIMEOUT = 30.0


def main() -> int:
    extra = sys.argv[1:]
    if len(extra) % 2:
        print("用法: mcp_smoke.py [工具名 JSON参数 ...]")
        return 2
    calls = [(extra[i], json.loads(extra[i + 1])) for i in range(0, len(extra), 2)]

    proc = subprocess.Popen(
        [sys.executable, "-u", SERVER, "--stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )
    responses: dict[int, dict] = {}
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and isinstance(msg.get("id"), int):
                responses[msg["id"]] = msg

    def read_stderr() -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            stderr_lines.append(line.rstrip())

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj) + "\n")  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]

    def wait(rid: int) -> dict | None:
        end = time.time() + TIMEOUT
        while time.time() < end:
            if rid in responses:
                return responses.pop(rid)
            if proc.poll() is not None:
                return None
            time.sleep(0.05)
        return None

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "mcp_smoke", "version": "1"}}})
    init = wait(1)
    if not init:
        print("[FAIL] initialize 无响应；stderr:")
        print("\n".join(stderr_lines[-20:]))
        proc.kill()
        return 1
    srv = init["result"]["serverInfo"]
    print("[OK] initialize -> %s %s (protocol %s)"
          % (srv.get("name"), srv.get("version"), init["result"].get("protocolVersion")))

    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    lst = wait(2)
    if not lst:
        print("[FAIL] tools/list 无响应")
        proc.kill()
        return 1
    tools = lst["result"]["tools"]
    names = [t["name"] for t in tools]
    print("[OK] tools/list -> %d 个工具" % len(names))
    mesh_tools = [n for n in names if "mesh" in n]
    print("     mesh 相关: %s" % mesh_tools)
    missing = [n for n, _ in calls if n not in names]
    if missing:
        print("[FAIL] 工具不存在: %s" % missing)

    rid = 3
    for name, args in calls:
        send({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
              "params": {"name": name, "arguments": args}})
        resp = wait(rid)
        rid += 1
        if not resp:
            print("[FAIL] %s 调用无响应" % name)
            continue
        res = resp.get("result", {})
        text = ""
        for item in res.get("content", []):
            if item.get("type") == "text":
                text += item.get("text", "")
        if resp.get("error") or res.get("isError"):
            print("[FAIL] %s -> %s" % (name, resp.get("error") or text[:400]))
            continue
        lines = text.splitlines()
        print("[OK] %s -> %d 行输出:" % (name, len(lines)))
        for line in lines[:14]:
            print("     " + line)
        if len(lines) > 14:
            print("     … 省略 %d 行" % (len(lines) - 14))

    proc.stdin.close()  # type: ignore[union-attr]
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
