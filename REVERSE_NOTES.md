# CS2 Hammer 工具模式 — 逆向工程笔记

> 最后更新: 2026-09-26
> 目标: 让 AI 通过 MCP 操控 CS2 Hammer 编辑器（地图编辑、粒子、模型、滤镜、贴图）
>
> ⚠️ **RVA 以 §11 为准**（2026-09-24 新版 hammer.dll）。§8 的速查表是旧版，已全部失效。

---

## 0. 架构总览

```
┌─────────────┐  命名管道  ┌──────────────────┐  CreateInterface  ┌─────────────────┐
│  Python MCP  │◄────────►│  cs2_tool.dll    │◄─────────────────►│  hammer.dll      │
│  (FastMCP)   │  \\.\pipe │  (注入 hammer.exe)│                   │  pet.dll         │
│              │  CS2ToolMCP│                 │                   │  particles.dll   │
└─────────────┘           └──────────────────┘                   └─────────────────┘
                                    │
                                    │ GetModuleHandleW
                                    ▼
                          pet.dll / particles.dll
```

**三层架构**（已全部跑通基础链路）:
1. **C++ 注入 DLL** — MSVC x64 Release, 注入 hammer.exe, 通过 Valve CreateInterface → ToolSystem2_001 → CHammerApp 拿顶层对象
2. **Python MCP Server** — ctypes 命名管道客户端 + FastMCP 包装
3. **注入器** — Python CreateRemoteThread + LoadLibraryW

---

## 1. 三大 DLL 接口表（CreateInterface）

### 1.1 hammer.dll

| 属性 | 值 |
|------|-----|
| imagebase | `0x180000000` |
| CreateInterface | **`0x1812E1B50`** (RVA `0x12E1B50`) |
| 接口链表头 | `qword_1826310E8` (RVA `0x26310E8`) |
| 编译语言 | C++ name mangling + thiscall |

**接口注册表** (`sub_18004A730`):
```c
node.factory = sub_180115270;    // CHammerApp 工厂
node.name    = "ToolSystem2_001";
node.next    = qword_1826310E8;
qword_1826310E8 = node;          // push 到链表头
```

**ToolSystem2_001 工厂** (`sub_180115270`): 返回全局单例指针 `&g_CHammerApp`
- 填充 `CHammerApp::vftable[0..5]` = `CHammerApp::vftable`
- 填充 `CToolEventMapRegistrationHelper<CHammerApp>::vftable`
- 填充 `CBindTargetProxy::vftable`
- memset 大量成员变量为 0
- 注册 `atexit(sub_18153DED0)` 清理函数

### 1.2 pet.dll（粒子编辑器）

| 属性 | 值 |
|------|-----|
| imagebase | `0x180000000` |
| CreateInterface | **`0x180370360`** (RVA `0x370360`) |
| 接口链表头 | `qword_1808EAF60` (RVA `0x8EAF60`) |
| 模块标识字符串 | `"particles"` (RVA `0x7F6590`) |

**pet.dll 完整接口列表**:

| 接口名 | 名字 RVA | 名字地址 | 功能 |
|--------|---------|---------|------|
| AssetSystem001 | `0x654860` | `0x180654860` | 资产系统 |
| AssetSystemTest001 | `0x654870` | `0x180654870` | 资产测试 |
| **ParticleSystemMgr003** | **`0x6F6968`** | **`0x1806F6968`** | **粒子系统管理器 ⭐** |
| VScriptManager010 | `0x654888` | `0x180654888` | VScript 脚本 |
| PropertyEditorSystem_001 | `0x6F69A0` | `0x1806F69A0` | 属性编辑器 |
| MATCHFRAMEWORK_001 | `0x6548A0` | `0x1806548A0` | 匹配框架 |
| **SceneSystem_002** | **`0x6F6A78`** | **`0x1806F6A78`** | **场景系统 ⭐** |
| propertyeditor | `0x6F69C0` | `0x1806F69C0` | 属性编辑器（内部） |
| ToolSceneNodeFactory_001 | `0x6F6980` | `0x1806F6980` | 场景节点工厂 |
| toolscenenodes | `0x6F69F0` | `0x1806F69F0` | 场景节点（内部） |
| particles | `0x6F6718` | `0x1806F6718` | pet.dll 模块名 |
| VDataChoice | `0x6F6820` | `0x1806F6820` | 数据选择 |

**注意**: 链表节点 factory 指针在 name 指针 **+8** 字节处（VTable 结构），不是独立函数。工厂初始化由 C++ 构造函数在 DLL 加载时完成。

### 1.3 particles.dll（粒子运行时引擎）

| 属性 | 值 |
|------|-----|
| 状态 | **IDA 已打开** (PID 43740, 端口 13315) |
| CreateInterface | 待查 |

---

## 2. hammer.dll 关键类反编译

### 2.1 CHammerApp vtable (继承自 QObject)

imagebase `0x180000000`，以下均为 RVA:

| idx | RVA | 地址 | 推断功能 |
|-----|-----|------|---------|
| 0 | `0x117940` | `0x180117940` | 默认处理 — 调 `sub_181364B10()`, 返回 bool |
| 1 | `0x118670` | `0x180118670` | **IDA 自动命名 `_DeleteExceptionPtr`** — QObject 虚析构 |
| 2 | `0x1364C20` | `0x181364C20` | **注册 VTOOLSDICTIONARY003** — 字符串查询 |
| 3 | `0x1364BE0` | `0x181364BE0` | 全局状态检查 `qword_1826305C8`, 清理 |
| 4 | `0x1363DC0` | `0x181363DC0` | **主 tick/update 循环** — `Plat_FloatTime()` + `QMetaObject::cast` + vtable[208]/[216] |
| 5 | `0x0753A0` | `0x1800753A0` | `_guard_check_icall_nop` — 空桩 |
| 8 | `0x11F450` | `0x18011F450` | **AddRef** — `*(_DWORD*)(a1+32)++` |
| 11 | `0x1360690` | `0x181360690` | **Create/Init** — 初始化成员 + 调 vtable[192] |
| 12 | `0x11F400` | `0x18011F400` | **Release** — `*a2` 决定释放, 调 vtable[392] 拿内部对象再销毁 |
| 13 | `0x1363E60` | `0x181363E60` | tick 变体 — vtable[200]/[152] + QMetaObject::cast |
| 14 | `0x135F940` | `0x18135F940` | 状态检查 `sub_18135F960()==0` |

**CHammerApp 对象布局** (从 vtable 反编译提取):

| 偏移 | 类型 | 说明 |
|------|------|------|
| +0 | QObject vftable | `CHammerApp::vftable` |
| +32 | DWORD | **引用计数** (vtable[8] 递增) |
| +58 | BYTE | 状态位 (vtable[4] 写 1) |
| +66 | ? | 传给 `sub_1813C0A90` |
| +103 | float | 定时阈值 |
| +112 | BYTE | 标志位 (vtable[4] 设 1) |
| +152 | QObject* | QMetaObject::cast 转换目标 |
| +192 | 虚函数 | create/init 回调 (vtable[11] 调用) |
| +200 | 虚函数 | tick 回调 (vtable[13]) |
| +208 | 虚函数 | tick 回调 (vtable[4]) |
| +216 | 虚函数 | tick 回调 (vtable[4]) |
| +232 | QObject* | 传给 `sub_1808E2FF0` |
| +392 | 虚函数 | Release 时获取内部对象 |
| +408 | BYTE | 启用标志 |
| +412 | float | 定时阈值 |

### 2.2 CMapDoc（地图文档主类）

从 `CMapDoc::FrameUpdate` (RVA `0x775F50`) 反编译提取:

| 偏移 | 类型 | 含义 |
|------|------|------|
| +0 | QObject vftable | 继承自 CHammerApp |
| +112 | Manager* | vtable[672] 回调 |
| +136 | CMapEntity* | 当前选中实体 |
| +288 | ? | 传给 sub_180791F60 / sub_180790F00 |
| +1120 | ? | 传给 sub_1809ECF50 |
| +1312 | DWORD | 待处理实体数组 count |
| +1320 | QWORD | 待处理实体数组 ptr |
| +1328 | DWORD | 数组 capacity |
| +1332 | DWORD | 状态标志 (0xC0000000 mask) |
| +144 | ? | sub_181323D00 参数 |
| +1624 | ? | sub_180A5A120 参数 |
| +1688 | BYTE | FrameUpdate 标志位 |
| +1720 | 物理世界 | sub_1809297E0 初始化 |
| +1992 | Manager* | sub_1808E1F50 处理 |
| +2756 | float | 当前时间戳 |
| +2912 | JobQueue* | 后台线程 job 队列 |
| +3248 | ? | sub_180A5CC80 参数 |
| +3256 | QObject* | vtable[1712] 回调 |
| +3264 | ? | sub_1809ECA40 参数 |

### 2.3 CMapEntity 关键 API

从 `CParticleHelper::SetDefinitionByName` (RVA `0x6E7380`) 反编译:

| 函数 | RVA | 地址 | 签名 |
|------|-----|------|------|
| **IsCMapEntity** | — | — | `vtable[1864](entity, "CMapEntity")` → bool (RTTI) |
| **GetAttribute** | `0x129670` | `0x180729670` | `(entity, name) → const char*` |
| **FindAttributeIdx** | `0x129C50` | `0x180729C50` | `(entity, name, -1) → int` |
| **SetAttribute** | — | — | `(helper, idx, value)` → void |

### 2.4 CUndoManager（撤销/重做）

从 `CUndoManager::Undo` (RVA `0x50B720`) 和 `CUndoManager::Redo` (RVA `0x50B290`):

| 偏移 | 类型 | 含义 |
|------|------|------|
| +0 | vftable | UndoManager 虚表 |
| +0 | int | undo stack top |
| +1 | QWORD* | undo stack base |
| +4 | int | redo stack top |
| +5 | QWORD* | redo stack base |
| +33 | BYTE | 标志位（bit3 控制状态） |

**UndoAction vtable**:
| idx | 功能 |
|-----|------|
| 0 | 执行 Undo/Redo 动作 |
| 32 | `GetName() → const char*` |
| 48 | `ShouldContinue() → bool` |

Undo 动作类型字符串:
- `CUndoCreateElement`
- `CUndoDestroyElement`
- `CUndoAttributeSetValueElement`
- `CUndoAttributeRenameElement`
- `CUndoAttributeArrayCopyAllElement`
- `CUndoAttributeArrayRemoveElement`
- `CUndoAttributeArrayInsertBefore`
- `CUndoAttributeAddRemove`
- 调试输出: `[%d] Pushing undo '%s'`, `[%d] Popping undo '%s'`, `[%d] Aborting undo '%s'`

### 2.5 CParticleHelper（粒子辅助）

**`CParticleHelper::SetDefinitionByName`** (RVA `0x6E7380`, 完整反编译可用):

支持的属性（通过 `V_stricmp_fast` 匹配）:

| 属性名 | 内部位置 | 含义 |
|--------|---------|------|
| `effect_configuration` | a1+176=CUtlString, a1+184=definition* | 粒子效果名 |
| `snapshot_file` | a1+744=CUtlString, a1+752=definition* | 快照文件路径 |
| `snapshot_mesh` | FindAttributeIdx("snapshot_mesh") | 快照 mesh 索引 |
| `data_cp` | a1+764 (int, 0-64) | 数据控制点编号 |
| `data_cp_value` | 通过 FindAttributeIdx 读写 | 数据控制点值 |
| `tint_cp` | a1+768 (int, 0-64) | 染色控制点编号 |
| `tint_cp_color` | 通过 FindAttributeIdx 读写 | 染色颜色 |
| `cpoint%d` | `V_sscanf(name, "cpoint%d", &idx)` → sub_1806E8530 | 任意控制点 |

**粒子定义查找**:
```
CRC64(name) → sub_181200290(&hash, 1717792886) → vtable[320](qword_1826306A0, &hash, name)
```

**全局粒子系统指针**:
| 全局指针 | RVA | 用途 |
|---------|-----|------|
| `qword_1826306A0` | `0x26306A0` | 粒子系统 (vtable[320]=FindParticleDefinition) |
| `qword_1826306A8` | `0x26306A8` | 粒子回收器 (refcount→0 时 vtable[16]=Destroy) |

### 2.6 其他关键字符串

| 字符串 | 地址 | 用途 |
|--------|------|------|
| `VTOOLDICTIONARY003` | `0x181905AB8` | vtable[2] 注册 |
| `CMapEntity` | `0x181593478` | IsCMapEntity 类型检查 |
| `CMapWorld` | `0x1815934E0` | 世界类 |
| `CMapEntityIONode` | `0x181623000` | IO 节点 |
| `CUtlDict<CMapEntity*>` | `0x1816297A0` | 实体字典遍历 |
| `CMapDoc::FrameUpdate` | `0x181629408` | 每帧更新 |
| `Async Simulate Particles` | `0x1816293E8` | 后台粒子模拟 |
| `CMapDocMaterialAdjustStruct` | `0x181630C00` | 材质调整 |
| `materials/error.vmat` | `0x181590640` | 错误材质 |

---

### 2.7 CMapDoc 实例表 & 构造函数（2026-09-21 新增，实测可用）

**`CMapDoc` 构造函数** = `sub_180768860` (RVA `0x768860`)，三个 vtable 分别写在 +0 / +8 / +16
（多继承：`??_7CMapDoc@@6B@` = `0x181628878`，`_0` = `0x1816288B8`，`_1` = `0x1816288D8`）。

构造函数末尾把所有文档实例登记进**全局数组**（这是枚举打开地图的关键）：

```c
// RVA 0x2355020 = 当前文档数 (int)
// RVA 0x2355028 = CMapDoc* 数组指针 (CMapDoc**)
// RVA 0x2355030 = 数组容量 (int)
// RVA 0x2355034 = 分配标志 (int)
g_docs[ g_doc_count++ ] = this;   // 每个元素 8 字节
```

| 全局 | RVA | 绝对地址 | 含义 |
|------|-----|---------|------|
| 文档数组指针 | `0x2355028` | `0x182355028` | `CMapDoc**` |
| 文档数量 | `0x2355020` | `0x182355020` | int |
| 数组容量 | `0x2355030` | `0x182355030` | int |

**CMapDoc 构造函数写入的关键偏移**：

| 偏移 | 值 | 含义 |
|------|-----|------|
| +136 | 0 | 当前选中实体（`CMapEntity*`） |
| +144 | `sub_181323020(...,"Hammer",...)` | Hammer 命名工具/作用域对象 (248B) |
| +288 | `sub_18078F0B0(168B, doc)` | 选择/实体管理器 |
| +1624 | `sub_180A59660(496B, doc)` | **`CDetailPropObjectManager`**（非 CDataModel） |
| +2808 | `sub_1806E5CB0(doc)` | 粒子相关辅助（邻近 `CParticleHelper`） |
| +3248 | `sub_180A5C940(24B, doc)` | JobQueue |
| +1336 | CUtlVector | 待处理实体数组（cap 初始 4096） |

### 2.8 Undo / Redo 调用链（2026-09-21 新增，已确认符号）

| 符号 | RVA | 绝对地址 | 说明 |
|------|-----|---------|------|
| `CUndoManager::Undo` | `0x50B720` | `0x18050B720` | 内部日志字符串 `"CUndoManager::Undo"` 已确认 |
| `CUndoManager::Redo` | `0x50B290` | `0x18050B290` | — |
| `CDataModel::Undo` (wrapper) | `0x4C0B60` | `0x1804C0B60` | vtable `??_7CDataModel@@6B@` @ `0x181587B90` |
| `CDataModel::Redo` (wrapper) | `0x4BEBE0` | `0x1804BEBE0` | 同上表 |

调用链（**关键**，来自 `CDataModel::Undo` 反编译）：

```c
sub_1804C0B60(int* a1) {            // a1 = CDataModel*
    if (sub_18050AD80(a1 + 60))     // CanUndo( CUndoManager* @ a1+240 )
        sub_18050B720(a1 + 60);     // CUndoManager::Undo
    return (*(vtable[1040/8]))(a1); // 通知/刷新
}
```

→ **`CUndoManager` 内嵌在 `CDataModel + 240`**（构造函数 `sub_1804B7090` 中 `sub_18050A3E0(a1 + 240)` 即初始化它）。

#### ✅ 2026-09-21 运行时验证：CDataModel 是全局单例

`sub_18004F500` 是 CDataModel 的**静态初始化函数**：

```c
int sub_18004F500() {
    sub_1804B7090((__int64)&unk_182344140);   // CDataModel::CDataModel(&g_CDataModel)
    return atexit(sub_18153FD80);
}
```

| 全局 | RVA | 绝对地址 | 含义 |
|------|-----|---------|------|
| **`g_CDataModel`** | `0x2344140` | `0x182344140` | CDataModel 全局单例 |

**实测结果**（hammer.dll base = `0x7ffdf53f0000`）：

```
g_CDataModel = 0x7ffdf7734140
  .vtable    = 0x7ffdf6977b90  == base + 0x1587B90 (CDataModel::vftable)  ✅
CUndoManager = 0x7ffdf7734230  (= g_CDataModel + 240)
  undo.count = 0, redo.count = 0
```

**Datamodel(DMX) 的撤销/重做**（注意：⚠️ 这不是地图编辑的撤销，见下方更正）：

```c
CUndoManager* um = (CUndoManager*)((char*)&g_CDataModel + 240);
// 直接调本体
um->Undo();                                  // hammer.dll + 0x50B720
um->Redo();                                  // hammer.dll + 0x50B290
// 或走带 UI 通知的包装
((CDataModel*)&g_CDataModel)->Undo();        // hammer.dll + 0x4C0B60
((CDataModel*)&g_CDataModel)->Redo();        // hammer.dll + 0x4BEBE0
```

> 注：`CMapDoc` 内**不含** CDataModel；`CMapDoc+0x658` 是 CDetailPropObjectManager（已实测确认）。
> `CHammerEditorSession` 位于 `CMapDoc+0xCD0`，其 `+0x738`=CMapDoc、`+0x740/+0x748`=CMapDocHistory、`+0x750`=CMapRootElement。

#### ⚠️ 2026-09-21 更正：g_CDataModel 的 undo **不是**地图编辑的撤销

实测（Hammer 里有 7 步编辑历史时）：

| 检查 | 结果 |
|------|------|
| `CMapDocHistory + 0x08` count | **7** ← 与 Hammer 显示的 7 步历史完全吻合 |
| `g_CDataModel + 240` CUndoManager undo/redo | **0 / 0** |
| 调用 `CDataModel::Undo` 后 `CMapDocHistory+8` | **7 → 7 未变** |

结论：**`g_CDataModel` 的 CUndoManager 是 Datamodel(DMX) 的撤销栈，与地图编辑历史无关**
（它的撤销元素是 `CUndoCreateElement` / `CUndoAttributeSetValueElement<DmElementHandle_t>` 等泛型 DMX 元素）。
`CUndoManager` 构造函数 `sub_18050A3E0` **只有 CDataModel 构造函数一个调用方**，`BeginUndoScope`
(`sub_18050B1C0`，日志 `"[%d] Pushing undo '%s'"`) 也只有一个位于 CDataModel 方法区的调用方
(`sub_1804C0AE0`)，进一步印证 CUndoManager 仅服务于 Datamodel。

**地图撤销历史的真实位置**：

| 项 | 值 |
|----|-----|
| 容器 | `CMapDocHistory` 对象（`CHammerEditorSession+0x740` / `+0x748`，vtable RVA `0x1628508`） |
| 计数 | `CMapDocHistory + 0x08`（int） |
| 数组指针 | `CMapDocHistory + 0x10`（元素 8 字节，实测为堆指针） |
| 容量 | `CMapDocHistory + 0x18`（int） |
| 实测样例 | `count=7 / ptr=0x00c9cf228280 / cap=8` |

`CMapDocHistory` 的虚表只有 4 个方法（RVA `0x75F980`/`0x75FDC0`/`0x760320`/`0x75F9E0`），
其中 `sub_18075FDC0` 引用 RTTI `IUndoable` + `CMapNode` —— 说明地图撤销基于 **IUndoable/CMapNode**，
而非 Datamodel。相关全局：`qword_182354F68`、`qword_182354F70`。

**下一步定位真正的地图 Undo 入口**（建议）：
用 CE（`mcp_ce-mcp`）在 `CMapDocHistory+8` 上下**硬件数据断点**，在 Hammer 里按 Ctrl+Z，
读取命中的指令地址 → 即撤销函数（反向可得 redo）。



**CUndoManager 内存布局**（与 §2.4 一致，`int*` 视角）：

| 偏移 | 类型 | 含义 |
|------|------|------|
| +0 | int | undo 栈顶（条数） |
| +8 | ptr | undo 栈数组基址 |
| +16 | int | redo 栈顶 |
| +24 | ptr | redo 栈数组基址 |
| +132 | byte | 标志位 |

---

## 2.9 地图撤销 / 重做（2026-09-21 CE 硬件断点实测 ✅）

> 用 Cheat Engine 在 VM（`192.168.3.137`）里对 **`CMapDocHistory+8`（历史计数）** 下硬件**写**断点，
> 然后按 Ctrl+Z，捕获到真正的撤销指令。VM 与实体机的 hammer.dll 为同一构建，RVA 通用。

### 实测捕获

```
断点地址 = CMapDocHistory + 0x08   (计数, 4 字节, 写)
命中时:
  RBX  = CMapDocHistory 对象
  RIP  = <写入指令的下一条>   (硬件数据断点陷阱在指令执行后触发)
关键指令:
  0x1408190   FF 4B 08        dec [rbx+08]     ← 撤销：历史计数 -1
```

按下 Ctrl+Z 后，读数验证：`undo.count 8 → 7`、`redo.count 0 → 1` ✅

### 撤销函数

| 项 | 值 |
|----|-----|
| **RVA** | **`0x14080D0`**（IDA `sub_1814080D0`；CE 反汇编首指令在 `0x14080D2`） |
| 结束 RVA | `0x1408248`（IDA 报告大小 `0x178`） |
| 调用约定 | `__fastcall`，**`this` = `CMapDocHistory*`（RCX）** |
| 关键指令 | RVA `0x1408190`: `dec [rbx+08]`（`rbx` = this） |

函数开头逻辑（节选）：

```asm
rva=0x14080d2  sub rsp,20
rva=0x14080d6  cmp byte [7FFE81182088],00   ; 全局开关
rva=0x14080dd  mov rbx,rcx                  ; rbx = this
rva=0x14080e6  cmp dword [rcx+8C],00        ; this->m_bBusy(+0x8C)
rva=0x14080f3  cmp byte  [rcx+90],00        ; this->m_bEnabled(+0x90)
rva=0x1408100  mov rax,[rcx]; call [rax+18] ; 虚调用（CanUndo 类）
rva=0x1408122  call 0x140797950             ; helper
rva=0x1408190  dec [rbx+08]                 ; ← 撤销核心
rva=0x140819c  mov dword [rbx+8C],01        ; 置忙标志
```

### CMapDocHistory 结构（CE 实测）

| 偏移 | 类型 | 含义 |
|------|------|------|
| +0x00 | void* | vtable（RVA `0x1628508` = `??_7CMapDocHistory@@6B@`） |
| +0x08 | int | **历史/撤销栈计数** |
| +0x0C | int | 未知（观测到 0x43e15bcf 之类的 id） |
| +0x10 | void** | 元素数组（每个 8 字节，实测为堆指针） |
| +0x18 | int | 容量 |
| +0x80 | void* | 关联对象（含 `+0x78` 子指针） |
| +0x8C | int | 忙标志（撤销时被置 1） |
| +0x90 | byte | 启用标志 |
| +0xA5 | byte | 某个被拷贝的标志位 |

### CHammerEditorSession 里 CMapDocHistory 的位置

> ⚠️ **实测发现两处偏移不同**，可能是不同 session/构建状态，取地址前请先按 vtable 扫描确认。

| 环境 | CMapDoc | 撤销用 History | redo 用 History | CMapRootElement |
|------|---------|---------------|----------------|-----------------|
| 实体机（`untitled_1.vmap`） | `session+0x738` | `session+0x740` | `session+0x748` | `session+0x750` |
| VM（有 8 步历史） | `session+0x9B8` | `session+0x9C0` | `session+0x9C8` | `session+0x9D0` |

→ **推荐做法**：不硬编码偏移，而是扫描 `CHammerEditorSession` 对象前 0x1000 字节，
找「目标首 8 字节 == `hammer.dll+0x1628508`」的两个指针（第一个=撤销历史，第二个=重做历史）。

### 调用方式（✅ Undo/Redo 共用同一个函数）

**关键结论**：`RVA 0x14080D0` 是通用的「**从传入的历史对象弹出最新一条并应用其反操作**」函数，
Hammer 的撤销和重做**调用的是同一个函数**，靠传入的 `this` 区分：

| 操作 | 传入的 this | 实测证据 |
|------|-------------|---------|
| **撤销** | 撤销历史对象（`session+0x9C0`） | 硬件断点命中 `dec [rbx+08]`，`RBX = 撤销历史` |
| **重做** | 重做历史对象（`session+0x9C8`） | 换到 redo 计数上下断点后，`Ctrl+Y` 命中**同一条指令** `dec [rbx+08]`，`RBX = 重做历史 (0x5C427081100)` |

函数内部会把弹出的条目转交给**配对历史**（`*(this+128)` 指向的对象），所以撤销会把条目推进
redo 栈、重做会推回 undo 栈，形成标准的一对栈。

