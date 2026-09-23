# CS2 Tool MCP — 进展记录

> 最后更新：2026-09-24
> 目的：让 AI 通过 MCP 操控 CS2 Hammer 工具模式（地图 / 实体 / 粒子 / 撤销 / 贴图）。
> 本文件记录**进度与决策**；底层逆向地址细节见 [REVERSE_NOTES.md](./REVERSE_NOTES.md)。

> ⚠️ **开发位置已变更（2026-09-24）**：改为**在虚拟机内直接用 Trae 开发**
> （编辑器、运行环境、目标进程同机，改完即可验证），不再走「实体机写码 → SSH 推 VM」。
> 目录布局、拉起 Hammer 全流程、编译与验证命令、关键陷阱见 **[VM_DEV.md](./VM_DEV.md)**。

---

## 1. 目标与范围

参考 `blender-mcp` 的设计，做一个 **cs2-tool MCP**：

- **交付范围**（已与用户确认）：Python MCP **+** 扩展 C++ 注入 DLL
- **工具命名**：保留 `cs2_` 前缀
- **架构**（三层）：

```
┌──────────────┐   命名管道     ┌───────────────┐  CreateInterface  ┌───────────┐
│ Python MCP   │◄────────────►│ cs2_tool.dll  │◄─────────────────►│ hammer.dll│
│  (FastMCP)   │ \\\\.\\pipe\\ │ (注入 hammer)  │                   │ pet.dll   │
└──────────────┘  CS2ToolMCP   └───────────────┘                   └───────────┘
```

---

## 2. 当前进度

### ✅ 已完成

| #   | 事项                                            | 说明                                                                                                                                                                                                                            |
| --- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 修复 IDA MCP 端口配置                           | `%APPDATA%\Trae CN\User\mcp.json` 中 `ida-pro-mcp-hammer` 由 `13331` 改为 `13400`（13331 无实例）；pet 仍为 `13332`。**需重载 Trae 才会出现 `mcp_ida-pro-mcp-hammer` 工具**，期间可直接走 HTTP。                                |
| 2   | 逆向 hammer.dll 关键对象                        | CMapDoc 全局文档表、CMapDoc 构造函数与偏移、CUndoManager::Undo/Redo、CDataModel vtable 与 `CUndoManager@+240`。详见 REVERSE_NOTES.md §2.7 / §2.8                                                                                |
| 3   | 扩展 C++ DLL                                    | 新增 10 个 IPC 方法（见 §4），MSVC Release 编译通过                                                                                                                                                                             |
| 4   | 重写 Python MCP                                 | 分层 `Cs2Pipe` 传输层 + 分组工具，19 个 tool 注册成功                                                                                                                                                                           |
| 5   | 创建 git 仓库 + 进展文档                        | 见 §6 / §7                                                                                                                                                                                                                      |
| 6   | **新 DLL 注入 + 端到端验证通过**                | Hammer 重启后注入 PID 54816；19 个 IPC 方法全部就位                                                                                                                                                                             |
| 7   | **定位并实测 CDataModel / CUndoManager**        | `g_CDataModel = hammer.dll+0x2344140`（全局单例），`CUndoManager = +240`；运行时 vtable 校验通过                                                                                                                                |
| 8   | **实现 `cs2_undo` / `cs2_redo`**                | 通过 `call_function` 直接调用，无需再改 DLL；空栈调用安全                                                                                                                                                                       |
| 9   | 新增诊断脚本                                    | `injector/probe_mapdoc.py`、`injector/probe_undo.py`                                                                                                                                                                            |
| 10  | **定位地图撤销/重做入口**                       | `RVA 0x14080D0`（Undo/Redo 共用，靠 `this` 区分），**必须主线程调用**。见 REVERSE_NOTES §2.9                                                                                                                                    |
| 11  | **DLL 新增主线程派发 + SEH**                    | `CallFunctionOnMainThread`（WH_GETMESSAGE 钩子）+ `__try/__except`，`call_function` 新增 `on_main_thread`/`main_thread_status`                                                                                                  |
| 12  | **DLL 新增内存原语 + 修 ListModules 缓存**      | 新增 `alloc_memory` / `free_memory` / `write_memory`；`ListModules` 改为每次重枚举（hammer.dll 是后加载的）                                                                                                                     |
| 13  | **逆向出引擎自带的按类名枚举**                  | `hammer.dll+0x745F10` = `EnumElements(node, CUtlVector*, className, flags, recurse)`；场景树 `+408` 父指针 / `+504` 子节点数 / `+512` 子句柄数组；Source 2 `CUtlVector` 布局已确认。见 REVERSE_NOTES §2.11                      |
| 14  | **实现 `cs2_entity_list` / `enum_elements`**    | 在目标进程摆一个空 `CUtlVector` 交给引擎填；VM 内实测**调用成功不崩溃**（`main_thread_status=0`）                                                                                                                               |
| 15  | 工具数 23 → **26**                              | 新增 `cs2_entity_list` / `cs2_entity_get_attr` / `cs2_entity_find_attr`                                                                                                                                                         |
| 16  | **`cs2_entity_set_attr` 实现并验证通过**        | 实体属性本质是 Datamodel(DMX) 的 `CDmAttribute` 链表（`CMapEntity+1328` = element 句柄）；写入链路 `GetAttribute` → `InternString` → `CDmAttribute::SetValue<CUtlSymbolLarge>`（RVA `0x4C7A10`）。见 REVERSE_NOTES §2.12        |
| 17  | **打通 Datamodel undo scope（属性修改可撤销）** | `BeginUndoScope`(`0x50B1C0`) / `EndUndoScope`(`0x50B0D0`) 配对 + 打开 undo 总开关（`CUndoManager+132` bit3，Hammer 平时是关的）。VM 实测：`targetname` 改后 DMX 栈 `0→1`，`cs2_undo` 回滚成功                                   |
| 18  | 工具数 26 → **27**                              | 新增 `cs2_entity_set_attr`                                                                                                                                                                                                      |
| 19  | **`cs2_map_info` 实现并验证通过**               | `CMapDoc + 0x6A0` = 地图全路径（`CUtlString`，+0 即 `char*`）。VM 实测返回 `.../content/csgo_addons/test/maps/untitled_1.vmap` + 文件名 + 撤销栈深度。**此前记的 `CMapDoc+2640` 是错的**                                        |
| 20  | 工具数 27 → **28**                              | 新增 `cs2_map_info`                                                                                                                                                                                                             |
| 21  | **`call_virtual` 支持 `on_main_thread`**        | DLL 侧 `CallVirtual` 新增 `on_main_thread` / `timeout_ms`（复用 `CallFunctionOnMainThread`），响应含 `main_thread_status`；顺手把 `map_list_docs` 的地图名偏移从 `+2640` 修正为 `+0x6A0`。⚠️ **尚未验证：VM 环境已变，见 §5.3** |

