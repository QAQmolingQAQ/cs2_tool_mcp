"""Hammer runtime operations."""
from __future__ import annotations
import json
import os
import struct
from typing import Any
from .offsets import (
    MAIN_THREAD_STATUS_NAMES,
    MAX_READ_CHUNK,
)
from .session import (
    get_session,
)
from .transport import (
    Cs2Pipe,
)


def _get_pipe() -> Cs2Pipe:
    return get_session().pipe


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


def _hammer_base() -> int:
    """hammer.dll 的基址（= PE ImageBase），**进程内缓存**。

    实测 DLL 的 `get_module` 单次约 **40ms**（模块枚举很贵），而 entity_list 这类
    批量操作会调它上百次 —— 缓存后 7.5s 直接降到 1 次调用。
    管道重连（Hammer 重启 / 重新注入）时由 `_invalidate_address_cache()` 丢弃。

    可用环境变量 `CS2_HAMMER_BASE` 覆盖（十六进制或十进制）。用途：注入 DLL 的模块
    列表若因故看不到 hammer.dll（例如模块枚举缓存陈旧），可临时用外部工具（CE）
    取到基址后走绝对地址，不必重启目标进程。
    """
    override = os.environ.get("CS2_HAMMER_BASE")
    if override:
        return int(override, 0)
    if get_session().cache.hammer_base is None:
        resp = _get_pipe().call("get_module", {"name": "hammer"})
        if "error" in resp:
            raise RuntimeError(resp["error"])
        get_session().cache.hammer_base = int(resp["result"]["base_hex"], 16)
    return get_session().cache.hammer_base


def _invalidate_address_cache() -> None:
    get_session().invalidate_caches()


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
    """Invoke an absolute native address on the Hammer main thread. Return (hex result, error)."""
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
    """Resolve a vtable slot explicitly and invoke it through the main-thread bridge."""
    vtable = _read_int(this_ptr, "u64")
    fn = _read_int(vtable + vtable_offset, "u64")
    if not fn:
        return "", f"虚表槽 {vtable_offset:#x} 为空（this={this_ptr:#x}）"
    return _call_addr(fn, [this_ptr, *args], timeout)


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


def _invoke_main(fn: int, args: list[int], timeout: int = 10000) -> int:
    """Invoke a native function on the main thread and return integer RAX; raise on bridge errors."""
    resp = _get_pipe().call("call_function", {
        "address": hex(fn), "args": args,
        "on_main_thread": True, "timeout_ms": timeout,
    })
    if "error" in resp:
        raise RuntimeError(resp["error"])
    res = resp["result"]
    st = res.get("main_thread_status", 0)
    if st != 0:
        raise RuntimeError(f"主线程调用失败 status={st}: {MAIN_THREAD_STATUS_NAMES.get(st, '未知')}")
    return int(res["ret_hex"], 16)


def _parse_addr(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(value, 0)


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


def _plausible_ptr(value: int) -> bool:
    """是否是像样的用户态指针（用来过滤实体内存里的整数/浮点）。"""
    return 0x10000 < value < 0x00007FFFFFFFFFFF and (value & 0x7) == 0


def _write_mem_chunked(address: int, data: bytes, chunk: int = 1024) -> None:
    """分块写内存（DLL 侧单次写入有上限）。"""
    for off in range(0, len(data), chunk):
        _write_mem(address + off, data[off:off + chunk])