IDA 反编译（`sub_1814080D0`）：

```c
void __fastcall MapHistoryPop(CMapDocHistory* a1)   // a1 = 要弹出的历史对象
{
  if (byte_1820F2088 && !a1[140] && a1[144] && a1->vtable[3](a1)) {
      last = a1->count ? a1->array[a1->count - 1] : 0;
      sub_1814074E0(a1[128], last + 36, 1, 0);   // 通知配对历史/UI
      --a1->count;                                // ← CE 捕获到的 dec [rbx+8]
      ...                                          // 逐个应用该条目的反操作
      sub_1814068B0(last); sub_1802B9A30(last, 192);  // 释放条目
  }
}
```

调用方 `sub_180760320`（CMapDocHistory 的虚方法，vtable[2]）是「跨多个历史对象分发」的包装。

C++ 等价：

```cpp
typedef void (__fastcall *MapHistoryPopFn)(void* history);
auto pop = (MapHistoryPopFn)(hammer_base + 0x14080D0);
pop(undoHistory);   // 撤销
pop(redoHistory);   // 重做
```

MCP 侧（`call_function`）：

```
call_function("hammer.dll+0x14080D0", [undoHistoryPtr])   # 撤销
call_function("hammer.dll+0x14080D0", [redoHistoryPtr])   # 重做
```

### 定位历史对象（不要硬编码偏移）

见 §2.9 上表「CHammerEditorSession 里 CMapDocHistory 的位置」——实体机与 VM 偏移不同，
稳妥做法是**扫描**：取 `CMapDoc+0xCD0` 得到 session，在其前 `0x1000` 字节里找
「目标首 8 字节 == `hammer.dll+0x1628508`」的指针，按偏移升序取前两个（第一个=撤销，第二个=重做）。

已实现：`mcp_server/cs2_mcp_server.py` 的 `cs2_map_undo` / `cs2_map_redo`。

### ⚠️ 关键约束：必须从 **Hammer 主线程**调用（2026-09-22 实测）

从我们 DLL 的**管道线程**直接调 `RVA 0x14080D0` 会：

| 现象 | 说明 |
|------|------|
| 撤销**实际生效** | 计数器 `undo 8 → 7`、`redo 0 → 1` ✅ |
| 但函数**永不返回** | 管道线程卡死，之后所有 IPC（连 `ping`）都无响应 |
| 历史被留在 busy 态 | `CMapDocHistory+0x8C` 保持 1 → 后续 Ctrl+Z 被静默忽略（`Responding=True`，主线程没死锁） |

→ 该函数内部依赖主线程（Qt/GUI 亲和）。**凡会改文档/UI 的调用都必须走主线程。**

**DLL 侧实现**（`hammer_bridge.cpp`）：`CallFunctionOnMainThread()`

```text
1. 找主线程：EnumWindows 取本进程第一个「可见且无 owner」窗口的线程 ID；
   找不到则退化为 Toolhelp 快照里最早创建的线程。
2. 挂一个临时 WH_GETMESSAGE 钩子到该线程（SetWindowsHookEx(..., hModule, tid)）。
3. PostThreadMessageW(tid, WM_NULL, 0, 0) 踢一下消息循环。
4. 钩子过程在**主线程**上下文里执行调用桩、SetEvent 唤醒调用方。
5. 调用方 WaitForSingleObject(超时) → 摘钩子。
```

IPC 侧：`call_function` / `cs2_call_function` 新增 **`on_main_thread`** 参数（默认 false），
`cs2_map_undo` / `cs2_map_redo` 已固定走主线程（`timeout_ms=15000`）。

#### ✅ 派发链路自检（`main_thread_selftest`）

为避免再拿 Hammer 的函数「盲试」把进程搞挂，DLL 里加了一个**零风险自检**：
只调用 **DLL 内部**的无害函数（返回魔数 `0x43533254434F4445`），完全不碰 Hammer 代码。

实测（VM 内，Hammer PID 2768）：

```json
{ "main_thread_id": 220, "pipe_thread_id": 10736, "different_threads": true,
  "main_thread_status": 0, "ret_hex": "0x43533254434f4445",
  "expected_ret_hex": "0x43533254434f4445" }
```

→ 钩子确实在主线程（220）执行、结果正确回传、命令**立即返回不卡**。机制本身没问题。

#### 上次崩溃的真因（重要教训）

之前「调用后 Hammer 卡死/退出」并不是派发机制的问题，而是**我盲选了一个需要有效参数的函数**：
拿 `RVA 0x1406F90` 当「无参小函数」调用，实际传 `rcx=0` → 函数解引用空指针 → **访问违例**；
当时钩子过程**没有异常保护**，异常把宿主主线程一起带走，客户端就一直等一个永远不会来的响应。

已修复：钩子过程用 `__try/__except` 包住调用 → 异常被记为 `main_thread_status=4`，
**宿主进程不受影响**，调用方也能正常拿到结果。

`call_function` 响应新增 `main_thread_status`，取值：
`0=成功 1=等待超时 2=未找到主线程 3=SetWindowsHookEx 失败 4=调用中触发异常`。

> 教训：**不要拿不认识的函数当冒烟测试**。先用自检验证机制，再用已知签名的函数验证功能。

#### ✅ 端到端功能验证通过（VM 内实测）

在 VM 的 Hammer（PID 2768，地图有 5 步历史）上验证，**全部立即返回、无卡顿**：

| 命令 | undo 历史 | redo 历史 | 目标 this |
|------|-----------|-----------|-----------|
| `map-undo` | 5 → 4 | 0 → 1 | `0x57073c9d400`（撤销历史） |
| `map-redo` | 4 → 5 | 1 → 0 | `0x57073c9d900`（重做历史） |
| `map-undo` | 5 → 4 | 0 → 1 | 撤销历史 |

→ `on_main_thread=True` 是正解：同一函数**从管道线程调用会挂死，从主线程调用正常返回**。

> 返回值的观察：函数返回的是**配对历史**的指针（撤销时返回 redo 历史指针，反之亦然）。

**结论：`cs2_map_undo` / `cs2_map_redo` 已可用。**

> 顺带修掉一个编译坑：源码是 UTF-8 且含中文注释，而 MSVC 默认按本地代码页(936)解码
> → 中文注释被错误切分导致 `C2187/C3484` 等语法错。已在 `CMakeLists.txt` 加 `/utf-8`。

---

### 2.11 场景节点遍历 & 实体枚举（2026-09-22 新增）

#### 场景树布局（CMapNode 基类，CMapWorld / CMapEntity 共用）

| 偏移 | 类型 | 含义 | 实测证据 |
|------|------|------|---------|
| +408 (`0x198`) | `CMapNode*` | **父指针** | `sub_18074AE00(a1) = *(a1+408)`；沿它上溯到 vtable[248] 为真的节点（world） |
| +504 (`0x1F8`) | `int` | **子节点数** | `sub_180745F10` 里 `*(a1+504)` |
| +512 (`0x200`) | `int32*` | **子节点句柄数组** | `*(a1+512)`，按 4 字节步进取值 |

> 实测（VM，空地图）：`CMapEntity+408 = CMapWorld`；`CMapEntity+504 = 0`、`+512 = 0`（叶子）。
> ⚠️ 注释：此前提到的「CMapDoc+136 = 当前选中实体」应更正为 **`CMapDoc+136 = CMapWorld*`**（已用 vtable 校验：`0x163B028` = `??_7CMapWorld@@6B@`）。

#### ⭐ 引擎自带的按类名枚举：`sub_180745F10`（RVA `0x745F10`）

```c
// 语义（IDA 反编译 sub_180745F10 归纳）
void EnumElements(CMapNode* node, CUtlVector<void*>* out,
                  const char* className, int flags, int recurse);
```

工作方式：
1. 取 `node->m_ChildrenCount`（+504）与 `node->m_ChildHandles`（+512，每项 4 字节句柄）。
2. 每个句柄用 `(*(off_18207E5D8 + 168))(off_18207E5D8, handle)` 反查成 `CDmElement*`
   （`off_18207E5D8` = RVA `0x207E5D8`，句柄→元素台账）。
3. 过滤后 `AddToTail` 到调用方给的 CUtlVector。
4. `!recurse && !(flags & 0x40)` 时对该子节点递归（每个节点都有自己的一份 +504/+512）。

`flags` 位（从反编译归纳）：

| 位 | 含义 |
|----|------|
| 1 | 跳过 `CMapWorld` 类型的节点 |
| 2 | 配合位1：世界节点也要过 `sub_180867F60()` 判断 |
| 4 | 有子节点（`sub_18074A850>0`）的节点跳过 |
| 8 | 用 `vtable[1864]`（类名==symbol 的精确判定）判类，否则用 `vtable[936]`（派生类也匹配） |
| 0x10 | `vtable[376]` 为真的节点跳过 |
| 0x20 | 只收 `node[872] != 0` 的节点 |
| 0x40 | 不递归 |

`className == NULL` → 不做类名过滤（全收）。

> 🔴 **重要更正（2026-09-22 实测）**：`className` 参数**不是 `const char*`，而是指向
> 「驻留符号（`CUtlSymbolLarge`）」的指针**——调用方传的是 `off_1820A7AA8` 这种全局符号变量的地址
> （IDA 只是把它注释成了 `"CMapInstance"` 字符串）。传 C 字符串**永远匹配不上**：
> 实测 `classname` 传 `CMapEntity` / `info_player_start` / `CMapWorld`，`flags` 传 0 或 8，
> **全部返回 0**；而传 `NULL`（不加过滤）能正确返回 6 个节点。
> → **正确做法：传 NULL 全枚举，再在本地按 `vtable` 或属性过滤。**

**调用方法**（已实现在 `cs2_entity_list` / `enum_elements`）：
在目标进程里摆一个空的 CUtlVector 交给它填：

```text
1. alloc_memory 拿一块暂存区
2. write_memory 写 CUtlVector 头 {size=0, pad, mem=buf+0x40, alloc=capacity, flags=0}
3. call_function(hammer.dll+0x745F10,
                 [world, buf, 0 /*className=NULL*/, flags, 0], on_main_thread=true)
4. 读回 buf+0(size) / buf+8(mem)，逐个取 8 字节元素指针
```

#### ✅ 端到端验证通过（2026-09-22，VM 内，地图有实体）

`python vm_pipe.py enumerate`（classname 空 → NULL）：

```
world=0x378d8c0f000 classname='' flags=0 -> 6
  [0] 0x00000378dc9f8000   ← vtable = base+0x1630140（非 CMapEntity，世界/图层类节点）
  [1] 0x00000378df29e000   ← vtable = base+0x161C548 = ??_7CMapEntity@@6B@
  [2..5] ...               ← 同上
```

`cs2_entity_list`（全枚举 + 按 vtable 过滤 + 读 classname）：

```
实体数: 5（场景节点总数 6，CMapDoc=0x378dcb94010, CMapWorld=0x378d8c0f000）

[  0] 0x00000378df29e000  info_player_start
[  1] 0x0000037805c42800  info_player_counterterrorist
[  2] 0x0037805c44400     info_player_terrorist
[  3] 0x0000037805c46000  info_player_terrorist
[  4] 0x0000037805c47c00  env_combined_light_probe_volume
```

属性 API 也一并验证：

| 调用 | 结果 |
|------|------|
| `GetAttribute(ent, "classname")` (RVA `0x729670`) | `'info_player_start'` ✅ |
| `FindAttributeIdx(ent, "classname", -1)` (RVA `0x729C50`) | `0` ✅ |
| `FindAttributeIdx(ent, "no_such_attr_xyz", -1)` | `-1` ✅ |
| `GetAttribute(ent, "origin")` | 空指针（该实体没有 `origin` 属性，位置走 `Transform`） |

> 注意 `CMapWorld+504` 在空地图上确实是 **0**，有实体时变成 **6** —— 印证了它就是子节点数。


#### Source 2 `CUtlVector`（x64）布局（重要，很多 API 要用）

```text
+0x00 int  m_Size
+0x04 int  (padding，未初始化)
+0x08 T*   m_pMemory
+0x10 int  m_nAllocationCount
+0x14 int  m_nGrowFlags      // 高 2 位表示"外部内存/不可自行释放"
```

实证：`sub_18076CB40` 里三个相邻栈变量 `v31(=0) / v32(=堆缓冲) / n1024(=1024)`
正好落在这个布局上，被当作 `CUtlVector*` 传给 `sub_180745F10`。

#### 其他相关发现

| 项 | 结论 |
|----|------|
| `CMapDoc+0x138` | `CUtlDict<CMapEntity*, CDefFastCaselessStringLess>`（`sub_180784620` 用 `a1+312` 插入）。**运行时为空** → 这是"具名/特定筛选"实体的字典，不是全量实体列表 |
| `CMapWorld+0x18C8` | 200 个 **24 字节 CUtlVector** 组成的数组（构造函数 `sub_180861CF0` 依次置空），即 200 个 `CUtlVector<void*>` |
| 实体自指针 | `CMapEntity+448` 存着指向自己的指针（+392 处又有 `{ptr,4}`）→ 疑似侵入式链表节点 |
| `CMapWorld` 构造 | `sub_180861CF0`（写 vtable `0x163B028`）；析构/相关 `sub_1808620C0` |

#### ⚠️ 工具链踩坑（本轮新增）

| 坑 | 说明 / 规避 |
|----|------------|
| CE `aob_scan` 结果不可全信 | 会返回 `0x29Exxxxxxx` 这类**不可读**地址（DLL/CE 都读不出）→ 命中地址必须回读校验 |
| 交互桌面分辨率 | Session 1 实际是 **1718x1038**（Session 0 的 `Screen::AllScreens` 报 1024x768，别用） |
| schtasks 控制台抢焦点 | `powershell -NoProfile -WindowStyle Hidden ...`，否则截屏全是控制台窗口 |
| 菜单截图拍不到 | 截屏本身走 schtasks，会抢焦点 → 刚弹出的菜单又关掉；键盘 Alt+X 同理 |
| `AppActivate` | 必须**在 Session 1 里**执行（Session 0 的 SSH 进程激活不了交互桌面窗口）→ `vm_ui.py activate <标题>` |

---

### 2.12 实体属性写入 & Datamodel Undo（2026-09-22 新增，VM 实测通过 ✅）

#### 实体属性其实存在 Datamodel(DMX) 里

`CMapEntity` 不是 `CDmElement`，而是"持有 element 句柄"的包装：

| 项 | 说明 |
|----|------|
| `CMapEntity + 1328` (`0x530`) | 所属 `CDmElement` 的句柄（`DmElementHandle_t`，32 位） |
| 句柄 → 元素 | `g_CDataModel` vtable[21]（字节偏移 168）= `GetElement(handle)` |

`GetAttribute(entity, name, out)`（RVA **`0x729670`**）实际做的事：

```c
const char* GetAttribute(CMapEntity* self, const char* name, CDmAttribute** out)
{
    CDmElement* e = g_CDataModel->GetElement(*(uint32*)((char*)self + 1328));
    for (CDmAttribute* a = FirstAttribute(e); a; a = a->m_pNext /*+0*/)
        if (!V_stricmp_fast(a->m_pName /*+0x20*/, name))
            { if (out) *out = a; return GetValueAsString(a); }
    if (out) *out = 0;
    return 0;
}
```

**`CDmAttribute` 布局（x64）**：

| 偏移 | 类型 | 含义 |
|------|------|------|
| +0x00 | `CDmAttribute*` | 链表 next |
| +0x08 | `char**` | 值（字符串类型是"指向 interned `char*` 的指针"） |
| +0x10 | `CDmElement*` | 所属元素 |
| +0x1C | `uint32` | **低 6 位 = 类型**（`5` = AT_STRING）；bit6 = 禁止修改等标志 |
| +0x20 | `const char*` | 属性名 |

`GetValueAsString`（RVA `0x72C630`）只处理 AT_STRING：`*(char**)*(a+8)`，空则返回全局空串 `unk_181C8FBEC`。

#### 写字符串属性：必须传「驻留符号（CUtlSymbolLarge）」

`CDmAttribute::SetValue<CUtlSymbolLarge>`（模板实例，RVA **`0x4C7A10`**，IDA `sub_1804C7A10`）：

```c
void SetValue_Symbol(CDmAttribute* a, CUtlSymbolLarge const* pSym)
{
    if ((a->m_nFlags & 0x3F) != 5) return;          // 非 AT_STRING
    if (*(char**)*(a + 8) == *pSym) return;         // 值没变
    if (a->m_nFlags & 0x40) return;                 // 禁止修改标志
    ... 通知所属 element 属性将变 ...
    if (IsUndoEnabled(g_CDataModel, a->m_pElement /*+0x10*/)) {
        创建 CUndoAttributeSetValueElement 并 PushUndo;
    }
    **(char***)(a + 8) = *pSym;                     // ★ 真正写值
    sub_1804E2830(a, 0, 0);                         // 变更后处理
}
```

`CUtlSymbolLarge` 在内存中就是一个 `const char*`（驻留字符串指针）。

**完整写入链路**：

```text
1. GetAttribute(entity, name, &attr)                       -> CDmAttribute*   (RVA 0x729670)
2. g_CDataModel->InternString(value)                       -> symbol          (vtable 字节偏移 424)
3. SetValue<CUtlSymbolLarge>(attr, &symbol)                -> 写值            (RVA 0x4C7A10)
```

> ⚠️ 直接调第 3 步**不会**记录任何撤销（实测 DMX 栈与地图历史计数都不变）——
> 因为不在 undo scope 内时 `IsUndoEnabled` 返回 false。

#### `IsUndoEnabled` 的两个条件

| 函数 | 地址 | 含义 |
|------|------|------|
| `IsUndoEnabled_Global` | CDataModel vtable[64] = RVA `0x4BDD00` | `return (*(BYTE*)(dm + 372) & 8) != 0;` ← **undo 总开关** |
| `IsUndoEnabled(dm, e)` | CDataModel vtable[65] = RVA `0x4C0BD0` | `vtable[64](dm) && e && *(int*)((char*)e + 88) != -1` |

| 项 | 地址 | 实测值 |
|----|------|--------|
| **undo 总开关** | `CDataModel + 372` = `CUndoManager + 132` 的 **bit3** | **Hammer 平时是 `0x00`（关）** |
| element 的 undo scope id | `CDmElement + 88` | `-1` = 不在任何 scope 中 |

#### Datamodel undo scope API（`CUndoManager` 内嵌在 `g_CDataModel + 240`）

| 函数 | RVA | 签名 / 说明 |
|------|-----|------------|
| `BeginUndoScope` | **`0x50B1C0`** | `(um, const char* name, const char* desc, int flags)`；日志 `"[%d] Pushing undo '%s'"` |
| `EndUndoScope` | **`0x50B0D0`** | `(um) -> bool`（scope 内是否有操作提交）；日志 `"[%d] Popping undo '%s'"` |
| `PushUndoElement` | CDataModel vtable[82] = `0x4B85A0` → `sub_18050A7F0` | 把 `IUndoElement*` 追加到 `um+8` 数组（日志 `"AddUndoElement '%s'"`） |
| `Undo` | `0x50A590`（另一份 `0x50B720`） | 日志 `"CUndoManager::Undo"`；`um+132 bit3 == 0` 时直接返回 |

`CUndoManager + 84` = scope 嵌套深度（Begin `+1` / End `-1`）；
`+96` = 当前 scope 名（symbol）、`+128` = 本次 scope 累计元素数。

#### ✅ 实测结果（VM，Hammer PID 10944）

| 步骤 | 结果 |
|------|------|
| `setattr`（不包 scope） | 属性值**已变**，但 DMX 栈 `0`、地图历史也不变 |
| 读 `CUndoManager+132` | `0x00` → **undo 总开关是关的** |
| 置 `bit3 = 1` + `BeginUndoScope` + `SetValue` + `EndUndoScope` | DMX undo `0 -> 1` ✅ |
| `CDataModel::Undo` | `undo 1 -> 0`、`redo 0 -> 1`，**属性值回滚成功** ✅ |
| Hammer 里按 **Ctrl+Z** | 不动 DMX 栈（地图历史仍 `6/1`）→ **两套栈互相独立** |

> **结论**：`CDmAttribute::SetValue` 的撤销只会进 **Datamodel(DMX) 撤销栈**，
> 而 Hammer 的 Ctrl+Z 操作的是 `CMapDocHistory`（见 §2.9）。
> 所以 `cs2_entity_set_attr` 的撤销入口是 **`cs2_undo`**，不是 Ctrl+Z。
>
> `cs2_entity_set_attr` 的实现（`mcp_server/cs2_mcp_server.py`）：
> 先 `_ensure_undo_enabled()` 把总开关打开，再用 `Begin/EndUndoScope` 包住 SetValue。

#### 附带确认：Hammer 会感知到属性修改

改完属性后 Hammer 标题变成 `Hammer - [untitled_1.vmap *]`（多出 `*` 表示有未保存修改），
说明 DMX 的属性变更通知链路是通的（视图/文档状态会同步），不是"只改了内存里的影子值"。

#### 相关地址速查（本轮新增）

| 名称 | RVA | 说明 |
|------|-----|------|
| `GetAttribute` | `0x729670` | `(entity, name, out_attr) -> const char*` |
| `FindAttributeIdx` | `0x729C50` | `(entity, name, default) -> int` |
| `GetValueAsString` | `0x72C630` | 仅处理 AT_STRING |
| `CDmAttribute::SetValue<CUtlSymbolLarge>` | `0x4C7A10` | 写字符串属性（含 undo 记录） |
| `CDataModel::InternString` | vtable 字节偏移 `424` | `char* -> CUtlSymbolLarge` |
| `CDataModel::GetElement` | vtable 字节偏移 `168` | `handle -> CDmElement*` |
| `CDataModel::PushUndoElement` | vtable 字节偏移 `656` = `0x4B85A0` | |
| `IsUndoEnabled_Global` | vtable 字节偏移 `512` = `0x4BDD00` | `CDataModel+372` bit3 |
| `IsUndoEnabled` | vtable 字节偏移 `520` = `0x4C0BD0` | |
| `CUndoManager::BeginUndoScope` | `0x50B1C0` | |
| `CUndoManager::EndUndoScope` | `0x50B0D0` | |
| `CUndoManager::Undo` | `0x50A590` / `0x50B720` | |
| `CDmAttribute` 类型偏移 | `+0x1C` | 低 6 位；`5` = AT_STRING |
| `CUndoManager` undo 总开关 | `+132` bit3 | Hammer 平时为 0 |

---

### 2.13 CMapDoc 地图路径（2026-09-22 实测 ✅）

| 偏移 | 类型 | 含义 |
|------|------|------|
| `CMapDoc + 0x6A0` (1696) | `CUtlString`（+0 就是 `char*`） | **地图全路径** |

VM 实测（Hammer 打开 `untitled_1.vmap`）：

```text
qword(CMapDoc + 0x6A0) = 0x378e2fac600
read_string(0x378e2fac600) =
  c:/program files (x86)/steam/steamapps/common/counter-strike global offensive/content/csgo_addons/test/maps/untitled_1.vmap
```

**定位方法**：把 `CMapDoc` 前 `0x3000` 字节按 8 字节步进，逐个把值当指针读字符串，
筛出含 `.vmap` 的那个 —— 对应脚本 `vm_pipe.py scan-str <base> <size_hex> <needle>`。

> ⚠️ **更正**：此前 PROGRESS 里记的 `CMapDoc+2640` 实测为 0，是错的；正确偏移是 **`0x6A0`**。
> 已据此实现 `cs2_map_info`（路径 / 文件名 / CMapDoc / CMapWorld / 撤销栈深度）。

---

### 2.14 Qt UI 自动化：直接点击 Hammer 按钮（2026-09-22 VM 实测成功 ✅）

新版 CS2 的 `cs2.exe -tools` 只进 **Mod Tools 启动器（Asset Browser）**，**不再自动加载**
`tools\hammer.dll` —— 要进 Hammer 必须在启动器里**点 Hammer 图标**。
（`tools\hammer.dll` 本身没变，与旧版 MD5 一致，所以本项目全部 RVA 依然有效。）

与其猜鼠标坐标（VM 上还容易触发 `Stall Detected`），不如直接调 Qt：
**注入 DLL → 用 Qt5 导出符号枚举控件 → 直接触发 click**。

#### 符号定位

Qt5 的 DLL 以 mangled 名**导出全部 public 符号**，所以 PE 导出表就能拿到 RVA。
工具：`injector/qt_exports.py`（**必须跳过 forward export** —— 其 RVA 落在导出目录内，指向 `DLL.func` 字符串）。

| 模块 | 符号 | RVA |
| --- | --- | --- |
| Qt5Widgets | `QApplication::allWidgets()` | `0xE270` |
| Qt5Widgets | `QAbstractButton::text()` | `0xE0900` |
| Qt5Widgets | `QAbstractButton::click()` | `0xDE8C0` |
| Qt5Widgets | `QWidget::toolTip()` | `0x4AE60` |
| Qt5Widgets | `QWidget::windowTitle()` | `0x4C460` |
| Qt5Core | `QObject::inherits(const char*)` | `0x290560` |
| Qt5Core | `QMetaObject::className()` | `0x1D6140` |

#### ⚠️ 两个会直接崩进程的 ABI 陷阱

