"""Hammer maps operations."""
from __future__ import annotations
import os
import time
import math
from .datamodel import (
    _fmt_attr_line,
    _dm_find_attrs,
    _dm_handle_element,
    _dm_handle_map,
    _dm_table,
    _dm_value_at,
    _dm_walk_attrs,
    _entity_get_attrs,
)
from .geometry import (
    _box_hits,
    _mesh_world_box,
    _parse_vec3_arg,
    _point_hits,
    _poly_materials,
    _poly_ready,
)
from .history import (
    _find_map_histories,
)
from .offsets import (
    CMAPDOC_ROOT_OFFSET,
    CMAPDOC_WORLD_OFFSET,
    ENTITY_OFF_ORIGIN,
    ENTITY_TARGETNAME_ATTR,
    MAIN_THREAD_STATUS_NAMES,
    MAP_DOC_PATH_OFFSET,
    POLY_OFF_FPOOL_CNT,
    POLY_OFF_VPOOL_CNT,
    RVA_CMAPENTITY_VTABLE,
    RVA_CMAPGROUP_VTABLE,
    RVA_CMAPMESH_VTABLE,
    RVA_CMAPROOT_VTABLE,
    RVA_HAMMER_SAVE_DOC,
)
from .runtime import (
    _get_pipe,
    _hammer_addr,
    _hammer_base,
    _read_int,
    _read_string,
    _read_vec3,
)
from .scene import (
    _entity_meshes,
    _map_doc,
    _walk_elements,
)


