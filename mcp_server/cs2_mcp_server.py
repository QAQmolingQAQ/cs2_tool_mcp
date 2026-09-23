#!/usr/bin/env python3
"""
CS2 Tool MCP Server
===================

通过命名管道与注入到 hammer.exe 中的 cs2_tool.dll 通信，把 Hammer 工具模式
的能力暴露为 MCP tools。整体结构参考 blender-mcp：

    ┌──────────────┐   命名管道     ┌───────────────┐   CreateInterface   ┌──────────┐
    │ 本 MCP Server │◄────────────►│ cs2_tool.dll  │◄──────────────────►│ hammer.dll│
    │  (FastMCP)   │ \\\\.\\pipe\\  │ (注入 hammer)  │                     │  pet.dll │
    └──────────────┘  CS2ToolMCP   └───────────────┘                     └──────────┘

工具分组
--------
* 连接/状态 : cs2_pipe_ping, cs2_hammer_status, cs2_initialize, cs2_list_tools
* 接口      : cs2_list_interfaces, cs2_get_interface
* 模块      : cs2_list_modules, cs2_get_module
* 内存      : cs2_read_memory, cs2_read_qword, cs2_read_value,
              cs2_write_value, cs2_read_string, cs2_read_ptr_chain
* 扫描      : cs2_find_pattern
* 调用      : cs2_call_function, cs2_call_virtual
* 撤销/重做 : cs2_undo, cs2_redo
* 地图      : cs2_map_list_docs, cs2_get_hammer_app

启动方式
--------
    python cs2_mcp_server.py
    python cs2_mcp_server.py --pipe \\\\.\\pipe\\CS2ToolMCP

前置条件：先用 injector/inject_dll.py 把 cs2_tool.dll 注入 hammer.exe。
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("ERROR: mcp package not found. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# 协议常量（必须与 injected_dll/protocol.h 一致）
# ---------------------------------------------------------------------------
MSG_MAGIC = 0x43533254  # "CS2T"
MSG_VERSION = 1
HEADER_SIZE = 16  # 4 x uint32

DEFAULT_PIPE = os.environ.get("CS2_TOOL_PIPE", r"\\.\pipe\CS2ToolMCP")
DEFAULT_PIPE_TIMEOUT = 5000  # ms


# ---------------------------------------------------------------------------
# 传输层：命名管道客户端
# ---------------------------------------------------------------------------
class Cs2Pipe:
    """与注入 DLL 中 IpcPipeServer 对应的命名管道客户端。"""

    def __init__(self, pipe_name: str = DEFAULT_PIPE, timeout_ms: int = DEFAULT_PIPE_TIMEOUT):
        self.pipe_name = pipe_name
        self.timeout_ms = timeout_ms
        self._handle: int | None = None

    # -- Win32 原语 ----------------------------------------------------

    @staticmethod
    def _kernel32():
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        k32.WaitNamedPipeW.restype = ctypes.c_int
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CreateFileW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ]
        k32.WriteFile.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
        ]
        k32.ReadFile.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
        ]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        return k32

    def _open(self) -> None:
        import ctypes
        k32 = self._kernel32()
        if not k32.WaitNamedPipeW(self.pipe_name, self.timeout_ms):
            raise ConnectionError(
                f"WaitNamedPipe failed for {self.pipe_name} (err={ctypes.get_last_error()}). "
                "cs2_tool.dll 是否已注入 hammer.exe？"
            )
        handle = k32.CreateFileW(
            self.pipe_name, 0x80000000 | 0x40000000, 0, None, 3, 0, None
        )
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise ConnectionError(
                f"CreateFileW failed for {self.pipe_name} (err={ctypes.get_last_error()})"
            )
        self._handle = handle

    def _close(self) -> None:
        if self._handle is not None:
            self._kernel32().CloseHandle(self._handle)
            self._handle = None

    def _write_all(self, data: bytes) -> None:
        import ctypes
        k32 = self._kernel32()
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        total = 0
        while total < len(data):
            written = ctypes.c_uint32(0)
            ok = k32.WriteFile(
                self._handle, ctypes.byref(buf, total),
                len(data) - total, ctypes.byref(written), None,
            )
            if not ok or written.value == 0:
                raise IOError("WriteFile failed")
            total += written.value

    def _read_exact(self, n: int) -> bytes:
        import ctypes
        k32 = self._kernel32()
        buf = ctypes.create_string_buffer(n)
        total = 0
        while total < n:
            got = ctypes.c_uint32(0)
            ok = k32.ReadFile(
                self._handle, ctypes.byref(buf, total),
                n - total, ctypes.byref(got), None,
            )
            if not ok or got.value == 0:
                raise IOError("ReadFile failed / pipe closed")
            total += got.value
        return buf.raw[:n]

    # -- 协议 API ------------------------------------------------------

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """发送 {id, method, params}，返回解析后的响应对应 dict。"""
        req: dict[str, Any] = {
            "id": int(time.time() * 1000) & 0x7FFFFFFF,
            "method": method,
        }
        if params is not None:
            req["params"] = params
        payload = json.dumps(req).encode("utf-8")

        frame = struct.pack("<IIII", MSG_MAGIC, MSG_VERSION, len(payload), 0) + payload

        self._open()
        try:
            self._write_all(frame)
            magic, _version, length, _reserved = struct.unpack("<IIII", self._read_exact(HEADER_SIZE))
            if magic != MSG_MAGIC:
                raise IOError(f"Bad response magic: 0x{magic:x}")
            body = self._read_exact(length) if length else b""
        finally:
            self._close()

        return json.loads(body.decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "cs2_tool",
    instructions=(
        "CS2 Hammer 工具模式 MCP —— 通过命名管道桥接到注入 hammer.exe 的 cs2_tool.dll。\n"
        "使用前请先注入 cs2_tool.dll。地址参数支持绝对地址 (0x...) 或 'hammer.dll+0x12E1B50' 形式。"
    ),
)

_pipe: Cs2Pipe | None = None


def _get_pipe() -> Cs2Pipe:
    global _pipe
    if _pipe is None:
        _pipe = Cs2Pipe()
    return _pipe


def _call(method: str, params: dict[str, Any] | None = None) -> str:
    """统一调用入口：格式化成功结果，把异常转成可读文本。"""
    try:
        resp = _get_pipe().call(method, params)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}\n请先把 cs2_tool.dll 注入 hammer.exe。"
    except Exception as e:  # noqa: BLE001 - 面向 LLM 的可读错误
        return f"ERROR {type(e).__name__}: {e}"

    if "error" in resp:
        return f"INJECTED_DLL_ERROR: {resp['error']}"

    result = resp.get("result")
    if result is None:
        return json.dumps(resp, indent=2, ensure_ascii=False)
    if isinstance(result, str):
        try:
            return json.dumps(json.loads(result), indent=2, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            return result
    return json.dumps(result, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 连接 / 状态
# ---------------------------------------------------------------------------
@mcp.tool()
def cs2_pipe_ping() -> str:
    """探测注入的 cs2_tool.dll 是否存活（验证命名管道 IPC）。
    返回目标进程内的初始化状态。"""
    return _call("ping")


@mcp.tool()
def cs2_hammer_status() -> str:
    """获取 hammer.dll 桥接状态：模块基址、CreateInterface 指针、
    ToolSystem2_001 实例，以及已注册接口名的前 30 个。"""
    return _call("get_status")


@mcp.tool()
def cs2_initialize() -> str:
    """强制（重新）初始化 DLL 内的 HammerBridge：
    重新枚举 hammer.dll、重新解析 CreateInterface、重新获取 ToolSystem2_001。
    在 hammer.dll 加载完成后调用。"""
    return _call("initialize")


@mcp.tool()
def cs2_list_tools() -> str:
    """列出注入 DLL 当前支持的所有 IPC 方法名。"""
    return _call("list_tools")


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
@mcp.tool()
def cs2_list_interfaces() -> str:
    """列出 hammer.dll 中 CreateInterface 链表上注册的全部 Valve 风格接口名
    （如 ToolSystem2_001、HammerMapLoader001 ...）。"""
    return _call("list_interfaces")


@mcp.tool()
def cs2_get_interface(name: str) -> str:
    """调用 CreateInterface(name)，返回接口指针与返回码（0=成功, 1=未找到）。
    例：name='ToolSystem2_001'。"""
    return _call("get_interface", {"name": name})


# ---------------------------------------------------------------------------
# 模块
# ---------------------------------------------------------------------------
@mcp.tool()
def cs2_list_modules() -> str:
    """列出目标进程已加载模块的 name / base / image_base / size。"""
    return _call("list_modules")


@mcp.tool()
def cs2_get_module(name: str) -> str:
    """获取单个模块的基址与大小。name 可省略 .dll，如 'hammer'、'pet'。"""
    return _call("get_module", {"name": name})


# ---------------------------------------------------------------------------
# 内存
# ---------------------------------------------------------------------------
@mcp.tool()
def cs2_read_memory(address: str, size: int = 8) -> str:
    """从 hammer.exe 进程内读取原始内存，返回十六进制转储。

    Args:
        address: 绝对地址 (0x...) 或 'hammer.dll+0x12E1B50' 形式。
        size: 读取字节数（上限 1024）。
    """
    return _call("read_memory", {"address": address, "size": size})


@mcp.tool()
def cs2_read_qword(address: str) -> str:
    """读取 8 字节指针值（cs2_read_memory 的便捷封装）。"""
    return _call("read_qword", {"address": address})


@mcp.tool()
def cs2_read_value(address: str, type: str = "u64") -> str:
    """按类型读取一个值。

    Args:
        address: 绝对地址或 'hammer.dll+0x...' 形式。
        type: u8/u16/u32/u64/i8/i16/i32/i64/f32/f64/ptr
    """
    return _call("read_value", {"address": address, "type": type})


@mcp.tool()
def cs2_write_value(address: str, value: int, type: str = "u64") -> str:
    """按类型写入一个值（谨慎使用，可能影响目标稳定性）。

    Args:
        address: 绝对地址或 'hammer.dll+0x...' 形式。
        value: 要写入的整数/位模式（float 请传其位模式的十进制整数）。
        type: u8/u16/u32/u64/i8/i16/i32/i64/f32/f64/ptr
    """
    return _call("write_value", {"address": address, "value": value, "type": type})


@mcp.tool()
def cs2_read_string(address: str, max_len: int = 256) -> str:
    """读取以 NUL 结尾的 C 字符串（跨页时安全截断）。"""
    return _call("read_string", {"address": address, "max_len": max_len})


@mcp.tool()
def cs2_read_ptr_chain(base: str, offsets: list[int]) -> str:
    """按多级指针链解析最终地址：base -> +off0 -> [ptr] +off1 -> [ptr] +off2 ...

    Args:
        base: 起始地址。
        offsets: 偏移序列（十进制或十六进制整数）。
    """
    return _call("read_ptr_chain", {"base": base, "offsets": offsets})


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------
@mcp.tool()
def cs2_find_pattern(pattern: str, module: str = "hammer.dll", limit: int = 20) -> str:
    """在模块内存中做 AOB 特征扫描。

    Args:
        pattern: 形如 '48 8B ?? E8 ?? ?? ?? ??'，'??' 或 '?' 为通配。
        module: 目标模块名（默认 hammer.dll）。
        limit: 最多返回命中数（默认 20）。
    """
    return _call("find_pattern", {"pattern": pattern, "module": module, "limit": limit})


# ---------------------------------------------------------------------------
# 调用（通用原语，等价于 Blender MCP 的 execute_blender_code 的“可编程”能力）
# ---------------------------------------------------------------------------
@mcp.tool()
def cs2_call_function(address: str, args: list[int] | None = None,
                      on_main_thread: bool = False) -> str:
    """调用任意函数（x64 fastcall，最多 6 个整数/指针参数）。

    参数顺序：args[0]→RCX, args[1]→RDX, args[2]→R8, args[3]→R9, args[4..5]→栈。
    调用 C++ 成员函数时，args[0] 传 this 指针。

    Args:
        address: 函数地址（绝对或 'hammer.dll+0x...'）。
        args: 整数参数列表；字符串形式的地址也可（会被解析）。
        on_main_thread: 在 Hammer 主线程执行。**凡是会改文档/UI 的函数都应置 True**
            —— 从管道线程直接调用这类函数可能永不返回（实测：地图撤销会把历史
            留在 busy 状态）。实现为主线程临时 WH_GETMESSAGE 钩子派发。
    """
    params: dict[str, Any] = {"address": address, "args": args or []}
    if on_main_thread:
        params["on_main_thread"] = True
        params["timeout_ms"] = 15000
    return _call("call_function", params)


@mcp.tool()
def cs2_call_virtual(this_ptr: str, vtable_offset: int, args: list[int] | None = None,
                     on_main_thread: bool = False, timeout_ms: int = 5000) -> str:
    """调用对象的虚函数。

    Args:
        this_ptr: 对象指针（作为隐式第一个参数）。
        vtable_offset: 虚表字节偏移（与 IDA 的 vtable[1040] 记法一致，单位字节）。
        args: 其余整数参数。
        on_main_thread: 在 Hammer 主线程执行。**会改文档/UI 的虚函数必须置 True**
            （从管道线程调用可能永不返回并把历史留在 busy 态）。
        timeout_ms: 主线程等待超时（仅 on_main_thread=True 时有意义）。
    """
    return _call("call_virtual", {
        "this": this_ptr, "vtable_offset": vtable_offset, "args": args or [],
        "on_main_thread": on_main_thread, "timeout_ms": timeout_ms,
    })


# ---------------------------------------------------------------------------
# 撤销 / 重做（已逆向 + 运行时验证，见 REVERSE_NOTES.md §2.7/2.8）
# ---------------------------------------------------------------------------
RVA_CDATAMODEL_GLOBAL = 0x2344140   # CDataModel 全局单例（静态初始化 sub_18004F500）
RVA_CDATAMODEL_VTABLE = 0x1587B90   # 用于运行前校验
UNDO_MANAGER_OFFSET = 240           # CUndoManager 内嵌在 CDataModel + 240
RVA_CDATAMODEL_UNDO = 0x4C0B60      # 带 UI 通知的包装
RVA_CDATAMODEL_REDO = 0x4BEBE0
RVA_UNDO_MANAGER_UNDO = 0x50B720    # CUndoManager::Undo 本体
RVA_UNDO_MANAGER_REDO = 0x50B290


def _hammer_base() -> int:
    """hammer.dll 的基址（= PE ImageBase）。

    可用环境变量 `CS2_HAMMER_BASE` 覆盖（十六进制或十进制）。用途：注入 DLL 的模块
    列表若因故看不到 hammer.dll（例如模块枚举缓存陈旧），可临时用外部工具（CE）
    取到基址后走绝对地址，不必重启目标进程。
    """
    override = os.environ.get("CS2_HAMMER_BASE")
    if override:
        return int(override, 0)
    resp = _get_pipe().call("get_module", {"name": "hammer"})
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return int(resp["result"]["base_hex"], 16)


def _hammer_addr(rva: int) -> str:
    """把 hammer.dll 的 RVA 表达成 DLL 能解析的地址表达式。

    有 `CS2_HAMMER_BASE` 覆盖时直接用绝对地址（绕开 DLL 的模块查找）。
    """
    override = os.environ.get("CS2_HAMMER_BASE")
    if override:
        return hex(int(override, 0) + rva)
    return f"hammer.dll+{rva:#x}"


def _read_int(address: int, type_: str) -> int:
    resp = _get_pipe().call("read_value", {"address": address, "type": type_})
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp["result"]["value"]


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


@mcp.tool()
def cs2_undo(use_wrapper: bool = True) -> str:
    """撤销 Datamodel(DMX) 的上一笔操作。

    ⚠️ 注意：这是 **Datamodel(DMX) 的撤销栈**（CDataModel 全局单例 hammer.dll+0x2344140，
    内嵌 CUndoManager@+240），**不影响地图编辑历史**（地图历史在 CMapDocHistory，见
    REVERSE_NOTES.md §2.8）。地图撤销入口尚未定位。

    Args:
        use_wrapper: True 走 CDataModel::Undo (hammer.dll+0x4C0B60)，会额外通知 UI 刷新；
                     False 直接调 CUndoManager::Undo (hammer.dll+0x50B720)。
    """
    return _undo_redo("undo", use_wrapper)


@mcp.tool()
def cs2_redo(use_wrapper: bool = True) -> str:
    """重做 Datamodel(DMX) 的操作。⚠️ 同样不影响地图编辑历史，详见 cs2_undo。"""
    return _undo_redo("redo", use_wrapper)


# ---------------------------------------------------------------------------
# 地图 / Hammer
# ---------------------------------------------------------------------------
RVA_MAP_HISTORY_POP = 0x14080D0      # 通用「弹出并应用」：Undo/Redo 同一函数，靠 this 区分
RVA_MAP_HISTORY_VTABLE = 0x1628508   # CMapDocHistory vtable，用于扫描定位
RVA_MAP_DOC_TABLE = 0x2355028        # CMapDoc* 数组
RVA_MAP_DOC_COUNT = 0x2355020        # 数组元素个数
MAP_DOC_SESSION_OFFSET = 0xCD0       # CMapDoc -> CHammerEditorSession
MAP_SESSION_SCAN_SIZE = 0x1000       # 在 session 内扫描 CMapDocHistory 的字节数

# 主线程派发状态（与 injected_dll/hammer_bridge.cpp 的 g_last_dispatch_status 对应）
MAIN_THREAD_STATUS_NAMES = {
    0: "成功",
    1: "等待超时（目标函数未返回，可能卡住）",
    2: "未找到主线程",
    3: "SetWindowsHookEx 失败",
    4: "调用中触发异常（已由 SEH 捕获，宿主进程未受影响）",
}


@mcp.tool()
def cs2_map_list_docs() -> str:
    """枚举当前所有打开的 CMapDoc 文档（来自 hammer.dll 全局文档表 0x182355028），
    返回地址与地图名。"""
    return _call("map_list_docs")


@mcp.tool()
def cs2_get_hammer_app() -> str:
    """获取 CHammerApp / ToolSystem2_001 顶层应用对象指针
    （IDA: ToolSystem2_001 工厂 sub_180115270 返回 CHammerApp）。"""
    return _call("get_hammer_app")


MAX_READ_CHUNK = 1024  # DLL 侧 read_memory 单次上限


def _read_bytes(address: int, size: int) -> bytes:
    """分块读取（DLL 的 read_memory 单次最多 1024 字节）。"""
    out = bytearray()
    while len(out) < size:
        n = min(size - len(out), MAX_READ_CHUNK)
        resp = _get_pipe().call("read_memory", {"address": address + len(out), "size": n})
        if "error" in resp:
            raise RuntimeError(resp["error"])
        out += bytes.fromhex(resp["result"]["hex"][2:])
    return bytes(out)


def _read_string(address: int, max_len: int = 256) -> str:
    """读取 C 字符串。"""
    resp = _get_pipe().call("read_string", {"address": address, "max_len": max_len})
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp["result"]["value"]


def _find_map_histories() -> tuple[int, int]:
    """定位当前地图的 (undoHistory, redoHistory)。

    路径：全局文档表 -> CMapDoc -> CHammerEditorSession(CMapDoc+0xCD0)
          -> 扫描 session 前 0x1000 字节，找 vtable == CMapDocHistory::vftable 的指针，
             按偏移升序取前两个（第一个=撤销历史，第二个=重做历史）。

    ⚠️ 不硬编码 session 内偏移：实测实体机与 VM 上该偏移不同（+0x740 vs +0x9C0）。
    """
    base = _hammer_base()
    if _read_int(base + RVA_MAP_DOC_COUNT, "u32") == 0:
        raise RuntimeError("当前没有打开的地图文档")
    doc_arr = _read_int(base + RVA_MAP_DOC_TABLE, "u64")
    if not doc_arr:
        raise RuntimeError("全局文档表为空")
    doc = _read_int(doc_arr, "u64")
    if not doc:
        raise RuntimeError("文档表首元素为空")
    session = _read_int(doc + MAP_DOC_SESSION_OFFSET, "u64")
    if not session:
        raise RuntimeError("未找到 CHammerEditorSession")

    want = base + RVA_MAP_HISTORY_VTABLE
    blk = _read_bytes(session, MAP_SESSION_SCAN_SIZE)
    found: list[tuple[int, int]] = []
    seen: set[int] = set()
    for off in range(0, len(blk) - 7, 8):
        cand = int.from_bytes(blk[off:off + 8], "little")
        if cand < 0x10000 or cand >= 0x800000000000 or cand in seen:
            continue
        seen.add(cand)
        try:
            if _read_int(cand, "u64") == want:
                found.append((off, cand))
                if len(found) == 2:
                    break
        except Exception:  # noqa: BLE001  不可读的候选直接跳过
            continue

    if len(found) < 2:
        raise RuntimeError(f"只找到 {len(found)} 个 CMapDocHistory（期望 2 个）")
    return found[0][1], found[1][1]


def _map_undo_redo(action: str) -> str:
    try:
        undo_h, redo_h = _find_map_histories()
        this_ptr = undo_h if action == "undo" else redo_h
        before_u = _read_int(undo_h + 8, "u32")
        before_r = _read_int(redo_h + 8, "u32")

        resp = _get_pipe().call("call_function", {
            "address": _hammer_addr(RVA_MAP_HISTORY_POP),
            "args": [this_ptr],
            # 必须走 Hammer 主线程：从管道线程直接调用会让该函数永不返回，
            # 并把历史留在 busy(+0x8C) 状态（实测），故 timeout 给足。
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

        after_u = _read_int(undo_h + 8, "u32")
        after_r = _read_int(redo_h + 8, "u32")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    name = "地图 Undo" if action == "undo" else "地图 Redo"
    note = ""
    if before_u == after_u and before_r == after_r:
        note = f"\n  提示: 计数未变化，{'撤销' if action == 'undo' else '重做'}栈可能已空"
    return (
        f"{name} 完成 (ret={ret}, this={this_ptr:#x})\n"
        f"  undo 历史: {before_u} -> {after_u}\n"
        f"  redo 历史: {before_r} -> {after_r}{note}"
    )


@mcp.tool()
def cs2_map_undo() -> str:
    """撤销**地图编辑**的上一步操作（真正的 Hammer 撤销，非 Datamodel）。

    已用 CE 硬件断点实测验证：RVA 0x14080D0 是通用的「从传入历史对象弹出并应用」，
    Undo/Redo 共用该函数，靠 `this` 区分：
      - this = 撤销历史对象 -> 撤销
      - this = 重做历史对象 -> 重做
    详见 REVERSE_NOTES.md §2.9。
    """
    return _map_undo_redo("undo")


@mcp.tool()
def cs2_map_redo() -> str:
    """重做**地图编辑**的下一步操作（真正的 Hammer 重做）。详见 cs2_map_undo。"""
    return _map_undo_redo("redo")


MAP_DOC_PATH_OFFSET = 0x6A0   # CMapDoc -> 地图全路径（CUtlString，+0 即 char*）


@mcp.tool()
def cs2_map_info() -> str:
    """返回当前地图文档的信息：路径 / 文件名 / 关键对象地址 / 撤销栈深度。

    `CMapDoc+0x6A0` 指向地图全路径字符串（VM 实测得到
    `.../content/csgo_addons/test/maps/untitled_1.vmap`）。
    """
    try:
        doc = _map_doc()
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
        undo_h, redo_h = _find_map_histories()
        lines.append(f"  撤销历史 : {_read_int(undo_h + 8, 'u32')} 步"
                     f"   重做历史: {_read_int(redo_h + 8, 'u32')} 步")
        lines.append(f"  undo历史对象: {undo_h:#x}    redo历史对象: {redo_h:#x}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"  （撤销历史读取失败: {e}）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Qt 自动化：触发菜单项（保存等 UI 操作，等价于点菜单，不依赖窗口焦点）
# 原理见 REVERSE_NOTES §2.14：Qt5 以 mangled 名导出全部 public 符号；
# 且 QAction 不是 QWidget，必须经 QWidget::actions() 取。
# ---------------------------------------------------------------------------
RVA_QT_ALL_WIDGETS = 0xE270        # QApplication::allWidgets()   @ Qt5Widgets
RVA_QT_TOPLEVEL_WIDGETS = 0x17A80  # QApplication::topLevelWidgets() @ Qt5Widgets
RVA_QT_MENUBAR = 0x135220          # QMainWindow::menuBar()       @ Qt5Widgets
RVA_QT_ACTION_TEXT = 0xB340        # QAction::text()              @ Qt5Widgets
RVA_QT_ACTION_TRIGGER = 0xBBC0     # QAction::trigger()           @ Qt5Widgets
RVA_QT_ACTION_MENU = 0x8010        # QAction::menu()              @ Qt5Widgets
RVA_QT_WIDGET_ACTIONS = 0x32E70    # QWidget::actions()           @ Qt5Widgets
RVA_QT_INHERITS = 0x290560         # QObject::inherits(const char*) @ Qt5Core

_qt_menu_cache: dict[str, tuple[int, int]] = {}   # key -> (action 地址, Qt5Widgets 基址)


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


def _qt_call(fn: int, args: list[int], timeout: int = 10000) -> int:
    """在主线程调用 Qt 函数并返回 RAX。

    ⚠️ 返回 QString/QList 这类非平凡类型的函数，隐藏返回缓冲区要放在 **rdx**
    （不是 rcx）—— 所以调用形式是 [this, retbuf] 或 [retbuf]（静态无参）。
    """
    resp = _get_pipe().call("call_function", {
        "address": hex(fn), "args": args,
        "on_main_thread": True, "timeout_ms": timeout,
    })
    if "error" in resp:
        raise RuntimeError(resp["error"])
    res = resp["result"]
    st = res.get("main_thread_status", 0)
    if st != 0:
        raise RuntimeError(f"主线程调用失败 status={st} (1=超时 2=无主线程 3=钩子失败 4=异常)")
    return int(res["ret_hex"], 16)


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
    _qt_call(wb + RVA_QT_ACTION_TEXT, [action, retbuf], 5000)
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
    hit = _qt_menu_cache.get(key)
    if hit and hit[1] == wb:
        return hit[0]

    retbuf = _qt_alloc(512)

    def _actions_of(obj: int) -> list[int]:
        _qt_call(wb + RVA_QT_WIDGET_ACTIONS, [obj, retbuf], 10000)
        return _read_qlist(int.from_bytes(_read_bytes(retbuf, 8), "little"))

    # 1) 收集候选菜单栏
    # 注意：主线程派发是「设置共享槽位 + 等钩子」的串行机制，短时间内发太多
    # on_main_thread 调用会积压并超时。所以先用 read_memory（不走主线程）读 vtable
    # 去重，只对每种类型各问一次 inherits。
    _qt_call(wb + RVA_QT_TOPLEVEL_WIDGETS, [retbuf], 20000)
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
                if _qt_call(cb + RVA_QT_INHERITS, [w, "str:QMainWindow"], 10000):
                    kind = "QMainWindow"
                elif _qt_call(cb + RVA_QT_INHERITS, [w, "str:QMenuBar"], 10000):
                    kind = "QMenuBar"
            except Exception:  # noqa: BLE001
                kind = ""
            seen[vt] = kind
        if kind == "QMainWindow":
            bar = _qt_call(wb + RVA_QT_MENUBAR, [w], 10000)     # QMenuBar*
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
            sub = _qt_call(wb + RVA_QT_ACTION_MENU, [top], 10000)   # -> QMenu*
            if not sub:
                continue
            for a in _actions_of(sub):
                txt = _qt_action_text(a, retbuf, wb)
                if needle in txt and (not exclude or exclude not in txt):
                    _qt_menu_cache[key] = (a, wb)
                    return a
    return 0


@mcp.tool()
def cs2_map_save() -> str:
    """保存当前地图（等价于 Hammer 的 File → Save / Ctrl+S）。

    ⚠️ 已知限制（详见 REVERSE_NOTES §2.14）：本实现靠触发 Qt 菜单项 `&Save` 完成，
    **只适合「已有真实文件路径」的地图**。若地图是 `&New` 出来的（只有内存中的
    虚拟路径、磁盘上并无此文件），Hammer 会走「指定文件名」流程并弹出模态对话框，
    而模态对话框会开启嵌套消息循环，使 trigger() 永不返回（表现为超时）。
    这种情况请改在实体机 UI 上手动另存。

    返回值中的 action 地址可用于确认「确实找到并触发了正确的菜单项」。
    """
    try:
        action = _qt_find_menu_action("&Save\t", menu="File", exclude="As")
        if not action:
            return "ERROR 没找到 File→Save 菜单项（Hammer 是否已打开地图？）"
        wb, _ = _qt_bases()
        try:
            _qt_call(wb + RVA_QT_ACTION_TRIGGER, [action], 8000)
        except Exception as e:  # noqa: BLE001
            return (
                f"⚠️ 已触发 保存（action={action:#x}），但调用未在超时内返回：{e}\n"
                "   最常见原因：地图还没有真实文件名（&New 建的地图）→ Hammer 弹了"
                "「另存为」模态对话框。请到实体机 UI 上指定路径，或先 &Open 一张已有地图。"
            )
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    return f"已保存（action={action:#x}）"


# ---------------------------------------------------------------------------
# 实体：CMapDoc -> CMapWorld -> 引擎遍历（枚举 / 属性读写）
# ---------------------------------------------------------------------------
RVA_ENTITY_GET_ATTR = 0x729670      # GetAttribute(entity, name, out_node) -> const char*
RVA_ENTITY_FIND_ATTR_IDX = 0x729C50  # FindAttributeIdx(entity, name, default) -> int

# --- 属性写入（Datamodel 层，见 REVERSE_NOTES §2.12）---
# 实体（CMapEntity）本质是 CDmElement，属性是 CDmAttribute 链表：
#   +0x00 next / +0x08 值 / +0x10 所属 element / +0x1C 类型(低6位) / +0x20 名字
# 字符串属性（类型 5 = AT_STRING）的写入必须传「驻留符号（CUtlSymbolLarge）」，
# 所以链路是：InternString(value) -> CDmAttribute::SetValue<CUtlSymbolLarge>。
RVA_DATAMODEL = 0x207E5D8           # off_18207E5D8：Datamodel 全局接口
VFN_OFF_INTERN_STRING = 424         # 该接口 vtable 字节偏移 424 = InternString(const char*) -> CUtlSymbolLarge
RVA_ATTR_SET_SYMBOL = 0x4C7A10      # CDmAttribute::SetValue<CUtlSymbolLarge>(attr, CUtlSymbolLarge*)
ATTR_OFF_TYPE = 0x1C                # CDmAttribute+0x1C：低 6 位为类型
DM_ATTR_TYPE_STRING = 5             # AT_STRING

# --- Datamodel undo scope（§2.12）---
# CDmAttribute::SetValue 内部只有当「undo 总开关开着」且「element 处于 undo scope 中」时
# 才会创建 CUndoAttributeSetValueElement 记进撤销栈；裸调用则完全不记录（实测）。
# 因此改属性要用 BeginUndoScope/EndUndoScope 包起来。
RVA_UNDO_SCOPE_BEGIN = 0x50B1C0     # CUndoManager::BeginUndoScope(um, name, desc, flags)
RVA_UNDO_SCOPE_END = 0x50B0D0       # CUndoManager::EndUndoScope(um) -> bool(是否有操作提交)
UNDO_MGR_OFF_SCOPE_DEPTH = 84       # +0x54 scope 嵌套深度（Begin +1 / End -1）
UNDO_MGR_OFF_FLAGS = 132            # +0x84 bit3 = undo 总开关
UNDO_MGR_FLAG_ENABLED = 0x08

# 引擎自带的场景节点遍历入口（见 REVERSE_NOTES §2.11）：
#   EnumElements(world, CUtlVector<T*>*, const char* className, int flags, int recurse)
# 内部按「节点自身 +504 的子节点数、+512 的 4 字节元素句柄数组」递归，
# 再用句柄反查 CDmElement，最后按类名（vtable[936] 或 vtable[1864]）过滤。
RVA_MAP_ENUM_ELEMENTS = 0x745F10
RVA_CMAPENTITY_VTABLE = 0x161C548     # ??_7CMapEntity@@6B@，用于把场景节点筛成实体
CMAPDOC_WORLD_OFFSET = 136          # CMapDoc -> CMapWorld*
VEC_OFF_SIZE = 0x00                 # CUtlVector: {int size; int pad; T* mem; int alloc; int flags;}
VEC_OFF_MEM = 0x08
VEC_OFF_ALLOC = 0x10
VEC_OFF_FLAGS = 0x14


def _parse_addr(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(value, 0)


def _map_doc() -> int:
    """取当前文档表里的第一个 CMapDoc；没有打开地图时抛异常。"""
    base = _hammer_base()
    if _read_int(base + RVA_MAP_DOC_COUNT, "u32") == 0:
        raise RuntimeError("当前没有打开的地图文档")
    arr = _read_int(base + RVA_MAP_DOC_TABLE, "u64")
    return _read_int(arr, "u64")


def _alloc_mem(size: int) -> int:
    resp = _get_pipe().call("alloc_memory", {"size": size})
    if "error" in resp:
        raise RuntimeError(f"alloc_memory 失败: {resp['error']}")
    return int(resp["result"]["address"], 16)


def _free_mem(address: int) -> None:
    _get_pipe().call("free_memory", {"address": hex(address)})


def _write_mem(address: int, data: bytes) -> None:
    resp = _get_pipe().call("write_memory",
                            {"address": hex(address), "hex": data.hex()})
    if "error" in resp:
        raise RuntimeError(f"write_memory 失败 @{address:#x}: {resp['error']}")


def enum_elements(world: int, classname: str, flags: int = 0,
                  capacity: int = 4096) -> list[int]:
    """用引擎自己的遍历函数枚举 world 下所有 `classname` 类型的元素。

    做法：在目标进程分配一块暂存区，手工摆一个空的 CUtlVector
    （{size=0, mem=数组, alloc=capacity, flags=0}）交给引擎填充，再读回结果。
    引擎只在元素数超过 capacity 时才自己扩容（那时数组会被换成引擎的堆内存），
    所以把 capacity 开得足够大即可。
    """
    buf = _alloc_mem(capacity * 8 + 0x40)
    try:
        arr = buf + 0x40
        _write_mem(buf, struct.pack("<IIQII", 0, 0, arr, capacity, 0))
        # classname 为空 -> 传 NULL，引擎会枚举所有节点（不做类名过滤）
        name_arg = f"str:{classname}" if classname else 0
        resp = _get_pipe().call("call_function", {
            "address": _hammer_addr(RVA_MAP_ENUM_ELEMENTS),
            "args": [world, buf, name_arg, flags, 0],
            "on_main_thread": True,
            "timeout_ms": 15000,
        })
        if "error" in resp:
            raise RuntimeError(resp["error"])
        status = resp["result"].get("main_thread_status", 0)
        if status != 0:
            raise RuntimeError(f"主线程派发失败 (main_thread_status={status}): "
                               f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}")

        count = _read_int(buf + VEC_OFF_SIZE, "u32")
        mem = _read_int(buf + VEC_OFF_MEM, "u64")
        if count <= 0 or not mem:
            return []
        n = min(count, capacity)
        raw = _read_bytes(mem, n * 8)
        return [int.from_bytes(raw[i * 8:i * 8 + 8], "little") for i in range(n)]
    finally:
        _free_mem(buf)


@mcp.tool()
def cs2_entity_list(limit: int = 200) -> str:
    """列出当前地图的所有实体（类名 + 地址）。

    数据来源：CMapDoc+136 得到 CMapWorld，用引擎的 `hammer.dll+0x745F10`
    枚举 world 下所有场景节点，再按 vtable == `??_7CMapEntity@@6B@` 筛出实体，
    最后逐个读 `classname` 属性。

    ⚠️ 引擎自带的类名过滤参数其实是**驻留符号（CUtlSymbolLarge）**而不是字符串，
    传 C 字符串匹配不上，所以这里改成"全枚举 + 本地按 vtable 过滤"。

    Args:
        limit: 最多返回多少条（同时决定读取 classname 的条数）。
    """
    try:
        doc = _map_doc()
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
        if not world:
            return "CMapDoc 里没有 CMapWorld（地图可能还没加载完）"
        nodes = enum_elements(world, "", capacity=max(limit, 512))
        ent_vtable = _hammer_base() + RVA_CMAPENTITY_VTABLE
        ents = [n for n in nodes if _read_int(n, "u64") == ent_vtable]
        rows: list[tuple[int, str]] = []
        for ent in ents[:limit]:
            try:
                node = _call_entity_attr(RVA_ENTITY_GET_ATTR, ent, "classname")
                ptr = node["ret"]
                cls = _read_string(ptr, 128) if ptr else "?"
            except Exception:  # noqa: BLE001
                cls = "<读取失败>"
            rows.append((ent, cls))
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    head = (f"实体数: {len(ents)}（场景节点总数 {len(nodes)}，"
            f"CMapDoc={doc:#x}, CMapWorld={world:#x}）")
    if not ents:
        return head
    lines = [head, ""]
    for n, (ent, cls) in enumerate(rows):
        lines.append(f"[{n:3}] {ent:#018x}  {cls}")
    if len(ents) > limit:
        lines.append(f"... 还有 {len(ents) - limit} 个（用 limit 调整）")
    return "\n".join(lines)


def _call_entity_attr(rva: int, entity: int, name: str, default: int | None = None) -> dict:
    args: list[Any] = [entity, f"str:{name}"]
    if default is not None:
        args.append(default)
    resp = _get_pipe().call("call_function", {
        "address": _hammer_addr(rva),
        "args": args,
        "on_main_thread": True,
        "timeout_ms": 15000,
    })
    if "error" in resp:
        raise RuntimeError(resp["error"])
    result = resp["result"]
    status = result.get("main_thread_status", 0)
    if status != 0:
        raise RuntimeError(
            f"主线程派发失败 (main_thread_status={status}): "
            f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}")
    return result


@mcp.tool()
def cs2_entity_get_attr(entity: str, name: str) -> str:
    """读取实体的属性值（字符串）。

    Args:
        entity: 实体地址（cs2_entity_list 给出，如 '0x1234abcd'）。
        name: 属性名，如 'targetname' / 'origin' / 'model'。
    """
    try:
        ent = _parse_addr(entity)
        result = _call_entity_attr(RVA_ENTITY_GET_ATTR, ent, name)
        ptr = result["ret"]
        if ptr == 0:
            return f"属性 {name!r} 不存在于实体 {ent:#x}（返回空指针）"
        value = _read_string(ptr, 512)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    return f"{name} = {value!r}  (entity={ent:#x}, node={ptr:#x})"


@mcp.tool()
def cs2_entity_find_attr(entity: str, name: str) -> str:
    """返回实体属性的索引；属性不存在时返回 -1。

    实现：FindAttributeIdx(entity, name, -1)。
    """
    try:
        ent = _parse_addr(entity)
        result = _call_entity_attr(RVA_ENTITY_FIND_ATTR_IDX, ent, name, default=0xFFFFFFFF)
        idx = result["ret"]
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    shown = idx if idx < 0x80000000 else idx - 0x100000000
    return f"{name} -> idx={shown}  (entity={ent:#x})"


def _entity_attr_str(entity: int, name: str) -> str | None:
    """读实体属性的字符串值；属性不存在时返回 None。"""
    ptr = _call_entity_attr(RVA_ENTITY_GET_ATTR, entity, name)["ret"]
    return _read_string(ptr, 512) if ptr else None


def _entity_attr_node(entity: int, name: str) -> int:
    """取实体属性的 CDmAttribute* 指针（GetAttribute 的第三个 out 参数）。

    与 cs2_entity_get_attr 的区别：那个只要返回值（字符串），这里要属性对象本身，
    才能进一步写值。
    """
    buf = _alloc_mem(8)
    try:
        _write_mem(buf, b"\x00" * 8)
        _call_entity_attr(RVA_ENTITY_GET_ATTR, entity, name, default=buf)
        return _read_int(buf, "u64")
    finally:
        _free_mem(buf)


def _intern_string(value: str) -> int:
    """把字符串驻留成 CUtlSymbolLarge，返回「存放该符号的」内存地址。

    Datamodel 的字符串属性存的是驻留符号而不是普通 C 字符串，
    所以 SetValue 前必须先把新值 intern 一遍（Datamodel 接口 vtable[424/8]）。

    调用方用完须 _free_mem 返回的地址。
    """
    dm = _read_int(_hammer_base() + RVA_DATAMODEL, "u64")
    if not dm:
        raise RuntimeError(f"Datamodel 全局接口为空（hammer.dll+{RVA_DATAMODEL:#x}）")
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
        "args": [um],
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


@mcp.tool()
def cs2_entity_set_attr(entity: str, name: str, value: str) -> str:
    """设置实体的**字符串**属性值（如 targetname / model / target / classname）。

    实现链路（逆向依据见 REVERSE_NOTES.md §2.12）：
      1. GetAttribute(entity, name, &attr)      -> 拿到 CDmAttribute*
      2. Datamodel::InternString(value)          -> CUtlSymbolLarge
      3. CDmAttribute::SetValue<CUtlSymbolLarge>(attr, &sym)

    `SetValue` 内部会按需创建 `CUndoAttributeSetValueElement` 并 push 到撤销栈，
    因此修改后可尝试 `cs2_map_undo` 撤销。

    ⚠️ 只能改字符串属性；数值/向量类属性需要另一套模板实例（暂未实现）。

    Args:
        entity: 实体地址（cs2_entity_list 给出）。
        name: 属性名，如 'targetname'。
        value: 新的字符串值。
    """
    try:
        ent = _parse_addr(entity)
        attr = _entity_attr_node(ent, name)
        if not attr:
            return (f"属性 {name!r} 不存在于实体 {ent:#x}（GetAttribute 返回空指针），"
                    "无法设置")

        attr_type = _read_int(attr + ATTR_OFF_TYPE, "u32") & 0x3F
        if attr_type != DM_ATTR_TYPE_STRING:
            return (f"属性 {name!r} 类型是 {attr_type}（非字符串 {DM_ATTR_TYPE_STRING}），"
                    "本工具目前只支持字符串属性")

        before = _entity_attr_str(ent, name)

        # Hammer 平时把 Datamodel 的 undo 总开关关着，先确保打开，
        # 再包一层 undo scope，SetValue 才会把本次修改记进撤销栈。
        undo_was_off = _ensure_undo_enabled()
        _undo_scope_begin(f"cs2 set {name}")
        try:
            sym_buf = _intern_string(value)
            try:
                resp = _get_pipe().call("call_function", {
                    "address": _hammer_addr(RVA_ATTR_SET_SYMBOL),
                    "args": [attr, sym_buf],
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
                _free_mem(sym_buf)
        finally:
            scope_committed = _undo_scope_end()

        after = _entity_attr_str(ent, name)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    ok = "已生效" if after == value else "读回值不一致（可能类型不匹配或写入被忽略）"
    if scope_committed:
        undo_note = ("  undo: 已记入 Datamodel 撤销栈（用 cs2_undo 撤销；"
                     "Hammer 的 Ctrl+Z 走的是地图历史，两套独立）")
        if undo_was_off:
            undo_note += "\n        （本次顺带打开了 Datamodel 的 undo 总开关）"
    else:
        undo_note = "  undo: scope 内没有操作被提交（值未变化时属正常）"
    return (
        f"设置 {name} = {value!r}  [{ok}]\n"
        f"  entity = {ent:#x}\n"
        f"  attr   = {attr:#x}  (类型 {attr_type}=STRING)\n"
        f"  读回   : {before!r} -> {after!r}\n"
        f"{undo_note}\n"
        f"  SetValue ret = {ret}"
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="CS2 Tool MCP Server")
    parser.add_argument("--pipe", default=DEFAULT_PIPE, help=f"命名管道名 (默认: {DEFAULT_PIPE})")
    parser.add_argument("--stdio", action="store_true", help="以 stdio 传输方式运行 MCP 客户端")
    args = parser.parse_args()

    global _pipe
    _pipe = Cs2Pipe(args.pipe)

    print(f"[cs2_tool_mcp] pipe={args.pipe}", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