### 🚧 待确认 / 待重编译

- **`read_memory` / `read_qword` 地址解析修复待重编译**：这两个既有方法的 DLL 侧原用 `GetInt` 解析地址，
  不支持 `'hammer.dll+0x...'` 字符串表达式（新方法已用 `GetAddressParam`）。源码已改，但重建时 DLL 被
  Hammer 占用（`LNK1104`），**需关闭 Hammer 后重新构建**。不阻塞其他功能。
- **撤销/重做验证结果（2026-09-21，负面结论，已验证）**：
  Hammer 中有 7 步编辑历史时，`CMapDocHistory+0x08` count = **7**（与 UI 显示一致），
  而 `g_CDataModel+240` 的 undo/redo 仍为 **0/0**；调用 `cs2_undo` 后地图历史 **7 → 7 未变**。
  → **`cs2_undo`/`cs2_redo` 目前作用于 Datamodel(DMX) 撤销栈，控制不了地图编辑撤销**。
  已在代码 docstring 与 REVERSE_NOTES.md §2.8 标注更正。

- **✅ 地图撤销/重做已打通（2026-09-21，CE 硬件断点实测）**：
  在 VM 里用 CE 对 `CMapDocHistory+8`（历史计数）下硬件**写**断点，按 Ctrl+Z 捕获到
  `RVA 0x1408190: dec [rbx+08]`（RBX = 历史对象）；换到 **redo 计数**上下断点后按 Ctrl+Y，
  命中**同一条指令**且 `RBX = 重做历史` → **Undo/Redo 共用同一函数 `RVA 0x14080D0`**，
  靠传入的 `this` 区分（撤销历史 / 重做历史）。
  → 已实现 **`cs2_map_undo` / `cs2_map_redo`**（工具总数 21 → **23**）。
  计数器读数同步验证：`8→7 (redo 0→1)`、`7→8 (redo 1→0)`。
  历史对象用**扫描**定位（不硬编码 session 内偏移）。

- **✅ 地图撤销/重做已端到端验证可用（2026-09-22，VM 内）**：
  关键前提是**必须从 Hammer 主线程调用**（从管道线程调用会执行成功但永不返回、
  并把历史留在 busy 态）。DLL 已加 `CallFunctionOnMainThread`（WH_GETMESSAGE 钩子派发）
  - SEH 异常保护 + 零风险自检 `main_thread_selftest`。
    VM 实测：`map-undo` 5→4、`map-redo` 4→5，**全部立即返回无卡顿**。
    详见 REVERSE_NOTES.md §2.9。

- **✅ 实体工具已端到端验证通过（2026-09-22，VM 内，地图有实体）**：
  在 Hammer 里放好实体后实测（`python vm_pipe.py entities`）：

  ```
  实体数: 5（场景节点总数 6，CMapDoc=0x378dcb94010, CMapWorld=0x378d8c0f000）
  [  0] 0x00000378df29e000  info_player_start
  [  1] 0x0000037805c42800  info_player_counterterrorist
  [  2] 0x0000037805c44400  info_player_terrorist
  [  3] 0x0000037805c46000  info_player_terrorist
  [  4] 0x0000037805c47c00  env_combined_light_probe_volume
  ```

  - `cs2_entity_list` = 引擎全枚举（classname 传 NULL）+ 本地按 `vtable == base+0x161C548` 筛 CMapEntity
    - 逐个读 `classname` 属性。
  - `cs2_entity_get_attr` / `cs2_entity_find_attr` 也验证：`classname` → `'info_player_start'`、
    idx `0`；不存在的属性 → 空指针 / `-1`；`origin` 不存在（CS2 位置走 `Transform`）。
  - 🔴 **重要更正**：引擎的 `className` 参数是**驻留符号指针**，不是 `const char*`。
    实测传 `CMapEntity`/`info_player_start`/`CMapWorld`（flags 0 或 8）**全部返回 0**。
    详见 REVERSE_NOTES §2.11。