1. **非平凡返回类型（QString / QList）必须由调用方提供「隐藏返回缓冲区」**，
   否则函数往垃圾地址写返回值 → 崩。`QString` 即使只有 8 字节也一样。
2. **这个缓冲区在 `rdx`，不是 `rcx`**（与 MSVC 文档描述相反）。
   反汇编 `QAbstractButton::text()` 开头：
   `mov rbx,rdx`（保存缓冲区）+ `mov rdx,[rcx+8]`（取 `this->d_ptr`）
   → **rcx = this，rdx = 缓冲区**。
   调用形式：`args = [this, retbuf]`。
   （`QApplication::allWidgets()` 是无参静态函数，形式为 `args = [retbuf]`。）

#### QList 布局（`allWidgets()` 的返回值）

`QList<QWidget*>` 的 d 指针指向 `QListData::Data`：

```
+0x00 ref(4) | +0x04 alloc(4) | +0x08 begin(4) | +0x0C end(4) | +0x10 array[1]
```

元素数 = `end - begin`；**第 i 个元素 = `*(d + 0x10 + 8*(begin+i))`**。
> 坑：`d + 0x10` 处**存的不是数组指针**，而就是元素 0 的值 ——
> Qt 的 `at(i)` 即 `d->array + d->begin + i`（`array` 是内嵌数组名）。当成二级指针读会读出垃圾。

#### QString 读取

`d` 指针指向 `QStringData`：`+0x04 size(4)`、`+0x10 offset(int64)`；
字符 = `(char*)d + offset` 处、`size` 个 UTF-16 code unit。

#### 完整流程（`vm_pipe.py` 子命令）

```powershell
python vm_pipe.py qt-types                 # 列所有 widget 的类名（只用平凡返回类型，安全）
python vm_pipe.py qt-buttons               # 列按钮的 toolTip / text —— 找目标按钮
python vm_pipe.py qt-str <widget> <rva>    # 读任意返回 QString 的成员函数
python vm_pipe.py qt-click <widget>        # 调 QAbstractButton::click()
```

实测：`allWidgets()` 返回 **441 个 widget**，其中

```
[231] 0x03056e856730  tip='Hammer (Map Editor)'  text='Hammer (Map Editor)'
```

对它调 `click()`，`hammer.dll` 随即被加载（模块数 0 → 1），Hammer 界面正常出现。

> 同类按钮还有 `Particle Editor` / `ModelDoc Editor` / `Material Editor` /
> `Counter-Strike 2 Workshop Manager` —— 说明**这套 Qt 方法可以启动任意子工具**，
> 后续的菜单、对话框自动化也能复用。

#### 菜单项：QAction 不是 widget，要经 `QWidget::actions()`

菜单栏 / 菜单的子项是 **`QAction`**，`allWidgets()` 拿不到 —— 必须：

```
QMenuBar(QWidget) --QWidget::actions()--> QList<QAction*> --QAction::text()--> 文本
                                                          --QAction::menu()--> 子菜单 QMenu
                                                          --QAction::trigger()--> 执行
```

| 模块 | 符号 | RVA |
| --- | --- | --- |
| Qt5Widgets | `QWidget::actions()` | `0x32E70` |
| Qt5Widgets | `QAction::text()` | `0xB340` |
| Qt5Widgets | `QAction::trigger()` | `0xBBC0` |
| Qt5Widgets | `QAction::menu()` | `0x8010` |

```powershell
python vm_pipe.py qt-menu                      # 列 QMenuBar 及其顶层菜单项
python vm_pipe.py qt-actions <menu_addr>       # 列某个 QMenu 的子项
python vm_pipe.py qt-trigger <action_addr>     # 触发菜单项
```

Hammer 的 File 菜单实测内容（节选）：

```
'&New\tCtrl+N'          '&Open\tCtrl+O'        '&Recent Files'  <- 有子菜单
'&Save\tCtrl+S'         'Save &As...\tCtrl+Shift+S'
'Import File...'        '&Build map...\tF9'    'E&xit'
```

**实测：直接 `qt-trigger` 的 `&New`（`0x0304a097cf90`）会立刻建好一张地图**
（`untitled_1.vmap`），且**不会阻塞主线程派发** —— 后续的 `map-info` / `entities` 照常工作。

> 这条路比模拟键盘可靠：Hammer 不理会 `keybd_event` 发的 `Ctrl+N`/`Ctrl+O`（焦点问题），
> 但直接 trigger `QAction` 一次成功。
> **注意**：`&Open...` 会弹模态文件对话框并**阻塞主线程**（派发机制会一直 busy），
> 所以优先用 `&New`、`&Recent Files` 这类不弹窗的项。

#### 模拟键盘：必须抢到前台，且「置前 + 发键」要在同一个任务里

`WScript.Shell.AppActivate` **不保证**抢到前台（Windows 前台锁 + 后台任务场景），
必须 `AttachThreadInput` 绕过前台锁再 `SetForegroundWindow` + `SetFocus`。

更关键的是：**置前和发键不能分成两个 schtasks 任务** ——
每个任务都会新起一个 `powershell.exe`，它的窗口会把前台抢回去，
结果按键全打在控制台上。实测证据：

```
OK key ctrl+z -> fg='C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.EXE'
```

为此新增 `keyto <窗口标题> | <按键>` 指令，在**同一个 ps1 进程内**先置前再发键：

```powershell
python vm_ui.py keyto "Hammer - [ | f9"
# -> OK keyto ... -> fg='Build Map untitled_2.vmap' combo='f9'
#    （F9 = File->Build map，弹出对话框即证明按键真的送达了 Hammer）
```

> 结论：需要模拟键盘时优先 `keyto`，不要 `activate` + `key` 分两步。

#### ⚠️ ps1 里的中文注释会把下一行代码「吞掉」

Windows PowerShell 5.1 读取**无 BOM 的 UTF-8** `.ps1` 时按 ANSI/GBK 解码，
中文注释中的字节被误解析后，**紧跟其后的代码会被并进注释**。

本例中这行导致 `$rest` 从未被赋值（恒为空），`key` / `activate` 因此全部失效
（连注释都显示成了 `...（窗口标题可能含空格）�?  $rest = if ...`）：

```powershell
  # $rest 取第二个 token 起的全部内容（窗口标题可能含空格，如 "Hammer - [map.vmap]"）
  $rest = if ($t.Count -gt 1) { ... }     # <-- 被上一行吞掉，从未执行
```

**两个修法（建议都做）**：
1. 脚本存为 **UTF-8 with BOM**（Python `encoding='utf-8-sig'`），PowerShell 便按 UTF-8 解码；
2. 注释独立成行，且尽量用 ASCII。

#### ⚠️ `QAction::trigger()` 在钩子上下文里会「永不返回」（2026-09-24 实测）

`cs2_map_save` 用 trigger 触发 `File → Save` 时，`trigger()` 一直不返回
（`main_thread_status=1` 超时），而且**没有**出现任何对话框窗口。

原因：主线程派发是在 `WH_GETMESSAGE` 钩子（消息处理回调）里执行目标函数的，
而 `trigger()` → 槽函数 → **弹模态对话框**时会开启**嵌套消息循环**。
嵌套循环仍会派发消息（所以后续调用还能用，实测 `map-info` 正常），
但 `trigger()` 自身要等对话框关闭才返回 —— 表现为永久超时。

**教训**：`qt-trigger` 只适合**不会弹窗**的菜单项（`&New` 已验证）；
凡「可能弹窗 / 长时间阻塞」的操作（Save / Save As / Build / Open）
都不能靠 trigger 实现。

**配套的坑**：`&New` 建出的地图只有**内存中的虚拟路径**
（`config:.../csgo_addons/test/maps/untitled_1.vmap`），磁盘上**并不存在**该文件
（实测该目录下只有 `cs_script_demo.vmap`）。所以 `map-info` 报的路径
不能当作「文件已存在」的证据；这类地图调 Save 必然要走「指定文件名」流程。

#### ⚠️ 性能：主线程派发是「串行槽位」机制，调用密度要控制

- `allWidgets()` 在**打开地图后**返回 **5400+** 个 widget（未开图时约 1900）
- 每个 `on_main_thread` 调用都要「设置共享槽位 → 等钩子执行 → 取结果」，
  短时间内发太多会**积压并超时**
- 因此遍历 widget 时应：**先用 `read_memory`（不走主线程）读 vtable 去重**，
  只对每种类型问一次 `inherits`；并优先用 `topLevelWidgets()`（实测 299 个）
  而非 `allWidgets()`（5400+）
- 优化后 `_qt_find_menu_action` 的调用序列（实测日志）：
  `topLevelWidgets`(1) → 读 299 个 vtable（不走主线程）→ `inherits`(46，已去重)
  → `menuBar`(2) → `actions`(2) → `text`(10) → 命中 `&Save`

#### 僵尸进程（必须跳过）

CS2 崩溃后 PID 会残留成僵尸：`HandleCount=0`、**枚举不到任何模块**，
注入与管道调用都会假失败（`WaitNamedPipe err=121`）。判据见 `inject_dll.py::_is_zombie`：

```python
h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
# 必须声明 argtypes，否则 64 位 HANDLE 被当 int 截断，调用恒失败
psapi.EnumProcessModules(h, buf, sizeof(buf), byref(needed))
return (not ok) or needed.value == 0
```

## 3. 全局单例接口汇总

| 全局指针 | RVA | 地址 | 类型 | 用途 |
|---------|-----|------|------|------|
| hammer.dll: | | | | |
| `qword_1826310E8` | `0x26310E8` | `0x1826310E8` | 链表头 | CreateInterface 注册表 |
| `off_18207E5D8` | `0x207E5D8` | `0x18207E5D8` | 日志接口 | vtable[1000]=log_start, [1008]=log_end |
| `qword_1826306A0` | `0x26306A0` | `0x1826306A0` | 粒子系统 | vtable[320]=FindParticleDefinition |
| `qword_1826306A8` | `0x26306A8` | `0x1826306A8` | 粒子回收 | refcount→0 时 vtable[16]=Destroy |
| `g_pMemAlloc` | — | `0x181571708` | 内存分配器 | vtable[24]=Free |
| `g_pThreadPool` | — | `0x181570E80` | 线程池 | vtable[128]=QueueJob, [104]=Submit |
| pet.dll: | | | | |
| `qword_1808EAF60` | `0x8EAF60` | `0x1808EAF60` | 链表头 | CreateInterface 注册表 |

---

## 4. IDA MCP 环境

### 4.1 活跃实例

| DLL | 端口 | PID | 状态 |
|-----|------|-----|------|
| hammer.dll | **13400** | 54096 | ✅ 运行中 |
| pet.dll | **13332** | 14900 | ✅ 运行中 |
| particles.dll | **13315** | 43740 | ✅ 运行中 |

### 4.2 协议端点
- **URL**: `http://127.0.0.1:<PORT>/mcp`
- **JSON-RPC 2.0**: `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"...","arguments":{...}}}`
- 支持的核心工具: `server_health`, `decompile`, `xrefs_to`, `find_regex`, `py_eval`, `disasm`, `search_text`

### 4.3 端口修改方法

**原理**: 通过 HTTP POST 调用 IDA MCP 的 `py_eval` 工具，在 IDA 进程内直接操作 MCP 插件实例。

**步骤**:

```powershell
# Step 1: 找出端口 (读 instance JSON + 进程列表)
Get-Process ida | Select Id,MainWindowTitle
Get-ChildItem "$env:APPDATA\Hex-Rays\IDA Pro\mcp\instances" -Filter *.json

# Step 2: 确认协议 (无需 initialize 握手, require_streamable_http_session=False)
Invoke-RestMethod -Uri "http://127.0.0.1:<OLD_PORT>/mcp" -Method Post -ContentType 'application/json' `
  -Body '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Step 3: py_eval 改端口并重启
$code = @'
def _main():
    import gc
    target = None
    for o in gc.get_objects():
        try:
            if type(o).__name__ == "MCP" and hasattr(o, "port") and hasattr(o, "mcp"):
                target = o; break
        except: pass
    old = target.port
    target.port = <NEW_PORT>
    target.run(0)  # 停旧 server → 重新 import ida_mcp → 在新端口 serve
    return "old=%s new=%s" % (old, <NEW_PORT>)
return _main()
'@
$body = @{jsonrpc='2.0'; id=1; method='tools/call'; params=@{name='py_eval'; arguments=@{code=$code}}} | ConvertTo-Json -Depth 8
Invoke-RestMethod -Uri "http://127.0.0.1:<OLD_PORT>/mcp" -Method Post -ContentType 'application/json' -Body $body

# Step 4: 持久化 (写 IDB netnode)
# 在 py_eval 里追加:
ida_netnode.netnode("$ ida_mcp.config", 0, True).altset(0, <NEW_PORT>)   # 端口
ida_netnode.netnode("$ ida_mcp.config", 0, True).supset(0, "127.0.0.1")  # host
```

**坑**:
1. `exec(code, globals, locals)` → 顶层 `import` 进 locals，函数体 `__globals__` 不含 → `import` 必须写在函数内
2. `run(0)` 必须在 IDA 主线程执行（`py_eval` 本身是 `@idasync`），放后台线程会导致旧 server 停了新的没起来
3. 直接在 py_eval body 里调 `target.port = X; target.run(0)` 会导致 HTTP 响应连接断开（正常，用新端口验证即可）

### 4.4 py_eval 常用 IDA 9.1 API

```python
import ida_bytes, ida_funcs, ida_nalt, idautils, idc, ida_name, ida_netnode

# 读导出
for ea, name in idautils.Exports():  # 或用 idc.get_name_ea_simple("CreateInterface")
    ...

# 读交叉引用
for x in idautils.XrefsTo(target_addr):
    fn = ida_funcs.get_func(x.frm)
    fname = ida_funcs.get_func_name(fn.start_ea) if fn else "?"

# 读内存
val = ida_bytes.get_qword(ea)
s = ida_bytes.get_strlit_contents(val, -1, ida_nalt.STRTYPE_C)

# IDB netnode (持久化)
n = ida_netnode.netnode("$ ida_mcp.config", 0, True)
n.altset(0, port)    # altval[0] = 端口
n.supset(0, "127.0.0.1")  # supstr[0] = host
```

---

## 5. cs2_tool.dll 当前实现状态

### 5.1 已完成模块

| 文件 | 功能 | 状态 |
|------|------|------|
| `dllmain.cpp` | DllMain + CreateThread + exports | ✅ |
| `hammer_bridge.h/.cpp` | CreateInterface + RVA 硬编码 | ✅ hammer.dll OK |
| `ipc_pipe.h/.cpp` | 命名管道服务器 + CancelSynchronousIo | ✅ 已修复死锁 |
| `protocol.h/.cpp` | 手动 JSON 实现 (零依赖) | ✅ 已修复 SkipWs bug |
| `build_msvc/Release/cs2_tool.dll` | MSVC x64 Release | ✅ 编译成功 |

### 5.2 已修复 Bug 清单

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| 1 | `protocol.cpp` SkipWs() | 错误把逗号当作空白跳过，JSON 对象解析失败 | 只保留 `isspace()` |
| 2 | Python _write_all | `ctypes.create_string_buffer(data)` 在第一个 `\x00` 截断 | `(ctypes.c_ubyte * N).from_buffer_copy(data)` |
| 3 | Python _open() | `SetNamedPipeHandleState` 强制 MESSAGE 模式 | 移除多余调用 |
| 4 | `ipc_pipe.cpp` Stop() | `server_thread_.join()` 在 DllMain loader lock 下死锁 | `detach()` + `CancelSynchronousIo()` |
| 5 | `cs2_mcp_server.py` | FastMCP `description` 已废弃 | 改成 `instructions` |

### 5.3 测试覆盖

- C++ pipe client 独立测试: **5/5 OK** ✅
- Python PipeClient 测试: **5/5 OK** ✅
- 真实 hammer.exe 注入后测试: **6/6 OK** ✅
- Shutdown 优雅退出: **Exit code 0** ✅
- MCP tools 注册: **9 tools** ✅

---

## 6. MCP 工具设计方案（参考 Blender MCP）

### 6.1 已实现

当前 9 个基础工具（pipe 通信通了，但只返回 CHammerApp 状态）

### 6.2 待实现

| 层级 | 工具 | 目标 API | 优先级 |
|------|------|---------|--------|
| **地图** | `map_get_info` | CMapDoc 全局状态 | P0 |
| | `map_frame_step` | 触发 FrameUpdate 一帧 | P2 |
| | `map_save` | 查找 Save 序列化函数 | P2 |
| **实体** | `entity_list` | `CUtlDict<CMapEntity*>` 遍历 | P1 |
| | `entity_get_attr` | `sub_180729670` GetAttribute | P0 |
| | `entity_set_attr` | 属性 setter + 自动 Undo | P1 |
| | `entity_create` | `CUndoCreateElement` | P2 |
| | `entity_delete` | `CUndoDestroyElement` | P2 |
| | `entity_select` | CMapDoc+136 | P1 |
| **粒子** | `particle_set_definition` | `CParticleHelper` effect_configuration | P0 |
| | `particle_set_snapshot` | snapshot_file / snapshot_mesh | P1 |
| | `particle_set_cpoint` | cpoint%d / tint_cp / data_cp | P1 |
| **Undo** | `undo_do` | `CUndoManager::Undo` (RVA `0x50B720`) | P1 |
| | `undo_redo` | `CUndoManager::Redo` (RVA `0x50B290`) | P1 |
| **材质/贴图** | 待挖掘 | 搜索 CMaterial / Texture 相关 | P3 |

---

## 7. 下一步行动项

- [ ] 扩展 cs2_tool.dll 的 HammerBridge 支持 pet.dll CreateInterface
- [ ] 反编译 pet.dll ParticleSystemMgr003 工厂和 vtable
- [ ] 反编译 pet.dll SceneSystem_002 工厂和 vtable
- [ ] 查找 particles.dll CreateInterface RVA
- [ ] 实现 entity_list + entity_get_attr 工具
- [ ] 实现 undo_do + undo_redo 工具
- [ ] 实现 particle_set_definition 工具
- [ ] 把 RVA 值和注释回注 hammer.dll.i64（IDA `set_comments` / `rename`）
- [ ] 注册 pet.dll IDA MCP 到 Trae（当前只有 hammer.dll 注册了）

---

## 8. 快速查找：RVA 速查表

### hammer.dll (imagebase `0x180000000`)

| 名称 | RVA | 绝对地址 |
|------|-----|---------|
| CreateInterface | `0x12E1B50` | `0x1812E1B50` |
| ToolSystem2_001 工厂 | `0x115270` | `0x180115270` |
| ToolSystem2_001 名字 | `0x1CB1B58` | `0x181CB1B58` |
| 接口链表头 | `0x26310E8` | `0x1826310E8` |
| CHammerApp vtable[0] | `0x117940` | `0x180117940` |
| CHammerApp vtable[1] | `0x118670` | `0x180118670` |
| CHammerApp vtable[8] | `0x11F450` | `0x18011F450` |
| CHammerApp vtable[11] | `0x1360690` | `0x181360690` |
| CHammerApp vtable[12] | `0x11F400` | `0x18011F400` |
| CUndoManager::Undo | `0x50B720` | `0x18050B720` |
| CUndoManager::Redo | `0x50B290` | `0x18050B290` |
| CParticleHelper::SetDefinitionByName | `0x6E7380` | `0x1806E7380` |
| CParticleHelper::SetDefinition (简单版) | `0x6E8800` | `0x1806E8800` |
| CMapDoc::FrameUpdate | `0x775F50` | `0x180775F50` |
| GetAttribute | `0x129670` | `0x180729670` |
| FindAttributeIdx | `0x129C50` | `0x180729C50` |
| 粒子系统 | `0x26306A0` | `0x1826306A0` |
| 日志接口 | `0x207E5D8` | `0x18207E5D8` |
| GetModuleHandleW("pet.dll") | — | 运行时动态 |

### pet.dll (imagebase `0x180000000`)

| 名称 | RVA | 绝对地址 |
|------|-----|---------|
| CreateInterface | `0x370360` | `0x180370360` |
| 接口链表头 | `0x8EAF60` | `0x1808EAF60` |
| ParticleSystemMgr003 名字 | `0x6F6968` | `0x1806F6968` |
| SceneSystem_002 名字 | `0x6F6A78` | `0x1806F6A78` |
| 模块名 "particles" | `0x7F6590` | `0x1807F6590` |

### 计算方式

```cpp
#define ABS(pDllBase, rva)  ((uintptr_t)(pDllBase) + (rva))

// 运行时:
uintptr_t hammer_base = (uintptr_t)GetModuleHandleW(L"hammer.dll");
uintptr_t pet_base    = (uintptr_t)GetModuleHandleW(L"pet.dll");

// CreateInterface:
auto hammer_CI = (CreateInterface_t)(hammer_base + 0x12E1B50);
auto pet_CI    = (CreateInterface_t)(pet_base + 0x370360);

// 拿 CHammerApp*:
char* err = nullptr;
auto hammer = (CHammerApp*)hammer_CI("ToolSystem2_001", &err);
```

---

## 9. Valve CreateInterface 协议说明

链表节点结构（3 个 QWORD）:
```cpp
struct IFaceNode {
    void* factory;   // +0: factory() 函数指针, 无参, 返回接口单例
    char* name;      // +8: 接口名字符串
    IFaceNode* next; // +16: 下一节点 (NULL 终止)
};
```

CreateInterface 行为:
1. 从链表头开始遍历
2. 用 `strcmp` 比较 name 指针指向的字符串（通过 `a1 - name_ptr` 计算偏移，然后比较 `name_ptr[offset]` vs `a1[offset]`）
3. 匹配成功: `factory()` → 返回接口指针, `*a2 = 0`
4. 遍历完没匹配: `*a2 = 1`, 返回 NULL

注册行为（静态构造函数）:
```cpp
// sub_18004A730 原型:
node.factory = &SomeFactory;
node.name    = "InterfaceName_001";
node.next    = g_interfaceHead;    // 链表头
g_interfaceHead = &node;            // push to head (LIFO)
```

---

## 10. 技术选型：为什么不用 MetaMod / ModSharp（2026-09-23 调研）

**结论：MetaMod:Source 与 ModSharp / CounterStrikeSharp 都是「游戏服务器」插件框架，
用在 Hammer 工具模式下加载不了 —— 本项目继续用自建注入方案。**

### 实测证据（实体机 / VM，CS2 新版）

机器上**已装 MetaMod**（`game\csgo\addons\metamod\`，含 `metamod.2.cs2.dll` 1.44MB、`cs2fixes.vdf`），但：

1. **它自己记录了加载失败** —— `game\bin\win64\metamod-fatal.log`：

```
Metamod:Source requires -dedicated or -insecure on the command line to be able to load
```

2. **正在运行的 Hammer 进程里它根本没加载**：

| 检查项 | 实测结果 |
| --- | --- |
| `server.dll` 来源 | `csgo\bin\win64\server.dll`（**36MB，CS2 自己的**） |
| MetaMod 的桩 `addons\metamod\bin\win64\server.dll`（218KB，x64） | **未加载** |
| `metamod.2.cs2.dll`（MetaMod 核心） | **未加载** |

### 原因：加载机制对不上

MetaMod 的入口是**替换 `server.dll`**，由 `addons\metamod_x64.vdf` 声明：

```
"Plugin"
{
        "file"  "addons/metamod/bin/win64/server"
}
```

而 `.vdf` 只在**游戏服务器初始化**时经 VSP 流程处理。
Hammer 是 `toolframework2.dll` + `hammer.dll` 的**工具程序**，不跑游戏服务器 ——
工具模式虽然确实加载了 CS2 自己的 `server.dll`，但走的是自身路径，**不读 addons 的 VDF**。

CounterStrikeSharp 官方文档亦印证其定位（ModSharp 同类）：

> "CounterStrikeSharp uses Metamod:Source as its main way of communicating with the **game server**"

### 即使能加载也不划算

这两个框架提供的是「插件装载 + hook 基础设施」，而本项目已自建同等能力且更贴合需求：

| 能力 | MetaMod / ModSharp | 本项目 `cs2_tool.dll` |
| --- | --- | --- |
| Hook 基础设施 | ✓ | ✓（含 `__try/__except`，异常不带走宿主） |
| 主线程派发 | 部分 | ✓（`WH_GETMESSAGE`，改文档/UI 必需） |
| 直调 `hammer.dll` RVA | 需自己写 | ✓（28 个工具 + 全套 RVA） |
| Qt 控件直调 | 无 | ✓（`qt-click` / `qt-trigger`） |

换过去等于推倒已经验证跑通的东西，还失去对 `hammer.dll` 内部状态的直接控制。

### 它们真正的适用场景

若目标改为**游戏内**（控制玩家 / 实体 / 事件 / HUD），MetaMod + CounterStrikeSharp
（或 ModSharp）才是正路，且本机已装好。
另注：CS2 现已有**官方地图脚本系统**（`custom_hud_layout`、`Instance.OnBombPlantStart` 等），
做游戏内逻辑可优先用官方 API，比第三方框架更稳。

> 一句话：**编辑器侧继续用注入方案；MetaMod 那条线留给将来做「编译地图 → 进游戏验证」时再用。**

---

## 11. 2026-09-24 新版 hammer.dll：RVA 全量重定位 + 底层调用链路 ✅

> 触发原因：Steam 于 2026-09-24 更新 `hammer.dll`，**旧版 §8 速查表里的 RVA 全部失效**。
> 本节是**当前唯一有效**的 RVA 表。新版 `hammer.dll` MD5 `DED2B1071B76EB3F71389EEBB865B023`，
> imagebase 仍为 `0x180000000`。

### 11.1 全局单例与虚表（已活体验证）

| 名称 | RVA | 说明 |
|------|-----|------|
| `g_CDataModel` | `0x24B7C80` | **静态内嵌对象**，直接用地址，不要再解引用 |
| `g_CDataModel` 的 vptr | `0x16C25C8` | 运行时确认：`hammer+0x24B7C80` 的首 qword |
| `off_1821B2B68` | `0x21B2B68` | qword 指针，值 = `base+0x24B7C80`（同一对象） |
| CUndoManager | `g_CDataModel + 240` | 内嵌 |

虚表 RVA：`CMapDoc 0x1764188`、`CMapWorld 0x1772920`、`CMapRootElement 0x1763FA8`、
`CMapEntity 0x1758D00`、`CMapDocHistory 0x1763E00`、`CParticleHelper 0x17500B8`。

### 11.2 对象链与内存布局

```
CHammerApp (get_status.tool_system)
  +0x50 当前 session      +0x58 session 数      +0x60 session 数组
  session+0x138 = CMapDocSession 包装；CMapDoc 内嵌在 wrapper+0x10
