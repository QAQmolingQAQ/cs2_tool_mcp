"""Hammer entity io operations."""
from __future__ import annotations
import struct
from typing import Any
from .datamodel import (
    _dm_array_handles,
)
from .history import (
    _find_map_histories,
    _hist_notify,
    _hist_push_step,
    _hist_record_node,
    _hist_state,
)
from .offsets import (
    CONN_OFF_DELAY,
    CONN_OFF_GLOBAL,
    CONN_OFF_INPUT,
    CONN_OFF_OUTPUT,
    CONN_OFF_PARAM,
    CONN_OFF_PARAMMAP,
    CONN_OFF_RELAY,
    CONN_OFF_SOURCE,
    CONN_OFF_TARGET,
    CONN_OFF_TIMES,
    CONN_OFF_TYPE,
    CONN_STRIDE,
    ENTITY_ATTR_CONNECTIONS,
    ENTITY_OFF_CONN_COUNT,
    ENTITY_OFF_CONN_DATA,
    IO_TARGET_TYPE_NAMES,
    RVA_CONN_VALUE_INIT,
    RVA_ENTITY_ADD_CONN,
    RVA_ENTITY_REMOVE_CONN,
)
from .runtime import (
    _alloc_mem,
    _call_fn,
    _free_mem,
    _hammer_base,
    _parse_addr,
    _plausible_ptr,
    _invoke_main,
    _read_bytes,
    _read_int,
    _read_string,
    _write_mem,
)
from .scene import (
    _doc_of_element,
)


def _native_conns(entity: int) -> list[dict[str, Any]]:
    """读 CMapEntity 的原生 IO 连接数组（Hammer **编辑期**的真实存放处）。

    布局（sub_180986EA0 / sub_180214420 反编译 + 活体实测，见 REVERSE_NOTES §11.13）：
        entity+0x4A0 u32 count ／ +0x4A8 Conn* ／ +0x4B0 u32 alloc，元素步长 0x50。
    """
    count = _read_int(entity + ENTITY_OFF_CONN_COUNT, "u32")
    data = _read_int(entity + ENTITY_OFF_CONN_DATA, "u64")
    if not count or count > 4096 or not _plausible_ptr(data):
        return []
    raw = _read_bytes(data, CONN_STRIDE * count)

    def _str_at(off: int) -> str:
        p = struct.unpack_from("<Q", raw, off)[0]
        if not (0x10000 < p < 0x00007FFFFFFFFFFF):
            return ""
        try:
            return _read_string(p, 512)
        except Exception:  # noqa: BLE001
            return ""

    conns: list[dict[str, Any]] = []
    for i in range(count):
        base = i * CONN_STRIDE
        conns.append({
            "source": _str_at(base + CONN_OFF_SOURCE),
            "output": _str_at(base + CONN_OFF_OUTPUT),
            "target": _str_at(base + CONN_OFF_TARGET),
            "input": _str_at(base + CONN_OFF_INPUT),
            "param": _str_at(base + CONN_OFF_PARAM),
            "target_type": struct.unpack_from("<i", raw, base + CONN_OFF_TYPE)[0],
            "delay": struct.unpack_from("<f", raw, base + CONN_OFF_DELAY)[0],
            "times_to_fire": struct.unpack_from("<i", raw, base + CONN_OFF_TIMES)[0],
            "relay": raw[base + CONN_OFF_RELAY],
            "global_relay": raw[base + CONN_OFF_GLOBAL],
        })
    return conns


def cs2_entity_get_io(entity: str) -> str:
    """读取实体的 IO（输出->输入连接），等价 Hammer 的 Outputs 页。

    ⚠ 数据源是 **CMapEntity 的原生 CUtlVector<Conn>（entity+0x4A0）**，不是 DMX 的
    `connectionsData` —— 后者只是保存 .vmap 时生成的临时镜像，平时计数为 0
    （这正是之前「读到 0 条」的原因，见 REVERSE_NOTES §11.13）。

    Args:
        entity: 实体地址（cs2_entity_list 给出）。
    """
    try:
        ent = _parse_addr(entity)
        conns = _native_conns(ent)
        lines = [f"实体 {ent:#x}  IO 连接 {len(conns)} 条（原生 Conn CUtlVector @entity+0x4A0）"]
        for i, c in enumerate(conns[:64]):
            tname = IO_TARGET_TYPE_NAMES.get(c["target_type"], "?")
            lines.append(
                f"  [{i}] {c['output'] or '<无输出>'} -> {c['target'] or '<无目标>'}:"
                f"{c['input'] or '<无输入>'}"
                f"   param={c['param']!r} type={c['target_type']}({tname})"
                f" delay={c['delay']} timesToFire={c['times_to_fire']}"
                f" relay={c['relay']} globalRelay={c['global_relay']}")
        dm = _dm_array_handles(ent, ENTITY_ATTR_CONNECTIONS)
        lines.append(f"DMX connectionsData 镜像: {len(dm)} 条"
                     "（Hammer 仅在保存 .vmap 期间填充，平时为 0）")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    return "\n".join(lines)


