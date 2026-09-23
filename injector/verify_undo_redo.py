#!/usr/bin/env python3
"""撤销/重做 端到端验证。

走的是 MCP 的真实工具实现（cs2_mcp_server.cs2_undo / cs2_redo），而非重写逻辑。

流程:
  1. 轮询等待 undo 栈出现内容（你在 Hammer 里做一次编辑：画笔刷 / 放实体 / 改贴图）
  2. 记录基线 -> 调用 cs2_undo -> 校验 undo 减少、redo 增加
  3. 调用 cs2_redo -> 校验恢复到基线

用法:
    python verify_undo_redo.py               # 等待最多 180s 让你做编辑
    python verify_undo_redo.py --wait 300    # 延长等待
    python verify_undo_redo.py --no-wait     # 不等待，直接按当前状态验证
    python verify_undo_redo.py --plain       # 走 CUndoManager::Undo 本体（默认走包装）
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))
import cs2_mcp_server as m  # noqa: E402


def counts() -> tuple[int, int]:
    """返回 (undo.count, redo.count)。"""
    base = m._hammer_base()
    um = base + m.RVA_CDATAMODEL_GLOBAL + m.UNDO_MANAGER_OFFSET
    return m._read_int(um, "u32"), m._read_int(um + 16, "u32")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=180, help="等待编辑出现的秒数，默认 180")
    ap.add_argument("--no-wait", action="store_true", help="不等待，直接验证当前状态")
    ap.add_argument("--plain", action="store_true", help="调用 CUndoManager 本体而非 CDataModel 包装")
    args = ap.parse_args()

    try:
        u0, r0 = counts()
    except ConnectionError as e:
        print(f"[FAIL] 管道未连接: {e}")
        print("       请先运行 injector/inject_dll.py 注入 cs2_tool.dll。")
        return 2

    print(f"基线: undo={u0} redo={r0}")

    if u0 == 0 and not args.no_wait:
        print(f"\n请在 Hammer 里做一次编辑（画笔刷 / 放实体 / 改材质），最多等待 {args.wait}s ...")
        deadline = time.time() + args.wait
        while time.time() < deadline:
            time.sleep(1.5)
            try:
                u, r = counts()
            except Exception as e:  # noqa: BLE001
                print(f"  读取失败: {e}")
                continue
            if u > 0:
                u0, r0 = u, r
                print(f"  检测到编辑: undo={u0} redo={r0}")
                break
        else:
            print("\n[SKIP] 超时，仍未检测到编辑历史。")
            print("       请在 Hammer 中执行一次编辑后重跑本脚本。")
            return 3

    if u0 == 0:
        print("\n[SKIP] 当前 undo 栈为空，无法验证撤销。")
        return 3

    use_wrapper = not args.plain
    print(f"\n--- 调用 cs2_undo (wrapper={use_wrapper}) ---")
    print(m.cs2_undo(use_wrapper))
    u1, r1 = counts()
    print(f"实测: undo={u1} redo={r1}")

    print(f"\n--- 调用 cs2_redo (wrapper={use_wrapper}) ---")
    print(m.cs2_redo(use_wrapper))
    u2, r2 = counts()
    print(f"实测: undo={u2} redo={r2}")

    ok_undo = u1 < u0 and r1 > r0
    ok_redo = u2 >= u1 and r2 <= r1
    print("\n" + "=" * 46)
    print(f"undo 生效 (undo {u0}->{u1}, redo {r0}->{r1}) : {'PASS' if ok_undo else 'FAIL'}")
    print(f"redo 生效 (undo {u1}->{u2}, redo {r1}->{r2}) : {'PASS' if ok_redo else 'FAIL'}")
    print("=" * 46)
    return 0 if (ok_undo and ok_redo) else 1


if __name__ == "__main__":
    sys.exit(main())