### ⬜ 待办（按优先级）

| 优先级  | 事项                                                                                         | 依赖                                                                                                                                              |
| ------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| ~~P0~~  | ~~定位真正的地图 Undo/Redo 入口~~                                                            | ✅ 已完成（见上，RVA `0x14080D0`）                                                                                                                |
| ~~P0~~  | ~~在 VM 里端到端验证 `cs2_map_undo`/`cs2_map_redo`~~                                         | ✅ **已完成**：`map-undo` 5→4 / `map-redo` 4→5，全部立即返回无卡顿（见上）                                                                        |
| ~~P1~~  | ~~`entity_list` / `entity_get_attr` / `entity_find_attr`~~                                   | ✅ **已完成并验证**：`cs2_entity_list` 正确列出 5 个实体 + 类名；属性读 / 查索引均通过                                                            |
| ~~P1~~  | ~~`entity_set_attr`（改属性 + 自动 Undo）~~                                                  | ✅ **已完成并验证**（§2 第 16/17 项、REVERSE_NOTES §2.12）。⚠️ 撤销走 **Datamodel 栈**（用 `cs2_undo`），Hammer 的 Ctrl+Z 是另一套（地图历史）    |
| ~~P1~~  | ~~`map_info`（地图名/路径）~~                                                                | ✅ **已完成并验证**：正确偏移是 `CMapDoc + 0x6A0`（旧记录的 `+2640` 有误）                                                                        |
| P2      | 粒子工具：`particle_set_definition`（`CParticleHelper::SetDefinitionByName` RVA `0x6E7380`） | 已发现 `CMapDoc+0xAF8` = CParticleSystemQueryHammerMapDoc、`+0xB68` = CParticlesLibHost_MapDocLib                                                 |
| P2      | map 保存 / FrameUpdate                                                                       | —                                                                                                                                                 |
| ~~P2~~  | ~~给 `call_virtual` 加 `on_main_thread`~~                                                    | ✅ **已完成并验证**：`vc <obj> 0` 调 `vtable[0]`(metaObject) 返回 `0x7ffe93ac99d0`，与 `cls <obj>` 独立算出的 meta 完全一致（类名 `QToolButton`） |
| ✅ 完成 | **新版「进 Hammer」入口**：在 Asset Browser 里点 Hammer 图标（见 §5.3）                      | 已用 **Qt 注入直调** 自动化（`vm_pipe.py qt-buttons` / `qt-click`）；点击后 hammer.dll 加载成功。**RVA 无需重新逆向**                             |
| P2      | `read_memory` 修复后重编译 + 重新注入                                                        | ✅ 已重编译并入库，实体机下次注入即生效                                                                                                           |

---

## 3. 关键约定与决策

- **地址表达式**：DLL 地址参数支持绝对地址 `0x...` 或 `hammer.dll+0x12E1B50`（模块名可省略 `.dll`）。
  ⚠️ `read_memory` / `read_qword` 的表达式支持需**待重编译的修复**生效（见 §2「待重编译」）；当前请传整数地址。
- **通用调用原语**：`call_function` / `call_virtual` 是「可编程控制」的核心，等价于 Blender MCP 的 `execute_blender_code`。参数顺序 `args[0]→RCX, [1]→RDX, [2]→R8, [3]→R9, [4..5]→栈`；调用成员函数时 `args[0]` 传 `this`。
- **`vtable_offset` 单位是字节**（与 IDA 的 `vtable[1040]` 记法一致）。
- **构建产物不入库**：`build_msvc/`、`*.dll`、`*.obj` 等已在 `.gitignore` 排除。
- **`vrf/` 不入库**：它是自带 `.git` 的上游仓库。

---

## 4. DLL IPC 方法清单（22 个）

**原有 9 个**：`ping`、`get_status`、`list_interfaces`、`get_interface`、`read_memory`、`read_qword`、`get_hammer_app`、`initialize`、`list_tools`

**新增 13 个**：

