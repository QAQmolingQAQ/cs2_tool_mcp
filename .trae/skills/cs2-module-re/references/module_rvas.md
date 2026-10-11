# 四模块 RVA 表与结构布局

数据为 **2026-10-10** 版（hammer.dll MD5 `832119E3…`）。ImageBase 均 `0x180000000`、`DYNAMIC_BASE=False`。
详细推导见 `REVERSE_NOTES.md` §22 / §23。

## 1. 模块常量

| 模块（DLL） | ToolSystem 接口名 | CreateInterface RVA | s_pInterfaceRegs 链头 RVA | bind 描述符链头 RVA | ToolSystem 实现类 | bind 目标/命令数 |
| --- | --- | --- | --- | --- | --- | --- |
| hammer.dll | `ToolSystem2_001` | `0x1401130` | `0x2738770` | `0x2731E98` | `CHammerApp` | 69 / 1194 |
| met.dll | `ToolSystem2_001` | `0x1D89A0` | `0x4A1740` | `0x4A0AD0` | `CMaterialEditorTool` | 1 / 15 |
| modeldoc_editor.dll | `ToolSystem2_ModelDoc` | `0xAF2AB0` | `0x1AAB588` | `0x1AA9620` | `CModelDocEditorApp` | 23 / 227 |
| pet.dll | `ToolSystem2_001` | `0x3A2AE0` | `0x93A1D0` | `0x938408` | `CPetApp` | 10 / 105 |

- `CreateInterface("ToolSystem2_*")` 返回的就是该编辑器的 **App 单例**（App 对象自身实现 ToolSystem2）。
- 接口链头可用序言解析动态得到；**bind 链头是纯数据全局，只能硬编码（按版本）**。
- met 只有 1 个 bind 目标是真实结果（其材质编辑工具不注册 bind 目标）。
- met 的 bind 枚举函数 `sub_18018C080`、pet `sub_18031D0B0`、modeldoc `sub_180A494D0`。

## 2. InterfaceNode（`s_pInterfaceRegs` 链）

```
+0x00  factory (void*)        // CreateInterface(name, &rc)
+0x08  name    (char*)
+0x10  next    (InterfaceNode*)
```

## 3. bind 描述符节点 `CBindableTargetDescriptorInstance<T>`（步长 0x70）

| 偏移 | 含义 |
| --- | --- |
| `+0x00` | vtable |
| `+0x08` | 目标名 hash (u32) |
| `+0x10` | 目标名 `char*`（vfn0） |
| `+0x18` | 实现类名 `char*`（vfn1） |
| `+0x20` | 注册源文件 `char*` · `+0x28` 行号 (u32) |
| `+0x30` | OverideHelpContextName |
| `+0x38` | **next** |
| `+0x40` | 命令数 (int) · `+0x48` 命令数组 · `+0x50` 容量 |

- 虚表槽：`[0]` 目标名 · `[1]` 类名 · `[2]` hash · `[3]`(byte 24) 命令数 · `[4]`(byte 32) 取第 i 个命令。
- 桥接层为了对其它模块**零虚调用**，直接按上面的字段偏移 raw 读。

## 4. 命令对象 `CBindTargetDescriptor<T>::CBindableCommand`（逻辑 0x240 字节，按 0x40 对齐块）

| 偏移 | 含义 |
| --- | --- |
| `+0x00` | vtable |
| `+0x08` | 命令名 `char*` |
| `+0x10` | 命令名 hash (u32) |
| `+0x18` | 描述 `char*`（多数空） |
| `+0x40 + 0x40*k` | **stage k 的 `std::function`**（k = 0..7） |

**判空块不可看指针非空**：空块是堆复用残留，会像自指链。
判据 = 「functor vtable 的槽 2（`+0x10`）落在本模块代码区」（用模块 base..base+size 判）。
即使这样仍有假阳性（残留恰好指向模块内），所以**执行前最好反汇编 `_Do_call` 确认形态**。

## 5. stage 语义

| stage | 含义 |
| --- | --- |
| 5 | **一次性执行**（绝大多数菜单命令只绑这档） |
| 0 | 按下 · 2 拖动 · 3 长按连发 · 6 松开 · 4/7 未定 · 1 从未出现 |

## 6. 执行：调 `_Do_call`，不要盲调 pmf ⚠

functor 布局**随 lambda 捕获而变**，至少三种：

| 形状 | `_Do_call` 反汇编 | 备注 |
| --- | --- | --- |
| 只捕 pmf | `mov rax,rcx; mov rcx,[rdx]; jmp qword [rax+8]` | `+0x10/+0x18` 是**堆残留**，盲算 `ctx+adj` 会得野 `this` |
| `[pmf, adj, arg]` | `movsxd rcx,dword [rcx+10h]; add rcx,[rdx]; movzx edx,byte [rax+18h]; jmp [rax+8]` | arg 是 **bool（1 字节）** |
| `[pmf, int, int]` | 见 `SetFunction<void (CGlobalHotkeyCommands::*)(int,int),int,int>` | 两个 int 实参 |

正确做法（`mcp_server/cs2_mcp_server.py::_bind_invoke_do_call`）：

```
alloc_memory(8) → write_value(cell, ctx_addr, u64)
→ call_function(do_call_addr, [fn_block, cell], on_main_thread=True) → free_memory(cell)
```

`_Do_call` 的第 2 实参是「**指向 ctx 指针的指针**」（它做 `[rdx]` 取真实 ctx），
等价 `std::function::operator()`，**布局无关**。

## 7. ctx 解析（`_bind_ctx` 现状）

| 目标实现类 | ctx 取法 |
| --- | --- |
| 该模块 App 类（`md["cls"]`，如 `CPetApp`） | `get_tool_system(module).tool_system`（App 单例） |
| `CGlobalHotkeyCommands`（`GlobalHotkeys` 目标） | 该类实例未定位；实测其命令**从不触碰 `this`** → 回退用 App 单例 |
| hammer 的工具实例（`CToolSelection` 等） | `CHammerApp +0x60` 会话数组 → 会话 `+0x120` = CToolManager → `+0x38` 实例数组，按 RTTI 类名匹配 |
| 非 hammer 的工具实例 | **未逆向**（需该编辑器先打开文档才有会话），必须用 `ctx=` 显式给地址 |

hammer 的 App 单例 = `CHammerApp`（`hammer+0x677F440`，与 `tool_system` 同一地址）；
App 内偏移：`+0x58` 会话数 · `+0x60` 会话数组 · `+0x120`(会话) 工具管理器 ·
CToolManager `+0x30` 实例数 · `+0x38` 实例数组。

## 8. RTTI 解析（MSVC x64 BCD）

```
obj → *(obj)        = vtable
    → *(vtable - 8) = CompleteObjectLocator (COL)
    → *(u32*)(COL+0x0C) = pTypeDescriptor 的 RVA（相对**模块加载基址**，故 td = module.base + rva）
    → *(char*)(td+0x10) = 修饰名 ".?AVCPetApp@@"
剥掉前缀 ".?AV" 与尾部 "@@"
```
⚠ `COL+0x00` 是 signature（=1），**不是** pTypeDescriptor；那是 32 位 BCD 的布局。
