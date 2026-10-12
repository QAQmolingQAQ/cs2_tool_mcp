"""Hammer particles operations."""
from __future__ import annotations
from .datamodel import (
    _dm_attr_value,
    _dm_find_attr,
    _entity_class_props,
    _resolve_handle,
)
from .history import (
    _ensure_undo_enabled,
    _undo_scope_begin,
    _undo_scope_end,
)
from .offsets import (
    CMAPENTITY_SIZE,
    MAIN_THREAD_STATUS_NAMES,
    OFF_HELPER_DEFINITION,
    OFF_HELPER_EFFECT_NAME,
    OFF_HELPER_ENTITY_HANDLE,
    PARTICLE_EFFECT_ATTR,
    PARTICLE_ENTITY_CLASS,
    RVA_CPARTICLE_HELPER_VTABLE,
    RVA_PARTICLE_SET_DEFINITION,
    RVA_PROPS_SET_STRING_ATTR,
)
from .runtime import (
    _get_pipe,
    _hammer_addr,
    _hammer_base,
    _parse_addr,
    _plausible_ptr,
    _read_bytes,
    _read_int,
    _read_string,
)


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
