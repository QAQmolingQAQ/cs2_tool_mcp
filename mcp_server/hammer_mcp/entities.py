"""Hammer entities operations."""
from __future__ import annotations
from .results import EditResult
import time
from typing import Any
from .datamodel import (
    _fmt_attr_line,
    _dm_array_handles,
    _dm_attr_type,
    _dm_attr_value,
    _dm_find_attr,
    _dm_table,
    _dm_walk_attrs,
    _entity_class_props,
    _entity_get_attrs,
    _resolve_handle,
)
from .geometry import (
    _mesh_world_box,
    _poly_ready,
)
from .history import (
    _ensure_undo_enabled,
    _find_map_histories,
    _hist_notify,
    _hist_push_step,
    _hist_record_node,
    _hist_record_object,
    _hist_state,
    _undo_manager_addr,
    _undo_scope_begin,
    _undo_scope_end,
)
from .offsets import (
    ATTR_OFF_NAME,
    ATTR_OFF_NEXT,
    CMAPDOC_WORLD_OFFSET,
    DM_ATTR_TYPE_NAMES,
    ELEMENT_OFF_ATTR_HEAD,
    ENTITY_CREATE_FLAGS,
    ENTITY_DMX_TYPE,
    ENTITY_OFF_ANGLES,
    ENTITY_OFF_ORIGIN,
    ENTITY_OFF_SCALES,
    ENTITY_TARGETNAME_ATTR,
    ENTITY_VFN_SET_CLASSNAME,
    INVALID_DMX_HANDLE,
    MAIN_THREAD_STATUS_NAMES,
    NODE_IFACE_OFFSET,
    NODE_OFF_CHILD_COUNT,
    NODE_VFN_REMOVE_CHILD,
    POLY_OFF_FPOOL_CNT,
    POLY_OFF_VPOOL_CNT,
    RVA_CDATAMODEL_GLOBAL,
    RVA_CMAPENTITY_VTABLE,
    RVA_CMAPMESH_VTABLE,
    RVA_CMAPWORLD_VTABLE,
    RVA_DATAMODEL_CREATE_ELEMENT,
    RVA_ELEMENT_MARK_DIRTY,
    RVA_ENTITY_SET_KEYVALUE,
    RVA_ENTITY_SET_NODE_ATTR,
    RVA_NODE_ADD_CHILD,
    RVA_NODE_GET_PARENT,
    RVA_NODE_POST_CLASS,
    RVA_PROPS_SET_STRING_ATTR,
    TRANSFORM_ATTR_OFFSETS,
    UNDO_MGR_OFF_UNDO_COUNT,
)
from .runtime import (
    _call_fn,
    _call_vfn,
    _get_pipe,
    _hammer_addr,
    _hammer_base,
    _parse_addr,
    _read_int,
    _read_string,
    _read_vec3,
    _write_mem,
)
from .scene import (
    _doc_of_element,
    _element_doc_strict,
    _entity_meshes,
    _map_doc,
    _walk_elements,
    list_entities,
)


