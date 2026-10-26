"""Hammer scene operations."""
from __future__ import annotations
import struct
from typing import Any
from .datamodel import (
    _dm_handle_element,
    _dm_table,
    _entity_get_attrs,
)
from .offsets import (
    CMAPDOC_WORLD_OFFSET,
    ENTITY_OFF_ORIGIN,
    ENTITY_TARGETNAME_ATTR,
    NODE_OFF_CHILD_COUNT,
    NODE_OFF_CHILD_HANDLES,
    RVA_CMAPENTITY_VTABLE,
    RVA_CMAPMESH_VTABLE,
    RVA_NODE_GET_PARENT,
)
from .runtime import (
    _call_fn,
    _get_pipe,
    _hammer_base,
    _read_bytes,
    _read_int,
    _read_vec3,
)


def _map_doc(sel: str = "") -> int:
    """取 CMapDoc。Hammer 可以**同时打开多个地图文档**（实测），必须能指定目标。

    枚举在 DLL 侧完成（app->session 数组->+0x138 wrapper->内嵌 +0x10），这里经
    `map_list_docs` 拿清单后按 `sel` 选：

    - `sel` 留空 -> 清单第一个（`docs[0]`，**历史行为**，不确定时别依赖它）
    - `sel` 是数字 -> 清单下标（`cs2_map_list_docs` 里那个 index）
    - 其余 -> 按**路径子串**匹配（如 `"untitled_2"`、`"ze_surf_easy.vmap"`），
      大小写不敏感、忽略 `/` 与 `\\` 差异；匹配到多个时报错要求更具体

    ⚠ 多文档时 DLL 的枚举顺序 = `CHammerApp` 会话数组顺序，**不等于**当前聚焦的窗口。
    不知道索引时先 `cs2_map_list_docs` 看清单。
    """
    resp = _get_pipe().call("map_list_docs", {})
    if "error" in resp:
        raise RuntimeError(resp["error"])
    docs = resp["result"].get("docs", [])
    if not docs:
        raise RuntimeError("当前没有打开的地图文档")
    sel = (sel or "").strip()
    if not sel:
        return int(docs[0]["address"], 16)
    if sel.isdigit():
        for d in docs:
            if int(d["index"]) == int(sel):
                return int(d["address"], 16)
        raise RuntimeError(f"没有 index={sel} 的文档（共 {len(docs)} 个）")
    needle = sel.lower().replace("\\", "/")
    hits = [d for d in docs if needle in str(d["name"]).lower().replace("\\", "/")]
    if len(hits) == 1:
        return int(hits[0]["address"], 16)
    names = "\n".join(f"  [{d['index']}] {d['name']}" for d in docs)
    if not hits:
        raise RuntimeError(f"没有路径含 {sel!r} 的文档（共 {len(docs)} 个）：\n{names}")
    raise RuntimeError(f"{sel!r} 匹配到多个文档，请更具体：\n{names}")


def _doc_of_element(el: int) -> int:
    """反查元素所属的 CMapDoc —— **多文档时写东西进历史必须用它**。

    沿 `RVA_NODE_GET_PARENT` 一路向上收集祖先地址（mesh 通常 1~2 跳就到顶），
    再与各文档的 `CMapDoc+0x88`(world) 比对。归属未知或不唯一时拒绝。
    """
    chain = []
    cur = el
    for _ in range(64):
        if not cur:
            break
        if cur in chain:
            raise RuntimeError('element parent chain contains a cycle; document ownership unverified')
        chain.append(cur)
        p, err = _call_fn(RVA_NODE_GET_PARENT, [cur])
        if err:
            raise RuntimeError('element parent query failed; document ownership unverified: ' + str(err))
        cur = int(p, 16) if p else 0
    else:
        raise RuntimeError('element parent chain exceeds bound; document ownership unverified')
    if chain:
        matches = set()
        response = _get_pipe().call("map_list_docs", {})
        if 'error' in response:
            raise RuntimeError('document enumeration failed: ' + str(response['error']))
        for d in response.get("result", {}).get("docs", []):
            addr = int(d["address"], 16)
            if _read_int(addr + CMAPDOC_WORLD_OFFSET, "u64") in chain:
                matches.add(addr)
        if len(matches) == 1:
            return matches.pop()
    raise RuntimeError('element document ownership missing or ambiguous; refusing active-document fallback')


