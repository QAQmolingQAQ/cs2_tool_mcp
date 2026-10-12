"""Hammer bindings operations."""
from __future__ import annotations
from .offsets import (
    APP_OFF_SESSION_ARRAY,
    APP_OFF_SESSION_COUNT,
    BIND_CMD_OFF_DESC,
    BIND_CMD_OFF_NAME,
    BIND_OFF_CLASS,
    BIND_OFF_FILE,
    BIND_OFF_LINE,
    BIND_OFF_NEXT,
    BIND_VFN_CMD_AT,
    BIND_VFN_CMD_COUNT,
    BIND_VFN_NAME,
    CMD_BLOCK_BASE,
    CMD_BLOCK_STRIDE,
    CMD_OFF_DESC,
    CMD_OFF_HASH,
    CMD_OFF_NAME,
    CMD_STAGE_AUTO_ORDER,
    CMD_STAGE_COUNT,
    CMD_STAGE_LABELS,
    FN_OFF_ADJ,
    FN_OFF_ARG,
    FN_OFF_PMF,
    FN_VT_OFF_DOCALL,
    RTTI_COL_TO_TYPEDESC,
    RVA_CHAMMERAPP,
    SESSION_OFF_TOOLMGR,
    TOOLMGR_OFF_ARRAY,
    TOOLMGR_OFF_COUNT,
)
from .runtime import (
    _call_addr,
    _call_vfn,
    _get_pipe,
    _hammer_base,
    _read_int,
    _read_string,
)
from .session import (
    get_session,
)


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