def cs2_entity_list(limit: int = 200, doc: str = "") -> str:
    """列出当前地图的所有实体（类名 + 目标名 + 世界坐标 + 地址）。

    纯内存读取（2026-09 新版，见 REVERSE_NOTES.md §3 / §11.9 / §15.6）：
      CMapDoc+0x88 -> CMapWorld；节点 +0x1F8 子节点数 / +0x200 句柄数组，
      句柄经 **CDataModel 元素表直查**（+0x90 数据 / +0x88 容量，16B/项）解析为元素
      （不再每个句柄一次主线程 vfn168）；按 vtable==CMapEntity 筛实体；
      classname/targetname 经 entity_properties -> CEditGameClassProps **一次遍历**读取；
      **坐标是 CMapEntity 原生 Vec3D 成员 @ +0xA0**（不在 DMX 属性里）。

    Args:
        limit: 最多返回多少条。
        doc: 目标地图文档（多文档**务必指定**）：留空 = 清单第一个；数字 = 索引；
             其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    try:
        rows, total, doc, world, ent_total = list_entities(limit, doc)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    head = (f"实体数: {ent_total}（场景元素总数 {total}，"
            f"CMapDoc={doc:#x}, CMapWorld={world:#x}）")
    if not rows:
        return head
    lines = [head, ""]
    for n, (ent, cls, tname, origin, node_id) in enumerate(rows):
        label = cls or "?"
        if node_id is not None:
            label += f"  id={node_id}"
        if tname:
            label += f"  name={tname}"
        if origin:
            label += "  origin=(%.1f, %.1f, %.1f)" % origin
        else:
            label += "  origin=<读取失败>"
        lines.append(f"[{n:3}] {ent:#018x}  {label}")
    if ent_total > limit:
        lines.append(f"... 还有 {ent_total - limit} 个（用 limit 调整）")
    return "\n".join(lines)


def cs2_entity_get_meshes(entity: str, limit: int = 100) -> str:
    """检查实体实际拥有的 CMapMesh，区分无 mesh、空 mesh、可读几何。

    适用于 func_button、func_brush、trigger 等实体；按实际子树读取，
    不根据 classname 猜测是否有几何。不包含嵌套实体拥有的 mesh。
    返回 mesh 地址、顶点/面数和世界 AABB，可继续用 cs2_mesh_get_geometry。
    只读；读取失败会报 ERROR，不能当作无 mesh。
    """
    try:
        el = _parse_addr(entity)
        if _read_int(el, "u64") != _hammer_base() + RVA_CMAPENTITY_VTABLE:
            return "ERROR entity 不是 CMapEntity"
        limit = max(1, min(int(limit), 5000))
        table, cap = _dm_table()
        meshes = _entity_meshes(el, table, cap)
        attrs = _entity_get_attrs(el, ("classname", ENTITY_TARGETNAME_ATTR))
        lines = [f"实体 {el:#x}  classname={attrs.get('classname')!r}  mesh={len(meshes)}"]
        if not meshes:
            lines.append("  无 mesh 子节点；创建实体节点不会自动生成笔刷几何。")
        for mesh in meshes[:limit]:
            poly = _poly_ready(mesh)
            if not poly:
                lines.append(f"  mesh={mesh:#x}  运行时几何未就绪")
                continue
            nv = _read_int(poly + POLY_OFF_VPOOL_CNT, "u32")
            nf = _read_int(poly + POLY_OFF_FPOOL_CNT, "u32")
            box = _mesh_world_box(mesh, poly)[0]
            lines.append(f"  mesh={mesh:#x}  vertices={nv}  faces={nf}  box={box}")
        if len(meshes) > limit:
            lines.append(f"  … 还有 {len(meshes) - limit} 个 mesh（limit={limit}）")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR {type(e).__name__}: {e}"


def cs2_entity_attach_mesh(entity: str, mesh: str) -> str:
    """将现有 CMapMesh 挂接到实体（func_button/func_brush/trigger 等）。

    调用 Hammer 官方父节点 AddChild 虚函数（字节偏移 456），支持从世界
    或其他实体移入；不复制几何。必须同属一个已打开文档，默认记录 Ctrl+Z。
    采用 Hammer 原生重设父节点的变换语义；不额外重写 origin/angles/scales。
    先用 cs2_mesh_create_box/arch 创建几何，再用此工具挂接，
    并用 cs2_entity_get_meshes 检查归属。重复挂接不新增撤销步。
    """
    return attach_mesh(entity=entity, mesh=mesh).report


def attach_mesh(entity: str, mesh: str) -> EditResult:
    """Internal editing operation; returns typed status and any allocated address."""
    child: int | None = None
    try:
        ent, child = _parse_addr(entity), _parse_addr(mesh)
        base = _hammer_base()
        if _read_int(ent, "u64") != base + RVA_CMAPENTITY_VTABLE:
            return EditResult(ok=False, report=("ERROR entity 不是 CMapEntity"), element=child)
        if _read_int(child, "u64") != base + RVA_CMAPMESH_VTABLE:
            return EditResult(ok=False, report=("ERROR mesh 不是 CMapMesh"), element=child)
        doc = _element_doc_strict(ent)
        if _element_doc_strict(child) != doc:
            return EditResult(ok=False, report=("ERROR entity 与 mesh 不属于同一地图文档"), element=child)
        table, cap = _dm_table()
        if any(el == ent for el, _ in _walk_elements(child, table, cap)):
            return EditResult(ok=False, report=("ERROR 挂接会形成父子循环"), element=child)
        ret, err = _call_fn(RVA_NODE_GET_PARENT, [child])
        if err:
            raise RuntimeError(err)
        before = int(ret, 16) if ret else 0
        if before == ent:
            return EditResult(ok=True, report=(f"mesh={child:#x} 已属于实体 {ent:#x}，未新增历史步"), element=child)
        history, _ = _find_map_histories(doc)
        _hist_push_step(history, "cs2: attach mesh to entity")
        _hist_record_node(history, child)
        ret, err = _call_vfn(ent, 456, [child], timeout=20000)
        _hist_notify(history)
        if err:
            return EditResult(ok=False, report=(f"ERROR 挂接调用失败: {err}；请检查归属并用地图 Undo 恢复"), element=child)
        parent_ret, parent_err = _call_fn(RVA_NODE_GET_PARENT, [child])
        if parent_err:
            raise RuntimeError(f"挂接后父节点读取失败: {parent_err}")
        after = int(parent_ret, 16) if parent_ret else 0
        owned = _entity_meshes(ent, *_dm_table())
        if after != ent or child not in owned:
            return EditResult(ok=False, report=(f"ERROR 挂接未生效: ret={ret} parent={after:#x}；可用地图 Undo 恢复"), element=child)
        return (EditResult(ok=True, report=(f"已挂接 mesh={child:#x} 到实体 {ent:#x}\n"
                f"  父节点 {before:#x} -> {after:#x}；已记录 Ctrl+Z，支持撤销/重做"), element=child))
    except Exception as e:
        return EditResult(ok=False, report=(f"ERROR {type(e).__name__}: {e}"), element=child)


def cs2_entity_get_transform(entity: str) -> str:
    """读取实体的变换：origin / angles / scales（纯内存，CMapEntity 原生 Vec3D 成员）。

    2026-09-26 CE 对比实测定位（详见 REVERSE_NOTES.md §11.9）：
        entity+0xA0  Vec3D origin  世界坐标
        entity+0xAC  Vec3D angles  欧拉角（度）
        entity+0xB8  Vec3D scales  缩放
    注意：这三个是 CMapEntity 对象的原生成员，**不是 DMX 属性**
    （.vmap 里的 origin/angles/scales 属性属于 CMapNode，运行时没有 CMapNode 元素）。

    Args:
        entity: 实体地址（cs2_entity_list 给出）。
    """
    try:
        ent = _parse_addr(entity)
        vt = _read_int(ent, "u64")
        origin = _read_vec3(ent + ENTITY_OFF_ORIGIN)
        angles = _read_vec3(ent + ENTITY_OFF_ANGLES)
        scales = _read_vec3(ent + ENTITY_OFF_SCALES)
        props = _entity_class_props(ent)
        cls = _dm_attr_value(_dm_find_attr(props, "classname")) if props else None
        tname = _dm_attr_value(_dm_find_attr(props, "targetname")) if props else None
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    is_ent = "CMapEntity" if vt == _hammer_base() + RVA_CMAPENTITY_VTABLE else f"非 CMapEntity(vt={vt:#x})"
    return (
        f"实体 {ent:#x}  [{is_ent}]\n"
        f"  classname = {cls!r}   targetname = {tname!r}\n"
        f"  origin    = ({origin[0]:.3f}, {origin[1]:.3f}, {origin[2]:.3f})\n"
        f"  angles    = ({angles[0]:.3f}, {angles[1]:.3f}, {angles[2]:.3f})\n"
        f"  scales    = ({scales[0]:.3f}, {scales[1]:.3f}, {scales[2]:.3f})"
    )


def cs2_entity_get_attr(entity: str, name: str) -> str:
    """读取实体的属性值。

    纯内存属性链读取：先查 entity_properties(CEditGameClassProps) 链
    （classname / targetname / vscripts 等），再查实体自身链。
    值按属性类型码解码（见 REVERSE_NOTES §14.2）：string / int / color / vec3 /
    句柄数组 / 字符串数组；未解码的类型原样回十六进制并标注 type=。

    Args:
        entity: 实体地址（cs2_entity_list 给出，如 '0x1234abcd'）。
        name: 属性名，如 'classname' / 'targetname' / 'name'。
    """
    try:
        ent = _parse_addr(entity)
        props = _entity_class_props(ent)
        attr = _dm_find_attr(props, name) if props else 0
        owner = props
        if not attr:
            attr = _dm_find_attr(ent, name)
            owner = ent
        if not attr:
            return f"属性 {name!r} 不存在于实体 {ent:#x}"
        value = _dm_attr_value(attr)
        tcode = _dm_attr_type(attr)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    shown = repr(value) if isinstance(value, str) else str(value)
    tname = DM_ATTR_TYPE_NAMES.get(tcode, "?")
    return (f"{name} = {shown}  (type={tname}({tcode}), attr={attr:#x}, "
            f"owner={owner:#x}, entity={ent:#x})")


def cs2_entity_find_attr(entity: str, name: str) -> str:
    """查询实体是否具有某属性（class props 链或实体自身链）。

    找到返回属性对象 CDmAttribute* 地址；找不到返回提示。
    """
    try:
        ent = _parse_addr(entity)
        props = _entity_class_props(ent)
        attr = _dm_find_attr(props, name) if props else 0
        where = "CEditGameClassProps"
        if not attr:
            attr = _dm_find_attr(ent, name)
            where = "entity"
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    if not attr:
        return f"{name!r} 未找到  (entity={ent:#x})"
    return f"{name} -> attr={attr:#x}  ({where} 链, entity={ent:#x})"


def cs2_entity_attrs(entity: str, limit: int = 200) -> str:
    """列出实体的**全部**属性 —— 等价 Hammer「Object Properties」面板，外加引擎字段。

    两条链分别列出，都是整条遍历（纯内存，无主线程调用）：
      · `entity_properties`(CEditGameClassProps) —— **全部 keyvalue**（实测 trigger_hurt
        有 23 项：damage/damagecap/spawnflags/StartDisabled…；logic_script 有 Group00~15）。
        注意 keyvalue 一律以字符串存储（类型码 5），数值/向量型也是字符串。
      · 实体自身链 —— 引擎字段：`nodeID`(Hammer 里的对象编号，分组/可见性组就是引用它)、
        `referenceID`(8 字节对象 ID)、`isProceduralEntity`(bool)、`hitNormal`(vec3)、
        `children`、`variableNames`/`variableTargetKeys`、`relayPlugData` 等。

    值按类型码解码（见 REVERSE_NOTES §14.2 / §15.8）：
    5=string(string) · 1=element_handle · 2/3/7=int · **4=bool(只读 1 字节)** ·
    8=color · 10=vec3 · **15=id(8 字节)** · 33/37=数组 · 34=数组(元素类型未定)。

    Args:
        entity: 实体地址（cs2_entity_list 给出）。
        limit: 每条链最多列多少项。
    """
    try:
        ent = _parse_addr(entity)
        n_lim = max(1, int(limit))
        props = _entity_class_props(ent)
        ent_attrs = _dm_walk_attrs(ent)
        props_attrs = _dm_walk_attrs(props) if props else []
        cls = _entity_get_attrs(ent, ("classname",), props=props).get("classname")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    lines = [f"实体 {ent:#x}  [CMapEntity]  classname={cls!r}"]
    if props_attrs:
        lines.append(f"\n── CEditGameClassProps @{props:#x}"
                     f"（keyvalue，{len(props_attrs)} 项）──")
        lines += [_fmt_attr_line(*a) for a in props_attrs[:n_lim]]
        if len(props_attrs) > n_lim:
            lines.append(f"  … 还有 {len(props_attrs) - n_lim} 项")
    else:
        lines.append("\n── 没有 entity_properties（不是普通实体元素？）──")
    lines.append(f"\n── 实体自身链（{len(ent_attrs)} 项）──")
    lines += [_fmt_attr_line(*a) for a in ent_attrs[:n_lim]]
    if len(ent_attrs) > n_lim:
        lines.append(f"  … 还有 {len(ent_attrs) - n_lim} 项")
    return "\n".join(lines)


def cs2_entity_remove_attr(entity: str, name: str) -> str:
    """删除实体的一个属性（从 CDmElement 属性链上摘除）。

    CDmElement 的属性是 `element+0x48` 的**单向链表**，且没有独立的名字索引
    （`sub_1805C7170` 就是逐项按驻留串指针比较），所以摘链是安全的：把前驱的
    next 改指后继（前驱为 0 时改写链头），再调 `sub_1805C81C0(el, 3)` 让
    datamodel 传播脏状态。见 REVERSE_NOTES §14.4。

    ⚠ 回收内存、登记 undo 都不做 —— 删除后请显式保存地图。
    ⚠ `origin`/`angles`/`scales` 是变换 pin（写原生成员），不在属性链上，删不了。

    Args:
        entity: 实体地址。
        name: 要删除的属性名。
    """
    try:
        ent = _parse_addr(entity)
        if name.lower() in TRANSFORM_ATTR_OFFSETS:
            return (f"{name!r} 是变换属性（写 CMapEntity 原生 Vec3D），不在属性链上，"
                    "无法删除")
        props = _entity_class_props(ent)
        el = prev = attr = 0
        for cand in (props, ent):
            if not cand:
                continue
            prev, cur = 0, _read_int(cand + ELEMENT_OFF_ATTR_HEAD, "u64")
            while cur:
                nptr = _read_int(cur + ATTR_OFF_NAME, "u64")
                if nptr and _read_string(nptr, 96) == name:
                    el, attr = cand, cur
                    break
                prev, cur = cur, _read_int(cur + ATTR_OFF_NEXT, "u64")
            if attr:
                break
        if not attr:
            return f"{name!r} 未找到  (entity={ent:#x})"
        before = _dm_attr_value(attr)
        nxt = _read_int(attr + ATTR_OFF_NEXT, "u64")
        _write_mem(prev + ATTR_OFF_NEXT if prev else el + ELEMENT_OFF_ATTR_HEAD,
                   nxt.to_bytes(8, "little"))
        resp = _get_pipe().call("call_function", {
            "address": _hammer_addr(RVA_ELEMENT_MARK_DIRTY),
            "args": [el, 3],
            "on_main_thread": True,
            "timeout_ms": 15000,
        })
        if "error" in resp:
            return f"INJECTED_DLL_ERROR（属性已摘除，但脏通知失败）: {resp['error']}"
        gone = not _dm_find_attr(el, name)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    return (
        f"已删除属性 {name!r}  [{'链上已消失' if gone else '仍在链上?!'}]\n"
        f"  entity = {ent:#x}  owner = {el:#x}  attr = {attr:#x}\n"
        f"  删除前的值 = {before!r}\n"
        f"  前驱 = {prev:#x}  后继 = {nxt:#x}"
    )


def cs2_entity_set_attr(entity: str, name: str, value: str, history: bool = True) -> str:
    """设置实体参数（keyvalue 或变换 origin/angles/scales）。

    走 Hammer 自己的两条高层写入链路（2026-09 新版已在活体上验证）：

    * **keyvalue**（spawnflags / speed / rendercolor / targetname / model ...）：
      `sub_18083E0D0(entity, name, value)` —— 实体属性全部以 AT_STRING 存储
      （实测在 182 个实体上逐个属性复查：数值/向量型 keyvalue 也是字符串，
      如 `rendercolor = "255 255 255"`、`movedir = "0 0 0"`），所以**数值/向量
      参数同样按字符串传入**（如 `spawnflags="3"`、`rendercolor="255 0 0"`）。
      该函数属性缺失时以 AT_STRING 创建，并在值变化后触发类回调、targetname
      名字索引更新与包围盒/脏通知。
    * **变换**（origin / angles / scales）：`sub_18086B550(entity, name, value, 0)`
      —— 这三个名字在属性表里是「变换 pin」，写它们会直接落到 CMapEntity 的
      原生 Vec3D 成员（+0xA0 / +0xAC / +0xB8），而不是属性链；用 keyvalue
      写入器会在属性链上凭空造出同名 AT_STRING（不生效）。

    Args:
        entity: 实体地址（cs2_entity_list 给出）。
        name: 参数名，如 'targetname' / 'spawnflags' / 'rendercolor' / 'origin'。
        value: 字符串形式的值，如 '3' / '255 0 0' / '128 256 64'（空串表示清空）。
        history: 默认 True —— 先压一个具名 Ctrl+Z 步并登记被改节点（改动前状态），
            使这次修改能被 Hammer 的 Ctrl+Z 撤销/重做。批量改同一批属性时可传 False
            只在自己的循环里压一次步，避免每改一个属性就多一个撤销步。
    """
    try:
        ent = _parse_addr(entity)
        props = _entity_class_props(ent)
        xform_off = TRANSFORM_ATTR_OFFSETS.get(name.lower())
        if xform_off is not None:
            rva = RVA_ENTITY_SET_NODE_ATTR
            args = [ent, f"str:{name}", f"str:{value}", 0]
            before = "%.3f %.3f %.3f" % _read_vec3(ent + xform_off)
            kind = "变换(原生成员)"
        else:
            if not props:
                return f"实体 {ent:#x} 没有 entity_properties，无法写 keyvalue"
            rva = RVA_ENTITY_SET_KEYVALUE
            args = [ent, f"str:{name}", f"str:{value}"]
            attr = _dm_find_attr(props, name) or _dm_find_attr(ent, name)
            before = _dm_attr_value(attr) if attr else None
            kind = "keyvalue"

        um = _undo_manager_addr()
        hist_note = ""
        if history:
            # 让这次修改能被 Hammer 的 Ctrl+Z 撤销：开一个具名步，并**先**登记被改节点的
            # 改动前状态（Hammer 自己改属性/变换也是这个顺序，见 REVERSE_NOTES §17.14）。
            same = (before == value) if xform_off is None else _transform_matches(before, value)
            if same:
                hist_note = "  值未变化，未新增 Ctrl+Z 步"
            else:
                try:
                    undo_h, _ = _find_map_histories(_doc_of_element(ent))
                    _hist_push_step(undo_h, f"cs2: set {name}")
                    _hist_record_node(undo_h, ent)
                    _hist_notify(undo_h)
                    hist_note = f"  Ctrl+Z 步: {_hist_state(undo_h)}"
                except Exception as e:  # noqa: BLE001
                    hist_note = f"  ⚠ 记 Ctrl+Z 历史失败（写入照常）: {type(e).__name__}: {e}"
        undo_before = _read_int(um + UNDO_MGR_OFF_UNDO_COUNT, "u32")
        undo_was_off = _ensure_undo_enabled()
        _undo_scope_begin(f"cs2 set {name}")
        try:
            resp = _get_pipe().call("call_function", {
                "address": _hammer_addr(rva),
                "args": args,
                "on_main_thread": True,
                "timeout_ms": 15000,
            })
            if "error" in resp:
                return f"INJECTED_DLL_ERROR: {resp['error']}"
            result = resp["result"]
            status = result.get("main_thread_status", 0)
            if status != 0:
                return (f"ERROR 主线程派发失败 (main_thread_status={status}): "
                        f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}")
            ret = result["ret_hex"]
        finally:
            _undo_scope_end()
        undo_after = _read_int(um + UNDO_MGR_OFF_UNDO_COUNT, "u32")

        attr2 = 0
        if xform_off is not None:
            after = "%.3f %.3f %.3f" % _read_vec3(ent + xform_off)
            ok = "已生效" if _transform_matches(after, value) else "读回值不一致"
        else:
            attr2 = _dm_find_attr(props, name) or _dm_find_attr(ent, name)
            after = _dm_attr_value(attr2)
            ok = ("已生效(新建属性)" if before is None else "已生效") if after == value \
                else "读回值不一致（可能被类回调改写）"
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    undo_note = (f"  Datamodel undo 栈: {undo_before} -> {undo_after}"
                 + ("（本次顺带打开了 undo 总开关）" if undo_was_off else ""))
    return (
        f"设置 {name} = {value!r}  [{ok}]  ({kind})\n"
        f"  entity = {ent:#x}  props = {props:#x}\n"
        f"  attr   = {attr2:#x}\n"
        f"  读回   : {before!r} -> {after!r}\n"
        f"{undo_note}\n"
        f"{hist_note}\n"
        f"  setter ret = {ret}"
    )


def _transform_matches(after: str, value: str) -> bool:
    """把读回的 'x y z' 和目标字符串都解析成浮点后比较（容忍格式差异）。

    注意 Hammer 只按空白分隔解析（',' 会被当成终止符），所以这里不做分隔符兼容。
    """
    try:
        got = [float(x) for x in after.split()]
        want = [float(x) for x in value.split()]
    except ValueError:
        return after.strip() == value.strip()
    return len(got) == len(want) and all(abs(a - b) < 1e-4 for a, b in zip(got, want))


def cs2_entity_set_transform(entity: str, origin: str = "", angles: str = "",
                             scales: str = "") -> str:
    """一次性设置实体变换（origin / angles / scales，留空 = 该分量不动）。

    三个分量都是 CMapEntity 的原生 Vec3D 成员（`+0xA0` / `+0xAC` / `+0xB8`），
    走 `sub_18086B550(entity, name, "x y z", 0)`（就是 `cs2_entity_set_attr`
    写变换用的同一个函数），因此立即生效、也不会在属性链上留同名 AT_STRING。
    值用**空格**分隔（Hammer 只按空白解析，逗号会被当终止符）。

    Args:
        entity: 实体地址。
        origin: 'x y z'（世界坐标，如 '128 256 64'）。
        angles: 'pitch yaw roll'（度，如 '0 90 0'）。
        scales: 'sx sy sz'（如 '2 2 2'）。
    """
    want = [(n, v) for n, v in (("origin", origin), ("angles", angles),
                                ("scales", scales)) if v.strip()]
    if not want:
        return "至少要给出 origin / angles / scales 之一"
    try:
        ent = _parse_addr(entity)
        before = {n: _read_vec3(ent + TRANSFORM_ATTR_OFFSETS[n]) for n, _ in want}
        lines, failed = [], []
        for n, v in want:
            resp = _get_pipe().call("call_function", {
                "address": _hammer_addr(RVA_ENTITY_SET_NODE_ATTR),
                "args": [ent, f"str:{n}", f"str:{v}", 0],
                "on_main_thread": True,
                "timeout_ms": 15000,
            })
            if "error" in resp:
                failed.append(f"{n}: {resp['error']}")
                continue
            status = resp["result"].get("main_thread_status", 0)
            if status != 0:
                failed.append(f"{n}: 主线程派发失败 (status={status})")
                continue
            lines.append((n, v, resp["result"]["ret_hex"]))
        after = {n: _read_vec3(ent + TRANSFORM_ATTR_OFFSETS[n]) for n, _ in want}
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    out = [f"设置变换  (entity={ent:#x})"]
    for n, v, ret in lines:
        ok = "已生效" if _transform_matches("%.3f %.3f %.3f" % after[n], v) \
            else "读回值不一致"
        out.append(f"  {n}: {v!r} -> (%.3f %.3f %.3f)  [{ok}]  ret={ret}" % after[n])
        out.append(f"      原值 (%.3f %.3f %.3f)" % before[n])
    for f in failed:
        out.append(f"  {f}")
    out.append("  注: 变换写原生成员，不进 Datamodel undo 栈；要留存请显式保存")
    return "\n".join(out)


def cs2_entity_create(classname: str = "", name: str = "", doc: str = "") -> str:
    """新建一个地图实体（纯 hammer.dll 底层链路，不用 UI/快捷键）。

    调用链与 Hammer **拖放放置对象**完全同路（`sub_180180190` = mapviewdroptarget.cpp），
    全部在 hammer.dll 内、不用任何 UI：

      1) 建元素：CDataModel::CreateElement `sub_1805BBB90(dm,"CMapEntity",name,1,0)`
           -> `sub_1805BA670` 取空闲句柄 -> `sub_1805BB7F0` 查元素工厂表
           -> 工厂槽0 Create `sub_180898D10` = new(6232) + CMapEntity 构造 `sub_180811220`
      2) `vfn2144(entity, classname, 0, 0)`          官方 SetClassName
      3) `sub_180866D70(entity, 0)`                 官方「设类名后置节点状态」
      4) `sub_180879170(doc, entity, 0)`            ★ 官方 CMapNode::AddChild —— 挂进世界
         （第一参数是 **CMapDoc**；函数内默认锚点 `*(doc+0x88)` 就是 CMapWorld）

    ⚠ 第 4 步是关键：之前只建元素不挂世界，所以 `cs2_entity_list` 看不到、UI 也不显示。
    ⚠ 不要改用 `sub_1805C81C0(world, 3)` 这种粗粒度置脏 —— 实测会触发病态的整世界重建
    （`cs2_entity_list` 从 ~1s 变成 200s，最终把主线程拖死）。AddChild 内部自己会更新索引。

    **会写进 Hammer 的 Ctrl+Z 历史**（2026-09-27 新增，见 REVERSE_NOTES.md §15.10）：
    挂进世界后压一个具名步 `cs2: create <类名>` 并把该对象登记为「新增」，
    于是 Ctrl+Z 能撤销掉这次新建（撤销/重做由 Hammer 自己处理，无需我们实现）。

    Args:
        classname: FGD 类名（如 'info_player_start'）。留空则只建一个空 CMapEntity。
                   func_button/func_brush 等也只创建实体节点，不自动生成或绑定 mesh。
                   用 cs2_entity_get_meshes 检查几何；带盒形笔刷用 cs2_entity_create_brush。
        name: 元素 name。留空由 Hammer 自行命名。
        doc: 目标地图文档（多文档**务必指定**）：留空 = 清单第一个；数字 = 索引；
             其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    return create_entity(classname=classname, name=name, doc=doc).report


