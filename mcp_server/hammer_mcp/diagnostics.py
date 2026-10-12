"""Hammer diagnostics operations."""
from __future__ import annotations
import json
import struct
from typing import Any
from .runtime import (
    _invalidate_address_cache,
    _call,
    _get_pipe,
    _hammer_base,
)


def cs2_pipe_ping() -> str:
    """探测注入的 cs2_tool.dll 是否存活（验证命名管道 IPC）。
    返回目标进程内的初始化状态。"""
    return _call("ping")


def cs2_hammer_status() -> str:
    """获取 hammer.dll 桥接状态：模块基址、CreateInterface 指针、
    ToolSystem2_001 实例，以及已注册接口名的前 30 个。"""
    return _call("get_status")


def cs2_initialize() -> str:
    """强制（重新）初始化 DLL 内的 HammerBridge：
    重新枚举 hammer.dll、重新解析 CreateInterface、重新获取 ToolSystem2_001。
    在 hammer.dll 加载完成后调用。"""
    _invalidate_address_cache()
    return _call("initialize")


def cs2_list_tools() -> str:
    """列出注入 DLL 当前支持的所有 IPC 方法名。"""
    return _call("list_tools")


def cs2_list_interfaces() -> str:
    """列出 hammer.dll 中 CreateInterface 链表上注册的全部 Valve 风格接口名
    （如 ToolSystem2_001、HammerMapLoader001 ...）。"""
    return _call("list_interfaces")


def cs2_get_interface(name: str) -> str:
    """调用 CreateInterface(name)，返回接口指针与返回码（0=成功, 1=未找到）。
    例：name='ToolSystem2_001'。"""
    return _call("get_interface", {"name": name})


def cs2_list_modules() -> str:
    """列出目标进程已加载模块的 name / base / image_base / size。"""
    return _call("list_modules")


def cs2_get_module(name: str) -> str:
    """获取单个模块的基址与大小。name 可省略 .dll，如 'hammer'、'pet'。"""
    return _call("get_module", {"name": name})


def cs2_tool_modules() -> str:
    """列出四个 CS2 编辑器模块的加载状态：hammer（Hammer）/ met（材质编辑器）/
    modeldoc_editor（ModelDoc）/ pet（粒子编辑器），各含 CreateInterface 地址、
    工具系统接口名（hammer/met/pet 是 ToolSystem2_001，modeldoc 是 ToolSystem2_ModelDoc）、
    工具系统实例指针，以及该实例的 RTTI 实现类名（tool_system_class，如
    CHammerApp / CMaterialEditorTool / CPetApp —— 编辑器 App 单例自身实现 ToolSystem2）。
    注意：只有把对应编辑器打开，它的 DLL 才会加载进进程。"""
    return _call("tool_modules")


def cs2_get_tool_system(module: str) -> str:
    """取某个编辑器模块的工具系统实例指针。
    module 可传 'hammer' / 'met' / 'modeldoc' / 'pet'（也可给 .dll 全名）。"""
    return _call("get_tool_system", {"module": module})


def _module_call(method: str, params: dict[str, Any]) -> tuple[Any, str | None]:
    """带错误处理的原始调用，返回 (result, None) 或 (None, 错误文本)。"""
    try:
        resp = _get_pipe().call(method, params)
    except ConnectionError as e:
        return None, f"管道未连接: {e}\n请先把新版 cs2_tool.dll 注入 cs2.exe。"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    if "error" in resp:
        return None, resp["error"]
    return resp.get("result"), None


def cs2_module_interfaces(module: str) -> str:
    """列出已加载 DLL 的 CreateInterface 注册表（名字+工厂地址，不调用工厂）。
    module 可用 hammer/met/modeldoc/pet 或 scenesystem/tier0/particles 等 DLL 名。
    目标必须已加载并导出 CreateInterface；普通运行时 DLL 不需要 ToolSystem。"""
    data, err = _module_call("module_interfaces", {"module": module})
    if err:
        return f"ERROR {err}"
    items = data if isinstance(data, list) else json.loads(data)
    lines = [f"{module} 模块注册接口 {len(items)} 个（CreateInterface 注册表）"]
    for it in items:
        lines.append(f"  {it['name']:<40} factory={it['factory_hex']}")
    return "\n".join(lines)


def cs2_module_get_interface(module: str, name: str) -> str:
    """向已加载 DLL 的 CreateInterface 请求命名接口，返回实例指针与返回码。
    module 可用 hammer/met/modeldoc/pet 或 scenesystem/tier0/particles 等 DLL 名；
    先用 cs2_module_interfaces 查看该模块实际注册的接口。"""
    return _call("module_get_interface", {"module": module, "name": name})