def cs2_bind_list(module: str = "hammer", filter: str = "", limit: int = 0) -> str:
    """列出某编辑器模块的「可绑定工具命令」全表 —— 即 Options → Key Bindings 那张表。

    数据源（见 REVERSE_NOTES §17/§23）：每个工具类在静态初始化时，把自己的
    `CBaseBindTargetDescriptor` 头插进一条**全局链表**（表头 per 模块；hammer `0x2731E98`、
    met `0x4A0AD0`、modeldoc `0x1AA9620`、pet `0x938408`）。每个描述符给出
    「工具名 + 实现类名 + 注册处源文件/行号」，并通过虚函数给出它的一批命令。

    读取方式**全只读**（纯 getter 虚调用），不改文档、不产生历史。

    Args:
        module: `hammer` / `met` / `modeldoc` / `pet`（默认 hammer）。该模块必须已加载。
        filter: 大小写不敏感的子串过滤（匹配工具名 / 类名 / 命令名）。
        limit: 最多列多少条命令（0 = 不限）。
    """
    cap = max(0, int(limit))
    kw = str(filter).strip().lower()
    try:
        md = _tool_module(module)
        head = _read_int(md["bind_head"], "u64")
        if not head:
            return f"{md['label']} 绑定目标链表为空（可能还没初始化完，或版本不符）"
        nodes, seen, n_cmds = [], set(), 0
        node = head
        while node and node not in seen and len(nodes) < 4096:
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

        lines = [f"{md['label']} 可绑定工具命令  工具 {len(nodes)} 个 / 命令 {n_cmds} 条"
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


def _tool_module(module: str = "hammer") -> dict:
    """取某编辑器模块的关键地址（base / bind_head / tool_system / 实现类名），带缓存。

    数据来自注入层 `get_tool_system`（四模块通用，见 REVERSE_NOTES §22/§23）。
    `bind_head` = 该模块 bind 描述符全局链表头的**地址**（值是首个节点指针）；
    `tool_system` = `CreateInterface(ToolSystem2_*)` 返回的 App 单例，即该模块
    「App 类」bind 目标要用的上下文对象（见 §23.4）。
    """
    key = (module or "hammer").strip().lower() or "hammer"
    if key.endswith(".dll"):
        key = key[:-4]
    info = get_session().cache.tool_modules.get(key)
    if info is None:
        resp = _get_pipe().call("get_tool_system", {"module": key})
        if "error" in resp:
            raise RuntimeError(resp["error"])
        r = resp["result"]
        if not r.get("loaded"):
            raise RuntimeError(f"模块未加载: {key}（先用 cs2_tool_modules 看状态）")
        size = 0
        try:
            m = _get_pipe().call("get_module", {"name": key}).get("result") or {}
            size = int(m.get("size") or 0)
        except Exception:  # noqa: BLE001
            size = 0
        info = {
            "label": r.get("label", key),
            "base": int(r["base_hex"], 16),
            "size": size or 0x8000000,   # 兜底 128MB（仅用于「代码指针落在本模块」判断）
            "bind_head": int(r["bind_head_hex"], 16),
            "tool_system": int(r["tool_system_hex"], 16),
            "cls": r.get("tool_system_class", ""),
        }
        get_session().cache.tool_modules[key] = info
    return info


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


def _bind_ctx(md: dict, target: str, cls: str, ctx: str) -> tuple[int, str]:
    """解析执行用的「上下文对象」-> (`地址`, 说明)。

    优先 `ctx` 参数；否则按类名自动解析：
      · 该模块的 **App 类**（`CHammerApp` / `CMaterialEditorTool` / `CPetApp` /
        `CModelDocEditorApp`）→ 该模块 `CreateInterface` 返回的 App 单例；
      · hammer 的其它工具类（`CToolSelection` 等）→ 会话里对应的**工具实例**（RTTI 类名匹配）。
    非 hammer 模块的「工具实例表」（会话 → CToolManager）尚未逆向，遇到工具类目标需用
    `ctx=` 显式给地址（见 REVERSE_NOTES §17.10）。
    """
    raw = (ctx or "").strip()
    if raw:
        return int(raw, 0), "由 ctx 参数指定"
    want = (cls or "").strip()
    tname = (target or "").strip()
    # App 单例：目标实现类名 == 该模块 ToolSystem 实现类（App 对象自身实现工具系统）
    if want and md["cls"] and want == md["cls"]:
        return md["tool_system"], f"{md['cls']} App 单例（该模块 ToolSystem）"
    if want == "CHammerApp" or tname.lower() == "hammerapp":
        return md["tool_system"], "CHammerApp 全局单例"
    # `GlobalHotkeys`（实现类 CGlobalHotkeyCommands）四模块都有，但该类实例未能定位。
    # IDA 反汇编确认其命令（ShowConsole / SwitchToEngineWindow / ShowInputDebugger /
    # DebugWidgetUnderMouse …）**全部只操作模块全局量、从不触碰 this**，故用本模块 App
    # 单例顶替即可（见 REVERSE_NOTES §23.6）。
    if want == "CGlobalHotkeyCommands":
        return md["tool_system"], "CGlobalHotkeyCommands 实例未知；其命令不触碰 this，用 App 单例顶替"
    # 工具实例表只在 hammer 侧逆向过（CHammerApp → 会话 → CToolManager）
    if md["label"] == "hammer" and want:
        for name, addr in _tool_instances():
            if name == want:
                return addr, f"{want} 工具实例（RTTI 匹配）"
    return 0, ""


def _bind_targets(md: dict) -> list[tuple[int, str, str]]:
    """遍历该模块的描述符全局链表 -> [(desc 指针, 目标名, 实现类名)]（只读）。"""
    out: list[tuple[int, str, str]] = []
    node = _read_int(md["bind_head"], "u64")
    seen = set()
    while node and node not in seen and len(out) < 4096:
        seen.add(node)
        out.append((node, _read_string(_vfn_ptr(node, BIND_VFN_NAME), 128),
                    _read_cptr(node, BIND_OFF_CLASS, 128)))
        node = _read_int(node + BIND_OFF_NEXT, "u64")
    return out


def _bind_find_target(md: dict, name: str):
    """按目标名 / 实现类名（大小写不敏感）找描述符 -> (desc, 名, 类名) 或 None。"""
    want = (name or "").strip().lower()
    if not want:
        return None
    for desc, tname, cls in _bind_targets(md):
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


def _bind_stage(cmd: int, stage: int, md: dict) -> dict | None:
    """取某个 stage 上绑定的函数信息；该 stage 没绑返回 None（只读）。"""
    if not (0 <= stage < CMD_STAGE_COUNT):
        return None
    blk = cmd + CMD_BLOCK_BASE + CMD_BLOCK_STRIDE * stage
    try:
        vt = _read_int(blk, "u64")
        if not vt:
            return None
        do_call = _read_int(vt + FN_VT_OFF_DOCALL, "u64")
        # 只有「vtable 槽 2 落在本模块代码区」才算真的绑了函数：
        # 空块的 +0x00 是堆里的残留指针，读出来的槽 2 不会落在代码区。
        if not (md["base"] <= do_call < md["base"] + md["size"]):
            return None
        return {
            "stage": stage, "block": blk, "functor_vt": vt, "do_call": do_call,
            "pmf": _read_int(blk + FN_OFF_PMF, "u64"),
            "adj": _read_int(blk + FN_OFF_ADJ, "u32"),
            "arg": _read_int(blk + FN_OFF_ARG, "u32"),
        }
    except Exception:  # noqa: BLE001
        return None


def _bind_stages(cmd: int, md: dict) -> list[dict]:
    """列出该命令**已绑函数**的全部 stage。"""
    return [s for s in (_bind_stage(cmd, k, md) for k in range(CMD_STAGE_COUNT)) if s]


def _fmt_stage(s: dict, md: dict) -> str:
    return (f"stage{s['stage']}[{CMD_STAGE_LABELS.get(s['stage'], '?')}] "
            f"(+{CMD_BLOCK_BASE + CMD_BLOCK_STRIDE * s['stage']:#x}) "
            f"pmf={md['label']}+{s['pmf'] - md['base']:#x} adj={s['adj']} 绑定实参={s['arg']}")


def _bind_invoke_do_call(s: dict, ctx_addr: int, timeout: int = 30000) -> tuple[str, str]:
    """通过模块自己的 `_Do_call` 执行该 stage 的 `std::function`（= `operator()`）。

    为什么不用「直接调 pmf」：functor 的内存布局**随 lambda 捕获而变**（有只捕 pmf 的、
    有捕 [pmf, adj, arg] 的、arg 还可能是 bool 1 字节）。`_Do_call` 是编译器为该 lambda
    生成的调用器，偏移全写死在它自己代码里，所以走它**布局无关、最稳**。

    `_Do_call` 第 2 个参数是「指向 ctx 指针的指针」，故先在目标进程分配 8 字节存放 ctx
    指针，再调 `_Do_call(fn, &cell)`，最后释放。返回 (ret_hex, 错误串)。
    """
    pipe = _get_pipe()
    a = pipe.call("alloc_memory", {"size": 8})
    if "error" in a:
        return "", f"alloc_memory 失败: {a['error']}"
    cell = int(a["result"]["address"], 16)
    try:
        w = pipe.call("write_value", {"address": hex(cell), "type": "u64", "value": ctx_addr})
        if "error" in w:
            return "", f"write_value 失败: {w['error']}"
        return _call_addr(s["do_call"], [s["block"], cell], timeout=timeout)
    finally:
        pipe.call("free_memory", {"address": hex(cell)})


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


def cs2_bind_inspect(module: str = "hammer", target: str = "", command: str = "") -> str:
    """（只读）看可绑定命令**实际绑了什么函数**、执行它需要哪个上下文对象。

    背景见 REVERSE_NOTES §17/§23：每个工具类在静态初始化时把
    `CBindTargetDescriptor<T>::CBindableCommand` 登记进本模块的全局链表，
    每个命令对象里按 **stage** 存了最多 8 个 `std::function`。

    Args:
        module:  `hammer` / `met` / `modeldoc` / `pet`（默认 hammer）。该模块必须已加载。
        target:  目标名（如 `HammerApp` / `ToolSelection`）；也可传实现类名。留空 = 列出全部目标。
        command: 命令名。留空 = 列出该目标下**所有已绑函数**的命令及其 stage。
    """
    try:
        md = _tool_module(module)
        if not (target or "").strip():
            rows = []
            for desc, tname, cls in _bind_targets(md):
                cmds = _bind_commands(desc)
                bound = [c for c, _, _ in cmds if _bind_stages(c, md)]
                rows.append(f"  {tname or '(无名)':<28} 类={cls or '?':<28} "
                            f"命令 {len(cmds)} 条 / 其中 {len(bound)} 条绑了函数")
            ctxrows = []
            if md["label"] == "hammer":
                ctxrows = [f"  {name or '(未知)':<28} {addr:#x}" for name, addr in _tool_instances()]
            ctxrows.insert(0, f"  {md['cls'] or '(App 类)':<28} {md['tool_system']:#x}  ← App 单例（tool_system）")
            return (f"[{md['label']}] 目标（共 %d 个）：\n%s\n\n"
                    "可用上下文对象（共 %d 个）：\n%s\n\n"
                    "用 cs2_bind_inspect(module=..., target=...) 看某个目标；"
                    "用 cs2_bind_run(module=..., target=..., command=...) 执行。"
                    % (len(rows), "\n".join(rows), len(ctxrows), "\n".join(ctxrows)))

        found = _bind_find_target(md, target)
        if not found:
            return f"找不到目标 {target!r}。用 cs2_bind_list 看有哪些目标。"
        desc, tname, cls = found

        if not (command or "").strip():
            lines = [f"[{md['label']}] 目标 {tname!r}  类={cls}  desc={desc:#x}"]
            for cmd, cname, cdesc in _bind_commands(desc):
                st = _bind_stages(cmd, md)
                if not st:
                    continue
                lines.append(f"\n· {cname}" + (f"  — {cdesc}" if cdesc else ""))
                lines.append(f"    cmd={cmd:#x} hash={_read_int(cmd + CMD_OFF_HASH, 'u32'):#x}")
                for s in st:
                    lines.append("    " + _fmt_stage(s, md))
            if len(lines) == 1:
                return f"目标 {tname!r} 下没有任何命令绑定函数。"
            return "\n".join(lines)

        fcmd = _bind_find_command(desc, command)
        if not fcmd:
            return f"目标 {tname!r} 下找不到命令 {command!r}。"
        cmd, cname, cdesc = fcmd
        st = _bind_stages(cmd, md)
        lines = [f"{tname}.{cname}   desc={desc:#x} cmd={cmd:#x}",
                 f"  名字 hash = {_read_int(cmd + CMD_OFF_HASH, 'u32'):#x}"
                 + (f"   描述: {cdesc}" if cdesc else "")]
        if not st:
            return "\n".join(lines + ["  该命令没绑任何 stage 函数（可能只是文档占位）。"])
        for s in st:
            lines.append("  " + _fmt_stage(s, md))
        ctx_addr, why = _bind_ctx(md, tname, cls, "")
        lines.append(f"  上下文对象: {ctx_addr:#x}（{why}）" if ctx_addr
                     else "  上下文对象: 未知（执行时要用 ctx= 显式给）")
        return "\n".join(lines)
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


def cs2_bind_run(module: str = "hammer", target: str = "", command: str = "", stage: str = "",
                 ctx: str = "", arg: int = -1, confirm: bool = False) -> str:
    """执行某编辑器模块的一个可绑定命令（直接调它绑定的成员函数）。

    ⚠ 这是**真执行**：会走该编辑器自己的工具方法（可能改选择集 / 视图 / 甚至开新文档）。
    先跑 `cs2_bind_inspect` 看清要调什么；真正执行必须显式 `confirm=True`。

    原理（REVERSE_NOTES §17.6）：命令对象的每个 stage 存一个 `std::function`，
    `_Do_call` 的语义是 `(上下文对象->*pmf)(绑定实参)`。我们直接调 pmf：
        pmf(ctx + adj, arg)
    全部参数是整数，所以 DLL 的调用桥无需支持 xmm。
    跨模块时 `ctx` 自动解析覆盖：**该模块的 App 单例**（`CHammerApp` / `CMaterialEditorTool` /
    `CPetApp` / `CModelDocEditorApp`），以及 `GlobalHotkeys`（其命令不触碰 `this`，回退用 App 单例）；
    其它工具类目标（如 modeldoc 的 `Tool_Selection`）需用 `ctx=` 显式给实例地址。

    Args:
        module:  `hammer` / `met` / `modeldoc` / `pet`（默认 hammer）。该模块必须已加载。
        target:  目标名（`HammerApp` / `ToolSelection` / `PetApp` ...）。
        command: 命令名（`ToggleSnapping` / `ShrinkGizmo` / `NextSession` ...）。
        stage:   要执行的 stage。可传数字 0-7，或名字 `press`/`drag`/`repeat`/`release`/`execute`。
                 **留空 = 自动**：优先 `execute`(5)，没有就 `press`(0)，再退到第一个已绑档。
                 持续型命令（`Nudge*` / `BoxSelect` 等）是分档的，需要「按住再松开」时手动传两次。
        ctx:     上下文对象地址（`0x...`）。留空 = 自动解析（App 类走该模块单例；hammer 的其它
                 工具类按类名 RTTI 找工具实例）。
        arg:     覆盖绑定实参（整数）；默认 -1 = 用命令自带的。
        confirm: 必须为 True 才真的执行；否则只回显将要调用的内容。
    """
    try:
        md = _tool_module(module)
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    try:
        stage_idx = _stage_index(stage)
    except ValueError as e:
        return f"ERROR {e}"
    try:
        found = _bind_find_target(md, target)
        if not found:
            return f"找不到目标 {target!r}。"
        desc, tname, cls = found
        fcmd = _bind_find_command(desc, command)
        if not fcmd:
            return f"目标 {tname!r} 下找不到命令 {command!r}。"
        cmd, cname, _ = fcmd

        allst = _bind_stages(cmd, md)
        if not allst:
            return f"{tname}.{cname} 没绑任何 stage 函数，无法执行。"
        s = _pick_stage(allst, stage_idx)
        if not s:
            return (f"{tname}.{cname} 在 stage={stage_idx} 没绑函数；"
                    f"可用 stage: {[x['stage'] for x in allst]}")

        ctx_addr, why = _bind_ctx(md, tname, cls, ctx)
        if not ctx_addr:
            return (f"{tname}.{cname} 需要「上下文对象」地址，但没有可自动解析的来源。\n"
                    f"请用 ctx='0x...' 指定（例如该工具类的实例地址）。\n"
                    f"可用 stage: {[x['stage'] for x in allst]}")

        label = CMD_STAGE_LABELS.get(s["stage"], "?")
        if arg >= 0:
            # 覆盖绑定实参 → 只能绕过 _Do_call 直接调 pmf（要求 [pmf, adj, arg] 布局）
            this = ctx_addr + s["adj"]
            how = (f"直接调 pmf({md['label']}+{s['pmf'] - md['base']:#x})(this={this:#x}, "
                   f"arg={int(arg)})   [⚠ 仅对 [pmf, adj, arg] 布局安全；arg 已被覆盖]")
            call_args = [this, int(arg)]
            call_target = s["pmf"]
        else:
            how = (f"走 _Do_call({md['label']}+{s['do_call'] - md['base']:#x})"
                   f"(fn={s['block']:#x}, &ctx={ctx_addr:#x})   [等价 std::function 调用，布局无关]")
            call_args = None
            call_target = s["do_call"]

        plan = (f"[{md['label']}] {tname}.{cname}  stage={s['stage']}[{label}]  "
                f"ctx={ctx_addr:#x} ({why})\n  {how}")
        if not confirm:
            return plan + "\n（confirm=False：只回显，未执行。确认无误后传 confirm=True。）"

        if call_args is None:
            ret_hex, err = _bind_invoke_do_call(s, ctx_addr)
        else:
            ret_hex, err = _call_addr(call_target, call_args, timeout=30000)
        if err:
            return plan + f"\n❌ 调用失败: {err}"
        return plan + f"\n✅ 已执行  返回值={ret_hex or '0x0'}"
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


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