def create_entity(classname: str = "", name: str = "", doc: str = "", *, document: int | None = None) -> EditResult:
    """Internal editing operation; returns typed status and any allocated address."""
    ent: int | None = None
    steps: list[str] = []
    add_err = ""
    try:
        doc = document if document is not None else _map_doc(doc)   # 参数是文档选择器，这里换成 CMapDoc 地址
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
        children_before = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")

        undo_was_off = _ensure_undo_enabled()
        _undo_scope_begin(f"cs2 create entity {classname or ENTITY_DMX_TYPE}")
        try:
            ret, err = _call_fn(RVA_DATAMODEL_CREATE_ELEMENT, [
                _hammer_base() + RVA_CDATAMODEL_GLOBAL,
                f"str:{ENTITY_DMX_TYPE}",
                f"str:{name}" if name else 0,
                ENTITY_CREATE_FLAGS,
                0,
            ], timeout=20000)
            if err:
                return EditResult(ok=False, report=(f"ERROR 建元素失败: {err}"), element=ent)
            steps.append(f"  CreateElement   ret = {ret}")
            handle = int(ret, 16) & 0xFFFFFFFF
            if handle == INVALID_DMX_HANDLE:
                return (EditResult(ok=False, report=("ERROR CDataModel::CreateElement 返回 0xFFFFFFFF（创建失败）："
                        "检查 hammer.dll 是否注册了 'CMapEntity' 元素工厂"), element=ent))
            ent = _resolve_handle(handle)

            if classname:
                ret2, err2 = _call_vfn(ent, ENTITY_VFN_SET_CLASSNAME,
                                       [f"str:{classname}", 0, 0], timeout=20000)
                steps.append(f"  vfn2144 SetClassName ret = {ret2}"
                             + (f"  [{err2}]" if err2 else ""))
                # vfn2144 不一定改属性链上的字符串，补一次属性直写保证存档正确
                ret3, err3 = _call_fn(RVA_ENTITY_SET_KEYVALUE,
                                      [ent, "str:classname", f"str:{classname}"])
                steps.append(f"  写 classname 属性   ret = {ret3}"
                             + (f"  [{err3}]" if err3 else ""))

            ret, err = _call_fn(RVA_NODE_POST_CLASS, [ent, 0])
            steps.append(f"  PostClass       ret = {ret}" + (f"  [{err}]" if err else ""))
            ret, err = _call_fn(RVA_NODE_ADD_CHILD, [doc, ent, 0], timeout=20000)
            steps.append(f"  AddChild        ret = {ret}" + (f"  [{err}]" if err else ""))
            add_err = err
        finally:
            scope_committed = _undo_scope_end()

        children_after = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")
        in_world = handle in (_dm_array_handles(world, "children") or [])
        parent_ret, _perr = _call_fn(RVA_NODE_GET_PARENT, [ent])
        parent = int(parent_ret, 16) if parent_ret else 0
        props = _entity_class_props(ent) if ent else 0
        cls = _dm_attr_value(_dm_find_attr(props, "classname")) if props else None

        # 记进 Hammer 的 Ctrl+Z 历史（REVERSE_NOTES.md §15.10）。
        # 放在操作**之后**：新建用 kind=2（不读父节点），所以不依赖顺序，
        # 这样万一建/挂失败也不会留下空步。
        if in_world:
            try:
                undo_hist, _redo_hist = _find_map_histories(doc)
                hist_before = _hist_state(undo_hist)
                # 步名保持 ASCII（管道是 ANSI，中文会变 `??`，见 _hist_push_step）
                _hist_push_step(undo_hist, f"cs2: create {classname or ENTITY_DMX_TYPE}")
                node = _hist_record_object(undo_hist, ent, added=True)
                _hist_notify(undo_hist)
                hist_note = (f"  Ctrl+Z 历史: {hist_before} -> {_hist_state(undo_hist)}"
                             f"  记录 node={node:#x}")
            except Exception as e:  # noqa: BLE001
                hist_note = f"  ⚠ 未记入 Ctrl+Z 历史（{type(e).__name__}: {e}）"
        else:
            hist_note = "  ⚠ 未挂进世界，跳过 Ctrl+Z 历史记录"
    except ConnectionError as e:
        return EditResult(ok=False, report=(f"ERROR 管道未连接: {e}"), element=ent)
    except Exception as e:  # noqa: BLE001
        return EditResult(ok=False, report=(f"ERROR {type(e).__name__}: {e}"), element=ent)

    ok = ""
    if classname:
        ok = "  [类名已生效]" if cls == classname else f"  [读回 {cls!r}，与请求不一致]"
    mounted = "已挂进世界 ✅" if in_world and parent == world else \
        ("已在 world.children 里" if in_world else "❌ 未挂进世界")
    return (
        EditResult(ok=bool(in_world and parent == world and (not classname or cls == classname) and not add_err), report=(f"新建实体: handle = {handle:#x}  element = {ent:#x}{ok}\n"
        f"  name      = {name!r}\n"
        f"  classname = {cls!r}\n"
        f"  props     = {props:#x}\n"
        + "\n".join(steps) + "\n"
        f"  world {world:#x} 子节点数 {children_before} -> {children_after}  "
        f"父节点 = {parent:#x}  -> {mounted}\n"
        f"  undo: scope_committed={scope_committed}"
        + ("（本次顺带打开了 Datamodel undo 总开关）" if undo_was_off else "") + "\n"
        + hist_note
        + (f"\n  ⚠ AddChild 失败: {add_err}" if add_err else "")), element=ent)
    )


