#!/usr/bin/env python3
"""扫描对象实例的成员指针，按 vtable 归属归类，用于定位子对象。

用途：找到 CDataModel（vtable = hammer.dll+0x1587B90），其内嵌 CUndoManager@+240，
      从而为 undo/redo 工具铺路。

用法:
    python probe_mapdoc.py                          # 扫描第一个 CMapDoc 的前 0x1000 字节
    python probe_mapdoc.py --size 0x3000            # 扩大扫描范围
    python probe_mapdoc.py --index 0                # 指定第几个文档
    python probe_mapdoc.py --base 0xc9cf0c0480      # 直接扫描任意对象地址
    python probe_mapdoc.py --base 0x... --vt 0x1587B90   # 高亮目标 vtable (RVA)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))
from cs2_mcp_server import Cs2Pipe  # noqa: E402

# 已知 vtable RVA（相对 hammer.dll imagebase）
KNOWN_VTABLES = {
    0x1628878: "CMapDoc::vftable",
    0x16288B8: "CMapDoc::vftable_0",
    0x16288D8: "CMapDoc::vftable_1",
    0x1587B90: "CDataModel::vftable  <== 目标 (CUndoManager@+240)",
    0x1628508: "CMapDocHistory::vftable",
    0x1628550: "CMapRootElement::vftable",
    0x1629BE0: "CSelection::vftable",
    0x16B0D80: "CDetailPropObjectManager::vftable",
    0x1614EB0: "CParticleSystemQueryHammerMapDoc::vftable",
    0x16B0E48: "CParticlesLibHost_MapDocLib::vftable",
    0x1CB60B0: "CHammerEditorSession::vftable",
}


class Probe:
    def __init__(self, pipe: Cs2Pipe):
        self.p = pipe
        self.modules: list[tuple[int, int, str]] = []

    def call(self, method: str, params=None):
        resp = self.p.call(method, params)
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error']}")
        return resp["result"]

    def load_modules(self) -> None:
        for m in self.call("list_modules"):
            base = int(m["base_hex"], 16)
            self.modules.append((base, base + m["size"], m["name"]))
        self.modules.sort()

    def owner(self, addr: int) -> tuple[str, int] | None:
        """返回 (模块名, RVA)，若地址不属于任何已知模块则返回 None。"""
        for base, end, name in self.modules:
            if base <= addr < end:
                return name, addr - base
        return None

    def read(self, addr: int, size: int) -> bytes:
        # 注意：read_memory 的 DLL 侧目前用 GetInt 解析地址（不支持字符串表达式），
        # 因此这里必须传整数地址。read_value 已走 GetAddressParam，两者都可。
        out = bytearray()
        while size > 0:
            n = min(size, 1024)
            hexstr = self.call("read_memory", {"address": addr + len(out), "size": n})["hex"]
            out += bytes.fromhex(hexstr[2:])
            size -= n
        return bytes(out)

    def qword(self, addr: int) -> int:
        return int(self.call("read_value", {"address": addr, "type": "u64"})["value_hex"], 16)

    def try_qword(self, addr: int) -> int | None:
        """读取失败（不可读地址）时返回 None，不抛异常。"""
        resp = self.p.call("read_value", {"address": addr, "type": "u64"})
        if "error" in resp:
            return None
        return int(resp["result"]["value_hex"], 16)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="0x1000", help="扫描字节数，默认 0x1000")
    ap.add_argument("--index", type=int, default=0, help="文档序号，默认 0")
    ap.add_argument("--base", default=None, help="直接扫描该对象地址（十六进制），绕过 CMapDoc")
    ap.add_argument("--vt", default=None, help="高亮目标 vtable 的 RVA（如 0x1587B90）")
    ap.add_argument("--pipe", default=None)
    args = ap.parse_args()

    pipe = Cs2Pipe(args.pipe) if args.pipe else Cs2Pipe()
    pr = Probe(pipe)
    pr.load_modules()

    if args.base:
        obj = int(args.base, 0)
        title = "对象"
    else:
        docs = pr.call("map_list_docs")
        if not docs["docs"]:
            print("没有打开的 CMapDoc 文档")
            return 1
        obj = int(docs["docs"][args.index]["address"], 16)
        title = "CMapDoc"

    size = int(args.size, 0)
    print(f"{title:<13}: {hex(obj)}")
    print(f"vtable       : {hex(pr.qword(obj))}")
    print(f"扫描范围     : {hex(obj)} .. {hex(obj + size)}")
    print("-" * 78)

    target_rva = int(args.vt, 0) if args.vt else None
    if target_rva is not None:
        KNOWN_VTABLES.setdefault(target_rva, "*** 目标 vtable ***")

    block = pr.read(obj, size)

    hits: list[tuple[int, int, int, str, int]] = []
    seen: set[int] = set()
    for off in range(0, len(block) - 7, 8):
        cand = int.from_bytes(block[off:off + 8], "little")
        if cand < 0x10000 or cand >= 0x8000_0000_0000:
            continue
        if cand in seen:
            continue
        seen.add(cand)
        vt = pr.try_qword(cand)
        if vt is None:
            continue
        own = pr.owner(vt)
        if own is None:
            continue
        mod, rva = own
        hits.append((off, cand, vt, mod, rva))
        label = KNOWN_VTABLES.get(rva, "")
        if label:
            print(f"  +{off:#06x}  obj={cand:#014x}  vt={mod}+{rva:#x}  <== {label}")

    print("-" * 78)
    print(f"共找到 {len(hits)} 个成员指针指向某模块内的 vtable")
    for off, cand, vt, mod, rva in hits:
        if KNOWN_VTABLES.get(rva):
            continue
        print(f"  +{off:#06x}  obj={cand:#014x}  vt={mod}+{rva:#x}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
