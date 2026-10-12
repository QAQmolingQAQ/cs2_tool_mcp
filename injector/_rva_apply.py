#!/usr/bin/env python3
"""按 `_rva_diff.py` 的体检结果，把 RVA 表批量搬到新版 hammer.dll。

表里的 (旧, 新) 全部来自 `_rva_diff.py` 的「片段/滑窗唯一定位」，
且每条都过了入口旁证（16 字节对齐 + 入口前 0xCC/0x90 填充）。
未列入表的一律不动：
  · 8 个虚表 + 3 个 polymesh 虚表 —— 实测位置没变（Δ0）；
  · 5 个数据全局（CDATAMODEL_GLOBAL / PTR_GLOBAL / HISTORY_GATE /
    BIND_TARGET_LIST / CHAMMERAPP）—— 在 .data 里，文件内容无参考价值，
    留旧值，靠活体校验暴露问题后再反查。

用法： python injector/_rva_apply.py [--dry]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "mcp_server" / "hammer_mcp" / "offsets.py"
BRIDGE = REPO / "injected_dll" / "hammer_bridge.cpp"

# (常量名, 旧, 新)
SERVER_RVAS = [
    ("RVA_CDATAMODEL_UNDO",            0x5C3160,  0x5C34A0),
    ("RVA_CDATAMODEL_REDO",            0x5C11E0,  0x5C1520),
    ("RVA_UNDO_MANAGER_UNDO",          0x60F8D0,  0x60FC10),
    ("RVA_UNDO_MANAGER_REDO",          0x60F440,  0x60F780),
    ("RVA_MAP_HISTORY_POP",            0x1529E80, 0x152A490),
    ("RVA_MAP_HISTORY_PUSH_STEP",      0x1529290, 0x15298A0),
    ("RVA_MAP_HISTORY_REC_ADDED",      0x15290B0, 0x15296C0),
    ("RVA_MAP_HISTORY_REC_REMOVED",    0x1528EC0, 0x15294D0),
    ("RVA_MAP_HISTORY_NOTIFY",         0x1529700, 0x1529D10),
    ("RVA_HIST_RECORD_NODE",           0x86D9B0,  0x86DCF0),
    ("RVA_ELEMENT_MARK_DIRTY",         0x5C81C0,  0x5C8500),
    ("RVA_ATTR_SET_SYMBOL",            0x5CF020,  0x5CF360),
    ("RVA_PROPS_SET_STRING_ATTR",      0x62C9A0,  0x62CCE0),
    ("RVA_PROPS_FIND_ATTR",            0x5C7170,  0x5C74B0),
    ("RVA_ENTITY_SET_KEYVALUE",        0x83E0D0,  0x83E410),
    ("RVA_ENTITY_SET_NODE_ATTR",       0x86B550,  0x86B890),
    ("RVA_NODE_POST_CLASS",            0x866D70,  0x8670B0),
    ("RVA_NODE_ADD_CHILD",             0x879170,  0x8794B0),
    ("RVA_NODE_GET_PARENT",            0x864EA0,  0x8651E0),
    ("RVA_NODE_GET_ROOT",              0x864EB0,  0x8651F0),
    ("RVA_PARTICLE_SET_DEFINITION",    0x7F5350,  0x7F5690),
    ("RVA_ENTITY_ADD_CONN",            0x986EA0,  0x9871E0),
    ("RVA_ENTITY_REMOVE_CONN",         0x987AF0,  0x987E30),
    ("RVA_CONN_VALUE_INIT",            0x13E79E0, 0x13E7FF0),
    ("RVA_CDMEPOLYGONMESH_VTABLE",     0x1D70620, 0x1D70700),
    ("RVA_MESH_SET_VERTEX_POSITIONS",  0x9B8880,  0x9B8BC0),
    ("RVA_POLY_SET_VERTEX_POSITIONS",  0xCDC6E0,  0xCDCA20),
    ("RVA_MESH_BUILD_FACE",            0x901F40,  0x902280),
    ("RVA_POLY_MERGE_VERTICES",        0xCD21E0,  0xCD2520),
    ("RVA_POLY_REMOVE_ISOLATED",       0xCD83C0,  0xCD8700),
    ("RVA_DATAMODEL_CREATE_ELEMENT",   0x5BBB90,  0x5BBED0),
    ("RVA_ELEMENT_CREATE_CORE",        0x5BB7F0,  0x5BBB30),
    ("RVA_CMAPENTITY_FACTORY",         0x21DB400, 0x21DB1F0),
    ("RVA_UNDO_SCOPE_BEGIN",           0x60F370,  0x60F6B0),
    ("RVA_UNDO_SCOPE_END",             0x60F1C0,  0x60F500),
    # --- 数据全局（.data 里文件内容是空的/运行时才填，靠引用或指针值反查出来的）---
    # CDATAMODEL_PTR_GLOBAL 的值就是指向单例的指针：新版读到 0x1824B7AC0
    # => 单例本体在 0x24B7AC0（Δ-0x1C0，与 BIND_TARGET_LIST 的 Δ 一致，互相印证）
    ("RVA_CDATAMODEL_PTR_GLOBAL",      0x21B2B68, 0x21B2958),
    ("RVA_CDATAMODEL_GLOBAL",          0x24B7C80, 0x24B7AC0),
    ("RVA_BIND_TARGET_LIST",           0x272D898, 0x272D6D8),
]

# DLL 侧（hammer_bridge.cpp 的 HammerAddr::kXxxRva）
#   kCreateInterfaceRva  : 走 GetProcAddress 成功，RVA 只是兜底；按导出表真值更新
#   kInterfaceListHeadRva: 旧值早就过期；这次直接从 CreateInterface 函数体里
#                          `mov r9,[rip+disp]` 解出 s_pInterfaceRegs 的新地址
BRIDGE_RVAS = [
    ("kCreateInterfaceRva",   0x12E1B50, 0x13FFCB0),
    ("kInterfaceListHeadRva", 0x26310E8, 0x2733FB0),
    ("kToolSystemNameRva",    0x1CB1B58, 0x1CB1C48),
]


def table_from_json(js: Path):
    """用 `_rva_diff.py --json` 的结果生成 (名字, 目标文件现值, 新值) 表。

    现值从目标文件里现读，所以不用手抄；两个文件都找一遍，按名落到对应表。
    """
    import json

    mp = json.loads(js.read_text(encoding="utf-8"))
    texts = {SERVER: SERVER.read_text(encoding="utf-8"),
             BRIDGE: BRIDGE.read_text(encoding="utf-8")}
    out = {SERVER: [], BRIDGE: []}
    missing: list[str] = []
    for name, new in mp.items():
        if name.startswith("RVA_QT_"):     # Qt5Widgets/Qt5Core 的偏移，不属于 hammer.dll
            continue
        hit = False
        for target, txt in texts.items():
            m = re.search(rf"^(\s*(?:constexpr\s+\w+\s+)?{re.escape(name)}\s*=\s*)"
                          rf"0[xX]([0-9A-Fa-f]+)", txt, re.M)
            if not m:
                continue
            hit = True
            cur = int(m.group(2), 16)
            if cur != new:
                out[target].append((name, cur, new))
        if not hit:
            missing.append(name)
    return out[SERVER], out[BRIDGE], missing


def patch(path: Path, table, dry: bool) -> list[str]:
    txt = path.read_text(encoding="utf-8")
    log: list[str] = []
    for name, old, new in table:
        if old == new:
            continue
        pat = re.compile(rf"^(\s*(?:constexpr\s+\w+\s+)?{re.escape(name)}\s*=\s*)0[xX]{old:X}\b",
                         re.M)
        hits = pat.findall(txt)
        if len(hits) != 1:
            log.append(f"   ❌ {name}: 期望命中 1 处，实际 {len(hits)} 处（0x{old:X}）")
            continue
        txt = pat.sub(rf"\g<1>0x{new:X}", txt, count=1)
        log.append(f"   ✔ {name:<32} 0x{old:X} -> 0x{new:X}   (Δ{new - old:+#x})")
    if not dry:
        path.write_text(txt, encoding="utf-8")
    return log


def main() -> int:
    dry = "--dry" in sys.argv
    srv_table, brg_table = SERVER_RVAS, BRIDGE_RVAS
    if "--from-json" in sys.argv:      # 差分结果直接落盘，省掉手抄 (名字, 旧, 新) 三步
        js = Path(sys.argv[sys.argv.index("--from-json") + 1])
        srv_table, brg_table, missing = table_from_json(js)
        print(f"[json] {js.name}: Python {len(srv_table)} 条 / DLL {len(brg_table)} 条")
        if missing:
            print(f"[json] ⚠ 目标文件里找不到这些名字，已跳过：{', '.join(missing)}")

    print(f"{'[dry] ' if dry else ''}更新 {SERVER.name}")
    log = patch(SERVER, srv_table, dry)
    print("\n".join(log))
    bad = sum(1 for x in log if "❌" in x)

    print(f"\n{'[dry] ' if dry else ''}更新 {BRIDGE.name}")
    log2 = patch(BRIDGE, brg_table, dry)
    print("\n".join(log2))
    bad += sum(1 for x in log2 if "❌" in x)

    print(f"\n完成：Python {len(srv_table)} 条 / DLL {len(brg_table)} 条，失败 {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
