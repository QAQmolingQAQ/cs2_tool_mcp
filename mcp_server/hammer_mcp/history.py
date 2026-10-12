"""Hammer history operations."""
from __future__ import annotations
from .offsets import (
    CMAPDOC_ROOT_OFFSET,
    HISTORY_OFF_ARRAY,
    HISTORY_OFF_COUNT,
    MAIN_THREAD_STATUS_NAMES,
    NODE_IFACE_OFFSET,
    ROOT_OFF_REDO_HISTORY,
    ROOT_OFF_UNDO_HISTORY,
    RVA_CDATAMODEL_GLOBAL,
    RVA_CDATAMODEL_REDO,
    RVA_CDATAMODEL_UNDO,
    RVA_CDATAMODEL_VTABLE,
    RVA_CMAPROOT_VTABLE,
    RVA_HIST_RECORD_NODE,
    RVA_MAP_HISTORY_GATE,
    RVA_MAP_HISTORY_NOTIFY,
    RVA_MAP_HISTORY_POP,
    RVA_MAP_HISTORY_PUSH_STEP,
    RVA_MAP_HISTORY_REC_ADDED,
    RVA_MAP_HISTORY_REC_REMOVED,
    RVA_MAP_HISTORY_VTABLE,
    RVA_UNDO_MANAGER_REDO,
    RVA_UNDO_MANAGER_UNDO,
    RVA_UNDO_SCOPE_BEGIN,
    RVA_UNDO_SCOPE_END,
    UNDO_MANAGER_OFFSET,
    UNDO_MGR_FLAG_ENABLED,
    UNDO_MGR_OFF_FLAGS,
)
from .runtime import (
    _call_fn,
    _get_pipe,
    _hammer_addr,
    _hammer_base,
    _read_int,
    _read_string,
)
from .scene import (
    _map_doc,
)


def _undo_redo(action: str, use_wrapper: bool) -> str:
    try:
        base = _hammer_base()
        data_model = base + RVA_CDATAMODEL_GLOBAL
        undo_mgr = data_model + UNDO_MANAGER_OFFSET

        vtable = _read_int(data_model, "u64")
        if vtable != base + RVA_CDATAMODEL_VTABLE:
            return (
                f"ERROR g_CDataModel 校验失败: vtable={vtable:#x}, "
                f"期望 {base + RVA_CDATAMODEL_VTABLE:#x}。hammer.dll 版本可能不符。"
            )

        # 总开关关着时 CUndoManager::Undo/Redo 会直接返回，先确保它是开的
        _ensure_undo_enabled()

        before_undo = _read_int(undo_mgr, "u32")
        before_redo = _read_int(undo_mgr + 16, "u32")

        # ⚠️ 硬守卫（2026-09-24 实测）：对空栈调用 Undo/Redo 不会立刻崩，但会破坏
        # undo 系统内部状态，之后任意走 undo scope 的操作（如保存）都会弹
        # "FATAL ERROR: Error in the undo system! Grab a programmer!" 并杀死 Hammer。
        if action == "undo" and before_undo == 0:
            return "已取消：DMX undo 栈为空（0 步），拒绝调用以防 undo 系统崩溃。"
        if action == "redo" and before_redo == 0:
            return "已取消：DMX redo 栈为空（0 步），拒绝调用以防 undo 系统崩溃。"

        if use_wrapper:
            rva = RVA_CDATAMODEL_REDO if action == "redo" else RVA_CDATAMODEL_UNDO
            this_ptr = data_model
        else:
            rva = RVA_UNDO_MANAGER_REDO if action == "redo" else RVA_UNDO_MANAGER_UNDO
            this_ptr = undo_mgr

        resp = _get_pipe().call("call_function", {
            "address": f"hammer.dll+{rva:#x}", "args": [this_ptr],
        })
        if "error" in resp:
            return f"INJECTED_DLL_ERROR: {resp['error']}"
        ret = resp["result"]["ret_hex"]

        after_undo = _read_int(undo_mgr, "u32")
        after_redo = _read_int(undo_mgr + 16, "u32")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    name = "Undo" if action == "undo" else "Redo"
    return (
        f"{name} 完成 (ret={ret})\n"
        f"  undo 栈: {before_undo} -> {after_undo}\n"
        f"  redo 栈: {before_redo} -> {after_redo}"
    )