| 方法             | 参数                                                | 说明                                                                                                             |
| ---------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `list_modules`   | —                                                   | 枚举模块 name/base/image_base/size（**每次重枚举**）                                                             |
| `get_module`     | `name`                                              | 单模块基址与大小                                                                                                 |
| `read_value`     | `address`, `type`                                   | 按类型读（u8..u64/i8..i64/f32/f64/ptr）                                                                          |
| `write_value`    | `address`, `value`, `type`                          | 按类型写                                                                                                         |
| `write_memory`   | `address`, `hex`                                    | 写任意字节（hex 串，允许空格/`0x` 前缀）                                                                         |
| `alloc_memory`   | `size`                                              | 在目标进程 `VirtualAlloc` 一块读写内存，返回地址                                                                 |
| `free_memory`    | `address`                                           | `VirtualFree` 释放 `alloc_memory` 的块                                                                           |
| `read_string`    | `address`, `max_len`                                | 读 C 字符串（跨页安全）                                                                                          |
| `read_ptr_chain` | `base`, `offsets[]`                                 | 多级指针链解析                                                                                                   |
| `find_pattern`   | `pattern`, `module`, `limit`                        | AOB 特征扫描（`??` 通配）                                                                                        |
| `call_function`  | `address`, `args[]`, `on_main_thread`, `timeout_ms` | 调用任意函数（x64 fastcall，≤6 参数）；`"str:文本"` 参数会在目标进程分配一份 C 字符串；返回 `main_thread_status` |
| `call_virtual`   | `this`, `vtable_offset`, `args[]`                   | 调用虚函数                                                                                                       |
| `map_list_docs`  | —                                                   | 枚举 CMapDoc 文档（地址 + 地图名）                                                                               |

另有 `main_thread_selftest`（零风险自检派发链路）。
集合为 **22 个**（含 `list_tools` 自身）。

对应 Python 工具共 **28 个**：`cs2_*` 同名（`cs2_list_modules` … `cs2_map_list_docs`），
再加 `cs2_entity_list` / `cs2_entity_get_attr` / `cs2_entity_set_attr` / `cs2_entity_find_attr`
/ `cs2_map_info` / `cs2_map_undo` / `cs2_map_redo`。

---

## 5. 环境信息（重要，避免遗忘）

| 项                 | 值                                                                                                                            |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| CS2 tools 目录     | `D:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\tools`                                       |
| IDA 安装           | `C:\Users\a5767\Downloads\IDA Professional 9.1`                                                                               |
| ida-pro-mcp 源码   | `C:\Users\a5767\Downloads\IDA Professional 9.1\mcp\ida-pro-mcp-main`                                                          |
| **IDA MCP 端口**   | **动态分配**，以 `instances/*.json` 为准。当前 hammer.dll → **13331**（PID 34476）                                            |
| **hammer.dll.i64** | `D:\SteamLibrary\...\game\bin\win64\tools\hammer.dll.i64`（**87.7 MB**，含完整分析）                                          |
| IDA 实例注册文件   | `%APPDATA%\Hex-Rays\IDA Pro\mcp\instances\instance_<port>.json`                                                               |
| Trae MCP 配置      | `%APPDATA%\Trae CN\User\mcp.json`                                                                                             |
| **构建命令**       | `cmake --build "<repo>\cs2_tool_mcp\injected_dll\build_msvc" --config Release`                                                |
| CMake 路径         | `C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe` |
| 注入脚本           | `cs2_tool_mcp/injector/inject_dll.py`（自动找 hammer.exe/cs2.exe）                                                            |
| 管道名             | `\\.\pipe\CS2ToolMCP`（可用环境变量 `CS2_TOOL_PIPE` 覆盖 MCP 侧）                                                             |
| IDA 查询助手       | `cs2_tool_mcp/injector/ida_mcp_call.py <port> <tool> '<json>'`                                                                |

#### 5.0.1 重新拉起 IDA（分析结果显示不出来时）

IDA 实例关掉后 `instances/*.json` 会残留（PID 已死），直接查端口会「积极拒绝」。重新拉起：

```powershell
Start-Process -FilePath "C:\Users\a5767\Downloads\IDA Professional 9.1\ida.exe" `
  -ArgumentList '"D:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\tools\hammer.dll.i64"'
