#!/usr/bin/env python3
"""CUndoManager 探测 / 撤销重做。

关键逆向结论（见 REVERSE_NOTES.md §2.7/2.8）：
  * CDataModel 全局单例 = hammer.dll + 0x2344140   （静态初始化 sub_18004F500）
  * CUndoManager 内嵌在 CDataModel + 240
  * CUndoManager::Undo    = hammer.dll + 0x50B720
  * CUndoManager::Redo    = hammer.dll + 0x50B290
  * CDataModel::Undo/Redo = hammer.dll + 0x4C0B60 / 0x4BEBE0 （会额外通知刷新）

CUndoManager 布局 (int* 视角):
  +0  undo.count   +8  undo.stack
  +16 redo.count   +24 redo.stack

用法:
    python probe_undo.py              # 只查看计数
    python probe_undo.py --undo       # 执行一次撤销
    python probe_undo.py --redo       # 执行一次重做
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))
from cs2_mcp_server import Cs2Pipe  # noqa: E402

# RVA 常量（相对 hammer.dll imagebase）
RVA_CDATAMODEL_GLOBAL = 0x2344140
RVA_UNDO_MANAGER_OFFSET = 240
RVA_UNDO = 0x50B720
RVA_REDO = 0x50B290
RVA_CDATAMODEL_UNDO = 0x4C0B60
RVA_CDATAMODEL_REDO = 0x4BEBE0
RVA_CDATAMODEL_VTABLE = 0x1587B90


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--undo", action="store_true", help="执行一次撤销")
    ap.add_argument("--redo", action="store_true", help="执行一次重做")
    ap.add_argument("--use-wrapped", action="store_true",
                    help="走 CDataModel::Undo/Redo 包装（会额外通知刷新）")
    ap.add_argument("--pipe", default=None)
    args = ap.parse_args()

    pipe = Cs2Pipe(args.pipe) if args.pipe else Cs2Pipe()

    def r(method, params=None):
        resp = pipe.call(method, params)
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error']}")
        return resp["result"]

    base = int(r("get_module", {"name": "hammer"})["base_hex"], 16)
    dm = base + RVA_CDATAMODEL_GLOBAL
    um = dm + RVA_UNDO_MANAGER_OFFSET

    vt = int(r("read_value", {"address": dm, "type": "u64"})["value_hex"], 16)
    expect = base + RVA_CDATAMODEL_VTABLE
    print(f"hammer.dll    : {base:#x}")
    print(f"g_CDataModel  : {dm:#x}")
    print(f"  vtable      : {vt:#x}  (expect {expect:#x})  {'OK' if vt == expect else 'MISMATCH!'}")
    print(f"CUndoManager  : {um:#x}")

    def count(off):
        return r("read_value", {"address": um + off, "type": "u32"})["value"]

    def stack(off):
        return int(r("read_value", {"address": um + off, "type": "u64"})["value_hex"], 16)

    print(f"  undo.count  : {count(0)}   stack={stack(8):#x}")
    print(f"  redo.count  : {count(16)}  stack={stack(24):#x}")

    if args.undo or args.redo:
        action = "redo" if args.redo else "undo"
        if args.use_wrapped:
            fn_rva = RVA_CDATAMODEL_REDO if args.redo else RVA_CDATAMODEL_UNDO
            this = dm
        else:
            fn_rva = RVA_REDO if args.redo else RVA_UNDO
            this = um
        print(f"\n调用 {action}: fn=hammer.dll+{fn_rva:#x} this={this:#x}")
        ret = r("call_function", {"address": f"hammer.dll+{fn_rva:#x}", "args": [this]})
        print(f"  ret        : {ret['ret_hex']}")
        print(f"  undo.count : {count(0)}")
        print(f"  redo.count : {count(16)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