def cs2_map_info(doc: str = "") -> str:
    """返回地图文档的信息：路径 / 文件名 / 关键对象地址 / 撤销栈深度。

    `CMapDoc+0x6A0` 指向地图全路径字符串（VM 实测得到
    `.../content/csgo_addons/test/maps/untitled_1.vmap`）。

    Args:
        doc: 目标地图文档（多文档**务必指定**）：留空 = 清单第一个；数字 = 索引；
             其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    try:
        doc = _map_doc(doc)
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
        path_ptr = _read_int(doc + MAP_DOC_PATH_OFFSET, "u64")
        path = _read_string(path_ptr, 512) if path_ptr else ""
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    lines = ["当前地图文档:"]
    lines.append(f"  路径     : {path or '<空>'}")
    lines.append(f"  文件名   : {path.replace(chr(92), '/').rsplit('/', 1)[-1] if path else '<空>'}")
    lines.append(f"  CMapDoc  : {doc:#x}")
    lines.append(f"  CMapWorld: {world:#x}")

    try:
        undo_h, redo_h = _find_map_histories(doc)
        lines.append(f"  撤销历史 : {_read_int(undo_h + 8, 'u32')} 步"
                     f"   重做历史: {_read_int(redo_h + 8, 'u32')} 步")
        lines.append(f"  undo历史对象: {undo_h:#x}    redo历史对象: {redo_h:#x}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"  （撤销历史读取失败: {e}）")
    return "\n".join(lines)


def cs2_map_check(doc: str = "", max_issues: int = 100) -> dict:
    """Read-only checks of an open Hammer map's entity and mesh structure.

    Reports missing brush geometry, unreadable/empty meshes, invalid origins, and
    duplicate targetnames. Duplicate names are informational: Source I/O may
    intentionally address several entities with one name. This does not compile
    the map or claim that it will load in game.
    """
    issues: list[dict] = []
    issue_count = 0
    counts = {"elements": 0, "entities": 0, "meshes": 0}
    names: dict[str, list[str]] = {}
    max_issues = max(1, min(int(max_issues), 1000))

    def report(code: str, severity: str, address: int, detail: str) -> None:
        nonlocal issue_count
        issue_count += 1
        if len(issues) < max_issues:
            issues.append({"code": code, "severity": severity,
                           "address": hex(address), "detail": detail})

    try:
        document = _map_doc(doc)
        world = _read_int(document + CMAPDOC_WORLD_OFFSET, "u64")
        if not world:
            raise RuntimeError("CMapDoc has no CMapWorld")
        table, cap = _dm_table()
        base = _hammer_base()
        entity_vt = base + RVA_CMAPENTITY_VTABLE
        mesh_vt = base + RVA_CMAPMESH_VTABLE
        for el, vt in _walk_elements(world, table, cap, strict=True):
            counts["elements"] += 1
            if counts["elements"] > 200000:
                raise RuntimeError("scene traversal exceeded 200000 elements")
            if vt == entity_vt:
                counts["entities"] += 1
                attrs = _entity_get_attrs(el, ("classname", ENTITY_TARGETNAME_ATTR))
                cls = str(attrs.get("classname") or "").strip()
                name = str(attrs.get(ENTITY_TARGETNAME_ATTR) or "").strip()
                if not cls:
                    report("missing_classname", "error", el, "entity has no classname")
                if name:
                    names.setdefault(name.casefold(), []).append(hex(el))
                origin = _read_vec3(el + ENTITY_OFF_ORIGIN)
                if not all(math.isfinite(v) for v in origin):
                    report("invalid_origin", "error", el, f"origin={origin}")
                if cls in {"func_button", "func_brush"} or cls.startswith("trigger_"):
                    owned = _entity_meshes(el, table, cap)
                    if not owned:
                        report("missing_brush_mesh", "warning", el,
                               f"{cls} has no owned CMapMesh")
            elif vt == mesh_vt:
                counts["meshes"] += 1
                poly = _poly_ready(el)
                if not poly:
                    report("mesh_not_ready", "warning", el,
                           "runtime CHammerPolyMesh is unavailable")
                    continue
                verts = _read_int(poly + POLY_OFF_VPOOL_CNT, "u32")
                faces = _read_int(poly + POLY_OFF_FPOOL_CNT, "u32")
                if not verts or not faces:
                    report("empty_mesh", "warning", el,
                           f"vertices={verts}, faces={faces}")
        for name, addresses in names.items():
            if len(addresses) > 1:
                report("duplicate_targetname", "info", int(addresses[0], 16),
                       f"{name}: {len(addresses)} entities ({', '.join(addresses[:8])})")
        return {"ok": True, "document": hex(document), "counts": counts,
                "issues": issues, "issue_count": issue_count,
                "issues_truncated": issue_count > len(issues),
                "scope": "open Hammer document; structural checks only"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "document": doc, "counts": counts,
                "issues": issues, "error": f"{type(exc).__name__}: {exc}"}


def cs2_map_groups(doc: str = "") -> str:
    """列出地图的**组织信息**：分组 / 可见性组 / 当前选择集 / 地图变量 / 相机。

    Hammer 的 Groups、Visgroups 面板与「当前选中了什么」都在这里（2026-09 实测，
    见 REVERSE_NOTES.md §15.8）。链路：
      `CMapDoc+0x80` -> CMapRootElement，它的属性引用：
        `rootSelectionSet` -> CMapSelectionSet（当前选择集）
        `visbility`        -> CVisibilityMgr（可见性组，`nodes` = 元素句柄表）
        `mapVariables`     -> CMapVariableSetStorage（地图变量）
        `3dcameras` / `defaultcamera` -> CStoredCameras / CStoredCamera
      **分组**是 CMapWorld 子树里的 `CMapGroup`，成员在其 `children` 属性（元素句柄表）。

    成员显示为 `h=<句柄>(<类名>)`：句柄经元素表直查，类名走 entity_properties。

    Args:
        doc: 目标地图文档（多文档**务必指定**）：留空 = 清单第一个；数字 = 索引；
             其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    try:
        base = _hammer_base()
        doc = _map_doc(doc)
        root = _read_int(doc + CMAPDOC_ROOT_OFFSET, "u64")
        if not root or _read_int(root, "u64") != base + RVA_CMAPROOT_VTABLE:
            return f"ERROR CMapRootElement 无效（root={root:#x}）"
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
        table, cap = _dm_table()
        refs = _dm_find_attrs(root, ("rootSelectionSet", "visbility", "mapVariables",
                                     "3dcameras", "defaultcamera"))

        def _ref_elem(name: str) -> int:
            """root 上的 type=1 引用属性 -> 元素地址（0 = 无效/未设置）。"""
            item = refs.get(name)
            if not item:
                return 0
            h = _dm_value_at(item[1], item[2])
            return _dm_handle_element(h, table, cap) if isinstance(h, int) else 0

        def _label(handle: int) -> str:
            el = _dm_handle_element(handle, table, cap)
            cls = "?"
            if el:
                try:
                    vt = _read_int(el, "u64")
                except Exception:  # noqa: BLE001
                    vt = 0
                if vt == base + RVA_CMAPENTITY_VTABLE:
                    cls = _entity_get_attrs(el, ("classname",)).get("classname") or "?"
                elif vt == base + RVA_CMAPMESH_VTABLE:
                    cls = "CMapMesh"
                elif vt == base + RVA_CMAPGROUP_VTABLE:
                    cls = "CMapGroup"
                else:
                    cls = f"vt={vt - base:#x}"
            return f"h={handle}({cls})"

        def _member_list(el: int, arr_name: str, maxn: int = 12) -> str:
            got = _dm_find_attrs(el, (arr_name,))
            if arr_name not in got:
                return "（无该属性）"
            arr = _dm_value_at(got[arr_name][1], got[arr_name][2])
            if not isinstance(arr, list) or not arr:
                return "（空）"
            shown = "  ".join(_label(h) for h in arr[:maxn])
            if len(arr) > maxn:
                shown += f"  … 共 {len(arr)} 个"
            return shown

        def _attr_of(el: int, name: str):
            got = _dm_find_attrs(el, (name,))
            return _dm_value_at(*got[name][1:]) if name in got else None

        def _fmtv(v) -> str:
            """vec3 友好显示，其余交给 str()。"""
            if isinstance(v, tuple) and len(v) == 3:
                return "(%.1f, %.1f, %.1f)" % v
            return str(v)

        lines = [f"地图组织信息  CMapRootElement={root:#x}  CMapWorld={world:#x}"]

        groups = [el for el, vt in _walk_elements(world, table, cap)
                  if vt == base + RVA_CMAPGROUP_VTABLE]
        lines.append(f"\n── 分组 CMapGroup（{len(groups)} 个）──")
        for n, el in enumerate(groups):
            lines.append(f"  [{n}] {el:#x}  nodeID={_attr_of(el, 'nodeID')}")
            lines.append(f"      成员: {_member_list(el, 'children')}")
        if not groups:
            lines.append("  （无）")

        vis = _ref_elem("visbility")
        lines.append(f"\n── 可见性组 CVisibilityMgr @{vis:#x} ──")
        if vis:
            lines.append(f"  nodes：{_member_list(vis, 'nodes')}")
            lines.append(f"  hiddenFlags：{_attr_of(vis, 'hiddenFlags')}")
        else:
            lines.append("  （CMapRootElement 上没有 visbility 引用）")

        sel = _ref_elem("rootSelectionSet")
        lines.append(f"\n── 当前选择集 CMapSelectionSet @{sel:#x} ──")
        if sel:
            for nm, atype, val in _dm_walk_attrs(sel):
                if nm != "name":
                    lines.append(_fmt_attr_line(nm, atype, val))
        else:
            lines.append("  （CMapRootElement 上没有 rootSelectionSet 引用）")

        vars_el = _ref_elem("mapVariables")
        lines.append(f"\n── 地图变量 CMapVariableSetStorage @{vars_el:#x} ──")
        if vars_el:
            shown_any = False
            for nm, atype, val in _dm_walk_attrs(vars_el):
                if nm == "name" or (isinstance(val, list) and not val):
                    continue
                lines.append(_fmt_attr_line(nm, atype, val))
                shown_any = True
            if not shown_any:
                lines.append("  （本图没有定义任何地图变量）")
        else:
            lines.append("  （CMapRootElement 上没有 mapVariables 引用）")

        lines.append("\n── 相机 ──")
        cams = _ref_elem("3dcameras")
        cam = _ref_elem("defaultcamera")
        if cams:
            cl = _attr_of(cams, "cameras")
            lines.append(f"  CStoredCameras @{cams:#x}: "
                         f"cameras {len(cl) if isinstance(cl, list) else 0} 个, "
                         f"activecamera={_attr_of(cams, 'activecamera')}")
        if cam:
            lines.append(f"  CStoredCamera @{cam:#x}: "
                         f"position={_fmtv(_attr_of(cam, 'position'))}")
            lines.append(f"      lookat={_fmtv(_attr_of(cam, 'lookat'))}")
        if not cams and not cam:
            lines.append("  （无）")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    return "\n".join(lines)