def cs2_undo(use_wrapper: bool = True) -> str:
    """撤销 Datamodel(DMX) 的上一笔操作。

    ⚠️ 注意：这是 **Datamodel(DMX) 的撤销栈**（CDataModel 全局单例 hammer.dll+0x24B7C80，
    内嵌 CUndoManager@+240），**不影响地图编辑历史**（地图历史在
    CMapRootElement+0x240/+0x248 的 CMapDocHistory，见 REVERSE_NOTES.md §3）。

    Args:
        use_wrapper: True 走 CDataModel::Undo (hammer.dll+0x5C3160)，会额外通知 UI 刷新；
                     False 直接调 CUndoManager::Undo (hammer.dll+0x60F8D0)。
    """
    return _undo_redo("undo", use_wrapper)


def cs2_redo(use_wrapper: bool = True) -> str:
    """重做 Datamodel(DMX) 的操作。⚠️ 同样不影响地图编辑历史，详见 cs2_undo。"""
    return _undo_redo("redo", use_wrapper)


def _find_map_histories(doc: int | None = None) -> tuple[int, int]:
    """定位当前地图的 (undoHistory, redoHistory)。

    新版链路（2026-09，运行时实测，见 REVERSE_NOTES.md §3）：
      CMapDoc+0x80 = CMapRootElement*
      root+0x240 = undo CMapDocHistory；root+0x248 = redo CMapDocHistory
    """
    doc = doc if doc is not None else _map_doc()
    root = _read_int(doc + CMAPDOC_ROOT_OFFSET, "u64")
    if not root:
        raise RuntimeError("CMapDoc 里没有 CMapRootElement")
    if _read_int(root, "u64") != _hammer_base() + RVA_CMAPROOT_VTABLE:
        raise RuntimeError("CMapRootElement vtable 校验失败（hammer.dll 版本不符？）")

    undo_h = _read_int(root + ROOT_OFF_UNDO_HISTORY, "u64")
    redo_h = _read_int(root + ROOT_OFF_REDO_HISTORY, "u64")
    want = _hammer_base() + RVA_MAP_HISTORY_VTABLE
    if not undo_h or _read_int(undo_h, "u64") != want:
        raise RuntimeError(f"undo 历史对象异常: {undo_h:#x}")
    if not redo_h or _read_int(redo_h, "u64") != want:
        raise RuntimeError(f"redo 历史对象异常: {redo_h:#x}")
    return undo_h, redo_h


def _hist_push_step(hist: int, name: str) -> int:
    """压入一个具名撤销步（名字会显示在 Hammer 的 Undo 菜单里）-> 压入后的步数。

    ⚠ 名字**必须是 ASCII**：参数经管道以 ANSI 字符串传给 `V_strncpy`，中文会变成 `??`
    （实测 `'cs2: 创建 info_target'` 存进去成了 `'cs2: ?? info_target'`）。
    """
    _call_fn(RVA_MAP_HISTORY_PUSH_STEP, [hist, f"str:{name}", 0, 0], timeout=20000)
    return _read_int(hist + HISTORY_OFF_COUNT, "u32")


def _hist_record_object(hist: int, element: int, added: bool) -> int:
    """把元素登记进**当前（栈顶）撤销步**：added=True 记「新增」，False 记「移除」。

    返回传入的 node 指针（= element + 0xC8）。调用方需保证 step 已压好；
    且记「移除」时必须**在摘除之前**调用。
    """
    node = element + NODE_IFACE_OFFSET
    _call_fn(RVA_MAP_HISTORY_REC_ADDED if added else RVA_MAP_HISTORY_REC_REMOVED,
             [hist, node], timeout=20000)
    return node