def _walk_elements(root: int, table: list[int] | None = None, cap: int = 0,
                   strict: bool = False):
    """从 CMapWorld 递归产出全部场景元素 -> (CDmElement*, vtable)。

    节点布局：+0x00 vtable / +0x1F8 子节点数 / +0x200 int32 句柄数组；句柄经
    **元素表直查**（`_dm_handle_element`）解析成 CDmElement*。每个节点只用
    **一次块读取到 vtable + 子节点字段**（都在 0x208 字节内），再加一次子节点数组读；
    用栈做深度优先，seen 防环。
    """
    if table is None:
        table, cap = _dm_table()
    stack: list[tuple[int, int]] = [(root, 0)]
    seen: set[int] = set()
    while stack:
        node, depth = stack.pop()
        if strict and depth > 64:
            raise RuntimeError(f"scene traversal exceeded depth 64 at {node:#x}")
        if not node or node in seen or depth > 64:
            continue
        seen.add(node)
        try:
            raw = _read_bytes(node, NODE_OFF_CHILD_HANDLES + 8)
        except Exception:  # noqa: BLE001
            if strict:
                raise
            yield node, 0
            continue
        yield node, int.from_bytes(raw[0:8], "little")
        count = int.from_bytes(raw[NODE_OFF_CHILD_COUNT:NODE_OFF_CHILD_COUNT + 4], "little")
        arr = int.from_bytes(raw[NODE_OFF_CHILD_HANDLES:NODE_OFF_CHILD_HANDLES + 8], "little")
        if count > 1_000_000 or (count and not arr):
            if strict:
                raise RuntimeError(f"node {node:#x} has invalid child array")
            continue
        if count <= 0:
            continue
        try:
            kids_raw = _read_bytes(arr, count * 4)
        except Exception:  # noqa: BLE001
            if strict:
                raise
            continue
        children: list[int] = []
        for i in range(count):
            handle = int.from_bytes(kids_raw[i * 4:i * 4 + 4], "little", signed=True)
            if handle <= 0:
                if strict:
                    raise RuntimeError(f"node {node:#x} has invalid child handle {handle}")
                continue
            child = _dm_handle_element(handle, table, cap)
            if strict and not child:
                raise RuntimeError(f"node {node:#x} has unresolved child handle {handle:#x}")
            if child and child not in seen:
                children.append(child)
        # 逆序压栈，保持数组原顺序输出
        for child in reversed(children):
            stack.append((child, depth + 1))


def list_entities(limit: int = 200, doc: str = ""
                  ) -> tuple[list[tuple[int, Any, Any, Any, Any]], int, int, int, int]:
    """返回 (rows[(entity, classname, targetname, origin, nodeID)], 场景元素总数, doc, world, 实体数)。"""
    doc = _map_doc(doc)
    world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
    if not world:
        raise RuntimeError("CMapDoc 里没有 CMapWorld（地图可能还没加载完）")

    table, cap = _dm_table()
    ent_vtable = _hammer_base() + RVA_CMAPENTITY_VTABLE
    ents: list[int] = []
    total = 0
    for el, vt in _walk_elements(world, table, cap):
        total += 1
        if total > 200000:
            break
        if vt == ent_vtable:
            ents.append(el)

    rows: list[tuple[int, Any, Any, Any, Any]] = []
    for ent in ents[:limit]:
        try:
            attrs = _entity_get_attrs(
                ent, ("classname", ENTITY_TARGETNAME_ATTR, "nodeID"))
        except Exception:  # noqa: BLE001
            attrs = {}
        try:
            origin = _read_vec3(ent + ENTITY_OFF_ORIGIN)
        except Exception:  # noqa: BLE001
            origin = None
        rows.append((ent, attrs.get("classname"), attrs.get(ENTITY_TARGETNAME_ATTR),
                     origin, attrs.get("nodeID")))
    return rows, total, doc, world, len(ents)


def _entity_meshes(entity: int, table: list[int], cap: int) -> list[int]:
    """Read owned descendant meshes; nested entities own their own geometry.

    Unlike the diagnostic world walker, fail on unreadable children instead of
    incorrectly reporting an entity as having no mesh.
    """
    base = _hammer_base()
    vt_mesh = base + RVA_CMAPMESH_VTABLE
    vt_ent = base + RVA_CMAPENTITY_VTABLE
    stack = [(entity, 0)]
    seen = set()
    meshes = []
    while stack:
        node, depth = stack.pop()
        if node in seen:
            raise RuntimeError("实体子树出现循环或重复节点，无法确认 mesh 归属")
        if depth > 64 or len(seen) >= 200000:
            raise RuntimeError("实体子树超过安全遍历上限")
        seen.add(node)
        raw = _read_bytes(node, NODE_OFF_CHILD_HANDLES + 8)
        vt = int.from_bytes(raw[:8], "little")
        if node != entity and vt == vt_ent:
            continue
        if vt == vt_mesh:
            meshes.append(node)
        count = int.from_bytes(raw[NODE_OFF_CHILD_COUNT:NODE_OFF_CHILD_COUNT + 4], "little")
        arr = int.from_bytes(raw[NODE_OFF_CHILD_HANDLES:NODE_OFF_CHILD_HANDLES + 8], "little")
        if count > 1000000 or (count and not arr):
            raise RuntimeError(f"节点 {node:#x} 的子节点数组异常")
        if not count:
            continue
        data = _read_bytes(arr, count * 4)
        children = []
        for h in struct.unpack(f"<{count}I", data):
            child = _dm_handle_element(h, table, cap)
            if not child:
                raise RuntimeError(f"节点 {node:#x} 的子句柄 {h:#x} 无法解析")
            children.append((child, depth + 1))
        stack.extend(reversed(children))
    return meshes


def _element_doc_strict(element: int) -> int:
    """Resolve owning document without the legacy docs[0] fallback."""
    worlds = {}
    response = _get_pipe().call("map_list_docs", {})
    if "error" in response:
        raise RuntimeError(response["error"])
    for item in response.get("result", {}).get("docs", []):
        doc = int(item["address"], 16)
        worlds[_read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")] = doc
    node = element
    seen = set()
    for _ in range(65):
        if node in worlds:
            return worlds[node]
        if not node or node in seen:
            break
        seen.add(node)
        ret, err = _call_fn(RVA_NODE_GET_PARENT, [node])
        if err:
            raise RuntimeError(f"读取父节点失败: {err}")
        node = int(ret, 16) if ret else 0
    raise RuntimeError("元素未挂入已打开的地图文档，拒绝默认写入第一个文档")