def cs2_entity_delete(entity: str, notify: bool = True) -> str:
    """删除一个实体（= 把它整棵子树从父节点上摘除），纯 hammer.dll 底层调用。

    这是 `cs2_entity_create` 里 AddChild 的**对偶**（见 REVERSE_NOTES.md §15.9）：

      1) `sub_180864EA0(entity)`                     取父节点
      2) `parent->vfn0x1D0(entity, notify)`          ★ 官方「移除子节点」虚函数
         · CMapWorld  +0x1D0 -> `sub_180925C60`（第三参数透传）
         · CMapEntity +0x1D0 -> `sub_18084F400`（notify 非 0 时多做 doc 侧簿记）
         · CMapGroup  等 6 个类 -> `sub_1809EB760`，**内部强制 notify=1**
      函数内同步更新父节点的 `children` DMX 属性（type=33 元素句柄数组，与原生
      `+0x1F8` 计数 / `+0x200` 句柄表同构）——实测两边逐项一致，所以删除结果
      **会写入 .vmap**，不是只改内存镜像。

    **会写进 Hammer 的 Ctrl+Z 历史**（2026-09-27 新增，见 REVERSE_NOTES.md §15.10）：
    摘除前先压一个具名步 `cs2: delete <类名> (<targetname>)` 并把该对象登记为「移除」，
    于是 Ctrl+Z 能把实体挂回来、Ctrl+Y 再删掉（撤销/重做由 Hammer 自己处理）。
    ⚠ 记录**必须在摘除之前** —— 记录函数会读 `node->vfn64()`（= 父节点）存起来供撤销挂回，
    而摘除后它立刻归 0，先删后记会导致撤销无处可挂。

    ⚠ 已知语义（2026-09-27 实测）：
      · 被摘下的 CDmElement **仍留在 CDataModel 元素表里**（孤儿），本会话内不回收；
        它已不属于世界树，`cs2_entity_list` / `cs2_mesh_list` 都看不到。
        **这是撤销的前提**（Hammer 靠元素 id 把它挂回去），所以别改成真销毁。
      · 实体自带的 CMapMesh 等子节点随整棵子树一起脱离世界（不做逐个递归摘除）。
      · `notify` 必须保持 True：实测 `notify=1` 会顺带把 Hammer 的名字/选择索引收拾干净，
        而 `notify=0`（早期探针）会留下「outliner 里看得到、但选不中、属性打不开」的幽灵。

    Args:
        entity: 实体地址（cs2_entity_list 给出）。
        notify: 是否执行 doc 侧收尾通知，默认 True（与官方各类虚表槽实现一致）。
    """
    try:
        ent = _parse_addr(entity)
        base = _hammer_base()
        vtable = _read_int(ent, "u64")
        if vtable == base + RVA_CMAPWORLD_VTABLE:
            return f"拒绝：{ent:#x} 是 CMapWorld（世界根），不能删除。"
        ent_vtable = base + RVA_CMAPENTITY_VTABLE
        mesh_vtable = base + RVA_CMAPMESH_VTABLE
        is_entity = vtable == ent_vtable
        if is_entity:
            try:
                attrs0 = _entity_get_attrs(ent, ("classname", ENTITY_TARGETNAME_ATTR))
            except Exception:  # noqa: BLE001
                attrs0 = {}
            label = (f"classname={attrs0.get('classname')!r}  "
                     f"targetname={attrs0.get(ENTITY_TARGETNAME_ATTR)!r}")
            step_name = f"cs2: delete {attrs0.get('classname') or ENTITY_DMX_TYPE}"
            tname = attrs0.get(ENTITY_TARGETNAME_ATTR)
            if tname:
                step_name += f" ({tname})"
        else:
            label = f"vtable=RVA {vtable - base:#x}（非 CMapEntity）"
            step_name = f"cs2: delete node RVA {vtable - base:#x}"

        doc = _doc_of_element(ent)   # 多文档：按元素反查所属文档，别写错历史栈
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
        parent_hex, perr = _call_fn(RVA_NODE_GET_PARENT, [ent])
        if perr:
            return f"ERROR 取父节点失败: {perr}"
        parent = int(parent_hex, 16) if parent_hex else 0

        table, cap = _dm_table()
        handle = next((i for i, e in enumerate(table) if e == ent), None)
        if not parent:
            return (f"{ent:#x} 没有父节点（已是游离节点，可能此前被摘除过）。\n"
                    f"  元素表 handle={handle}")

        # 子树规模（不递归摘除，只统计有多少节点跟着一起脱离世界）
        n_ent = n_mesh = n_other = 0
        for el, vt in _walk_elements(ent, table, cap):
            if el == ent:
                continue
            if vt == ent_vtable:
                n_ent += 1
            elif vt == mesh_vtable:
                n_mesh += 1
            else:
                n_other += 1

        cnt_before = _read_int(parent + NODE_OFF_CHILD_COUNT, "u32")

        # ★ 记进 Hammer 的 Ctrl+Z 历史（REVERSE_NOTES.md §15.10）—— 必须在**摘除之前**：
        # 记录函数会读 `node->vfn64()`（= 父节点）存进命令包装供撤销挂回，摘除后它归 0。
        hist_before = hist_note = ""
        undo_hist = 0
        try:
            undo_hist, _redo_hist = _find_map_histories(doc)
            hist_before = _hist_state(undo_hist)
            _hist_push_step(undo_hist, step_name)
            _hist_record_object(undo_hist, ent, added=False)
        except Exception as e:  # noqa: BLE001
            undo_hist = 0
            hist_note = f"  ⚠ 未记入 Ctrl+Z 历史（{type(e).__name__}: {e}）"

        t0 = time.perf_counter()
        ret, err = _call_vfn(parent, NODE_VFN_REMOVE_CHILD,
                             [ent, 1 if notify else 0], timeout=30000)
        elapsed = time.perf_counter() - t0
        cnt_after = _read_int(parent + NODE_OFF_CHILD_COUNT, "u32")
        parent2_hex, _perr2 = _call_fn(RVA_NODE_GET_PARENT, [ent])
        parent2 = int(parent2_hex, 16) if parent2_hex else 0
        still_in_attr = handle in _dm_array_handles(parent, "children") if handle is not None else None

        if undo_hist:
            try:
                _hist_notify(undo_hist)
                hist_note = (f"  Ctrl+Z 历史: {hist_before} -> {_hist_state(undo_hist)}"
                             f"  记录 node={ent + NODE_IFACE_OFFSET:#x}")
            except Exception as e:  # noqa: BLE001
                hist_note = f"  ⚠ Ctrl+Z 历史已记录但通知监听者失败：{type(e).__name__}: {e}"
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    where = "CMapWorld" if parent == world else f"节点 {parent:#x}"
    ok = (not err and parent2 == 0 and cnt_after == cnt_before - 1 and still_in_attr is False)
    lines = [
        f"删除实体 {ent:#x}",
        f"  属性       : {label}",
        f"  父节点     : {parent:#x}（{where}）",
        f"  随之脱离的子树: 实体 {n_ent} + mesh {n_mesh} + 其他 {n_other}",
        f"  vfn{NODE_VFN_REMOVE_CHILD:#x}(parent, child{', 1' if notify else ', 0'})"
        f" -> ret={ret}  err={err!r}  用时 {elapsed:.3f}s",
        f"  父节点子节点数: {cnt_before} -> {cnt_after}",
        f"  GetParent     : {parent:#x} -> {parent2:#x}",
        f"  仍在 children 属性里: {still_in_attr}",
    ]
    if ok:
        lines.append("✔ 已从世界树摘除（children 属性同步，保存后不会写回 .vmap）")
    else:
        lines.append("⚠ 摘除结果与预期不符，请核对上面各项")
    if hist_note:
        lines.append(hist_note)
    lines.append(f"  元素仍在元素表，handle={handle}（孤儿 —— 撤销要靠它挂回去）")
    return "\n".join(lines)


