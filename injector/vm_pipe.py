#!/usr/bin/env python3
"""直连 cs2_tool.dll 命名管道的命令行客户端（供 VM 内使用）。

不依赖 `mcp` 包：`map-*` 子命令通过兼容入口复用
`mcp_server/cs2_mcp_server.py` 里的**真实实现**，避免复制逻辑。

用法:
    python vm_pipe.py ping
    python vm_pipe.py list_tools
    python vm_pipe.py read_memory '{"address": 140000000, "size": 16}'
    python vm_pipe.py map-info                 # 定位 CMapDoc / session / 两个历史对象
    python vm_pipe.py map-undo
    python vm_pipe.py map-redo
    python vm_pipe.py call-main hammer.dll+0x1406F90        # 主线程调用（免 JSON 引号地狱）
    python vm_pipe.py call-main hammer.dll+0x14080D0 12345
    python vm_pipe.py --pipe \\\\.\\pipe\\CS2ToolMCP ping
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))


def _load_server():
    """Load bridge operations without importing the MCP framework."""
    import cs2_mcp_server
    return cs2_mcp_server


def main() -> int:
    # VM 控制台是 GBK，MCP 侧文本含中文/符号时 print 会抛 UnicodeEncodeError
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("command", help="方法名，或 map-info/map-undo/map-redo/call-main")
    ap.add_argument("params", nargs="*", default=[], help="JSON 参数；call-main 时为 地址 [参数...]")
    ap.add_argument("--pipe", default=None, help="命名管道名（默认 \\\\.\\pipe\\CS2ToolMCP）")
    args = ap.parse_args()

    server = _load_server()
    if args.pipe:
        server.configure_default(args.pipe)

    if args.command == "map-info":
        print(server.cs2_map_info())
        return 0

    if args.command in ("map-undo", "map-redo"):
        fn = server.cs2_map_undo if args.command == "map-undo" else server.cs2_map_redo
        print(fn())
        return 0

    if args.command == "map-save":
        print(server.cs2_map_save())
        return 0

    if args.command == "dm-info":
        # DMX（Datamodel）撤销栈：属性修改走的是这一套，不是 CMapDocHistory
        base = server._hammer_base()
        # g_CDataModel 是内嵌全局对象：base+RVA 本身就是对象地址（不是指针）
        dm = base + server.RVA_CDATAMODEL_GLOBAL
        um = dm + 240
        print(f"g_CDataModel = {dm:#x}  (CUndoManager = {um:#x})")
        print(f"  undo count = {server._read_int(um, 'u32')}")
        print(f"  redo count = {server._read_int(um + 16, 'u32')}")
        return 0

    if args.command in ("dm-undo", "dm-redo"):
        print(server.cs2_undo() if args.command == "dm-undo" else server.cs2_redo())
        return 0

    if args.command == "dm-flag":
        # dm-flag on|off：手动开关 Datamodel undo 总开关（CUndoManager+132 bit3）
        um = server._undo_manager_addr()
        addr = um + server.UNDO_MGR_OFF_FLAGS
        cur = server._read_int(addr, "u8")
        want_on = not (args.params and args.params[0] == "off")
        new = (cur | 0x08) if want_on else (cur & ~0x08)
        resp = server._get_pipe().call("write_value",
                                       {"address": hex(addr), "value": new, "type": "u8"})
        back = server._read_int(addr, "u8")
        print(f"undo flag @ {addr:#x}: {cur:#04x} -> {new:#04x} (读回 {back:#04x})  {resp}")
        return 0

    if args.command == "scan-str":
        # scan-str <结构地址> <大小(hex)> <关键词>：在结构里找「指向含关键词字符串」的指针
        if len(args.params) < 3:
            print("用法: scan-str <base> <size_hex> <needle>")
            return 1
        base = int(args.params[0], 0)
        size = int(args.params[1], 0)
        needle = args.params[2]
        blk = server._read_bytes(base, size)
        seen: set[int] = set()
        n = 0
        for off in range(0, len(blk) - 7, 8):
            v = int.from_bytes(blk[off:off + 8], "little")
            if not (0x10000 < v < 0x7FFFFFFFFFFF) or v in seen:
                continue
            seen.add(v)
            try:
                s = server._read_string(v, 200)
            except Exception:  # noqa: BLE001  不可读的候选直接跳过
                continue
            if needle in s:
                print(f"  +{off:#06x}  @{base + off:#x} -> {v:#x}  {s!r}")
                n += 1
                if n >= 60:
                    break
        print(f"命中 {n} 处（扫描 {len(blk)} 字节，从 {base:#x}）")
        return 0

    if args.command == "module":
        # module <名字>：避免在远程 shell 里为 JSON 参数打架
        if not args.params:
            print("用法: module <dll 名>")
            return 1
        resp = server._get_pipe().call("get_module", {"name": args.params[0]})
        if "error" in resp:
            print(resp["error"])
            return 1
        m = resp["result"]
        print(f"{m['name']}  base={m['base_hex']}  size={m['size']}")
        return 0

    if args.command == "attr":
        # attr <实体地址> <属性名>：免 JSON 读实体属性
        if len(args.params) < 2:
            print("用法: attr <entity> <name>")
            return 1
        print(server.cs2_entity_get_attr(args.params[0], args.params[1]))
        return 0

    if args.command == "findattr":
        # findattr <实体地址> <属性名>：免 JSON 查属性索引
        if len(args.params) < 2:
            print("用法: findattr <entity> <name>")
            return 1
        print(server.cs2_entity_find_attr(args.params[0], args.params[1]))
        return 0

    if args.command == "setattr":
        # setattr <实体地址> <属性名> <新值>：免 JSON 设字符串属性
        if len(args.params) < 3:
            print("用法: setattr <entity> <name> <value>")
            return 1
        print(server.cs2_entity_set_attr(args.params[0], args.params[1], args.params[2]))
        return 0

    if args.command == "enumerate":
        # enumerate [类名] [flags]：直接调引擎遍历，用于摸清类名/flag 语义
        classname = args.params[0] if args.params else ""
        flags = int(args.params[1], 0) if len(args.params) > 1 else 0
        try:
            doc = server._map_doc()
            world = server._read_int(doc + server.CMAPDOC_WORLD_OFFSET, "u64")
            ents = server.enum_elements(world, classname, flags=flags)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {type(e).__name__}: {e}")
            return 1
        print(f"world={world:#x} classname={classname!r} flags={flags} -> {len(ents)}")
        for i, e in enumerate(ents[:30]):
            print(f"  [{i:3}] {e:#018x}")
        return 0

    if args.command == "entities":
        try:
            print(server.cs2_entity_list(limit=20))
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {type(e).__name__}: {e}")
            return 1
        return 0

    if args.command == "call-main":
        if not args.params:
            print("用法: call-main <address> [int_args...]")
            return 1
        resp = server._get_pipe().call("call_function", {
            "address": args.params[0],
            "args": [int(x, 0) for x in args.params[1:]],
            "on_main_thread": True,
            "timeout_ms": 15000,
        })
        print(json.dumps(resp, indent=2, ensure_ascii=False))
        return 0 if "error" not in resp else 1

    if args.command == "qt-widgets":
        # qt-widgets [过滤词]：用 QApplication::allWidgets() 枚举所有 Qt widget，
        # 列出按钮(QAbstractButton 子类)及其文本 —— 免鼠标坐标定位 UI 控件。
        # 原理见 REVERSE_NOTES：Qt5 DLL 以 mangled 名导出全部 public 符号。
        needle = args.params[0].lower() if args.params else ""
        pipe = server._get_pipe()
        bases = {}
        for name in ("Qt5Widgets.dll", "Qt5Core.dll"):
            r = pipe.call("get_module", {"name": name})
            if "error" in r:
                print(f"ERROR: 拿不到 {name}: {r['error']}")
                return 1
            bases[name] = int(r["result"]["base_hex"], 16)
        wb, cb = bases["Qt5Widgets.dll"], bases["Qt5Core.dll"]
        print(f"Qt5Widgets={wb:#x}  Qt5Core={cb:#x}")

        RVA_ALL_WIDGETS = 0xE270
        RVA_CLICK = 0xDE8C0
        RVA_TEXT = 0xE0900
        RVA_INHERITS = 0x290560

        # MSVC x64 陷阱：QString / QList 这类「非平凡拷贝构造」的类型，
        # 即使只有 8 字节也必须由调用方传隐藏返回缓冲区（RCX），真实参数整体右移。
        # 不给缓冲区 = 函数往垃圾地址写 → 直接崩进程。
        alloc = pipe.call("alloc_memory", {"size": 256})
        if "error" in alloc:
            print(f"ERROR: alloc_memory 失败: {alloc['error']}")
            return 1
        retbuf = int(alloc["result"]["address"], 16)
        print(f"返回缓冲区 = {retbuf:#x}")

        def qcall(fn, fargs, timeout=10000, has_ret_obj=True):
            """调用 Qt 函数；has_ret_obj=True 时在 RCX 前置隐藏返回缓冲区。"""
            call_args = ([retbuf] if has_ret_obj else []) + list(fargs)
            r = pipe.call("call_function", {
                "address": hex(fn), "args": call_args,
                "on_main_thread": True, "timeout_ms": timeout,
            })
            if "error" in r:
                raise RuntimeError(r["error"])
            res = r["result"]
            st = res.get("main_thread_status", 0)
            if st != 0:
                raise RuntimeError(f"main_thread_status={st} (1=超时 2=无主线程 3=钩子失败 4=异常)")
            return int(res["ret_hex"], 16)

        def read_qstring(d_ptr: int) -> str:
            """Qt5 QString = 单个 d 指针 -> QStringData{ref(4) size(4) alloc(4) offset(8)}。"""
            if not d_ptr:
                return ""
            head = server._read_bytes(d_ptr, 24)
            size = int.from_bytes(head[4:8], "little")
            off = int.from_bytes(head[16:24], "little", signed=True)
            if size <= 0 or size > 8192:
                return ""
            raw = server._read_bytes(d_ptr + off, size * 2)
            return raw.decode("utf-16-le", "replace")

        qcall(wb + RVA_ALL_WIDGETS, [])
        qlist = int.from_bytes(server._read_bytes(retbuf, 8), "little")
        if not qlist:
            print("allWidgets() 返回空")
            return 1
        # QListData::Data { ref(4) alloc(4) begin(4) end(4) array[]@16 }
        # 注意：元素紧跟 Data 之后，第 i 个元素地址 = d + 16 + 8*(begin+i)
        # （Qt 的 at(i) 就是 d->array + d->begin + i，array 本身是内嵌数组名）
        head = server._read_bytes(qlist, 24)
        begin = int.from_bytes(head[8:12], "little")
        end = int.from_bytes(head[12:16], "little")
        arr = qlist + 16
        n = end - begin
        print(f"allWidgets()={qlist:#x}  widget 数={n} (begin={begin} end={end} array={arr:#x})")
        if n <= 0 or n > 20000:
            print("widget 数异常，停止")
            return 1

        if needle == "dump":
            # 只 dump 原始数据，不调用任何 Qt 函数（排查布局用）
            print(f"d 头 32B: {server._read_bytes(qlist, 32).hex(' ')}")
            for i in range(min(12, n)):
                e = int.from_bytes(server._read_bytes(arr + 8 * (begin + i), 8), "little")
                line = f"  [{i:2}] ele={e:#018x}"
                if 0x10000 < e < 0x7FFFFFFFFFFF:
                    try:
                        vt = int.from_bytes(server._read_bytes(e, 8), "little")
                        line += f"  vt={vt:#018x}"
                    except Exception as ex:  # noqa: BLE001
                        line += f"  (读 vtable 失败: {ex})"
                print(line)
            return 0

        hits = 0
        for i in range(n):
            slot = arr + 8 * (begin + i)
            try:
                w = int.from_bytes(server._read_bytes(slot, 8), "little")
            except Exception:  # noqa: BLE001
                continue
            if not w:
                continue
            try:
                # inherits() 返回 bool，是平凡类型 -> 走 RAX，不占返回缓冲区
                is_btn = qcall(cb + RVA_INHERITS, [w, "str:QAbstractButton"], 8000,
                               has_ret_obj=False)
            except Exception as e:  # noqa: BLE001
                print(f"  [{i}] {w:#x} inherits 失败: {e}")
                continue
            if not is_btn:
                continue
            try:
                qcall(wb + RVA_TEXT, [w], 8000)          # QString 写进 retbuf
                d_ptr = int.from_bytes(server._read_bytes(retbuf, 8), "little")
                txt = read_qstring(d_ptr)
            except Exception as e:  # noqa: BLE001
                txt = f"<读取失败 {e}>"
            if needle and needle not in txt.lower():
                continue
            hits += 1
            print(f"  [{i:3}] {w:#014x}  {txt!r}")
        print(f"按钮命中 {hits} 个")
        return 0

    if args.command == "qt-click":
        # qt-click <widget 地址>：直接触发按钮 click()
        if not args.params:
            print("用法: qt-click <widget_addr>")
            return 1
        pipe = server._get_pipe()
        r = pipe.call("get_module", {"name": "Qt5Widgets.dll"})
        wb = int(r["result"]["base_hex"], 16)
        resp = pipe.call("call_function", {
            "address": hex(wb + 0xDE8C0),
            "args": [int(args.params[0], 0)],
            "on_main_thread": True,
            "timeout_ms": 10000,
        })
        print(json.dumps(resp, indent=2, ensure_ascii=False))
        return 0 if "error" not in resp else 1

    if args.command == "qt-types":
        # qt-types [过滤词]：列出所有 widget 的类名。
        # 全程只用「平凡返回类型」的调用：metaObject() 是虚函数(取 vtable[0])，
        # className() 返回 const char* —— 不会踩 QString 的隐藏缓冲区 ABI 坑。
        needle = args.params[0].lower() if args.params else ""
        pipe = server._get_pipe()
        r = pipe.call("get_module", {"name": "Qt5Core.dll"})
        if "error" in r:
            print(f"ERROR: {r['error']}")
            return 1
        cb = int(r["result"]["base_hex"], 16)
        RVA_CLASSNAME = 0x1D6140     # QMetaObject::className()
        r = pipe.call("get_module", {"name": "Qt5Widgets.dll"})
        wb = int(r["result"]["base_hex"], 16)
        RVA_ALL_WIDGETS = 0xE270
        RVA_INHERITS = 0x290560

        alloc = pipe.call("alloc_memory", {"size": 256})
        retbuf = int(alloc["result"]["address"], 16)

        def raw(fn, fargs, timeout=8000):
            r = pipe.call("call_function", {
                "address": hex(fn), "args": fargs,
                "on_main_thread": True, "timeout_ms": timeout,
            })
            if "error" in r:
                raise RuntimeError(r["error"])
            res = r["result"]
            if res.get("main_thread_status", 0) != 0:
                raise RuntimeError(f"main_thread_status={res['main_thread_status']}")
            return int(res["ret_hex"], 16)

        raw(wb + RVA_ALL_WIDGETS, [retbuf])   # QList 写入 retbuf
        qlist = int.from_bytes(server._read_bytes(retbuf, 8), "little")
        head = server._read_bytes(qlist, 24)
        begin = int.from_bytes(head[8:12], "little")
        end = int.from_bytes(head[12:16], "little")
        arr = qlist + 16
        n = end - begin

        from collections import Counter  # noqa: PLC0415
        stat: Counter = Counter()
        rows = []
        for i in range(n):
            w = int.from_bytes(server._read_bytes(arr + 8 * (begin + i), 8), "little")
            if not (0x10000 < w < 0x7FFFFFFFFFFF):
                continue
            try:
                vt = int.from_bytes(server._read_bytes(w, 8), "little")
                meta_obj_fn = int.from_bytes(server._read_bytes(vt, 8), "little")
                meta = raw(meta_obj_fn, [w])
                cn_ptr = raw(cb + RVA_CLASSNAME, [meta])
                cls = server._read_string(cn_ptr, 64)
            except Exception as ex:  # noqa: BLE001
                rows.append((i, w, f"<失败 {ex}>", ""))
                continue
            is_btn = ""
            try:
                if raw(cb + RVA_INHERITS, [w, "str:QAbstractButton"]):
                    is_btn = "BTN"
            except Exception:  # noqa: BLE001
                pass
            stat[cls] += 1
            rows.append((i, w, cls, is_btn))

        for i, w, cls, tag in rows:
            if needle and needle not in cls.lower():
                continue
            print(f"  [{i:3}] {w:#014x}  {cls:<28} {tag}")
        print("=== 类名统计 ===")
        for cls, cnt in stat.most_common(25):
            print(f"  {cnt:4}  {cls}")
        return 0

    if args.command == "qt-text":
        # qt-text <widget> [a|b|c]：实验 QString 返回 ABI
        #   a = [retbuf, this]  MSVC 标准（返回缓冲区在 rcx）
        #   b = [this]          假设返回值走 RAX
        #   c = [this, retbuf]  按反汇编：rcx=this、rdx=返回缓冲区
        if not args.params:
            print("用法: qt-text <widget_addr> [a|b|c]")
            return 1
        w = int(args.params[0], 0)
        mode = args.params[1] if len(args.params) > 1 else "c"
        pipe = server._get_pipe()
        wb = int(pipe.call("get_module", {"name": "Qt5Widgets.dll"})["result"]["base_hex"], 16)
        retbuf = int(pipe.call("alloc_memory", {"size": 256})["result"]["address"], 16)
        fargs = {"a": [retbuf, w], "b": [w], "c": [w, retbuf]}[mode]
        print(f"mode={mode} retbuf={retbuf:#x} args={[hex(x) for x in fargs]}")
        resp = pipe.call("call_function", {
            "address": hex(wb + 0xE0900), "args": fargs,
            "on_main_thread": True, "timeout_ms": 8000,
        })
        if "error" in resp:
            print(f"ERROR: {resp['error']}")
            return 1
        res = resp["result"]
        print(f"main_thread_status={res.get('main_thread_status')} ret={res.get('ret_hex')}")
        if res.get("main_thread_status", 0) != 0:
            return 1
        # 返回值可能落在 retbuf（模式 c）或 RAX（模式 b）
        cand = []
        cand.append(("retbuf", int.from_bytes(server._read_bytes(retbuf, 8), "little")))
        cand.append(("rax", int(res["ret_hex"], 16)))
        for src, d_ptr in cand:
            if not (0x10000 < d_ptr < 0x7FFFFFFFFFFF):
                continue
            try:
                h = server._read_bytes(d_ptr, 24)
                size = int.from_bytes(h[4:8], "little")
                off = int.from_bytes(h[16:24], "little", signed=True)
                print(f"  [{src}] d={d_ptr:#x} size={size} off={off:#x}")
                if 0 < size < 4096:
                    txt = server._read_bytes(d_ptr + off, size * 2).decode("utf-16-le", "replace")
                    print(f"         text = {txt!r}")
            except Exception as ex:  # noqa: BLE001
                print(f"  [{src}] {d_ptr:#x} 读取失败: {ex}")
        return 0

    if args.command == "qt-str":
        # qt-str <widget> <rva> [rva2 ...]：调用返回 QString 的成员函数并打印文本。
        # ABI 要点（实测 + 反汇编确认）：这类函数的隐藏返回缓冲区在 **rdx**，
        # 即调用形式为 rcxs=this、rdx=缓冲区 —— 不是 MSVC 文档里的「缓冲区在 rcx」。
        if len(args.params) < 2:
            print("用法: qt-str <widget_addr> <rva> [rva ...]")
            return 1
        w = int(args.params[0], 0)
        rvas = [int(x, 0) for x in args.params[1:]]
        pipe = server._get_pipe()
        wb = int(pipe.call("get_module", {"name": "Qt5Widgets.dll"})["result"]["base_hex"], 16)
        retbuf = int(pipe.call("alloc_memory", {"size": 256})["result"]["address"], 16)

        def read_qstring(d_ptr: int) -> str:
            if not (0x10000 < d_ptr < 0x7FFFFFFFFFFF):
                return ""
            head = server._read_bytes(d_ptr, 24)
            size = int.from_bytes(head[4:8], "little")
            off = int.from_bytes(head[16:24], "little", signed=True)
            if size <= 0 or size > 8192:
                return ""
            return server._read_bytes(d_ptr + off, size * 2).decode("utf-16-le", "replace")

        for rva in rvas:
            resp = pipe.call("call_function", {
                "address": hex(wb + rva), "args": [w, retbuf],
                "on_main_thread": True, "timeout_ms": 8000,
            })
            if "error" in resp:
                print(f"  rva={rva:#x} ERROR {resp['error']}")
                return 1
            res = resp["result"]
            if res.get("main_thread_status", 0) != 0:
                print(f"  rva={rva:#x} main_thread_status={res['main_thread_status']}")
                return 1
            d_ptr = int.from_bytes(server._read_bytes(retbuf, 8), "little")
            print(f"  rva={rva:#x}  ->  {read_qstring(d_ptr)!r}")
        return 0

    if args.command == "qt-buttons":
        # qt-buttons [过滤词]：列出所有按钮及其 toolTip / text —— 用来定位「Hammer」按钮
        needle = args.params[0].lower() if args.params else ""
        pipe = server._get_pipe()
        wb = int(pipe.call("get_module", {"name": "Qt5Widgets.dll"})["result"]["base_hex"], 16)
        cb = int(pipe.call("get_module", {"name": "Qt5Core.dll"})["result"]["base_hex"], 16)
        RVA_ALL_WIDGETS, RVA_INHERITS = 0xE270, 0x290560
        RVA_TEXT, RVA_TOOLTIP = 0xE0900, 0x4AE60
        retbuf = int(pipe.call("alloc_memory", {"size": 256})["result"]["address"], 16)

        def call(fn, fargs, timeout=8000):
            r = pipe.call("call_function", {
                "address": hex(fn), "args": fargs,
                "on_main_thread": True, "timeout_ms": timeout,
            })
            if "error" in r:
                raise RuntimeError(r["error"])
            res = r["result"]
            if res.get("main_thread_status", 0) != 0:
                raise RuntimeError(f"status={res['main_thread_status']}")
            return int(res["ret_hex"], 16)

        def qstr(fn_rva, this):
            call(wb + fn_rva, [this, retbuf])
            return read_qs(int.from_bytes(server._read_bytes(retbuf, 8), "little"))

        def read_qs(d_ptr):
            if not (0x10000 < d_ptr < 0x7FFFFFFFFFFF):
                return ""
            h = server._read_bytes(d_ptr, 24)
            size = int.from_bytes(h[4:8], "little")
            off = int.from_bytes(h[16:24], "little", signed=True)
            if size <= 0 or size > 8192:
                return ""
            return server._read_bytes(d_ptr + off, size * 2).decode("utf-16-le", "replace")

        call(wb + RVA_ALL_WIDGETS, [retbuf])
        qlist = int.from_bytes(server._read_bytes(retbuf, 8), "little")
        head = server._read_bytes(qlist, 24)
        begin = int.from_bytes(head[8:12], "little")
        end = int.from_bytes(head[12:16], "little")
        arr = qlist + 16
        n = end - begin

        hits = 0
        for i in range(n):
            w = int.from_bytes(server._read_bytes(arr + 8 * (begin + i), 8), "little")
            if not (0x10000 < w < 0x7FFFFFFFFFFF):
                continue
            try:
                if not call(cb + RVA_INHERITS, [w, "str:QAbstractButton"]):
                    continue
                tip = qstr(RVA_TOOLTIP, w)
                txt = qstr(RVA_TEXT, w)
            except Exception as e:  # noqa: BLE001
                print(f"  [{i}] {w:#x} 失败: {e}")
                return 1
            blob = f"{tip} | {txt}"
            if needle and needle not in blob.lower():
                continue
            hits += 1
            print(f"  [{i:3}] {w:#014x}  tip={tip!r}  text={txt!r}")
        print(f"命中 {hits} 个（共扫描 {n} 个 widget）")
        return 0

    if args.command == "qt-menu":
        # qt-menu [过滤词]：列出 QMenuBar / QMenu 里的菜单项(QAction) 及其地址。
        # QAction 不是 QWidget，allWidgets() 拿不到 —— 必须经 QWidget::actions() 取。
        needle = args.params[0].lower() if args.params else ""
        pipe = server._get_pipe()
        wb = int(pipe.call("get_module", {"name": "Qt5Widgets.dll"})["result"]["base_hex"], 16)
        cb = int(pipe.call("get_module", {"name": "Qt5Core.dll"})["result"]["base_hex"], 16)
        RVA_ALL_WIDGETS, RVA_CLASSNAME = 0xE270, 0x1D6140
        RVA_WIDGET_ACTIONS, RVA_ACTION_TEXT = 0x32E70, 0xB340
        retbuf = int(pipe.call("alloc_memory", {"size": 512})["result"]["address"], 16)

        def call(fn, fargs, timeout=8000):
            r = pipe.call("call_function", {
                "address": hex(fn), "args": fargs,
                "on_main_thread": True, "timeout_ms": timeout,
            })
            if "error" in r:
                raise RuntimeError(r["error"])
            res = r["result"]
            if res.get("main_thread_status", 0) != 0:
                raise RuntimeError(f"status={res['main_thread_status']}")
            return int(res["ret_hex"], 16)

        def qstr(fn, this):
            call(fn, [this, retbuf])
            d = int.from_bytes(server._read_bytes(retbuf, 8), "little")
            if not (0x10000 < d < 0x7FFFFFFFFFFF):
                return ""
            h = server._read_bytes(d, 24)
            size = int.from_bytes(h[4:8], "little")
            off = int.from_bytes(h[16:24], "little", signed=True)
            if size <= 0 or size > 8192:
                return ""
            return server._read_bytes(d + off, size * 2).decode("utf-16-le", "replace")

        def iter_widgets():
            call(wb + RVA_ALL_WIDGETS, [retbuf])
            qlist = int.from_bytes(server._read_bytes(retbuf, 8), "little")
            h = server._read_bytes(qlist, 24)
            begin = int.from_bytes(h[8:12], "little")
            end = int.from_bytes(h[12:16], "little")
            for i in range(end - begin):
                w = int.from_bytes(server._read_bytes(qlist + 16 + 8 * (begin + i), 8), "little")
                if 0x10000 < w < 0x7FFFFFFFFFFF:
                    yield w

        def class_of(w):
            vt = int.from_bytes(server._read_bytes(w, 8), "little")
            fn = int.from_bytes(server._read_bytes(vt, 8), "little")
            meta = call(fn, [w])
            cn = call(cb + RVA_CLASSNAME, [meta])
            return server._read_string(cn, 64)

        total = 0
        for w in iter_widgets():
            try:
                # 先用 inherits 廉筛（1 次远程调用），命中才做 className / 列 actions
                is_bar = call(cb + 0x290560, [w, "str:QMenuBar"])
                if not is_bar:
                    continue
                cls = class_of(w)
            except Exception:  # noqa: BLE001
                continue
            try:
                call(wb + RVA_WIDGET_ACTIONS, [w, retbuf])   # QList<QAction*> -> retbuf
                ql = int.from_bytes(server._read_bytes(retbuf, 8), "little")
                h = server._read_bytes(ql, 24)
                b2 = int.from_bytes(h[8:12], "little")
                e2 = int.from_bytes(h[12:16], "little")
                for j in range(e2 - b2):
                    a = int.from_bytes(server._read_bytes(ql + 16 + 8 * (b2 + j), 8), "little")
                    if not (0x10000 < a < 0x7FFFFFFFFFFF):
                        continue
                    txt = qstr(wb + RVA_ACTION_TEXT, a)
                    sub = call(wb + 0x8010, [a])             # QAction::menu() -> QMenu*
                    total += 1
                    if needle and needle not in txt.lower():
                        continue
                    print(f"  [{cls}] bar={w:#014x}  action={a:#014x}  menu={sub:#014x}  {txt!r}")
            except Exception as ex:  # noqa: BLE001
                print(f"  [{cls}] {w:#x} 取 actions 失败: {ex}")
                return 1
        print(f"共列出 {total} 个菜单项")
        return 0

    if args.command == "qt-actions":
        # qt-actions <menu_addr>：列出某个 QMenu 对象的子项(QAction) 地址与文本
        if not args.params:
            print("用法: qt-actions <menu_addr>")
            return 1
        menu = int(args.params[0], 0)
        needle = args.params[1].lower() if len(args.params) > 1 else ""
        pipe = server._get_pipe()
        wb = int(pipe.call("get_module", {"name": "Qt5Widgets.dll"})["result"]["base_hex"], 16)
        retbuf = int(pipe.call("alloc_memory", {"size": 512})["result"]["address"], 16)

        def call(fn_rva, fargs, timeout=8000):
            r = pipe.call("call_function", {
                "address": hex(wb + fn_rva), "args": fargs,
                "on_main_thread": True, "timeout_ms": timeout,
            })
            if "error" in r:
                raise RuntimeError(r["error"])
            res = r["result"]
            if res.get("main_thread_status", 0) != 0:
                raise RuntimeError(f"status={res['main_thread_status']}")
            return int(res["ret_hex"], 16)

        def qstr(fn_rva, this):
            call(fn_rva, [this, retbuf])
            d = int.from_bytes(server._read_bytes(retbuf, 8), "little")
            if not (0x10000 < d < 0x7FFFFFFFFFFF):
                return ""
            h = server._read_bytes(d, 24)
            size = int.from_bytes(h[4:8], "little")
            off = int.from_bytes(h[16:24], "little", signed=True)
            if size <= 0 or size > 8192:
                return ""
            return server._read_bytes(d + off, size * 2).decode("utf-16-le", "replace")

        call(0x32E70, [menu, retbuf])
        ql = int.from_bytes(server._read_bytes(retbuf, 8), "little")
        h = server._read_bytes(ql, 24)
        b2 = int.from_bytes(h[8:12], "little")
        e2 = int.from_bytes(h[12:16], "little")
        n = 0
        for j in range(e2 - b2):
            a = int.from_bytes(server._read_bytes(ql + 16 + 8 * (b2 + j), 8), "little")
            if not (0x10000 < a < 0x7FFFFFFFFFFF):
                continue
            txt = qstr(0xB340, a)
            sub = call(0x8010, [a])
            n += 1
            if needle and needle not in txt.lower():
                continue
            print(f"  action={a:#014x}  submenu={sub:#014x}  {txt!r}")
        print(f"共 {n} 项")
        return 0

    if args.command == "qt-trigger":
        # qt-trigger <action_addr>：触发 QAction（等价于点菜单项）
        if not args.params:
            print("用法: qt-trigger <action_addr>")
            return 1
        pipe = server._get_pipe()
        wb = int(pipe.call("get_module", {"name": "Qt5Widgets.dll"})["result"]["base_hex"], 16)
        resp = pipe.call("call_function", {
            "address": hex(wb + 0xBBC0),          # QAction::trigger()
            "args": [int(args.params[0], 0)],
            "on_main_thread": True,
            "timeout_ms": 10000,
        })
        print(json.dumps(resp, indent=2, ensure_ascii=False))
        return 0 if "error" not in resp else 1

    if args.command == "tl":
        # tl：单独验证 QApplication::topLevelWidgets()（排查它是否可用）
        pipe = server._get_pipe()
        wb = int(pipe.call("get_module", {"name": "Qt5Widgets.dll"})["result"]["base_hex"], 16)
        retbuf = int(pipe.call("alloc_memory", {"size": 256})["result"]["address"], 16)
        r = pipe.call("call_function", {
            "address": hex(wb + 0x17A80), "args": [retbuf],
            "on_main_thread": True, "timeout_ms": 20000,
        })
        print(json.dumps(r, indent=2, ensure_ascii=False))
        if "error" not in r and r["result"].get("main_thread_status", 0) == 0:
            ql = int.from_bytes(server._read_bytes(retbuf, 8), "little")
            print(f"qlist={ql:#x}")
            if ql:
                head = server._read_bytes(ql, 24)
                b = int.from_bytes(head[8:12], "little")
                e = int.from_bytes(head[12:16], "little")
                print(f"count={e - b}")
        return 0

    if args.command == "vc":
        # vc <this> <vtable_offset> [int_args...]：免 JSON 调虚函数（默认走主线程）
        # vtable_offset 单位是字节，与 IDA 的 vtable[N] 记法一致（N*8）
        if len(args.params) < 2:
            print("用法: vc <this_addr> <vtable_offset> [int_args...]")
            return 1
        resp = server._get_pipe().call("call_virtual", {
            "this": args.params[0],
            "vtable_offset": int(args.params[1], 0),
            "args": [int(x, 0) for x in args.params[2:]],
            "on_main_thread": True,
            "timeout_ms": 10000,
        })
        print(json.dumps(resp, indent=2, ensure_ascii=False))
        return 0 if "error" not in resp else 1

    if args.command == "cls":
        # cls <obj>：读任意 Qt 对象的类名（走 metaObject()->className()，全程平凡返回类型）
        if not args.params:
            print("用法: cls <obj_addr>")
            return 1
        obj = int(args.params[0], 0)
        pipe = server._get_pipe()
        cb = int(pipe.call("get_module", {"name": "Qt5Core.dll"})["result"]["base_hex"], 16)
        RVA_CLASSNAME = 0x1D6140

        def qcall(fn, a):
            r = pipe.call("call_function", {
                "address": hex(fn), "args": a,
                "on_main_thread": True, "timeout_ms": 8000,
            })
            if "error" in r:
                raise RuntimeError(r["error"])
            res = r["result"]
            if res.get("main_thread_status", 0) != 0:
                raise RuntimeError(f"status={res['main_thread_status']}")
            return int(res["ret_hex"], 16)

        meta_fn = int.from_bytes(server._read_bytes(int.from_bytes(server._read_bytes(obj, 8), "little"), 8), "little")
        meta = qcall(meta_fn, [obj])                  # QMetaObject*
        cn = qcall(cb + RVA_CLASSNAME, [meta])        # const char*
        print(f"{obj:#x}  meta={meta:#x}  class={server._read_string(cn, 64)!r}")
        return 0

    params = json.loads(args.params[0]) if args.params else None
    resp = server._get_pipe().call(args.command, params)
    print(json.dumps(resp, indent=2, ensure_ascii=False))
    return 0 if "error" not in resp else 1


if __name__ == "__main__":
    sys.exit(main())
