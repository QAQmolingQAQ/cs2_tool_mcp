"""Hammer qt operations."""
from __future__ import annotations
from .offsets import (
    RVA_QT_ACTION_MENU,
    RVA_QT_ACTION_TEXT,
    RVA_QT_INHERITS,
    RVA_QT_MENUBAR,
    RVA_QT_TOPLEVEL_WIDGETS,
    RVA_QT_WIDGET_ACTIONS,
)
from .runtime import (
    _get_pipe,
    _invoke_main,
    _read_bytes,
)
from .session import (
    get_session,
)


def _qt_bases() -> tuple[int, int]:
    """返回 (Qt5Widgets base, Qt5Core base)；Hammer 没起来时会抛异常。"""
    resp = _get_pipe().call("get_module", {"name": "Qt5Widgets.dll"})
    if "error" in resp:
        raise RuntimeError("Qt5Widgets.dll 未加载（Hammer 没起来？）")
    wb = int(resp["result"]["base_hex"], 16)
    resp = _get_pipe().call("get_module", {"name": "Qt5Core.dll"})
    if "error" in resp:
        raise RuntimeError("Qt5Core.dll 未加载")
    return wb, int(resp["result"]["base_hex"], 16)


def _qt_alloc(size: int = 512) -> int:
    resp = _get_pipe().call("alloc_memory", {"size": size})
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return int(resp["result"]["address"], 16)


def _qt_read_qstring(ptr: int) -> str:
    """读 Qt 的 QString：d 指针指向 {ref(4) size(4) alloc(4) offset(8)}，字符为 UTF-16。"""
    if not (0x10000 < ptr < 0x7FFFFFFFFFFF):
        return ""
    head = _read_bytes(ptr, 24)
    size = int.from_bytes(head[4:8], "little")
    off = int.from_bytes(head[16:24], "little", signed=True)
    if size <= 0 or size > 8192:
        return ""
    return _read_bytes(ptr + off, size * 2).decode("utf-16-le", "replace")


def _qt_action_text(action: int, retbuf: int, wb: int) -> str:
    _invoke_main(wb + RVA_QT_ACTION_TEXT, [action, retbuf], 5000)
    return _qt_read_qstring(int.from_bytes(_read_bytes(retbuf, 8), "little"))


def _read_qlist(ptr: int) -> list[int]:
    """读 QList<指针>：元素紧跟 QListData::Data 之后（d+0x10），共 end-begin 个。"""
    if not (0x10000 < ptr < 0x7FFFFFFFFFFF):
        return []
    head = _read_bytes(ptr, 24)
    begin = int.from_bytes(head[8:12], "little")
    end = int.from_bytes(head[12:16], "little")
    n = end - begin
    if n <= 0 or n > 20000:
        return []
    raw = _read_bytes(ptr + 16 + 8 * begin, n * 8)
    return [int.from_bytes(raw[k * 8:k * 8 + 8], "little") for k in range(n)]


def _qt_find_menu_action(needle: str, menu: str = "", exclude: str = "") -> int:
    """在菜单栏里找文本含 needle（且不含 exclude）的 QAction 地址。

    路径：`QApplication::topLevelWidgets()` → 顶层窗口若是 `QMainWindow` 就取 `menuBar()`。
    `menu` 给定时只在名称含它的顶层菜单（如 "File"）里找，可大幅减少主线程调用。

    为什么不用 `allWidgets()`：打开地图后它有 5400+ 个 widget，逐个读 vtable 的
    管道往返太多，且主线程派发是串行槽位机制，调用太密会超时。
    结果按 Qt5Widgets 基址缓存。
    """
    wb, cb = _qt_bases()
    key = f"{needle}|{menu}|{exclude}"
    hit = get_session().cache.qt_menus.get(key)
    if hit and hit[1] == wb:
        return hit[0]

    retbuf = _qt_alloc(512)

    def _actions_of(obj: int) -> list[int]:
        _invoke_main(wb + RVA_QT_WIDGET_ACTIONS, [obj, retbuf], 10000)
        return _read_qlist(int.from_bytes(_read_bytes(retbuf, 8), "little"))

    # 1) 收集候选菜单栏
    # 注意：主线程派发是「设置共享槽位 + 等钩子」的串行机制，短时间内发太多
    # on_main_thread 调用会积压并超时。所以先用 read_memory（不走主线程）读 vtable
    # 去重，只对每种类型各问一次 inherits。
    _invoke_main(wb + RVA_QT_TOPLEVEL_WIDGETS, [retbuf], 20000)
    tops = _read_qlist(int.from_bytes(_read_bytes(retbuf, 8), "little"))
    bars: list[int] = []
    seen: dict[int, str] = {}          # vtable -> "QMainWindow" / "QMenuBar" / ""
    for w in tops:
        if not (0x10000 < w < 0x7FFFFFFFFFFF):
            continue
        try:
            vt = int.from_bytes(_read_bytes(w, 8), "little")
        except Exception:  # noqa: BLE001
            continue
        kind = seen.get(vt)
        if kind is None:
            kind = ""
            try:
                if _invoke_main(cb + RVA_QT_INHERITS, [w, "str:QMainWindow"], 10000):
                    kind = "QMainWindow"
                elif _invoke_main(cb + RVA_QT_INHERITS, [w, "str:QMenuBar"], 10000):
                    kind = "QMenuBar"
            except Exception:  # noqa: BLE001
                kind = ""
            seen[vt] = kind
        if kind == "QMainWindow":
            bar = _invoke_main(wb + RVA_QT_MENUBAR, [w], 10000)     # QMenuBar*
            if bar:
                bars.append(bar)
        elif kind == "QMenuBar":
            bars.append(w)

    # 2) 逐个菜单栏找目标 action
    # 优化：先读「顶层菜单名」（如 File/Edit/Map），只深入名称匹配 menu 的那个，
    # 否则会把每个菜单栏下的所有菜单项文本都读一遍（上千次主线程调用 → 超时）。
    for bar in bars:
        for top in _actions_of(bar):
            top_txt = _qt_action_text(top, retbuf, wb)
            if menu and menu not in top_txt:
                continue
            sub = _invoke_main(wb + RVA_QT_ACTION_MENU, [top], 10000)   # -> QMenu*
            if not sub:
                continue
            for a in _actions_of(sub):
                txt = _qt_action_text(a, retbuf, wb)
                if needle in txt and (not exclude or exclude not in txt):
                    get_session().cache.qt_menus[key] = (a, wb)
                    return a
    return 0