def cs2_entity_set_classname(entity: str, classname: str) -> str:
    """设置实体类名（等价于 Hammer 拖放/属性面板改 Entity Class），纯 DLL 调用。

    2026-09-27 更正：官方改类名**确实走 vfn2144**（`sub_180896390`，见拖放处理器
    `sub_180180190`），此前判定「无效」是因为当时实体还没被挂进世界、节点状态不对。
    现在按官方顺序做两件事：

      1) `vfn2144(entity, classname, 0, 0)` —— 重建游戏类绑定（ent+0x550 / +0x558）
         并刷新 props、重建 CParticleHelper 等依附对象；
      2) 属性直写 `sub_18062C9A0(props, "classname", value, 1)` —— 保证 .vmap 里
         存的就是新类名（vfn2144 不一定改属性链上的字符串）；
      3) `sub_180866D70(entity, 0)` —— 官方的「设类名后置节点状态」。

    Args:
        entity: 实体地址（cs2_entity_list 给出）。
        classname: FGD 类名，如 'info_particle_system'。
    """
    steps: list[str] = []
    try:
        ent = _parse_addr(entity)
        props = _entity_class_props(ent)
        owner = props or ent
        attr = _dm_find_attr(owner, "classname")
        before = _dm_attr_value(attr) if attr else None

        undo_was_off = _ensure_undo_enabled()
        _undo_scope_begin(f"cs2 set classname {classname}")
        try:
            r2ret, r2err = _call_vfn(ent, ENTITY_VFN_SET_CLASSNAME,
                                     [f"str:{classname}", 0, 0], timeout=20000)
            steps.append(f"  vfn2144 SetClassName  ret = {r2ret}"
                         + (f"  [{r2err}]" if r2err else ""))

            resp = _get_pipe().call("call_function", {
                "address": _hammer_addr(RVA_PROPS_SET_STRING_ATTR),
                "args": [owner, "str:classname", f"str:{classname}", 1],
                "on_main_thread": True,
                "timeout_ms": 15000,
            })
            if "error" in resp:
                return f"INJECTED_DLL_ERROR: {resp['error']}"
            result = resp["result"]
            status = result.get("main_thread_status", 0)
            if status != 0:
                return (f"ERROR 主线程派发失败 (main_thread_status={status}): "
                        f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}")
            ret = result["ret_hex"]
            steps.append(f"  写 classname 属性     ret = {ret}")

            ret, err = _call_fn(RVA_NODE_POST_CLASS, [ent, 0])
            steps.append(f"  PostClass             ret = {ret}" + (f"  [{err}]" if err else ""))
        finally:
            scope_committed = _undo_scope_end()

        attr2 = _dm_find_attr(owner, "classname")
        after = _dm_attr_value(attr2) if attr2 else None
        game_class = _read_int(ent + 0x550, "u64")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    ok = "已生效" if after == classname else "读回值不一致"
    return (
        f"设置 classname = {classname!r}  [{ok}]\n"
        f"  entity = {ent:#x}  owner = {owner:#x}\n"
        f"  读回   : {before!r} -> {after!r}\n"
        + "\n".join(steps) + "\n"
        f"  游戏类 ent+0x550 = {game_class:#x}\n"
        f"  undo: scope_committed={scope_committed}"
        + ("（本次顺带打开了 Datamodel undo 总开关）" if undo_was_off else "")
    )