# 约 40s 后插件 autostart 会自行起 MCP 并注册实例，端口看 instances/*.json
Get-ChildItem "$env:APPDATA\Hex-Rays\IDA Pro\mcp\instances" -Filter *.json |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { Get-Content $_.FullName -Raw }
```

> 插件是**自包含**的（`zeromcp` 内置，无需 pip 依赖），源在
> `%APPDATA%\Hex-Rays\IDA Pro\plugins\`：`ida_mcp.py` + `ida_mcp\`。

### 5.1 Cheat Engine（VM 远程调试）

用于定位「地图 Undo 入口」——因为调试点必须与目标进程同机，而**实体机上没装 CE**，
所以改在 **VM 里跑一份 CS2 + CE**，只用来定位 RVA（RVA 与实体机通用，已验证两边的
hammer.dll 为同一构建）。

| 项             | 值                                                                                      |
| -------------- | --------------------------------------------------------------------------------------- |
| VM IP          | `192.168.3.137`（实体机 `192.168.3.4`）                                                 |
| VM 内目标      | `cs2.exe`（Hammer）                                                                     |
| CE bridge 端口 | TCP `17171`（由 `ce_mcp_bridge.lua` 在 CE 内启动）                                      |
| MCP 服务脚本   | `D:\ai\ce_mcp\ce-mcp\cheatengine-mcp-tcp-bridge-main\...\MCP_Server\mcp_cheatengine.py` |
| 该脚本硬编码   | `CE_HOST = "192.168.3.137"`（本次已从旧的 `192.168.31.96` 改过来，第 144 行）           |
| **直连助手**   | `cs2_tool_mcp/injector/ce_call.py <method> '<json>'`（绕过 Trae 重启，直接调 CE）       |
| 协议           | 请求/响应均为 `<I` 长度前缀 + UTF-8 JSON（JSON-RPC 2.0）                                |

> `ce-mcp` 在 Trae 里也已配置，但改完 `CE_HOST` 需**重启 Trae** 才生效；开发期直接用
> `ce_call.py` 更快。
> ⚠️ CE → Settings → Extra **必须取消勾选 "Query memory region routines"**，否则可能蓝屏。

### 5.2 VM 完整链路（SSH，主调试环境）

VM 里也装了 CS2，因此把**整条链路**（DLL + 注入器 + 管道客户端）搬进 VM，
端到端验证与后续迭代都在 VM 里做（VM 可随意重启，不影响实体机）。

| 项                 | 值                                                                                                                                                                                                        |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| VM SSH             | `ssss@192.168.3.137` / 密码 `ssss`（Win10 1903，主机名 `DESKTOP-JHRDFC0`）                                                                                                                                |
| VM 内 Python       | `3.14.7`（另有 3.11）                                                                                                                                                                                     |
| VM 内 cs2.exe      | `C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe`                                                                                                    |
| VM 部署目录        | `C:\cs2_tool_mcp\`（镜像仓库结构：`injected_dll\build_msvc\Release\cs2_tool.dll`、`injector\`、`mcp_server\`）                                                                                            |
| **SSH 助手**       | `injector/vm_ssh.py`（paramiko；`--ps64` 用 `-EncodedCommand` 免引号转义；支持 `--upload/--download`）                                                                                                    |
| **管道客户端**     | `injector/vm_pipe.py`（stub 掉 `mcp` 包复用 `cs2_mcp_server.py`；子命令：`ping`/`map-info`/`map-undo`/`map-redo`/`call-main`/`main_thread_selftest`/`module <名>`/`enumerate [类名] [flags]`/`entities`） |
| **UI 自动化**      | `injector/vm_ui.py` + `vm_screen.ps1` + `vm_input.ps1`（走 `schtasks /IT` 投到 Session 1；支持 `setup/shot/click/dblclick/drag/wheel/key/type/activate`）                                                 |
| **调试图省事副本** | `C:\Users\ssss\cs2mcp\`（只放 `injector\` + `mcp_server\`，跑 `vm_pipe.py`/`probe_entities.py` 用；DLL 仍从 `C:\cs2_tool_mcp\...` 加载）                                                                  |

复制链路的命令（在仓库根）：

```powershell
python injector\vm_ssh.py "mkdir C:\cs2_tool_mcp\injected_dll\build_msvc\Release" "mkdir C:\cs2_tool_mcp\injector" "mkdir C:\cs2_tool_mcp\mcp_server"
python injector\vm_ssh.py --upload "injected_dll\build_msvc\Release\cs2_tool.dll" "C:/cs2_tool_mcp/injected_dll/build_msvc/Release/cs2_tool.dll"
python injector\vm_ssh.py --upload "mcp_server\cs2_mcp_server.py" "C:/cs2_tool_mcp/mcp_server/cs2_mcp_server.py"
python injector\vm_ssh.py "cd /d C:\cs2_tool_mcp\injector && python inject_dll.py <pid>"
python injector\vm_ssh.py "cd /d C:\cs2_tool_mcp\injector && python vm_pipe.py map-info"
```

#### VM 里手动拉起 Hammer（⚠️ 必须投递到交互会话）

启动命令（**不能带 `-steam`**，带了会因等待 Steam 授权瞬间退出）：

```
C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe -insecure -worldwide -condebug -high -tools -addon test
```

**但直接经 SSH 启动会失败**：SSH 登录落在 **Session 0（服务会话，无桌面）**，进程拿不到显示适配器，
cs2 会在 `csgo\console.log` 里报下面这段然后**自己退出**（不是崩溃，Application 日志里没有事件）：

```
[RenderSystem] No usable DX11 adapters found out of 2 available...
No display adapters found. Falling back to software rasterizer.
Failed to initialize video!  →  Failed to create DirectX 11 render device!
```

**正解：用计划任务 `/IT` 把进程投递到交互会话（Session 1）**：

```powershell
# injector/launch_hammer.cmd 里 cd 到 win64 再 start cs2.exe（工作目录很重要）
schtasks /create /tn HammerLaunch /tr "C:\cs2_tool_mcp\launch_hammer.cmd" /sc once /st 23:59 /IT /F
schtasks /run /tn HammerLaunch
# 稍后确认 SessionId=1
Get-Process cs2 | Select-Object Id,SessionId,Responding
```

排查会话用 `query session`：`services`=0（SSH 在这）、`console`=1（用户 `ssss`，有 explorer 的会话）。
**判断依据：`SessionId` 必须是 1。**

> 另注：即便 Hammer 窗口起来了，**没打开地图时 hammer.dll 尚未加载**，
> 此时任何 `hammer.dll+...` 地址都会报 `module not found: hammer`。

#### 5.2.1 VM 的 IDA（已装好 MCP）

| 项       | 值                                                                                                                                                                                                          |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| IDA 安装 | `C:\Users\ssss\Desktop\IDA Professional 9.1`（内置 `python311`）                                                                                                                                            |
| 插件位置 | `C:\Users\ssss\AppData\Roaming\Hex-Rays\IDA Pro\plugins\`（`ida_mcp.py` + `ida_mcp\`）                                                                                                                      |
| 安装方式 | 从实体机 `%APPDATA%\Hex-Rays\IDA Pro\plugins` 打包（去 `__pycache__`/`tests`）后解压过去                                                                                                                    |
| **备注** | VM 的 IDA **没有** `hammer.dll.i64`（87.7 MB 分析库在实体机）。若要用 VM 做 RE，需把 `hammer.dll` + `hammer.dll.i64` 一起拷过去（IDB 与输入文件路径绑定，跨机打开会提示"数据库由其它文件创建"，选继续即可） |

> ⚠️ 构建目录 `build_msvc` 的 CMake 缓存曾因仓库路径改动（`cs2` → `cs2 - edit`）失效；
> 已重新 configure。若再次报 `CMakeCache.txt directory ... is different`，删除
> `build_msvc/CMakeCache.txt` 与 `build_msvc/CMakeFiles/` 后重新 `cmake -S injected_dll -B injected_dll/build_msvc -G "Visual Studio 17 2022" -A x64`。

### 5.3 ⚠️ 环境变化：新版 `-tools` 不再直接进 Hammer（2026-09-22 夜查明）

**结论先说：`hammer.dll` 本身没变，本项目全部 RVA 依然有效 —— 变的是「怎么启动 Hammer」。**

CS2 更新后，`cs2.exe -tools` 的行为变了：

| 项                              | 旧版        | 新版                                  |
| ------------------------------- | ----------- | ------------------------------------- |
| `-tools` 启动后进入             | 直接 Hammer | **Mod Tools 启动器（Asset Browser）** |
| 是否自动加载 `tools\hammer.dll` | 是          | **否**（需再走一步才进 Hammer）       |

**已核实的事实**：

- 两机的 `tools\hammer.dll` **MD5 完全相同** = `06E2929BEADE01B5DDA050EB8F01612D`（38,791,832 字节）。
- 该文件仍含 `CHammerApp` / `ToolSystem2_001` / `CMapDoc` / `CMapEntity` → **仍是 Hammer 本体**。
- 新版 `-tools` 加载的是 `bin\win64\toolframework2.dll` + `csgo\bin\win64\modtools.dll`（Mod Tools 框架，内含 ModelDoc 等工具）。
- 两个框架 DLL 里含 `ToolsStartup`、`HammerMapLoader001` 等符号；`hammer` 相关字符串只有 `HammerMapLoader001` / `HammerEntityPicker()`。

**推断**：Mod Tools 是「工具容器」，Hammer 只是其中一个工具；
**打开一张 `.vmap` 才会拉起 `tools\hammer.dll`** —— 第一次重启时它确实进了 Hammer，正是因为它恢复了上次的 `untitled_1.vmap` 会话。

排查当前加载了哪个工具模块：

```powershell
Get-Process cs2 | Select-Object -ExpandProperty Modules |
  Where-Object { $_.ModuleName -match "hammer|modtools|toolframework" } | Select-Object ModuleName,FileName
