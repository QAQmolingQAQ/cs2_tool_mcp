# CS2 Hammer 工具模式 — 逆向工程笔记

> 最后更新: 2026-09-21
> 目标: 让 AI 通过 MCP 操控 CS2 Hammer 编辑器（地图编辑、粒子、模型、滤镜、贴图）

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
