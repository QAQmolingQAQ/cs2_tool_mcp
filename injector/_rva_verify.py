#!/usr/bin/env python3
r"""新版 hammer.dll 的 RVA 活体全量校验（在一个**全新进程**里跑）。

为什么要新进程：`cs2_mcp_server.py` 的 RVA 常量是模块级常数，MCP 服务进程
是长驻的，改文件对它不生效——只有新起的进程才会用新值。

覆盖的 RVA 分组：
  读路径   _dm_table / _walk_elements / _entity_class_props / PROPS_FIND_ATTR
  写路径   ENTITY_SET_KEYVALUE / PROPS_SET_STRING_ATTR / ATTR_SET_SYMBOL /
           ELEMENT_MARK_DIRTY / HIST_RECORD_NODE / ENTITY_SET_NODE_ATTR / NODE_POST_CLASS
  建实体   DATAMODEL_CREATE_ELEMENT / ELEMENT_CREATE_CORE / CMAPENTITY_FACTORY / NODE_ADD_CHILD
  连 IO    ENTITY_ADD_CONN / ENTITY_REMOVE_CONN / CONN_VALUE_INIT
  网格     MESH_BUILD_FACE / MESH_SET_VERTEX_POSITIONS / POLY_*
  撤销     UNDO_SCOPE_BEGIN/END / MAP_HISTORY_* / CDATAMODEL_UNDO|REDO
  粒子     PARTICLE_SET_DEFINITION

用法： python injector/_rva_verify.py [--doc 0]
⚠ 会在目标地图里建几个临时实体/盒子，跑完会删掉。
"""
from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "mcp_server"))
import cs2_mcp_server as srv  # noqa: E402

DOC = "0"
TMP_ENT = "rva_verify_tmp"
TMP_FX = "rva_verify_fx"
TMP_BOX = "rva_verify_box"

results: list[tuple[str, bool, str]] = []


def step(label: str, fn, *a, **kw):
    try:
        out = fn(*a, **kw)
    except Exception as e:                       # noqa: BLE001
        results.append((label, False, f"{type(e).__name__}: {e}"))
        return None
    ok = not str(out).lstrip().startswith(("ERROR", "❌"))
    results.append((label, ok, str(out).splitlines()[0][:96]))
    return out


def elem(out) -> int:
    m = re.search(r"(0x[0-9a-f]{8,})", str(out) or "")
    return int(m.group(1), 16) if m else 0


def main() -> int:
    global DOC
    if "--doc" in sys.argv:
        DOC = sys.argv[sys.argv.index("--doc") + 1]

    base = srv._hammer_base()
    print(f"hammer base = {base:#x}   doc 选择器 = {DOC!r}\n")
    if not base:
        print("❌ 拿不到 hammer base")
        return 1

    doc = srv._map_doc(DOC)
    world = srv._read_int(doc + srv.CMAPDOC_WORLD_OFFSET, "u64")
    print(f"CMapDoc = {doc:#x}   CMapWorld = {world:#x}")
    step("① CDataModel 元素表 (_dm_table)", lambda: str(len(list(srv._walk_elements(world)))))
    step("② CMapDoc/CDataModel 读取 (cs2_map_info)", srv.cs2_map_info, DOC)

    # ---- 建实体：DATAMODEL_CREATE_ELEMENT / ELEMENT_CREATE_CORE / FACTORY / NODE_ADD_CHILD
    out = step("③ cs2_entity_create (prop_dynamic)", srv.cs2_entity_create, "prop_dynamic", TMP_ENT, DOC)
    ent = elem(out)
    print(f"   -> element {ent:#x}" if ent else "   -> 没解析到 element")

    if ent:
        h = hex(ent)
        step("④ cs2_entity_set_attr targetname/model",
             srv.cs2_entity_set_attr, h, "targetname", TMP_ENT)
        step("④ cs2_entity_set_transform",
             srv.cs2_entity_set_transform, h, "0 0 300", "0 0 0", "1 1 1")
        step("⑤ cs2_entity_get_attr",
             srv.cs2_entity_get_attr, h, "targetname")
        step("⑥ cs2_entity_add_io (ENTITY_ADD_CONN)",
             srv.cs2_entity_add_io, h, "OnUser1", "Kill", "!self")
        step("⑦ cs2_entity_get_io",
             srv.cs2_entity_get_io, h)
        step("⑧ cs2_entity_remove_io (ENTITY_REMOVE_CONN)",
             srv.cs2_entity_remove_io, h, 0)
        step("⑨ cs2_entity_remove_attr",
             srv.cs2_entity_remove_attr, h, "targetname")
        step("⑩ cs2_entity_attrs",
             srv.cs2_entity_attrs, h, 20)

    # ---- 粒子：PARTICLE_SET_DEFINITION
    fx_out = step("⑪ cs2_entity_create (info_particle_system)",
                  srv.cs2_entity_create, "info_particle_system", TMP_FX, DOC)
    fx = elem(fx_out)
    if fx:
        step("⑫ cs2_particle_set_definition (PARTICLE_SET_DEFINITION)",
             srv.cs2_particle_set_definition, hex(fx), "particles/test.vpcf")

    # ---- 网格：CREATE_ELEMENT / MESH_BUILD_FACE / POLY_*
    box_out = step("⑬ cs2_mesh_create_box (MESH_BUILD_FACE + POLY_*)",
                   srv.cs2_mesh_create_box, "0 0 600", "128 128 128",
                   "materials/dev/reflectivity_30.vmat", TMP_BOX, True, 512.0, DOC)
    box = elem(box_out)
    if box:
        step("⑭ cs2_mesh_get_geometry", srv.cs2_mesh_get_geometry, hex(box), 4)
        step("⑮ cs2_mesh_scale", srv.cs2_mesh_scale, hex(box), "2 2 2", "")

    # ---- 撤销：UNDO_SCOPE_* / MAP_HISTORY_* / CDATAMODEL_UNDO|REDO
    step("⑯ cs2_map_undo", srv.cs2_map_undo, DOC)
    step("⑰ cs2_map_redo", srv.cs2_map_redo, DOC)

    # ---- 清理
    if ent:
        step("⑱ cs2_entity_delete (临时实体)", srv.cs2_entity_delete, hex(ent))
    if fx:
        step("⑱ cs2_entity_delete (临时粒子)", srv.cs2_entity_delete, hex(fx))
    if box:
        step("⑱ cs2_entity_delete (临时盒子)", srv.cs2_entity_delete, hex(box))

    print("\n" + "=" * 78)
    npass = sum(1 for _l, ok, _m in results if ok)
    for label, ok, msg in results:
        print(f" {'✔' if ok else '✘'} {label:<52} {msg}")
    print("=" * 78)
    print(f"通过 {npass} / {len(results)}")
    return 0 if npass == len(results) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:                             # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(3)