CMapDoc
  +0x80 CMapRootElement*      +0x88 CMapWorld*
  +0x6A0 路径 char*
  +0xAF8 CParticleSystemQueryHammerMapDoc     +0xB68 CParticlesLibHost_MapDocLib
CMapRootElement
  +0x240 CMapDocHistory(undo)   +0x248 (redo)
  +0x1F8 int 子节点数           +0x200 int32 句柄数组
CDmAttribute（40 字节）
  +0x00 next   +0x08 值存储指针(valptr)   +0x10 owner
  +0x1C 类型低 6 位（字符串 = 5）          +0x20 名字 char*
  实体属性链表头 = 元素 +0x48；字符串值： [attr+8]=valptr，字符串时 [valptr]=char*
CParticleHelper（>1160 字节）
  +0x98(u32) 所属实体句柄   +0xB0 effect_name(CUtlString)
  +0xB8 解析出的粒子定义指针
CMapEntity 对象大小 = 6232 字节
```

句柄 → 元素 = CDataModel **vtable 字节偏移 168**（`sub_1805BEC50`）。

### 11.3 ⭐ 底层「写属性」链路（本节新增，已活体验证）

旧版 `CDmAttribute::SetValue<CUtlSymbolLarge> = 0x4C7A10` 已失效。新版对应关系：

| 用途 | RVA | 签名 / 说明 |
|------|-----|------------|
| **按名写字符串属性**（推荐） | **`0x62C9A0`** | `sub_18062C9A0(elem, const char* name, const char* value, bool createIfMissing)`；**内部自己 intern**，属性缺失时以 AT_STRING(5) 创建。Hammer 拖放建实体、快照写回都走它 |
| CDmAttribute 值写入 | `0x5CF020` | `sub_1805CF020(attr, const CUtlStringToken*)` |
| 按名取 CDmAttribute* | `0x5C7170` | `sub_1805C7170(elem, const char* name)` |
| 字符串 intern | CDataModel vtable **byte 424** | `sub_1805BF5F0(dm, outToken*, const char* s)` |

**活体实测**（对 world 元素写 `name` 属性，管道直调，`on_main_thread=true`）：

```
call hammer+0x62C9A0(world, "str:name", "str:cs2_mcp_test", 1)
  -> main_thread_status=0, ret=0x262d63cfd40 (CDmAttribute*)
读回 name = 'cs2_mcp_test'      ✔
再写回 '' 读回 = ''             ✔
```

### 11.4 类名与粒子

| 用途 | 位置 | 说明 |
|------|------|------|
| 设置实体类名 | CMapEntity vtable **byte 2144** = `sub_180896390` | `vfn2144(entity, const char* classname, bool, bool)`，Hammer 拖放建实体就这么调 |
| `CParticleHelper::SetDefinitionByName` | `0x7F5350` | `(helper, const char* vpcfPath)` → 写 `helper+0xB8` |
| 属性名常量 | `effect_name` @ `0x1DEBB38` | helper 工厂 `0x7F22A0` 在 `0x7F22C1` 引用它 |
| 类名常量 | `info_particle_system` @ `0x1DF9AE0` | 拖放处理器 `sub_180180190` @ `0x180180950` 引用 |
| vpcf 资源串 | `particles/environment/glow01.vpcf` @ `0x1A58550`、`particles/error/error.vpcf` @ `0x1A0C3E0` | |
| helper 工厂（通用） | `0x7F22A0` | `(config, docContext)`；基类 ctor `0x7F1A70` |
| helper→实体解析 | `0x81FA00` | `datamodel vfn168(*(u32*)(helper+0x98))` |
| helper 属性同步 | `0x198F20` | 读实体 `effect_name`，与 helper 现值比较，不同才调 `0x7F5350` |

### 11.5 DMX 元素工厂注册表（供后续「底层建实体」用）

```
sub_180052E20()  注册节点： {next, ?, ?, ?, factory=&off_1821DB400, name="CMapEntity"}
  qword_1824B98B8 = 链表头（RVA 0x24B98B8）
  off_1821DB400   = CDmElementFactory<CMapEntity> 实例（RVA 0x21DB400）
  该实例 vtable   = CDmElementFactory<CMapEntity>::`vftable' @ RVA 0x1765170
    slot0 (Create)      = sub_180898D10  (RVA 0x898D10) -> alloc(6232) + sub_180811220
    slot5 (+40 注册类名) = sub_180898D80
    slot7/8             = sub_180898D90 / sub_180898DB0
```

✅ **已解决（见 §11.8）**：`Create` 第 2 参（element handle）由 CDataModel 的通用创建入口分配 ——
入口就是 `sub_1805BBB90(dm, "CMapEntity", name, 1, 0)`（CDataModel 的虚方法），
内部 `sub_1805BA670` 取空闲句柄 → `sub_1805BB7F0` 按类型名查工厂表 → 调工厂 slot0 `0x898D10`。
直接调工厂 Create 仍然不行（缺句柄），必须走 `sub_1805BBB90`。

### 11.6 陷阱（新版实测）

* **DMX 空栈调 Undo 会杀进程**：空 undo 栈时调 `cs2_undo()`，当时不崩，但**保存地图时弹
  `FATAL ERROR: Error in the undo system! Grab a programmer!` 并直接杀死 cs2.exe**。
  已在 MCP 侧 `_undo_redo()` 加硬守卫（计数为 0 时拒绝调用）。
* **管道单实例串行且无超时**：不要在管道线程跑长任务（Qt 控件全量枚举、全进程堆扫描），
  会占死管道且 DLL 管道线程不重启，只能重启 cs2。全进程堆扫描已实测把 cs2 扫崩，
  现改用 `__try/__except` + 256KB 分块（`scan_heap`）。
* **Qt 模态对话框会阻塞管道**：另存为/警告框要走 Win32 消息（`ui_dialog_*.ps1`）。
* **DPI 缩放**：物理屏 2998x1238，未声明 DPI aware 的坐标会被虚拟化缩放 ~1.6x。

### 11.7 MCP 工具现状（对应 §5）

新增/启用：

| 工具 | 底层调用 |
|------|---------|
| `cs2_entity_create(classname, name)` | `hammer+0x5BBB90`（CDataModel 通用创建）→ 见 §11.8 |
| `cs2_entity_set_attr(entity, name, value)` | `hammer+0x62C9A0`（**原为哨兵占位，现已启用**） |
| `cs2_entity_set_classname(entity, classname)` | `hammer+0x62C9A0` 写 props 的 `classname`（**vfn2144 已弃用，实测无效**，见 §11.8） |
| `cs2_particle_set_definition(entity, vpcf)` | ① `0x62C9A0` 写 `effect_name` ② 实体内存扫 `CParticleHelper`（vptr=`base+0x17500B8`）+ 主线程调 `0x7F5350` |
| `scan_heap`（DLL 侧） | SEH 保护的分块全进程扫描，替代易崩的整块扫描 |

---

## 11.8 ⭐ 底层「新建实体」链路（2026-09-26 新增，CE 硬件断点活体验证 ✅）

### 调用链（全部 hammer.dll 内部）

```
CDataModel::CreateElement          sub_1805BBB90   RVA 0x5BBB90
    (dm, const char* typeName, const char* name, int flags, const void* uniqueId)
    -> 返回新元素句柄 (u32)，失败 0xFFFFFFFF
    |
    |-- sub_1805BA670(dm+0x80)              取空闲 DMX 元素句柄
    `-- sub_1805BB7F0(dm, &handle, type, name, flags, uid)   RVA 0x5BB7F0
          |-- sub_1805B8CC0(dm+0x58, &type) 按类型名查元素工厂表
          |-- new CUndoCreateElement（flags != -1 且 dm 允许撤销时）
          |-- factory->vfn0(factory, handle, type, name, flags, uid, extra)
          |     └─ CDmElementFactory<CMapEntity> 实例 @ RVA 0x21DB400
          |        vtable @ RVA 0x1765170，slot0 = RVA 0x898D10
          |        └─ new(6232) + sub_180811220  == CMapEntity 构造
          |             └─ 0x811480 -> 0x811580 -> CDmElement 基类 ctor 0x5C5660
          |                （elem+0x28 = handle；0x5BA2F0 把 handle 登记进 datamodel；
          |                  0x5C7AD0 建 "name" 属性；CopyUniqueId 写 elem+8）
          |-- 登记 handle->element、跑 vfn80/0x5C6FF0/0x5C81B0 收尾
          `-- factory->vfn4(factory, element)  RVA 0x619A00（通知工厂的监听者）
```

### ⚠️ 踩坑：地址算错导致「断点 0 命中」

上一轮把工厂 Create 的运行时地址写成 `base + 0x888D10`（`0x7FF9E4118D10`），正确是
`base + 0x898D10`（`0x7FF9E4128D10`）—— 差 `0x10000`，所以断点永远不命中，
一度误判「实体不是经工厂建的」。**校验方法**：读运行时的 `*(工厂对象+0)` 得虚表，
再读 `*虚表` 得 slot0，与 IDB 对照：

```
read_pointer(0x7FF9E5A6B400, [0,0])   # 0x7FF9E5A6B400 = hammer_base + 0x21DB400
 -> 0x7FF9E4FF5170  (RVA 0x1765170 ✔)
 -> 0x7FF9E4128D10  (RVA 0x898D10  ✔ = 工厂 slot0)
```

修正后挂上，一次点击（实体工具放 2 个实体）命中 **2 次**，RDX=handle、R8="CMapEntity"、
R9=空串(name)、RCX=工厂对象 → 链路确认。

### ⚠️ 陷阱：CE 的 hit `timestamp` 有 −8h 时区偏差

CE `get_breakpoint_hits` 返回的 `timestamp` 比系统 `Get-Date -UFormat %s` **小 28800**，
不要据此判断"断点已失效"。判断断点死活的正确办法：找高频地址（如每帧函数）看它是否还在涨。

### 读调用栈的正确姿势（重要）

`capture_stack` 返回的 `stack` 数组是**从 RSP 起的裸内存 qword 复制**，不是栈回溯；
中间大量垃圾值。要拿「直接调用者」：入口断点的返回地址在 `[RSP + 序言压栈字节数]`
（实测 `sub_180811220` 入口为 `[RSP+0x38]`）；更稳的是**多取几帧、筛出落在
hammer 镜像范围内的地址**,再逐个 `get_func` 归属。

### ⚠️ vfn2144 不是「改类名」的有效入口（推翻 §11.4 结论）

`CMapEntity` vtable byte 2144 = `sub_180896390(entity, const char* cls, bool, bool)`：

* 它只在「已有游戏类句柄(ent+0x550)」时做**字符串比较**，不同才转
  `sub_180828950(entity, cls, flag, 0)`；实测**调用后 `classname` 属性完全没变**。
* 对**既有实体**（已在世界里、有 props）测试同样无效 → 不是"新实体没准备好"的问题。

**真正生效的改类名入口**（也是 Hammer 属性面板走的路）＝ 属性直写：

```
sub_18062C9A0(propsElement, "classname", value, /*createIfMissing*/1)   RVA 0x62C9A0
```

实测：既有实体 `info_player_start` → `info_particle_system`，读回一致 ✔
（`cs2_entity_set_classname` 已按此改写）

### 新建实体的实测结果

`cs2_entity_create("info_player_start", "mcp_t2")` →

```
CreateElement ret = 0x2c            # handle
element = 0x263faf20000
props   = 0x262bbbbe580             # entity_properties 已建
```

✅ 元素确实被建出来了（datamodel 里合法、props 已生成、CUndoCreateElement 已登记）。

❌ **未挂进 CMapWorld 子节点表**：`cs2_entity_list()`（走 world 的 +0x1F8 子数 /
+0x200 句柄数组）看不到新元素，Hammer UI 也不会显示。

### 下一步（新建实体剩下的最后一环）

1. **世界挂载**：找到把元素句柄追加进 `world/父节点 + 0x1F8/+0x200`（`CUtlVector<CDmElementHandle_t>`
   AddToTail）的官方 API。候选线索：实体工具在 `sub_1805BBB90` 之后会调它；
   也可从 `CUndoCreateElement` 的 Apply（vtable RVA `0x16C3510`，方法
   `0x5C12B0/0x5C1220/0x5C31A0/0x5C1350`）里找"重新挂回世界"的那条调用。
2. **建完即设类名**：现在 `cs2_entity_create` 用 `0x62C9A0` 写 classname 是有效的；
   但**写属性不会重建游戏类/helper**（entity+0x550 的游戏类句柄仍指向旧类），
   所以 `CParticleHelper` 不会因此生成 —— 需要补 `sub_180828950`(0x828950) 那条
   "设游戏类 + 重建 props/helper"的链路（或在写属性后补调 vfn2144 做重建）。

---

## 11.9 ⭐ 实体坐标 / 元素类清单 / mesh 与 IO 结构（2026-09-26 新增）

### 11.9.1 实体坐标 = CMapEntity 原生成员（CE 对比实测 ✅）

坐标**不在 DMX 属性里**。`origin/angles/scales` 是 `CMapNode` 的属性
（`GetAttributeTable_CMapNode` @ `0x8617D0`，属性类型是 `CToolAttrGetSetAccess<Vec3D<float>, CMapNode>`），
但**运行时根本没有 CMapNode 元素**（见 11.9.2），所以坐标只存在 CMapEntity 对象里：

```
entity + 0xA0   Vec3D  origin   世界坐标
entity + 0xAC   Vec3D  angles   欧拉角（度）
entity + 0xB8   Vec3D  scales   （新建时为 1,1,1）
```

**怎么确认的（可复现）**：

1. 反编译 `sub_1808327B0`（被游戏类 setter `sub_180828950` 调用）时看到
   `*(float*)(entity+172) == 0 && (entity+176) == 0 && (entity+180) == 0` 用来判断
   `"angles"` 键值 → `172 = 0xAC` 正好是 angles 的起点，相邻结构自然对齐。
2. 枚举 datamodel 元素表（见 11.9.2），把「UI 实体工具放置的实体」和「`cs2_entity_create`
   新建的实体」逐个对比 `entity+0x80..0x140` 的浮点：
   * 放置的 → `+0xA0 = (-448,-448,0)` / `(-1152,-128,0)` / `(-576,-320,0)`，**全是网格整数倍**
   * 新建未定位的 → `(0,0,0)`
   * 两者 `+0xB8` 都是 `(1,1,1)`（scales），`+0xAC` 都是 `(0,0,0)`（angles）

对应 MCP：`cs2_entity_list` 现在每行带 `origin=(x,y,z)`；新增 `cs2_entity_get_transform(entity)`。

### 11.9.2 运行时元素类清单（datamodel 元素表枚举）

元素表在 `CDataModel + 0x90`（`u64 m_pElements`），容量 `+0x88`（u32），
每项 16 字节：`{u32 flags, u32 ?, u64 CDmElement*}`，句柄 = 数组下标。

当前测试地图（50 个活元素）：

| 类（RTTI 取自 vtable-8 → `??_R4XXX@@6B@`） | vtable RVA | 数量 |
|---|---|---|
| CMapEntity | `0x1758D00` | 21 |
| CEditGameClassProps | `0x175E2B8` | 22 |
| CMapRootElement | `0x1763FA8` | 1 |
| CMapWorld | `0x1772920` | 1 |
| CMapSelectionSet | `0x17C2718` | 1 |
| CMapVariableSetStorage | `0x17F1428` | 1 |
| CVisibilityMgr | `0x17EC118` | 1 |
| CStoredCameras / CStoredCamera | `0x1763EA8` / `0x1763E28` | 1 / 1 |

⚠️ 注意 `cs2_entity_list` 走的是 world 的 `children` 树（20 个元素），
而元素表有 50 个 → **有 30 个元素不在世界树里**（我们新建的和大部分 props）。
这也是「新建实体不显示」的根因之一。CNavNode / CNavMesh 之类不在 DMX 里。

### 11.9.3 DMX 属性类型编码（实测）

`attr+0x1C` 的低 6 位（`& 0x3F`）：

| 值 | 含义 | 例 |
|---|---|---|
| 1 | 元素句柄 | `entity_properties`, `relayPlugData` |
| 2 | int32 | `nodeID`, `nextDecalID` |
| 4 | bool | `isProceduralEntity`, `fixupEntityNames` |
| 5 | string | `classname`, `targetname`, `name` |
| 10 | Vec3D | `hitNormal` |
| 15 | uint64 | `referenceID` |
| 33 = `0x20｜1` | 数组<元素句柄> | `children`, `connectionsData` |
| 37 = `0x20｜5` | 数组<string> | `variableNames`, `variableTargetKeys` |

即 **bit 0x20 = 数组标志**。值指针 `attr+0x08` 指向值存储。

### 11.9.4 mesh 结构（来自真实 .vmap 字符串表，与 VRF 一致）

`cmap` 里的 mesh 是**半边缘（DCEL）+ 顶点流**结构：

```
CMapMesh                                  RVA 待定位
  meshData   -> CDmePolygonMesh           半边缘网格
  renderAmt / tintColor / smoothingAngle / disableHeightDisplacement /
  keep_vertices / renderToCubemaps / renderwithdynamic / disablemerging /
  visexclude / emissiveLightingMode / rtproxy* / bakeLightDoubleSided /
  lightingDummy / emissiveLighting(Boost|Enabled) / cubeMapName / bakelighting /
  disableShadows / physics*  ...          ← 渲染 & 物理属性
CDmePolygonMesh
  faceData / edgeData / faceVertexData / vertexData     ← 索引数组
  faceDataIndices / faceEdgeIndices / edgeVertexDataIndices / edgeDataIndices /
  edgeFaceIndices / edgeNextIndices / edgeOppositeIndices / edgeVertexIndices /
  vertexDataIndices / vertexEdgeIndices
  streams          -> [CDmePolygonMeshDataStream]        ← 顶点属性流
  subdivisionData  -> CDmePolygonMeshSubdivisionData
CDmePolygonMeshDataStream
  semanticName / semanticIndex / standardAttributeName
  data -> CDmePolygonMeshDataArray      （size + 数据）
  textureScale / textureAxisU / textureAxisV / materialindex / flags /
  lightmapScaleBias / vertexBufferLocation / dataStateFlags / subdivisionBinding
语义名（字符串表顺序）：position / texcoord / normal / tangent
→ **顶点坐标 = position 流；UV = texcoord 流**；面材质 = materialindex
CMapGroup                                 组节点（lodlevel / materialoverride 等）
```

### 11.9.5 实体 IO（connectionsData）

* `CMapEntity.connectionsData`（类型 33 = 元素句柄数组）→ 每个元素是一条连接；
  另有 `relayPlugData`（元素句柄）与 `DmePlugList`
  （属性 `descriptions / plugTypes / dataTypes / names`）。
* 测试地图里所有实体 `connectionsData` 计数都是 0（没有 IO 数据），
  所以**要验证 IO 读写，需要一个带连接的地图或先造一条连接**。
  `cs_script_demo.vmap`（68MB，同目录）里应有大量连接可用。

### 11.9.6 ⚠️ 环境约束：VM 内访问不了 GitHub

* `git clone https://github.com/...` → `Recv failure: Connection was reset`
* 镜像 `ghfast.top` → 300s 超时；`gitclone.com` 同样不通
* MCP 侧 WebFetch: `api.github.com` 可达，但**每次只保留前 ~15KB**，
  且 `raw.githubusercontent.com` 直接失败 → **无法整仓拉取**

**VRF 参考仓库（ValveResourceFormat）**：需要的文件是 vmap / DMX / 半边缘网格相关源码
（`.vmap` 资源类型实现、`CDmePolygonMesh` 及其流、`EntityLump`）。
请在能访问 GitHub 的机器上克隆后同步进 VM，例如：

```
git clone --depth 1 https://github.com/ValveResourceFormat/ValveResourceFormat.git
```

放到 `c:\cs2_tool_mcp\third_party\ValveResourceFormat`（**已由用户 clone 到位，见 §11.10**）。
另外官方 wiki 有 `.vmap` 的**文本格式**示例（`Save Copy As Text` 也能导出），
可用来对照属性名：https://www.source2.wiki/FileFormats/vmap/example.vmap

---

## 11.10 ⭐ VRF 对照补全（仓库已 clone 到 `third_party/ValveResourceFormat`）

看的关键文件（都很有价值，后续都按它核对）：

| 文件 | 作用 |
|---|---|
| `ValveResourceFormat/IO/ContentFormats/ValveMap.cs` | **.vmap 全部元素类与属性定义**（本次最重要的参考） |
| `ValveResourceFormat/IO/Hammer/HammerMeshBuilder.cs` | 半边缘网格 ↔ 三角形，**顶点流的语义名与位置** |
| `ValveResourceFormat/IO/Extract/MapExtract.cs` | 实体 / mesh / 材质 提取流程 |
| `Renderer/Renderer/Entities/*` | 各类实体读哪些 keyvalue、IO 怎么用 |
| `Tests/IO/EntityIOParamMapTest.cs` | 实体 IO 参数映射 |

### 11.10.1 MapNode / BaseEntity / CMapEntity 继承链（关键更正）

```
MapNode                    ← 所有地图树节点的基类
  origin(Vector3) angles(QAngle) scales(Vector3=1,1,1)
  nodeID(int)  referenceID(ulong)  children(ElementArray)
  editorOnly / force_hidden / transformLocked (bool)
  variableTargetKeys / variableNames (StringArray)
 └ BaseEntity
     relayPlugData(DmePlugList)  connectionsData(ElementArray<DmeConnectionData>)
     entity_properties(EditGameClassProps = 字符串字典，含 classname)
    └ CMapEntity / CMapWorld / CMapPath / CMapPathNode / CMapWorldLayer / CMapPrefab / ...
CMapMesh : MapNode（另有 meshData(CDmePolygonMesh) 与渲染/物理属性）
```

所以 **`origin/angles/scales` 确实是元素的 DMX 属性**；运行时读不到是因为
Hammer 只在**序列化时**才把这些属性写出来（默认值不落表），编辑期真值在
CMapEntity 的原生成员里 —— 与我们实测的 `+0xA0/+0xAC/+0xB8` 一致（§11.9.1）。
**改坐标的正确做法**：走 DMX 属性（`0x62C9A0` 写 origin 前需先建该属性）或
Hammer 自己的 setter（`sub_18086B550` / `sub_18083E0D0` 一带），不要直接改原生成员。

### 11.10.2 DMX 数组属性内存布局（实测 + 现在通用化了）

```
值存储 vp:  +0x00 u32 m_nSize     +0x04 u32 _unused
            +0x08 u64 m_pMemory   +0x10 u32 m_nAllocation
元素：句柄数组(AT 33) = u32 句柄；数值数组 = 相应分量 float/int；字符串数组(AT 37) = CUtlString(8B)
```
实测 `world.children`：size=19，data 里是 (8,10,12,…,48) 这些偶数句柄 → 经 vfn168
解析全是 CMapEntity（奇数句柄是它们的 CEditGameClassProps，所以不进 children）。

### 11.10.3 实体 IO（VRF 精确字段）

```
CMapEntity.connectionsData -> [DmeConnectionData]
    outputName(string)   触发输出名，如 "OnTrigger"
    targetType(int)      targetName 的解析方式
    targetName(string)   目标实体名
    inputName(string)    目标输入名，如 "Enable"
    overrideParam(string) 覆盖输出自带参数
    delay(float)         延迟秒
    timesToFire(int)     -1 = 无限
CMapEntity.relayPlugData -> DmePlugList
    names(StringArray) dataTypes(IntArray) plugTypes(IntArray) descriptions(StringArray)
```

MCP：新增 `cs2_entity_get_io(entity)`（当前地图 0 连接，待带 IO 的地图验证）。

### 11.10.4 mesh 精确结构（VRF 确认 + 流位置）

