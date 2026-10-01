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
import ctypes
import json
import math
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
KERNEL32 = None


def _kernel32():
    """kernel32 绑定（**进程内缓存**）。

    原先每次 Win32 调用都重建一遍 `ctypes.WinDLL(...)` 并重设 argtypes ——
    那点构造开销比读写本身还大；缓存后单次 IPC 往返明显变快。
    """
    global KERNEL32
    if KERNEL32 is None:
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
        KERNEL32 = k32
    return KERNEL32


class Cs2Pipe:
    """与注入 DLL 中 IpcPipeServer 对应的命名管道客户端。"""

    def __init__(self, pipe_name: str = DEFAULT_PIPE, timeout_ms: int = DEFAULT_PIPE_TIMEOUT):
        self.pipe_name = pipe_name
        self.timeout_ms = timeout_ms
        self._handle: int | None = None

    # -- Win32 原语 ----------------------------------------------------

    def _open(self) -> None:
        k32 = _kernel32()
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
        _invalidate_address_cache()   # 新连接：对端可能换过进程，基址缓存作废

    def _close(self) -> None:
        if self._handle is not None:
            _kernel32().CloseHandle(self._handle)
            self._handle = None

    def _write_all(self, data: bytes) -> None:
        k32 = _kernel32()
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
        k32 = _kernel32()
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
        """发送 {id, method, params}，返回解析后的响应对应 dict。

        **长连接**：DLL 侧 `ClientThread` 是「ReadRequest → HandleRequest →
        SendResponse」循环，一个连接可服务多次调用，所以这里复用已打开的管道句柄
        （原先每次调用都 CreateFileW + CloseHandle，光系统调用开销就占了单次往返
        的大半）。读写失败时关掉句柄、重连后重试一次。
        """
        req: dict[str, Any] = {
            "id": int(time.time() * 1000) & 0x7FFFFFFF,
            "method": method,
        }
        if params is not None:
            req["params"] = params
        payload = json.dumps(req).encode("utf-8")
        frame = struct.pack("<IIII", MSG_MAGIC, MSG_VERSION, len(payload), 0) + payload

        last: Exception | None = None
        for _ in range(2):
            if self._handle is None:
                self._open()
            try:
                self._write_all(frame)
                magic, _version, length, _reserved = struct.unpack(
                    "<IIII", self._read_exact(HEADER_SIZE))
                if magic != MSG_MAGIC:
                    raise IOError(f"Bad response magic: 0x{magic:x}")
                body = self._read_exact(length) if length else b""
                return json.loads(body.decode("utf-8", errors="replace"))
            except (IOError, OSError) as e:  # noqa: PERF203
                last = e
                self._close()   # 断线：下次循环重连
        raise last if last else IOError("call failed")

    def close(self) -> None:
        self._close()


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
# 撤销 / 重做（2026-09 新版 hammer.dll 重新定位，见 REVERSE_NOTES.md §3）
# ---------------------------------------------------------------------------
# g_CDataModel 是静态内嵌对象（2026-10-01 新版在 hammer.dll+0x24B7AC0）；
# hammer.dll+0x21B2958 (off_1821B2958) 处的 qword 也指向同一对象。
RVA_CDATAMODEL_GLOBAL = 0x24B7AC0   # CDataModel 全局单例（静态初始化 sub_18004F890）
RVA_CDATAMODEL_PTR_GLOBAL = 0x21B2958  # qword 指针，值 = base+0x24B7AC0
RVA_CDATAMODEL_VTABLE = 0x16C25C8   # 用于运行前校验
UNDO_MANAGER_OFFSET = 240           # CUndoManager 内嵌在 CDataModel + 240（不变）
RVA_CDATAMODEL_UNDO = 0x5C34A0      # 带 UI 通知(vfn+1040)的包装
RVA_CDATAMODEL_REDO = 0x5C1520
RVA_UNDO_MANAGER_UNDO = 0x60FC10    # CUndoManager::Undo 本体（带 profile）
RVA_UNDO_MANAGER_REDO = 0x60F780    # CUndoManager::Redo 本体
# 新布局：undo 计数 @+0 / 栈 @+8；redo 计数 @+16 / 栈 @+24（Redo 反编译实测）
UNDO_MGR_OFF_UNDO_COUNT = 0
UNDO_MGR_OFF_REDO_COUNT = 16


_HAMMER_BASE: int | None = None


def _hammer_base() -> int:
    """hammer.dll 的基址（= PE ImageBase），**进程内缓存**。

    实测 DLL 的 `get_module` 单次约 **40ms**（模块枚举很贵），而 entity_list 这类
    批量操作会调它上百次 —— 缓存后 7.5s 直接降到 1 次调用。
    管道重连（Hammer 重启 / 重新注入）时由 `_invalidate_address_cache()` 丢弃。

    可用环境变量 `CS2_HAMMER_BASE` 覆盖（十六进制或十进制）。用途：注入 DLL 的模块
    列表若因故看不到 hammer.dll（例如模块枚举缓存陈旧），可临时用外部工具（CE）
    取到基址后走绝对地址，不必重启目标进程。
    """
    global _HAMMER_BASE
    override = os.environ.get("CS2_HAMMER_BASE")
    if override:
        return int(override, 0)
    if _HAMMER_BASE is None:
        resp = _get_pipe().call("get_module", {"name": "hammer"})
        if "error" in resp:
            raise RuntimeError(resp["error"])
        _HAMMER_BASE = int(resp["result"]["base_hex"], 16)
    return _HAMMER_BASE


def _invalidate_address_cache() -> None:
    """丢弃缓存的模块基址。任何一次「新建立的管道连接」都调它 —— 重连意味着
    对端可能换过进程（Hammer 重启/重注入），基址要重新取。"""
    global _HAMMER_BASE
    _HAMMER_BASE = None


def _hammer_addr(rva: int) -> str:
    """把 hammer.dll 的 RVA 表达成 DLL 能解析的地址表达式。

    有 `CS2_HAMMER_BASE` 覆盖时直接用绝对地址（绕开 DLL 的模块查找）。
    """
    override = os.environ.get("CS2_HAMMER_BASE")
    if override:
        return hex(int(override, 0) + rva)
    return f"hammer.dll+{rva:#x}"


_UINT_WIDTH = {"u8": 1, "u16": 2, "u32": 4, "u64": 8}


def _read_int(address: int, type_: str) -> int:
    """读整数。**无符号类型强制按位宽还原** —— DLL 的 `read_value` 返回的是有符号
    JSON 整数，最高位为 1 的值（高地址指针、referenceID 这类 64 位 ID）会变成负数，
    直接 `hex()` 出来就是 `0x-...`。"""
    resp = _get_pipe().call("read_value", {"address": address, "type": type_})
    if "error" in resp:
        raise RuntimeError(resp["error"])
    val = resp["result"]["value"]
    width = _UINT_WIDTH.get(type_)
    if width:
        val &= (1 << (width * 8)) - 1
    return val


def _call_addr(address: int | str, args: list, timeout: int = 15000) -> tuple[str, str]:
    """在 Hammer 主线程上调**绝对地址**处的函数 -> (ret_hex, 错误串)。

    错误串为空表示调用成功。所有「会碰文档/UI 状态」的函数都必须走这条路。
    ⚠ 虚拟调用请自己解析虚表槽再走这里 —— DLL 的 `call_virtual` 实测会把
    `ret` 填成「已解析的函数地址」而不是函数返回值（看起来并没有真正带参调用）。
    """
    resp = _get_pipe().call("call_function", {
        "address": address if isinstance(address, str) else hex(address),
        "args": args,
        "on_main_thread": True,
        "timeout_ms": timeout,
    })
    if "error" in resp:
        return "", f"管道错误 {resp['error']}"
    result = resp["result"]
    status = result.get("main_thread_status", 0)
    if status != 0:
        return "", (f"主线程派发失败 (status={status}): "
                    f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}")
    return result["ret_hex"], ""


def _call_fn(rva: int, args: list, timeout: int = 15000) -> tuple[str, str]:
    """在 Hammer 主线程上调 hammer.dll 里 RVA 处的函数（见 `_call_addr`）。"""
    return _call_addr(_hammer_addr(rva), args, timeout)


def _call_vfn(this_ptr: int, vtable_offset: int, args: list,
              timeout: int = 15000) -> tuple[str, str]:
    """调虚函数：**自己解析虚表槽**后用 `_call_addr` 调用 -> (ret_hex, 错误串)。

    ⚠ 不要用管道自带的 `call_virtual`：`injected_dll/ipc_pipe.cpp` 里它的参数解析
    只把字符串当「模块地址」`ResolveAddress`，`"str:xxx"` 会被**静默丢弃**，
    于是参数整体左移、被调函数收到空指针。实测后果：`vfn2144(SetClassName)` 收到
    `classname == 0` → 判定空类名直接 return，长期被误判成「这条虚函数无效」。
    (`_resolve_handle` 用的是纯整数参数，所以它一直没受影响。)
    """
    vtable = _read_int(this_ptr, "u64")
    fn = _read_int(vtable + vtable_offset, "u64")
    if not fn:
        return "", f"虚表槽 {vtable_offset:#x} 为空（this={this_ptr:#x}）"
    return _call_addr(fn, [this_ptr, *args], timeout)


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


@mcp.tool()
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


@mcp.tool()
def cs2_redo(use_wrapper: bool = True) -> str:
    """重做 Datamodel(DMX) 的操作。⚠️ 同样不影响地图编辑历史，详见 cs2_undo。"""
    return _undo_redo("redo", use_wrapper)


# ---------------------------------------------------------------------------
# 地图 / Hammer（2026-09 新版对象链，见 REVERSE_NOTES.md §3）
#   CHammerApp(ToolSystem2_001)
#     +0x58/+0x60           CHammerEditorSession* 的 CUtlVector {count, mem}
#     session+0x138         活动 CMapDocSession*
#     wrapper+0x10          内嵌 CMapDoc（不是再解引用！）
#     doc+0x80              CMapRootElement*
#     doc+0x88              CMapWorld*
#     root+0x240/+0x248     两个 CMapDocHistory（undo / redo）
# 旧全局文档表 0x2355020/0x2355028 已失效；枚举逻辑在 DLL 侧 ListMapDocs()。
# ---------------------------------------------------------------------------
APP_OFF_SESSION_VEC_COUNT = 0x58
APP_OFF_SESSION_VEC_MEM = 0x60
SESSION_OFF_ACTIVE_WRAPPER = 0x138
WRAPPER_DOC_EMBED_OFFSET = 0x10
CMAPDOC_ROOT_OFFSET = 0x80           # CMapDoc -> CMapRootElement*
RVA_CMAPROOT_VTABLE = 0x1763FA8
RVA_MAP_HISTORY_VTABLE = 0x1763E00   # CMapDocHistory vtable
ROOT_OFF_UNDO_HISTORY = 0x240
ROOT_OFF_REDO_HISTORY = 0x248
# 新版 CMapDocHistory 栈布局（运行时实测，与旧版一致）：
#   +0x08 int 条目数 / +0x10 IUndoable** 数组 / +0x18 int 容量
#   +0x80 ptr 配对历史（撤销<->重做互指）/ +0x8C int 忙标志 / +0x90 byte 启用标志
HISTORY_OFF_COUNT = 0x08
HISTORY_OFF_ARRAY = 0x10
HISTORY_OFF_PAIR = 0x80
# 「弹出并应用」= CMapDocHistory::Pop（旧版 0x14080D0，2026-09-27 重新定位）。
# 反编译与旧版逐行一致（见 REVERSE_NOTES §15）：
#   if (g_gate && !this->busy && this->enabled && this->vfn3_CanUndo())
#       { last = top; push_to_pair(last); --count; this->busy = 1;
#         逐条应用反操作(sub_181529D20); this->busy = 0; free(last); }
# 撤销/重做共用本函数，靠传入的 history 指针区分（撤销=root+0x240，重做=root+0x248）。
# ⚠ 内部有 CanUndo 守卫，空栈时整段跳过（不会像 Datamodel undo 那样破坏状态）。
RVA_MAP_HISTORY_POP = 0x152A490
# Pop 最外层那个全局开关（旧版 byte_1820F2088，新版 byte_18221A418）
RVA_MAP_HISTORY_GATE = 0x221A418

# --- CMapDocHistory 的「记录型」写入接口（2026-09-27 定位，见 REVERSE_NOTES.md §15.10）---
# 栈里每一项是一个 192B「步」对象（名字在 +0x24），步里挂若干个 80B「命令包装」；
# 包装的 kind 就是动作类型：0=通用命令 / 1=对象被移除 / 2=对象被新增。
# ⚠ 传的对象必须是 **元素 + 0xC8**（CMapNode 接口子对象），不是元素本身。
RVA_MAP_HISTORY_PUSH_STEP = 0x15298A0   # sub_181529290(hist, name, 0, 0) 压入具名步（并清空重做栈）
RVA_MAP_HISTORY_REC_ADDED = 0x15296C0   # sub_1815290B0(hist, node) 记录「对象被新增」(kind=2)
RVA_MAP_HISTORY_REC_REMOVED = 0x15294D0  # sub_181528EC0(hist, node) 记录「对象被移除」(kind=1)
RVA_MAP_HISTORY_NOTIFY = 0x1529D10      # sub_181529700(hist, 2) 通知监听者（刷新 Undo 菜单/工具态）
# 把「被修改的节点（含子/父链）」登记进当前撤销步 —— Hammer 改属性/变换前就是这么干的。
# 见 REVERSE_NOTES §17.14：sub_18086D9B0(hist, node, 1)
RVA_HIST_RECORD_NODE = 0x86DCF0
NODE_IFACE_OFFSET = 0xC8                # CDmElement -> 内嵌的 CMapNode 接口子对象

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
    """枚举当前所有打开的 CMapDoc 文档，返回地址与地图名。

    新版（2026-09）链路：CHammerApp+0x58/+0x60 的 CHammerEditorSession* 数组
    → session+0x138 活动 CMapDocSession → CMapDoc 内嵌于 wrapper+0x10。
    """
    return _call("map_list_docs")


@mcp.tool()
def cs2_get_hammer_app() -> str:
    """获取 CHammerApp / ToolSystem2_001 顶层应用对象指针
    （IDA: ToolSystem2_001 工厂 sub_180115270 返回 CHammerApp）。"""
    return _call("get_hammer_app")


MAX_READ_CHUNK = 8192  # DLL 侧 read_memory 单次上限（injected_dll/ipc_pipe.cpp kMaxReadSize）


def _read_bytes(address: int, size: int) -> bytes:
    """分块读取（DLL 的 read_memory 单次上限见 MAX_READ_CHUNK）。"""
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


# ---------------------------------------------------------------------------
# 往 Hammer 的 Ctrl+Z 历史里写记录（REVERSE_NOTES.md §15.10）
# ---------------------------------------------------------------------------
# 为什么需要它：我们的工具走的是底层调用，只会进 DMX 的 CUndoManager（属性级），
# 而 Hammer 的 Ctrl+Z 读的是 **CMapDocHistory**（root+0x240）—— 实测两者互不相通
# （一次 create+delete 后 CMapDocHistory 计数 27→27 完全不动）。所以必须显式记录。
#
# ⚠ 三条硬约束（都是实测得出）：
#   1) 传的对象是 **元素 + 0xC8**（CMapNode 接口子对象），不是元素本身；
#   2) 记录是**追加到栈顶步**的 —— 所以要先压步，否则会自动建一个**无名**步；
#   3) 记「移除」**必须在摘除之前** —— 记录函数会读 `node->vfn64()`（= 父节点）存起来
#      供撤销挂回用，而摘除后它立刻变成 0。
#
# 撤销/重做无需我们实现：Pop 应用 kind1/kind2 时会自动往配对栈写反向记录（§15.10.4）。


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


@mcp.tool()
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


@mcp.tool()
def cs2_map_redo(doc: str = "") -> str:
    """重做**地图编辑**的下一步操作（真正的 Hammer 重做）。详见 cs2_map_undo。"""
    return _map_undo_redo("redo", doc)


MAP_DOC_PATH_OFFSET = 0x6A0   # CMapDoc -> 地图全路径（CUtlString，+0 即 char*）


@mcp.tool()
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


@mcp.tool()
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


def _file_stat(path: str) -> tuple[int, str] | None:
    """(字节数, mtime 文本)；路径为空或文件不可访问时返回 None。"""
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))


# 底层保存（per-document）：sub_1801639B0(doc, a2, a3, a4, a5, a6)
#   a2 = CommandLine 的某个开关（实测传 0 正常）
#   a3 = 0 → 非「按脏检查」模式；a4 = 1 → 强制保存（跳过脏判定）
#   a5/a6 = 可选的「未落盘文件」输出 CUtlVector，函数内部判空，传 0 即可
# ⚠️ 不要改调外层 sub_1801363C0：它在 a3==0 时还会顺带保存「编辑会话布局」
#     （sub_180147DD0 → assetsystem/tier0），实测会把 Hammer 主线程永久卡死。
#     详见 REVERSE_NOTES.md §12。
RVA_HAMMER_SAVE_DOC = 0x1639B0


@mcp.tool()
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


# ---------------------------------------------------------------------------
# 实体：纯内存树遍历 + CDmElement 属性链（2026-09 新版，见 REVERSE_NOTES.md §3）
# ---------------------------------------------------------------------------
RVA_CMAPENTITY_VTABLE = 0x1758D00   # ??_7CMapEntity@@6B@（运行时实测）
RVA_CMAPWORLD_VTABLE = 0x1772920    # CMapWorld
# CMapGroup：分组（组成员在 `children` 属性里，元素句柄表）。RVA 由 ze_surf_easy
# 元素表类型分布反查（IDA 按 RVA 取符号名，完整 RVA→类名对照见 REVERSE_NOTES §15.7.1）
RVA_CMAPGROUP_VTABLE = 0x178B4A8
CMAPDOC_WORLD_OFFSET = 0x88         # CMapDoc -> CMapWorld*（136，旧版同偏移）

# --- 工具系统「可绑定命令」注册表（Hammer Options → Key Bindings 那张表），见 REVERSE_NOTES §17 ---
# 每个工具类在静态初始化时把一个 CBaseBindTargetDescriptor 头插进这条全局链表。
RVA_BIND_TARGET_LIST = 0x272D6D8    # 链表头（qword_18272D898）
BIND_VFN_NAME = 0                   # vtable[0]  = 取工具名 (char*)
BIND_VFN_CMD_COUNT = 24             # vtable[24] = 命令数 (int)
BIND_VFN_CMD_AT = 32                # vtable[32] = 取第 i 个命令 (命令对象*)
BIND_OFF_CLASS = 0x18               # 类名 char*（KV 里的 "ClassName"）
BIND_OFF_FILE = 0x20                # 注册处源文件（CBufferString）
BIND_OFF_LINE = 0x28                # 注册处行号 (u32)
BIND_OFF_NEXT = 0x38                # next
BIND_CMD_OFF_NAME = 0x08            # 命令对象：命令名 char*
BIND_CMD_OFF_DESC = 0x18            # 命令对象：描述 char*

# CMapNode/CMapWorld/CMapEntity 共用子树布局（与旧版完全一致）：
#   +0x1F8 int 子节点数；+0x200 int32 句柄数组指针（每项 4 字节 handle）
NODE_OFF_CHILD_COUNT = 0x1F8
NODE_OFF_CHILD_HANDLES = 0x200

