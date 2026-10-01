#!/usr/bin/env python3
"""钉死 DMX binary 头部布局：打印前若干字节 + 按 NUL 切出的头几条字符串。"""
from __future__ import annotations

from pathlib import Path

MAP = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive"
    r"\content\csgo_addons\ze_surf_nannoimi\maps\ze_surf_nannoimi.vmap")


def main() -> int:
    d = MAP.read_bytes()
    nl = d.index(b"\n")
    print(f"header = {d[:nl].decode()!r}  (len={nl}, 换行在 {nl})")
    print("紧随其后的 24 字节:")
    for i in range(nl + 1, nl + 25, 16):
        chunk = d[i:i + 16]
        print(f"  {i:#06x}: {' '.join('%02x' % b for b in chunk)}")
        print(f"          {''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)}")

    pos = nl + 1
    print(f"\n从 {pos:#x} 起按 NUL 切串（前 25 条）:")
    end = pos + 600
    parts = d[pos:end].split(b"\x00")
    off = pos
    for j, p in enumerate(parts[:25]):
        show = p.decode("utf-8", "replace")
        print(f"  [{j:2d}] @{off:#08x} len={len(p)} {show!r}")
        off += len(p) + 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
