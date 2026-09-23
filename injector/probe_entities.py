#!/usr/bin/env python3
"""探测 CMapDoc 的实体字典（CMapDoc+312, CUtlDict<CMapEntity*>）。

用法（在目标机运行，需 cs2_tool.dll 已注入）:
    python probe_entities.py                 # 概览：字典头 + 节点统计
    python probe_entities.py --dump 8        # 额外打印前 8 个节点明细
    python probe_entities.py --doc 0x...     # 手动指定 CMapDoc（默认取文档表第一个）

输出全部为 ASCII，避免远程控制台代码页把中文弄乱。
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vm_pipe import _load_server  # noqa: E402

# CUtlDict 相对 CMapDoc 的偏移（见 REVERSE_NOTES §2.10）
DICT_OFFSET = 312          # 0x138
NODE_STRIDE = 32
NODE_OFF_LEFT = 0x00
NODE_OFF_RIGHT = 0x04
NODE_OFF_KEY = 0x10
NODE_OFF_VALUE = 0x18


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=None, help="CMapDoc 地址（默认取文档表第一个）")
    ap.add_argument("--dump", type=int, default=0, help="额外打印前 N 个节点明细")
    ap.add_argument("--max-nodes", type=int, default=64, help="最多扫描多少节点槽位")
    ap.add_argument("--scan-vt", default=None,
                    help="按 vtable 扫指针：给出 RVA（如 0x161c548 = CMapEntity），"
                         "在对象 [0,size) 内列出 vtable 匹配的指针")
    ap.add_argument("--size", type=lambda x: int(x, 0), default=0x1000,
                    help="--scan-vt / --find-ptr 的扫描字节数")
    ap.add_argument("--find-ptr", default=None,
                    help="在 --doc 指定的对象里搜「值等于该地址」的 qword，"
                         "打印命中偏移（用于反查谁持有某个对象指针）")
    ap.add_argument("--find-ptr2", default=None,
                    help="二级反查：在 --doc 对象里找指针 P，使 *(P) == 该地址。"
                         "用于定位「容器头的 m_pMemory 指向的元素数组」")
    ap.add_argument("--peek", default=None, help="直接打印该地址的原始字节（配合 --size）")
    args = ap.parse_args()

    s = _load_server()
    base = s._hammer_base()

    # 0) 裸读模式
    if args.peek:
        addr = int(args.peek, 0)
        raw = s._read_bytes(addr, args.size)
        print(f"{addr:#x} ({args.size} bytes):")
        print(raw.hex(" "))
        return 0

    # 0a) 二级反查：对象里每个 8 字节对齐的指针 P，检查 *(P) 是否等于目标
    if args.find_ptr2:
        want = int(args.find_ptr2, 0)
        if not args.doc:
            print("--find-ptr2 需要同时给出 --doc <对象地址>")
            return 2
        obj = int(args.doc, 0)
        print(f"object = {obj:#x}  size = {args.size:#x}  want *(P) == {want:#x}")
        raw = s._read_bytes(obj, args.size)
        hits = 0
        for off in range(0, len(raw) - 7, 8):
            p = int.from_bytes(raw[off:off + 8], "little")
            if p < 0x10000 or p >= 0x800000000000:
                continue
            try:
                v = s._read_int(p, "u64")
            except Exception:  # noqa: BLE001
                continue
            if v == want:
                print(f"  +0x{off:04x}: P={p:#x} -> [P] == {want:#x}")
                hits += 1
                if hits >= 40:
                    print("  ... 更多命中已省略")
                    break
        print(f"hits = {hits}")
        return 0

    # 0b) 一级反查：对象里搜「值 == 目标」的 qword
    if args.find_ptr:
        want = int(args.find_ptr, 0)
        if not args.doc:
            print("--find-ptr 需要同时给出 --doc <对象地址>")
            return 2
        obj = int(args.doc, 0)
        print(f"object = {obj:#x}  size = {args.size:#x}  want = {want:#x}")
        raw = s._read_bytes(obj, args.size)
        hits = 0
        for off in range(0, len(raw) - 7, 8):
            p = int.from_bytes(raw[off:off + 8], "little")
            if p == want:
                print(f"  +0x{off:04x}  == {want:#x}")
                hits += 1
        # 未对齐（4 字节步进）也扫一遍，避免漏掉 packed 结构
        for off in range(0, len(raw) - 7, 4):
            p = int.from_bytes(raw[off:off + 8], "little")
            if p == want and off % 8:
                print(f"  +0x{off:04x}  == {want:#x}  (unaligned)")
                hits += 1
        print(f"hits = {hits}")
        return 0

    # 0) 按 vtable 扫指针模式（用于在未知结构里认出某类对象）
    if args.scan_vt:
        want = base + int(args.scan_vt, 0)
        if args.doc:
            obj = int(args.doc, 0)
        else:
            arr = s._read_int(base + s.RVA_MAP_DOC_TABLE, "u64")
            obj = s._read_int(arr, "u64")
        print(f"object = {obj:#x}  size = {args.size:#x}  want_vt = {want:#x}")
        raw = s._read_bytes(obj, args.size)
        hits = 0
        for off in range(0, len(raw) - 7, 8):
            p = int.from_bytes(raw[off:off + 8], "little")
            if p < 0x10000 or p >= 0x800000000000:
                continue
            try:
                if s._read_int(p, "u64") == want:
                    print(f"  +0x{off:04x} -> {p:#x}   (vt matches)")
                    hits += 1
                    if hits >= 40:
                        print("  ... 更多命中已省略")
                        break
            except Exception:  # noqa: BLE001
                continue
        print(f"hits = {hits}")
        return 0

    # 1) 定位 CMapDoc
    if args.doc:
        doc = int(args.doc, 0)
    else:
        count = s._read_int(base + s.RVA_MAP_DOC_COUNT, "u32")
        print(f"doc_count = {count}")
        if count == 0:
            print("NO_DOC")
            return 1
        arr = s._read_int(base + s.RVA_MAP_DOC_TABLE, "u64")
        doc = s._read_int(arr, "u64")
    print(f"CMapDoc   = {doc:#x}")

    # 2) 字典头
    d = doc + DICT_OFFSET
    n_count = s._read_int(d + 0x08, "u32")
    n_flags = s._read_int(d + 0x0C, "u32")
    p_elems = s._read_int(d + 0x10, "u64")
    n_root = s._read_int(d + 0x18, "u32")
    print(f"dict@{d:#x}: count={n_count} flags={n_flags:#x} "
          f"elems={p_elems:#x} root={n_root}")
    elems_base = p_elems if (n_flags & 0x7FFFFFFF) else 0
    print(f"elems_base = {elems_base:#x}")

    if n_count <= 0 or elems_base == 0:
        print("DICT_EMPTY")
        return 0

    # 3) 扫描节点槽位
    scan = min(n_count, args.max_nodes)
    print(f"\n--- scanning {scan} node slots ---")
    live = 0
    for i in range(scan):
        node = elems_base + i * NODE_STRIDE
        left = s._read_int(node + NODE_OFF_LEFT, "u32")
        right = s._read_int(node + NODE_OFF_RIGHT, "u32")
        kp = s._read_int(node + NODE_OFF_KEY, "u64")
        vp = s._read_int(node + NODE_OFF_VALUE, "u64")
        name = ""
        if kp:
            try:
                name = s._read_string(kp, 96)
            except Exception:  # noqa: BLE001
                name = "<unreadable>"
        vt = ""
        if vp:
            try:
                v = s._read_int(vp, "u64")
                if v > base:
                    vt = f"vt=+{v - base:#x}"
            except Exception:  # noqa: BLE001
                vt = "vt=?"
        if kp or vp:
            live += 1
        if args.dump and i < args.dump:
            print(f"  [{i:3}] L={left:5} R={right:5} key={kp:#018x} "
                  f"val={vp:#018x} {vt} name={name!r}")
    print(f"live slots (key or value nonzero) = {live} / {scan}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