def cs2_module_bind_targets(module: str, include_commands: bool = True,
                            limit: int = 0) -> str:
    """列出某个编辑器模块的可绑定目标（Key Bindings / 工具热键体系）。
    四个编辑器 DLL（hammer/met/modeldoc/pet）共用同一套 tier2 bind 框架，
    节点布局相同，链表头由 IDA 逆向硬编码（REVERSE_NOTES §17/§23）。
    每个目标含：目标名、实现类名、注册源文件+行号、命令列表。

    Args:
        module: 'hammer' / 'met' / 'modeldoc' / 'pet'（或 .dll 全名）。
        include_commands: 是否展开每个目标下的命令（modeldoc 目标很多，
            只看目标名/类名时可传 false 大幅提速）。
        limit: 最多显示多少个目标，0=全部。
    """
    data, err = _module_call("module_bind_targets",
                             {"module": module, "include_commands": include_commands})
    if err:
        return f"ERROR {err}"
    obj = data if isinstance(data, dict) else json.loads(data)
    targets = obj.get("targets", [])
    shown = targets if limit <= 0 else targets[:limit]
    lines = [f"{obj['module']} 可绑定目标 {obj['target_count']} 个 / "
             f"命令 {obj['command_total']} 条"
             + (f"（只显示前 {len(shown)} 个）" if limit and len(targets) > limit else "")]
    for t in shown:
        src = t.get("source_file") or "?"
        lines.append(f"\n[{t['name']}]  <- {t['class']}  ({src}:{t['line']})")
        if include_commands:
            cmds = t.get("commands", [])
            if cmds:
                lines.append("    命令: " + ", ".join(cmds))
    return "\n".join(lines)


def cs2_read_memory(address: str, size: int = 8) -> str:
    """从 hammer.exe 进程内读取原始内存，返回十六进制转储。

    Args:
        address: 绝对地址 (0x...) 或 'hammer.dll+0x12E1B50' 形式。
        size: 读取字节数（上限 1024）。
    """
    return _call("read_memory", {"address": address, "size": size})


def cs2_read_qword(address: str) -> str:
    """读取 8 字节指针值（cs2_read_memory 的便捷封装）。"""
    return _call("read_qword", {"address": address})


def cs2_read_value(address: str, type: str = "u64") -> str:
    """按类型读取一个值。

    Args:
        address: 绝对地址或 'hammer.dll+0x...' 形式。
        type: u8/u16/u32/u64/i8/i16/i32/i64/f32/f64/ptr
    """
    return _call("read_value", {"address": address, "type": type})


def cs2_write_value(address: str, value: int, type: str = "u64") -> str:
    """按类型写入一个值（谨慎使用，可能影响目标稳定性）。

    Args:
        address: 绝对地址或 'hammer.dll+0x...' 形式。
        value: 要写入的整数/位模式（float 请传其位模式的十进制整数）。
        type: u8/u16/u32/u64/i8/i16/i32/i64/f32/f64/ptr
    """
    return _call("write_value", {"address": address, "value": value, "type": type})


def cs2_read_string(address: str, max_len: int = 256) -> str:
    """读取以 NUL 结尾的 C 字符串（跨页时安全截断）。"""
    return _call("read_string", {"address": address, "max_len": max_len})


def cs2_read_ptr_chain(base: str, offsets: list[int]) -> str:
    """按多级指针链解析最终地址：base -> +off0 -> [ptr] +off1 -> [ptr] +off2 ...

    Args:
        base: 起始地址。
        offsets: 偏移序列（十进制或十六进制整数）。
    """
    return _call("read_ptr_chain", {"base": base, "offsets": offsets})


def cs2_find_pattern(pattern: str, module: str = "hammer.dll", limit: int = 20) -> str:
    """在模块内存中做 AOB 特征扫描。

    Args:
        pattern: 形如 '48 8B ?? E8 ?? ?? ?? ??'，'??' 或 '?' 为通配。
        module: 目标模块名（默认 hammer.dll）。
        limit: 最多返回命中数（默认 20）。
    """
    return _call("find_pattern", {"pattern": pattern, "module": module, "limit": limit})


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


def cs2_map_list_docs() -> str:
    """枚举当前所有打开的 CMapDoc 文档，返回地址与地图名。

    新版（2026-09）链路：CHammerApp+0x58/+0x60 的 CHammerEditorSession* 数组
    → session+0x138 活动 CMapDocSession → CMapDoc 内嵌于 wrapper+0x10。
    """
    return _call("map_list_docs")


def cs2_get_hammer_app() -> str:
    """获取 CHammerApp / ToolSystem2_001 顶层应用对象指针
    （IDA: ToolSystem2_001 工厂 sub_180115270 返回 CHammerApp）。"""
    return _call("get_hammer_app")


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