```
CMapMesh.meshData -> CDmePolygonMesh          半边缘（DCEL）
    vertexData / faceVertexData / edgeData / faceData : CDmePolygonMeshDataArray
        .size(int)  .streams(ElementArray<CDmePolygonMeshDataStream>)
    materials(StringArray)      被 faceData 的 materialindex 流索引
    索引数组：vertexEdgeIndices / vertexDataIndices / edgeVertexIndices /
              edgeOppositeIndices / edgeNextIndices / edgeFaceIndices /
              edgeDataIndices / edgeVertexDataIndices / faceEdgeIndices / faceDataIndices
CDmePolygonMeshDataStream
    semanticName / semanticIndex / standardAttributeName / vertexBufferLocation ...
    data : 基础类型数组（IntArray / Vector2Array / Vector3Array / Vector4Array）

流的位置（HammerMeshBuilder.CreateStream 第 2 参 = vertexBufferLocation）：
    vertexData     loc 3 : "position:0" (Vector3)            ← 顶点坐标
    faceVertexData loc 1 : "texcoord:0"(Vector2) "texcoord:1" "normal:0"(Vector3)
                          "tangent:0"(Vector4) "VertexPaintBlendParams/TintColor"(Vector4)
                          ← per half-edge（半边角数据）
    faceData       loc 0/1/3/8: "textureScale:0"(Vector2) "textureAxisU:0"/"textureAxisV:0"(Vector4)
                          "lightmapScaleBias:0"(int) "flags:0"(int) "materialindex:0"(int)
```
遍历某个 face：`faceEdgeIndices[f]` 取一条内边 → 沿 `edgeNextIndices` 绕一圈；
每个半边 `e`：顶点 = `vertexDataIndices[edgeVertexIndices[e]]`（索引进 position 流），
UV = `edgeVertexDataIndices[e]`（索引进 faceVertexData 的 texcoord 流）；三角化用扇形。

MCP：新增 `cs2_mesh_list(limit)`（按 **CMapMesh 主虚表 RVA 0x176B8E0** 从元素表筛）
与 `cs2_mesh_get_geometry(mesh, max_faces)`（读 position/texcoord/materialindex + 三角化）。
`CDmePolygonMesh` 主虚表 RVA `0x1D70620`。**当前地图无 mesh，待验证。**

### 11.10.5 新增/更新的 RVA 速查

| 名称 | RVA | 说明 |
|---|---|---|
| CMapMesh 主虚表 | `0x176B8E0` | RTTI `??_R4CMapMesh@@6B@` |
| CMapStaticOverlay 主虚表 | `0x176C3E0` | 贴花 overlay（也是 CMapMesh 派生） |
| CMapGroup 主虚表 | `0x178B4A8` | |
| CDmePolygonMesh 主虚表 | `0x1D70620` | |

---

## 11.11 ⭐⭐ mesh 几何的真实存放位置（2026-09-26 用户画了 9 个 mesh 后实测）

### 11.11.1 结论：编辑期几何**不在** CDmePolygonMesh 里

用户在地图里画了 9 个 `CMapMesh`，实测：

* 9 个 `CMapMesh` 的 `meshData` 属性值**全是 `0xFFFFFFFF`（无效句柄）**；
* 扫整个进程（0x26300000000–0x26390000000）**一个 `CDmePolygonMesh` 实例都没有**。

⇒ `CDmePolygonMesh` / `meshData` 只是 **.vmap 存档格式**（`Save Copy As Text` 里能看到
`CMapMesh → meshData → CDmePolygonMesh → streams`），编辑期 Hammer 用它自己的类：

```
CMapMesh + 0x498   内嵌 CHammerPolyMesh 对象（首 8 字节 = 该虚表）
CMapMesh + 0x560   指向该内嵌对象的实体指针（自指）
CMapMesh + 0x118   CMapMesh 缓存的 AABB（**空 mesh = 全 ±FLT_MAX**；
                   实测 9 个 mesh 里只有 h=51/h=53 有真实 bounds，其余 7 个是空的）
```

`CHammerPolyMesh` 继承 `CPolygonMesh`（半边缘 DCEL），**对象约 13632 字节**。

### 11.11.2 两个虚表 + 相关构造

| 类 | 主虚表 RVA | 说明 |
|---|---|---|
| `CHammerPolyMesh` | `0x1766ED8` | 派生类；`sub_1808B2090` 是它的构造 |
| `CPolygonMesh` | `0x18143D0` | 基类；`sub_180C89010` 是它的初始化 |

`CHammerPolyMesh` 构造 `sub_1808B2090` 初始化了：
`+13440/13448/13456/13464/13472/13480/13488/13496/13504/13512/13520/13528/13536/13544`
（若干 CUtlVector 式三元组）、`+13552` MeasuredHistory、`+13584` bool、
`+13588` int=2、`+13596/-13608` = AABB min/max（±FLT_MAX）、`+13624` ptr。

`CPolygonMesh` 初始化 `sub_180C89010` 初始化了：
`+8/+12/+20 = -1`（哨兵）、`+24/+32/+40`、`+48`、`+56/+64`、`+72/76 = 0x3FFFFF`
（**0x3FFFFF = 无效索引哨兵**）、`+88/+96`、`+104`、`+112/+120`、`+128/132 = 0x3FFFFF`、
`+144/+152`、`+160`、`+168/+176`、`+184/188 = 0x3FFFFF`、`+192/+200`、
`a1+200 = a1`（自指）；随后一堆内嵌子对象：`+208`/`+2848`/`+8104`/`+10744`（各 2640 字节）、
`+5496` 起 30×24 的空闲表、`+6936 = -1`、`+6984/+7208/+7432/+7656`（各 224 字节）、
`+13384/13392/13400/13408/13416/13424/13432`。

`CHammerPolyMesh` 主虚表槽 0–8 在 `0x180CE25A0 / 0x180CE2870 / 0x180CE0E30 / 0x180CE1430 /
0x180CE1F00 / 0x180CE2240 / 0x180CE1D60 / 0x180CE0D10 / 0x180CE0C80`，
槽 9/10 = `0x1808E2A30 / 0x1808E28D0`。**这些多半就是几何访问器**（下一步优先看）。

⚠️ 已试过的歪路：把 `CPolygonMesh` 低偏移的那些 `{ptr,size}` 当顶点数组解引用 —— 结果
全是内部池/哈希桶（含 `0x3FFFFF` 标记、`0x263...` 近似指针的打包值），**不是几何数组**。

### 11.11.3 本轮新增的两个通用排障工具

* `cs2_mem_scan(pattern, limit, start, end)` —— 走 DLL 侧 `scan_heap`（SEH 分块 + 2GB 上限），
  pattern 形如 `48 8B 05 ?? ?? ?? ??`。**一定要给 start/end**，否则从最低地址扫很难到高地址堆。
* `cs2_find_by_vtable(rva, limit, start, end)` —— 按虚表指针找某类实例，
  对**不在 DMX 元素表里的原生对象**（mesh/几何/渲染对象）特别有用。
  自检：`cs2_find_by_vtable('0x176B8E0')` 精确返回 9 个 CMapMesh。

### 11.11.4 下一步（mesh 几何）

1. **优先**：反编译 `CHammerPolyMesh` 虚表槽 0–10，找出
   「取顶点/取面/取 UV」的访问器，然后用 `call_virtual` 直接调用（比猜 offset 稳）。
2. 或找渲染前的"网格→三角形"函数（读 position/texcoord 写 GPU 缓冲），从它反推成员偏移。
3. 若只是要**读**几何，也可以走**存档格式**：`CDmePolygonMesh` 那套 DMX 读法
   （`cs2_mesh_get_geometry` 已实现）对**载入的地图**有效 —— 即打开 `.vmap` 后读。

---

## 11.12 ⭐ 实体 IO 实测结论（2026-09-26，用户加了 trigger_multiple + 一条 IO）

### 11.12.1 结论：编辑期连接**也不在 DMX 里**（同 mesh 的情况）

用户在某 `trigger_multiple` 上加了 `OnStartTouch → !self:Kill`，实测：

* 20+ 个实体的 `connectionsData`（AT 33）**全为 size=0**；
* 元素表里**没有任何 `CDmeConnectionData` 实例**（元素类统计里就没有这个类）；
* `entity_properties`（keyvalue 字典）里**没有** `On...` 键 —— 所以也不是走 VMF 那种
  "输出当 keyvalue"的老路；
* 但**磁盘上的 `untitled_2.vmap` 里有**（用户"编译并保存"后）：
  `DmeConnectionData`(0x12FEC) + `outputName`(0x13049) + `inputName`(0x1301E) +
  `targetName`(0x1302D) + `overrideParam`(0x13010) + `OnStartTouch`(0x13054) +
  `Kill`(0x13028) + `!self`(0x13038) —— **字段名与 VRF 完全一致**
  （用户贴的 `connections=[{sourceEntity/output/targetEntity/...}]` 是 Hammer 剪贴板的
  **KV3 表示**，不是 .vmap 里的名字；`ioTargetType` 在文件里不存在，对应 VRF 的 `targetType`(int)）。

⇒ **Hammer 保存时才会把原生连接转成 `CDmeConnectionData` 元素**，
编辑期连接只在原生结构里。**要活体读 IO 必须找到那个原生结构。**

### 11.12.2 已拿到的东西（为下一步铺路）

| 项 | 值 |
|---|---|
| `CDmeConnectionData` 主虚表 RVA | `0x1779D30` |
| 工厂 Create | `sub_180983AE0` = `new(264)` + `CDmElement` 基类构造 + vtable |
| 对象布局 | 基类 152 字节 + **7 个 16 字节字段**（正好对应 VRF 的 outputName/targetType/targetName/inputName/overrideParam/delay/timesToFire） |
| 属性表定义 | `sub_180983E50`（引用 `outputName`/`inputName`/`targetname` 字符串） |

### 11.12.3 另一个可复用的观察：「元素被编辑过」的字段簇

把 5 个同类 `trigger_multiple` 逐字段比对，只有**用户编辑过的那一个**在这些偏移非 0：

```
+0x100  指向一个含 GUID 串的堆对象（"….12c7f3c-8a33-…"）
+0x198  CMapWorld*
+0x200  堆对象
+0x220  指向 **共享单例**（类虚表 RVA 0x1DEF408）—— mesh 那条 diff 里也是同一个地址
        （疑似当前 undo scope / 编辑器上下文）
+0x228  CMapEntity 次级虚表（0x1759600）
+0x278  {ptr, size} 小向量
```

⇒ 这一簇是「该元素已被实例化/被编辑器接触」的标记（CMapMesh 里"有几何"与"空"的差异
也是同一簇），**不是几何/连接本身**，但可以用它快速判断"哪个元素刚被动过"。

### 11.12.4 下一步（IO 活体读取）

1. 用 `sub_180983AE0`(CDmeConnectionData Create) 的反向：找**保存时创建它**的调用者
   —— 创建是走工厂虚表间接调用，直接 call 扫描找不到（已确认 0 命中），
   需改为在 CE 上对 `sub_180983AE0` 设硬件断点，**保存一次地图**抓调用栈，
   从栈上回溯出原生连接结构的来源。
2. 或退一步：**先实现 .vmap 文件解析**（连接/几何都能读，只是需要先保存）。

---

## 11.13 ⭐⭐⭐ 实体 IO 原生结构已定位并打通（2026-09-26，方案 A 完成 ✅）

§11.12 的结论「编辑期连接只在原生结构里」**得到了确认，并且那个结构已经找到、读写都已验证**。
抓手是**静态反编译 + 剪贴板链路**，不是栈回溯（栈回溯在 §11.12 已被证明不可靠）。

### 11.13.1 关键突破：Outputs 面板的「粘贴」链路

从 KV3 字段名字符串反查 xref，找到这一串函数（全部在 `hammer.dll`）：

| RVA | 作用 |
|---|---|
| `0x1809A01C0` | **原生 Conn → KV3**：`a1` = Conn*，把 `sourceEntity/output/targetEntity/input/param/ioTargetType/delay/timesToFire/relayConnection/fromGlobalRelay/m_paramMap` 写进 KV3 |
| `0x18099EF40` | 把上面这个「数组」写成 KV3 成员 `connections`（元素步长 80） |
| `0x1809A08E0` | KV3 成员回调（名字就是 `"connections"`，hash `-1946358639`） |
| `0x18020D240` | **Outputs 面板 Paste**：读**剪贴板** → `LoadKV3`(generic) → `connections` 数组 → `sub_180986EA0` 逐条塞进实体 |
| `0x180986EA0` | ⭐ **追加一条连接到实体**：`(entityElement, int outHandle[4], const Conn* src)` |
| `0x18099F130` / `0x18099F260` | `Conn::Conn(dst, src)`：先把 dst 全部初始化，再把 src 的 5 个 CUtlString 用 `CUtlString::SetDirect` **深拷贝**过来 |
| `0x180214420` | `CUtlVector<Conn>` 析构：逐条 `FreeMemoryBlock` 5 个字符串 + `sub_1813E7A90(rec+0x30)`（paramMap 析构） |
| `0x18203DBB0` 附近 | KV3 成员描述表（`connections` 成员 → 上面那对序列化/反序列化回调） |

**用户贴的那段 KV3（`connections = [{sourceEntity/.../m_paramMap}]`）就是 Hammer 剪贴板的格式**
——`sub_18020D240` 读的正是 `QGuiApplication::clipboard()` 的文本。

### 11.13.2 ⭐ 结论：连接存在 **CMapEntity 对象自己的原生 CUtlVector<Conn>** 里

```
CMapEntity + 0x4A0  u32  m_nSize        ← 连接条数
CMapEntity + 0x4A4  u32  （常量 0x262，非计数）
CMapEntity + 0x4A8  Conn* m_pMemory     ← 记录数组
CMapEntity + 0x4B0  u32  m_nAllocation
```

`Conn` 结构（**0x50 = 80 字节**）：

```
+0x00  CUtlString sourceEntity        (const char*，Hammer 用 CUtlString::SetDirect 拥有)
+0x08  CUtlString output              ← outputName，如 "OnStartTouch"
+0x10  CUtlString targetEntity        ← targetName，如 "!self"
+0x18  CUtlString input               ← inputName，如 "Kill"
+0x20  CUtlString param               ← overrideParam
+0x28  int        ioTargetType        （默认 7）
+0x30  KV3值      m_paramMap          （16 字节；初始化 = sub_1813E79E0(this, 1, 8)）
+0x40  float      delay
+0x44  int        timesToFire         （-1 = 无限）
+0x48  bool       relayConnection
+0x49  bool       fromGlobalRelay
+0x4C  int        唯一 id（Hammer 自增分配，sub_18099F130 里写）
```

**活体实证**（trigger_multiple `0x26426690C00`，Hammer pid 3824 / hammer base `0x7FF9E3890000`）：

```
+0x4A0 = 1  +0x4A8 = 0x263D411B220  +0x4B0 = 1
Conn[0]: src=0  out="OnStartTouch"  tgt="!self"  in="Kill"  param=0
         type=7  delay=0.0  timesToFire=-1  relay=0  globalRelay=0
```
与用户 KV3 **逐字段一致**。

`ioTargetType` 枚举（`hammer.dll` 内枚举描述表 `0x1816CF740`，32 字节/项，name@+0 / value@+8）：

| 值 | 名字 |
|---|---|
| -1 | `ENTITY_IO_TARGET_INVALID` |
| 2 | `ENTITY_IO_TARGET_ENTITYNAME` |
| 6 | `ENTITY_IO_TARGET_EHANDLE` |
| 7 | `ENTITY_IO_TARGET_ENTITYNAME_OR_CLASSNAME` |

### 11.13.3 为什么之前「`connectionsData` 读到 0 条」是个假象

* `connectionsData`（DMX，AT 33，值布局 `{u32 size@0; u64 data@8; u32 alloc@0x10}`）
  是**保存 .vmap 时生成的临时镜像**：写完文件后 **size 被清零**，
  只留下 `alloc=8` 和一个**陈旧句柄**（实测 `data[0] = 0x18E = 398`，指向那个
  `CDmeConnectionData` 元素 —— 元素还活着但已无人引用，所以看起来"孤儿化"）。
* 因此 **编辑期读 IO 绝对不能看 `connectionsData`**，必须读 `entity+0x4A0`。
* 同时解释了 §11.12 里"保存时才会创建 `CDmeConnectionData`"的现象：那是
  **原生向量 → DMX 镜像** 的单向转换，转换完镜像即被丢弃。

### 11.13.4 落地的 MCP 工具（均已活体验证）

| 工具 | 说明 | 验证结果 |
|---|---|---|
| `cs2_entity_get_io(entity)` | 读 `entity+0x4A0` 原生向量（并附 DMX 镜像条数作对照） | ✅ 读出 `[0] OnStartTouch -> !self:Kill param='' type=7(ENTITY_IO_TARGET_ENTITYNAME_OR_CLASSNAME) delay=0.0 timesToFire=-1 relay=0 globalRelay=0` |
| `cs2_entity_add_io(entity, output, input_name, target, param, delay, times_to_fire, target_type, relay, global_relay, source)` | 调 **Hammer 自己的** `sub_180986EA0` 追加 | ✅ `连接数 1 -> 2`，新记录 `OnTrigger -> !self:Kill param='p1' delay=0.25 timesToFire=3`，Hammer 自动分配了唯一 id |
| `cs2_entity_remove_io(entity, index)` | 后移 80 字节 + 计数减一 | ✅ `连接数 2 -> 1` |

实现要点：
* `_conn_scratch()` 在目标进程里拼一条「源 Conn」（80 字节 + 字符串池），
  并**按 Hammer 的做法**调用 `sub_1813E79E0(src+0x30, 1, 8)` 初始化 `m_paramMap`；
* ⚠ **必须"先写 payload 再初始化 paramMap"** —— 反了会把 paramMap 覆盖成 0（踩过一次）；
* 追加调用走主线程（`_qt_call` → DLL `call_function on_main_thread=true`）；
* 删除时**不回收**被删记录的 CUtlString 内存（`FreeMemoryBlock` 是延迟导入 IAT，
  拿不到稳定 RVA），只泄漏几十字节，不会破坏 Hammer 状态。

### 11.13.5 新增 RVA 速查

| 名称 | RVA | 说明 |
|---|---|---|
| `RVA_ENTITY_ADD_CONN` | `0x986EA0` | `AppendConnection(entityElement, int out[4], const Conn*)` |
| `RVA_CONN_VALUE_INIT` | `0x13E79E0` | `sub_1813E79E0(this, 1, 8)` 初始化 KV3 值（paramMap） |
| `RVA_ENTITY_OFF_CONN_COUNT` | `0x4A0` | `CMapEntity` 原生连接向量（size/data@+8/alloc@+0x10） |
| `RVA_CDME_CONN_DATA_VTABLE` | `0x1779D30` | `CDmeConnectionData`（仅存档镜像用） |

### 11.13.6 未完成 / 已知限制