# CDmElement / CDmAttribute（新版实测）
ELEMENT_OFF_ATTR_HEAD = 0x48        # CDmAttribute 侵入式链表头（沿 attr+0 串起）
ATTR_OFF_NEXT = 0x00                # 40 字节一个属性
ATTR_OFF_VALUE = 0x08               # 值存储指针
ATTR_OFF_OWNER = 0x10               # 所属 element 回指
ATTR_OFF_TYPE = 0x1C                # 低 6 位为类型（字符串 type=5 时此字节=0x5）
ATTR_OFF_NAME = 0x20                # CUtlSymbolLarge 即裸 char*
DM_ATTR_TYPE_STRING = 5             # AT_STRING
DM_ATTR_TYPE_BOOL = 4               # AT_BOOL —— **值存储只占 1 字节**
DM_ATTR_TYPE_ID = 15                # referenceID 之类的 8 字节对象 ID
DM_ATTR_TYPE_ARRAY_UNK = 34         # CUtlVector 数组，但元素类型尚未确定
# 类型码 -> 名字（`attr+0x1C` 低 6 位）。证据见 REVERSE_NOTES.md §14.2 / §15.8：
# 5/8/10 由对应 setter 的 CUndoAttributeSetValueElement<T> 实例反查，
# 1/2/3/7 由 sub_1805CE490（int 写入器）的接受分支反查，33/37 由活体属性枚举，
# 4/15/34 由 ze_surf_easy 实测值存储字节数反查。
DM_ATTR_TYPE_NAMES = {
    DM_ATTR_TYPE_STRING: "string",
    1: "element_handle",
    2: "int", 3: "int", 7: "int",
    DM_ATTR_TYPE_BOOL: "bool",
    8: "color",
    10: "vec3",
    DM_ATTR_TYPE_ID: "id",
    33: "element_array",
    DM_ATTR_TYPE_ARRAY_UNK: "array",
    37: "string_array",
}
# CDmElement::MarkDirty(this, flags)（sub_1805C81C0）：把标志或进 element+0x5E/+0x60
# 并递归通知依赖者。摘掉属性后用它传播脏状态。
RVA_ELEMENT_MARK_DIRTY = 0x5C8500

# 句柄 -> 元素：CDataModel vtable slot21（字节偏移 168），args=[handle]，
# 必须在主线程调用。
DATAMODEL_VFN_RESOLVE_HANDLE = 168

# 实体的 classname 不直接挂在实体上：实体属性链里有 entity_properties 属性，
# 其值存储处放的是元素句柄，经 datamodel 解析得到 CEditGameClassProps，
# classname / targetname / vscripts 等在它自己的属性链上。
ENTITY_PROPS_ATTR_NAME = "entity_properties"
ENTITY_TARGETNAME_ATTR = "name"      # 实体自身链上的 'name' 属性即 targetname

# --- 属性写入（Datamodel 层，2026-09 新版已重新定位，见 REVERSE_NOTES.md §4）---
RVA_DATAMODEL = RVA_CDATAMODEL_GLOBAL
# CDataModel vtable slot（字节偏移 424）= 字符串 intern，签名 (dm, outToken*, const char*)。
# 由 sub_18062C9A0 / sub_18062C880 的调用序列实测确认。
VFN_OFF_INTERN_STRING = 424
# CDmAttribute 值写入：sub_1805CF020(attr, const CUtlStringToken*)（旧 0x4C7A10 已失效）
RVA_ATTR_SET_SYMBOL = 0x5CF360
# 更高层、更安全的按名写字符串属性：
#   sub_18062C9A0(ownerElement, const char* name, const char* value, bool createIfMissing)
# 内部自行 intern，并在属性缺失时以类型 5(AT_STRING) 创建。Drop/快照等内置逻辑均走它。
RVA_PROPS_SET_STRING_ATTR = 0x62CCE0
# 按名取属性（返回 CDmAttribute*），签名 (ownerElement, const char* name)
RVA_PROPS_FIND_ATTR = 0x5C74B0
# 按名写**实体 keyvalue**（推荐入口，比上面那个更高层）：
#   sub_18083E0D0(entity, const char* name, const char* value)
# 属性缺失时以类型 5(AT_STRING) 创建；值变化后还会调 CMapEntity 的类回调
# (vfn+2136)、targetname 名字索引(vfn+1272/2160) 与包围盒/脏通知
# (sub_1808672E0/sub_180867040)。⚠ origin/angles/scales 不走这里（见下）。
RVA_ENTITY_SET_KEYVALUE = 0x83E410
# 按名写**实体属性表属性**（含变换），签名 (entity, const char* name, const char* value, uint flags)：
#   sub_18086B550 取实体的 CMapNode 属性表，按属性声明类型分派 —— 变换类属性由
#   CMapNodeTransformPin 直接落到 CMapEntity 的原生 Vec3D 成员（+0xA0/+0xAC/+0xB8），
#   普通 keyvalue 仍写 CEditGameClassProps。属性不存在时返回 0（不创建）。
RVA_ENTITY_SET_NODE_ATTR = 0x86B890
# sub_18083E0D0 内部用的「实体 -> entity_properties 句柄」下标：entity + 1336
ENTITY_OFF_PROPS_HANDLE = 1336

# --- 实体/粒子（2026-09 新版重新定位）---
# CMapEntity 主 vtable 字节偏移 2144 = 设置类名：
#   vfn2144(entity, const char* classname, bool updateDependents, bool force)
# （拖放建实体的处理器 sub_180180190 就是这么调的，实测 0x180896390）
ENTITY_VFN_SET_CLASSNAME = 2144
# --- 官方「放置 / 改类」序列（拖放处理器 sub_180180190 = mapviewdroptarget.cpp，见 REVERSE_NOTES §15）---
# 官方放一个实体就是这么走的（prop_static / info_particle_system 两个分支完全同构）：
#   node = 工厂 Create(...)
#   node->vfn2144(classname, 0, 0)        ← SetClassName（这条其实有效，前提是节点状态正确）
#   sub_18083E0D0(node, "<其它kv>", ...)  ← 写 model / effect_name 等
#   sub_180866D70(node, 0)                ← 建好后置节点状态（紧跟 SetClassName）
#   sub_180879170(doc, node, 0)           ← ★ AddChild：这一步才真正挂进世界
# ⚠ 第一参数是 **CMapDoc**（不是 CMapWorld）：函数内默认锚点 = `*(doc+0x88)` 正好就是
#   CMapWorld 字段；传 world 会让它把 `*(world+0x88)` 当锚点 → 拿错对象。
RVA_NODE_POST_CLASS = 0x8670B0     # sub_180866D70(node, flag)
RVA_NODE_ADD_CHILD = 0x8794B0      # sub_180879170(doc, child, siblingOr0)
RVA_NODE_GET_PARENT = 0x8651E0     # sub_180864EA0(node) -> 父节点（实测：func_brush 的父就是 CMapWorld）
RVA_NODE_GET_ROOT = 0x8651F0       # sub_180864EB0(node) -> 根/世界（实测全部实体都指向 CMapWorld）
# ★ AddChild 的对偶：父节点**虚表字节偏移 0x1D0** 的虚函数 = 移除子节点。
#   CMapWorld  +0x1D0 -> sub_180925C60（第三参数透传给 sub_18084F400）
#   CMapEntity +0x1D0 -> sub_18084F400（直接；notify 非 0 时多做 doc 侧簿记）
#   CMapGroup  等 6 个类 -> sub_1809EB760，**强制 notify=1**，故删除默认也传 1
NODE_VFN_REMOVE_CHILD = 0x1D0
# CParticleHelper::SetDefinitionByName(this, const char* vpcfPath)
RVA_PARTICLE_SET_DEFINITION = 0x7F5690
# CParticleHelper 主 vtable RVA —— 用于在堆/实体内存里识别 helper 对象
RVA_CPARTICLE_HELPER_VTABLE = 0x17500B8
CMAPENTITY_SIZE = 6232              # CMapEntity 对象大小（工厂 sub_180898D10 分配）
OFF_HELPER_ENTITY_HANDLE = 152      # helper+0x98 = 所属实体句柄(u32)
OFF_HELPER_EFFECT_NAME = 176        # helper+0xB0 = effect_name (CUtlString)
OFF_HELPER_DEFINITION = 184          # helper+0xB8 = 解析出的粒子定义指针

# --- CMapEntity 原生变换成员（2026-09-26 CE 对比实测 ✅）---
# 坐标不在 DMX 元素属性里（CMapEntity 元素只有 name/children/connectionsData/... ，
# origin/angles/scales 是 GetAttributeTable_CMapNode 的属性，运行时没有 CMapNode 元素），
# 而是 CMapEntity 对象的原生 Vec3D 成员。用「工具放置的实体 vs 新建实体」对比确认：
#   放置的 3 个实体 origin 分别为 (-448,-448,0) / (-1152,-128,0) / (-576,-320,0)  ← 全部网格对齐
#   新建（未定位）实体 origin 为 (0,0,0)
# 且 sub_1808327B0 里 `*(float*)(entity+172/176/180)` 与 0 比较来处理 "angles" 键值，
# 172=0xAC 正好落在 angles 上 → 三个成员依次相邻可互证。
ENTITY_OFF_ORIGIN = 0xA0             # Vec3D 世界坐标
ENTITY_OFF_ANGLES = 0xAC             # Vec3D 欧拉角（度）
ENTITY_OFF_SCALES = 0xB8             # Vec3D 缩放（新建时为 1,1,1）
# 这三个名字在实体属性表里是「变换 pin」而不是 keyvalue：写它们必须走
# RVA_ENTITY_SET_NODE_ATTR（实测直接写原生成员并立即生效），
# 若误用 keyvalue 写入器会在 CEditGameClassProps 上凭空造一个同名 AT_STRING。
TRANSFORM_ATTR_OFFSETS = {
    "origin": ENTITY_OFF_ORIGIN,
    "angles": ENTITY_OFF_ANGLES,
    "scales": ENTITY_OFF_SCALES,
}

# --- DMX「数组」属性值存储布局（实测 world.children）---
# 值存储 vp：{ u32 m_nSize @+0 ; u32 _unused @+4 ; u64 m_pMemory @+8 ; u32 m_nAllocation @+0x10 }
# 元素句柄数组（AT 33）元素是 u32（CDmElementHandle_t）；
# 基础类型数组（AT 37 字符串 / 数值数组）同构，元素大小按类型算。
ARR_OFF_SIZE = 0x00
ARR_OFF_DATA = 0x08
ARR_OFF_ALLOC = 0x10

# --- 实体 IO：原生连接数组（2026-09-26 反编译 + 活体实测 ✅ 见 REVERSE_NOTES §11.13）---
# ⚠ 关键结论：Hammer **编辑期**把 IO 连接放在 CMapEntity 对象自己的原生
#   `CUtlVector<Conn>` 里（entity+0x4A0），**不在 DMX 属性上**。
#   DMX 的 `connectionsData`（元素句柄数组 -> DmeConnectionData）只是**保存时生成的
#   临时镜像**：写完 .vmap 后计数会被清零，只留下容量和一个陈旧句柄 —— 这正是此前
#   「connectionsData 读到 0 条」的原因。
# 证据链：
#   * sub_180986EA0(entity, outHandle, const Conn*) 把一条 Conn 追加进 entity+0x4A0
#     （Outputs 面板粘贴链路 sub_18020D240 调用它）
#   * sub_180214420 释放整个向量，逐条 FreeMemoryBlock 5 个 CUtlString + paramMap
#   * 活体 trigger_multiple 0x26426690C00 的 +0x4A0 读出的第 0 条与用户粘贴的 KV3 完全一致
#   * 保存出的 untitled_2.vmap（二进制 DMX）里确实有 DmeConnectionData 的字符串块
ENTITY_OFF_CONN_COUNT = 0x4A0   # CUtlVector<Conn> m_nSize
ENTITY_OFF_CONN_DATA = 0x4A8    # Conn* m_pMemory
ENTITY_OFF_CONN_ALLOC = 0x4B0   # m_nAllocation
CONN_STRIDE = 0x50              # sizeof(Conn) = 80
CONN_OFF_SOURCE = 0x00          # CUtlString sourceEntity（触发者名字，通常空）
CONN_OFF_OUTPUT = 0x08          # CUtlString output（输出名，如 OnStartTouch）
CONN_OFF_TARGET = 0x10          # CUtlString targetEntity（如 !self）
CONN_OFF_INPUT = 0x18           # CUtlString input（如 Kill）
CONN_OFF_PARAM = 0x20           # CUtlString param（覆盖参数）
CONN_OFF_TYPE = 0x28            # int ioTargetType（新建默认 7）
CONN_OFF_PARAMMAP = 0x30        # KV3 值 m_paramMap（16 字节，Hammer 用 sub_1813E79E0 初始化）
CONN_OFF_DELAY = 0x40           # float delay
CONN_OFF_TIMES = 0x44           # int timesToFire（-1 = 无限）
CONN_OFF_RELAY = 0x48           # bool relayConnection
CONN_OFF_GLOBAL = 0x49          # bool fromGlobalRelay
CONN_OFF_UNIQUE = 0x4C          # int 唯一 id（Hammer 分配，仅 UI 用）
# ioTargetType 枚举（hammer.dll 内的枚举描述表 0x1816CF740 实测）
IO_TARGET_TYPE_NAMES = {
    -1: "ENTITY_IO_TARGET_INVALID",
    2: "ENTITY_IO_TARGET_ENTITYNAME",
    6: "ENTITY_IO_TARGET_EHANDLE",
    7: "ENTITY_IO_TARGET_ENTITYNAME_OR_CLASSNAME",
}
# 追加一条连接到实体的原生向量：sub_180986EA0(entity, int outHandle[4], const Conn* src)
RVA_ENTITY_ADD_CONN = 0x9871E0
# 删除按下标的连接：sub_180987AF0(entity, index<<16) -> char（1=成功/0=下标非法）。
# Outputs 面板「Delete Output」(sub_18020CD40) 用的就是它：析构 Conn（paramMap +
# 5 个 CUtlString 全部正确释放）→ 尾块前移 80B → 计数减一。
# ⚠ 索引是**打包在高 16 位**的 int16（低字必须为 0），故仅支持 index < 32768。
RVA_ENTITY_REMOVE_CONN = 0x987E30
# KV3 值初始化：sub_1813E79E0(this, 1, 8)（Hammer 的 Conn::Conn 内部同款调用）
RVA_CONN_VALUE_INIT = 0x13E7FF0

# --- 实体 IO（DMX 侧，仅存档镜像参考；对照 VRF ValveMap.cs）---
ENTITY_ATTR_CONNECTIONS = "connectionsData"   # 元素句柄数组 -> DmeConnectionData
ENTITY_ATTR_RELAY_PLUGS = "relayPlugData"     # -> DmePlugList
# DmeConnectionData 的字段（CamelCaseProperties）
IO_CONN_FIELDS = ("outputName", "targetType", "targetName", "inputName",
                  "overrideParam", "delay", "timesToFire")
# DmePlugList 的字段
IO_PLUG_FIELDS = ("names", "dataTypes", "plugTypes", "descriptions")

# --- mesh（对照 VRF ValveMap.cs / HammerMeshBuilder.cs）---
# CMapMesh（主虚表 RTTI ??_R4CMapMesh@@6B@）/ CDmePolygonMesh
RVA_CMAPMESH_VTABLE = 0x176B8E0
RVA_CDMEPOLYGONMESH_VTABLE = 0x1D70700
# mesh 顶点坐标写入：sub_1809B8880(element, CUtlVector<顶点handle>*, CUtlVector<Vector>*)
#   内部 = 取元素变换(vfn+160 → 48B 矩阵) → sub_180BFA650 转成存储空间 → sub_180CDC6E0
#   sub_180CDC6E0(poly, handles, transform, positions) 是 CPolygonMesh 的官方算子
#   "SetVertexPositions"（开事务/写位置通道/更新缓存/发脏通知），见 REVERSE_NOTES §13.10
RVA_MESH_SET_VERTEX_POSITIONS = 0x9B8BC0
# CPolygonMesh 本体的算子（元素级包装就是调它）：(poly, handles, 3x4矩阵, positions)
# 传单位矩阵 = 直接把 positions 原样写进位置通道（不改参照系）
RVA_POLY_SET_VERTEX_POSITIONS = 0xCDCA20
RVA_MESH_BUILD_FACE = 0x902280       # sub_180901F40(el, 点数组, 默认贴图轴, 点数, 材质名)
# CPolygonMesh 算子（2026-09-29 逆向，见 REVERSE_NOTES §16.10）：
#   sub_180CD21E0(poly, CUtlVector<16B 顶点条目>*, float 距离, char 维护半边, char 取中点, out*)
#     "MergeVerticesWithinDistance"：把距离 <= 阈值的顶点两两合并；返回本轮合并数(>0 表示有变化)
#     a4=1 焊接时同步重接半边（官方 UI 固定传 1）；a5=1 新位置取两端中点，0 保留其中一端
#   sub_180CD83C0(poly) "RemoveIsolatedVertices"：删掉不再属于任何面的孤立顶点（焊接后必跑）
RVA_POLY_MERGE_VERTICES = 0xCD2520
RVA_POLY_REMOVE_ISOLATED = 0xCD8700
# ⚠ 2026-09-26 实测：运行时的 mesh 几何**不在** CDmePolygonMesh 里。
# CMapMesh 的 `meshData` 属性值是无效句柄 0xFFFFFFFF，元素表里也没有 CDmePolygonMesh 实例；
# 真正存几何的是 **CHammerPolyMesh : CPolygonMesh**（半边缘 DCEL）：
#     CMapMesh + 0x498  内嵌 CHammerPolyMesh 对象（首 8 字节 = 该虚表）
#     CMapMesh + 0x560  指回内嵌对象自身的指针
#     CHammerPolyMesh 大小约 13632 字节（见其构造 sub_1808B2090 + 基类初始化 sub_180C89010）
#     CHammerPolyMesh + 13596/-FLT_MAX … 是自身 AABB（+13596 min / +13608 max）
#     CMapMesh + 0x118 附近是 CMapMesh 自己缓存的 AABB（空 mesh 时全是 ±FLT_MAX）
# CDmePolygonMesh 只在 .vmap 存档/载入时使用（`Save Copy As Text` 可看到）。
RVA_CHAMMERPOLYMESH_VTABLE = 0x1766ED8
RVA_CPOLYGONMESH_VTABLE = 0x18143D0
MESH_OFF_POLYMESH = 0x498            # CMapMesh 内嵌 CHammerPolyMesh 的偏移
MESH_OFF_POLYMESH_BACKPTR = 0x560    # 指回内嵌 CHammerPolyMesh 的指针
MESH_OFF_AABB = 0x118                # CMapMesh 缓存的 AABB（空 mesh = ±FLT_MAX）

# ---- CHammerPolyMesh 原生几何布局（2026-09-27 实证，见 REVERSE_NOTES.md §13）----
# 三组「池 + handle→槽位 映射」，组内均为 CUtlVector{count@+0, ?@+4, ptr@+8, cap@+0x10, flags@+0x14}
POLY_OFF_VPOOL_CNT = 0x18            # 顶点记录池(32B/条)：活顶点数
POLY_OFF_VPOOL_PTR = 0x20
POLY_OFF_VPOOL_CAP = 0x28            # 顶点池槽位容量（槽位数，不是字节数）
POLY_OFF_VMAP_CNT = 0x30             # 顶点 handle -> 池槽位（24B/条，句柄在 +8）
POLY_OFF_VMAP_PTR = 0x38
POLY_OFF_HEPOOL_PTR = 0x58           # 半边记录池(80B/条)
POLY_OFF_HEMAP_CNT = 0x68
POLY_OFF_HEMAP_PTR = 0x70
POLY_OFF_FPOOL_CNT = 0x88            # 面记录池(32B/条)
POLY_OFF_FPOOL_PTR = 0x90
POLY_OFF_FMAP_CNT = 0xA0
POLY_OFF_FMAP_PTR = 0xA8
POLY_OFF_CH_CTL = 0x688              # 通道集控制字：低字节==2，次字节==位置通道序号
POLY_OFF_CH_FLAGS = 0x8CC            # 逐通道 present 标志（0x8CC + 通道号）
POLY_OFF_CH0 = 0x8D8                 # 通道描述符数组（24B/项）
POLY_CH_STRIDE = 24
VREC_OFF_POS_INDEX = 0x10            # 顶点记录 +0x10 = 位置通道数据下标
HEC_OFF_ORIGIN_VERTEX = 0x00         # 半边记录 +0 = 起点顶点 handle（低 22 位为索引）
HEC_OFF_NEXT = 0x20                  # 半边记录 +0x20 = 下一条半边 handle
FACE_OFF_FIRST_HE = 0x00             # 面记录 +0 = 首条半边 handle
POLY_HANDLE_MASK = 0x3FFFFF          # handle 低 22 位 = 索引
POLY_HANDLE_INVALID = 0x3FFFFF
POLY_HANDLE_SERIAL_MASK = 0xFFC00000

