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
# g_CDataModel 是静态内嵌对象（位于 hammer.dll+0x24B7C80）；
# hammer.dll+0x21B2B68 (off_1821B2B68) 处的 qword 也指向同一对象。
RVA_CDATAMODEL_GLOBAL = 0x24B7C80   # CDataModel 全局单例（静态初始化 sub_18004F890）
RVA_CDATAMODEL_PTR_GLOBAL = 0x21B2B68  # qword 指针，值 = base+0x24B7C80
RVA_CDATAMODEL_VTABLE = 0x16C25C8   # 用于运行前校验
UNDO_MANAGER_OFFSET = 240           # CUndoManager 内嵌在 CDataModel + 240（不变）
RVA_CDATAMODEL_UNDO = 0x5C3160      # 带 UI 通知(vfn+1040)的包装
RVA_CDATAMODEL_REDO = 0x5C11E0
RVA_UNDO_MANAGER_UNDO = 0x60F8D0    # CUndoManager::Undo 本体（带 profile）
RVA_UNDO_MANAGER_REDO = 0x60F440    # CUndoManager::Redo 本体
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


def _read_int(address: int, type_: str) -> int:
    resp = _get_pipe().call("read_value", {"address": address, "type": type_})
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp["result"]["value"]


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
RVA_MAP_HISTORY_POP = 0x1529E80
# Pop 最外层那个全局开关（旧版 byte_1820F2088，新版 byte_18221A418）
RVA_MAP_HISTORY_GATE = 0x221A418

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