def _file_stat(path: str) -> tuple[int, str] | None:
    """(字节数, mtime 文本)；路径为空或文件不可访问时返回 None。"""
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))


def cs2_map_save(doc: str = "") -> str:
    """保存地图（直接调用 Hammer 底层保存函数，不依赖 UI / 菜单）。

    走 `sub_1801639B0`（per-document save），语义等价于 Hammer 的 File→Save：
    `a4=1` 强制保存，不要求文档处于「已修改」状态；`a3=0` 保持与交互式保存
    一致的检查流程，但**不会**走外层那段会阻塞主线程的「编辑会话布局」保存。

    地图必须已有真实文件路径（`CMapDoc+0x6A0`）。&New 出来的地图只有内存虚拟
    路径，请先 &Open 一张已有 .vmap，或手动另存为。

    Args:
        doc: 目标地图文档（多文档**务必指定**，否则可能保存错图）：留空 = 清单第一个；
             数字 = 索引；其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    try:
        doc = _map_doc(doc)
        path_ptr = _read_int(doc + MAP_DOC_PATH_OFFSET, "u64")
        path = _read_string(path_ptr, 512) if path_ptr else ""
        before = _file_stat(path)
        resp = _get_pipe().call("call_function", {
            "address": _hammer_addr(RVA_HAMMER_SAVE_DOC),
            "args": [doc, 0, 0, 1, 0, 0],
            "on_main_thread": True,
            "timeout_ms": 30000,
        })
        if "error" in resp:
            return f"INJECTED_DLL_ERROR: {resp['error']}"
        result = resp["result"]
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    status = result.get("main_thread_status", 0)
    if status != 0:
        return (
            f"ERROR 主线程派发失败 (main_thread_status={status}): "
            f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}\n"
            f"  doc={doc:#x}  文件={path or '<无路径>'}"
        )

    ret = result.get("ret_hex", "?")
    ok = bool(int(ret, 16)) if isinstance(ret, str) else bool(ret)
    after = _file_stat(path)
    lines = [f"保存{'成功' if ok else '未写入'} (ret={ret})  doc={doc:#x}"]
    lines.append(f"  文件: {path or '<无路径>'}")
    if before and after:
        changed = before != after
        lines.append(f"  磁盘: {before[0]} 字节 / {before[1]} → {after[0]} 字节 / {after[1]}"
                     f"{'  [已更新]' if changed else '  [未变化]'}")
    if not ok:
        lines.append("  提示: 返回 0 = 没有任何文件被写入（路径无效 / 只读 / 被占用）。")
    return "\n".join(lines)


def cs2_area_query(min: str = "", max: str = "", kinds: str = "mesh,trigger,point",
                   limit: int = 200, doc: str = "") -> str:
    """按世界坐标范围(AABB)取地图内容 —— 大图别全量拉，只取盒子里的对象。

    `kinds` 逗号分隔，可取：
      mesh    : CMapMesh（手绘网格 / 贴花；材质里含 trigger 的会在行里标出来）
      trigger : 实体类名以 `trigger` 开头的（trigger_multiple 等）；也含材质带 trigger 的 mesh
      point   : 其余实体（info_* / point_* / env_* / light 等「点实体」）
      brush   : 实际拥有 mesh 的非 trigger 实体，以及类名以 `func_` 开头的实体

    坐标轴同游戏（x/y 水平、z 朝上），单位同 Hammer，闭区间相交。
    精度：mesh 范围优先用元素缓存 AABB（`el+0x118`，实测手绘 mesh 与顶点算出来的一致）；
    缓存非法或某轴被压成 0 宽时（单面 / 带旋转的 mesh）会与「顶点+origin」算出的范围取并集
    —— 宁可外扩不漏。少数地图自带 tile mesh 两种来源不在同一参照系（REVERSE_NOTES §13.6），
    所以范围只当「大致范围」，精确几何仍用 cs2_mesh_get_geometry。带 mesh 的实体按各子 mesh
    的 AABB 判相交；无 mesh 的实体按 `+0xA0` origin 判点。读取失败报 ERROR。

    Args:
        min: 盒角 "x y z"（也接受 "x,y,z" / [x,y,z]）；留空 = 该侧不设限
        max: 对角 "x y z"；留空 = 该侧不设限
        kinds: 逗号分隔，mesh / trigger / point / brush
        limit: 每类最多列多少条（命中总数仍完整统计）
        doc: 目标地图文档（多文档**务必指定**）：留空 = 清单第一个；数字 = 索引；
             其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    try:
        qmin = _parse_vec3_arg(min, "min") if str(min).strip() else (-float("inf"),) * 3
        qmax = _parse_vec3_arg(max, "max") if str(max).strip() else (float("inf"),) * 3
    except ValueError as e:
        return f"ERROR {e}"
    if any(qmin[i] > qmax[i] for i in range(3)):
        return "ERROR min 每个分量都要 <= max"

    want = {k.strip().lower() for k in str(kinds).split(",") if k.strip()}
    unknown = want - {"mesh", "trigger", "point", "brush"}
    if unknown:
        return f"ERROR 不认识的 kinds: {sorted(unknown)}（可用 mesh/trigger/point/brush）"
    if not want:
        return "ERROR kinds 为空"
    # 注意：参数名 min/max 会遮蔽内建函数，这里不要用内建 min()/max()
    limit = int(limit)
    if limit < 1:
        limit = 1
    elif limit > 5000:
        limit = 5000

    try:
        base = _hammer_base()
        vt_mesh = base + RVA_CMAPMESH_VTABLE
        vt_ent = base + RVA_CMAPENTITY_VTABLE
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"

    # ---- 一趟走完世界树，同时收 mesh 与实体 ----
    # （旧版先扫一遍元素表找 mesh、再走一遍树找实体：既重复劳动，又因 `_enum_elements`
    #   的 8192 截断而漏掉 handle≥8192 的对象。走树时 vtable 顺带就有，不用额外读。）
    world = _read_int(_map_doc(doc) + CMAPDOC_WORLD_OFFSET, "u64")
    if not world:
        return "ERROR CMapDoc 里没有 CMapWorld（地图可能还没加载完）"
    table, cap = _dm_table()
    handle_of = _dm_handle_map(table, cap)
    want_mesh = bool({"mesh", "trigger"} & want)

    mesh_hits: list[tuple[int, int]] = []
    ent_hits: list[tuple[str, int, str, str, tuple[float, float, float]]] = []
    mesh_total = ent_total = 0
    seen = 0
    for el, vt in _walk_elements(world, table, cap):
        seen += 1
        if seen > 200000:
            break
        if vt == vt_mesh:
            mesh_total += 1
            if not want_mesh:
                continue
            poly = _poly_ready(el)
            if not poly:
                continue
            try:
                box = _mesh_world_box(el, poly)[0]
            except Exception:  # noqa: BLE001
                continue
            if box and _box_hits(box, qmin, qmax):
                mesh_hits.append((handle_of.get(el, -1), el))
        elif vt == vt_ent:
            # 先看真实 mesh 子树；不能按 origin 粗筛带几何实体。
            ent_total += 1
            try:
                origin = _read_vec3(el + ENTITY_OFF_ORIGIN)
            except Exception:  # noqa: BLE001
                continue
            try:
                owned_meshes = _entity_meshes(el, table, cap)
                boxes = []
                for mesh in owned_meshes:
                    poly = _poly_ready(mesh)
                    box = _mesh_world_box(mesh, poly)[0] if poly else None
                    if box is None:
                        raise RuntimeError(f"实体 {el:#x} 的 mesh {mesh:#x} 范围不可读")
                    boxes.append(box)
            except Exception as e:
                return f"ERROR 无法确认实体几何范围: {e}"
            if boxes:
                if not any(_box_hits(box, qmin, qmax) for box in boxes):
                    continue
            elif not _point_hits(origin, qmin, qmax):
                continue
            try:
                attrs = _entity_get_attrs(el, ("classname", ENTITY_TARGETNAME_ATTR))
            except Exception:  # noqa: BLE001
                attrs = {}
            cls = attrs.get("classname") or "?"
            kind = ("trigger" if cls.startswith("trigger")
                    else "brush" if owned_meshes or cls.startswith("func_") else "point")
            if kind not in want:
                continue
            tname = attrs.get(ENTITY_TARGETNAME_ATTR) or ""
            ent_hits.append((kind, el, cls, tname, origin))

    head = ("范围 (%s) ~ (%s)  命中: mesh %d/%d  实体 %d/%d（按 %s 过滤）"
            % ("%.1f,%.1f,%.1f" % qmin, "%.1f,%.1f,%.1f" % qmax,
               len(mesh_hits), mesh_total, len(ent_hits), ent_total,
               ",".join(sorted(want))))
    lines = [head]

    # ---- mesh 明细 ----
    shown = 0
    for h, el in mesh_hits:
        if shown >= limit:
            lines.append(f"  [mesh ] … 还有 {len(mesh_hits) - shown} 个 mesh 在范围内（limit={limit}）")
            break
        try:
            poly = _poly_ready(el)
            nv = _read_int(poly + POLY_OFF_VPOOL_CNT, "u32")
            nf = _read_int(poly + POLY_OFF_FPOOL_CNT, "u32")
            mats = [m.replace("materials/", "").replace(".vmat", "")
                    for m in _poly_materials(poly) if m]
        except Exception:  # noqa: BLE001
            nv = nf = -1
            mats = []
        is_trig = any("trigger" in m.lower() for m in mats)
        if "mesh" not in want and not is_trig:
            continue  # 只要 trigger：跳过非触发材质的 mesh
        box = _mesh_world_box(el, poly)[0]
        lines.append("  [mesh ] h=%-5d %#x  nv=%-5d nf=%-5d  mat=[%s]%s  box=(%.1f,%.1f,%.1f)~(%.1f,%.1f,%.1f)"
                     % (h, el, nv, nf, ",".join(mats[:3]), " <trigger>" if is_trig else "", *box))
        shown += 1

    # ---- 实体明细（按 kind 分组，各组 limit 条）----
    for kind, tag in (("trigger", "trg  "), ("point", "point"), ("brush", "brush")):
        group = [r for r in ent_hits if r[0] == kind]
        for _k2, el, cls, tname, origin in group[:limit]:
            lines.append("  [%s] %#x  %s%s  origin=(%.1f, %.1f, %.1f)"
                         % (tag, el, cls, f"  name={tname}" if tname else "", *origin))
        if len(group) > limit:
            lines.append(f"  [{tag}] … 还有 {len(group) - limit} 个（limit={limit}）")
    if len(lines) == 1:
        lines.append("  （范围内没有命中对象）")
    return "\n".join(lines)