```

**✅ 已解决（2026-09-22 夜）**：新版进入 Hammer 的标准入口确认 = **在 Asset Browser 里点 Hammer 图标**
（用户确认：「启动 asset browser，然后点击 hammer 的图标，让 cs2 加载 hammer.dll」）。

已用 **Qt 注入直调** 实现自动化，不再依赖鼠标坐标（VM 上点鼠标还会触发 `Stall Detected`）：

```powershell
python vm_pipe.py qt-buttons               # 找按钮（toolTip='Hammer (Map Editor)'）
python vm_pipe.py qt-click <widget>        # 直接调 QAbstractButton::click()
python vm_pipe.py qt-menu                  # 列菜单栏（QAction 不是 widget，要经 QWidget::actions()）
python vm_pipe.py qt-trigger <action>      # 触发菜单项，如 &New
```

**实测全自动链路（无人工操作）**：

1. `cs2.exe -tools` → Asset Browser
2. 注入 `cs2_tool.dll`
3. `qt-click` 点 Hammer 图标 → `hammer.dll` 加载（模块数 0 → 1），Hammer 界面出现
4. `qt-trigger` 触发 `&New` → 立刻建好 `untitled_1.vmap`（`map-info` 显示路径/CMapDoc/CMapWorld）
5. `entities` → `info_player_start` ×1；`attr`/`setattr`/`dm-undo` 全部正常工作

> 只要 Hammer 起来了，原有的 `hammer.dll+0x...` 全部地址与已实现工具都照常可用。
> 注：`&Open...` 会弹模态文件对话框并阻塞主线程，优先用 `&New` / `&Recent Files`。

---

## 6. 变更文件清单

| 文件                             | 变更                                                                                                                                                                                                                     |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `injected_dll/hammer_bridge.h`   | 新增 `ModuleDesc`、`ValueType`、`ParseValueType` 以及模块/内存/扫描/调用/地图文档接口声明；新增 `CallFunctionOnMainThread` / `GetMainThreadId` / `SetBridgeModuleHandle`                                                 |
| `injected_dll/hammer_bridge.cpp` | 实现上述接口；`ReadMem/WriteMem` 改用 `VirtualQuery` 安全检查（原 `IsBadReadPtr`）；抽出 `InvokeStub`，新增 WH_GETMESSAGE 主线程派发                                                                                     |
| `injected_dll/ipc_pipe.cpp`      | 新增 10 个方法分发；`call_function` 新增 `on_main_thread` / `timeout_ms`；`read_memory` 单次上限 1024 字节                                                                                                               |
| `injected_dll/dllmain.cpp`       | 保存模块句柄供主线程钩子使用                                                                                                                                                                                             |
| `injected_dll/CMakeLists.txt`    | 加 `/utf-8`（源码含中文注释，MSVC 默认按 936 解码会编译失败）                                                                                                                                                            |
| `mcp_server/cs2_mcp_server.py`   | 分层结构，**28** 个工具；实体属性读写（`cs2_entity_get_attr`/`set_attr`/`find_attr`）+ `cs2_map_info` + Datamodel undo scope 包装（`_ensure_undo_enabled` / `_undo_scope_begin` / `_undo_scope_end`）                    |
| `injector/ida_mcp_call.py`       | 新增（IDA MCP HTTP 查询助手）                                                                                                                                                                                            |
| `injector/probe_mapdoc.py`       | 新增（对象成员指针/vtable 探测，支持 `--base` / `--vt`）                                                                                                                                                                 |
| `injector/probe_undo.py`         | 新增（CUndoManager 探测 + 撤销/重做验证）                                                                                                                                                                                |
| `injector/probe_struct.py`       | 新增（按「计数 + 相邻指针」特征在未知结构里定位数组/栈）                                                                                                                                                                 |
| `injector/ce_call.py`            | 新增（直连 Cheat Engine MCP Bridge 的 TCP 客户端，免重启 Trae 即可控制 CE）                                                                                                                                              |
| `injector/vm_ssh.py`             | 新增（VM SSH 助手：paramiko + `--ps64` 免转义 + `--upload/--download`）                                                                                                                                                  |
| `injector/vm_pipe.py`            | 新增（VM 内管道客户端，stub 掉 `mcp` 复用生产代码）；子命令：`map-info`/`map-undo`/`map-redo`/`dm-info`/`dm-undo`/`dm-redo`/`dm-flag`/`scan-str`/`module`/`enumerate`/`entities`/`attr`/`findattr`/`setattr`/`call-main` |
| `injector/verify_undo_redo.py`   | 新增（撤销/重做端到端验证，走 MCP 真实工具实现）                                                                                                                                                                         |
| `REVERSE_NOTES.md`               | 新增 §2.7（CMapDoc 实例表/构造函数）、§2.8（Undo/Redo 调用链 + g_CDataModel 实测结论）、§2.9（**地图撤销/重做 CE 实测**）                                                                                                |
| `.gitignore` / `PROGRESS.md`     | 新增                                                                                                                                                                                                                     |

---

## 7. 下一步操作（恢复上下文时从这里开始）

**当前状态**（2026-09-22 末）：

- ✅ DLL 已加**主线程执行**能力（`on_main_thread`）+ SEH 保护 + 自检。
- ✅ DLL 已加 **`alloc_memory` / `free_memory` / `write_memory`**，并修掉 `ListModules` 永久缓存 bug。
- ✅ VM 里 **Hammer 已重启并注入新 DLL**（PID 10944），`hammer.dll` base = `0x7ffe7f950000`。
- ✅ **实体工具全部验证通过**：`cs2_entity_list` 列出 5 个实体（`info_player_start` 等），
  `cs2_entity_get_attr` / `cs2_entity_find_attr` 也通过。地图里现在有实体（可继续测）。
- ✅ **`cs2_entity_set_attr` 打通并验证**：改属性生效 + 记入 Datamodel 撤销栈，
  `cs2_undo` 能回滚（`targetname` `ai_scope_01 → ai_auto_01 → ai_scope_01`）。
  详见 REVERSE_NOTES §2.12。
- ⬜ 下一步：`map_info`、粒子工具、`call_virtual` 加主线程。

1. **测实体属性读写**（当前地图已有实体，`info_player_start` = `0x378df29e000`）：

   ```powershell
   python injector\vm_ssh.py --ps64 'cd C:\Users\ssss\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py entities'
   python injector\vm_ssh.py --ps64 'cd C:\Users\ssss\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py attr <实体地址> targetname'
   python injector\vm_ssh.py --ps64 'cd C:\Users\ssss\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py setattr <实体地址> targetname ai_test'
   python injector\vm_ssh.py --ps64 'cd C:\Users\ssss\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py dm-info'   # 看 DMX 撤销栈
   python injector\vm_ssh.py --ps64 'cd C:\Users\ssss\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py dm-undo'   # 撤销属性修改
   ```

   > ⚠️ `enumerate <类名>` 恒为 0：类名过滤参数是**驻留符号指针**，不是 C 字符串 → 只能用 `enumerate` 全枚举后本地过滤。
   > ⚠️ `dm-flag off` 可把 Datamodel undo 总开关关回去（调试用；平时由 `cs2_entity_set_attr` 自动打开）。

2. **VM 常用链路**（重新注入 / 看模块）：
   ```powershell
   python injector\vm_ssh.py --ps64 'Get-Process cs2 | Select-Object Id,Responding'
   python injector\vm_ssh.py --ps64 'cd C:\cs2_tool_mcp\injector; python inject_dll.py <pid>'
   python injector\vm_ssh.py --ps64 'cd C:\Users\ssss\cs2mcp\injector; python vm_pipe.py module hammer.dll'
   ```
   > 部署新 DLL：先 `Stop-Process cs2`，把新 dll 覆盖到
   > `C:\cs2_tool_mcp\injected_dll\build_msvc\Release\cs2_tool.dll`（运行中会被占用），
   > 再用 `schtasks /run /tn Cs2Hammer` 拉起 Hammer（**必须走 Session 1**）。
3. **编译 DLL**：
   ```powershell
   & "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" --build . --config Release
   # cwd = cs2_tool_mcp\injected_dll\build_msvc
   ```
4. **下一步功能**：`map_info`（地图名/路径）、粒子工具、`map_save`。
5. **给 `call_virtual` 也加 `on_main_thread`**（P2）。

### 关键坑速查

| 症状                               | 原因 / 对策                                                                                                                           |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 命令返回但 Hammer 无反应、历史卡住 | 忘了走主线程 → `on_main_thread=True`                                                                                                  |
| **调用后 Hammer 卡死/退出**        | 目标函数参数给错（如传 `this=0`）→ 访问违例。钩子已加 `__try/__except`，现在只会返回 `main_thread_status=4`，不再带走宿主             |
| `main_thread_status=1`             | 目标函数 15s 内没返回，可能自身会阻塞                                                                                                 |
| 想安全验证主线程链路               | `python vm_pipe.py main_thread_selftest`（只调 DLL 内部无害函数，碰不到 Hammer）                                                      |
| `invalid size`                     | DLL 的 `read_memory` 单次上限 1024 字节，需分块                                                                                       |
| MSVC 报 `C2187/C3484`              | 源文件 UTF-8 + 中文注释，需 `/utf-8`（已在 CMakeLists 加）                                                                            |
| 注入 `OpenProcess err=87`          | PID 已失效（Hammer 启动会换 PID），重新取 PID                                                                                         |
| VM 里直接跑 cs2.exe 闪退           | `-steam` 校验，必须从 Steam 启动                                                                                                      |
| `get_module hammer.dll` 说找不到   | hammer.dll 是**后加载**的；`ListModules` 已改为每次重枚举，仍找不到就等工具界面起来再试                                               |
| CE `aob_scan` 命中地址读不出来     | CE 的扫描结果不可全信（会返回 `0x29Exxxxxxx` 这种不可读地址）→ 命中必须回读校验                                                       |
| 远程 shell 里 JSON 参数引号打架    | 用 `vm_pipe.py module <名字>` / `enumerate [类名] [flags]` 这类**免 JSON** 子命令                                                     |
| 截屏全是控制台窗口                 | schtasks 的 powershell 加了 `-WindowStyle Hidden`（见 `vm_ui.py`）                                                                    |
| 弹出的菜单截不到                   | 截屏走 schtasks 会抢焦点 → 菜单又关了；尽量用坐标点击或免 UI 的方式                                                                   |
| 算 UI 坐标老是不对                 | Session 1 实际是 **1718x1038**（不是 SSH 侧 `Screen::AllScreens` 报的 1024x768）                                                      |
| `enumerate <类名>` 恒为 0          | 引擎的类名参数是**驻留符号指针**，不是 C 字符串 → 传空（NULL）全枚举，本地再按 vtable / 属性过滤                                      |
| 实体枚举要按类筛                   | 实体统一是 `??_7CMapEntity@@6B@`（RVA `0x161C548`）；用 `cs2_entity_get_attr(ent,"classname")` 取游戏内类名（如 `info_player_start`） |
| 改了属性但 Hammer 的 Ctrl+Z 撤不掉 | 属性修改走 **Datamodel 撤销栈**（`cs2_undo`），Ctrl+Z 走地图历史（`CMapDocHistory`），两套独立。见 REVERSE_NOTES §2.12                |
| `setattr` 后 DMX 栈没变            | undo 总开关（`CUndoManager+132` bit3）关着时 SetValue 不记录；`cs2_entity_set_attr` 会自动打开它                                      |
| `dm-undo`/`cs2_undo` 没反应        | 同上：总开关关着时 `CUndoManager::Undo` 直接返回                                                                                      |