# ---- 面 / 半边属性（2026-09-27 实证，VRF HammerMeshBuilder.WriteMesh 的运行时对应）----
POLY_OFF_HE_DENSE = 0x1110           # 「密集序 -> 半边 handle 索引」映射表（16B/条）
POLY_OFF_HE_TEXCOORD = 0x1240        # 每半边 texcoord（Vec2，按密集序）
POLY_OFF_HE_NORMAL = 0x1328          # 每半边 normal（Vec3）
POLY_OFF_HE_TANGENT = 0x1428         # 每半边 tangent（Vec4，w=手性）
POLY_OFF_FACE_SCALE = 0x3118         # 每面 textureScale（Vec2，Hammer 默认 0.125）
POLY_OFF_FACE_AXIS_U = 0x3300        # 每面 textureAxisU（Vec4）
POLY_OFF_FACE_AXIS_V = 0x3318        # 每面 textureAxisV（Vec4）
POLY_OFF_FACE_MATINDEX = 0x33B8      # 每面 materialindex（int，索引进材料名表；-1 = 无）
POLY_OFF_MATERIALS = 0x3448          # 材料名表 CUtlVector<CUtlString>：count@+0 / data@+8
POLY_CUTLSTRING_SIZE = 16            # CUtlString 记录步长，条首 qword = 名字指针
MESH_ATTR_DATA = "meshData"          # CMapMesh -> CDmePolygonMesh
MESH_ATTR_MATERIALS = "materials"    # CDmePolygonMesh -> 材质名数组
MESH_ATTR_STREAMS = "streams"        # CDmePolygonMeshDataArray -> [CDmePolygonMeshDataStream]
MESH_STREAM_ATTR_SEMANTIC = "semanticName"
MESH_STREAM_ATTR_DATA = "data"
# 流的位置（VRF HammerMeshBuilder.cs）：position 在 vertexData(loc 3)，
# texcoord/normal/tangent 在 faceVertexData(loc 1，per half-edge)，materialindex 在 faceData(loc 8)
MESH_STREAM_COMPONENTS = {
    "position": 3, "texcoord": 2, "normal": 3, "tangent": 4,
    "materialindex": 1, "flags": 1, "lightmapScaleBias": 1,
    "textureScale": 2, "textureAxisU": 4, "textureAxisV": 4,
}
MESH_ATTR_VERTEX_DATA = "vertexData"
MESH_ATTR_FACE_VERTEX_DATA = "faceVertexData"
MESH_ATTR_FACE_DATA = "faceData"
MESH_ATTR_FACE_DATA_INDICES = "faceDataIndices"
MESH_ATTR_FACE_EDGE_INDICES = "faceEdgeIndices"
MESH_ATTR_EDGE_NEXT_INDICES = "edgeNextIndices"
MESH_ATTR_EDGE_VERTEX_DATA_INDICES = "edgeVertexDataIndices"

# --- 新建元素/实体（2026-09 新版；CE 硬件断点活体实测确认）---
# CDataModel 通用元素创建（Hammer 实体工具/拖放建实体走的就是它）：
#   sub_1805BBB90(dm, const char* typeName, const char* name, int flags, const void* uniqueId)
#     -> 返回新元素句柄(u32)，失败 0xFFFFFFFF
#   uniqueId 传 0 时内部 CreateUniqueId 自动生成。
#   内部：sub_1805BA670 取空闲句柄 -> sub_1805BB7F0 按类型名查元素工厂表
#         -> factory->vfn0(handle, type, name, flags, uid) 即下面的 CMapEntity Create
#         -> 登记 句柄->元素、按需登记 CUndoCreateElement -> factory->vfn4(factory, elem)
RVA_DATAMODEL_CREATE_ELEMENT = 0x5BBED0
RVA_ELEMENT_CREATE_CORE = 0x5BBB30   # sub_1805BB7F0（内部，最终调工厂 Create）
# CMapEntity 元素工厂对象 RVA / 其虚表 RVA（slot0 = Create = 0x898D10）
RVA_CMAPENTITY_FACTORY = 0x21DB1F0
RVA_CMAPENTITY_FACTORY_VTABLE = 0x1765170
ENTITY_DMX_TYPE = "CMapEntity"       # 实体在 .vmap 里的元素类型名
ENTITY_CREATE_FLAGS = 1              # 与实体工具一致；!= -1 时登记 CUndoCreateElement 撤销步
INVALID_DMX_HANDLE = 0xFFFFFFFF

# --- Datamodel undo scope（新版反编译实测）---
# BeginUndoScope: "[%d] Pushing undo '%s'" 在 0x1816C7ED0 -> 0x60F370
# EndUndoScope(um, bool abort): 自减 scope 深度(+88) -> 0x60F1C0
RVA_UNDO_SCOPE_BEGIN = 0x60F6B0     # CUndoManager::BeginUndoScope(um, name, desc, flags)
RVA_UNDO_SCOPE_END = 0x60F500       # CUndoManager::EndUndoScope(um, bool abort=0)
UNDO_MGR_OFF_SCOPE_DEPTH = 88       # +0x58（新版；旧版在 +84）
UNDO_MGR_OFF_FLAGS = 132            # +0x84 bit3 = undo 总开关（不变）
UNDO_MGR_FLAG_ENABLED = 0x08


