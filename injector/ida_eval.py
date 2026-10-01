#!/usr/bin/env python3
"""向 IDA Pro MCP 的 py_eval 发送 Python 代码（从 stdin 读取，避开 shell JSON 转义）。

用法:
    type code.py | python ida_eval.py 13337
    "print(1+1)" | python ida_eval.py 13337
    python ida_eval.py 13337 --exec code.py      # 改用 py_exec_file 思路（本地读文件后整体发送）
"""
from __future__ import annotations

import json
import sys
import urllib.request


def call(port: int, tool: str, args: dict, timeout: float = 120.0) -> dict:
    data = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    port = int(sys.argv[1])
    if len(sys.argv) >= 3 and sys.argv[2] == "--exec":
        with open(sys.argv[3], "r", encoding="utf-8") as f:
            code = f.read()
    else:
        code = sys.stdin.read()
    # 去掉可能的 UTF-8 BOM（Windows 管道/文件常见），否则 IDA 侧 ast.parse 会报错
    code = code.lstrip("\ufeff")
    r = call(port, "py_eval", {"code": code})
    if "error" in r:
        print(json.dumps(r["error"], indent=2, ensure_ascii=False))
        return 1
    for item in r.get("result", {}).get("content", []):
        if item.get("type") == "text":
            print(item.get("text", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
