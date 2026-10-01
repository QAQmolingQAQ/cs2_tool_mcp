#!/usr/bin/env python3
"""从 DMX binary v9 的 .vmap 里把所有可打印字符串抽出来（含偏移），便于检索实体/键值。

DMX binary 的字符串表是一段连续的 NUL 结尾串，直接按可打印游程抽取即可，
不做结构解析（结构解析另说）。
"""
from __future__ import annotations

import sys
from pathlib import Path

MAP = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive"
    r"\content\csgo_addons\ze_surf_nannoimi\maps\ze_surf_nannoimi.vmap"
)
OUT = Path(r"c:\cs2_tool_mcp\_vmap_out\ze_surf_nannoimi.strings.txt")


def main() -> int:
    data = MAP.read_bytes()
    out = []
    cur = bytearray()
    start = 0
    for i, b in enumerate(data):
        if 0x20 <= b <= 0x7E:
            if not cur:
                start = i
            cur.append(b)
        else:
            if len(cur) >= 2:
                out.append(f"{start}\t{cur.decode('ascii')}")
            cur.clear()
    if len(cur) >= 2:
        out.append(f"{start}\t{cur.decode('ascii')}")
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"strings={len(out)} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
