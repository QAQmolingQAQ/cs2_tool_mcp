"""Hammer datamodel operations."""
from __future__ import annotations
import struct
from typing import Any
from .offsets import (
    DM_ATTR_TYPE_NAMES,
    ARR_OFF_ALLOC,
    ARR_OFF_DATA,
    ARR_OFF_SIZE,
    ATTR_OFF_NAME,
    ATTR_OFF_NEXT,
    ATTR_OFF_TYPE,
    ATTR_OFF_VALUE,
    DATAMODEL_VFN_RESOLVE_HANDLE,
    DM_ATTR_TYPE_ARRAY_UNK,
    DM_ATTR_TYPE_BOOL,
    DM_ATTR_TYPE_ID,
    DM_ATTR_TYPE_STRING,
    ELEMENT_OFF_ATTR_HEAD,
    ENTITY_PROPS_ATTR_NAME,
    INVALID_DMX_HANDLE,
    MAIN_THREAD_STATUS_NAMES,
    MAX_READ_CHUNK,
    RVA_CDATAMODEL_GLOBAL,
    RVA_DATAMODEL,
    VFN_OFF_INTERN_STRING,
)
from .runtime import (
    _alloc_mem,
    _free_mem,
    _get_pipe,
    _hammer_base,
    _read_bytes,
    _read_int,
    _read_string,
    _write_mem,
)
from .session import (
    get_session,
)


def _resolve_handle(handle: int) -> int:
    """CDataModel 句柄 -> CDmElement*（vtable slot21，字节偏移 168，主线程）。"""
    resp = _get_pipe().call("call_virtual", {
        "this": hex(_hammer_base() + RVA_CDATAMODEL_GLOBAL),
        "vtable_offset": DATAMODEL_VFN_RESOLVE_HANDLE,
        "args": [int(handle)],
        "on_main_thread": True,
        "timeout_ms": 10000,
    })
    if "error" in resp:
        raise RuntimeError(resp["error"])
    result = resp["result"]
    if result.get("main_thread_status", 0) != 0:
        raise RuntimeError(
            f"句柄解析主线程派发失败 (main_thread_status={result.get('main_thread_status')})")
    return int(result["ret_hex"], 16)