def _parse_addr(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(value, 0)


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
    再与各文档的 `CMapDoc+0x88`(world) 比对。找不到时退回 `_map_doc("")`（旧行为）。
    """
    chain = []
    cur = el
    for _ in range(64):
        if not cur:
            break
        chain.append(cur)
        p, err = _call_fn(RVA_NODE_GET_PARENT, [cur])
        if err:
            break
        cur = int(p, 16) if p else 0
    if chain:
        worlds = {}
        for d in _get_pipe().call("map_list_docs", {}).get("result", {}).get("docs", []):
            addr = int(d["address"], 16)
            worlds[_read_int(addr + CMAPDOC_WORLD_OFFSET, "u64")] = addr
        for addr in chain:
            if addr in worlds:
                return worlds[addr]
    return _map_doc("")


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


# --- CDataModel 元素表直查（句柄 -> CDmElement*，免主线程调用）-------------
_DM_TABLE: list[int] | None = None
_DM_TABLE_KEY: tuple[int, int, int] = (0, 0, 0)


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
    global _DM_TABLE, _DM_TABLE_KEY
    base = _hammer_base()
    dm = base + RVA_CDATAMODEL_GLOBAL
    arr = _read_int(dm + 0x90, "u64")
    cap = _read_int(dm + 0x88, "u32")
    count = _read_int(dm + 0x80, "u32")      # 存活元素数：新建会 +1，删除的孤儿仍占位
    key = (base, arr, cap, count)
    if _DM_TABLE is not None and key == _DM_TABLE_KEY:
        return _DM_TABLE, cap
    if not arr or cap <= 0 or cap > 1_000_000:
        raise RuntimeError(f"CDataModel 元素表异常: arr={arr:#x} cap={cap}")
    table = [0] * cap
    for off in range(0, cap * 16, MAX_READ_CHUNK):
        n = min(MAX_READ_CHUNK, cap * 16 - off)
        raw = _read_bytes(arr + off, n)
        for k in range(0, n - 15, 16):
            table[(off + k) // 16] = int.from_bytes(raw[k + 8:k + 16], "little")
    _DM_TABLE, _DM_TABLE_KEY = table, key
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


def _walk_elements(root: int, table: list[int] | None = None, cap: int = 0):
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
        if not node or node in seen or depth > 64:
            continue
        seen.add(node)
        try:
            raw = _read_bytes(node, NODE_OFF_CHILD_HANDLES + 8)
        except Exception:  # noqa: BLE001
            yield node, 0
            continue
        yield node, int.from_bytes(raw[0:8], "little")
        count = int.from_bytes(raw[NODE_OFF_CHILD_COUNT:NODE_OFF_CHILD_COUNT + 4], "little")
        arr = int.from_bytes(raw[NODE_OFF_CHILD_HANDLES:NODE_OFF_CHILD_HANDLES + 8], "little")
        if count <= 0 or count > 1_000_000 or not arr:
            continue
        try:
            kids_raw = _read_bytes(arr, count * 4)
        except Exception:  # noqa: BLE001
            continue
        children: list[int] = []
        for i in range(count):
            handle = int.from_bytes(kids_raw[i * 4:i * 4 + 4], "little", signed=True)
            if handle <= 0:
                continue
            child = _dm_handle_element(handle, table, cap)
            if child and child not in seen:
                children.append(child)
        # 逆序压栈，保持数组原顺序输出
        for child in reversed(children):
            stack.append((child, depth + 1))


_SYMBOL_NAMES: dict[int, str] = {}
"""CUtlSymbolLarge 指针 -> 字符串。属性名是驻留串，同名字共享同一 char*，
所以命中缓存后查属性名**零额外读取**。"""


def _dm_read_name(nameptr: int) -> str:
    nm = _SYMBOL_NAMES.get(nameptr)
    if nm is None:
        try:
            nm = _read_string(nameptr, 128)
        except Exception:  # noqa: BLE001
            nm = ""
        _SYMBOL_NAMES[nameptr] = nm
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


def _read_vec3(address: int) -> tuple[float, float, float]:
    """读 3 个连续 float（Source 2 的 Vec3D，12 字节）。"""
    return struct.unpack("<3f", _read_bytes(address, 12))


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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


# ---------------------------------------------------------------------------
# 实体类名 / 粒子定义（底层调用，2026-09 新版）
# ---------------------------------------------------------------------------
PARTICLE_ENTITY_CLASS = "info_particle_system"
PARTICLE_EFFECT_ATTR = "effect_name"


def _plausible_ptr(value: int) -> bool:
    """是否是像样的用户态指针（用来过滤实体内存里的整数/浮点）。"""
    return 0x10000 < value < 0x00007FFFFFFFFFFF and (value & 0x7) == 0


def _find_particle_helper(ent: int) -> int:
    """在实体内存里定位属于它的 CParticleHelper*。

    判定依据（纯内存，不调用任何函数）：
      * 候选对象首 qword（vptr）== hammer.dll + RVA_CPARTICLE_HELPER_VTABLE；
      * 候选对象 +152 的 u32 句柄经 datamodel vfn168 解析后 == 本实体。
    先在实体自身 6232 字节里找直挂的指针，再对每个可疑指针做一层二级扫描
    （helper 常放在 CUtlVector 的独立缓冲区里）。
    """
    base = _hammer_base()
    want_vt = base + RVA_CPARTICLE_HELPER_VTABLE

    raw = _read_bytes(ent, CMAPENTITY_SIZE)
    direct: list[int] = []
    for off in range(0, len(raw) - 8, 8):
        q = int.from_bytes(raw[off:off + 8], "little")
        if not _plausible_ptr(q):
            continue
        direct.append(q)
        if len(direct) > 600:
            break

    def _is_our_helper(cand: int) -> bool:
        try:
            if _read_int(cand, "u64") != want_vt:
                return False
            handle = _read_int(cand + OFF_HELPER_ENTITY_HANDLE, "u32")
            if not handle:
                return False
            return _resolve_handle(handle) == ent
        except Exception:  # noqa: BLE001
            return False

    for q in direct:                      # 一级：实体字段直指 helper
        if _is_our_helper(q):
            return q

    for q in direct[:200]:                # 二级：实体字段指向的容器里存 helper
        if not _plausible_ptr(q):
            continue
        try:
            blob = _read_bytes(q, 512)
        except Exception:  # noqa: BLE001
            continue
        for off in range(0, len(blob) - 8, 8):
            cand = int.from_bytes(blob[off:off + 8], "little")
            if _plausible_ptr(cand) and _is_our_helper(cand):
                return cand
    return 0


@mcp.tool()
def cs2_mem_scan(pattern: str, limit: int = 32, start: str = "", end: str = "") -> str:
    """全进程堆扫描字节模式（DLL 侧带 SEH 分块 + 2GB 上限，避免把游戏扫崩）。

    pattern 形如 `48 8B 05 ?? ?? ?? ??`（空格分隔十六进制，`??` 为通配）。
    start/end 可选，传地址字符串（如 '0x26360000000'）限定范围 —— 强烈建议限定，
    否则从最小应用地址开始扫，很可能到不了高地址堆。

    ⚠ 这是**进程内直读**，比 CS2 自己的反作弊/句柄扫描轻，但仍建议一次只扫一小段。

    Args:
        pattern: 空格分隔的十六进制字节模式。
        limit: 最多返回多少个命中。
        start: 可选起始地址。
        end: 可选结束地址。
    """
    try:
        params: dict[str, Any] = {"pattern": pattern, "limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        resp = _get_pipe().call("scan_heap", params)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    if "error" in resp:
        return f"INJECTED_DLL_ERROR: {resp['error']}"
    res = resp["result"]
    return (f"pattern={res['pattern']}  命中 {res['count']} 个\n"
            + "\n".join("  " + a for a in res["matches"]))


@mcp.tool()
def cs2_find_by_vtable(vtable_rva: str, limit: int = 32, start: str = "", end: str = "") -> str:
    """按「虚表指针」在进程内存里找某类的所有实例。

    原理：C++ 对象首 8 字节是虚表指针，值 = hammer_base + vtable_rva。
    对**不在 DMX 元素表里的原生对象**（如 mesh 的 CDmePolygonMesh）特别有用。

    Args:
        vtable_rva: 虚表 RVA，如 '0x176B8E0'(CMapMesh) / '0x1D70620'(CDmePolygonMesh)。
                    也接受 '0x7FF9...' 这种已加基址的绝对地址。
        limit: 最多返回多少个。
        start: 可选起始地址（建议给，否则可能扫不到高地址堆）。
        end: 可选结束地址。
    """
    try:
        rva = int(vtable_rva, 16)
        abs_vt = rva if rva > 0x7F0000000000 else _hammer_base() + rva
        pat = " ".join(f"{b:02X}" for b in struct.pack("<Q", abs_vt))
    except Exception as e:  # noqa: BLE001
        return f"ERROR 解析 vtable_rva 失败: {e}"
    out = cs2_mem_scan(pat, limit=limit, start=start, end=end)
    return f"vtable = {abs_vt:#x} (rva {rva:#x})\n{out}"


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


@mcp.tool()
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
    _qt_call(_hammer_base() + RVA_CONN_VALUE_INIT, [blk + CONN_OFF_PARAMMAP, 1, 8])
    return blk


@mcp.tool()
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
                hist_note = f"  ⚠ 记 Ctrl+Z 历史失败（写入照常）: {type(e).__name__}: {e}"
        blk = _conn_scratch({"source": source, "output": output, "target": target,
                             "input": input_name, "param": param},
                            target_type, delay, times_to_fire, relay, global_relay)
        outbuf = _alloc_mem(16)
        try:
            _qt_call(_hammer_base() + RVA_ENTITY_ADD_CONN, [ent, outbuf, blk], timeout=15000)
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


@mcp.tool()
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
                hist_note = f"  ⚠ 记 Ctrl+Z 历史失败（删除照常）: {type(e).__name__}: {e}"
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


def _poly_u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _poly_u64(buf: bytes, off: int) -> int:
    return struct.unpack_from("<Q", buf, off)[0]


def _poly_handle_slot(map_ptr: int, map_cnt: int, handle: int) -> int | None:
    """handle(低22位索引+高位序列号) -> 记录池槽位；校验不过返回 None。

    与 hammer.dll sub_180CC2830 的校验等价：索引范围内 + 表项里存的句柄索引一致 + 序列号一致。
    """
    idx = handle & POLY_HANDLE_MASK
    if not map_ptr or idx == POLY_HANDLE_INVALID or idx >= map_cnt:
        return None
    rec = _read_bytes(map_ptr + 24 * idx, 24)
    stored = _poly_u32(rec, 8)
    if (stored & POLY_HANDLE_MASK) != idx:
        return None
    if (handle ^ stored) & POLY_HANDLE_SERIAL_MASK:
        return None
    return _poly_u32(rec, 0)


def _poly_position_channel(poly: int) -> tuple[int, int, int]:
    """取位置通道 -> (数据个数, 数据指针, 通道号)；无位置通道返回 (0, 0, -1)。"""
    ctl = _read_int(poly + POLY_OFF_CH_CTL, "u32")
    ch = (ctl >> 8) & 0xFF
    if (ctl & 0xFF) != 2 or ch > 5:
        return 0, 0, -1
    if _read_bytes(poly + POLY_OFF_CH_FLAGS + ch, 1)[0] == 0:
        return 0, 0, -1
    desc = poly + POLY_OFF_CH0 + POLY_CH_STRIDE * ch
    cnt = _read_int(desc, "u32")
    ptr = _read_int(desc + 8, "u64")
    return cnt, ptr, ch


def _poly_ready(el: int) -> int:
    """校验并返回该元素的运行时 CHammerPolyMesh 地址；不是 mesh / 未就绪返回 0。"""
    base = _hammer_base()
    want = base + RVA_CHAMMERPOLYMESH_VTABLE
    try:
        poly = _read_int(el + MESH_OFF_POLYMESH_BACKPTR, "u64")
        if poly and _read_int(poly, "u64") == want:
            return poly
        poly = el + MESH_OFF_POLYMESH
        if _read_int(poly, "u64") == want:
            return poly
    except Exception:  # noqa: BLE001
        pass
    return 0


def _poly_materials(poly: int) -> list[str]:
    """材料名表 CUtlVector<CUtlString> @ poly+0x3448（16B/条，条首 qword = 名字指针）。"""
    cnt = _read_int(poly + POLY_OFF_MATERIALS, "u32")
    ptr = _read_int(poly + POLY_OFF_MATERIALS + 8, "u64")
    if not (0 < cnt < 4096) or not (0x10000000000 < ptr < 0x800000000000):
        return []
    rec = _read_bytes(ptr, POLY_CUTLSTRING_SIZE * cnt)
    names = []
    for i in range(cnt):
        sp = _poly_u64(rec, POLY_CUTLSTRING_SIZE * i)
        try:
            names.append(_read_string(sp, 260) if 0x10000 < sp < 0x7FFFFFFFFFFF else "")
        except Exception:  # noqa: BLE001
            names.append("")
    return names


def _poly_vertex_box(poly: int, origin: tuple[float, float, float],
                     max_verts: int = 4096):
    """用顶点池 + 位置通道算世界包围盒（(xmin,ymin,zmin,xmax,ymax,zmax)）；顶点太多返回 None。

    只用于元素缓存 AABB 失效（例如单面 mesh 某轴被压成 0 宽）时的兜底。
    """
    try:
        vcnt = _read_int(poly + POLY_OFF_VPOOL_CNT, "u32")
        vptr = _read_int(poly + POLY_OFF_VPOOL_PTR, "u64")
        pos_cnt, pos_ptr, _ = _poly_position_channel(poly)
        if not (0 < vcnt <= max_verts) or not vptr or not pos_ptr:
            return None
        recs = _read_bytes(vptr, 32 * vcnt)
    except Exception:  # noqa: BLE001
        return None
    mn = [float("inf")] * 3
    mx = [float("-inf")] * 3
    seen = 0
    for i in range(vcnt):
        pidx = _poly_u32(recs, 32 * i + VREC_OFF_POS_INDEX)
        if pidx >= pos_cnt:
            continue
        try:
            p = struct.unpack("<3f", _read_bytes(pos_ptr + 12 * pidx, 12))
        except Exception:  # noqa: BLE001
            continue
        for k in range(3):
            w = p[k] + origin[k]
            mn[k] = min(mn[k], w)
            mx[k] = max(mx[k], w)
        seen += 1
    if not seen:
        return None
    return (mn[0], mn[1], mn[2], mx[0], mx[1], mx[2])


def _mesh_world_box(el: int, poly: int):
    """mesh 的世界包围盒 + 来源说明。

    优先用元素缓存 AABB（`el+0x118`，布局 `{u32, xmin, ymin, zmin, xmax, ymax, zmax}`；
    实测手绘 mesh 与顶点算出来的一致）；缓存某个轴被压成 0 宽（单面 mesh 常见）或非法时，
    用小顶点数兜底重算。注意：地图自带的部分 tile mesh 缓存与顶点不在同一参照系（§13.6），
    两者都只当「大致范围」用。
    """
    box = None
    try:
        f = struct.unpack("<7f", _read_bytes(el + MESH_OFF_AABB, 28))
        xmin, ymin, zmin, xmax, ymax, zmax = f[1:7]
        if (xmin <= xmax and ymin <= ymax and zmin <= zmax
                and abs(xmin) < 1e9 and abs(xmax) < 1e9):
            box = (xmin, ymin, zmin, xmax, ymax, zmax)
    except Exception:  # noqa: BLE001
        box = None

    if box and all(box[i + 3] - box[i] > 0.01 for i in range(3)):
        return box, "AABB缓存"

    try:
        origin = _read_vec3(el + ENTITY_OFF_ORIGIN)
    except Exception:  # noqa: BLE001
        origin = (0.0, 0.0, 0.0)
    vbox = _poly_vertex_box(poly, origin)
    if box is None:
        return vbox, "顶点重算(无缓存)"
    if vbox is None:
        return box, "AABB缓存(某轴0宽)"
    # 缓存某轴被压成 0 宽时（单面 mesh / 带旋转的 mesh，两个来源的退化轴可能互补），
    # 取并集 —— 宁可范围外扩，也不要把对象漏掉。
    union = tuple([min(box[i], vbox[i]) for i in range(3)]
                  + [max(box[i + 3], vbox[i + 3]) for i in range(3)])
    return union, "并集(AABB缓存+顶点)"


def _parse_vec3_arg(value: Any, name: str) -> tuple[float, float, float]:
    """把 "x y z" / "x,y,z" / [x, y, z] 解析成 3 个 float。"""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    parts = str(value).replace("[", " ").replace("]", " ").replace(",", " ").split()
    if len(parts) != 3:
        raise ValueError(f'{name} 需要 3 个数字，例如 "0 0 0"（收到 {value!r}）')
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError as e:
        raise ValueError(f'{name} 不是 3 个数字：{value!r}') from e


def _box_hits(box: tuple[float, ...], qmin: tuple[float, float, float],
              qmax: tuple[float, float, float]) -> bool:
    """AABB 相交（闭区间）。"""
    return all(box[i + 3] >= qmin[i] and box[i] <= qmax[i] for i in range(3))


def _point_hits(p: tuple[float, float, float], qmin: tuple[float, float, float],
                qmax: tuple[float, float, float]) -> bool:
    return all(qmin[i] <= p[i] <= qmax[i] for i in range(3))



def _mesh_geometry_runtime(mesh_el: int, max_faces: int) -> str:
    """读运行时 CHammerPolyMesh 的半边缘几何（顶点/面环/世界包围盒）。"""
    poly = _poly_ready(mesh_el)
    if not poly:
        return (f"{mesh_el:#x} 没找到运行时的 CHammerPolyMesh"
                f"（+{MESH_OFF_POLYMESH_BACKPTR:#x} 指针 与 +{MESH_OFF_POLYMESH:#x} 内嵌均校验失败）")

    hdr = _read_bytes(poly, POLY_OFF_CH0 + POLY_CH_STRIDE * 6)
    vpool_cnt = _poly_u32(hdr, POLY_OFF_VPOOL_CNT)
    vpool_ptr = _poly_u64(hdr, POLY_OFF_VPOOL_PTR)
    vmap_cnt = _poly_u32(hdr, POLY_OFF_VMAP_CNT)
    vmap_ptr = _poly_u64(hdr, POLY_OFF_VMAP_PTR)
    hepool_ptr = _poly_u64(hdr, POLY_OFF_HEPOOL_PTR)
    hemap_cnt = _poly_u32(hdr, POLY_OFF_HEMAP_CNT)
    hemap_ptr = _poly_u64(hdr, POLY_OFF_HEMAP_PTR)
    fpool_cnt = _poly_u32(hdr, POLY_OFF_FPOOL_CNT)
    fpool_ptr = _poly_u64(hdr, POLY_OFF_FPOOL_PTR)
    if max(vpool_cnt, vmap_cnt, hemap_cnt, fpool_cnt) > 2_000_000:
        return f"{mesh_el:#x} 的 CHammerPolyMesh 头异常（count 过大），可能不是 mesh 元素"

    pos_cnt, pos_ptr, pos_ch = _poly_position_channel(poly)
    origin = _read_vec3(mesh_el + ENTITY_OFF_ORIGIN)

    def vec_desc(off: int) -> tuple[int, int]:
        """读一个 CUtlVector 描述符 -> (元素数, 数据指针)。"""
        return _read_int(poly + off, "u32"), _read_int(poly + off + 8, "u64")

    # 半边「密集序 -> handle 索引」映射：逐半边属性数组按密集序排列
    dense_cnt, dense_ptr = vec_desc(POLY_OFF_HE_DENSE)
    handle_to_dense: dict[int, int] = {}
    if 0 < dense_cnt < 1_000_000 and 0x10000000000 < dense_ptr < 0x800000000000:
        raw = _read_bytes(dense_ptr, 16 * dense_cnt)
        for i in range(dense_cnt):
            handle_to_dense[_poly_u32(raw, 16 * i) & POLY_HANDLE_MASK] = i

    tc_cnt, tc_ptr = vec_desc(POLY_OFF_HE_TEXCOORD)
    nrm_cnt, nrm_ptr = vec_desc(POLY_OFF_HE_NORMAL)
    fscale_cnt, fscale_ptr = vec_desc(POLY_OFF_FACE_SCALE)
    fau_cnt, fau_ptr = vec_desc(POLY_OFF_FACE_AXIS_U)
    fav_cnt, fav_ptr = vec_desc(POLY_OFF_FACE_AXIS_V)
    fmi_cnt, fmi_ptr = vec_desc(POLY_OFF_FACE_MATINDEX)
    materials = _poly_materials(poly)

    def he_uv(handle: int):
        d = handle_to_dense.get(handle & POLY_HANDLE_MASK)
        if d is None or not tc_ptr or d >= tc_cnt:
            return None
        return struct.unpack("<2f", _read_bytes(tc_ptr + 8 * d, 8))

    def he_normal(handle: int):
        d = handle_to_dense.get(handle & POLY_HANDLE_MASK)
        if d is None or not nrm_ptr or d >= nrm_cnt:
            return None
        return struct.unpack("<3f", _read_bytes(nrm_ptr + 12 * d, 12))

    def face_material(fslot: int) -> str:
        if not fmi_ptr or fslot >= fmi_cnt:
            return "<无 materialindex>"
        idx = _read_int(fmi_ptr + 4 * fslot, "i32")
        if 0 <= idx < len(materials):
            return materials[idx]
        return f"<越界 index={idx}，材料名表 {len(materials)} 项>"

    def face_tex_params(fslot: int) -> str:
        parts = []
        if fscale_ptr and fslot < fscale_cnt:
            s = struct.unpack("<2f", _read_bytes(fscale_ptr + 8 * fslot, 8))
            parts.append("scale=(%.4f,%.4f)" % s)
        if fau_ptr and fslot < fau_cnt:
            u = struct.unpack("<4f", _read_bytes(fau_ptr + 16 * fslot, 16))
            parts.append("U=(%.3f,%.3f,%.3f,w=%.3f)" % u)
        if fav_ptr and fslot < fav_cnt:
            v = struct.unpack("<4f", _read_bytes(fav_ptr + 16 * fslot, 16))
            parts.append("V=(%.3f,%.3f,%.3f,w=%.3f)" % v)
        return "  ".join(parts) if parts else "<无贴图参数>"

    pos_cache: dict[int, tuple[float, float, float]] = {}

    def vertex_local(vslot: int):
        """顶点池槽位 -> 本地坐标（位置通道 12B/顶点）。"""
        if vslot in pos_cache:
            return pos_cache[vslot]
        vrec = _read_bytes(vpool_ptr + 32 * vslot, 32)
        pidx = _poly_u32(vrec, VREC_OFF_POS_INDEX)
        pt = None
        if pos_ptr and pidx < pos_cnt:
            pt = struct.unpack("<3f", _read_bytes(pos_ptr + 12 * pidx, 12))
        pos_cache[vslot] = pt
        return pt

    lines = [
        f"CMapMesh {mesh_el:#x} 运行时 CHammerPolyMesh={poly:#x}",
        f"  顶点池 {vpool_cnt}（handle 表 {vmap_cnt}）  半边池 {hemap_cnt}（handle 表）  "
        f"面池 {fpool_cnt}  位置通道 #{pos_ch} 数据 {pos_cnt}  元素 origin={origin}",
        f"  材料名表 {len(materials)} 项 {materials[:8]}",
    ]

    verts: dict[int, tuple[float, float, float] | None] = {}
    for slot in range(min(vpool_cnt, max(max_faces * 8, 64))):
        verts[slot] = vertex_local(slot)

    wpts = []
    for slot, p in verts.items():
        if p:
            w = (origin[0] + p[0], origin[1] + p[1], origin[2] + p[2])
            wpts.append(w)
            lines.append(f"  v{slot:<3} 本地=({p[0]:9.3f},{p[1]:9.3f},{p[2]:9.3f})  "
                         f"世界=({w[0]:9.3f},{w[1]:9.3f},{w[2]:9.3f})")
    if wpts:
        mn = [min(p[i] for p in wpts) for i in range(3)]
        mx = [max(p[i] for p in wpts) for i in range(3)]
        lines.append("  世界包围盒 = (%.3f, %.3f, %.3f) ~ (%.3f, %.3f, %.3f)"
                     % (*mn, *mx))

    shown = 0
    for fslot in range(fpool_cnt):
        if shown >= max_faces:
            lines.append(f"  … 其余 {fpool_cnt - shown} 个面省略（max_faces={max_faces}）")
            break
        frec = _read_bytes(fpool_ptr + 32 * fslot, 32)
        first = _poly_u32(frec, FACE_OFF_FIRST_HE)
        loop: list[int | None] = []
        he_list: list[int] = []
        he = first
        for _ in range(4096):
            hslot = _poly_handle_slot(hemap_ptr, hemap_cnt, he)
            if hslot is None:
                loop.append(None)
                break
            hrec = _read_bytes(hepool_ptr + 80 * hslot, 80)
            he_list.append(he)
            loop.append(_poly_handle_slot(vmap_ptr, vmap_cnt,
                                          _poly_u32(hrec, HEC_OFF_ORIGIN_VERTEX)))
            he = _poly_u32(hrec, HEC_OFF_NEXT)
            if (he & POLY_HANDLE_MASK) == (first & POLY_HANDLE_MASK):
                break
        lines.append(f"  face[{fslot}] 首半边#{first & POLY_HANDLE_MASK} 顶点数 {len(loop)}  "
                     f"材质={face_material(fslot)}")
        lines.append(f"      贴图 {face_tex_params(fslot)}")
        for vs, he_h in zip(loop, he_list):
            p = verts.get(vs) if vs is not None else None
            if not p:
                continue
            uv = he_uv(he_h)
            n = he_normal(he_h)
            extra = ""
            if uv:
                extra += "  uv=(%.4f, %.4f)" % uv
            if n:
                extra += "  n=(%.3f, %.3f, %.3f)" % n
            lines.append("      v%-3d 世界=(%.3f, %.3f, %.3f)%s"
                         % (vs, origin[0] + p[0], origin[1] + p[1], origin[2] + p[2], extra))
        shown += 1
    return "\n".join(lines)


def _mesh_live_vertices(el: int, poly: int):
    """枚举活跃顶点 -> [(vertexHandle, poolSlot, posIndex, world(x,y,z))]。

    走顶点 handle 映射表（`poly+0x30`，24B/条：{池槽位@0, ?@4, 句柄@8}），
    句柄低 22 位 == 下标即为活跃项；顶点记录 `+0x10` 是位置通道下标，世界坐标 = 位置 + 元素 origin。
    """
    vmap_cnt = _read_int(poly + POLY_OFF_VMAP_CNT, "u32")
    vmap_ptr = _read_int(poly + POLY_OFF_VMAP_PTR, "u64")
    vpool_cap = _read_int(poly + POLY_OFF_VPOOL_CAP, "u32")
    vpool_ptr = _read_int(poly + POLY_OFF_VPOOL_PTR, "u64")
    pos_cnt, pos_ptr, _ = _poly_position_channel(poly)
    if not (0 < vmap_cnt < 1_000_000 and 0 < vpool_cap < 1_000_000) or not vmap_ptr or not vpool_ptr:
        return []
    origin = _read_vec3(el + ENTITY_OFF_ORIGIN)
    raw_map = _read_bytes(vmap_ptr, 24 * vmap_cnt)
    raw_pool = _read_bytes(vpool_ptr, 32 * vpool_cap)
    raw_pos = _read_bytes(pos_ptr, 12 * pos_cnt) if pos_ptr and pos_cnt else b""
    out = []
    for i in range(vmap_cnt):
        handle = _poly_u32(raw_map, 24 * i + 8)
        if (handle & POLY_HANDLE_MASK) != i:      # 空闲槽
            continue
        slot = _poly_u32(raw_map, 24 * i)
        if slot >= vpool_cap:
            continue
        pidx = _poly_u32(raw_pool, 32 * slot + VREC_OFF_POS_INDEX)
        if pidx >= pos_cnt or len(raw_pos) < 12 * (pidx + 1):
            continue
        p = struct.unpack_from("<3f", raw_pos, 12 * pidx)
        out.append((handle, slot, pidx,
                    (p[0] + origin[0], p[1] + origin[1], p[2] + origin[2])))
    return out


def _write_mem_chunked(address: int, data: bytes, chunk: int = 1024) -> None:
    """分块写内存（DLL 侧单次写入有上限）。"""
    for off in range(0, len(data), chunk):
        _write_mem(address + off, data[off:off + chunk])


@mcp.tool()
def cs2_mesh_scale(mesh: str, scale: str = "1 1 1", pivot: str = "") -> str:
    """缩放 mesh 几何（改顶点坐标），走 Hammer 自己的顶点写入算子。

    链路（2026-09-27 逆向，见 REVERSE_NOTES §13.10）：

        sub_180CDC6E0(poly, CUtlVector<顶点handle>*, 3x4矩阵*, CUtlVector<Vector>*)
          = CPolygonMesh 官方算子 **"SetVertexPositions"**：开事务 → 写位置通道 →
            更新缓存 → 发脏通知（Hammer 自己的 vfn+160 变换也走它）

    这里给它传**单位矩阵** + 网格本地坐标 —— 于是写进去的就是想要的值，不依赖
    「local→world 只差一个平移」的假设（地图自带 tile mesh 不满足该假设，见 §13.6）。
    顶点位置是 mesh 唯一的几何真相，缩放它就是缩放 mesh；UV 不动，所以贴图会跟着拉伸
    （等价 Hammer 里「关掉纹理锁定」缩放）。

    Args:
        mesh: CMapMesh 元素地址（cs2_mesh_list / cs2_area_query 给出）。
        scale: 各轴缩放系数 "sx sy sz"（也接受 "s,s,s"；单个数字 = 等比）。
        pivot: 缩放中心（世界坐标 "x y z"，内部换算到网格本地）；留空 = 用元素 origin。
    """
    base = _hammer_base()
    try:
        el = _parse_addr(mesh)
        poly = _poly_ready(el)
        if not poly:
            return f"{el:#x} 不是可编辑的 CMapMesh（没找到运行时 CHammerPolyMesh）"
        if "," in str(scale) or " " in str(scale).strip():
            sc = _parse_vec3_arg(scale, "scale")
        else:
            s = float(str(scale).strip())
            sc = (s, s, s)
        if sc[0] == 0 or sc[1] == 0 or sc[2] == 0:
            return "ERROR scale 不能含 0（会把 mesh 压成平面）"

        verts = _mesh_live_vertices(el, poly)
        if not verts:
            return f"{el:#x} 没有活跃顶点（可能只是空 mesh 元素）"
        origin = _read_vec3(el + ENTITY_OFF_ORIGIN)

        # 世界 pivot -> 本地 pivot（本地就是位置通道里存的坐标）
        if str(pivot).strip():
            pw = _parse_vec3_arg(pivot, "pivot")
        else:
            pw = origin
        pv = (pw[0] - origin[0], pw[1] - origin[1], pw[2] - origin[2])

        n = len(verts)
        size = 48 + 24 + 16 * n + 24 + 12 * n
        mem = _alloc_mem(size)
        mtx = mem
        hdr_h, data_h = mem + 48, mem + 48 + 24
        hdr_p, data_p = data_h + 16 * n + 24, data_h + 16 * n + 24 + 24
        try:
            hbuf = bytearray(16 * n)
            pbuf = bytearray(12 * n)
            for i, (handle, _slot, _pidx, w) in enumerate(verts):
                struct.pack_into("<I", hbuf, 16 * i, handle)
                # w 是「本地 + origin」，先还原成本地
                lx, ly, lz = w[0] - origin[0], w[1] - origin[1], w[2] - origin[2]
                struct.pack_into("<3f", pbuf, 12 * i,
                                 pv[0] + (lx - pv[0]) * sc[0],
                                 pv[1] + (ly - pv[1]) * sc[1],
                                 pv[2] + (lz - pv[2]) * sc[2])
            _write_mem_chunked(mtx, struct.pack("<12f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0))
            _write_mem_chunked(hdr_h, struct.pack("<IIQII", n, 0, data_h, n, 0))
            _write_mem_chunked(data_h, bytes(hbuf))
            _write_mem_chunked(hdr_p, struct.pack("<IIQII", n, 0, data_p, n, 0))
            _write_mem_chunked(data_p, bytes(pbuf))
            _qt_call(base + RVA_POLY_SET_VERTEX_POSITIONS, [poly, hdr_h, mtx, hdr_p],
                     timeout=20000)
        finally:
            _free_mem(mem)

        after = _mesh_live_vertices(el, poly)
        if not after:
            return "⚠ 调用已发出，但顶点读不回来了（mesh 状态异常）"
        mn = [min(v[3][k] for v in after) for k in range(3)]
        mx = [max(v[3][k] for v in after) for k in range(3)]
        try:
            box = struct.unpack("<7f", _read_bytes(el + MESH_OFF_AABB, 28))[1:7]
        except Exception:  # noqa: BLE001
            box = (0.0,) * 6
        body = (
            "已缩放 mesh 顶点  scale=(%.3f, %.3f, %.3f)  pivot(世界)=(%.1f, %.1f, %.1f)  顶点 %d 个\n"
            "  顶点世界包围盒 = (%.3f, %.3f, %.3f) ~ (%.3f, %.3f, %.3f)\n"
            "  元素缓存 AABB  = (%.3f, %.3f, %.3f) ~ (%.3f, %.3f, %.3f)"
            % (*sc, *pw, len(after), *mn, *mx, *box)
        )
        return body + "（缓存由 Hammer 异步刷新，可能延迟一拍）"
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


def _poly_set_flat_normals(poly: int) -> int:
    """把每角法线重写成**所属面的面法线**（Hammer 原生笔刷那种平直着色）。返回写入的半边数。

    为什么需要：官方焊接算子 `MergeVerticesWithinDistance` 会把每角法线**重算成顶点平均
    法线** —— 方块的角点变成 `(±1,±1,±1)/√3`，等于把方块渲染成"圆角/球面感"，实测
    未焊接时 CreateFace 给的是正确面法线，一焊就坏；而 Hammer 自己的笔刷（同样共享顶点、
    8 顶点 6 面）存的是**面法线**。所以焊接后必须按面重写一遍。

    写的是 `poly+POLY_OFF_HE_NORMAL` 那张**逐半边密集序**数组（12B/条，索引走
    `poly+POLY_OFF_HE_DENSE` 的「密集序 -> handle」映射），与 cs2_mesh_get_geometry 的读法同源。
    """
    try:
        vpool_ptr = _read_int(poly + POLY_OFF_VPOOL_PTR, "u64")
        vmap_cnt = _read_int(poly + POLY_OFF_VMAP_CNT, "u32")
        vmap_ptr = _read_int(poly + POLY_OFF_VMAP_PTR, "u64")
        hepool_ptr = _read_int(poly + POLY_OFF_HEPOOL_PTR, "u64")
        hemap_cnt = _read_int(poly + POLY_OFF_HEMAP_CNT, "u32")
        hemap_ptr = _read_int(poly + POLY_OFF_HEMAP_PTR, "u64")
        fpool_cnt = _read_int(poly + POLY_OFF_FPOOL_CNT, "u32")
        fpool_ptr = _read_int(poly + POLY_OFF_FPOOL_PTR, "u64")
        dense_cnt = _read_int(poly + POLY_OFF_HE_DENSE, "u32")
        dense_ptr = _read_int(poly + POLY_OFF_HE_DENSE + 8, "u64")
        nrm_cnt = _read_int(poly + POLY_OFF_HE_NORMAL, "u32")
        nrm_ptr = _read_int(poly + POLY_OFF_HE_NORMAL + 8, "u64")
        pos_cnt, pos_ptr, _ = _poly_position_channel(poly)
        if not (vpool_ptr and vmap_ptr and hepool_ptr and hemap_ptr and fpool_ptr
                and dense_ptr and nrm_ptr and pos_ptr):
            return 0
        if not (0 < dense_cnt < 1_000_000 and 0 < nrm_cnt < 1_000_000):
            return 0

        handle_to_dense: dict[int, int] = {}
        raw = _read_bytes(dense_ptr, 16 * dense_cnt)
        for i in range(dense_cnt):
            handle_to_dense[_poly_u32(raw, 16 * i) & POLY_HANDLE_MASK] = i

        pos_of_slot: dict[int, tuple[float, float, float]] = {}

        def slot_pos(vslot: int):
            if vslot in pos_of_slot:
                return pos_of_slot[vslot]
            p = None
            try:
                vrec = _read_bytes(vpool_ptr + 32 * vslot, 32)
                pidx = _poly_u32(vrec, VREC_OFF_POS_INDEX)
                if pidx < pos_cnt:
                    p = struct.unpack("<3f", _read_bytes(pos_ptr + 12 * pidx, 12))
            except Exception:  # noqa: BLE001
                p = None
            pos_of_slot[vslot] = p
            return p

        normals = bytearray(_read_bytes(nrm_ptr, 12 * nrm_cnt))
        written = 0
        for fslot in range(fpool_cnt):
            first = _poly_u32(_read_bytes(fpool_ptr + 32 * fslot, 32), FACE_OFF_FIRST_HE)
            he = first
            hes: list[int] = []
            pts: list[tuple[float, float, float]] = []
            for _ in range(4096):
                hslot = _poly_handle_slot(hemap_ptr, hemap_cnt, he)
                if hslot is None:
                    break
                hrec = _read_bytes(hepool_ptr + 80 * hslot, 80)
                hes.append(he & POLY_HANDLE_MASK)
                vs = _poly_handle_slot(vmap_ptr, vmap_cnt,
                                       _poly_u32(hrec, HEC_OFF_ORIGIN_VERTEX))
                p = slot_pos(vs) if vs is not None else None
                if p:
                    pts.append(p)
                he = _poly_u32(hrec, HEC_OFF_NEXT)
                if (he & POLY_HANDLE_MASK) == (first & POLY_HANDLE_MASK):
                    break
            if len(pts) < 3:
                continue
            nx, ny, nz = _face_normal_newell(pts)
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            if ln < 1e-12:
                continue
            packed = struct.pack("<3f", nx / ln, ny / ln, nz / ln)
            for h in hes:
                d = handle_to_dense.get(h)
                if d is None or d >= nrm_cnt:
                    continue
                normals[12 * d:12 * d + 12] = packed
                written += 1
        if written:
            _write_mem_chunked(nrm_ptr, bytes(normals))
        return written
    except Exception:  # noqa: BLE001
        return 0


def _mesh_weld_native(el: int, poly: int, distance: float = 0.01) -> tuple[int, int, int, str]:
    """原生焊接两步（不含历史）：MergeVerticesWithinDistance + RemoveIsolatedVertices。

    返回 (焊接前活跃顶点数, 焊接后活跃顶点数, 算子报告的合并数, 错误串)。
    """
    verts = _mesh_live_vertices(el, poly)
    n_before = len(verts)
    if n_before < 2:
        return n_before, n_before, 0, ""
    mem = _alloc_mem(20 + 16 * n_before)
    data = mem + 20
    try:
        hbuf = bytearray(16 * n_before)
        for i, (handle, _slot, _pidx, _w) in enumerate(verts):
            struct.pack_into("<I", hbuf, 16 * i, handle)
        _write_mem_chunked(mem, struct.pack("<IIQII", n_before, 0, data, n_before, 0))
        _write_mem_chunked(data, bytes(hbuf))
        # float 阈值走 "f:" 前缀 → xmm2（Win64 第 3 参数槽）
        ret, err = _call_fn(RVA_POLY_MERGE_VERTICES,
                            [poly, mem, f"f:{distance}", 1, 1, 0], timeout=30000)
        if err:
            return n_before, n_before, 0, f"MergeVerticesWithinDistance: {err}"
        merged = int(ret, 16) if ret else 0
        _r2, e2 = _call_fn(RVA_POLY_REMOVE_ISOLATED, [poly], timeout=30000)
        if e2:
            return n_before, n_before, merged, f"RemoveIsolatedVertices: {e2}"
    finally:
        _free_mem(mem)
    # 焊接会把每角法线变成平均法线（方块角 → (±1,±1,±1)/√3）→ 按面重写回面法线
    _poly_set_flat_normals(poly)
    return n_before, len(_mesh_live_vertices(el, poly)), merged, ""


@mcp.tool()
def cs2_mesh_weld_vertices(mesh: str, distance: float = 0.01,
                           history: bool = True) -> str:
    """焊接 mesh 中距离很近的重复顶点（Hammer 官方 MergeVerticesWithinDistance 算子）。

    用途：`cs2_mesh_create_box` 每个面各带 4 个顶点 → 24 顶点/6 面；本工具把同一位置的
    顶点焊成一个 → 8 顶点，等价原生 Block 工具的产物。

    链路（2026-09-29 逆向，见 REVERSE_NOTES §16.10）：

        sub_180CD21E0(poly, 全部顶点 handle 向量, float 阈值, 1, 1, 0)
          = CPolygonMesh 算子 "MergeVerticesWithinDistance"
            第 4 参数=1：焊接时同步重接半边；第 5 参数=1：新顶点取两端中点
            （与 Hammer 顶点工具的「Weld Vertices」命令完全同款参数）
        sub_180CD83C0(poly)
          = "RemoveIsolatedVertices"：合并后旧顶点变成孤立点，必须再调一次清掉

    阈值是**距离**（单位：世界单位的网格本地尺度，算子内部平方比较）。官方 UI 固定 0.01。

    Args:
        mesh: CMapMesh 元素地址（cs2_mesh_list / cs2_area_query 给出）。
        distance: 焊接距离阈值，<= 该距离的顶点合并（默认 0.01，官方 UI 同款）。
        history: 是否记入 Hammer 的 Ctrl+Z 历史（默认 True）。
    """
    base = _hammer_base()
    try:
        if distance < 0:
            return "ERROR distance 不能为负"
        el = _parse_addr(mesh)
        poly = _poly_ready(el)
        if not poly:
            return f"{el:#x} 不是可编辑的 CMapMesh（没找到运行时 CHammerPolyMesh）"

        hist_note = ""
        if history:
            try:
                doc = _doc_of_element(el)   # 多文档：按 mesh 反查所属文档，别写错历史栈
                undo_h, _rd = _find_map_histories(doc)
                hist_before = _hist_state(undo_h)
                _hist_push_step(undo_h, "cs2: weld vertices")
                # 记录的是**改动前**节点状态，必须在真正焊接之前登记
                _hist_record_node(undo_h, el)
                _hist_notify(undo_h)
            except Exception as e:  # noqa: BLE001
                hist_note = f"  ⚠ 未记入 Ctrl+Z 历史（{type(e).__name__}: {e}）"

        n_before, n_after, merged, werr = _mesh_weld_native(el, poly, distance)
        if n_before < 2:
            return f"{el:#x} 活跃顶点不足 2 个（{n_before}），无需焊接"
        if werr:
            return f"ERROR {werr}"

        if history and not hist_note:
            try:
                hist_note = f"  Ctrl+Z 历史: {hist_before} -> {_hist_state(undo_h)}"
            except Exception:  # noqa: BLE001
                pass

        after = _mesh_live_vertices(el, poly)
        if n_after:
            mn = [min(v[3][k] for v in after) for k in range(3)]
            mx = [max(v[3][k] for v in after) for k in range(3)]
            box_s = (f"  顶点世界包围盒 = ({mn[0]:.3f}, {mn[1]:.3f}, {mn[2]:.3f})"
                     f" ~ ({mx[0]:.3f}, {mx[1]:.3f}, {mx[2]:.3f})")
        else:
            box_s = "  ⚠ 焊接后读不回顶点（mesh 状态异常）"
        return (
            f"已焊接 mesh 顶点 元素={el:#x}  阈值={distance:g}\n"
            f"  顶点 {n_before} -> {n_after}（算子报告合并 {merged} 个）\n"
            f"{box_s}\n{hist_note}".rstrip()
        )
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


# 盒子 8 角（±1 占位）与 6 个面（外法线方向逆时针）
_BOX_CORNERS = ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))
_BOX_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 4, 7, 3), (1, 2, 6, 5))


# ---------------------------------------------------------------------------
# 面贴图坐标（UV）—— Hammer 默认的「世界对齐」投影（2026-09-29）
# ---------------------------------------------------------------------------
# ⚠ 建面算子 `sub_180901F40` 的第 3 参**不是** 32 字节的「默认贴图轴常量」，而是
#   **每点 8 字节的 Vec2 UV 数组**（反编译 sub_1808CAE90 第 2 段循环：`v71 + 8*n` 读）。
#   它把这些值**原样**写进 texcoord 流；Hammer 之后按这些 UV 反推面的贴图轴/scale/偏移
#   （VertexFormat `ComputeFaceTextureParametersFromCoordinates`）。
#   旧代码 6 个面共用一份 `(0,1)(1,1)(1,0)(0,0)` → 每面各铺满一张贴图、不随世界平铺，
#   于是「贴图和 UV 不对」。
#
# Hammer 默认的世界对齐（实测地图自带笔刷的面参数 + VRF `PolygonMesh.TextureAlignToGrid`）：
#     uv = dot(worldAxis, 世界坐标) / (scale * textureSize)
#   * `scale` = 0.125（`PolygonMesh.DefaultTextureScale`）
#   * 轴只由面法线的**主轴**决定（实测 ±X/±Y/±Z 用同一组轴，不看正负号）：
#         主轴 X → U=(0,1,0) V=(0,0,-1)   主轴 Y → U=(1,0,0) V=(0,0,-1)
#         主轴 Z → U=(1,0,0) V=(0,-1,0)
#   * `textureSize` = 贴图像素尺寸（Hammer 从材质系统取；未知材质 VRF 用 1024）。
#     它决定「一张贴图平铺多少世界单位」= scale * textureSize（512 贴图 → 64 单位）。
TEX_DEFAULT_SCALE = 0.125
TEX_DEFAULT_SIZE = 512.0
_TEX_AXES_BY_MAJOR = {
    0: ((0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),   # 主轴 X
    1: ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),   # 主轴 Y
    2: ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),   # 主轴 Z
}


def _face_normal_newell(pts):
    """多边形面法线（Newell 法，凹多边形也成立；大小为两倍面积）。"""
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0, z0 = pts[i]
        x1, y1, z1 = pts[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return nx, ny, nz


def _tex_axes_for_face(pts):
    """按面法线主轴选世界对齐贴图轴（主轴取绝对值最大者；并列时取靠后者，同 Hammer）。"""
    nx, ny, nz = _face_normal_newell(pts)
    absn = (abs(nx), abs(ny), abs(nz))
    best, major = -1.0, 0
    for i in range(3):
        if absn[i] >= best:
            best, major = absn[i], i
    return _TEX_AXES_BY_MAJOR[major]


def _dot_axis_range(ax, lo, hi):
    """`dot(ax, ·)` 在 AABB [lo, hi] 上的 (最小值, 最大值)。

    `ax` 只含 ±1 / 0（世界轴），所以逐分量取值即可，不需要枚举顶点。
    """
    d_lo = d_hi = 0.0
    for k in range(3):
        if ax[k] > 0.0:
            d_lo += ax[k] * lo[k]
            d_hi += ax[k] * hi[k]
        elif ax[k] < 0.0:
            d_lo += ax[k] * hi[k]
            d_hi += ax[k] * lo[k]
    return d_lo, d_hi


def _face_uv_bytes(pts, lo, hi, tex_size=TEX_DEFAULT_SIZE, tex_scale=TEX_DEFAULT_SCALE):
    """给一个面算 Hammer 风格的 UV（每点 8 字节 Vec2），返回字节串。

    ⚠ 必须传**世界坐标**（元素 origin + 本地坐标）与整网格的 AABB `[lo, hi]`。

    相位规则（实测 Hammer Block 工具产物）：轴是**世界轴**（按面法线主轴选），
    但 UV **从网格自己的角点起算** ——

        u = (dot(U轴, 世界坐标) − u_min) / (scale × textureSize)      # 锚在网格 U 向最小端
        v = (dot(V轴, 世界坐标) − v_max) / (scale × textureSize)      # 锚在网格 V 向最大端

    以 `materials/dev/reflectivity_30.vmat`（512 → 64 单位/贴图）为例，Hammer 新建的
    64×96×64 块：顶面 `u=(x−xmin)/64 → 0…1`、`v=−(y−ymin)/64 → 0…−1.5`；
    若改成世界相位（`u=x/64`）就会得到 `−13…−12`，和 Hammer 建出来的块对不上（差半个
    非整数相位，视觉上"效果不太一样"）。
    """
    (ux, uy, uz), (vx, vy, vz) = _tex_axes_for_face(pts)
    u_ax, v_ax = (ux, uy, uz), (vx, vy, vz)
    u_org, _ = _dot_axis_range(u_ax, lo, hi)
    _, v_org = _dot_axis_range(v_ax, lo, hi)
    k = (tex_scale or TEX_DEFAULT_SCALE) * (tex_size or TEX_DEFAULT_SIZE)
    out = bytearray()
    for x, y, z in pts:
        out += struct.pack("<2f",
                           (u_ax[0] * x + u_ax[1] * y + u_ax[2] * z - u_org) / k,
                           (v_ax[0] * x + v_ax[1] * y + v_ax[2] * z - v_org) / k)
    return bytes(out)


@mcp.tool()
def cs2_mesh_create_box(center: str = "", size: str = "32 32 32",
                        material: str = "materials/tools/toolsnodraw.vmat",
                        name: str = "cs2_box", weld: bool = True,
                        tex_size: float = TEX_DEFAULT_SIZE,
                        doc: str = "") -> str:
    """从零建一个**盒形笔刷**（CMapMesh + 6 个面），挂进世界并记进 Hammer 的 Ctrl+Z 历史。

    链路（2026-09-27 逆向，见 REVERSE_NOTES §16）：

        CreateElement("CMapMesh")       → 元素自带一个**空的** CHammerPolyMesh（el+0x498）
        每个面: sub_180901F40(el, 4 个点(12B/点), 4 个 UV(8B/点), 4, 材质名)
        PostClass sub_180866D70(el, 0)  → AddChild sub_180879170(doc, el, 0)
        weld=True: MergeVerticesWithinDistance + RemoveIsolatedVertices（见 §16.10）

    ⚠ 用 `sub_180901F40` 而**不是**官方的 `sub_180901DF0(el, 宽, 高, 材质)`：后者第 2/3 个
    参数是 float（走 xmm 寄存器），现在 DLL 调用桥已支持浮点（"f:" 前缀）。

    每面各带 4 个顶点（共 24 个）；`weld=True`（默认）会用官方算子把同一位置的顶点焊成
    一个 → **8 顶点 / 6 面**，与 Hammer Block 工具产物一致。焊接归入同一个 Ctrl+Z 步，
    一次 Undo 即删除整个盒子。

    贴图：每面按 Hammer Block 工具的规则写 UV —— 轴取**世界轴**（按面法线主轴选），
    但相位**锚在本网格自己的角点**（`u=(U向坐标−最小值)/k`、`v=(V向坐标−最大值)/k`，
    `k = 0.125×tex_size`，见 `_face_uv_bytes`）—— 建出来的块与 Hammer 手建的块外观一致。

    Args:
        center: 盒心世界坐标 "x y z"（留空 = 世界原点）。
        size: 三个方向的边长 "sx sy sz"（单个数字 = 正方体）。
        material: 材质路径（写进网格的材质表）。
        name: 元素名（显示在 Hammer 里）。
        weld: 是否把 24 个面顶点焊接为 8 个共享顶点（默认 True）。
        tex_size: 贴图像素尺寸（默认 512）。一张贴图平铺 `tex_size×0.125` 世界单位，
             512 → 64 单位；材质贴图不是 512 时改这里（纯色/nodraw 材质无所谓）。
        doc: 目标地图文档：留空 = 清单第一个；数字 = 索引；其余 = 路径子串
             （多文档时**务必指定**，见 `cs2_map_list_docs`）。
    """
    base = _hammer_base()
    try:
        ctr = _parse_vec3_arg(center, "center") if str(center).strip() else (0.0, 0.0, 0.0)
        # 单个数字 = 正方体（和 cs2_mesh_scale 一个口径）
        if "," in str(size) or " " in str(size).strip():
            sz = _parse_vec3_arg(size, "size")
        else:
            s = float(str(size).strip())
            sz = (s, s, s)
        if min(sz) <= 0:
            return "ERROR size 必须为正数"
        doc = _map_doc(doc)   # 参数是文档选择器，这里换成 CMapDoc 地址
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")

        ret, err = _call_fn(RVA_DATAMODEL_CREATE_ELEMENT, [
            base + RVA_CDATAMODEL_GLOBAL, "str:CMapMesh", f"str:{name}",
            ENTITY_CREATE_FLAGS, 0], timeout=20000)
        if err:
            return f"ERROR 建 CMapMesh 元素失败: {err}"
        el = _resolve_handle(int(ret, 16) & 0xFFFFFFFF)
        poly = _poly_ready(el)
        if not poly:
            return f"ERROR 新建的 {el:#x} 没有运行时 CHammerPolyMesh"
        _write_mem_chunked(el + ENTITY_OFF_ORIGIN, struct.pack("<3f", *ctr))

        hx, hy, hz = sz[0] * 0.5, sz[1] * 0.5, sz[2] * 0.5
        corners = [(hx * c[0], hy * c[1], hz * c[2]) for c in _BOX_CORNERS]
        # 世界坐标（本地角点 + 元素 origin）—— UV 要按世界坐标算（相位再锚到网格 AABB）
        world_faces = [[(ctr[0] + corners[i][0], ctr[1] + corners[i][1], ctr[2] + corners[i][2])
                        for i in face] for face in _BOX_FACES]
        # UV 相位的锚点 = 整网格 AABB（世界坐标）
        lo = (ctr[0] - hx, ctr[1] - hy, ctr[2] - hz)
        hi = (ctr[0] + hx, ctr[1] + hy, ctr[2] + hz)
        mb = str(material).encode() + b"\x00"
        n_pts = sum(len(f) for f in world_faces)
        uv_sz = sum(8 * len(f) for f in world_faces)
        mem = _alloc_mem(12 * n_pts + uv_sz + len(mb) + 8)
        pts, uvs, matp = mem, mem + 12 * n_pts, mem + 12 * n_pts + uv_sz
        try:
            buf = bytearray()
            for face in _BOX_FACES:
                for i in face:
                    buf += struct.pack("<3f", *corners[i])
            _write_mem_chunked(pts, bytes(buf))
            _write_mem_chunked(uvs, b"".join(_face_uv_bytes(f, lo, hi, tex_size)
                                             for f in world_faces))
            _write_mem_chunked(matp, mb)
            off = uv_off = 0
            for f in world_faces:
                _qt_call(base + RVA_MESH_BUILD_FACE,
                         [el, pts + off, uvs + uv_off, len(f), matp], timeout=20000)
                off += 12 * len(f)
                uv_off += 8 * len(f)
        finally:
            _free_mem(mem)

        _qt_call(base + RVA_NODE_POST_CLASS, [el, 0], timeout=20000)
        before = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")
        add_ret, add_err = _call_fn(RVA_NODE_ADD_CHILD, [doc, el, 0], timeout=30000)
        after = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")

        weld_note = ""
        if weld:
            # 归入下面同一个 create box 撤销步：记录的是「新增元素」最终态，一次 Undo 整盒删除
            n_b, n_a, merged, werr = _mesh_weld_native(el, poly, 0.01)
            weld_note = (f"  焊接 {n_b} -> {n_a} 顶点（合并 {merged}）\n"
                         if not werr else f"  ⚠ 焊接失败: {werr}\n")

        hist_note = ""
        try:
            undo_hist, _rd = _find_map_histories(doc)
            hist_before = _hist_state(undo_hist)
            _hist_push_step(undo_hist, f"cs2: create box {sz[0]:g}x{sz[1]:g}x{sz[2]:g}")
            _hist_record_object(undo_hist, el, added=True)
            _hist_notify(undo_hist)
            hist_note = (f"  Ctrl+Z 历史: {hist_before} -> {_hist_state(undo_hist)}"
                         f"  记录 node={el + NODE_IFACE_OFFSET:#x}")
        except Exception as e:  # noqa: BLE001
            hist_note = f"  ⚠ 未记入 Ctrl+Z 历史（{type(e).__name__}: {e}）"

        verts = _mesh_live_vertices(el, poly) or []
        try:
            box = struct.unpack("<7f", _read_bytes(el + MESH_OFF_AABB, 28))[1:7]
        except Exception:  # noqa: BLE001
            box = (0.0,) * 6
        parent_hex, _pe = _call_fn(RVA_NODE_GET_PARENT, [el])
        return (
            f"已建盒形笔刷 元素={el:#x}  顶点={len(verts)}（{'8 共享顶点' if weld else '每面 4 个，未焊接'}）\n"
            f"  center=({ctr[0]:g}, {ctr[1]:g}, {ctr[2]:g})  size=({sz[0]:g}, {sz[1]:g}, {sz[2]:g})"
            f"  材质={material!r}\n"
            f"  元素缓存 AABB = ({box[0]:.3f}, {box[1]:.3f}, {box[2]:.3f})"
            f" ~ ({box[3]:.3f}, {box[4]:.3f}, {box[5]:.3f})\n"
            f"  材质表 = {_poly_materials(poly)}\n"
            f"{weld_note}"
            f"  AddChild ret={add_ret} err={add_err!r}  world 子节点 {before} -> {after}\n"
            f"  GetParent = {parent_hex}\n"
            + hist_note
        )
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


def _arch_outline(width: float, height: float, opening: float,
                  opening_height: float, segments: int) -> list[tuple[float, float]]:
    """拱门在 XZ 截面（x=宽向, z=竖直）上的**简单凹多边形**轮廓（CCW），门洞从地面切入。

    外轮廓 = width×height 矩形；门洞宽 opening（半圆半径 r=opening/2），直墙高
    opening_height-r，拱顶半圆由 segments 段折线近似。

    ⚠ `opening_height` 必须**严格小于** height：否则拱顶顶点与该矩形顶边相切，多边形退化成
    非简单多边形（三角化会出现零面积片、Hammer 拒收）。
    """
    half_out, r = width * 0.5, opening * 0.5
    side_h = opening_height - r
    pts: list[tuple[float, float]] = [
        (-half_out, 0.0),       # 外墙左下角
        (-r, 0.0),              # 门洞左内边（地面）
        (-r, side_h),           # 左墙顶 = 半圆起点(θ=π)
    ]
    for k in range(1, segments + 1):        # 半圆 θ: π → 0，末点 = (r, side_h)
        t = math.pi * (1.0 - k / segments)
        pts.append((r * math.cos(t), side_h + r * math.sin(t)))
    pts += [
        (r, 0.0),               # 门洞右内边落地
        (half_out, 0.0),        # 外墙右下角
        (half_out, height),     # 右上
        (-half_out, height),    # 左上（闭合回外墙左下）
    ]
    return pts


@mcp.tool()
def cs2_mesh_create_arch(center: str = "", width: float = 160.0, height: float = 160.0,
                         thickness: float = 16.0, opening: float = 96.0,
                         opening_height: float = 0.0, segments: int = 12,
                         material: str = "materials/tools/toolsnodraw.vmat",
                         name: str = "cs2_arch", weld: bool = True,
                         tex_size: float = TEX_DEFAULT_SIZE,
                         doc: str = "") -> str:
    """建一个**拱门笔刷**（凹多边形截面沿厚度拉伸：矩形墙 + 半圆拱顶门洞），挂进世界并记历史。

    构造方式：XZ 截面上画一个 U 形凹多边形（`_arch_outline`），沿 y 向拉伸 thickness ——
    前/后端面各一个 n 点**凹多边形面**（建面算子 `CreateFaceLocalFromPoints` 点数直接透传、
    凹面同样接受），每条截面边（含拱顶半圆的 segments 段折线）生成一个连接前后的四边形
    条带 → 共 n+2 个面、2n 个顶点；最后走官方焊接算子合并共享顶点 → 收敛到 n 个顶点。

    ⚠ `opening_height` 必须**严格小于** height：否则拱顶顶点与矩形顶边相切，截面退化成
    非简单多边形（建面会静默失败 / 焊接无法收敛）。

    几何参数（全部世界单位）：

        外墙：宽 width、总高 height、进深 thickness（y 向）
        门洞：宽 opening（半圆直径 = opening），地面到拱顶高 opening_height
              （默认 0 = 自动取 height×0.9，顶部留出拱冠厚度）

    Args:
        center: 拱门底平面中心 "x y z"（截面 z=0 落在此高度；留空 = 世界原点）。
        width: 外墙总宽（默认 160）。
        height: 外墙总高（默认 160）。
        thickness: 墙厚/进深（默认 16）。
        opening: 门洞宽（半圆直径，默认 96；须 < width）。
        opening_height: 门洞地面到拱顶高（默认 0 = height×0.9；须 ≥ opening/2 且 < height）。
        segments: 拱顶半圆分段数（默认 12，越大越圆滑、面越多）。
        material: 材质路径。
        name: 元素名。
        weld: 是否焊接共享顶点（默认 True）。
        tex_size: 贴图像素尺寸（默认 512）；每面按世界对齐投影写 UV，见 `cs2_mesh_create_box`。
        doc: 目标地图文档：留空 = 清单第一个；数字 = 索引；其余 = 路径子串
             （多文档时**务必指定**，见 `cs2_map_list_docs`）。
    """
    base = _hammer_base()
    try:
        if opening >= width:
            return "ERROR opening 必须 < width（门洞要比外墙窄）"
        r = opening * 0.5
        oh = float(opening_height) if opening_height else height * 0.9
        if r > oh:
            return f"ERROR opening/2 ({r:g}) 不能大于 opening_height ({oh:g})（半圆放不下）"
        if oh >= height:
            return (f"ERROR opening_height ({oh:g}) 必须 < height ({height:g})"
                    f"（否则拱顶与墙顶相切，截面退化为非简单多边形）")
        if segments < 3:
            return "ERROR segments 至少 3"
        ctr = _parse_vec3_arg(center, "center") if str(center).strip() else (0.0, 0.0, 0.0)
        cx, cy, cz = ctr
        # ⚠ 顶点写**本地坐标**，元素 origin 设成 ctr（渲染时相加）—— 和 cs2_mesh_create_box 一致。
        #   早期版本把 ctr 加进了顶点、又设了 origin，导致位置被叠加两次（拱门跑偏一倍）。
        yf, yb = -thickness * 0.5, thickness * 0.5
        outline = _arch_outline(width, height, opening, oh, segments)
        n = len(outline)

        # 面表：前/后端面各一个 n 点凹多边形（建面算子点数直接透传，**凹面同样接受**，
        # 实测 19 点 U 形面可正常建立），每条轮廓边一个四边形条带 → 共 n+2 个面。
        # 绕序：outline 为 (x,z) 平面 CCW → 外法线 -y（前端面 yf 朝外）；后端面反向 → +y。
        faces: list[list[tuple[float, float, float]]] = [
            [(x, yf, z) for x, z in outline],
            [(x, yb, z) for x, z in reversed(outline)],
        ]
        for i in range(n):
            xi, zi = outline[i]
            xj, zj = outline[(i + 1) % n]
            fi = (xi, yf, zi)
            bi = (xi, yb, zi)
            bj = (xj, yb, zj)
            fj = (xj, yf, zj)
            faces.append([fi, bi, bj, fj])    # 条带绕序 → 法线统一朝截面外侧

        doc = _map_doc(doc)   # 参数是文档选择器，这里换成 CMapDoc 地址
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
        ret, err = _call_fn(RVA_DATAMODEL_CREATE_ELEMENT, [
            base + RVA_CDATAMODEL_GLOBAL, "str:CMapMesh", f"str:{name}",
            ENTITY_CREATE_FLAGS, 0], timeout=20000)
        if err:
            return f"ERROR 建 CMapMesh 元素失败: {err}"
        el = _resolve_handle(int(ret, 16) & 0xFFFFFFFF)
        poly = _poly_ready(el)
        if not poly:
            return f"ERROR 新建的 {el:#x} 没有运行时 CHammerPolyMesh"
        _write_mem_chunked(el + ENTITY_OFF_ORIGIN, struct.pack("<3f", *ctr))

        total_pts = sum(len(f) for f in faces)
        uv_sz = sum(8 * len(f) for f in faces)
        # UV 相位的锚点 = 整网格 AABB（世界坐标）
        alo = tuple(min(p[k] for f in faces for p in f) for k in range(3))
        ahi = tuple(max(p[k] for f in faces for p in f) for k in range(3))
        mb = str(material).encode() + b"\x00"
        mem = _alloc_mem(12 * total_pts + uv_sz + len(mb) + 8)
        pts_base, uvs, matp = mem, mem + 12 * total_pts, mem + 12 * total_pts + uv_sz
        try:
            buf = bytearray()
            for f in faces:
                for p in f:
                    buf += struct.pack("<3f", *p)
            _write_mem_chunked(pts_base, bytes(buf))
            # faces 里已是世界坐标 → 直接算 UV（相位锚在网格角点，见 _face_uv_bytes）
            _write_mem_chunked(uvs, b"".join(_face_uv_bytes(f, alo, ahi, tex_size)
                                             for f in faces))
            _write_mem_chunked(matp, mb)
            off = uv_off = 0
            for f in faces:
                _qt_call(base + RVA_MESH_BUILD_FACE,
                         [el, pts_base + off, uvs + uv_off, len(f), matp], timeout=20000)
                off += 12 * len(f)
                uv_off += 8 * len(f)
        finally:
            _free_mem(mem)

        _qt_call(base + RVA_NODE_POST_CLASS, [el, 0], timeout=20000)
        before = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")
        add_ret, add_err = _call_fn(RVA_NODE_ADD_CHILD, [doc, el, 0], timeout=30000)
        after = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")

        weld_note = ""
        if weld:
            n_b, n_a, merged, werr = _mesh_weld_native(el, poly, 0.01)
            weld_note = (f"  焊接 {n_b} -> {n_a} 顶点（合并 {merged}）\n"
                         if not werr else f"  ⚠ 焊接失败: {werr}\n")

        hist_note = ""
        try:
            undo_hist, _rd = _find_map_histories(doc)
            hist_before = _hist_state(undo_hist)
            _hist_push_step(undo_hist, f"cs2: create arch {width:g}x{height:g}")
            _hist_record_object(undo_hist, el, added=True)
            _hist_notify(undo_hist)
            hist_note = f"  Ctrl+Z 历史: {hist_before} -> {_hist_state(undo_hist)}"
        except Exception as e:  # noqa: BLE001
            hist_note = f"  ⚠ 未记入 Ctrl+Z 历史（{type(e).__name__}: {e}）"

        verts = _mesh_live_vertices(el, poly) or []
        return (
            f"已建拱门笔刷 元素={el:#x}  面={len(faces)}（{segments} 段拱顶）  顶点={len(verts)}\n"
            f"  外墙 {width:g} 宽 × {height:g} 高 × {thickness:g} 厚；门洞宽 {opening:g}"
            f" 高 {oh:g}（直墙高 {oh - r:g}）\n"
            f"  center=({cx:g}, {cy:g}, {cz:g})\n"
            f"  材质表 = {_poly_materials(poly)}\n"
            f"{weld_note}"
            f"  AddChild ret={add_ret} err={add_err!r}  world 子节点 {before} -> {after}\n"
            + hist_note
        )
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


def _read_cptr(addr: int, off: int = 0, maxlen: int = 256) -> str:
    """读 `*(char**)(addr+off)` 指向的字符串；指针不像样就返回空串。"""
    if not addr:
        return ""
    try:
        p = _read_int(addr + off, "u64")
        return _read_string(p, maxlen) if 0x10000 < p < 0x7FFFFFFFFFFF else ""
    except Exception:  # noqa: BLE001
        return ""


def _vfn_ptr(this_ptr: int, vtable_offset: int, args: list | None = None,
             timeout: int = 10000) -> int:
    """调虚函数并把返回值当**指针/整数**取回（失败返回 0）。

    `_call_vfn` 返回的是 `(ret_hex, err)` 元组，**必须自己解包**——直接把元组喂给
    `_read_string`/`int` 会被 JSON 序列化成数组，DLL 的 `GetAddressParam` 拒收，
    报 `invalid 'address'`。
    """
    if not this_ptr:
        return 0
    try:
        ret_hex, _err = _call_vfn(this_ptr, vtable_offset, list(args or []), timeout)
        return int(ret_hex, 16) if ret_hex else 0
    except Exception:  # noqa: BLE001
        return 0


@mcp.tool()
def cs2_bind_list(filter: str = "", limit: int = 0) -> str:
    """列出 Hammer 的「可绑定工具命令」全表 —— 就是 Options → Key Bindings 里那张表。

    数据源（2026-09-27 逆向，见 REVERSE_NOTES.md §17）：Hammer 里**每个工具类**在静态初始化时，
    把自己的 `CBaseBindTargetDescriptor` 头插进一条**全局链表**（表头 `hammer+0x272D898`）。
    每个描述符给出「工具名 + 实现类名 + 注册处源文件/行号」，并通过虚函数给出它的一批命令。

    读取方式**全只读**（纯 getter 虚调用），不改地图、不产生历史：

        vtable[0]  → 工具名 (char*)        vtable[24] → 命令数 (int)
        vtable[32] → 第 i 个命令 (对象*)   命令对象 +0x08 = 命令名 · +0x18 = 描述

    用途：摸清 Hammer 自己有哪些原子操作（选择 / 对齐 / 吸附 / 各种工具的开关），
    后续可以按名字去调它们，而不是逐个逆向底层实现。

    Args:
        filter: 大小写不敏感的子串过滤（匹配工具名 / 类名 / 命令名）。
        limit: 最多列多少条命令（0 = 不限）。
    """
    base = _hammer_base()
    cap = max(0, int(limit))
    kw = str(filter).strip().lower()
    try:
        head = _read_int(base + RVA_BIND_TARGET_LIST, "u64")
        if not head:
            return "绑定目标链表为空（Hammer 可能还没初始化完，或版本不符）"
        nodes, seen, n_cmds = [], set(), 0
        node = head
        while node and node not in seen and len(nodes) < 1024:
            seen.add(node)
            name = _read_string(_vfn_ptr(node, BIND_VFN_NAME), 128)
            cls = _read_cptr(node, BIND_OFF_CLASS, 128)
            fname = _read_cptr(node, BIND_OFF_FILE, 200)
            try:
                line = _read_int(node + BIND_OFF_LINE, "u32")
            except Exception:  # noqa: BLE001
                line = 0
            n = _vfn_ptr(node, BIND_VFN_CMD_COUNT)
            cmds = []
            for i in range(max(0, min(int(n), 512))):
                cptr = _vfn_ptr(node, BIND_VFN_CMD_AT, [i])
                cname = _read_cptr(cptr, BIND_CMD_OFF_NAME, 160)
                if not cname:
                    continue
                cmds.append((cname, _read_cptr(cptr, BIND_CMD_OFF_DESC, 200)))
            nodes.append((node, name, cls, fname, line, cmds))
            n_cmds += len(cmds)
            node = _read_int(node + BIND_OFF_NEXT, "u64")

        lines = [f"Hammer 可绑定工具命令  工具 {len(nodes)} 个 / 命令 {n_cmds} 条"
                 f"  链表头={head:#x}"]
        shown = 0
        for node, name, cls, fname, line, cmds in nodes:
            if cap and shown >= cap:
                break
            hit_tool = (not kw) or kw in (name or "").lower() or kw in (cls or "").lower()
            hit_cmds = [(c, d) for c, d in cmds if not kw or kw in c.lower()]
            if not hit_tool and not hit_cmds:
                continue
            lines.append(f"\n【{name or '(无名)'}】  类={cls or '?'}")
            if fname:
                lines.append(f"   注册处: {fname}:{line}")
            use = cmds if hit_tool else hit_cmds
            for c, d in use:
                if cap and shown >= cap:
                    break
                lines.append(f"   · {c}" + (f"  — {d}" if d else ""))
                shown += 1
        lines.append(f"\n（已列出 {shown} 条命令；用 filter 过滤工具名/类名/命令名）")
        return "\n".join(lines)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 工具系统：命令对象的执行（REVERSE_NOTES.md §17.6）
#
# 一个 `CBindTargetDescriptor<T>::CBindableCommand` 分配 0x240 字节：
#   头 0x40：+0x00 vtable · +0x08 命令名 char* · +0x10 名字 hash(u32) · +0x18 描述 char*
#   之后 8 个 0x40 的块 = **8 个 stage** 的 `std::function`（stage k 在 +0x40*(k+1)）
#
# 每个 std::function（MSVC，functor 够小 → 内联在块里）：
#   +0x00 functor vtable   +0x08 成员函数指针   +0x10 this 调整(int)   +0x18 绑定实参(u32)
#   functor vtable 的槽 2（+0x10）= `_Do_call`，其实现为：
#       (*(fn+8))( *(arg0) + *(int*)(fn+16), *(u32*)(fn+24) )
#   —— 也就是 `(上下文对象->*pmf)(绑定实参)`。
#
# ⚠ 执行需要**上下文对象**（如 CToolSelection 实例 / CHammerApp 单例）。
#   我们直接调 pmf（等价于 `_Do_call`，当 adj==0 时），因此只要 ctx 的**值**，
#   不需要「指向 ctx 的指针」，全部参数都是整数 —— DLL 的调用桥不必支持 xmm。
# ---------------------------------------------------------------------------
CMD_OFF_NAME = 0x08
CMD_OFF_HASH = 0x10
CMD_OFF_DESC = 0x18
CMD_BLOCK_BASE = 0x40        # stage 0 的 std::function 块
CMD_BLOCK_STRIDE = 0x40
CMD_STAGE_COUNT = 8
# stage 语义（**实测归纳**，见 REVERSE_NOTES §17.13）：
#   5 = 一次性执行   —— 88/89 条 ToolSelection 命令、全部 76 条 HammerApp 菜单命令都只绑这一档
#   0 = 按下         —— 持续型交互命令的第一档（BoxSelect / MoveSelected / Nudge* / ToggleSnapping）
#   2 = 拖动         —— BoxSelect / LassoSelect / MoveSelected
#   3 = 长按连发     —— Nudge*（NudgeUp/Down/Left/Right、NudgeRotate*）
#   6 = 松开         —— 所有多段命令的收尾档（Nudge* 三层是 0/3/6，BoxSelect 是 0/2/6）
#   1/4/7 用途未定（1 从未出现；4/7 只在 `Select` 上出现）
CMD_STAGE_LABELS = {0: "press", 2: "drag", 3: "repeat", 5: "execute", 6: "release"}
# 自动选档的优先顺序：先「一次性执行」，再「按下」，再退到第一个
CMD_STAGE_AUTO_ORDER = (5, 0, 2, 3, 6, 4, 7, 1)
FN_VT_OFF_DOCALL = 0x10      # functor vtable 槽 2 = _Do_call
FN_OFF_PMF = 0x08
FN_OFF_ADJ = 0x10
FN_OFF_ARG = 0x18
# CHammerApp（ToolSystem2）**单例对象本体**：全局变量地址，首字段就是它的 vtable
RVA_CHAMMERAPP = 0x677AC80
APP_OFF_SESSION_COUNT = 0x58         # CHammerApp+0x58 = 编辑器会话 CUtlVector 计数
APP_OFF_SESSION_ARRAY = 0x60         # CHammerApp+0x60 = 会话数组
SESSION_OFF_TOOLMGR = 0x120          # 会话+0x120 = 工具管理器（CToolManager）
TOOLMGR_OFF_COUNT = 0x30             # 工具管理器+0x30 = 工具实例数
TOOLMGR_OFF_ARRAY = 0x38             # 工具管理器+0x38 = 工具实例数组
RTTI_COL_TO_TYPEDESC = 0xC           # MSVC COL+0xC = TypeDescriptor 的 RVA


def _rtti_class(obj: int) -> str:
    """用 MSVC RTTI 取对象的类名（返回如 `CToolSelection`；失败/非 RTTI 返回空串）。

    obj → vtable → `vtable[-8]` = CompleteObjectLocator → `COL+0xC`(u32) = TypeDescriptor 的 RVA
    → `td+0x10` = 修饰名（形如 `.?AVCToolSelection@@`）。
    """
    base = _hammer_base()
    try:
        vt = _read_int(obj, "u64")
        if not (base <= vt < base + 0x8000000):
            return ""
        col = _read_int(vt - 8, "u64")
        if not (base <= col < base + 0x8000000):
            return ""
        name = _read_string(base + _read_int(col + RTTI_COL_TO_TYPEDESC, "u32") + 0x10, 160)
    except Exception:  # noqa: BLE001
        return ""
    if name.startswith(".?AV"):
        name = name[4:].split("@@")[0]
    return name


def _tool_instances() -> list[tuple[str, int]]:
    """枚举当前会话的工具实例 -> [(类名, 实例地址)]（只读）。

    链路（2026-09-28 实测，见 REVERSE_NOTES §17.12）：
        CHammerApp+0x58/+0x60 = 编辑器会话数组
        会话+0x120            = CToolManager
        toolMgr+0x30/+0x38    = 工具实例数 / 数组
    每个工具实例的第一项是 vtable，可经 RTTI 读出类名（与描述符 `+0x18` 的类名对应）。
    """
    base = _hammer_base()
    app = base + RVA_CHAMMERAPP
    out: list[tuple[str, int]] = []
    try:
        cnt = _read_int(app + APP_OFF_SESSION_COUNT, "u32")
        arr = _read_int(app + APP_OFF_SESSION_ARRAY, "u64")
        if not arr or cnt <= 0 or cnt > 64:
            return out
        for i in range(cnt):
            sess = _read_int(arr + 8 * i, "u64")
            if not sess:
                continue
            mgr = _read_int(sess + SESSION_OFF_TOOLMGR, "u64")
            if not mgr:
                continue
            n = _read_int(mgr + TOOLMGR_OFF_COUNT, "u32")
            tools = _read_int(mgr + TOOLMGR_OFF_ARRAY, "u64")
            if not tools or n <= 0 or n > 256:
                continue
            for k in range(n):
                t = _read_int(tools + 8 * k, "u64")
                if t:
                    out.append((_rtti_class(t), t))
    except Exception:  # noqa: BLE001
        pass
    return out


def _bind_ctx(target: str, cls: str, ctx: str) -> tuple[int, str]:
    """解析执行用的「上下文对象」-> (`地址`, 说明)。

    优先 `ctx` 参数；否则按类名自动解析：
      · `CHammerApp`（全局菜单那批命令）→ CHammerApp 单例本体；
      · 其它工具类（`CToolSelection` 等）→ 会话里对应的**工具实例**（RTTI 类名匹配）。
    """
    raw = (ctx or "").strip()
    if raw:
        return int(raw, 0), "由 ctx 参数指定"
    base = _hammer_base()
    want = (cls or "").strip()
    if want == "CHammerApp" or (target or "").strip().lower() == "hammerapp":
        return base + RVA_CHAMMERAPP, "CHammerApp 全局单例"
    if want:
        for name, addr in _tool_instances():
            if name == want:
                return addr, f"{want} 工具实例（RTTI 匹配）"
    return 0, ""


def _bind_targets() -> list[tuple[int, str, str]]:
    """遍历描述符全局链表 -> [(desc 指针, 目标名, 实现类名)]（只读）。"""
    base = _hammer_base()
    out: list[tuple[int, str, str]] = []
    node = _read_int(base + RVA_BIND_TARGET_LIST, "u64")
    seen = set()
    while node and node not in seen and len(out) < 1024:
        seen.add(node)
        out.append((node, _read_string(_vfn_ptr(node, BIND_VFN_NAME), 128),
                    _read_cptr(node, BIND_OFF_CLASS, 128)))
        node = _read_int(node + BIND_OFF_NEXT, "u64")
    return out


def _bind_find_target(name: str):
    """按目标名 / 实现类名（大小写不敏感）找描述符 -> (desc, 名, 类名) 或 None。"""
    want = (name or "").strip().lower()
    if not want:
        return None
    for desc, tname, cls in _bind_targets():
        if tname.lower() == want or (cls or "").lower() == want:
            return desc, tname, cls
    return None


def _bind_commands(desc: int) -> list[tuple[int, str, str]]:
    """列出一个描述符的命令 -> [(命令对象指针, 命令名, 描述)]。"""
    out = []
    n = _vfn_ptr(desc, BIND_VFN_CMD_COUNT)
    for i in range(max(0, min(int(n), 512))):
        cmd = _vfn_ptr(desc, BIND_VFN_CMD_AT, [i])
        cname = _read_cptr(cmd, CMD_OFF_NAME, 160)
        if cname:
            out.append((cmd, cname, _read_cptr(cmd, CMD_OFF_DESC, 200)))
    return out


def _bind_find_command(desc: int, name: str):
    """按命令名（大小写不敏感）找命令对象 -> (cmd, 名, 描述) 或 None。"""
    want = (name or "").strip().lower()
    for cmd, cname, cdesc in _bind_commands(desc):
        if cname.lower() == want:
            return cmd, cname, cdesc
    return None


def _bind_stage(cmd: int, stage: int) -> dict | None:
    """取某个 stage 上绑定的函数信息；该 stage 没绑返回 None（只读）。"""
    if not (0 <= stage < CMD_STAGE_COUNT):
        return None
    blk = cmd + CMD_BLOCK_BASE + CMD_BLOCK_STRIDE * stage
    try:
        vt = _read_int(blk, "u64")
        if not vt:
            return None
        do_call = _read_int(vt + FN_VT_OFF_DOCALL, "u64")
        base = _hammer_base()
        # 只有「vtable 槽 2 落在本模块代码区」才算真的绑了函数：
        # 空块的 +0x00 是堆里的残留指针，读出来的槽 2 不会落在代码区。
        if not (base <= do_call < base + 0x8000000):
            return None
        return {
            "stage": stage, "block": blk, "functor_vt": vt, "do_call": do_call,
            "pmf": _read_int(blk + FN_OFF_PMF, "u64"),
            "adj": _read_int(blk + FN_OFF_ADJ, "u32"),
            "arg": _read_int(blk + FN_OFF_ARG, "u32"),
        }
    except Exception:  # noqa: BLE001
        return None


def _bind_stages(cmd: int) -> list[dict]:
    """列出该命令**已绑函数**的全部 stage。"""
    return [s for s in (_bind_stage(cmd, k) for k in range(CMD_STAGE_COUNT)) if s]


def _fmt_stage(s: dict, base: int) -> str:
    return (f"stage{s['stage']}[{CMD_STAGE_LABELS.get(s['stage'], '?')}] "
            f"(+{CMD_BLOCK_BASE + CMD_BLOCK_STRIDE * s['stage']:#x}) "
            f"pmf=hammer+{s['pmf'] - base:#x} adj={s['adj']} 绑定实参={s['arg']}")


def _stage_index(stage) -> int:
    """把 `stage` 参数（整数 / `"press"` 之类名字 / 空）解析成 stage 下标；空 = -1（自动）。"""
    if stage is None or (isinstance(stage, str) and not stage.strip()):
        return -1
    if isinstance(stage, int):
        return stage
    t = str(stage).strip().lower()
    if t.lstrip("-").isdigit():
        return int(t)
    for idx, name in CMD_STAGE_LABELS.items():
        if name == t:
            return idx
    raise ValueError(f"未知 stage {stage!r}；可用名字: {sorted(set(CMD_STAGE_LABELS.values()))} 或 0-7")


def _pick_stage(allst: list[dict], stage: int) -> dict | None:
    """选要执行的 stage。stage < 0 = 自动：优先「一次性执行」，其次「按下」，再退到第一个。"""
    if stage >= 0:
        return next((x for x in allst if x["stage"] == stage), None)
    for want in CMD_STAGE_AUTO_ORDER:
        hit = next((x for x in allst if x["stage"] == want), None)
        if hit:
            return hit
    return allst[0]


@mcp.tool()
def cs2_bind_inspect(target: str = "", command: str = "") -> str:
    """（只读）看可绑定命令**实际绑了什么函数**、执行它需要哪个上下文对象。

    背景见 REVERSE_NOTES.md §17：Hammer 每个工具类在静态初始化时把
    `CBindTargetDescriptor<T>::CBindableCommand` 登记进全局链表（表头 `hammer+0x272D898`），
    每个命令对象里按 **stage** 存了最多 8 个 `std::function`。

    Args:
        target:  目标名（如 `HammerApp` / `ToolSelection`）；也可传实现类名。留空 = 列出全部目标。
        command: 命令名。留空 = 列出该目标下**所有已绑函数**的命令及其 stage。
    """
    base = _hammer_base()
    try:
        if not (target or "").strip():
            rows = []
            for desc, tname, cls in _bind_targets():
                cmds = _bind_commands(desc)
                bound = [c for c, _, _ in cmds if _bind_stages(c)]
                rows.append(f"  {tname or '(无名)':<28} 类={cls or '?':<28} "
                            f"命令 {len(cmds)} 条 / 其中 {len(bound)} 条绑了函数")
            tools = _tool_instances()
            trows = [f"  {name or '(未知)':<28} {addr:#x}" for name, addr in tools]
            return ("目标（共 %d 个）：\n%s\n\n"
                    "上下文对象（工具实例，共 %d 个）：\n%s\n\n"
                    "用 cs2_bind_inspect(target=...) 看某个目标；"
                    "用 cs2_bind_run(target=..., command=...) 执行。"
                    % (len(rows), "\n".join(rows), len(trows), "\n".join(trows)))

        found = _bind_find_target(target)
        if not found:
            return f"找不到目标 {target!r}。用 cs2_bind_list 看有哪些目标。"
        desc, tname, cls = found

        if not (command or "").strip():
            lines = [f"目标 {tname!r}  类={cls}  desc={desc:#x}"]
            for cmd, cname, cdesc in _bind_commands(desc):
                st = _bind_stages(cmd)
                if not st:
                    continue
                lines.append(f"\n· {cname}" + (f"  — {cdesc}" if cdesc else ""))
                lines.append(f"    cmd={cmd:#x} hash={_read_int(cmd + CMD_OFF_HASH, 'u32'):#x}")
                for s in st:
                    lines.append("    " + _fmt_stage(s, base))
            if len(lines) == 1:
                return f"目标 {tname!r} 下没有任何命令绑定函数。"
            return "\n".join(lines)

        fcmd = _bind_find_command(desc, command)
        if not fcmd:
            return f"目标 {tname!r} 下找不到命令 {command!r}。"
        cmd, cname, cdesc = fcmd
        st = _bind_stages(cmd)
        lines = [f"{tname}.{cname}   desc={desc:#x} cmd={cmd:#x}",
                 f"  名字 hash = {_read_int(cmd + CMD_OFF_HASH, 'u32'):#x}"
                 + (f"   描述: {cdesc}" if cdesc else "")]
        if not st:
            return "\n".join(lines + ["  该命令没绑任何 stage 函数（可能只是文档占位）。"])
        for s in st:
            lines.append("  " + _fmt_stage(s, base))
        ctx_addr, why = _bind_ctx(tname, cls, "")
        lines.append(f"  上下文对象: {ctx_addr:#x}（{why}）" if ctx_addr
                     else "  上下文对象: 未知（执行时要用 ctx= 显式给）")
        return "\n".join(lines)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


@mcp.tool()
def cs2_bind_run(target: str, command: str, stage: str = "", ctx: str = "",
                 arg: int = -1, confirm: bool = False) -> str:
    """执行一个 Hammer 可绑定命令（直接调它绑定的成员函数，等价 Ctrl+Z 之外的原生动作）。

    ⚠ 这是**真执行**：会走 Hammer 自己的工具方法（可能改选择集 / 视图 / 甚至开新地图）。
    先跑 `cs2_bind_inspect` 看清要调什么；真正执行必须显式 `confirm=True`。

    原理（REVERSE_NOTES §17.6）：命令对象的每个 stage 存一个 `std::function`，
    `_Do_call` 的语义是 `(上下文对象->*pmf)(绑定实参)`。我们直接调 pmf：
        pmf(ctx + adj, arg)
    全部参数是整数，所以 DLL 的调用桥无需支持 xmm。

    Args:
        target:  目标名（`HammerApp` / `ToolSelection` ...）。
        command: 命令名（`ToggleSnapping` / `ShrinkGizmo` ...）。
        stage:   要执行的 stage。可传数字 0-7，或名字 `press`/`drag`/`repeat`/`release`/`execute`。
                 **留空 = 自动**：优先 `execute`(5)，没有就 `press`(0)，再退到第一个已绑档。
                 持续型命令（`Nudge*` / `BoxSelect` 等）是分档的，需要「按住再松开」时手动传两次。
        ctx:     上下文对象地址（`0x...`）。留空 = 自动解析（`HammerApp` 走单例，其余按类名 RTTI 找工具实例）。
        arg:     覆盖绑定实参（整数）；默认 -1 = 用命令自带的。
        confirm: 必须为 True 才真的执行；否则只回显将要调用的内容。
    """
    base = _hammer_base()
    try:
        stage_idx = _stage_index(stage)
    except ValueError as e:
        return f"ERROR {e}"
    try:
        found = _bind_find_target(target)
        if not found:
            return f"找不到目标 {target!r}。"
        desc, tname, cls = found
        fcmd = _bind_find_command(desc, command)
        if not fcmd:
            return f"目标 {tname!r} 下找不到命令 {command!r}。"
        cmd, cname, _ = fcmd

        allst = _bind_stages(cmd)
        if not allst:
            return f"{tname}.{cname} 没绑任何 stage 函数，无法执行。"
        s = _pick_stage(allst, stage_idx)
        if not s:
            return (f"{tname}.{cname} 在 stage={stage_idx} 没绑函数；"
                    f"可用 stage: {[x['stage'] for x in allst]}")

        ctx_addr, why = _bind_ctx(tname, cls, ctx)
        if not ctx_addr:
            return (f"{tname}.{cname} 需要「上下文对象」地址，但没有可自动解析的来源。\n"
                    f"请用 ctx='0x...' 指定（例如该工具类的实例地址）。\n"
                    f"可用 stage: {[x['stage'] for x in allst]}")
        obj = ctx_addr + s["adj"]
        real_arg = s["arg"] if arg < 0 else int(arg)

        plan = (f"{tname}.{cname}  stage={s['stage']}"
                f"[{CMD_STAGE_LABELS.get(s['stage'], '?')}]  pmf=hammer+{s['pmf'] - base:#x}\n"
                f"  将调用 pmf(this={obj:#x}, arg={real_arg})   "
                f"[_Do_call=hammer+{s['do_call'] - base:#x}  ctx={ctx_addr:#x} ({why}) adj={s['adj']}]")
        if not confirm:
            return plan + "\n（confirm=False：只回显，未执行。确认无误后传 confirm=True。）"

        ret_hex, err = _call_addr(s["pmf"], [obj, real_arg], timeout=30000)
        if err:
            return plan + f"\n❌ 调用失败: {err}"
        return plan + f"\n✅ 已执行  返回值={ret_hex or '0x0'}"
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


# 语义名 -> (目标, 命令名)。全部落在 ToolSelection 上，就是 Key Bindings 里
# `Context = ToolSelection` 那批原生命令（名字取自 cs2_bind_list 的实测输出）。
_SEL_FEATURES = {
    # 选择
    "select": ("ToolSelection", "Select"),
    "box_select": ("ToolSelection", "BoxSelect"),
    "lasso_select": ("ToolSelection", "LassoSelect"),
    "select_next": ("ToolSelection", "SelectNext"),
    "select_prev": ("ToolSelection", "SelectPrev"),
    "add_to_selection": ("ToolSelection", "AddObjectToSelection"),
    "remove_from_selection": ("ToolSelection", "RemoveObjectFromSelection"),
    "grow": ("ToolSelection", "GrowSelection"),
    "shrink": ("ToolSelection", "ShrinkSelection"),
    "activate": ("ToolSelection", "ActivateObject"),
    "show_properties": ("ToolSelection", "ShowObjectProperties"),
    "cancel": ("ToolSelection", "CancelSelectOperation"),
    # 吸附开关
    "toggle_snapping": ("ToolSelection", "ToggleSnapping"),
    "toggle_align_to_surface": ("ToolSelection", "ToggleAlignToSurface"),
    # 原点 / 朝向
    "origin_to_pivot": ("ToolSelection", "SetOriginToPivot"),
    "origin_to_center": ("ToolSelection", "SetOriginToCenter"),
    "orientation_to_world": ("ToolSelection", "SetOrientationToWorld"),
    "clear_rotation_scale": ("ToolSelection", "ClearRotationAndScale"),
    "bake_transform": ("ToolSelection", "BakeTransform"),
    # 对齐 / 吸附到对象
    "align_to_object": ("ToolSelection", "AlignOriginToObject"),
    "align": ("ToolSelection", "AlignObjects"),
    "align_rotation": ("ToolSelection", "AlignObjectsRotation"),
    "align_to_workplane": ("ToolSelection", "AlignObjectsToWorkplane"),
    "align_workplane_to_object": ("ToolSelection", "AlignWorkplaneToObject"),
    "snap_to_object": ("ToolSelection", "SnapToObject"),
    "snap_position_to_object": ("ToolSelection", "SnapToObjectPosition"),
    # 钉住
    "pin": ("ToolSelection", "PinToObject"),
    "pin_selected": ("ToolSelection", "PinSelectedObjects"),
    "unpin": ("ToolSelection", "UnpinSelectedObjects"),
    "clear_pin_offset": ("ToolSelection", "ClearPinOffset"),
    "move_down_by_trace": ("ToolSelection", "MoveObjectDownByTrace"),
    # 枢轴
    "pivot_clear": ("ToolSelection", "ClearPivot"),
    "pivot_to_selection_center": ("ToolSelection", "SetPivotToSelectionCenter"),
    "pivot_to_world_origin": ("ToolSelection", "SetPivotToWorldOrigin"),
    "pivot_next": ("ToolSelection", "NextPivotCycle"),
    "pivot_prev": ("ToolSelection", "PrevPivotCycle"),
    "pivot_center_in_view": ("ToolSelection", "CenterPivotInView"),
    "pivot_end_manipulation": ("ToolSelection", "EndPivotManipulation"),
    # Gizmo
    "gizmo_enlarge": ("ToolSelection", "EnlargeGizmo"),
    "gizmo_shrink": ("ToolSelection", "ShrinkGizmo"),
    "gizmo_apply": ("ToolSelection", "GizmoApplyValue"),
    "gizmo_clear": ("ToolSelection", "GizmoClearValue"),
    "local_offset_update": ("ToolSelection", "UpdateLocalOffset"),
    "local_offset_reposition": ("ToolSelection", "RepositionToMatchLocalOffset"),
    # Nudge（也可用 cs2_sel("nudge", direction=...)）
    "nudge_left": ("ToolSelection", "NudgeLeft"),
    "nudge_right": ("ToolSelection", "NudgeRight"),
    "nudge_up": ("ToolSelection", "NudgeUp"),
    "nudge_down": ("ToolSelection", "NudgeDown"),
    "nudge_rotate_left": ("ToolSelection", "NudgeRotateLeft"),
    "nudge_rotate_right": ("ToolSelection", "NudgeRotateRight"),
    "nudge_rotate_up": ("ToolSelection", "NudgeRotateUp"),
    "nudge_rotate_down": ("ToolSelection", "NudgeRotateDown"),
    # 网格编辑
    "flip_normals": ("ToolSelection", "FlipNormals"),
    "merge": ("ToolSelection", "MergeSelectedMeshes"),
    "merge_by_edge": ("ToolSelection", "MergeMeshesByEdge"),
    "separate": ("ToolSelection", "SeparateMeshComponents"),
    "bake_deformers": ("ToolSelection", "BakeMeshDeformers"),
    "toggle_deformation": ("ToolSelection", "ToggleDeformation"),
    "hide": ("ToolSelection", "HideElement"),
    "replace_with_instance": ("ToolSelection", "ReplaceSelectionWithInstance"),
    "replace_with_smartprop": ("ToolSelection", "ReplaceSelectedWithSmartProp"),
}
_SEL_NUDGE_DIRS = {"left": "Left", "right": "Right", "up": "Up", "down": "Down"}


@mcp.tool()
def cs2_sel(feature: str, direction: str = "", stage: str = "", confirm: bool = False) -> str:
    """按**语义名**执行选择工具的常用动作（= `cs2_bind_run("ToolSelection", 对应命令)`）。

    这些就是 Key Bindings 里 `Context = ToolSelection` 那批原生命令（截图里那些
    「对齐 / 吸附 / 钉住 / 枢轴 / Nudge」），执行时自动解析到当前 `CToolSelection` 实例。

    ⚠ 真执行。默认 `confirm=False` 只回显；改选择集/几何的命令会进 Ctrl+Z，
    纯视图/枢轴命令不进（见 REVERSE_NOTES §17.12）。多数「对齐/钉住/Nudge」需要**先选中对象**，
    否则是空操作。

    Args:
        feature:  语义名，见下（不传对的值会回显全部可用名）。
        direction: 仅 `nudge` / `nudge_rotate` 用，取 `left`/`right`/`up`/`down`。
        stage:    透传给 `cs2_bind_run`；留空 = 自动（`execute` → `press`）。
        confirm:  必须 True 才真执行。
    """
    key = (feature or "").strip().lower()
    if key in ("nudge", "nudge_rotate"):
        d = (direction or "").strip().lower()
        if d not in _SEL_NUDGE_DIRS:
            return f"{key} 需要 direction ∈ {sorted(_SEL_NUDGE_DIRS)}（收到 {direction!r}）。"
        key = f"{key}_{d}"
    hit = _SEL_FEATURES.get(key)
    if not hit:
        lines = "\n".join(f"    {k:<32} -> {t}.{c}" for k, (t, c) in sorted(_SEL_FEATURES.items()))
        return (f"未知 feature {feature!r}。可用：\n{lines}\n"
                f"    nudge / nudge_rotate{' ' * 13}-> 需再给 direction ∈ {sorted(_SEL_NUDGE_DIRS)}")
    target, command = hit
    return (f"[cs2_sel {key} -> {target}.{command}]\n"
            + cs2_bind_run(target=target, command=command, stage=stage, confirm=confirm))


@mcp.tool()
def cs2_area_query(min: str = "", max: str = "", kinds: str = "mesh,trigger,point",
                   limit: int = 200, doc: str = "") -> str:
    """按世界坐标范围(AABB)取地图内容 —— 大图别全量拉，只取盒子里的对象。

    `kinds` 逗号分隔，可取：
      mesh    : CMapMesh（手绘网格 / 贴花；材质里含 trigger 的会在行里标出来）
      trigger : 实体类名以 `trigger` 开头的（trigger_multiple 等）；也含材质带 trigger 的 mesh
      point   : 其余实体（info_* / point_* / env_* / light 等「点实体」）
      brush   : 实体类名以 `func_` 开头的（func_brush / func_movelinear 等「笔刷实体」）

    坐标轴同游戏（x/y 水平、z 朝上），单位同 Hammer，闭区间相交。
    精度：mesh 范围优先用元素缓存 AABB（`el+0x118`，实测手绘 mesh 与顶点算出来的一致）；
    缓存非法或某轴被压成 0 宽时（单面 / 带旋转的 mesh）会与「顶点+origin」算出的范围取并集
    —— 宁可外扩不漏。少数地图自带 tile mesh 两种来源不在同一参照系（REVERSE_NOTES §13.6），
    所以范围只当「大致范围」，精确几何仍用 cs2_mesh_get_geometry。实体按 `+0xA0` origin 判点。

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
            # 实体：先按 origin 粗筛，命中才查类名/目标名
            ent_total += 1
            try:
                origin = _read_vec3(el + ENTITY_OFF_ORIGIN)
            except Exception:  # noqa: BLE001
                continue
            if not _point_hits(origin, qmin, qmax):
                continue
            try:
                attrs = _entity_get_attrs(el, ("classname", ENTITY_TARGETNAME_ATTR))
            except Exception:  # noqa: BLE001
                attrs = {}
            cls = attrs.get("classname") or "?"
            kind = ("trigger" if cls.startswith("trigger")
                    else "brush" if cls.startswith("func_") else "point")
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


@mcp.tool()
def cs2_mesh_list(limit: int = 100, doc: str = "") -> str:
    """列出地图里的 CMapMesh（Hammer 手绘网格 / 贴花 overlay）。

    走**世界树**（`_walk_elements`）按主虚表筛 `CMapMesh`（RVA 0x176B8E0）。
    旧版走 `_enum_elements`（元素表），会被它的 8192 截断坑到 —— ze_surf_easy
    实测只报 338 个，实际有 4124 个。走树只访问场景内元素且 vtable 顺带就有。
    坐标同样读 `+0xA0`（CMapMesh 也派生自 MapNode）。

    Args:
        limit: 最多返回多少条。
        doc: 目标地图文档（多文档**务必指定**）：留空 = 清单第一个；数字 = 索引；
             其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    try:
        base = _hammer_base()
        vt_mesh = base + RVA_CMAPMESH_VTABLE
        doc = _map_doc(doc)
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
        if not world:
            return "ERROR CMapDoc 里没有 CMapWorld（地图可能还没加载完）"
        table, cap = _dm_table()
        handle_of = _dm_handle_map(table, cap)
        rows = [(handle_of.get(el, -1), el)
                for el, vt in _walk_elements(world, table, cap) if vt == vt_mesh]
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    if not rows:
        return "地图里没有 CMapMesh（该图没有手绘网格 / 贴花）"
    lines = [f"CMapMesh 数: {len(rows)}"]
    for h, el in rows[:limit]:
        try:
            origin = _read_vec3(el + ENTITY_OFF_ORIGIN)
            origin_s = "(%.1f, %.1f, %.1f)" % origin
        except Exception:  # noqa: BLE001
            origin_s = "<读取失败>"
        # 运行时几何容器：CMapMesh+0x498 是内嵌 CHammerPolyMesh 的 vptr，
        # +0x560 才是指向该对象的实体指针
        poly_s = "-"
        try:
            p = _read_int(el + MESH_OFF_POLYMESH_BACKPTR, "u64")
            if p and _read_int(p, "u64") == base + RVA_CHAMMERPOLYMESH_VTABLE:
                poly_s = f"{p:#x}"
        except Exception:  # noqa: BLE001
            pass
        # 存档用 DMX 引用（编辑期通常无效）
        dmx = _dm_attr_element(el, MESH_ATTR_DATA)
        dmx_s = f"{dmx:#x}" if dmx else "INVALID(编辑期未生成)"
        lines.append(f"  handle={h:<5} mesh={el:#x}  origin={origin_s}")
        lines.append(f"        runtimePolyMesh(CHammerPolyMesh)={poly_s}   meshData(DMX)={dmx_s}")
    return "\n".join(lines)


@mcp.tool()
def cs2_mesh_get_geometry(mesh: str, max_faces: int = 16) -> str:
    """读 CMapMesh 的几何：顶点坐标 / 面顶点环 / 世界包围盒。

    编辑期 Hammer **不用** CDmePolygonMesh 存几何，真正在内存里的是
    `CMapMesh+0x498` 内嵌的 CHammerPolyMesh（半边缘 DCEL）。本工具优先直接读它
    （布局 2026-09-27 实证，见 REVERSE_NOTES.md §13）：
        poly+0x18 顶点池(32B/条)   {count@+0, ptr@+8}
        poly+0x50 半边池(80B/条)：+0=起点顶点 handle，+0x20=下一条半边 handle
        poly+0x88 面池(32B/条)：+0=首条半边 handle（低 22 位为索引）
        poly+0x30/0x68/0xA0 三张 handle->槽位 映射表（24B/条，句柄在 +8）
        poly+0x8D8 数据通道数组（24B/通道，ch0 通常是 position，12B/顶点）
        顶点记录 +0x10 = 位置通道数据下标；世界坐标 = 位置 + CMapMesh+0xA0(origin)
    面/半边属性同样读运行时结构（见 REVERSE_NOTES §13.8）：
        poly+0x1110 「密集序 -> 半边 handle」映射；texcoord/normal/tangent 按密集序排列
        poly+0x3118/0x3300/0x3318 每面 textureScale / textureAxisU / textureAxisV
        poly+0x33B8 每面 materialindex，索引 poly+0x3448 的 CUtlVector<CUtlString> 材料名表
    meshData 有效时（载入/导出场景）仍走 CDmePolygonMesh 分支。

    Args:
        mesh: CMapMesh 元素地址（cs2_mesh_list 给出）。
        max_faces: 最多输出多少个面的顶点环。
    """
    def _stream(da: int, semantic: str) -> tuple[int, int]:
        """在 DataArray 里找 semanticName==semantic 的流 -> (流元素, 分量数)。"""
        if not da:
            return 0, 0
        for h in _dm_array_handles(da, MESH_ATTR_STREAMS):
            st = _resolve_handle(h)
            if not st:
                continue
            a = _dm_find_attr(st, MESH_STREAM_ATTR_SEMANTIC)
            if a and _dm_attr_value(a) == semantic:
                return st, MESH_STREAM_COMPONENTS.get(semantic, 0)
        return 0, 0

    try:
        mesh_el = _parse_addr(mesh)
        poly = _dm_attr_element(mesh_el, MESH_ATTR_DATA)
        if not poly:
            return _mesh_geometry_runtime(mesh_el, max_faces)

        materials = _dm_array_strings(poly, MESH_ATTR_MATERIALS)
        vda = _dm_attr_element(poly, MESH_ATTR_VERTEX_DATA)
        fvda = _dm_attr_element(poly, MESH_ATTR_FACE_VERTEX_DATA)
        fda = _dm_attr_element(poly, MESH_ATTR_FACE_DATA)

        pos_st, pos_c = _stream(vda, "position")
        uv_st, uv_c = _stream(fvda, "texcoord")
        nrm_st, _ = _stream(fvda, "normal")
        mat_st, _ = _stream(fda, "materialindex")

        positions = _dm_array_numbers(pos_st, MESH_STREAM_ATTR_DATA, pos_c) if pos_st else []
        uvs = _dm_array_numbers(uv_st, MESH_STREAM_ATTR_DATA, uv_c) if uv_st else []
        normals = _dm_array_numbers(nrm_st, MESH_STREAM_ATTR_DATA, 3) if nrm_st else []
        mat_idx = _dm_array_numbers(mat_st, MESH_STREAM_ATTR_DATA, 1) if mat_st else []

        face_edge = _dm_array_numbers(poly, MESH_ATTR_FACE_EDGE_INDICES, 1)
        edge_next = _dm_array_numbers(poly, MESH_ATTR_EDGE_NEXT_INDICES, 1)
        edge_vert = _dm_array_numbers(poly, "edgeVertexIndices", 1)
        edge_vdata = _dm_array_numbers(poly, MESH_ATTR_EDGE_VERTEX_DATA_INDICES, 1)
        vert_data_idx = _dm_array_numbers(poly, "vertexDataIndices", 1)

        def v_pos(vertex_index: int):
            si = vert_data_idx[vertex_index] if vertex_index < len(vert_data_idx) else vertex_index
            o = si * pos_c
            if o + pos_c > len(positions):
                return None
            return tuple(positions[o:o + pos_c])

        def v_uv(half_edge: int):
            si = edge_vdata[half_edge] if half_edge < len(edge_vdata) else half_edge
            o = si * uv_c
            if not uv_c or o + uv_c > len(uvs):
                return None
            return tuple(uvs[o:o + uv_c])

        lines = [
            f"CMapMesh {mesh_el:#x}  meshData(CDmePolygonMesh)={poly:#x}",
            f"  顶点(position) {len(positions) // pos_c if pos_c else 0}   "
            f"半边 {len(edge_vert)}   face {len(face_edge)}   材质 {len(materials)}",
            f"  materials = {materials[:12]}",
            f"  materialindex = {mat_idx[:16]}",
        ]

        for f in range(min(len(face_edge), max_faces)):
            start = face_edge[f]
            loop: list[int] = []
            e = start
            for _ in range(256):
                loop.append(e)
                e = edge_next[e] if e < len(edge_next) else start
                if e == start or len(loop) > 255:
                    break
            verts = [edge_vert[e] if e < len(edge_vert) else -1 for e in loop]
            pts = [v_pos(v) for v in verts]
            uv = [v_uv(e) for e in loop]
            mat = materials[mat_idx[f]] if f < len(mat_idx) and 0 <= mat_idx[f] < len(materials) else "?"
            lines.append(f"  face[{f}] mat={mat!r} verts={verts}")
            for i in range(1, max(len(pts) - 1, 1)):
                tri = [pts[0], pts[i], pts[i + 1]] if len(pts) > i + 1 else []
                if tri and all(t is not None for t in tri):
                    lines.append("      tri " + "  ".join(
                        "(%.3f, %.3f, %.3f)" % t for t in tri))
            if uv and uv[0] is not None:
                lines.append("      uv " + "  ".join(
                    ("(%.4f, %.4f)" % t) if t else "<->" for t in uv))
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    return "\n".join(lines)


@mcp.tool()
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
        name: 元素 name。留空由 Hammer 自行命名。
        doc: 目标地图文档（多文档**务必指定**）：留空 = 清单第一个；数字 = 索引；
             其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    steps: list[str] = []
    add_err = ""
    try:
        doc = _map_doc(doc)   # 参数是文档选择器，这里换成 CMapDoc 地址
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
                return f"ERROR 建元素失败: {err}"
            steps.append(f"  CreateElement   ret = {ret}")
            handle = int(ret, 16) & 0xFFFFFFFF
            if handle == INVALID_DMX_HANDLE:
                return ("ERROR CDataModel::CreateElement 返回 0xFFFFFFFF（创建失败）："
                        "检查 hammer.dll 是否注册了 'CMapEntity' 元素工厂")
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
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    ok = ""
    if classname:
        ok = "  [类名已生效]" if cls == classname else f"  [读回 {cls!r}，与请求不一致]"
    mounted = "已挂进世界 ✅" if in_world and parent == world else \
        ("已在 world.children 里" if in_world else "❌ 未挂进世界")
    return (
        f"新建实体: handle = {handle:#x}  element = {ent:#x}{ok}\n"
        f"  name      = {name!r}\n"
        f"  classname = {cls!r}\n"
        f"  props     = {props:#x}\n"
        + "\n".join(steps) + "\n"
        f"  world {world:#x} 子节点数 {children_before} -> {children_after}  "
        f"父节点 = {parent:#x}  -> {mounted}\n"
        f"  undo: scope_committed={scope_committed}"
        + ("（本次顺带打开了 Datamodel undo 总开关）" if undo_was_off else "") + "\n"
        + hist_note
        + (f"\n  ⚠ AddChild 失败: {add_err}" if add_err else "")
    )


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def cs2_particle_set_definition(entity: str, vpcf: str) -> str:
    """给 info_particle_system 实体设置粒子定义（.vpcf 路径），全程底层调用。

    不使用任何 UI/快捷键，分两步：

      1) 写 `effect_name` 属性 —— 调 Hammer 自己的
         sub_18062C9A0(owner, "effect_name", vpcf, 1)，这是会被保存进 .vmap
         的权威字段，并触发文档通知；
      2) 立即生效 —— 在实体内存里定位 CParticleHelper，直接调
         `CParticleHelper::SetDefinitionByName(helper, vpcf)`（hammer.dll+0x7F5350），
         把解析好的定义指针写进 helper+0xB8。

    Args:
        entity: 实体地址（cs2_entity_list 给出）。
        vpcf: 粒子文件路径，如 'particles/environment/glow01.vpcf'。
    """
    if not vpcf.lower().endswith(".vpcf"):
        return f"vpcf 应以 .vpcf 结尾，收到 {vpcf!r}"

    try:
        ent = _parse_addr(entity)
        props = _entity_class_props(ent)
        cls = _dm_attr_value(_dm_find_attr(props, "classname")) if props else None
        if cls != PARTICLE_ENTITY_CLASS:
            return (f"实体 {ent:#x} 的类名是 {cls!r}，不是 {PARTICLE_ENTITY_CLASS!r}。\n"
                    f"  先执行：cs2_entity_set_classname('{ent:#x}', "
                    f"'{PARTICLE_ENTITY_CLASS}')")

        # --- 1) 写 effect_name 属性（文档级、可保存）---
        owner = props or ent
        undo_was_off = _ensure_undo_enabled()
        _undo_scope_begin("cs2 particle set definition")
        try:
            resp = _get_pipe().call("call_function", {
                "address": _hammer_addr(RVA_PROPS_SET_STRING_ATTR),
                "args": [owner, f"str:{PARTICLE_EFFECT_ATTR}", f"str:{vpcf}", 1],
                "on_main_thread": True,
                "timeout_ms": 15000,
            })
            if "error" in resp:
                return f"INJECTED_DLL_ERROR: {resp['error']}"
            result = resp["result"]
            status = result.get("main_thread_status", 0)
            if status != 0:
                return (f"ERROR 写 effect_name 主线程派发失败 (main_thread_status={status}): "
                        f"{MAIN_THREAD_STATUS_NAMES.get(status, '未知')}")
            attr_ret = result["ret_hex"]
        finally:
            scope_committed = _undo_scope_end()

        attr = _dm_find_attr(props, PARTICLE_EFFECT_ATTR) if props else 0
        if not attr:
            attr = _dm_find_attr(ent, PARTICLE_EFFECT_ATTR)
        attr_value = _dm_attr_value(attr) if attr else None

        # --- 2) 直接刷新 helper 的解析结果 ---
        helper = _find_particle_helper(ent)
        helper_lines: list[str] = []
        if helper:
            resp = _get_pipe().call("call_function", {
                "address": _hammer_addr(RVA_PARTICLE_SET_DEFINITION),
                "args": [helper, f"str:{vpcf}"],
                "on_main_thread": True,
                "timeout_ms": 15000,
            })
            if "error" in resp:
                helper_lines.append(f"  SetDefinitionByName 失败: {resp['error']}")
            else:
                hres = resp["result"]
                hstatus = hres.get("main_thread_status", 0)
                if hstatus != 0:
                    helper_lines.append(
                        "  SetDefinitionByName 主线程派发失败 "
                        f"(main_thread_status={hstatus}): "
                        f"{MAIN_THREAD_STATUS_NAMES.get(hstatus, '未知')}")
                else:
                    try:
                        definition = _read_int(helper + OFF_HELPER_DEFINITION, "u64")
                        hname = _read_int(helper + OFF_HELPER_EFFECT_NAME, "u64")
                        hname_s = _read_string(hname, 512) if hname else ""
                    except Exception:  # noqa: BLE001
                        definition, hname_s = 0, ""
                    helper_lines.append(
                        f"  helper = {helper:#x}  SetDefinitionByName ret = {hres['ret_hex']}")
                    helper_lines.append(
                        f"  helper+0xB8 定义指针 = {definition:#x}"
                        + ("" if definition else "  (0 = 名字没解析出定义，检查 vpcf 路径)"))
                    helper_lines.append(f"  helper+0xB0 effect_name = {hname_s!r}")
        else:
            helper_lines.append(
                "  未在实体内存里找到 CParticleHelper（可能尚未创建）。"
                "effect_name 属性已写入，Hammer 会在下一次刷新时创建 helper 并解析定义；"
                "稍后重跑本工具即可看到 helper+0xB8。")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    ok = "已生效" if attr_value == vpcf else "读回值不一致"
    return "\n".join([
        f"设置 {PARTICLE_EFFECT_ATTR} = {vpcf!r}  [{ok}]",
        f"  entity = {ent:#x}  owner = {owner:#x}  attr = {attr:#x}",
        f"  undo: scope_committed={scope_committed}"
        + ("（本次顺带打开了 Datamodel undo 总开关）" if undo_was_off else ""),
        f"  SetStringAttr ret = {attr_ret}",
        *helper_lines,
    ])


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