1. **落盘未打通**（~~已解决，见 [§12](#12--地图保存链路打通--保存后主线程永久卡死定位2026-09-27)~~）：
   旧实现靠触发 Qt 菜单 `&Save`，而 Hammer 在文档"干净"时该 QAction 处于 **disabled**，
   `trigger()` 直接 no-op（实测：强制 `QAction::setEnabled(action,1)`（Qt5Widgets RVA `0x9D10`）
   后再 trigger，文件 mtime/大小仍不变），因为我们的内存写入不会置位「文档已修改」标记。
   → 现已改为**直接调用 `sub_1801639B0`（per-document 保存，a4=1 强制）**，见 §12。
2. **编辑 IO 后未做 UI 侧确认**：`sub_180986EA0` 只追加原生向量，没有走
   Outputs 面板的表格提交（`sub_180206BC0`）与 undo scope；面板刷新时机未验证。
3. `Conn::Conn` 里 paramMap 的 flags 高 32 位与 Hammer KV3 载入路径产出的不完全一致
   （`0x2405` vs `0x5F00002405`），对 .vmap 存档无影响（DMX 镜像里没有 paramMap），
   但走 KV3 序列化路径时值得复核。

---

## 12. ⭐⭐⭐ 地图保存链路打通 + 「保存后主线程永久卡死」定位（2026-09-27）✅

> 目的：让 `cs2_map_save()` 真正把改动落盘（§11.13.6 遗留问题 1）。
> 结论：**已打通且可重复调用**，端到端验证通过（内存加 IO → 保存 → 文件中可检索到）。

### 12.1 保存调用链（Hammer File→Save）

```
sub_1801363C0(session, a2, a3=检查脏, a4=强制)        ← 会话级「保存全部」
  ├─ a3 != 0 时：sub_18097F590(off_1821DC070, doc)   ← 脏判定，脏就走；不脏直接 return 0
  ├─ sub_1801639B0(doc, a2, a3, a4, &vecA, &vecB)     ← ⭐ per-document 保存壳
  │     └─ 打包 doc 列表 → sub_180163BA0(&vector, a2, a3, a4, a5, a6)
  │           ├─ 收集：if (a4 || sub_18097F640(off_1821DC070, doc))   ← a4=1 跳过脏判定
  │           ├─ a3 == 0 时：sub_1814826B0 / sub_18149AB90 "need to be checked out..."
  │           └─ 逐文件 sub_1809806A0(off_1821DC070, doc, a2, 文件名, a3)   ← 真正写盘
  ├─ sub_18089BF80(msg, n)                            ← 状态栏提示
  └─ if (a3 == 0) { sub_180147DD0(session, a2); ... }  ← ⚠️ 编辑会话布局保存（卡死点！）
```

* `doc = *(session + 312) + 16`（`wrapper + 0x10`，即 `CMapDoc`，与 `_map_doc()` 一致）。
* `a5`/`a6` 是「未落盘文件」输出 `CUtlVector`，两个函数内部都有判空 → **传 0 即可**。

### 12.2 卡死根因（2026-09-26 那次「保存成功但 Hammer 冻死」）

* 之前调的是**最外层** `sub_1801363C0(session, 0, 0, 1)`，`a3=0` 命中了最后那个
  `if (!a3)` 分支 → `sub_180147DD0(session)` → 取/存**编辑器会话布局**（窗口停靠布局），
  该链路最终进入 `assetsystem.dll+0x8950E` → `tier0.dll+0x12153` 并**永久阻塞**。
* 现场证据（`injector/scan_stack.py <pid> all`，主线程 RSP 原生扫描）：

  ```
  rip  tier0.dll+0x12153                     ← Wait/LpcReply，CPU 冻结
       tier0.dll+0x12481
       assetsystem.dll+0x8950E
       hammer.dll+0x1306C9F
       hammer.dll+0x1F41A6
       hammer.dll+0x89BD16
       hammer.dll+0x1367A7                   ← = sub_1801363C0+0x3E7，正好是
                                                 `call sub_180147DD0` 的返回地址
       cs2_tool.dll+0xFD8A / +0x1041B        ← 我们的 WH_GETMESSAGE 钩子派发
       user32.dll+0x237C6                    ← 消息循环
  ```
* **注意**：文件其实在这之前就已经写完了（`sub_1809806A0` 先执行），
  所以表现是「文件已更新，但 Hammer 从此不再响应、管道也一起挂掉」。

### 12.3 落地实现（绕过卡死分支）

不调 `sub_1801363C0`，**直接调 per-document 壳**：

```python
# cs2_mcp_server.py
RVA_HAMMER_SAVE_DOC = 0x1639B0
doc = _map_doc()
pipe.call("call_function", {
    "address": hex(hammer_base + RVA_HAMMER_SAVE_DOC),
    "args": [doc, 0, 0, 1, 0, 0],   # a2=0, a3=0, a4=1(强制), a5=NULL, a6=NULL
    "on_main_thread": True,
    "timeout_ms": 30000,
})
```

* `a4=1` 强制保存，**不要求文档处于「已修改」状态**（我们的原生写入本来就不置脏标记）。
* `a3=0` 保持与交互式保存一致的检查路径，但**不会**走 12.2 那段布局保存。
* 实测耗时 **0.2s**，`main_thread_status=0`、`ret=0x1`，连续调用无副作用。
* `cs2_map_save()` 工具还会回显保存前后的文件字节数 / mtime，便于确认「真的落盘了」。

### 12.4 RVA 速查

| 名称 | RVA | 说明 |
|---|---|---|
| `RVA_HAMMER_SAVE_DOC` | `0x1639B0` | per-document 保存壳（**推荐入口**） |
| `sub_180163BA0` | `0x163BA0` | 内部逐文件保存 + 干净/脏/强制判定 |
| `sub_1809806A0` | `0x9806A0` | 单文件真正写盘 |
| `sub_1801363C0` | `0x1363C0` | 会话级「保存全部」（⚠️ `a3=0` 会卡死，勿用） |
| `sub_180147DD0` | `0x147DD0` | 编辑器会话布局保存（卡死源，勿调） |

### 12.5 端到端验证（2026-09-27）

在 `cs_script_demo.vmap`（68,868,325 B）上：

1. `cs2_entity_add_io(0x5bb710b3000, "OnUser1", "Kill", "!self", param="E2E_MARK_003852", delay=1.25)`
   → `连接数 0 -> 1`
2. `cs2_map_save()` → `ret=0x1`，文件 `68869381 → 68869511` 字节（+130 B），mtime 更新
3. 在 .vmap 里检索 `E2E_MARK_003852`：**新文件命中 1 处，保存前备份 0 处** ✅
4. 连调 2 次 `map-save` 均 0.2s 返回，Hammer 保持 `Responding=True`，管道仍可用 ✅

### 12.6 排障工具（本轮新增，可复用）

* `injector/scan_stack.py <pid> [关键字|all]`：StackWalk64 在本环境第一帧就失败，
  改用**逐页读栈 + call-site 校验**（`E8 rel32` / `[REX] FF 15 disp32` / `FF D0-D7`）。
* `injector/qt_button.py find|click` / `injector/open_map.py`：Qt/原生对话框驱动。
* ⚠️ 排查卡死时**不要**用 CE 的 `DebugActiveProcessStop` 去摘调试器 —— 会让目标进程被内核终止。

---

## 13. ⭐⭐⭐ CHammerPolyMesh 原生几何读取打通（2026-09-27）✅

§11.11 只确认了「几何在 `CMapMesh+0x498` 的内嵌 CHammerPolyMesh 里」，本轮把**顶点坐标 /
面顶点环 / 世界包围盒**全部读出来了，并落地 `cs2_mesh_get_geometry`。

### 13.1 定案：官方访问器 = `sub_180CC2830`（hammer.dll）

它是「面 → 顶点坐标数组」的官方实现（`CUtlVector<Vector>* ` 出参），
完整链路（`a2` = 面 handle，`a4` = 输出向量）：

```
面 handle --(面映射表, count@poly+0xA0, 表@poly+0xA8, 24B/条)--> 槽位
   槽位 --> 面池记录(poly+0x90 起, 32B/条) 的 [0..16) 16 字节 = 首条半边 handle
半边 handle --(半边映射表, count@poly+0x68, 表@poly+0x70, 24B/条)--> 槽位
   槽位 --> 半边池记录(poly+0x58 起, 80B/条)：+0 = 起点顶点 handle，+0x20 = 下一条半边 handle
顶点 handle --(顶点映射表, count@poly+0x30, 表@poly+0x38, 24B/条)--> 槽位
   槽位 --> 顶点池记录(poly+0x20 起, 32B/条)：+0x10 = 位置通道数据下标
位置 = *(poly+2264+24*通道号 的 +8 指针) + 12*下标      ← 12B/顶点、Vec3
坐标再经 sub_180BFDAA0(a3) 做变换后写入出参
```

* **handle 编码**：低 22 位 = 索引，高位 = 序列号；`0x3FFFFF` = 无效哨兵。
  映射表每项 24B：`{槽位@+0, ?@+4, 句柄@+8}`，校验 = 索引一致 && `(handle^stored)&0xFFC00000 == 0`。
* **CUtlVector 布局**（代码里反复出现）：`{count@+0, ?@+4, ptr@+8, capacity@+0x10, flags@+0x14}`，共 24B。
* **必须先过映射表校验再遍历**：半边 handle 空间有 50 槽（`poly+0x68 = 50`），
  但一个方块只有 24 条半边是活的，其余槽是空闲链；顺序遍历半边池会把空闲槽当边读。
* 环的终止条件：`next` 的索引回到「本面的首条半边索引」（不是池槽位）。

### 13.2 定案字段表（偏移全部相对 `poly = CMapMesh+0x498`，即其虚表地址）

| 偏移 | 含义 |
|---|---|
| `+0x18 / +0x20` | 顶点记录池 `CUtlVector`：活顶点数 / 数据指针（记录 32B） |
| `+0x30 / +0x38` | 顶点 handle→槽位 映射表：项数 / 指针（24B/项） |
| `+0x50 / +0x58` | 半边记录池：条数 / 指针（记录 **80B**） |
| `+0x68 / +0x70` | 半边 handle→槽位 映射表：项数 / 指针 |
| `+0x88 / +0x90` | 面记录池：面数 / 指针（记录 **32B**） |
| `+0xA0 / +0xA8` | 面 handle→槽位 映射表：项数 / 指针 |
| `+0x688` | 通道集控制字：低字节 `==2`（表示「通道集」），**次字节 = 位置通道号** |
| `+0x8CC + 通道号` | 该通道 present 标志（笔刷方块只有 ch0 = 1） |
| `+0x8D8 + 24*通道号` | 通道描述符：`{count@+0, ?, data@+8, cap@+0x10}`，共 6 个通道 |
| `+0x1110` | 半边 handle 列表（24B？实为 16B 记录的 handle 对，待细究） |
| `+0x351C / +0x3528` | 自身 AABB min/max（±FLT_MAX = 空） |

> ⚠️ 旧笔记（§11.11.2）里 CPolygonMesh 初始化列的 `+48/+56/+64/...` 是**以 `poly+8` 为基**的，
> 与上表相差 0x8，对照时注意。

### 13.3 世界坐标与轴序（本轮定案）

* 通道里存的是**本地坐标**，世界坐标 = 本地 + `CMapMesh+0xA0`（Vec3，即元素 origin）。
* 分量顺序就是标准 **(x, y, z)**，**z 轴朝上**。判据（活体实测 `cs_script_demo.vmap`）：
  * `h=773`：8 顶点/5 面的 384×512 平面，**z 厚度恰为 0** ⇒ 是地板；
  * `h=754`：64 格地板薄板，z 只有 8；`h=835`：y 厚度为 0 的竖墙。
* 面顶点环是**逆时针且法线朝外**（32 方块顶面 `v0→v1→v5→v2` 叉积 = +Z）。
* `CMapMesh+0x118` 是缓存的 AABB，布局 `{u32 保留, xmin, ymin, zmin, xmax, ymax, zmax}`；
  用户新画的 mesh 上它与顶点算出的世界包围盒**逐位一致**，但地图自带的 tile/mesh 上不一致
  （见 13.6 已知问题），所以**以顶点为准**，`+0x118` 只当交叉校验。

### 13.4 用户放的 32 / 64 / 128 方块 —— 活体验证 ✅

| 边长 | 元素地址 | handle | origin（= 包围盒中心） | 世界包围盒 | 顶点/面 |
|---|---|---|---|---|---|
| 32 | `0x5bac7ba0000` | 425 | (336, 848, 16) | (320, 832, 0) ~ (352, 864, 32) | 8 / 6 |
| 64 | `0x5bac7ba4000` | 442 | (320, 768, 32) | (288, 736, 0) ~ (352, 800, 64) | 8 / 6 |
| 128 | `0x5bac7b8c000` | 499 | (224, 608, 32) | (160, 544, -32) ~ (288, 672, 96) | 8 / 6 |

三个方块全部返回 **8 顶点 + 6 个 4 顶点面环**，坐标全整数且与包围盒自洽（32/64 底面 z=0 落地）。
`cs2_mesh_list` 也能列出它们（该地图共 40+ 个 CMapMesh；`h=394/438/482/526/571/615` 等
是几万~几十万顶点的「tile 静态 mesh」，不是手画的）。

### 13.5 通道框架（为什么笔刷方块没有 UV）

6 个通道描述符（`poly+0x8D8 + 24*i`），笔刷方块的 present 标志是 `[1,0,0,0,0,0]`：

| 通道 | 语义（代码 `sub_180D04240` 里 `*(a1+1672)` 的次字节） |
|---|---|
| 0 | **position**（Vec3，12B/顶点）← 本工具用到的 |
| 1..5 | 其它顶点/面属性（normal / texcoord / 颜色 / …），笔刷方块**全为空** |

⇒ 笔刷 mesh 的 UV **不在几何里**，由「面材质 + 该面的贴图轴」决定（Hammer 的 brush side 概念）。
`poly+0x1240 / 0x1328 / 0x1428` 有 3 个 24 项的 Vec2/Vec3 数组（值域 {0,±0.5,±1}，
量正好 = 6 面 × 4 角），**疑似**每面角的 UV / 贴图轴 / 法线，但**尚未确认**，需要 UV 时再挖。

### 13.6 已知问题 / 下一步

1. **非手画 mesh 的 pivot 语义不同**：`h=754 / h=773` 这类地图自带 tile mesh 的
   `+0xA0` 是 (0,-32,0)，与其顶点算出的包围盒在不同参照系（尺寸一致、位置/轴序有差），
   说明它们还带一个完整变换（很可能是 `sub_180BFDAA0(a3)` 里的矩阵，待查调用点）。
   本工具对「mesh 工具画出来的」元素已验证正确。
2. ~~UV / 材质：见 13.5，需接着定 `poly+0x1240..0x1480` 三个 24 项数组的语义。~~
   → **已解决，见 §13.8**（texcoord/normal/tangent + 逐面贴图参数 + 材料名表）。
3. ~~`poly+0x1110` 那个 24 项 handle 列表与「半边池 50 槽」的对应关系还没完全对上。~~
   → **已解决，见 §13.8.1**：它是「密集序 → handle 索引」映射表。
4. 贴图轴 `w` 分量含义未解（见 §13.8.3）。

### 13.7 RVA 速查

| 名称 | RVA | 说明 |
|---|---|---|
| `sub_180CC2830` | `0xCC2830` | **面 → 顶点坐标** 官方访问器（本轮逆向的入口） |
| `sub_180D04240` | `0xD04240` | 通道描述符读取样本（`+2264+24*ch`，`+8` 是数据指针） |
| `sub_180BFDAA0` | `0xBFDAA0` | 顶点写入出参前的变换（参数 `a3` 由调用方给，待查） |
| `sub_180856150` | `0x856150` | 生成 "EmbeddedNode.<类名>" 显示名 + `hammer_embedded_properties` 面板 |
| `sub_180CD6A90` | `0xCD6A90` | CPolygonMesh 的 Clear/Reset（**末尾 16B 步长释放 CUtlString**，证明材料名表布局） |

---

## 13.8 ⭐⭐ 面/半边属性：UV、法线、切线、材质（2026-09-27 续）✅

已有几何（§13.1）之后，把**逐面贴图参数 + 逐面材质 + 逐角 UV/法线/切线**也读通了。
字段对应关系来自 VRF（`third_party/ValveResourceFormat`）的 `HammerMeshBuilder.WriteMesh`，
它就是把 `CPolygonMesh` 写成 `.vmap` 里 `CDmePolygonMesh` 的那段代码 —— **流名与运行时成员一一对应**：

| .vmap 流（VRF） | 作用域 | 运行时偏移（相对 `poly`） | 元素 |
|---|---|---|---|
| `position:0` | 顶点 | `+0x8D8` 通道描述符 ch0 | Vec3（12B） |
| `texcoord:0` | 半边 | **`+0x1240`** | Vec2（8B） |
| `normal:0` | 半边 | **`+0x1328`** | Vec3（12B） |
| `tangent:0` | 半边 | **`+0x1428`** | Vec4（16B，w=手性） |
| `textureScale:0` | 面 | **`+0x3118`** | Vec2（Hammer 默认 0.125） |
| `textureAxisU:0` | 面 | **`+0x3300`** | Vec4 |
| `textureAxisV:0` | 面 | **`+0x3318`** | Vec4 |
| `materialindex:0` | 面 | **`+0x33B8`** | int（索引进材料名表，-1 = 无） |
| `flags:0` / `lightmapScaleBias:0` | 面 | **`+0x33D0` / `+0x33E8`** | int |
| `materials`（字符串表） | 网格 | **`+0x3448`** | `CUtlVector<CUtlString>`，**16B/条**，条首 qword = 名字指针 |
| 半边「密集序 → handle」 | 网格 | **`+0x1110`** | 16B/条，条首 u32 低 22 位 = handle 索引 |

### 13.8.1 ⚠️ 关键坑：逐半边属性按「密集序」排列，不是按池槽位

半边池有 50 个 handle 槽（`poly+0x68 = 50`），活跃的只有 24 条，池槽位 `0..23` 但 handle 索引是打散的
（例如 24、6、48、21…）。逐半边属性数组**按密集序 `0..活跃数-1` 排列**，必须用
`poly+0x1110`（密集序 → handle 索引）映射，否则会「串面」。

判据（实测，32 方块）：按**池槽位**或**handle 索引**直读 `+0x1328`，同一个面的 4 条半边法线各不相同；
按**密集序**读则完全一致，且正好是该面法线（顶面 `(0,0,1)`、底面 `(0,0,-1)`、x 面 `(±1,0,0)`、y 面 `(0,±1,0)`）✅

### 13.8.2 实测结果（32 方块）

* 材质：`materials/dev/reflectivity_30.vmat`（`materialindex` 全 0，材料名表 1 项）✅
* 每面 4 角 UV 构成规整的 0.5×0.5 矩形（如顶面 `(-0.5,0.5) (0,0.5) (0,0) (-0.5,0)`）；
  贴图轴与面朝向自洽：顶/底面 `U=X, V=-Y`，x 面 `U=Y, V=-Z`，y 面 `U=X, V=-Z` ✅
* 多材质 mesh 对照（`h=11`，113 顶点/97 面，地图自带地板）：材料名表 3 项
  `colorcode_green / dev_measuregeneric01c / reflectivity_30`，各面 `textureScale` 不同（0.25 / 0.0625）✅
  ⇒ 存储的 texcoord 是**按材质纹理尺寸归一化**的 UV（可 >1 表示平铺、可负），不是 0..1 限制值。

### 13.8.3 贴图轴的 w 分量：只在部分面上等于 UV 偏移

VRF 的重建公式是 `uv = (dot(axis, pos_world) / scale + offset) / textureSize`。
单个面能对上、但不是所有面都能对上（实测 box `0x3e12abe8000`，同一网格两种材质）：

| 面 | 材质 | axisU/axisV(w) | 反推 textureSize | 反推 offset | 内存里的 w |
|---|---|---|---|---|---|
| face[5] | noillum_primary_green | (1,0,0, w=1600) / (0,0,-1, w=2976) | 512 | **1600 / 2976** ✅ 与 w 一致 | 1600 / 2976 |
| face[0..4] | reflectivity_30b | (1,0,0, w=0) / (0,-1,0, w=0) | 32 | **−5568** ❌ w=0 | 0 |

⇒ 公式的 `dot(axis, 世界坐标)/scale` 部分成立（Δ 完全对得上），但 `w` **不是**一致的偏移量：
绿色材质面上 w 就是偏移，30b 材质面上 w=0 却需要一个 −5568 的偏移。所以：

* 工具**直接输出存储的 texcoord 数组值**（权威，与公式无关），axes/scale 只作参考；
* `w` 的真实语义（疑似「只在某些对齐状态下才写入」或「相对某个网格级基准的差值」）留待后续。

### 13.8.4 工具

`cs2_mesh_get_geometry(mesh, max_faces)` 现在每个面还会打印：
`材质=<名字>` + `贴图 scale=(..) U=(..,w=..) V=(..,w=..)`，每个角打印 `uv=(u, v)` 与 `n=(x,y,z)`。
实测 32/64/128 方块与地图自带多材质 mesh 均正确。
**多材质交叉验证**（重启后新文档，box `0x3e12abe8000`，材料名表 2 项）：
`face[0..4] = materials/dev/reflectivity_30b.vmat`、`face[5] = materials/dev/noillum_primary_green.vmat`
⇒ `materialindex → poly+0x3448 表` 的映射确认无误（不是 `poly+0x3488` 那张同名表）。

实体 IO（`cs2_entity_get_io`）也一并复验：地图里 12 个实体有连接，
如 `OnTrigger -> scriptent:RunScriptInput param='StartTraining' type=7 delay=0 timesToFire=-1` ✅
（IO 与 mesh 无关，属 `CMapEntity+0x4A0` 原生 `CUtlVector<Conn>`，见 §11.13）

---

## 13.9 范围查询用的 mesh 包围盒：缓存 AABB vs 顶点（2026-09-27）

给 `cs2_area_query` 定「按世界 AABB 圈选」的数据源时，把 70 个 mesh 两种来源逐个对比：

* **元素缓存 AABB `el+0x118`**（布局 `{u32, xmin, ymin, zmin, xmax, ymax, zmax}`，几乎零成本）
  * 与「顶点 + `+0xA0`」算出的世界包围盒 **逐位一致**：所有手绘方块 / 多数面片都 OK（40+ 个样本）
  * 对 **单面 mesh**（`nv=4 / nf=1`）会把**某个轴压成 0 宽**：如 `h=292` 给出 `x=[-176,-176], y=[1136,1216], z=[96,176]`，
    而顶点算出来是 `x=[-232,-152], y=1160, z=[96,176]` —— 两者退化轴**互补**（怀疑元素带 90° 旋转，
    顶点只做平移相加不够，可比 §13.6）
* **顶点 + origin**：对 `nv` 大的地图自带 tile mesh（`h=394/438/482/…`）会算出**只有零点几单位**的荒谬小盒
  （位置通道不在世界尺度上，需要 `sub_180BFDAA0(a3)` 那个变换），缓存 AABB 反而是合理的那个

**结论 / 工具策略**：默认用缓存 AABB；若它某轴被压成 0 宽（单面/旋转 mesh），再花小代价用
顶点重算并**取并集**（宁可范围外扩、不漏对象）。`nv>4096` 时不算顶点盒；两种来源的差异只影响
「圈选范围」的精度，精确几何仍以 `cs2_mesh_get_geometry` 为准。

---

## 13.10 ⭐⭐ 写 mesh 顶点（缩放 mesh 大小）—— 官方算子 `SetVertexPositions` ✅

### 13.10.1 算子表

字符串表（就在 `CPolygonMesh` 虚表 `0x1818143D0` 后面）给了一张操作名清单：
`SetVertexPositions / AddFace / MirrorAcrossPlane / FlipAllFaces / DissolveEdge / AddVertexToEdge /
AddEdgeToFace / CollapseEdge / CollapseFace / CopyFaceMaterialIndex / ConnectEdges / BevelVertex /
BevelFaces / QuadSliceFace / MergeVerticesWithinDistance / SplitEdges`

| RVA | 签名 | 说明 |
|---|---|---|
| `0xCDC6E0` | `sub_180CDC6E0(poly, CUtlVector<顶点handle>*, 3x4矩阵*, CUtlVector<Vector>*)` | **官方算子 "SetVertexPositions"**：开事务(名字就是 `"SetVertexPositions"`) → 写位置通道 → `sub_180CB78C0`/`sub_180CCF570` 更新缓存 → `sub_180333B60` 发脏通知 |
| `0x9B8880` | `sub_1809B8880(element, handles*, positions*)` | 元素级包装：**取元素变换**（`vfn+160` → 48B）→ `sub_180BFA650`（转成存储空间）→ 调上面的算子。所以它收**世界坐标** |
| `0xBFDAA0` | `sub_180BFDAA0(矩阵, x, y, z) -> (x', y', z')` | **3×4 行主序矩阵**变换：`movups [rcx]/[rcx+10h]/[rcx+20h]` 三行 + 向量 `(x,y,z,1)`。单位矩阵 = `{1,0,0,0, 0,1,0,0, 0,0,1,0}` |
| `0xBFA650` | — | 元素变换 → 存储空间变换（world→local 之类，未细究） |

### 13.10.2 为什么用「单位矩阵 + 本地坐标」而不是元素级包装

元素级包装（`sub_1809B8880`）收世界坐标，但把「网格本地坐标」换算成世界只能靠
`local + CMapMesh+0xA0` —— 这个假设**只对手绘 mesh 成立**（见 §13.6/§13.9 的 tile mesh 反例）。
直接调 `sub_180CDC6E0` 并传**单位矩阵**，写进去的就是我们给的值（不再做任何参照系换算），
于是对任何 mesh 类型都精确、且语义清晰：**按网格本地轴缩放**。

* 顶点 handle 向量：16B/条（首 u32 = handle），与 `poly+0x1110` 那张「密集序→handle」表同构；
  结构 = `CUtlVector` 头 `{count@0, ?@4, data@8, cap@0x10, flags@0x14}`。
* 活跃顶点怎么来：顶点 handle 映射表 `poly+0x30`（24B/条，`{池槽位@0, ?@4, 句柄@8}`），
  `句柄低22位 == 下标` 即活跃；顶点记录 `+0x10` = 位置通道数据下标。
* 位置通道有「写解锁标志」：`poly+0x8D2+ch`（算子内部首写时置 1 并取可写指针），
  实测连续调用不会卡住（0.13s/次、可重复、Hammer 保持响应）。

### 13.10.3 实测（`cs2_mesh_scale`）

手绘盒子 `h=1159`（32×8×32，origin=(-456,1020,-268)）：

| 操作 | 结果 |
|---|---|
| `scale="2 2 2"` | 包围盒 → `(-488,916,-300) ~ (-424,932,-236)` = **64×16×64**（= 2×，且按 pivot 精确）✅ 0.13s |
| `scale="0.5 0.5 0.5"` | **完全还原**成 `(-472,968,-284) ~ (-440,976,-252)` ✅ |
| `scale="1 2 1"` @ 自定义 pivot | → `32×16×32` 完全符合预期 ✅ |
| 地图自带 tile mesh `h=773` | 本地轴 ×2 精确、×0.5 还原 ✅（世界轴与之不同，工具里注明了这个 caveat） |

元素缓存 AABB（`el+0x118`）由 Hammer **异步**刷新，写完立刻读可能还是旧值（一拍之后才对上）。

---

## 14 ⭐⭐ 实体参数（keyvalue / 变换）读写 —— 全部走 Hammer 高层写入器 ✅

### 14.1 结论：实体 keyvalue 一律以 AT_STRING 存储，数值型也是字符串

对活体 cs_script_demo（182 实体 / 260 元素）逐个枚举 `CEditGameClassProps` 属性链实测：

```
=== 0x3e12ab70400 classname='func_movelinear' props=0x3e16d019e80 ===
    spawnflags     type=5  vp=0x3e16d134630 '0'
    speed          type=5  vp=0x3e16d134680 '100'
    movedir        type=5  vp=0x3e16d134620 '0 0 0'
    rendercolor    type=5  vp=0x3e16d1345b0 '255 255 255'
    rendermode     type=5  vp=0x3e16d134590 'kRenderNormal'
    movedistance   type=5  vp=0x3e16d134690 '100'
    targetname     type=5  vp=0x3e16d134500 'chess.q'
    classname      type=5  vp=0x3e16d019f18 'func_movelinear'
```

**所以「修改实体数值/向量参数」不需要任何按类型分派的写入器**：`spawnflags="3"`、
`rendercolor="255 0 0"`、`movedir="0 0 1"` 都是写字符串，Hammer 在编译/运行期自己解析。
（先前 §8.2 里「按类型分派 `sub_18062CA90` 那一族写入器」的待办因此**作废**。）

### 14.2 类型码实测表（`attr+0x1C` 低 6 位）

| 码 | 语义 | 出处 / 证据 |
|---|---|---|
| 1 | 元素句柄(u32) | `entity_properties` / `relayPlugData`，值就是 CDmElementHandle_t |
| 2 / 3 / 4 / 7 | 32 位整数族 | `sub_1805CE490`（int 写入器）分支条件是 `n4-3 & ~4 == 0`（n4∈{3,7}）或 `n4==2` / `n4==4`，四条都写同一个 dword；`nodeID`(2)、`isProceduralEntity`(4, 值 0x01010100) 实测 |
| 5 | **AT_STRING**（CUtlSymbolLarge） | 全部实体 keyvalue；`sub_18062C9A0` 用 5 创建 |
| 8 | **AT_COLOR** | `sub_1805CF1F0` 里 `CUndoAttributeSetValueElement<Color>::vftable`、值写 dword |
| 10 | **AT_VECTOR3**（Vec3D<float>） | `sub_1805CEA30` 要求 `attr+1C&3F == 0xA`，写 12 字节；`hitNormal` 实测 |
| 15 | 16 字节定长值 | `referenceID`（16B）；类型名表附近有 `"4/8/16-byte data pool"` |
| 33 | 元素句柄数组 | `children` / `connectionsData` |
| 37 | 字符串数组 | `variableNames` / `variableTargetKeys` |

类型总表（`qword_1824B8090[1..16] / [33..48]`，`sub_1805DB5E0(type)` 取名字）
对应的 `CUndoAttributeSetValueElement<T>` 实例共 16 个，活体名表：
`CUtlSymbolLarge / CUtlBinaryBlock / Color / int / float / bool / DmeTime_t / QAngle /
QuaternionStorage / Vec2D<float> / Vec3D<float> / Vec4D<float> / VMatrix /
DmElementHandle_t / uint64 / uint8`
（vtable：`0x1816C54B0 / 5508 / 5560 / 55B8 / 5610 / 5668 / 56C0 / 5718 / 5770 / 6750 / 69E0 / 6C70 / 7370 / 7838 / 7AC8 / 7D58`）。

### 14.3 两条写入链路（推荐）

| RVA | 签名 | 用途 |
|---|---|---|
| `0x83E0D0` | `sub_18083E0D0(entity, const char* name, const char* value)` | **keyvalue 首选**。属性缺失时以 AT_STRING(5) 创建；值变化后调 CMapEntity 类回调(vfn+2136)、`targetname` 名字索引(vfn+1272/2160)、包围盒/脏通知(`sub_1808672E0`/`sub_180867040`)。内部用 `entity+1336` 的 entity_properties 句柄 |
| `0x86B550` | `sub_18086B550(entity, const char* name, const char* value, uint flags)` | **变换(origin/angles/scales)专用**。取实体的 CMapNode 属性表按声明类型分派：变换属性由 `CMapNodeTransformPin` 落到 CMapEntity 原生 Vec3D（`+0xA0/+0xAC/+0xB8`），普通 keyvalue 也照写。属性不存在返回 0（不创建） |
| `0x62C9A0` | `sub_18062C9A0(ownerElement, name, value, createIfMissing)` | 更底层的按名写字符串（原 `cs2_entity_set_attr` 用法），无类回调/包围盒通知 |

**为什么变换不能走 keyvalue 写入器**：`sub_1808327B0`（预制件键重映射）里对
`origin/angles/scales` 做了显式**排除**（`V_stricmp_fast(key,"origin") && …("angles") && …("scales")`
时才调 `sub_18083E0D0`；命中三个名字之一则改走 `sub_18086B550`）。
若误用 `0x83E0D0`/`0x62C9A0` 写 `origin`，只会在 `CEditGameClassProps` 上凭空造一个同名
AT_STRING（不移动实体）。

### 14.4 实体属性链结构与安全摘除

* `CDmElement + 0x48` = `CDmAttribute*` **单向链表头**；`attr+0x00` = next，`attr+0x20` = 名字指针。
* `sub_1805C7590(el)` 就是 `return *(el+0x48)`（取头）；`sub_1805C7170(el, &token)` 按
  **驻留串指针相等**查找（`while (*token != attr[4]) attr = *attr;`）—— 说明链表**就是唯一索引**，
  没有额外的名字哈希表，因此手动摘链是安全的。
* 摘链后调 `sub_1805C81C0(el, 3)` 让 datamodel 传播脏状态（该函数把标志或进 `el+0x5E/+0x60`
  并递归通知依赖者）。
* 摘除配方（实测摘掉测试时误建的 `zzz_test_key` 后，`classname/targetname/spawnflags/speed`
  全部完好）：找到前驱 `prev`，`prev+0 = attr->next`（`prev==0` 时写 `el+0x48`）。

### 14.5 实测（真 MCP 通道 + 直连管道）

`cs2_entity_set_attr(entity, name, value)`：

| 目标 | 操作 | 结果 |
|---|---|---|
| `func_movelinear` 0x3e12ab70400 | `spawnflags` `'0'→'3'→'0'` | 读回一致 ✅ |
| 同上 | `rendercolor` `'255 255 255'→'255 0 0'→`还原 | ✅ |
| 同上 | `speed` `'100'→'150'→'100'` | ✅ |
| 同上 | `origin` `(32,-96,96)→(200,300,40)→`还原 | ret=1，原生成员立即变化 ✅ |
| `info_target` 0x3e164fc3c00 | `angles` `(0,0,0)→(0,45,10)→`还原 | ✅ |
| 同上 | `scales` `(1,1,1)→(2,2,2)→`还原 | ✅ |
| 同上 | `targetname` `'h8'→'probe_node_attr'→'h8'` | ✅ |
| 新建属性 `zzz_test_key` | 写入 `'abc'` | 属性链上新建成功（读回 `'abc'`），事后手动摘除 ✅ |
| 不存在的名字 | `no_such_attr` | 也会新建 AT_STRING —— 注意这是**副作用**，删属性需按 14.4 摘链 |

副产物观测：

* keyvalue 写入**会推进 Datamodel undo 栈**（`CUndoManager+0`：7→8→9）；
  **变换写入不动它**（写的是原生成员，不经过 CDmAttribute），这与「变换不在属性链上」互证。
* Hammer **只按空白分隔**解析三元组：`"0.2,0.2,0.2"` 被解析成 `(0.2, 0, 0)`（`,` 是终止符）。
* `CMapDoc` 自己的「已修改」标志在写入后**未变化**（前 0x900 字节 diff 为 0 处不同），
  即这类底层写入不会点亮 Hammer 的未保存提示 —— 需要留存改动时请显式保存。
* 顺手打开的 Datamodel undo 总开关（`CUndoManager+0x84` bit3）会**保持打开**。

---

## 15 地图撤销 Pop 重定位 + 官方「放置/改类」序列 + 三条踩坑（2026-09-27）

### 15.1 ⭐ 地图撤销 `CMapDocHistory::Pop`：旧 `0x14080D0` → 新 **`0x1529E80`** ✅

新版 `CMapDocHistory` 虚表 RVA `0x1763E00`（旧 `0x1628508`），4 个方法：

| slot | 字节偏移 | 新 RVA | 旧 RVA | 说明 |
|---|---|---|---|---|
| 0 | 0 | `0x86D910` | `0x75F980` | 析构类 |
| 1 | 8 | `0x86DD50` | `0x75FDC0` | 引用 `IUndoable`/`CMapNode` |
| 2 | 16 | `0x86E2B0` | `0x760320` | 只是「跨多个历史对象分发」的包装（现在转调 `0x181529E80`） |
| 3 | 24 | `0x86D970` | `0x75F9E0` | **CanUndo 守卫**（Pop 内部会调它） |

真正的「弹出并应用」在 `0x181529E80`（**RVA `0x1529E80`**），反编译与旧版
`sub_1814080D0` **逐行一致**：

```c
if (g_gate && !this->busy/*+0x8C*/ && this->enabled/*+0x90*/ && this->vfn3_CanUndo()) {
    last = count ? array[count-1] : 0;
    sub_181529290(this->pair/*+0x80*/, last + 36, 1, 0);   // 推给配对历史（撤销<->重做）
    --count;                      // ← 就是旧版 CE 抓到的 dec [rbx+8]
    busy = 1;
    ... 逐条应用反操作(sub_181529D20) ...
    busy = 0;
    sub_181528660(last); sub_1802D6ED0(last, 192);         // 释放条目
}
```

* 结构布局与旧版**完全一致**：`+0x08` count / `+0x10` 数组 / `+0x18` 容量 /
  `+0x80` 配对历史 / `+0x8C` busy / `+0x90` enabled。
* 最外层全局开关：旧 `byte_1820F2088` → 新 **`hammer.dll+0x221A418`**（实测 = 1）。
* **空栈安全**：vtable[3] 是 CanUndo 守卫，count=0 时整段跳过（不像 Datamodel undo
  那样会破坏 undo 系统内部状态）。
* 撤销/重做**共用**这一个函数，靠传入的 this 区分（`CMapRootElement+0x240` 撤销 /
  `+0x248` 重做）。已接进 `cs2_map_undo` / `cs2_map_redo`。
* **✅ 端到端验证通过（2026-09-27）**。方法：让用户在 Hammer 里真实编辑一次（放置一个
  `info_player_start`，历史 4 步，未保存），然后跑**自包含往返验证**
  `A --undo--> B --redo--> C --undo--> D`（不依赖预先抓的基线，避免和用户编辑的时序打架）：

  | 状态 | undo 步 | redo 步 | 实体数 | world 子节点 |
  |---|---|---|---|---|
  | A（用户编辑后） | 4 | 0 | 183 | 130 |
  | B（undo 后） | 3 | 1 | 182 | 129 |
  | C（redo 后） | 4 | 0 | 183 | 130 |
  | D（再 undo） | 3 | 1 | 182 | 129 |

  判定：**A ≠ B**（撤销真的移除了那个实体 `0x27318b32c00`）、
  **C == A**（重做后 183 个实体的 classname/targetname/坐标**逐个一致**）、
  **D == B**（可重复）。计数每次都精确 ±1，配对历史推进正确。
  详见 PROGRESS §8.2 第 28 行 ②。
* ⚠ 我们通过 MCP 做的写入**不进地图历史**（Datamodel undo 与 CMapDocHistory 是两套栈），
  所以必须在 Hammer UI 里真实操作一次才会有条目可撤。

### 15.2 ⭐ 官方「放置对象 / 改类名」序列（`sub_180180190` = `mapviewdroptarget.cpp`）

拖放处理器的三个分支（`prop_static` / `info_particle_system` / `.vmdl`）**完全同构**：

```c
node = sub_18089A5C0(??, 0, "…mapviewdroptarget.cpp", line);   // 工厂 Create（CDataModel vfn+152）
node->vfn+136(&pos);                                           // 设变换
node->vfn2144(classname, 0, 0);                                // ★ SetClassName
sub_18083E0D0(node, "model" / "effect_name", 值);              // 写其它 keyvalue
sub_180866D70(node, 0);                                        // ★ 设类名后置节点状态
sub_180879170(doc, node, 0);                                   // ★★ CMapNode::AddChild（doc = *(…+312)+16）
sub_18083E560(node);                                           // （prop_static 分支才调）
```

| RVA | 签名 | 说明 |
|---|---|---|
| `0x879170` | `sub_180879170(doc, child, siblingOr0)` | **官方 AddChild**。⚠ 第一参数是 **CMapDoc**（不是父节点）：函数内默认锚点 `a3 = *(doc+136)`，而 `136=0x88` 正好是 `CMapDoc->CMapWorld` 字段 → 锚点=世界。child 已有父则跳过重设父；否则 `anchor⇢vfn456(child)`（设父）→ `sub_180887A40(doc, child)` 插入 → `sub_180861500(child,2)` → 空间/索引更新（`sub_180870460(doc+32 / *(doc+24)+8)`）。**内部自己会更新索引** |
| `0x866D70` | `sub_180866D70(node, flag)` | 置 `node+0x118(=280) = flag+1`，递归子节点；全局开关开时再调 `vfn+1888(1)` |
| `0x864EA0` | `sub_180864EA0(node)` | **GetParent**（实测：func_brush 的父 == `CMapDoc+0x88` 的 CMapWorld；info_target 的父是中间容器节点） |
| `0x864EB0` | `sub_180864EB0(node)` | **GetRoot/World**（实测全部实体都指向 CMapWorld） |
| `0x89A5C0` | `sub_18089A5C0(a1, a2, file, line)` | 工厂 Create：`CDataModel vfn+152(dm, &typeToken, a2, a1, 0)` → `resolve` → `vfn+32` IsA 校验 → `sub_18086A5B0(node, file, line)` 记录创建点 |

**`world.children` 是 pin 属性**（实测）：`attr.valueStore == world+0x1F8`，
即 DMX 的 `children` 与原生 `CUtlVector<handle>`（count@+0x1F8 / ptr@+0x200 / cap@+0x208）
是同一块内存。想手工追加时用官方算子
`sub_1805DAF80({valueStore, attr}, &handle)`（Hammer 自己拼 `children` 就用它，
会正确扩容；实测 128→129 且 alloc 128→256）。

### 15.3 ⚠⚠ 踩坑 1：**不要**对 world 调粗粒度置脏

`sub_1805C81C0(world, 3)`（= `CDmElement::MarkDirty(world, value|structure)`）之后，
`cs2_entity_list` 从 ~1s 涨到 **165–200s**（触发Hammer病态的整世界重建），
最终把主线程拖死。**AddChild 内部已经会做正确的索引更新，不要额外置脏整个 world。**

### 15.4 ⚠⚠ 踩坑 2：**不要**在「主线程派发」中途杀掉客户端

实测（2026-09-27）：脚本正在 main-thread 派发时被 `StopCommand` 杀掉 →
Hammer 主线程**永久阻塞**：`Responding=False`、CPU 不再增长（阻塞而非死循环）、
Qt 出现隐藏窗口 `[WatchdogThreadWndClass] Stall Detected`、无模态框。
管道随之卡死（连 `ping` 都不回）。**恢复方式只有重启 Hammer。**

> 第二次同样卡死（这次没有杀客户端）：`cs2_entity_create` 的新序列
> （CreateElement → vfn2144 → `0x866D70` → `0x879170`）整段把主线程卡住。
> **根因**：AddChild 的第一参数被写成了 `CMapWorld`，而它要的是 **CMapDoc**
> （函数内 `a3 = *(a1+136)`，`136=0x88` 正好是 `CMapDoc->CMapWorld` 字段；
> 实测 `*(doc+136) == world`，`*(world+136) == 0` → 传 world 时锚点为 null）。
> 改正后同一序列 **0.08s 正常返回**，不再卡。已写进 `RVA_NODE_ADD_CHILD` 注释。

### 15.4b ⚠⚠⚠ 踩坑 3（重要）：管道自带的 `call_virtual` 会**静默丢弃** `str:` 参数

`injected_dll/ipc_pipe.cpp` 里两个方法的参数解析完全不同：

```c
// call_function：支持 "str:文本"（在本进程 VirtualAlloc 一份 C 字符串传指针）
if (s.rfind("str:", 0) == 0) { ...args.push_back(mem); }

// call_virtual：字符串只当“模块地址”解析，解析失败就**跳过**
else if (v.type == String) { if (bridge.ResolveAddress(v.sval, a)) args.push_back(a); }
```

→ `call_virtual(this, 2144, ["str:info_target", 0, 0])` 实际传进去的是 `[0, 0]`
（`str:` 那项被丢掉、后面的参数整体左移）。而 `sub_180896390`(SetClassName) 开头就是
`if (!a2 || !*a2) { ... return; }` —— **收到空类名直接返回**。

**这就是长期结论「CMapEntity vtable 2144 SetClassName 无效」的真因**：不是虚函数无效，
是我们的调用通道把它喂成了空指针。（`_resolve_handle` 用纯整数参数，所以从来没暴露。）

**规避（已在 Python 侧全部改掉）**：新增 `_call_vfn(this, vtable_offset, args, timeout)`
—— 自己读 `*(this)` 取虚表、读 `*(vtable+pointer)` 取函数指针，再用 `call_function`
调用（它支持 `str:`）。

**✅ DLL 侧已修（2026-09-27，见 §15.6）**：`call_virtual` 与 `call_function` 的参数解析
合并为 `ParseCallArgs`，支持 `str:`；且**解析失败的字符串压 0 保持参数个数**（不再左移）。
已重新构建 `cs2_tool.dll` 并注入验证（`arg_count=3`、类名生效）。Python 侧 `_call_vfn` 保留。

### 15.4c ✅ 官方放置序列 + 改类名 —— 端到端验证通过（2026-09-27）

`cs2_entity_create("info_particle_system", "cs2_e2e_test")`（Hammer 内实测）：

| 步骤 | 结果 |
|---|---|
| CreateElement | handle `0x800144`，0.11s |
| vfn2144（`_call_vfn`） | ret=0，**类名已生效** |
| 写 classname 属性 | ret=0（保证存档正确） |
| `sub_180866D70` | ret=0x28af5c51dc8 |
| `sub_180879170`(AddChild, doc) | ret=0，0.08s |
| world 子节点数 | **130 → 131** |
| GetParent | **== CMapWorld ✅ 已挂进世界** |
| 游戏类 `+0x550` | **0x28bde87c780（已绑定）** |
| CParticleHelper | **0x28c31359e00（已创建 ✅）** |
| 总耗时 | 1.73s |

随后 `cs2_entity_set_classname(ent, "info_target")` → `+0x550` 由
`0x28bde87c780` **换成 `0x28bde87c140`（重建成功 ✅）**、helper 归 0（该类无 helper ✅）、
classname 读回 `info_target` ✅。

结论：**「新建实体 → 挂进世界 → 绑定游戏类 / 重建 helper」整链打通**，
`cs2_entity_create` 建出的实体已经是可用的真实体（变换、属性、类名都能改）。

### 15.5 性能实测（优化前基线，2026-09-27）

**优化前** `list_entities`（182 实体 / 260 场景元素）的往返构成：

| 项 | `limit=200` 次数 | 单次耗时 | 小计 |
|---|---|---|---|
| `read_value`（属性链逐字段） | 22,753 | ~0.8ms | ~18s |
| `read_string`（逐字段读属性名） | 10,235 | ~1.8ms | ~18s |
| `get_module`（每实体一次取基址） | 636 | **40ms** | **~25s** |
| `call_virtual`（每节点一次主线程 resolve） | 635 | **~31ms** | **~20s** |
| `read_memory`（子节点数组） | 227 | ~0.9ms | ~0.2s |
| **合计** | **34,487** | 平均 3.3ms | **114.12s** |

`limit=20` 时 7,904 次 / **22.65s**（树遍历的 635+636 次是固定成本，占绝大部分）。

四个真凶（都不是「往返 2.2ms」那么简单）：
1. **每个子句柄一次主线程 `call_virtual`** 解析成元素（`_walk_elements` 里）；
2. **每个实体一次 `get_module`** 取 hammer 基址（模块枚举 40ms，被调了 636 次）；
3. **属性链逐字段往返**：每看一个属性 3 次（next / 名字指针 / 名字字符串），
   props 链 ~35 个属性 × 每实体两轮查找（classname + targetname）；
4. **每次 IPC 都 `CreateFileW` + `CloseHandle`**，且每次 Win32 调用都重建 `ctypes.WinDLL`。

→ 修复与实测结果见 **§15.6**。

---

### 15.6 ⭐⭐⭐ `cs2_entity_list` 提速 48.6× + DLL 侧修复（2026-09-27）

#### 15.6.1 结果（同会话成对测量，输出逐字节一致）

| 场景 | 优化前 | 优化后 | 提升 |
|---|---|---|---|
| 稳定会话 `limit=200` | **114.12s** / 34,487 次 | **2.35s** / 3,145 次 | **48.6×** |
| 稳定会话 `limit=20` | 22.65s / 7,904 次 | 0.56s / 751 次 | 40× |
| 刚开图（繁忙）`limit=200` | 265.82s / 33,246 次 | 12.54s / 2,776 次 | 21× |

> ⚠ 绝对耗时随 Hammer 忙闲漂移很大（同一份新代码 10 分钟内从 12.54s 变成 21.35s：
> 刚打开地图时进程持续满载渲染，`read_value` 从 0.8ms 涨到 1.4ms、`map_list_docs`
> 从 21ms 涨到 141ms）。**要做对比必须同时段成对测**，别跨会话比绝对值。

#### 15.6.2 Python 侧改动（5 项，未动 DLL）

**① 句柄 → 元素改查 CDataModel 元素表（最大单项）**

元素表：`g_CDataModel + 0x90` 数据指针 / `+0x88` 容量，**16 字节一项，元素指针在 +8**，
**下标 = 句柄低 22 位**（`handle & 0x3FFFFF`）。实测：

```
handle=311  vfn168 -> 0x28bdf7cc000   table[311] -> 0x28bdf7cc000   match=True
handle=319  vfn168 -> 0x28c10190000   table[319] -> 0x28c10190000   match=True
...（连续 8 项全部一致）
```

于是 `_walk_elements` 里**每个子句柄一次主线程 `call_virtual`（~31ms）彻底消失**，
整条树遍历变成纯内存读。新增 `_dm_table()`（批量读全表并缓存，键 = `(base, arr, cap)`）、
`_dm_handle_element(handle)`。

**② 属性链块读 + 驻留串名缓存**

CDmAttribute 对象**按 0x30（48）字节步长连续分配**（实测同一元素链上相邻节点地址差
恒为 48，偶有跳跃）。所以 `_dm_find_attrs` 改成**一次块读 8KB**，块内顺着 `next`
走完 ~21 个节点，只有跳出块时才补读。属性名是驻留串（`CUtlSymbolLarge` = 裸 `char*`），
用**指针 → 字符串缓存** `_SYMBOL_NAMES`，命中后查一个属性名**零额外读取**。
再把 `classname` + `name` 合并成**一次遍历取齐**（原先 props 链要遍历两遍）。

**③ 树遍历每节点一次块读**

vtable 在 `node+0`、子节点数/句柄数组在 `+0x1F8/+0x200` —— 都在 0x208 字节内，
所以一次块读同时拿到三者（原来要 3 次往返：vtable + count + ptr）。
`_walk_elements` 因此改为 yield `(element, vtable)`，调用方不必再单独读 vtable。

**④ 管道长连接 + 缓存 kernel32**

DLL 的 `ClientThread` 本来就是「`ReadRequest` → `HandleRequest` → `SendResponse`」循环
（一个连接可服务多次调用），但 Python 侧 `Cs2Pipe.call` 每次 `_open()`/`_close()` —— 光
`WaitNamedPipeW` + `CreateFileW` + `CloseHandle` 就占了单次往返的大半。改成**复用句柄**，
读写失败才关掉重连重试一次。另外 `_kernel32()` 原来**每次 Win32 调用都重建
`ctypes.WinDLL` 并重设 argtypes**，改为进程内缓存。

**⑤ 缓存 hammer 基址（第二大单项）**

`get_module` 单次 **40ms**（模块枚举很贵），而 `_entity_class_props` → `_dm_table` →
`_hammer_base` 让**每个实体都调一次**（636 次 ≈ 25s）。改为进程内缓存：
`_hammer_base()` 缓存结果，**`Cs2Pipe._open()` 一建立新连接就调
`_invalidate_address_cache()` 作废** —— 重连意味着对端可能换过进程（Hammer 重启/重注入），
这样既拿到 40ms→1 次的收益，又不会在换进程后用到陈旧基址。

#### 15.6.3 DLL 侧改动（`injected_dll/ipc_pipe.cpp`，已重新构建并注入）

**⑥ `call_virtual` 参数解析与 `call_function` 合并**（修 §15.4b 的缺陷）

抽出共用的 `ParseCallArgs`：`Number` → 值；`"str:文本"` → 本进程 `VirtualAlloc` 后传指针；
其它字符串 → 当模块地址表达式解析。**关键**：每个元素都必须压一个参数，
**解析失败压 0 而不是跳过** —— 跳过会让参数整体左移（这正是 §15.4b 的根因）。
`call_virtual` 的响应里新增 `arg_count`，便于直接验证参数个数。

验证（活体，`vfn2144` SetClassName）：

```
call_virtual(this=ent, 2144, ["str:info_target", 0, 0]) -> arg_count=3, ret=0x0, status=0
    classname = 'info_target'          ent+0x550 = 0x272d039e000   （游戏类对象已替换）
call_virtual(this=ent, 2144, ["str:info_player_terrorist", 0, 0]) -> arg_count=3
    classname = 'info_player_terrorist' ent+0x550 = 0x272d0485f40   （精确还原）
call_virtual(this=ent, 2144, ["not_a_module_expr", 0, 0]) -> arg_count=3   （不再左移）
```

**⑦ `read_memory` 上限 1024 → 8192，十六进制改查表编码**

原来逐字节 `snprintf("%02x")`；改成 512 字节静态查表（`HexTable`，C++11 保证函数内
静态初始化线程安全）。实测**单次耗时与读取大小无关**：

| size | 64 | 256 | 1024 | 2048 | 4096 | 8192 |
|---|---|---|---|---|---|---|
| 单次耗时 | 1.48ms | 1.37ms | 1.41ms | 1.53ms | 1.51ms | **1.43ms** |

（同一繁忙会话里 `ping` 是 0.275ms，可见编码开销已≈0。）Python 侧 `MAX_READ_CHUNK`
同步改成 8192。

**⑧ `SendResponse` 改循环写**

大响应（如 8KB → 16KB 十六进制）可能超过管道缓冲区，单次 `WriteFile` 只写一部分
就会让响应流错位（客户端读到的就是垃圾）。改成和 `ReadRequest` 对称的循环写。

#### 15.6.4 回归验证

`cs2_entity_get_attr` / `cs2_entity_get_transform` / `cs2_entity_find_attr` / `cs2_map_info` /
`cs2_area_query` / `cs2_mesh_list` 全部正常（`area_query` 同时受益：它的实体段也走
元素表 + 批量属性读）。

---

### 15.7 ⭐⭐ 大图实测（`ze_surf_easy`）+ `_enum_elements` 静默截断 bug（2026-09-27）

拿一张真实反编译的 ZE 图（`content/csgo_addons/ze_surf_easy/maps/ze_surf_easy.vmap`）压测，
暴露出一个**会漏对象**的真 bug。

#### 15.7.1 元素表规模事实（与 264 元素的小测试图完全不同的量级）

| 项 | ze_surf_easy | 小测试图 `cs_script_demo` |
|---|---|---|
| `dm+0x88` cap（表容量） | **97,102** | 2,130 |
| 表内非零项 | **12,958** | ~264 |
| 场景元素（走世界树） | 8,546 | 264 |

表内类型分布（vtable → 类名，类名由 IDA 按 RVA 查符号得到）：

| RVA | 类 | 个数 |
|---|---|---|
| `0x1758d00` | `CMapEntity` | 4,403 |
| **`0x175e2b8`** | **`CEditGameClassProps`** | 4,404 |
| `0x176b8e0` | `CMapMesh` | **4,124** |
| `0x176c3e0` | `CMapStaticOverlay` | 13 |
| `0x178b4a8` | `CMapGroup` | 5 |

**结论**：① 每个实体都配一个 `CEditGameClassProps` 元素（1:1，小图上没注意到的独立一层）；
② 反编译/塌陷过的 surf 图会把每个笔刷都变成 `CMapMesh`（4124 个）；
③ **遍历元素表（12,958 次 vtable 读）比走世界树（8,546 个元素）更贵**，所以「列地图对象」
一律优先走树 —— 表只用于「找不在树里的元素」这种诊断场景。

#### 15.7.2 🐛 bug：`_enum_elements` 的 `limit=8192` 静默截断

旧实现是 `for i in range(min(cap, limit))` 且 `limit` 默认 **8192** ——
`cap=97,102` 时**只扫了表的前 8.4%**，且不报错、不提示。后果：

| 现象 | 实际 | 旧报告 |
|---|---|---|
| `cs2_mesh_list` 的 mesh 总数 | 4,124 | **338** |
| `cs2_area_query` 的 `mesh_total` | 4,124 | **338** |
| 同一个小盒查询命中的 mesh | **18** | **4** |

即 `area_query` **漏掉了 78% 的命中对象**（handle ≥ 8192 的完全看不到）——
大图上「按范围取内容」这个核心用途直接失真。

**修法**（2026-09-27）：
1. `_enum_elements`：`limit<=0`（新默认）= 扫全表；表数据改走 `_dm_table()` 批量读
   （97k 项 ≈ 190 次块读 0.3s），只对非零项读一次 vtable；文档写清代价与「优先走树」。
2. `cs2_mesh_list` / `cs2_area_query` **改走一趟 `_walk_elements`**：走树时 vtable
   顺带就有（不用额外读），用 `vt` 分类收集 mesh 与实体。
   - `area_query` 顺带把「先扫表找 mesh、再走树找实体」的两趟合成一趟（原来重复劳动）。
   - 输出里的 `h=` 是句柄，走树只拿到地址 → 新增 `_dm_handle_map(table)`（纯本地反查，无 IPC）。
   - 顺带修掉 `area_query` 头部把「实体 x/**8546**」写成分母为**元素总数**的措辞问题，
     现在分母是真正的实体数 4403。

修复后复测：`cs2_mesh_list` → **4,124** 个；小盒查询 → **mesh 18/4124 实体 1/4403**。

#### 15.7.3 大图功能测试（全部通过）

| 项目 | 结果 |
|---|---|
| 全部 `CMapMesh` 读运行时几何 | **4,124 个全成功**（0 失败、0 缺 poly），合计 36,715 顶点 / 27,095 面，平均 8.9 顶点/mesh |
| 材质分布 | `toolsnodraw` 3345 / `zoo/concrete` 1672 / `zoo/tile` 1239 / `toolsplayerclip` 547 / `toolstrigger` 275 … |
| 全部实体读原生 IO | 4,403 个实体中 **155 个有连接、共 820 条**（3.5%） |
| IO 内容抽样 | `OnTrigger→server:Command param='mp_freezetime 1'`、`zr_infect_mzombie_respawn 120`、`OnStartTouch→!self:Kill`、`OnStartTouch→tele_05:Enable delay=40.0` |
| 单个 mesh 几何 | `h=13`：8 顶点 / 24 半边 / 6 面 / 1 材质，本地坐标为整数、世界 = 本地 + origin，UV 与法线正确 |
| 实体属性/变换/类名 | `trigger_hurt` / `targetname='falldmg_tr'` / origin 精确 |

#### 15.7.4 大图性能实测（背景数据，同一繁忙会话 ~3ms/往返）

| 工具 | 耗时 | 往返 |
|---|---|---|
| `cs2_entity_list(limit=200)` | 52.86s | 14,969 |
| `cs2_entity_list` 全量（4403 实体） | 194.40s | 65,602 |
| `cs2_mesh_list(10)`（修复前） | 13.95s | 9,268 |
| 全量读 4,124 mesh 几何 | 701s | ~72k `read_value` |
| 全量读 4,403 实体 IO | 47.41s | — |

⚠ **`limit` 不省成本**：必须先走完整棵树才知道总数，所以大图上 `limit=200` 也要 52.86s
（占全量的 27%）。「只想瞄一眼」在大图上依然慢 —— 这是已知的待优化项（方向：
early-exit、树遍历合并块读），本轮按用户要求暂不动。

---

### 15.8 ⭐⭐ 元素类型全谱 / 属性类型码补全 / 补齐「漏读的数据」（2026-09-27）

接着 §15.7 的大图，把「图里存在但工具没读」的数据系统盘了一遍，并补上两个工具。

#### 15.8.1 元素表 RVA → 类名全谱（IDA 按 RVA 取符号名）

| RVA | 类 | ze_surf_easy 里的数量 |
|---|---|---|
| `0x1758D00` | `CMapEntity` | 4,403 |
| `0x175E2B8` | `CEditGameClassProps` | 4,404 |
| `0x176B8E0` | `CMapMesh` | 4,124 |
| `0x176C3E0` | `CMapStaticOverlay` | 13 |
| `0x178B4A8` | `CMapGroup` | 5 |
| `0x17C2718` | `CMapSelectionSet` | 1 |
| `0x1763FA8` | `CMapRootElement` | 1 |
| `0x17F1428` | `CMapVariableSetStorage` | 1 |
| `0x17EC118` | `CVisibilityMgr` | 1 |
| `0x1763EA8` | `CStoredCameras` | 1 |
| `0x1763E28` | `CStoredCamera` | 1 |
| `0x1772920` | `CMapWorld` | 1 |
| `0x16C37D0` | `CDmElement`（基类，doc 级杂项） | 2 |

#### 15.8.2 各元素的属性清单（实测；★ = 本轮之前工具没暴露的）

**CMapEntity 自身链（11 项）** —— 注意**每个实体都有一个 1:1 的 `CEditGameClassProps` 元素**：
```
isProceduralEntity(4)  hitNormal(10)  entity_properties(1)  connectionsData(33)
relayPlugData(1)       variableNames(37)  variableTargetKeys(37)  children(33)
referenceID(15)  nodeID(2)  name(5)
```
★ `nodeID` = Hammer 里的对象编号（`CMapGroup.children` / `CVisibilityMgr.nodes` 引用的就是句柄，
实测 entity 的 nodeID 与句柄常常相同但不保证）；★ `referenceID` = 8 字节对象 ID；
★ `children` 是 DMX 镜像（走树用的是原生 `+0x1F8/+0x200`）。

**CMapMesh（7 项）**：`meshData(1,in编辑期 INVALID)` `variableNames` `variableTargetKeys`
`children` `referenceID` `nodeID` `name` —— **几何全在原生 CHammerPolyMesh，DMX 里没有**，
而原生几何我们已读（§13）。所以 mesh 侧只剩 `textureAxisU/V.w` 语义未定。

**CMapStaticOverlay（8 项）**：`projectionTargets(34)` `meshData(1,INVALID)`
`variableNames` `variableTargetKeys` `children` `referenceID` `nodeID` `name`
→ 实际贴花数据（材质/渲染顺序/投影参数）**在原生结构里，尚未逆向**（已知缺口）。

**CMapRootElement（16 项）** —— 地图文档根：
```
nodeInstanceData(33)  m_bCordonsVisible(4)  m_bIsCordoning(4)  m_ReferencedMeshSnapshots(33)
rootSelectionSet(1)   mapVariables(1)  visbility(1)  world(1)  3dcameras(1)  defaultcamera(1)
itemFile(5)  editorversion(2)  editorbuild(2)  isprefab(4)  name(5)  $prefix_attribute$(1)
```
链路：`CMapDoc+0x80` -> root（vtable `0x1763FA8`，与 `_find_map_histories` 同源）。
实测 `editorversion=400`、`editorbuild=10912`。

**CMapWorld（12 项）**：`mapUsageType(5)='standard'` `fixupEntityNames(4)` `nextDecalID(2)`
`entity_properties(1)` `connectionsData` `relayPlugData` `variableNames` `variableTargetKeys`
`children(33)` `referenceID` `nodeID=1` `name`

**CMapGroup（6 项）**：`children(33)`（= 成员**元素句柄**表）`variableNames`
`variableTargetKeys` `referenceID` `nodeID` `name`
**CVisibilityMgr（8 项）**：`nodes(33)`（= 6069 个元素句柄）`hiddenFlags(34)`
`variableNames` `variableTargetKeys` `children` `referenceID` `nodeID=0` `name`
> 实测 `nodes` 与 `hiddenFlags` 长度**都是 6069** → 两者并行，`hiddenFlags` 是逐节点的标志数组。
**CMapSelectionSet（4 项）**：`selectionSetData(1)`（当前选中，INVALID=空）`selectionSetName(5)`
`children(33)` `name`
**CMapVariableSetStorage（8 项）**：`variableNames/VariableValues/variableGroupNames/
variableTypeNames/variableTypeParameters(37 数组)` + `variableAndChoiceOrder(34)` + `m_ChoiceGroups(33)`
**CStoredCameras（3）**：`cameras(33)` `activecamera(2)` `name`
**CStoredCamera（3）**：`lookat(10)` `position(10)` `name`

#### 15.8.3 属性类型码补全（实测值存储字节数）

| 码 | 名字 | 值存储 | 证据 |
|---|---|---|---|
| 1 | element_handle | 4B（`0xFFFFFFFF`=无效） | 全图通用 |
| 2 | int | 4B | `nodeID` 读数干净（9/11/12…） |
| **4** | **bool** | **1B** | ⚠ 见下 |
| 5 | string | 8B（char*） | 全图 keyvalue |
| 10 | vec3 | 12B | `hitNormal`/`position` |
| **15** | **id** | **8B** | `referenceID` |
| 33 | element_array | 24B（CUtlVector 头） | `children` |
| **34** | **数组** | 24B（CUtlVector 头） | `hiddenFlags` 实测 count=6069/cap=6069 |
| 37 | string_array | 24B | `variableNames` |

**⚠ 踩坑：`type=4` 是 1 字节 bool，按 u32 读会带上后 3 字节的未初始化内存。**
实测同一个字段：`entity.isProceduralEntity` 原始 `00 7b 53 3f …` → 读成 `1062435584`；
`world.fixupEntityNames` 原始 `01 00 00 00 …` → 恰好后 3 字节为 0 所以看起来正常（更隐蔽）。
已改成只读 1 字节。

**⚠ 踩坑：`type=15` 只占 8 字节**，别读 16 —— 后 8 字节是相邻内存（实测都是 `0x549_xxxx` 形态的堆指针，
连续多个属性共享同一高位段）。读 16 会把垃圾当 ID 的高半。

**`type=34` 已证实是 CUtlVector**（`hiddenFlags`：`count=6069 / cap=6069`，数据全 0），
但元素宽度未定（`projectionTargets`、`variableAndChoiceOrder` 都是空数组，没有反例），
所以只报表头 + 前 16 字节，不猜。

#### 15.8.4 修 `_read_int(u64)` 的有符号问题

DLL 的 `read_value` 返回的是**有符号** JSON 整数，最高位为 1 的值会变负数 —— `referenceID`
曾被打印成 `'0x-114e62cf3cd44a44'`，高位地址同理（`hex()` 出来是负的，回传给 DLL 还会解析失败）。
`_read_int` 现在按声明位宽强制还原无符号（`_UINT_WIDTH`）。

#### 15.8.5 新增两个工具

* **`cs2_entity_attrs(entity)`** —— 列出实体**全部**属性（keyvalue 链 + 实体自身链，各带类型码）。
  补上了「只能按名字猜着查 keyvalue」这个最大的实用缺口。实测 `trigger_hurt` 有 23 项 keyvalue
  （`damage='999999'` / `damagecap='999999'` / `spawnflags='4097'` / `StartDisabled='1'` …），
  `logic_script` 有 `Group00~Group15` + `vscripts='ze_surf_easy/ze_surf_easy.nut'`。
* **`cs2_map_groups()`** —— 分组 / 可见性组 / 当前选择集 / 地图变量 / 相机。
  实测 ze_surf_easy：5 个分组（328 个实体 / 3585 个 CMapMesh / 光照探针 6 个 / 18 个 ambient_generic），
  可见性组 `nodes` 6069 个，选择集为空，无地图变量，`defaultcamera` 有 position/lookat。
* `cs2_entity_list` 每行补 `id=<nodeID>`。

实现上把属性链遍历抽成了**单一实现** `_dm_iter_attrs()`（生成器），`_dm_find_attrs`（找齐即停）
与 `_dm_walk_attrs`（全量）都基于它，避免两份块读逻辑漂移。

#### 15.8.6 仍未获取的数据（已知缺口）

1. **`CMapStaticOverlay` 的实际贴花数据** —— DMX 里只有 `meshData`(编辑期 INVALID) 与
   `projectionTargets`，材质/渲染顺序/投影参数在原生结构里，未逆向。
2. **`type=34` 数组的元素宽度**（疑似 1 字节 bool，缺反例）。
3. **`textureAxisU/V.w` 语义**（§13.8.3，老遗留）。
4. **Hammer 视口 / 网格 / 当前工具等 UI 状态**（不在 DMX，需从 CHammerApp 侧挖）。
5. **`0x175E2B8` 之外的游戏类侧数据**（`CMapEntity+0x550` 游戏类对象内部字段，未展开）。

### 15.9 ⭐⭐ 删除实体：`AddChild` 的对偶虚表槽 `父节点+0x1D0`（2026-09-27）

#### 15.9.1 定位过程

`cs2_entity_create` 用的官方 AddChild 是 `sub_180879170(doc, child, 0)`，其反编译里
出现关键一行 `(*(*(a3) + 456))(a3, a2)` —— **加子节点是父节点虚表字节偏移 456(0x1C8)
的虚函数**。于是对称地找移除槽：

| 类 | `+0x1C8` AddChild | `+0x1D0` RemoveChild |
|---|---|---|
| `CMapWorld` | `sub_180925C10` | **`sub_180925C60`** |
| `CMapEntity` | `sub_18084F2F0` | **`sub_18084F400`** |
| `CMapGroup` 等 6 个类 | `sub_1809EB6F0` | `sub_1809EB760` |

静态校验：`CMapWorld` vtable 运行时 `0x7fff8ca92920` = `base + 0x1772920`，
`+0x1D0` → IDA 里 `0x181772af0` 存的确实是 `sub_180925C60` ✅；
`CMapEntity` 的 `base + 0x1758D00 + 0x1D0 = 0x181758ed0` 存的是 `sub_18084F400` ✅。

```
sub_180925C60(parent, child):            // CMapWorld 的槽，第三参数 r8 **原样透传**
    sub_18084F400(parent, child, r8)     // 指令级确认：mov rbx,rcx / mov rdi,rdx 后直接 call，**没有设 r8**
    rcx = *(parent + 0x1820)
    if (rcx) sub_180BA05A0(rcx, child)

sub_18084F400(parent, child, notify):    // 真正的移除实现
    id = sub_1800897C0(child)
    if (sub_1805E0000(parent + 504, &id) == -1) return;   // ⚠ 守卫：child 不在 parent 子表里就什么都不做
    ... 从 parent 子表摘除 ...
    (*(child_vtable + 504))(child, 0)                     // 清 child 的父指针
    if (notify) {
        (*(parent_vtable + 128))(parent, 2)
        v7 = (*(parent_vtable + 1272))(parent, 0)
        if (v7) sub_1808786F0(v7, child + 308)            // 追加 24B 记录到 doc 的待处理表
    }
```

`notify` 取值依据：`CMapGroup` 等 6 个类的槽实现在 `sub_1809EB760` 里**硬编码传 1**
（`sub_18084F400(a1, a2, 1)`，之后再做一批子类收尾），而 world/entity 的槽是透传本轮
调用方给的值。故删除工具**默认 `notify=True`**。

#### 15.9.2 关键结论：`children` 是 DMX 属性，与原生子表同构

`parent + 0x1F8`（计数）/ `+0x200`（句柄指针）**就是** `children` 属性（AT 33
元素句柄数组）的内联 CUtlVector 头，不是两套数据：

```
原生 +0x1F8 子节点数 = 636
DMX 属性 children 元素数 = 636
  两者集合相同: True           ← 逐项一致
  原生里有而属性里没有: 0
  属性里有而原生没有: 0
```

所以删除是**一致且可存档**的（`children` 属性同步 → 保存 .vmap 不会写回被删实体），
不是只改内存镜像。实测被摘除的 3 个临时实体在原生表与 `children` 属性里**都已消失**。

#### 15.9.3 实测（A/B + 端到端，全部成功）

| 用例 | 结果 |
|---|---|
| 裸链路建临时实体 → `vfn0x1D0(child, 0)` | `children 637→636`、`GetParent → 0x0`、6ms |
| 同上但 `notify=1` | `children 637→636`、`GetParent → 0x0`、8ms、`ret` 非 0 |
| 新工具 `cs2_entity_delete` 正常删除 | `637→636`、`GetParent 0x54958488000→0x0`、`仍在 children 属性里: False`、5ms |
| 新工具删 `CMapWorld` | 直接拒绝（返回提示，不调用） |
| 新工具重复删同一实体 | 报「没有父节点（已是游离节点）」+ 打印元素表 handle |

#### 15.9.4 已知语义（重要，写进工具的 docstring）

* **不产生 Undo 历史** —— `vfn0x1D0` 直接改原生子表，不经过 Hammer 的 Undo 命令层，
  Ctrl+Z 恢复不了。（这也是用户看到「没有历史」的原因。）
* 被摘下的 `CDmElement` **仍留在 CDataModel 元素表里**（孤儿），本会话内不回收；
  已不属于世界树，`cs2_entity_list` / `cs2_mesh_list` 都看不到。
* 实体自带的 `CMapMesh` 子节点**随整棵子树一起脱离世界**（不做逐节点递归摘除）——
  实测 `trigger_hurt` / `trigger_once` / `func_buyzone` 等实体各有 1 个 `CMapMesh` 子节点；
  `CMapWorld` 的直接子节点里有 39 个 `CMapMesh`、5 个 `CMapGroup`、4 个 `CMapStaticOverlay`、588 个 `CMapEntity`。
* 该槽对**任意** `CMapNode` 都可用（不限于实体），工具非实体时只报 vtable RVA。

#### 15.9.5 新工具

**`cs2_entity_delete(entity, notify=True)`** —— 摘除实体整棵子树；返回父节点、随之脱离的
子树规模（实体/mesh/其他计数）、`children` 计数前后、`GetParent` 前后、是否仍在属性里，
并显式提示「不产生 Undo 历史 / 元素成孤儿」。

### 15.10 ⭐⭐⭐ 把操作写进 Hammer 的撤销历史（`CMapDocHistory` 记录型接口）（2026-09-27）

用户问「创建和删除怎么加历史」。结论：**Hammer 的历史栈是「记录型」的，当成可写接口用即可，
不需要自己实现 Undo/Redo**。

#### 15.10.1 两套撤销系统（成对实测）

* **栈 A = `CMapDocHistory`**（`CMapRootElement+0x240` 撤销 / `+0x248` 重做）—— **Hammer 的 Ctrl+Z**
* **栈 B = DMX `CUndoManager`**（`g_CDataModel+240`）—— `_undo_scope_*` 那套，属性级

一次 create + 一次 delete 的成对测量：

| 时点 | 栈 A undo / redo | 栈 B |
|---|---|---|
| 基线 | **27 / 0** | 1190910 |
| `cs2_entity_create` 之后 | **27 / 0**（不动） | 1190928（+18） |
| `cs2_entity_delete` 之后 | **27 / 0**（不动） | 1190929（+1） |
| `cs2_entity_set_attr`（孤儿）之后 | 27 / 0 | 1190929 |

→ 这就是「删了但没历史」的根因：我们的操作只进栈 B，而 Ctrl+Z 读的是栈 A。
（另注：栈 B 的 `+0` 是**单调计数器**而非栈深度，取值 119 万级。）

#### 15.10.2 栈 A 的数据结构（活体 dump + 反编译逐行对齐）

**步对象 192B**（`sub_181529290` 内 `sub_1803D4300(192)` 分配）：

```
+0x00 u32 命令数      +0x04 (未初始化残留)  +0x08 ptr 命令数组
+0x10 u32 容量        +0x14 u32 flags       +0x18 ptr 所属 CMapDocHistory（回指）
+0x20 u32 步ID（dword_18221A41C 递增）      +0x24 char name[128]   ← Ctrl+Z 菜单显示的那串
+0xA4 byte            +0xA8 CUtlString       +0xB0 16B 结构（合计 192 = 0xC0）
```

**命令包装 80B**（`sub_1815282C0` 构造）：

```
+0x00 byte state | +0x04 int kind
kind=0 → 动作对象 @+0x08（另：+0x10 = obj->vfn0()、+0x18 = obj->vfn64()、+0x20 = obj->vfn80()）
kind=1 → 动作对象 @+0x28（另：+0x30 = obj->vfn64()、+0x38 = obj->vfn80()）
kind=2 → 动作对象 @+0x40
```

活体 dump 出的真实步（撤销栈，节选）+ vtable RVA 反查类名：

```
[ 2] name='New Entity'        命令=2 → [CSelection备份, kind2=CMapEntity]
[ 3] name='Delete Selection'  命令=3 → [CSelection备份, CVisibilityMgr备份, kind1=CMapEntity]
[ 4] name='Modify Selection'  命令=1 → [CSelection备份]
```

`0x1765548`=`CSelection` · `0x17654E0`=`CSelectionStateBackup` · `0x177EC900`=`CVisibilityMgr`
· `0x1759598`=`??_7CMapEntity@@6B@_0`（副虚表，即 `元素+0xC8` 的那个）

#### 15.10.3 记录 API（可直接调用，全部已静态校验）

| RVA | 函数 | 作用 |
|---|---|---|
| `0x1529290` | `sub_181529290(hist, name, 0, 0)` | 压入一个**具名步**（裸版） |
| `0x1529240` | `sub_181529240(hist, name, extra)` | 同上 + 通知（内带 `+145` 重入锁 / `+148` 忙判定） |
| `0x15290B0` | `sub_1815290B0(hist, node)` | 记录**「对象被新增」**（kind=2） |
| `0x1528EC0` | `sub_181528EC0(hist, node)` | 记录**「对象被移除」**（kind=1，另存 `node->vfn64()`=父 到 +0x30） |
| `0x1528D70` | `sub_181528D70(hist, obj)` | 记录通用命令（kind=0，靠 `obj->vfn56()` 作闸门） |
| `0x1529700` | `sub_181529700(hist, code)` | 通知监听者（`hist+1176` 计数 / `+1184` 数组，逐对象 `vfn0(code)`） |

⚠ **`node` 必须传 `元素 + 0xC8`** —— 那是 `CMapNode` 接口子对象（实测其 vtable =
`??_7CMapEntity@@6B@_0` / `??_7CMapWorld@@6B@_0`），**不是元素本身**。

这批能力也以**虚函数**形式挂在 `CMapDocHistory` 虚表（RVA `0x1763E00`）上 —— **这才是
"工具间交互的桥"**（`CMapEntity` / `CMapWorld` / `CMapMesh` 等 100+ 个类都实现了这些槽）：

```
槽 +0x08 (sub_18086DD50) → sub_181528EC0   记录「对象被移除」
槽 +0x10 (sub_18086E2B0) → 另一接口方法
内部 helper sub_18086DF10 / sub_18086E030 → sub_1815290B0   记录「对象被新增」
           sub_18086E1A0 → sub_181529240   压入具名步
```

#### 15.10.4 ⭐ 撤销/重做自洽 —— 不必自己实现

`sub_181529D20(wrap, pairHist)`（Pop 里逐条应用反操作）反编译：

```
kind=0 → obj->vfn8(保存值) + obj->vfn40(0) + …
kind=1 → obj->vfn72(保存的父节点) ; sub_1815290B0(pairHist, obj)   // 撤销「移除」= 挂回 + 往重做栈记「新增」
kind=2 → pairHist->vfn1(obj)     ; obj->vfn72(0)                    // 撤销「新增」= 往重做栈记「移除」+ 摘下
```

即 **kind1 / kind2 互为逆操作，且会自动往配对栈写反向记录**。我们只需「记录」。

#### 15.10.5 ⚠ 顺序陷阱（实测，最容易踩）

记录函数会调 `obj->vfn64()` 存进包装 `+0x30`，撤销 kind1 时用它 `vfn72(父)` 挂回去。
实测 `vfn64(元素+0xC8)` = **父节点（接口形式）**，且**摘除后立刻归 0**：

```
摘除前  vfn64 = 0x549584880c8   (= world + 0xC8)
摘除后  vfn64 = 0x0             ← 父指针已清空
```

→ **删除必须「先记录、后摘除」**。这也解释了 Hammer 自己那步 `'Delete Selection'` 的包装
`+0x30` 为何是有效的 `world+0xC8`。

正确顺序：

* **创建**：`PushStep → 建元素/挂世界 → RecAdded → Notify`
* **删除**：`PushStep → RecRemoved → 摘除 → Notify`
  （记录器是追加到**栈顶步**的，所以必须先压步；没有步它会自己建一个**无名**步。）

#### 15.10.6 前置条件（实测均已满足，无需额外准备）

| 条件 | 实测 |
|---|---|
| 全局闸门 `hammer+0x221A418` | **1** |
| `hist+144` enabled | **1** |
| `hist+140` busy | 0 |
| 步ID计数器 `hammer+0x221A41C` | 60 |

#### 15.10.7 仍未打通

* **属性修改**（`cs2_entity_set_attr`）走 DMX 属性级（栈 B）。Hammer 的 `'Modify Selection'`
  步里**只有 `CSelectionStateBackup` 一条命令**，说明属性改动「如何被绑进这一步」尚未查清 ——
  故本轮方案只覆盖**创建 / 删除**。
* 元素**不能真销毁**：撤销靠元素 id 复原（kind1 撤销 = `vfn72(父)` 把同一元素挂回 + 往配对栈记
  `RecAdded`），所以现在的「留成孤儿」语义**正是撤销的前提**。

#### 15.10.8 🐛 孤儿副作用（用户实测反馈，2026-09-27）

早先被 `vfn0x1D0` 摘除的 `mcp_place_test`（`0x5499e364400`，handle=10）现场：

```
元素 name='mcp_place_test'  classname='info_target'  targetname='mcp_place_test'
GetParent=0x0   node+0xC8 的 vfn64=0x0   世界树可达=False   cs2_entity_get_io 仍可正常读
```

现象：**Hammer 里「看得到、选不中、打不开 I/O」**。任何**枚举 DMX 元素**的列表（按名字的
target 下拉、Entity Report 之类）仍会列出它；但凡走**世界树**的路径（地图视图选中、I/O 面板、
`cs2_entity_list`）都到不了它 —— 选不中，自然也就没有 I/O 面板。

根因：**纯摘除（`vfn0x1D0`）不改 Hammer 的名字/选择索引**。根治方向 = 改走 15.10.3 的记录型删除
（Hammer 自己的删除路径会顺带把这些索引收拾干净）。