def _hist_notify(hist: int) -> None:
    """通知历史对象上的监听者（刷新 Undo/Redo 菜单与工具状态）。"""
    _call_fn(RVA_MAP_HISTORY_NOTIFY, [hist, 2], timeout=20000)


def _hist_record_node(hist: int, element: int) -> None:
    """把元素的**节点子树**登记进当前撤销步 —— 记录的是**改动前**的状态。

    Hammer 自己改属性/变换（如 `AlignObjects`）就是：`PushStep` 开步 →
    逐个 `sub_18086D9B0(hist, node, 1)` 登记节点 → **然后**才真正改。
    该函数会自己沿父链/子链递归登记，所以**必须在 `_hist_push_step()` 之后、
    真正修改之前**调用；元素不是节点（如 world）时应由调用方跳过。

    ⚠ 元素多/层级深时会比较慢（递归），超时给得比其它历史调用大。
    """
    _call_fn(RVA_HIST_RECORD_NODE, [hist, element + NODE_IFACE_OFFSET, 1], timeout=60000)


def _hist_state(hist: int) -> str:
    """回显撤销栈状态：`步数=N 栈顶='名字'(K 条命令)`（工具返回值里用于验证记录生效）。"""
    n = _read_int(hist + HISTORY_OFF_COUNT, "u32")
    if not n:
        return "步数=0"
    top = _read_int(_read_int(hist + HISTORY_OFF_ARRAY, "u64") + 8 * (n - 1), "u64")
    return f"步数={n} 栈顶={_read_string(top + 0x24, 128)!r}({_read_int(top, 'u32')} 条命令)"


def _map_undo_redo(action: str, doc: str = "") -> str:
    try:
        undo_h, redo_h = _find_map_histories(_map_doc(doc))
        before_u = _read_int(undo_h + HISTORY_OFF_COUNT, "u32")
        before_r = _read_int(redo_h + HISTORY_OFF_COUNT, "u32")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    name = "地图 Undo" if action == "undo" else "地图 Redo"
    if (before_u if action == "undo" else before_r) == 0:
        return (f"{name} 已取消：{'撤销' if action == 'undo' else '重做'}历史为空"
                f"（undo {before_u} 步 / redo {before_r} 步）")
    gate = _read_int(_hammer_base() + RVA_MAP_HISTORY_GATE, "u8")
    if not gate:
        return (f"{name} 已取消：CMapDocHistory 全局开关（hammer.dll+{RVA_MAP_HISTORY_GATE:#x}）"
                "是 0，Pop 会直接返回")

    this_ptr = undo_h if action == "undo" else redo_h
    try:
        resp = _get_pipe().call("call_function", {
            "address": _hammer_addr(RVA_MAP_HISTORY_POP),
            "args": [this_ptr],
            # 必须走 Hammer 主线程：从管道线程直接调用会让该函数永不返回，
            # 并把历史留在 busy 状态（旧版实测），故 timeout 给足。
            "on_main_thread": True,
            "timeout_ms": 15000,
        })
        if "error" in resp:
            return f"INJECTED_DLL_ERROR: {resp['error']}"
        result = resp["result"]
        ret = result["ret_hex"]
        status = result.get("main_thread_status", 0)
        if status != 0:
            return (
                f"ERROR 主线程派发失败 (main_thread_status={status}): "
                f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}\n"
                "  1=等待超时(目标函数可能卡住) 2=未找到主线程 3=SetWindowsHookEx 失败 4=调用中触发异常"
            )

        after_u = _read_int(undo_h + HISTORY_OFF_COUNT, "u32")
        after_r = _read_int(redo_h + HISTORY_OFF_COUNT, "u32")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    note = ""
    if before_u == after_u and before_r == after_r:
        note = f"\n  提示: 计数未变化，{'撤销' if action == 'undo' else '重做'}栈可能已空"
    return (
        f"{name} 完成 (ret={ret}, this={this_ptr:#x})\n"
        f"  undo 历史: {before_u} -> {after_u}\n"
        f"  redo 历史: {before_r} -> {after_r}{note}"
    )