def _map_undo_redo(action: str) -> str:
    try:
        undo_h, redo_h = _find_map_histories()
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
def cs2_map_undo() -> str:
    """撤销**地图编辑**的上一步操作（真正的 Hammer 撤销，非 Datamodel）。

    走 `CMapDocHistory::Pop`（新版 RVA `0x1529E80`，见 REVERSE_NOTES §15），
    撤销/重做共用该函数，靠传入的历史对象区分（`CMapRootElement+0x240` 撤销 /
    `+0x248` 重做）。空栈时会提前拒绝（函数内部也有 CanUndo 守卫）。
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
def cs2_map_save() -> str:
    """保存当前地图（直接调用 Hammer 底层保存函数，不依赖 UI / 菜单）。

    走 `sub_1801639B0`（per-document save），语义等价于 Hammer 的 File→Save：
    `a4=1` 强制保存，不要求文档处于「已修改」状态；`a3=0` 保持与交互式保存
    一致的检查流程，但**不会**走外层那段会阻塞主线程的「编辑会话布局」保存。

    地图必须已有真实文件路径（`CMapDoc+0x6A0`）。&New 出来的地图只有内存虚拟
    路径，请先 &Open 一张已有 .vmap，或手动另存为。
    """
    try:
        doc = _map_doc()
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
CMAPDOC_WORLD_OFFSET = 0x88         # CMapDoc -> CMapWorld*（136，旧版同偏移）

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
# 类型码 -> 名字（`attr+0x1C` 低 6 位）。证据见 REVERSE_NOTES.md §14.2：
# 5/8/10 由对应 setter 的 CUndoAttributeSetValueElement<T> 实例反查，
# 1/2/3/4/7 由 sub_1805CE490（int 写入器）的接受分支反查，33/37 由活体属性枚举。
DM_ATTR_TYPE_NAMES = {
    DM_ATTR_TYPE_STRING: "string",
    1: "element_handle",
    2: "int", 3: "int", 4: "int", 7: "int",
    8: "color",
    10: "vec3",
    33: "element_array",
    37: "string_array",
}
# CDmElement::MarkDirty(this, flags)（sub_1805C81C0）：把标志或进 element+0x5E/+0x60
# 并递归通知依赖者。摘掉属性后用它传播脏状态。
RVA_ELEMENT_MARK_DIRTY = 0x5C81C0

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
RVA_ATTR_SET_SYMBOL = 0x5CF020
# 更高层、更安全的按名写字符串属性：
#   sub_18062C9A0(ownerElement, const char* name, const char* value, bool createIfMissing)
# 内部自行 intern，并在属性缺失时以类型 5(AT_STRING) 创建。Drop/快照等内置逻辑均走它。
RVA_PROPS_SET_STRING_ATTR = 0x62C9A0
# 按名取属性（返回 CDmAttribute*），签名 (ownerElement, const char* name)
RVA_PROPS_FIND_ATTR = 0x5C7170
# 按名写**实体 keyvalue**（推荐入口，比上面那个更高层）：
#   sub_18083E0D0(entity, const char* name, const char* value)
# 属性缺失时以类型 5(AT_STRING) 创建；值变化后还会调 CMapEntity 的类回调
# (vfn+2136)、targetname 名字索引(vfn+1272/2160) 与包围盒/脏通知
# (sub_1808672E0/sub_180867040)。⚠ origin/angles/scales 不走这里（见下）。
RVA_ENTITY_SET_KEYVALUE = 0x83E0D0
# 按名写**实体属性表属性**（含变换），签名 (entity, const char* name, const char* value, uint flags)：
#   sub_18086B550 取实体的 CMapNode 属性表，按属性声明类型分派 —— 变换类属性由
#   CMapNodeTransformPin 直接落到 CMapEntity 的原生 Vec3D 成员（+0xA0/+0xAC/+0xB8），
#   普通 keyvalue 仍写 CEditGameClassProps。属性不存在时返回 0（不创建）。
RVA_ENTITY_SET_NODE_ATTR = 0x86B550
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
RVA_NODE_POST_CLASS = 0x866D70     # sub_180866D70(node, flag)
RVA_NODE_ADD_CHILD = 0x879170      # sub_180879170(doc, child, siblingOr0)
RVA_NODE_GET_PARENT = 0x864EA0     # sub_180864EA0(node) -> 父节点（实测：func_brush 的父就是 CMapWorld）
RVA_NODE_GET_ROOT = 0x864EB0       # sub_180864EB0(node) -> 根/世界（实测全部实体都指向 CMapWorld）
# CParticleHelper::SetDefinitionByName(this, const char* vpcfPath)
RVA_PARTICLE_SET_DEFINITION = 0x7F5350
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
RVA_ENTITY_ADD_CONN = 0x986EA0
# KV3 值初始化：sub_1813E79E0(this, 1, 8)（Hammer 的 Conn::Conn 内部同款调用）
RVA_CONN_VALUE_INIT = 0x13E79E0

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
RVA_CDMEPOLYGONMESH_VTABLE = 0x1D70620
# mesh 顶点坐标写入：sub_1809B8880(element, CUtlVector<顶点handle>*, CUtlVector<Vector>*)
#   内部 = 取元素变换(vfn+160 → 48B 矩阵) → sub_180BFA650 转成存储空间 → sub_180CDC6E0
#   sub_180CDC6E0(poly, handles, transform, positions) 是 CPolygonMesh 的官方算子
#   "SetVertexPositions"（开事务/写位置通道/更新缓存/发脏通知），见 REVERSE_NOTES §13.10
RVA_MESH_SET_VERTEX_POSITIONS = 0x9B8880
# CPolygonMesh 本体的算子（元素级包装就是调它）：(poly, handles, 3x4矩阵, positions)
# 传单位矩阵 = 直接把 positions 原样写进位置通道（不改参照系）
RVA_POLY_SET_VERTEX_POSITIONS = 0xCDC6E0
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
RVA_DATAMODEL_CREATE_ELEMENT = 0x5BBB90
RVA_ELEMENT_CREATE_CORE = 0x5BB7F0   # sub_1805BB7F0（内部，最终调工厂 Create）
# CMapEntity 元素工厂对象 RVA / 其虚表 RVA（slot0 = Create = 0x898D10）
RVA_CMAPENTITY_FACTORY = 0x21DB400
RVA_CMAPENTITY_FACTORY_VTABLE = 0x1765170
ENTITY_DMX_TYPE = "CMapEntity"       # 实体在 .vmap 里的元素类型名
ENTITY_CREATE_FLAGS = 1              # 与实体工具一致；!= -1 时登记 CUndoCreateElement 撤销步
INVALID_DMX_HANDLE = 0xFFFFFFFF

# --- Datamodel undo scope（新版反编译实测）---
# BeginUndoScope: "[%d] Pushing undo '%s'" 在 0x1816C7ED0 -> 0x60F370
# EndUndoScope(um, bool abort): 自减 scope 深度(+88) -> 0x60F1C0
RVA_UNDO_SCOPE_BEGIN = 0x60F370     # CUndoManager::BeginUndoScope(um, name, desc, flags)
RVA_UNDO_SCOPE_END = 0x60F1C0       # CUndoManager::EndUndoScope(um, bool abort=0)
UNDO_MGR_OFF_SCOPE_DEPTH = 88       # +0x58（新版；旧版在 +84）
UNDO_MGR_OFF_FLAGS = 132            # +0x84 bit3 = undo 总开关（不变）
UNDO_MGR_FLAG_ENABLED = 0x08


def _parse_addr(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(value, 0)


def _map_doc() -> int:
    """取当前活动 CMapDoc。

    枚举在 DLL 侧完成（app->session 数组->+0x138 wrapper->内嵌 +0x10），
    这里直接用 map_list_docs IPC 的第一个结果。
    """
    resp = _get_pipe().call("map_list_docs", {})
    if "error" in resp:
        raise RuntimeError(resp["error"])
    docs = resp["result"].get("docs", [])
    if not docs:
        raise RuntimeError("当前没有打开的地图文档")
    return int(docs[0]["address"], 16)


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

    缓存以 (base, 数据指针, 容量) 作键，换图/进程重启会自动重读。
    """
    global _DM_TABLE, _DM_TABLE_KEY
    base = _hammer_base()
    dm = base + RVA_CDATAMODEL_GLOBAL
    arr = _read_int(dm + 0x90, "u64")
    cap = _read_int(dm + 0x88, "u32")
    key = (base, arr, cap)
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