def _dm_table() -> tuple[list[int], int]:
    """元素表快照 -> (下标=句柄低 22 位 -> CDmElement*, 容量)。

    g_CDataModel + 0x90 数据指针 / +0x88 容量，16 字节一项（元素指针在 +8）。
    实测 `table[handle & 0x3FFFFF]` 与 vfn168 `_resolve_handle` 逐项一致，
    于是整棵树/整批实体解析**不需要**主线程调用 —— 原先每个子句柄一次
    `call_virtual`，单次 cs2_entity_list 就要 300+ 次主线程往返。

    ⚠ 缓存键必须含 `+0x80` 的**存活元素数**：新建元素时数组指针与容量通常**都不变**
    （只是填了一个旧空槽），只按 (base, arr, cap) 做键会让长驻进程（MCP server）
    一直用过期快照 —— 实测「刚用工具建的笔刷，`cs2_mesh_list` / `cs2_area_query`
    却查不到」（它在世界树里、父节点/子句柄数组都对）。计数变了就重读。
    """
    base = _hammer_base()
    dm = base + RVA_CDATAMODEL_GLOBAL
    arr = _read_int(dm + 0x90, "u64")
    cap = _read_int(dm + 0x88, "u32")
    count = _read_int(dm + 0x80, "u32")      # 存活元素数：新建会 +1，删除的孤儿仍占位
    key = (base, arr, cap, count)
    if get_session().cache.dm_table is not None and key == get_session().cache.dm_table_key:
        return get_session().cache.dm_table, cap
    if not arr or cap <= 0 or cap > 1_000_000:
        raise RuntimeError(f"CDataModel 元素表异常: arr={arr:#x} cap={cap}")
    table = [0] * cap
    for off in range(0, cap * 16, MAX_READ_CHUNK):
        n = min(MAX_READ_CHUNK, cap * 16 - off)
        raw = _read_bytes(arr + off, n)
        for k in range(0, n - 15, 16):
            table[(off + k) // 16] = int.from_bytes(raw[k + 8:k + 16], "little")
    get_session().cache.dm_table, get_session().cache.dm_table_key = table, key
    return table, cap


def _dm_handle_element(handle: int, table: list[int] | None = None,
                       cap: int = 0) -> int:
    """句柄 -> CDmElement*（走元素表；等价 `_resolve_handle`，但不进主线程）。"""
    if not handle or handle == INVALID_DMX_HANDLE:
        return 0
    if table is None:
        table, cap = _dm_table()
    idx = handle & 0x3FFFFF
    return table[idx] if idx < cap else 0


def _dm_handle_map(table: list[int] | None = None, cap: int = 0) -> dict[int, int]:
    """元素地址 -> 句柄（= 元素表下标）。纯本地换算，无 IPC。

    走 `_walk_elements` 只拿到元素地址，而工具输出里的 `h=` 是句柄，需要反查。
    """
    if table is None:
        table, cap = _dm_table()
    return {el: i for i, el in enumerate(table) if el}


def _dm_read_name(nameptr: int) -> str:
    nm = get_session().cache.symbol_names.get(nameptr)
    if nm is None:
        try:
            nm = _read_string(nameptr, 128)
        except Exception:  # noqa: BLE001
            nm = ""
        get_session().cache.symbol_names[nameptr] = nm
    return nm


def _dm_iter_attrs(element: int, maxn: int = 512):
    """按链序产出 `(attr, 名字, 类型码, 值指针)` —— 属性链遍历的唯一实现。

    **块读优化**：CDmAttribute 对象按 0x30 步长连续分配（实测同一元素的链上
    相邻节点地址差恒为 48，偶有跳跃），所以一次块读能覆盖 ~21 个节点，
    只在跳出块时补读 —— 整条链的读取次数从「每节点一次」降到「每块一次」。
    名字走驻留串缓存（命中零额外读取）。
    """
    hdr_len = ATTR_OFF_NAME + 8
    try:
        attr = _read_int(element + ELEMENT_OFF_ATTR_HEAD, "u64")
    except Exception:  # noqa: BLE001
        return
    blk_addr, blk = 0, b""
    for _ in range(maxn):
        if not attr or attr < 0x10000:
            return
        if not (blk_addr and blk_addr <= attr and attr + hdr_len <= blk_addr + len(blk)):
            blk_addr = attr
            try:
                blk = _read_bytes(attr, MAX_READ_CHUNK)
            except Exception:  # noqa: BLE001
                try:  # 块尾可能压到未映射页，退回只读一个节点头
                    blk = _read_bytes(attr, hdr_len)
                except Exception:  # noqa: BLE001
                    return
        off = attr - blk_addr
        nameptr = int.from_bytes(blk[off + ATTR_OFF_NAME:off + ATTR_OFF_NAME + 8], "little")
        nm = _dm_read_name(nameptr) if nameptr >= 0x10000 else ""
        atype = blk[off + ATTR_OFF_TYPE] & 0x3F
        valptr = int.from_bytes(
            blk[off + ATTR_OFF_VALUE:off + ATTR_OFF_VALUE + 8], "little")
        yield attr, nm, atype, valptr
        attr = int.from_bytes(blk[off + ATTR_OFF_NEXT:off + ATTR_OFF_NEXT + 8], "little")


def _dm_find_attrs(element: int, names) -> dict[str, tuple[int, int, int]]:
    """一次遍历属性链，收集 names 里命中的属性 -> {name: (attr, 类型码, 值指针)}。

    找齐 names 即提前结束（不要改成遍历全链，那会把热路径变慢）。
    """
    want = set(names)
    found: dict[str, tuple[int, int, int]] = {}
    for attr, nm, atype, valptr in _dm_iter_attrs(element):
        if nm and nm in want:
            found[nm] = (attr, atype, valptr)
            want.discard(nm)
            if not want:
                break
    return found


def _dm_walk_attrs(element: int, maxn: int = 512) -> list[tuple[str, int, Any]]:
    """遍历**整条**属性链 -> [(名字, 类型码, 值)]（用于「列出全部属性」）。"""
    out: list[tuple[str, int, Any]] = []
    for _attr, nm, atype, valptr in _dm_iter_attrs(element, maxn):
        try:
            val = _dm_value_at(atype, valptr)
        except Exception:  # noqa: BLE001
            val = "<解码失败>"
        out.append((nm or "?", atype, val))
    return out


def _dm_find_attr(element: int, name: str) -> int:
    """在 CDmElement 的属性侵入式链表（头 @+0x48，next @attr+0）上按名查找。

    返回 CDmAttribute*，找不到返回 0。
    """
    got = _dm_find_attrs(element, (name,))
    return got[name][0] if name in got else 0


def _dm_attr_type(attr: int) -> int:
    """CDmAttribute 的类型码（`attr+0x1C` 低 6 位）。"""
    return _read_int(attr + ATTR_OFF_TYPE, "u8") & 0x3F


def _dm_attr_value(attr: int):
    """读 CDmAttribute 的值，按类型码解码（见 DM_ATTR_TYPE_NAMES）。"""
    return _dm_value_at(_dm_attr_type(attr), _read_int(attr + ATTR_OFF_VALUE, "u64"))


def _dm_value_at(atype: int, valptr: int):
    """按（类型码, 值存储指针）解码属性值。

    5=string -> str；2,3,7=int / 8=color -> int；10=vec3 -> (x,y,z)；
    **4=bool -> 只读 1 字节**；**15=id -> 8 字节 ID 的 hex 串**；
    33=元素句柄数组 / 37=字符串数组 -> list；34=数组（元素类型未定）-> 带表头的说明串；
    其余类型返回 '<type=N 原始 …>'（不做猜测）。
    """
    if not valptr:
        return None
    if atype == DM_ATTR_TYPE_STRING:
        cp = _read_int(valptr, "u64")  # 字符串：[值存储] = char*
        return _read_string(cp, 2048) if cp else ""
    if atype == DM_ATTR_TYPE_BOOL:
        # ⚠ 值存储**只有 1 字节**。按 u32 读会把后面 3 字节的未初始化内存当高位
        # （实测 isProceduralEntity 被读成 3472246784 这类垃圾；见 §15.8）
        return _read_bytes(valptr, 1)[0] != 0
    if atype == DM_ATTR_TYPE_ID:
        # 8 字节对象 ID（如 referenceID）。**不要读 16 字节** —— 后 8 字节是相邻内存
        return f"0x{_read_int(valptr, 'u64'):016x}"
    if atype == 1:                     # 元素句柄：无效哨兵显示成「无引用」
        h = _read_int(valptr, "u32")
        return None if h == INVALID_DMX_HANDLE else h
    if atype in (2, 3, 7, 8):          # 整数族 / 颜色：内联 32 位
        return _read_int(valptr, "u32")
    if atype == 10:                    # Vec3D<float>：内联 12 字节
        return struct.unpack("<3f", _read_bytes(valptr, 12))
    if atype in (33, 34, 37):          # 数组：值存储里是 CUtlVector 头
        size = _read_int(valptr + ARR_OFF_SIZE, "u32")
        data = _read_int(valptr + ARR_OFF_DATA, "u64")
        if not size or not data or size > 100000:
            return []
        if atype == 33:
            return list(struct.unpack(f"<{size}I", _read_bytes(data, 4 * size)))
        if atype == DM_ATTR_TYPE_ARRAY_UNK:
            # 已证实是 CUtlVector（hiddenFlags 实测 count=6069 / cap=6069），
            # 但元素宽度还没定（本图里数据全 0），所以先只报表头 + 前几字节
            cap = _read_int(valptr + ARR_OFF_ALLOC, "u32")
            head = _read_bytes(data, min(16, size))
            return (f"<type=34 数组 n={size} cap={cap} 元素类型未定, "
                    f"前 {len(head)}B: {head.hex(' ')}>")
        return [_read_string(_read_int(data + 8 * i, "u64"), 512) or ""
                for i in range(size)]
    raw = _read_bytes(valptr, 16)
    return f"<type={atype} 未解码, 16B: {raw.hex(' ')}>"


def _entity_class_props(entity: int) -> int:
    """实体 -> entity_properties 句柄解析出的 CEditGameClassProps*（classname 在它上面）。

    走元素表直查（`_dm_handle_element`），不再为每个实体做一次主线程调用。
    """
    got = _dm_find_attrs(entity, (ENTITY_PROPS_ATTR_NAME,))
    if ENTITY_PROPS_ATTR_NAME not in got:
        return 0
    valptr = got[ENTITY_PROPS_ATTR_NAME][2]
    if not valptr:
        return 0
    return _dm_handle_element(_read_int(valptr, "u32"))


def _attr_value_at(element: int, name: str) -> tuple[Any, int]:
    """在指定元素链上读属性 -> (值, 所属 element)；不存在返回 (None, 0)。"""
    if not element:
        return None, 0
    got = _dm_find_attrs(element, (name,))
    if name not in got:
        return None, 0
    return _dm_value_at(got[name][1], got[name][2]), element


def _entity_get_attr_value(entity: int, name: str) -> tuple[Any, int]:
    """读实体属性：先查 CEditGameClassProps 链（classname/targetname 等），
    再查实体自身链。返回 (值, 所属 element)；不存在返回 (None, 0)。"""
    val, owner = _attr_value_at(_entity_class_props(entity), name)
    if owner:
        return val, owner
    return _attr_value_at(entity, name)


def _entity_get_attrs(entity: int, names, props: int = -1) -> dict[str, Any]:
    """批量读实体属性（先 props 链后实体链）-> {name: 值}，缺失的名字不出现在结果里。

    与逐个 `_entity_get_attr_value` 语义一致，但 props 链**只遍历一次** ——
    这是 entity_list / area_query 的主要开销来源。
    """
    want = set(names)
    out: dict[str, Any] = {}
    if props == -1:
        props = _entity_class_props(entity)
    if props:
        got = _dm_find_attrs(props, want)
        for nm, (_, atype, valptr) in got.items():
            out[nm] = _dm_value_at(atype, valptr)
        want -= set(got)
    if want:
        got = _dm_find_attrs(entity, want)
        for nm, (_, atype, valptr) in got.items():
            out[nm] = _dm_value_at(atype, valptr)
    return out


def _dm_array_loc(element: int, name: str) -> tuple[int, int, int]:
    """定位元素的「数组」属性 -> (元素个数, 数据指针, 分配个数)；不存在返回 (0,0,0)。

    实测布局（world.children）：值存储 = {u32 size @+0; u32 _ @+4; u64 data @+8; u32 alloc @+0x10}。
    """
    attr = _dm_find_attr(element, name)
    if not attr:
        return 0, 0, 0
    vp = _read_int(attr + ATTR_OFF_VALUE, "u64")
    if not vp:
        return 0, 0, 0
    size = _read_int(vp + ARR_OFF_SIZE, "u32")
    data = _read_int(vp + ARR_OFF_DATA, "u64")
    alloc = _read_int(vp + ARR_OFF_ALLOC, "u32")
    if size > 1_000_000:
        return 0, 0, 0
    return size, data, alloc


def _dm_array_handles(element: int, name: str) -> list[int]:
    """读「元素句柄数组」属性（AT 33，如 children/connectionsData/streams）-> 句柄列表。"""
    size, data, _ = _dm_array_loc(element, name)
    if not size or not data:
        return []
    return list(struct.unpack(f"<{size}I", _read_bytes(data, 4 * size)))


def _dm_array_numbers(element: int, name: str, comps: int = 1) -> list[float]:
    """读基础类型数组属性，返回扁平数值列表（comps=每个元素的 32 位分量数）。

    comps=1 时按 int32 解（materialindex/flags 等），否则按 float 解（position/texcoord/...）。
    """
    size, data, _ = _dm_array_loc(element, name)
    if not size or not data or comps < 1:
        return []
    raw = _read_bytes(data, 4 * comps * size)
    if comps == 1:
        return list(struct.unpack(f"<{size}i", raw))
    return list(struct.unpack(f"<{size * comps}f", raw))


def _dm_array_strings(element: int, name: str) -> list[str]:
    """读字符串数组属性（AT 37，如 materials）-> list[str]；元素是 CUtlString（8 字节）。"""
    size, data, _ = _dm_array_loc(element, name)
    if not size or not data:
        return []
    raw = _read_bytes(data, 8 * size)
    out: list[str] = []
    for i in range(size):
        p = struct.unpack_from("<Q", raw, 8 * i)[0]
        out.append(_read_string(p, 1024) if p else "")
    return out


def _dm_attr_element(element: int, name: str) -> int:
    """读「元素句柄」属性（AT 1）-> 解析出的元素指针；不存在/无效返回 0。"""
    attr = _dm_find_attr(element, name)
    if not attr:
        return 0
    vp = _read_int(attr + ATTR_OFF_VALUE, "u64")
    if not vp:
        return 0
    handle = _read_int(vp, "u32")
    if not handle or handle == INVALID_DMX_HANDLE:
        return 0
    return _resolve_handle(handle)


def _enum_elements(limit: int = 0, table: list[int] | None = None, cap: int = 0):
    """枚举 datamodel 元素表 -> (handle, element, vtable)。句柄 = 表下标。

    ⚠ **旧版默认 `limit=8192` 配合 `min(cap, limit)` 会静默截断大图的表**：
    ze_surf_easy 实测 `cap=97,102` / 非零 12,958，只扫到 8.4% —— 于是
    `cs2_mesh_list` 少报（338 vs 实际 4124）、`cs2_area_query` 漏掉 handle≥8192 的对象。
    现在 `limit<=0`（默认）表示**扫全表**。

    表数据走 `_dm_table()` 批量读（97k 项 ≈ 190 次块读，0.3s），只对非零项读一次 vtable。
    代价：每个非零项 1 次 `read_value`（大图约 1.3 万次）。
    **列举地图对象请优先用 `_walk_elements`** —— 它只访问场景内的元素，且顺带拿到
    vtable（不再多读一次），大图上便宜得多。本函数的价值在于「能看到不在 children
    树里的元素」（如刚新建、尚未挂进世界的），做诊断时用它。
    """
    if table is None:
        table, cap = _dm_table()
    n = cap if limit <= 0 else min(cap, limit)
    base = _hammer_base()
    for i in range(n):
        el = table[i]
        if not el or el < 0x10000 or el > 0x7FFFFFFFFFFF:
            continue
        try:
            vt = _read_int(el, "u64")
        except Exception:  # noqa: BLE001
            continue
        if not vt or vt < base or vt > base + 0x4000000:
            continue
        yield i, el, vt


def _intern_string(value: str) -> int:
    """把字符串驻留成 CUtlSymbolLarge，返回「存放该符号的」内存地址。

    Datamodel 的字符串属性存的是驻留符号而不是普通 C 字符串，
    所以 SetValue 前必须先把新值 intern 一遍（Datamodel 接口 vtable[424/8]）。

    调用方用完须 _free_mem 返回的地址。
    """
    dm = _hammer_base() + RVA_DATAMODEL   # 静态内嵌对象，直接用地址（不再解引用）
    vtable = _read_int(dm, "u64")
    fn = _read_int(vtable + VFN_OFF_INTERN_STRING, "u64")
    if not fn:
        raise RuntimeError("InternString 函数指针为空")

    buf = _alloc_mem(8)
    _write_mem(buf, b"\x00" * 8)
    resp = _get_pipe().call("call_function", {
        "address": hex(fn),
        "args": [dm, buf, f"str:{value}"],
        "on_main_thread": True,
        "timeout_ms": 15000,
    })
    if "error" in resp:
        _free_mem(buf)
        raise RuntimeError(f"InternString 调用失败: {resp['error']}")
    status = resp["result"].get("main_thread_status", 0)
    if status != 0:
        _free_mem(buf)
        raise RuntimeError(f"InternString 主线程派发失败 (main_thread_status={status}): "
                           f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}")
    return buf


def _fmt_attr_line(name: str, atype: int, value: Any, name_w: int = 26) -> str:
    """一行属性：`名字  类型(码) = 值`（向量/数组做紧凑显示）。"""
    tname = DM_ATTR_TYPE_NAMES.get(atype, "?")
    if isinstance(value, tuple) and len(value) == 3:
        shown = "(%.4g, %.4g, %.4g)" % tuple(float(v) for v in value)
    elif isinstance(value, list):
        items = ", ".join(repr(x) if isinstance(x, str) else str(x) for x in value[:12])
        shown = f"[{items}]"
        if len(value) > 12:
            shown = shown[:-1] + f", … 共 {len(value)} 项]"
    elif isinstance(value, str):
        shown = repr(value)
    else:
        shown = str(value)
    if len(shown) > 220:
        shown = shown[:220] + "…"
    return f"  {name:<{name_w}} {tname}({atype}) = {shown}"
