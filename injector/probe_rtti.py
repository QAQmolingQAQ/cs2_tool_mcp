#!/usr/bin/env python3
"""通过 relative-RTTI 在运行时解析对象每个成员指针的类名。

用法:
    python probe_rtti.py <obj_addr> [scan_size]
    python probe_rtti.py vptr <vptr_addr>      # 只解析一个 vtable 的类名

新版 hammer.dll 的 vtable 布局:
    vtable[-1] (qword) -> RTTI record; record+0xc (dword) = type_descriptor 的 RVA;
    type_descriptor+0x10 = ".?AVClassName@@" 字符串。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))
from cs2_mcp_server import Cs2Pipe  # noqa: E402


class Rtti:
    def __init__(self, pipe: Cs2Pipe):
        self.p = pipe

    def call(self, method: str, params=None):
        r = self.p.call(method, params)
        if "error" in r:
            raise RuntimeError(f"{method}: {r['error']}")
        return r["result"]

    def setup(self):
        m = {x["name"]: x for x in self.call("list_modules")}["hammer.dll"]
        self.base = int(m["base_hex"], 16)
        self.end = self.base + m["size"]

    def qw(self, addr: int) -> int:
        return int(self.call("read_value", {"address": addr, "type": "u64"})["value_hex"], 16)

    def dw(self, addr: int) -> int:
        return int(self.call("read_value", {"address": addr, "type": "u32"})["value_hex"], 16)

    def read(self, addr: int, size: int) -> bytes:
        out = bytearray()
        while len(out) < size:
            try:
                r = self.call("read_memory", {"address": addr + len(out),
                                              "size": min(size - len(out), 1024)})
            except Exception:
                out += b"\x00" * min(size - len(out), 1024)
                continue
            out += bytes.fromhex(r["hex"][2:])
        return bytes(out)

    def cstr(self, addr: int, n: int = 96) -> str:
        try:
            return self.call("read_string", {"address": addr, "max_len": n})["value"]
        except Exception:
            return ""

    def vptr_class(self, vptr: int) -> str | None:
        if not (self.base <= vptr < self.end):
            return None
        try:
            rec = self.qw(vptr - 8)
            if not (self.base <= rec < self.end):
                return None
            td_rva = self.dw(rec + 0xC)
            if not (0 < td_rva < 0x7000000):
                return None
            name = self.cstr(self.base + td_rva + 0x10)
        except Exception:
            return None
        if name.startswith(".?AV"):
            return name[4:].split("@@")[0]
        return None

    def obj_class(self, obj: int) -> str | None:
        if not (0x10000 < obj < 0x7FFFFFFFFFFF):
            return None
        try:
            return self.vptr_class(self.qw(obj))
        except Exception:
            return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    r = Rtti(Cs2Pipe())
    r.setup()

    if sys.argv[1] == "vptr":
        vptr = int(sys.argv[2], 0)
        print(hex(vptr), "->", r.vptr_class(vptr))
        return 0

    obj = int(sys.argv[1], 0)
    size = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x1500
    own = r.obj_class(obj)
    print(f"对象 {obj:#x} 类名 = {own}")
    block = r.read(obj, size)
    print(f"扫描 0..{size:#x}")
    print("-" * 78)
    cache: dict[int, str | None] = {}
    for off in range(0, len(block) - 7, 8):
        v = struct.unpack_from("<Q", block, off)[0]
        if not (0x10000 < v < 0x7FFFFFFFFFFF):
            continue
        # v 是成员对象指针：先取其首 8 字节 vptr，再走 RTTI 链
        if v in cache:
            cls = cache[v]
        else:
            cls = r.obj_class(v)
            cache[v] = cls
        if cls:
            print(f"  +{off:#06x}  ptr={v:#014x}  class={cls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
