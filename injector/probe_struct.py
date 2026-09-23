#!/usr/bin/env python3
"""在未知结构里按「计数值 + 相邻指针」特征定位数组/栈（如撤销栈）。

对每个 8 字节对齐偏移 off，检查：
  * u32(off) 落在 [min, max] 范围内
  * qword(off+8) 是一个可读指针（指向已提交内存）
两者同时成立时打印，便于快速定位 CUtlVector / 栈结构。

用法:
    python probe_struct.py --base 0xc9cf072d00 --size 0x400
    python probe_struct.py --base 0xc9cf072d00 --value 7      # 只看计数等于 7 的
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))
from cs2_mcp_server import Cs2Pipe  # noqa: E402


class Pr:
    def __init__(self, pipe: Cs2Pipe):
        self.p = pipe
        self.modules: list[tuple[int, int, str]] = []

    def call(self, method, params=None):
        resp = self.p.call(method, params)
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error']}")
        return resp["result"]

    def load_modules(self):
        for m in self.call("list_modules"):
            b = int(m["base_hex"], 16)
            self.modules.append((b, b + m["size"], m["name"]))
        self.modules.sort()

    def owner(self, addr):
        for b, e, n in self.modules:
            if b <= addr < e:
                return n, addr - b
        return None

    def read(self, addr, size):
        out = bytearray()
        while size > 0:
            n = min(size, 1024)
            h = self.call("read_memory", {"address": addr + len(out), "size": n})["hex"]
            out += bytes.fromhex(h[2:])
            size -= n
        return bytes(out)

    def try_qword(self, addr):
        resp = self.p.call("read_value", {"address": addr, "type": "u64"})
        if "error" in resp:
            return None
        return int(resp["result"]["value_hex"], 16)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="结构起始地址（十六进制）")
    ap.add_argument("--size", default="0x400", help="扫描字节数，默认 0x400")
    ap.add_argument("--min", type=int, default=1, help="计数值下限，默认 1")
    ap.add_argument("--max", type=int, default=100000, help="计数值上限，默认 100000")
    ap.add_argument("--value", type=int, default=None, help="只显示等于该值的计数")
    ap.add_argument("--pipe", default=None)
    args = ap.parse_args()

    pipe = Cs2Pipe(args.pipe) if args.pipe else Cs2Pipe()
    pr = Pr(pipe)
    pr.load_modules()

    base = int(args.base, 0)
    size = int(args.size, 0)
    print(f"结构: {base:#x} .. {base+size:#x}")
    print("-" * 74)

    block = pr.read(base, size)
    n_hits = 0
    for off in range(0, len(block) - 15, 8):
        cnt = int.from_bytes(block[off:off + 4], "little")
        if not (args.min <= cnt <= args.max):
            continue
        if args.value is not None and cnt != args.value:
            continue
        ptr = int.from_bytes(block[off + 8:off + 16], "little")
        if ptr < 0x10000 or ptr >= 0x8000_0000_0000:
            continue
        own = pr.owner(ptr)
        if own:
            desc = f"module {own[0]}+{own[1]:#x}"
        else:
            peek = pr.try_qword(ptr)
            desc = f"heap, *ptr={peek:#x}" if peek is not None else "unreadable"
        print(f"  +{off:#06x}  count={cnt:<8} ptr={ptr:#014x}  ({desc})")
        n_hits += 1

    print("-" * 74)
    print(f"命中 {n_hits} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