def _dm_find_attrs(element: int, names) -> dict[str, tuple[int, int, int]]:
    """一次遍历属性链，收集 names 里命中的属性 -> {name: (attr, 类型码, 值指针)}。

    **块读优化**：CDmAttribute 对象按 0x30 步长连续分配（实测同一元素的链上
    相邻节点地址差恒为 48，偶有跳跃），所以一次 1024 字节读能覆盖 ~21 个节点，
    只在遇到断点时补读下一块 —— 整条链的读取次数从「每节点一次」降到「每块一次」。
    名字走驻留串缓存（命中零额外读取）。找齐 names 即提前结束。
    """
    want = set(names)
    found: dict[str, tuple[int, int, int]] = {}
    hdr_len = ATTR_OFF_NAME + 8
    try:
        attr = _read_int(element + ELEMENT_OFF_ATTR_HEAD, "u64")
    except Exception:  # noqa: BLE001
        return found
    blk_addr, blk = 0, b""
    for _ in range(512):
        if not attr or attr < 0x10000 or not want:
            break
        if not (blk_addr and blk_addr <= attr and attr + hdr_len <= blk_addr + len(blk)):
            blk_addr = attr
            try:
                blk = _read_bytes(attr, MAX_READ_CHUNK)
            except Exception:  # noqa: BLE001
                try:  # 块尾可能压到未映射页，退回只读一个节点头
                    blk = _read_bytes(attr, hdr_len)
                except Exception:  # noqa: BLE001
                    break
        off = attr - blk_addr
        nameptr = int.from_bytes(blk[off + ATTR_OFF_NAME:off + ATTR_OFF_NAME + 8], "little")
        if nameptr >= 0x10000:
            nm = _dm_read_name(nameptr)
            if nm in want:
                found[nm] = (
                    attr,
                    blk[off + ATTR_OFF_TYPE] & 0x3F,
                    int.from_bytes(blk[off + ATTR_OFF_VALUE:off + ATTR_OFF_VALUE + 8], "little"),
                )
                want.discard(nm)
        attr = int.from_bytes(blk[off + ATTR_OFF_NEXT:off + ATTR_OFF_NEXT + 8], "little")
    return found


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

    5=string -> str；8=color / 1,2,3,4,7=int -> int；10=vec3 -> (x,y,z)；
    33=元素句柄数组 -> list[int]；37=字符串数组 -> list[str]；
    其余类型返回 '<type=N 原始 …>' 形式的原样十六进制（不做猜测）。
    """
    if not valptr:
        return None
    if atype == DM_ATTR_TYPE_STRING:
        cp = _read_int(valptr, "u64")  # 字符串：[值存储] = char*
        return _read_string(cp, 2048) if cp else ""
    if atype in (1, 2, 3, 4, 7, 8):    # 句柄 / 整数族 / 颜色：内联 32 位
        return _read_int(valptr, "u32")
    if atype == 10:                    # Vec3D<float>：内联 12 字节
        return struct.unpack("<3f", _read_bytes(valptr, 12))
    if atype in (33, 37):              # 数组：值存储里是 CUtlVector 头
        size = _read_int(valptr + ARR_OFF_SIZE, "u32")
        data = _read_int(valptr + ARR_OFF_DATA, "u64")
        if not size or not data or size > 100000:
            return []
        if atype == 33:
            return list(struct.unpack(f"<{size}I", _read_bytes(data, 4 * size)))
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


def _enum_elements(limit: int = 8192):
    """枚举 datamodel 元素表（dm+0x90，16 字节一项，句柄=下标）-> (handle, element, vtable)。

    比走世界树可靠：能看到不在 children 树里的元素（如我们新建的）。
    """
    base = _hammer_base()
    dm = base + RVA_CDATAMODEL_GLOBAL
    arr = _read_int(dm + 0x90, "u64")
    cap = _read_int(dm + 0x88, "u32")
    if not arr:
        return
    for i in range(min(cap, limit)):
        el = _read_int(arr + 16 * i + 8, "u64")
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


def list_entities(limit: int = 200) -> tuple[list[tuple[int, Any, Any, Any]], int, int, int]:
    """返回 (rows[(entity, classname, targetname, origin)], 场景元素总数, doc, world, 实体数)。"""
    doc = _map_doc()
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

    rows: list[tuple[int, Any, Any, Any]] = []
    for ent in ents[:limit]:
        try:
            attrs = _entity_get_attrs(ent, ("classname", ENTITY_TARGETNAME_ATTR))
        except Exception:  # noqa: BLE001
            attrs = {}
        try:
            origin = _read_vec3(ent + ENTITY_OFF_ORIGIN)
        except Exception:  # noqa: BLE001
            origin = None
        rows.append((ent, attrs.get("classname"), attrs.get(ENTITY_TARGETNAME_ATTR), origin))
    return rows, total, doc, world, len(ents)


@mcp.tool()
def cs2_entity_list(limit: int = 200) -> str:
    """列出当前地图的所有实体（类名 + 目标名 + 世界坐标 + 地址）。

    纯内存读取（2026-09 新版，见 REVERSE_NOTES.md §3 / §11.9 / §15.6）：
      CMapDoc+0x88 -> CMapWorld；节点 +0x1F8 子节点数 / +0x200 句柄数组，
      句柄经 **CDataModel 元素表直查**（+0x90 数据 / +0x88 容量，16B/项）解析为元素
      （不再每个句柄一次主线程 vfn168）；按 vtable==CMapEntity 筛实体；
      classname/targetname 经 entity_properties -> CEditGameClassProps **一次遍历**读取；
      **坐标是 CMapEntity 原生 Vec3D 成员 @ +0xA0**（不在 DMX 属性里）。

    Args:
        limit: 最多返回多少条。
    """
    try:
        rows, total, doc, world, ent_total = list_entities(limit)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    head = (f"实体数: {ent_total}（场景元素总数 {total}，"
            f"CMapDoc={doc:#x}, CMapWorld={world:#x}）")
    if not rows:
        return head
    lines = [head, ""]
    for n, (ent, cls, tname, origin) in enumerate(rows):
        label = cls or "?"
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
def cs2_entity_set_attr(entity: str, name: str, value: str) -> str:
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
                      global_relay: bool = False, source: str = "") -> str:
    """给实体追加一条 IO 连接（等价 Hammer Outputs 页的 Add）。

    直接调用 Hammer 自己的追加函数 `sub_180986EA0(entity, outHandle, const Conn*)`
    —— 与 Outputs 面板粘贴链路（sub_18020D240）完全同一条代码，扩容/字符串深拷贝/
    唯一 id 都由 Hammer 处理，不绕过文档逻辑。

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
    """
    try:
        ent = _parse_addr(entity)
        before = _read_int(ent + ENTITY_OFF_CONN_COUNT, "u32")
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
                    f"   (连接数 {before} -> {after})")
        return (f"⚠ 追加调用已发出，但连接数未按预期变化：{before} -> {after}"
                f"（outHandle 缓冲区 {outbuf:#x}）")
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


@mcp.tool()
def cs2_entity_remove_io(entity: str, index: int) -> str:
    """删除实体的一条 IO 连接（等价 Hammer Outputs 页的 Delete）。

    做法：把 index 之后的记录整体前移 80 字节，再把计数减一。
    ⚠ 被删记录自身的 CUtlString 内存不回收（Hammer 的 FreeMemoryBlock 是延迟导入，
    没有稳定 RVA）—— 只泄漏几十字节，不会破坏 Hammer 状态。

    Args:
        entity: 实体地址。
        index: 连接下标（cs2_entity_get_io 输出里的 [i]）。
    """
    try:
        ent = _parse_addr(entity)
        count = _read_int(ent + ENTITY_OFF_CONN_COUNT, "u32")
        data = _read_int(ent + ENTITY_OFF_CONN_DATA, "u64")
        if not (0 <= index < count) or not _plausible_ptr(data):
            return f"ERROR 下标越界：{index}（当前 {count} 条）"
        if index < count - 1:
            tail = _read_bytes(data + CONN_STRIDE * (index + 1),
                               CONN_STRIDE * (count - index - 1))
            _write_mem(data + CONN_STRIDE * index, tail)
        _write_mem(ent + ENTITY_OFF_CONN_COUNT, struct.pack("<I", count - 1))
        return f"已删除 IO 连接 [{index}]，连接数 {count} -> {count - 1}"
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


@mcp.tool()
def cs2_area_query(min: str = "", max: str = "", kinds: str = "mesh,trigger,point",
                   limit: int = 200) -> str:
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

    # ---- mesh：先按 AABB 粗筛（每次 1 次读），命中才读顶点数/面数/材质 ----
    mesh_hits: list[tuple[int, int]] = []
    mesh_total = 0
    for h, el, vt in _enum_elements():
        if vt != vt_mesh:
            continue
        mesh_total += 1
        if "mesh" not in want and "trigger" not in want:
            continue
        poly = _poly_ready(el)
        if not poly:
            continue
        try:
            box = _mesh_world_box(el, poly)[0]
        except Exception:  # noqa: BLE001
            continue
        if box and _box_hits(box, qmin, qmax):
            mesh_hits.append((h, el))

    # ---- 实体：先按 origin 粗筛，命中才查类名/目标名 ----
    ent_hits: list[tuple[str, int, str, str, tuple[float, float, float]]] = []
    ent_total = 0
    world = _read_int(_map_doc() + CMAPDOC_WORLD_OFFSET, "u64")
    for el, vt in _walk_elements(world):
        ent_total += 1
        if ent_total > 200000:
            break
        if vt != vt_ent:
            continue
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
def cs2_mesh_list(limit: int = 100) -> str:
    """列出地图里的 CMapMesh（Hammer 手绘网格 / 贴花 overlay）。

    走 datamodel 元素表（dm+0x90）按主虚表筛 `CMapMesh`（RVA 0x176B8E0），
    比走世界树可靠。坐标同样读 `+0xA0`（CMapMesh 也派生自 MapNode，待有 mesh 时核对）。

    Args:
        limit: 最多返回多少条。
    """
    try:
        base = _hammer_base()
        vt_mesh = base + RVA_CMAPMESH_VTABLE
        rows = [(h, el) for h, el, vt in _enum_elements() if vt == vt_mesh]
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    if not rows:
        return "地图里没有 CMapMesh（当前测试地图确实没有：需要一个含 mesh 的地图来验证）"
    lines = [f"CMapMesh 数: {len(rows)}"]
    base = _hammer_base()
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
def cs2_entity_create(classname: str = "", name: str = "") -> str:
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

    Args:
        classname: FGD 类名（如 'info_player_start'）。留空则只建一个空 CMapEntity。
        name: 元素 name。留空由 Hammer 自行命名。
    """
    steps: list[str] = []
    add_err = ""
    try:
        doc = _map_doc()
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
        + ("（本次顺带打开了 Datamodel undo 总开关）" if undo_was_off else "")
        + (f"\n  ⚠ AddChild 失败: {add_err}" if add_err else "")
    )


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