def _conn_scratch(values: dict[str, str], target_type: int, delay: float,
                  times_to_fire: int, relay: bool, global_relay: bool) -> int:
    """在目标进程里拼一条可传给 sub_180986EA0 的「源 Conn」（80 字节 + 字符串池）。

    m_paramMap（+0x30）必须是一个已初始化的 KV3 值，否则 Hammer 复制它时会读到垃圾，
    所以这里按 Hammer 自己的做法调用 sub_1813E79E0(this, 1, 8) 初始化。
    返回 scratch 块地址；调用方负责 _free_mem。
    """
    blk = _alloc_mem(0x400)
    _write_mem(blk, b"\x00" * 0x400)
    off = 0x100
    ptrs: dict[str, int] = {}
    for key in ("source", "output", "target", "input", "param"):
        raw = (values.get(key) or "").encode("utf-8") + b"\x00"
        _write_mem(blk + off, raw)
        ptrs[key] = blk + off
        off += len(raw) + 8
    payload = bytearray(CONN_STRIDE)
    for key, off_ in (("source", CONN_OFF_SOURCE), ("output", CONN_OFF_OUTPUT),
                      ("target", CONN_OFF_TARGET), ("input", CONN_OFF_INPUT),
                      ("param", CONN_OFF_PARAM)):
        struct.pack_into("<Q", payload, off_, ptrs[key])
    struct.pack_into("<i", payload, CONN_OFF_TYPE, target_type)
    struct.pack_into("<f", payload, CONN_OFF_DELAY, delay)
    struct.pack_into("<i", payload, CONN_OFF_TIMES, times_to_fire)
    payload[CONN_OFF_RELAY] = 1 if relay else 0
    payload[CONN_OFF_GLOBAL] = 1 if global_relay else 0
    _write_mem(blk, bytes(payload))
    # ⚠ 必须在写完 payload 之后再初始化 m_paramMap，否则会把它覆盖成 0
    _invoke_main(_hammer_base() + RVA_CONN_VALUE_INIT, [blk + CONN_OFF_PARAMMAP, 1, 8])
    return blk


def cs2_entity_add_io(entity: str, output: str, input_name: str,
                      target: str = "!self", param: str = "",
                      delay: float = 0.0, times_to_fire: int = -1,
                      target_type: int = 7, relay: bool = False,
                      global_relay: bool = False, source: str = "",
                      history: bool = True) -> str:
    """给实体追加一条 IO 连接（等价 Hammer Outputs 页的 Add）。

    直接调用 Hammer 自己的追加函数 `sub_180986EA0(entity, outHandle, const Conn*)`
    —— 与 Outputs 面板「Add New Output」(sub_18020C9E0) / 粘贴链路（sub_18020D240）
    完全同一条代码，扩容/字符串深拷贝/唯一 id 都由 Hammer 处理，不绕过文档逻辑。

    history=True（默认）时严格按面板的顺序：先压具名 Ctrl+Z 步 +
    `sub_18086D9B0` 登记实体节点的改动前快照，**然后**才追加 —— 因此本次添加
    可被 `cs2_map_undo` / `cs2_map_redo` 完整撤销重做（Hammer 用专门的
    CMapEntityIONode 重放连接，见 REVERSE_NOTES §11.13.7）。
    ⚠ Outputs 面板若正开着不会即时刷新表格（面板提交 sub_180206BC0 纯 UI），
    重选实体或重开页面即可；`cs2_entity_get_io` 直接读原生向量，不受影响。

    ⚠ 数据写入的是原生向量，Hammer 的「文档已修改」标记不会因此置位；
    要落盘请随后调用 `cs2_map_save()`（底层强制保存，无需脏标记）。

    Args:
        entity: 实体地址。
        output: 输出名，如 'OnStartTouch' / 'OnTrigger' / 'OnUser1'。
        input_name: 目标输入名，如 'Kill' / 'Enable' / 'Trigger'。
        target: 目标实体名或类名，默认 '!self'（'!activator' / '!caller' 亦常用）。
        param: 覆盖参数 overrideParam。
        delay: 延迟秒数。
        times_to_fire: 可触发次数，-1 = 无限。
        target_type: ioTargetType，7=ENTITYNAME_OR_CLASSNAME（默认）/ 2=ENTITYNAME / 6=EHANDLE。
        relay: relayConnection 标志。
        global_relay: fromGlobalRelay 标志。
        source: sourceEntity（触发者，一般留空）。
        history: 是否记入 Hammer 的 Ctrl+Z 历史（默认 True）。
    """
    try:
        ent = _parse_addr(entity)
        before = _read_int(ent + ENTITY_OFF_CONN_COUNT, "u32")
        hist_note = ""
        if history:
            # 与面板 sub_18020C9E0 同序：PushStep("Add New Output") →
            # sub_18086D9B0(hist, entity+0xC8, 1) → 追加（§17.14 同一套 API）。
            try:
                undo_h, _ = _find_map_histories(_doc_of_element(ent))
                _hist_push_step(undo_h, "cs2: Add New Output")
                _hist_record_node(undo_h, ent)
                _hist_notify(undo_h)
                hist_note = f"  Ctrl+Z 步: {_hist_state(undo_h)}"
            except Exception as e:  # noqa: BLE001
                return f"ERROR IO追加未执行；撤销准备失败或结果未知，勿重试: {type(e).__name__}: {e}"
        blk = _conn_scratch({"source": source, "output": output, "target": target,
                             "input": input_name, "param": param},
                            target_type, delay, times_to_fire, relay, global_relay)
        outbuf = _alloc_mem(16)
        try:
            _invoke_main(_hammer_base() + RVA_ENTITY_ADD_CONN, [ent, outbuf, blk], timeout=15000)
        finally:
            _free_mem(outbuf)
            _free_mem(blk)
        after = _read_int(ent + ENTITY_OFF_CONN_COUNT, "u32")
        conns = _native_conns(ent)
        if after == before + 1 and conns:
            c = conns[-1]
            return (f"已添加 IO 连接 [{after - 1}] {c['output']} -> {c['target']}:{c['input']}"
                    f"   (连接数 {before} -> {after})\n{hist_note}")
        return (f"⚠ 追加调用已发出，但连接数未按预期变化：{before} -> {after}"
                f"（outHandle 缓冲区 {outbuf:#x}）\n{hist_note}")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