def cs2_map_undo(doc: str = "") -> str:
    """撤销**地图编辑**的上一步操作（真正的 Hammer 撤销，非 Datamodel）。

    走 `CMapDocHistory::Pop`（新版 RVA `0x1529E80`，见 REVERSE_NOTES §15），
    撤销/重做共用该函数，靠传入的历史对象区分（`CMapRootElement+0x240` 撤销 /
    `+0x248` 重做）。空栈时会提前拒绝（函数内部也有 CanUndo 守卫）。

    Args:
        doc: 目标地图文档（多文档时必填）：留空 = 清单第一个；数字 = 索引；
             其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    return _map_undo_redo("undo", doc)


def cs2_map_redo(doc: str = "") -> str:
    """重做**地图编辑**的下一步操作（真正的 Hammer 重做）。详见 cs2_map_undo。"""
    return _map_undo_redo("redo", doc)


def _undo_manager_addr() -> int:
    """CUndoManager 地址（内嵌在 g_CDataModel + 240）。"""
    return _hammer_base() + RVA_CDATAMODEL_GLOBAL + UNDO_MANAGER_OFFSET


def _ensure_undo_enabled() -> bool:
    """确保 Datamodel 的 undo 总开关（CUndoManager+132 bit3）是开的。

    Hammer 平时把它关着，此时 `CDmAttribute::SetValue` **不会**记录撤销元素
    （实测：DMX 栈与地图历史计数都不变），`CUndoManager::Undo` 也会直接返回。
    返回 True 表示本次由我们打开。
    """
    um = _undo_manager_addr()
    addr = um + UNDO_MGR_OFF_FLAGS
    cur = _read_int(addr, "u8")
    if cur & UNDO_MGR_FLAG_ENABLED:
        return False
    resp = _get_pipe().call("write_value", {
        "address": hex(addr),
        "value": cur | UNDO_MGR_FLAG_ENABLED,
        "type": "u8",
    })
    if "error" in resp:
        raise RuntimeError(f"打开 undo 总开关失败: {resp['error']}")
    return True


def _undo_scope_begin(name: str) -> None:
    """开一个 Datamodel undo scope（须与 _undo_scope_end 配对）。"""
    um = _undo_manager_addr()
    resp = _get_pipe().call("call_function", {
        "address": _hammer_addr(RVA_UNDO_SCOPE_BEGIN),
        "args": [um, f"str:{name}", f"str:{name}", 0],
        "on_main_thread": True,
        "timeout_ms": 15000,
    })
    if "error" in resp:
        raise RuntimeError(f"BeginUndoScope 调用失败: {resp['error']}")
    status = resp["result"].get("main_thread_status", 0)
    if status != 0:
        raise RuntimeError(f"BeginUndoScope 主线程派发失败 (main_thread_status={status}): "
                           f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}")


def _undo_scope_end() -> int:
    """结束 Datamodel undo scope；返回值非 0 表示 scope 内确有操作被提交。"""
    um = _undo_manager_addr()
    resp = _get_pipe().call("call_function", {
        "address": _hammer_addr(RVA_UNDO_SCOPE_END),
        "args": [um, 0],          # 新版 EndUndoScope(this, bool abort=0)
        "on_main_thread": True,
        "timeout_ms": 15000,
    })
    if "error" in resp:
        raise RuntimeError(f"EndUndoScope 调用失败: {resp['error']}")
    status = resp["result"].get("main_thread_status", 0)
    if status != 0:
        raise RuntimeError(f"EndUndoScope 主线程派发失败 (main_thread_status={status}): "
                           f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}")
    return resp["result"]["ret"]