def cs2_entity_remove_io(entity: str, index: int, history: bool = True) -> str:
    """删除实体的一条 IO 连接（等价 Hammer Outputs 页的 Delete）。

    直接调用 Hammer 自己的删除函数 `sub_180987AF0(entity, index<<16)` —— 面板
    「Delete Output」(sub_18020CD40) 用的就是它：析构 Conn（paramMap + 5 个
    CUtlString 全部正确释放，不再有旧实现的字符串泄漏）→ 尾块前移 → 计数减一。

    history=True（默认）时与面板同序：先压具名 Ctrl+Z 步 + 登记改动前快照，
    **然后**才删除，可被 `cs2_map_undo` / `cs2_map_redo` 完整撤销重做。

    Args:
        entity: 实体地址。
        index: 连接下标（cs2_entity_get_io 输出里的 [i]）。
        history: 是否记入 Hammer 的 Ctrl+Z 历史（默认 True）。
    """
    try:
        ent = _parse_addr(entity)
        count = _read_int(ent + ENTITY_OFF_CONN_COUNT, "u32")
        data = _read_int(ent + ENTITY_OFF_CONN_DATA, "u64")
        if not (0 <= index < count) or not _plausible_ptr(data):
            return f"ERROR 下标越界：{index}（当前 {count} 条）"
        if index >= 0x8000:
            return f"ERROR 下标过大：{index}（删除函数的索引是 int16，上限 32767）"
        old = _native_conns(ent)[index]
        hist_note = ""
        if history:
            # 与面板 sub_18020CD40 同序：PushStep("Delete Output") →
            # sub_18086D9B0(hist, entity+0xC8, 1) → sub_180987AF0。
            try:
                undo_h, _ = _find_map_histories(_doc_of_element(ent))
                _hist_push_step(undo_h, "cs2: Delete Output")
                _hist_record_node(undo_h, ent)
                _hist_notify(undo_h)
                hist_note = f"  Ctrl+Z 步: {_hist_state(undo_h)}"
            except Exception as e:  # noqa: BLE001
                return f"ERROR IO删除未执行；撤销准备失败或结果未知，勿重试: {type(e).__name__}: {e}"
        ret, err = _call_fn(RVA_ENTITY_REMOVE_CONN, [ent, index << 16], timeout=15000)
        if err:
            return f"ERROR 调用 Hammer 删除函数 sub_180987AF0 失败: {err}"
        after = _read_int(ent + ENTITY_OFF_CONN_COUNT, "u32")
        if int(ret, 16) != 1 or after != count - 1:
            return (f"⚠ 删除函数已调用但结果异常：ret={ret}，连接数 {count} -> {after}"
                    f"（下标 {index}）\n{hist_note}")
        return (f"已删除 IO 连接 [{index}] {old['output']} -> {old['target']}:{old['input']}"
                f"   (连接数 {count} -> {after})\n{hist_note}")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
