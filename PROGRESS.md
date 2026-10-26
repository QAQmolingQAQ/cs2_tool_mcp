# CS2 Tool MCP — 进展记录

> 最后更新：2026-09-26
> 目的：让 AI 通过 MCP 操控 CS2 Hammer 工具模式（地图 / 实体 / 粒子 / 撤销 / 贴图）。
> 本文件记录**进度与决策**；底层逆向地址细节见 [REVERSE_NOTES.md](./REVERSE_NOTES.md)。
>
> ⚠️ §2～§7 是**旧版本 hammer.dll + 旧环境（实体机/SSH 推 VM）**的记录，部分 RVA 已失效。
> **最新状态看 §8**；RVA 一律以 REVERSE_NOTES §11 为准。

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
| IDA 安装           | `%USERPROFILE%\Downloads\IDA Professional 9.1`                                                                               |
| ida-pro-mcp 源码   | `%USERPROFILE%\Downloads\IDA Professional 9.1\mcp\ida-pro-mcp-main`                                                          |
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
Start-Process -FilePath "%USERPROFILE%\Downloads\IDA Professional 9.1\ida.exe" `
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
| VM IP          | `<VM 内网 IP>`（实体机 `<内网 IP>`）                                                 |
| VM 内目标      | `cs2.exe`（Hammer）                                                                     |
| CE bridge 端口 | TCP `17171`（由 `ce_mcp_bridge.lua` 在 CE 内启动）                                      |
| MCP 服务脚本   | `D:\ai\ce_mcp\ce-mcp\cheatengine-mcp-tcp-bridge-main\...\MCP_Server\mcp_cheatengine.py` |
| 该脚本环境变量 | `CE_HOST` 环境变量（CE 所在机器 IP，必填；仓库内不留默认地址）                          |
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
| VM SSH             | 用户名 / 密码走环境变量 `VM_USER` / `VM_PASS`（Win10 1903）                                                                                                                                |
| VM 内 Python       | `3.14.7`（另有 3.11）                                                                                                                                                                                     |
| VM 内 cs2.exe      | `C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe`                                                                                                    |
| VM 部署目录        | `C:\cs2_tool_mcp\`（镜像仓库结构：`injected_dll\build_msvc\Release\cs2_tool.dll`、`injector\`、`mcp_server\`）                                                                                            |
| **SSH 助手**       | `injector/vm_ssh.py`（paramiko；`--ps64` 用 `-EncodedCommand` 免引号转义；支持 `--upload/--download`）                                                                                                    |
| **管道客户端**     | `injector/vm_pipe.py`（stub 掉 `mcp` 包复用 `cs2_mcp_server.py`；子命令：`ping`/`map-info`/`map-undo`/`map-redo`/`call-main`/`main_thread_selftest`/`module <名>`/`enumerate [类名] [flags]`/`entities`） |
| **UI 自动化**      | `injector/vm_ui.py` + `vm_screen.ps1` + `vm_input.ps1`（走 `schtasks /IT` 投到 Session 1；支持 `setup/shot/click/dblclick/drag/wheel/key/type/activate`）                                                 |
| **调试图省事副本** | `%USERPROFILE%\cs2mcp\`（只放 `injector\` + `mcp_server\`，跑 `vm_pipe.py`/`probe_entities.py` 用；DLL 仍从 `C:\cs2_tool_mcp\...` 加载）                                                                  |

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
| IDA 安装 | `%USERPROFILE%\Desktop\IDA Professional 9.1`（内置 `python311`）                                                                                                                                            |
| 插件位置 | `%USERPROFILE%\AppData\Roaming\Hex-Rays\IDA Pro\plugins\`（`ida_mcp.py` + `ida_mcp\`）                                                                                                                      |
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
| `mcp_server/cs2_mcp_server.py`   | 分层结构，**41** 个工具（含 `cs2_mesh_*` 几何/UV/材质读取、`cs2_area_query` 范围查询、`cs2_entity_*_io`）；实体属性读写（`cs2_entity_get_attr`/`set_attr`/`find_attr`）+ `cs2_map_info` + Datamodel undo scope 包装（`_ensure_undo_enabled` / `_undo_scope_begin` / `_undo_scope_end`）                    |
| `injector/mcp_smoke.py`          | 新增（**真·MCP stdio 冒烟测试**：起服务进程 → `initialize`/`tools/list`/`tools/call`，改完服务器代码用它验发布路径）                                                                                                      |
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
   python injector\vm_ssh.py --ps64 'cd %USERPROFILE%\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py entities'
   python injector\vm_ssh.py --ps64 'cd %USERPROFILE%\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py attr <实体地址> targetname'
   python injector\vm_ssh.py --ps64 'cd %USERPROFILE%\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py setattr <实体地址> targetname ai_test'
   python injector\vm_ssh.py --ps64 'cd %USERPROFILE%\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py dm-info'   # 看 DMX 撤销栈
   python injector\vm_ssh.py --ps64 'cd %USERPROFILE%\cs2mcp\injector; $env:CS2_HAMMER_BASE="0x7ffe7f950000"; python vm_pipe.py dm-undo'   # 撤销属性修改
   ```

   > ⚠️ `enumerate <类名>` 恒为 0：类名过滤参数是**驻留符号指针**，不是 C 字符串 → 只能用 `enumerate` 全枚举后本地过滤。
   > ⚠️ `dm-flag off` 可把 Datamodel undo 总开关关回去（调试用；平时由 `cs2_entity_set_attr` 自动打开）。

2. **VM 常用链路**（重新注入 / 看模块）：
   ```powershell
   python injector\vm_ssh.py --ps64 'Get-Process cs2 | Select-Object Id,Responding'
   python injector\vm_ssh.py --ps64 'cd C:\cs2_tool_mcp\injector; python inject_dll.py <pid>'
   python injector\vm_ssh.py --ps64 'cd %USERPROFILE%\cs2mcp\injector; python vm_pipe.py module hammer.dll'
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

---

## 9. 2026-10-01 新版 hammer.dll：**离线差分**批量重定位（最新）

> Steam 于 2026-10-01 16:49 更新 `hammer.dll`（新 MD5 `F417605FAA3A992C89717F7CA64C938E`，
> 39,598,744 字节），旧 RVA 表整片失效。
>
> 这次**没有重开 IDA**：`ida_db\hammer_new.dll` 里留着上一版副本，用离线差分
> （`injector/_rva_diff.py` 体检+重定位 → `_rva_apply.py` 批量落盘 →
> `injector/_rva_verify.py` 活体全量校验）把 38 条代码 RVA + 4 个数据全局一次性
> 重新定位，`cs2_tool.dll` 重编译重注入后**活体校验 21/21 通过**。
> 手法、分区段 Δ、每个全局的定位依据见 [REVERSE_NOTES.md §20](./REVERSE_NOTES.md)。
>
> ⚠️ 遗留：`RVA_MAP_HISTORY_GATE` 未定位（新版 `.text` 里没有任何引用它的指令，
> sites=0），暂留旧值；运行时读到非 0，`cs2_map_undo/redo` 实测可用。
>
> ⚠️ **MCP 服务是长驻进程**，RVA 是模块级常量 —— 改完 `cs2_mcp_server.py` 必须让
> MCP 服务重启（或另起新进程）才生效。

---

## 8. 2026-09-24 新版 hammer.dll：重定位 + 工具「底层化」改造

> Steam 于 2026-09-24 更新 `hammer.dll`（MD5 `DED2B1071B76EB3F71389EEBB865B023`），
> **旧 RVA 全部失效**。本节记录重定位结果与新增的底层工具。
> 详细地址表见 [REVERSE_NOTES.md §11](./REVERSE_NOTES.md)。

### 8.1 环境（当前有效）

| 项 | 值 |
| --- | --- |
| 开发位置 | **VM 内直接用 Trae**（同机跑 cs2 + 编辑器） |
| 构建目录 | `injected_dll/build_vs18`（本机是 **Visual Studio 18 2026 BuildTools**，不是 VS2022） |
| 构建命令 | `cmake -G "Visual Studio 18 2026" -A x64 -B build_vs18` → `cmake --build build_vs18 --config Release` |
| CMake 路径 | `C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe` |
| 注入用 DLL | `C:\cs2_tool_mcp\injected_dll\build_vs18\Release\cs2_tool.dll` |
| IDA MCP | 端口 **13337**，库 `c:\cs2_tool_mcp\ida_db\hammer_new.dll.i64`，imagebase `0x180000000` |
| IDA 查询 | `python injector\ida_eval.py 13337 --exec <脚本.py>`（脚本内用 `def _main():` + `_main()`） |
| 拉起 Hammer | `schtasks /run /tn HammerLaunch` → 等 `MainWindowTitle=Asset Browser` → 点 Hammer 图标 → 等 `hammer.dll` 加载 → 注入 |

### 8.2 已完成

| # | 事项 | 说明 |
| --- | --- | --- |
| 1 | **新版 RVA 全量重定位** | DLL 侧 + Python 侧硬编码全部更新并重编译、重注入。见 REVERSE_NOTES §11.1 |
| 2 | **端到端验证通过** | `map_list_docs`（count/路径）、`cs2_entity_list`（类名正确）、`cs2_map_info`、`cs2_read_qword("hammer.dll+0x24B7C80")` 精确命中 |
| 3 | **map 保存打通** | 有真实路径 + 脏状态时 `cs2_map_save()`（Qt 菜单）约 4.8s 返回并落盘；新图首次另存为要走 Win32 `#32770` 对话框 |
| 4 | **空栈 Undo 致命错误修复** | 空 DMX undo 栈调 `cs2_undo()` 后**保存地图时会弹 `FATAL ERROR: Error in the undo system!` 并杀死 cs2**。已在 `_undo_redo()` 加计数守卫 |
| 5 | **⭐ 底层写属性链路重定位 + 活体验证** | `sub_18062C9A0`（按名写字符串属性，内部自动 intern/创建）= **RVA `0x62C9A0`**；`CDmAttribute` 值写入 = `0x5CF020`；intern = CDataModel vtable **byte 424**。实测对 world 写 `name` 再读回一致 ✔ |
| 6 | **`cs2_entity_set_attr` 真正启用** | 之前是哨兵占位（等重定位），现走 `0x62C9A0` |
| 7 | **新增 `cs2_entity_set_classname`** | ~~CMapEntity vtable byte 2144（`sub_180896390`）~~ **该路径实测无效，已改为属性直写 `0x62C9A0`，见第 12 行** |
| 8 | **新增 `cs2_particle_set_definition`** | ① `0x62C9A0` 写 `effect_name` ② 实体内存扫 `CParticleHelper`（vptr=`base+0x17500B8`）+ 主线程调 `SetDefinitionByName`（`0x7F5350`）写 `helper+0xB8` |
| 9 | **DLL 新增 `scan_heap`** | 全进程堆扫描。**整块扫描实测会把 cs2 扫崩**，已改 `__try/__except` + 256KB 分块，并加 2GB 扫描上限 |
| 10 | **⭐ 底层「新建实体」链路打通** | `sub_1805BBB90(dm,"CMapEntity",name,1,0)`（CDataModel 通用创建，RVA `0x5BBB90`）→ `sub_1805BA670` 取句柄 → `sub_1805BB7F0` 查工厂表 → 工厂 slot0 `0x898D10`（new 6232 + `sub_180811220`）。CE 硬件断点活体验证：实体工具一次放 2 个实体，该断点命中 2 次 ✔。详见 REVERSE_NOTES §11.8 |
| 11 | **新增 `cs2_entity_create(classname, name)`** | 实测能建出合法元素（返回 handle + element，props 已建，CUndoCreateElement 已登记）；**但尚未挂进 CMapWorld 子节点表**，见 8.3 |
| 12 | **`cs2_entity_set_classname` 改为有效链路** | vfn2144(`0x896390`) 实测**改不动 classname**（既有实体也无效）；改为属性直写 `0x62C9A0` 写 props 的 `classname` → 实测 `info_player_start` → `info_particle_system` 读回一致 ✔ |
| 13 | **修正上一轮地址算错的坑** | 工厂 Create 运行时地址应为 `base+0x898D10`（`0x7FF9E4128D10`），此前写成 `base+0x888D10`，导致断点 0 命中、误判"实体不经工厂创建"。CE hit `timestamp` 另有 −8h 时区偏差，勿据此判断断点死活 |
| 14 | **⭐ 实体坐标打通（本轮主任务）** | 坐标不在 DMX 属性里，是 `CMapEntity` 原生 Vec3D：**`+0xA0` origin / `+0xAC` angles / `+0xB8` scales**。用「UI 放置的实体 vs 新建实体」对比确认（放置的为网格整数倍 `(-576,-320,0)` 等，新建的为 `(0,0,0)`）。`cs2_entity_list` 现在带 `origin=`，新增 `cs2_entity_get_transform`。详见 REVERSE_NOTES §11.9.1 |
| 15 | **元素类清单 + DMX 类型编码 + mesh/IO 结构** | datamodel 元素表（`dm+0x90`）枚举出 9 类元素（CMapEntity/CEditGameClassProps/CMapWorld/CMapRootElement/CMapSelectionSet/CMapVariableSetStorage/CVisibilityMgr/CStoredCameras/CStoredCamera）；属性类型编码（5=string, 33=数组<元素>, 37=数组<string>，bit 0x20=数组标志）；mesh = `CMapMesh.meshData → CDmePolygonMesh`（半边缘）+ 顶点流 `position/texcoord/normal/tangent`。详见 REVERSE_NOTES §11.9 |
| 16 | **VRF 仓库对照补全 + IO/mesh 读取工具** | 用户 clone 了 `third_party/ValveResourceFormat`；据 `IO/ContentFormats/ValveMap.cs` 更正继承链（`MapNode(origin/angles/scales) → BaseEntity(connectionsData/relayPlugData) → CMapEntity`）、IO 字段（`DmeConnectionData` 7 字段）、mesh 流位置（position 在 vertexData/loc3，texcoord 在 faceVertexData/loc1，materialindex 在 faceData/loc8）；解析出 **CMapMesh 虚表 RVA `0x176B8E0`**、`CDmePolygonMesh` `0x1D70620`；摸清 DMX **数组属性内存布局**并通用化。新增 `cs2_entity_get_io` / `cs2_mesh_list` / `cs2_mesh_get_geometry`。详见 REVERSE_NOTES §11.10 |
| 17 | **⭐ mesh 几何真实位置查明（测试发现）** | 用户画了 9 个 CMapMesh：**origin 读到了**（`+0xA0` 对 CMapMesh 同样成立），但 `meshData` 全是无效句柄、进程里**没有 CDmePolygonMesh 实例** → 编辑期几何不在 DMX 里，而在 **`CMapMesh+0x498` 内嵌的 `CHammerPolyMesh : CPolygonMesh`**（半边缘，~13632B，`+0x560` 自指回）。已拿到两个类的主虚表（`0x1766ED8` / `0x18143D0`）与两个构造函数的成员初始化清单。另新增通用排障工具 `cs2_mem_scan` / `cs2_find_by_vtable`（自检：按 `0x176B8E0` 精确找到 9 个 CMapMesh）。详见 REVERSE_NOTES §11.11 |
| 18 | **待验证的两项** | ① 9 个 mesh 里只有 2 个真有几何（AABB 非 ±FLT_MAX），其余是空 mesh；② ~~所有实体 `connectionsData` 仍为 0，IO 读取尚未验证~~ → **已解决，见第 21 行**（`connectionsData` 是保存期临时镜像，真数据在 `entity+0x4A0`） |
| 19 | **⭐ IO 实测结论：编辑期同样不落 DMX** | 用户在 `trigger_multiple` 上加了 `OnStartTouch → !self:Kill`：20+ 实体 `connectionsData` **全 size=0**、元素表**无 `CDmeConnectionData` 实例**、`entity_properties` 里**没有** `On...` 键；但**保存后的 `untitled_2.vmap` 里有**（`DmeConnectionData` + `outputName/inputName/targetName/overrideParam` + `OnStartTouch/Kill/!self`，与 VRF 字段名一致）。⇒ Hammer **保存时**才把原生连接转成 DMX 元素。已拿到 `CDmeConnectionData` 虚表 RVA `0x1779D30`、工厂 Create `sub_180983AE0`(`new(264)`，基类 152 + **7×16 字节字段**)。另发现「元素被编辑过」的字段簇（`+0x100/+0x198/+0x200/+0x220/+0x228/+0x278`，只有动过的那个元素非 0）。详见 REVERSE_NOTES §11.12 |
| 20 | **下一步（IO 活体读取，二选一）** | ~~**A**：CE 在 `sub_180983AE0` 设硬件断点 + 用户再保存一次地图 → 抓调用栈回溯原生连接结构~~（栈回溯已证明不可靠）；**B**：先实现 .vmap 文件解析 |
| 21 | **⭐⭐⭐ 方案 A 完成：实体 IO 原生结构已定位 + 读/增/删全部打通** | 不走栈回溯，改走**静态反编译 + 剪贴板链路**：从 KV3 字段名反查 xref → `sub_18020D240`（Outputs 面板 Paste，读 `QGuiApplication::clipboard()` 的 KV3 文本）→ **`sub_180986EA0(entity, out[4], const Conn*)` 追加连接**。<br>**结论**：编辑期连接存在 **`CMapEntity + 0x4A0` 的原生 `CUtlVector<Conn>`**（size@+0 / pad@+4 / data@+0x8 / alloc@+0x10），`Conn` **80 字节**：`+0x00` sourceEntity / `+0x08` output / `+0x10` targetEntity / `+0x18` input / `+0x20` param / `+0x28` ioTargetType / `+0x30` m_paramMap(KV3,16B) / `+0x40` float delay / `+0x44` int timesToFire / `+0x48` relay / `+0x49` globalRelay / `+0x4C` 唯一 id。<br>**活体实证** trigger_multiple `0x26426690C00`：`out="OnStartTouch" tgt="!self" in="Kill" type=7 delay=0 timesToFire=-1`，与用户 KV3 **逐字段一致**。<br>**`connectionsData` 假象解开**：它只是保存 .vmap 时的临时镜像，写完即清零（只剩 `alloc=8` + 陈旧句柄 `0x18E`(398)）。<br>**工具**：重写 `cs2_entity_get_io`（读原生向量）+ 新增 `cs2_entity_add_io`（调 Hammer 自己的追加函数，实测 `1→2` 条且 Hammer 自动分配唯一 id）+ `cs2_entity_remove_io`（后移 80B + 计数--，实测 `2→1`）。另解出 `ioTargetType` 枚举表（`0x1816CF740`：-1 INVALID / 2 ENTITYNAME / 6 EHANDLE / 7 ENTITYNAME_OR_CLASSNAME）。详见 REVERSE_NOTES §11.13 |
| 22 | **⭐⭐⭐ `cs2_map_save()` 真正落盘 + 「保存后主线程卡死」定位** | 之前调**最外层** `sub_1801363C0(session,0,0,1)`：文件写成功了，但 `a3==0` 会多跑一段「编辑器会话布局保存」（`sub_180147DD0` → `assetsystem.dll+0x8950E` → `tier0.dll+0x12153`）**把主线程永久卡死**（管道一起挂）。<br>**修法**：改调 **per-document 壳 `sub_1801639B0(doc, 0, 0, 1, 0, 0)`**（a4=1 强制保存、跳过脏判定，且不走布局分支）。doc = `*(session+312)+16` = `_map_doc()`。<br>**实测**：0.2s 返回、`main_thread_status=0`、`ret=0x1`，连调 2 次无副作用，Hammer 保持响应。<br>**端到端**：加 IO（param=`E2E_MARK_003852`）→ 保存 → 文件 `68869381→68869511` B，新文件命中该标记 1 处、保存前备份 0 处 ✔。详见 REVERSE_NOTES §12 |
| 23 | **⭐⭐⭐ mesh 几何读取打通（本轮主任务）** | 从官方访问器 `sub_180CC2830`（面→顶点坐标）反推出完整链路：**面池(32B)@poly+0x90 → 首半边 handle → 半边池(80B)@poly+0x58（+0=起点顶点 handle、+0x20=下一条半边）→ 顶点池(32B)@poly+0x20（+0x10=位置通道下标）→ 位置 = 通道指针@poly+0x8E0 + 12*下标**；三张 `handle(低22位索引)→槽位` 映射表在 `+0x38/+0x70/+0xA8`（24B/项）。数据通道数组 `poly+0x8D8+24*ch`（ch0=position）。<br>**轴序定案**：标准 (x,y,z)、z 朝上（用「z 厚度为 0 的地板 / y 厚度为 0 的墙」判定），世界坐标 = 本地 + `CMapMesh+0xA0`。<br>**活体验证**：用户放的 3 个方块（32³ `0x5bac7ba0000`、64³ `0x5bac7ba4000`、128³ `0x5bac7b8c000`）全部返回 8 顶点 + 6 个 4 顶点面环，坐标全整数、与包围盒自洽；`cs2_mesh_get_geometry` 已从「占位报错」改成真正读运行时几何 ✔。详见 REVERSE_NOTES §13 |
| 24 | **⭐⭐ 面/半边属性打通：UV + 法线 + 切线 + 材质** | 用 VRF `HammerMeshBuilder.WriteMesh`（`CPolygonMesh` → `.vmap` 的官方写法）对齐出运行时偏移：逐半边 `texcoord@0x1240 / normal@0x1328 / tangent@0x1428`，逐面 `textureScale@0x3118 / axisU@0x3300 / axisV@0x3318 / materialindex@0x33B8 / flags@0x33D0 / lightmap@0x33E8`，材料名表 `CUtlVector<CUtlString>@0x3448`（16B/条，条首 qword=名字）。<br>**关键坑**：逐半边属性按 **`poly+0x1110` 的「密集序」**排列，**不能**按池槽位或 handle 直读（否则串面；判据=同面 4 条半边法线必须一致）。<br>**实测**：32 方块材质 `materials/dev/reflectivity_30.vmat`、每面 4 角 UV 成规整 0.5×0.5 矩形、法线即面法线；地图自带多材质 mesh（`h=11`）读出 3 个材质名 + 每面不同 scale ✔。<br>`cs2_mesh_get_geometry` 已带上 `材质=` / `贴图 scale,U,V` / 每角 `uv=` `n=`。实体 IO（`cs2_entity_get_io`）一并复验：12 个实体有连接 ✔。详见 REVERSE_NOTES §13.8 |
| 26 | **⭐⭐⭐ 编辑 mesh 大小：官方顶点写入算子 `SetVertexPositions` 打通** | 从 `CPolygonMesh` 虚表后面那张操作名表（`SetVertexPositions/AddFace/MirrorAcrossPlane/FlipAllFaces/DissolveEdge/…`）反查到实现 `sub_180CDC6E0(poly, 顶点handle向量, 3×4矩阵, 位置向量)`；元素级包装 `sub_1809B8880(element, handles, positions)` 会先取元素变换再调它，`sub_180BFDAA0(矩阵,x,y,z)` 是那个 3×4 行主序矩阵变换。<br>**做法**：传**单位矩阵**直调底算子 → 写进去的就是我们给的值，不依赖「local+origin=世界」（tile mesh 不满足）。顶点 handle 从 `poly+0x30` 映射表枚举（低22位==下标即活跃）。<br>**实测**（`cs2_mesh_scale`）：手绘盒子 32×8×32 `scale="2 2 2"` → 精确 64×16×64、`0.5` 完全还原、非等比 `1 2 1`@自定义pivot 正确、tile mesh 本地轴精确；0.13s/次、可重复、Hammer 保持响应 ✔。详见 REVERSE_NOTES §13.10 |
| 27 | **⭐⭐⭐ 修改实体参数已打通（本轮主任务）+ IO 修改收尾** | **关键发现**：实体 keyvalue **一律以 AT_STRING(类型码 5) 存储**，数值/向量型也是字符串 ——活体枚举 `CEditGameClassProps` 链实测 `spawnflags='0'` / `speed='100'` / `movedir='0 0 0'` / `rendercolor='255 255 255'`，所以「修改数值/向量参数」**不需要按类型分派的写入器**（原「`sub_18062CA90` 一族」的待办作废）。<br>**两条写入链路**：① keyvalue 用 `sub_18083E0D0(entity, name, value)`（RVA `0x83E0D0`，属性缺失时按类型 5 创建，带类回调/targetname 索引/包围盒脏通知）；② 变换 `origin/angles/scales` 用 `sub_18086B550(entity, name, value, 0)`（RVA `0x86B550`，属性表变换 pin → 直接写 `CMapEntity+0xA0/+0xAC/+0xB8` 原生 Vec3D；用 keyvalue 写入器只会凭空造同名 AT_STRING）。<br>`cs2_entity_set_attr` 已按此改写，实测：`spawnflags 0→3→0`、`rendercolor →255 0 0→还原`、`speed 100→150→100`、`targetname h8→probe→h8`、`origin/angles/scales` 写读一致且**立即生效**（真 MCP 通道复验 ✔）。<br>**副产物**：属性链是 `element+0x48` 单向链表（无独立哈希索引），按 §14.4 配方可安全摘链删属性（本轮实测摘掉两个测试键，其余属性完好）；keyvalue 写入会推进 Datamodel undo 栈，变换写入不会。<br>IO 修改（增/删/查）此前已完成，本轮用真 MCP 通道复核净零改动 ✔。详见 REVERSE_NOTES §14 |



| 28 | **⭐⭐⭐ 收尾补齐 + undo 重定位 + 官方放置序列（本轮，前两项已验证）** | ① **收尾补齐**（已验证）：新增 `cs2_entity_remove_attr`（摘链删属性，带脏传播）、`cs2_entity_set_transform`（一次设 origin/angles/scales），`cs2_entity_get_attr` 现在带类型码并按类型解码（string/int/color/vec3/句柄数组/字符串数组）。工具数 42→44。<br>② **地图撤销 Pop 重定位**：旧 `0x14080D0` → 新 **`0x1529E80`**（`CMapDocHistory::Pop`，反编译与旧版逐行一致；虚表 `0x1763E00`，全局开关 `hammer.dll+0x221A418`，空栈有 CanUndo 守卫）。已接进 `cs2_map_undo/redo`。**✅ 端到端已验证（2026-09-27）**：用户在 Hammer 里放置一个 `info_player_start`（历史 4 步，未保存）后跑自包含往返验证 `A→undo→B→redo→C→undo→D` —— **A≠B**（撤销确实移除该实体）、**C==A**（重做后 183 个实体逐字段一致）、**D==B**（可重复），计数每次精确 ±1。详见 §15.1<br>③ **官方「放置对象」序列挖出**（`sub_180180190` = mapviewdroptarget.cpp）：`工厂 Create → vfn2144 SetClassName → sub_180866D70 → sub_180879170(doc, child, 0)`，其中 **`0x879170` = CMapNode::AddChild** 才是「挂进世界」那一步（第一参数是 **CMapDoc**，不是 world）。另确认 `0x864EA0`=GetParent、`0x864EB0`=GetRoot。详见 §15.2<br>④ **⭐ 端到端验证通过**（§15.4c）：`cs2_entity_create("info_particle_system", …)` → 类名生效、world 子节点 **130→131**、`GetParent == CMapWorld`、游戏类 `+0x550` 已绑定、**CParticleHelper 已创建**，1.73s；随后 `cs2_entity_set_classname(…, "info_target")` → `+0x550` **换成目标类对象**、helper 归 0。**「新建实体 → 挂进世界 → 绑定游戏类/重建 helper」整链打通**。<br>⑤ **重大纠错**：长期结论「vfn2144 SetClassName 无效」是**错的** —— 真因是管道自带的 `call_virtual` 会**静默丢弃 `str:` 参数**（`ipc_pipe.cpp` 里它只把字符串当模块地址解析），导致函数收到空类名直接 return。已新增 `_call_vfn`（自己解析虚表槽 + `call_function`）替代，所有相关调用点已改。<br>⑥ 三条踩坑见 §15.3/§15.4：别对 world 调 `sub_1805C81C0(world,3)`（entity_list 从 1s 变 200s）；别在主线程派发中途杀客户端（Hammer 永久死锁）；`call_virtual` 别传 `str:` 参数（**该 DLL 缺陷已于第 29 行修复**）。 |
| 29 | **⭐⭐⭐ `cs2_entity_list` 提速 48.6× + DLL `call_virtual` / 编码修复（本轮）** | **性能**（同会话成对实测，输出逐字节一致）：`limit=200` **114.12s / 34,487 次往返 → 2.35s / 3,145 次**；`limit=20` 22.65s → 0.56s；刚开图的繁忙会话里 265.82s → 12.54s（绝对耗时随 Hammer 忙闲漂移，故以成对测量为准）。手段（①~⑤ 全在 Python 侧）：<br>① **句柄→元素改查 CDataModel 元素表**（`+0x90` 数据 / `+0x88` 容量，16B/项，元素指针在 +8；下标 = 句柄低 22 位）—— 实测与 vfn168 `_resolve_handle` 逐项一致，于是**彻底免掉「每个子句柄一次主线程 `call_virtual`」**（~31ms/次，原 limit=20 就 303 次）。<br>② **属性链块读**：CDmAttribute 按 **0x30 步长连续分配**（实测相邻地址差恒 48、偶有跳跃），一次块读覆盖 ~21 个节点；属性名走**驻留串指针缓存**（命中零额外读取）；`classname`+`name` **一次遍历取齐**（原先 props 链要遍历两遍）。<br>③ 树遍历**每节点一次块读**（vtable@+0 与子节点字段@+0x1F8/+0x200 都落在 0x208 字节内）。<br>④ **管道长连接**（DLL 的 `ClientThread` 本来就是「读请求→处理→写响应」循环；Python 侧原先每次调用都 `CreateFileW`+`CloseHandle`）+ 缓存 kernel32 绑定（原每次 Win32 调用都重建 `WinDLL`）。<br>⑤ **缓存 hammer 基址**：DLL 的 `get_module` 单次要 **40ms**（模块枚举很贵），优化前每实体一次共 624 次 ≈ 25s；缓存后 1 次，**管道重连（Hammer 重启/重注入）时由 `_invalidate_address_cache()` 自动失效**。<br>**DLL 侧**：⑥ `call_virtual` 与 `call_function` 的参数解析合并为 `ParseCallArgs`（支持 `str:`；解析失败的字符串**压 0 保持参数个数**，不再左移），响应新增 `arg_count` 便于验证 ⑦ `read_memory` 上限 1024→**8192** + 十六进制改**查表编码**（实测 64B 与 8KB 单次耗时相同 ≈1.4ms，编码开销≈0）⑧ `SendResponse` 改**循环写**（大响应可能超过管道缓冲区，单次 `WriteFile` 只写一部分会让响应流错位）。<br>**验证**：`call_virtual(str:"info_target")` → `arg_count=3`、classname 生效、`+0x550` 游戏类对象替换；再改回原类名后 classname 与 `+0x550` **精确还原，净零改动**；畸形字符串参数也保持 `arg_count=3`。回归 `get_attr`/`get_transform`/`find_attr`/`map_info`/`area_query`/`mesh_list` 全部正常。详见 REVERSE_NOTES §15.6 |
| 30 | **⭐⭐ 大图实测（`ze_surf_easy` 反编译 ZE 图）+ 修 `_enum_elements` 静默截断 bug** | 用户换上一张**真实反编译 ZE 图**压测（4,403 实体 / 8,546 场景元素 / 4,124 CMapMesh / 元素表 cap **97,102**），功能全通但暴露一个**会漏对象**的真 bug。<br>**功能验证（全通）**：① 全部 4,124 个 `CMapMesh` 读运行时几何 **0 失败**（合计 36,715 顶点 / 27,095 面，材质 `toolsnodraw`/`zoo/concrete`/`zoo/tile`/`toolsplayerclip`/`toolstrigger`…）；② 全部 4,403 实体读原生 IO → **155 个有连接、共 820 条**，内容真实（`OnTrigger→server:Command param='mp_freezetime 1'`、`zr_infect_mzombie_respawn`、`OnStartTouch→!self:Kill`、`tele_05:Enable delay=40`）；③ 实体属性/变换/类名/单个 mesh 几何（8 顶点/6 面/UV/法线）全部正确。<br>**🐛 bug**：`_enum_elements` 的 `for i in range(min(cap, limit))` 里 `limit` 默认 **8192**，`cap=97,102` 时**只扫了表的前 8.4% 且静默不报** → `cs2_mesh_list` 报 **338**（实际 **4124**）、`cs2_area_query` 的 `mesh_total` 同错，**同一个小盒查询命中 mesh 从 4 涨到 18**（漏掉 78% 的命中对象，handle≥8192 的完全查不到）。<br>**修法**：`_enum_elements` 改 `limit<=0`=扫全表 + 表数据走 `_dm_table()` 批量读；`cs2_mesh_list` / `cs2_area_query` **改走一趟 `_walk_elements`**（vtable 顺带就有），`area_query` 同时把「扫表找 mesh + 走树找实体」两趟并一趟；新增 `_dm_handle_map` 反查句柄；顺带修掉 `area_query` 头部把分母写成元素总数的措辞。复测：mesh_list **4124**、小盒 **mesh 18/4124 实体 1/4403**。<br>**另查明**元素表类型分布：`CMapEntity` 4403 / **`CEditGameClassProps` 4404（每实体 1:1 的独立元素层）** / `CMapMesh` 4124 / `CMapStaticOverlay` 13 / `CMapGroup` 5；**遍历表（12,958 次 vtable 读）比走树（8,546）更贵**，所以列对象一律走树。详见 REVERSE_NOTES §15.7 |
| 31 | **⭐⭐ 补齐「漏读的数据」：元素类型全谱 + 属性类型码补全 + 两个新工具（工具数 44→46）** | 用户问「还有什么漏的数据没获取」，于是把 ze_surf_easy 里**图里存在但工具没碰**的东西系统盘了一遍（IDA 按 RVA 取符号名 + 活体遍历属性链）。<br>**① 元素类型全谱**（13 种，见 REVERSE_NOTES §15.8.1）：`CMapEntity` 4403 / `CEditGameClassProps` 4404（**每实体 1:1 的独立元素层**）/ `CMapMesh` 4124 / `CMapStaticOverlay` 13 / `CMapGroup` 5 / `CMapSelectionSet` 1 / `CMapRootElement` 1 / `CMapVariableSetStorage` 1 / `CVisibilityMgr` 1 / `CStoredCameras`+`CStoredCamera` 1+1 / `CMapWorld` 1 / `CDmElement` 2。后 8 种本轮之前**完全没读**。<br>**② 属性链全量清点**（§15.8.2）：实体自身链 11 项（原来只暴露过 `name`）；`CMapRootElement` 16 项（`rootSelectionSet`/`mapVariables`/`visbility`/`3dcameras`/`world`…）；`CMapWorld` 12 项；mesh/overlay/group 各 6~8 项。<br>**③ 🐛 修两个解码 bug**（§15.8.3）：`type=4` 是 **1 字节 bool** 却按 u32 读 → 高 3 字节未初始化垃圾（`isProceduralEntity` 读成 1062435584；`fixupEntityNames` 恰好后 3 字节为 0 所以看着正常，更隐蔽）；`type=15`(`referenceID`) **只占 8 字节**，别读 16。另证实 `type=34` 是 CUtlVector（`hiddenFlags` count=cap=6069）。<br>**④ 🐛 修 `_read_int(u64)` 有符号**（§15.8.4）：DLL 返回有符号 JSON 整数 → `referenceID` 被打印成 `'0x-114e62cf3cd44a44'`、高位地址 `hex()` 变负。现按位宽强制还原无符号。<br>**⑤ 新增工具**（§15.8.5）：**`cs2_entity_attrs`**（列出实体**全部**属性 / keyvalue —— 补上最大的实用缺口，实测 `trigger_hurt` 23 项含 `damage='999999'`/`spawnflags='4097'`）、**`cs2_map_groups`**（分组 / 可见性组 / 选择集 / 地图变量 / 相机 —— 实测 5 个分组：328 实体 / 3585 mesh / 光照探针 / 18 ambient_generic，可见性组 nodes 6069 个）；`cs2_entity_list` 每行补 `id=<nodeID>`。<br>实现上把属性链遍历抽成**单一实现** `_dm_iter_attrs()` 生成器（`_dm_find_attrs` 找齐即停 / `_dm_walk_attrs` 全量），避免两份块读逻辑漂移。 |
| 32 | **⭐⭐ 删除实体：`AddChild` 的对偶虚表槽 `父节点+0x1D0`（工具数 46→47）** | 用户问「删除成功了吗 / 没有历史」，遂把删除链路做完并端到端验收。<br>**① 槽位定位**：AddChild 是父节点虚表字节偏移 **0x1C8**（`sub_180879170` 里 `(*(*(a3)+456))(a3, a2)`），对偶移除槽 = **`+0x1D0`**。静态校验：`CMapWorld` `0x1772920+0x1D0` → IDA `0x181772af0` 存的正是 `sub_180925C60` ✅；`CMapEntity` `0x1758D00+0x1D0 = 0x181758ed0` → `sub_18084F400` ✅；`CMapGroup` 等 6 类 → `sub_1809EB760`（**硬编码 `notify=1`**，故工具默认也传 1）。<br>**② ⭐ 关键结论：`children` 就是 DMX 属性**（AT 33 元素句柄数组），`parent+0x1F8`(计数)/`+0x200`(句柄指针) 就是它的内联 CUtlVector 头 —— 实测两边**逐项一致**（636=636、集合相同、差集 0）。所以删除**一致且可存档**：`children` 属性同步 → 保存 .vmap 不会写回被删实体。三个被摘除的临时实体在原生表与属性里**都已消失**。<br>**③ 实测**：裸链路建临时实体 → `vfn0x1D0(child,0)` `children 637→636` / 6ms；`notify=1` 同效 / 8ms；新工具删除 `637→636`、`GetParent 0x54958488000→0x0`、`仍在 children 属性里=False`、5ms；删 `CMapWorld` 被拒；重复删报「已是游离节点」。Hammer 全程保持响应（`ping ok`）。<br>**④ 已知语义（写进 docstring）**：**不产生 Undo 历史**（vfn0x1D0 直接改原生子表，不经 Hammer Undo 命令层 —— 这就是用户看到「没有历史」的原因）；被摘下的 `CDmElement` **仍留在元素表里成孤儿**（本会话不回收）；实体自带的 `CMapMesh` 子节点随整棵子树脱离世界（不逐节点递归）。<br>**⑤ 新工具**：`cs2_entity_delete(entity, notify=True)`。详见 REVERSE_NOTES §15.9 |
| 33 | **⭐⭐⭐ 摸清「怎么把操作写进 Hammer 的撤销历史」（`CMapDocHistory` 记录型接口）** | 用户问「创建和删除怎么加历史」。**核心结论：Hammer 的历史栈是「记录型」的，当可写接口用即可，不需要自己实现 Undo/Redo。**<br>**① 两套撤销系统（成对实测）**：栈 A = `CMapDocHistory`（`root+0x240`/`+0x248`）= **Ctrl+Z**；栈 B = DMX `CUndoManager`（`CDataModel+240`）= `_undo_scope_*` 那套。一次 create+delete：**栈 A 27→27 完全不动**，栈 B 1190910→1190928→1190929（+18/+1）→ **这就是「删了没历史」的根因**。另查明栈 B 的 `+0` 是**单调计数器**（119 万级）不是栈深度。<br>**② 栈 A 结构（活体 dump + 反编译对齐）**：**步对象 192B** = `+0x00 命令数 / +0x08 命令数组 / +0x10 容量 / +0x18 回指 history / +0x20 步ID / +0x24 char name[128]`（就是 Ctrl+Z 菜单那串）；**命令包装 80B** = `+0x04 kind`（**0=通用命令 / 1=对象被移除 / 2=对象被新增**），对象分别存 `+0x08 / +0x28 / +0x40`。活体 dump 到真实步：`'New Entity'`(2 命令) / `'Delete Selection'`(3 命令) / `'Modify Selection'`(1 命令)；vtable 反查 `0x1765548`=`CSelection`、`0x17654E0`=`CSelectionStateBackup`、`0x177EC900`=`CVisibilityMgr`、`0x1759598`=`??_7CMapEntity@@6B@_0`。<br>**③ 记录 API（可直接调）**：`0x1529290` PushStep(hist,name,0,0) · `0x1529240` PushStep+Notify · **`0x15290B0` RecAdded(hist,node)** · **`0x1528EC0` RecRemoved(hist,node)** · `0x1528D70` RecCommand · `0x1529700` Notify。⚠ **`node` 必须传 `元素+0xC8`**（CMapNode 接口子对象），不是元素本身。这些也以虚函数挂在 `CMapDocHistory` 虚表（RVA 0x1763E00）上 —— **这才是用户直觉里的"工具间交互的桥"**（不是 tier0 的 memmove）。<br>**④ ⭐ 撤销/重做自洽**：`sub_181529D20` 反编译显示 kind1↔kind2 互为逆操作且**自动往配对栈写反向记录**（撤销「移除」=`vfn72(保存的父)`+往重做栈记「新增」；撤销「新增」=往重做栈记「移除」+`vfn72(0)`）→ **只需记录，无需实现 Undo/Redo**。<br>**⑤ ⚠ 顺序陷阱（实测）**：记录函数会调 `obj->vfn64()`（= **父节点**，`world+0xC8`）存进包装 `+0x30` 供撤销挂回用，而**摘除后它立刻归 0**（`0x549584880c8 → 0x0`）→ **删除必须「先记录、后摘除」**（这也解释了 Hammer 自己那步 `+0x30` 存的是有效值）。正确顺序：创建 `PushStep→建/挂→RecAdded→Notify`；删除 `PushStep→RecRemoved→摘除→Notify`。<br>**⑥ 前置条件实测全满足**：全局闸门 `hammer+0x221A418`=1、`hist+144` enabled=1、`hist+140` busy=0、步ID计数器=60。<br>**⑦ 🐛 孤儿副作用（用户实测反馈）**：早先被 `vfn0x1D0` 摘除的 `mcp_place_test`（handle=10）——元素、名字、类名、句柄都还在（`cs2_entity_get_io` 仍可读），但 `GetParent=0`、`vfn64=0`、世界树不可达 → **Hammer 里「看得到、选不中、打不开 I/O」**（枚举 DMX 元素的列表仍列出它，走世界树的路径都到不了）。根因：**纯摘除不改 Hammer 的名字/选择索引**；根治方向 = 改用记录型删除。详见 REVERSE_NOTES §15.10<br>**⑧ ✅ 当日已实现并往返验收**：新增 `_hist_push_step` / `_hist_record_object` / `_hist_notify` / `_hist_state`；`cs2_entity_create` 挂进世界后记「新增」、`cs2_entity_delete` **摘除前**记「移除」（历史逻辑 try/except 包裹，失败只警告）。自包含往返 `A→undo→B→redo→C→undo→D` 全通（undo 40→41→40→41→42→41；A 在树内 / B 移出 / C 回来 / D 挂回 `GetParent=CMapWorld`）。🐛 踩坑：**步名必须 ASCII**（管道走 ANSI，中文变 `??`），已改为 `cs2: create/delete <类名>`。详见 §15.10.8/§15.10.9 |
| 34 | **⭐⭐⭐ 从零创建笔刷（盒形 solid）成功 —— 新工具 `cs2_mesh_create_box`** | 用户问「能改 mesh 大小吗，在 mcp_place_test 上面 64 放个 32 的正方体」。**改已有 mesh 尺寸**走既有 `cs2_mesh_scale`（PROGRESS 第 26 行已验收）；**从零建笔刷**本轮打通。<br>**① 关键事实**：CS2 笔刷 = `CMapMesh` 元素 + **内嵌的运行时 `CHammerPolyMesh`**（`el+0x498`）；`CreateElement("CMapMesh")` 出来的新元素**自带一个空的可用网格**（vtable 校验通过、顶点 0）→ **不需要碰 `CDmePolygonMesh`**（`meshData` 属性编辑期是无效句柄，存盘才写，实测地图里已有笔刷也一样）。`CMapSolid` 字符串只被 `sub_18064C5B0` 引用 = **加载期版本迁移**，不是创建路径。<br>**② 找到建面 API**：`sub_180901F40(el, 点数组, 贴图轴默认值, 点数, 材质名)` = **全整数/指针参数**，可直接用桥调；内部 = 开 op 上下文(`CreateFaceLocalFromPoints`) → `sub_1808CAE90` 建面（含建顶点）→ `sub_1808BB240` 指定材质。点是 **12B/个**的本地坐标 `{x,y,z}`；贴图轴默认值 **32B** = 常量 `(0,1,1,1)`+`(1,0,0,0)`。<br>**③ 官方样板**：`sub_1801813E0`（`mapviewdroptarget.cpp:696` 拖放贴花）= 建元素 → `sub_180901DF0(el,宽,高,材质)` 建面 → 设位置/朝向 → `sub_180866D70` PostClass → **`sub_180879170` AddChild**（与建实体同一条）。<br>**④ 🐛 大坑（通用教训）**：官方的 `sub_180901DF0` 第 2/3 参是 **float（走 xmm）**，而注入 DLL 的调用桥 `InvokeStub` **只设整数寄存器**（`hammer_bridge.cpp:608`）→ 实测调它建出来**空的**。**以后「调了没反应」先查目标函数有没有 float/double 形参。**<br>**⑤ 验收（ze_surf_easy 实测）**：`cs2_mesh_create_box(center="-12992 11872 144", size="32")` → 元素 `0x5496ff04000`、顶点 24、材质 `tools/toolsnodraw`、AABB `(-13008,11856,128)~(--12976,11888,160)`（正好 32³、盒心吻合）、`AddChild` 成功（world 638→639）、`GetParent=CMapWorld`、**记进 Ctrl+Z 历史**（97 步 `'cs2: create box 32x32x32'`）；`cs2_area_query` 能看到。详见 REVERSE_NOTES §16 |
| 35 | **⭐⭐ 桥接层支持四编辑器模块 + pet 活体验证；10-10 新版 hammer.dll CE 免注入重定位** | ① **四模块**：hammer / met / modeldoc_editor / pet 各 DLL **自带** `CreateInterface` + 独立 ToolSystem2（接口名：modeldoc 是 `ToolSystem2_ModelDoc`，其余 `ToolSystem2_001`；CreateInterface RVA 见 REVERSE_NOTES §22.1）。新增 IPC `tool_modules`/`get_tool_system`、MCP 工具 `cs2_tool_modules`/`cs2_get_tool_system`（54→56）；`Initialize()` 放宽为任一模块可用即成功。<br>② **🐛 修复模块快照陈旧**：首版只在注入时枚举一次，注入后才按需加载的 `pet.dll`（双击 `.vpcf` 才加载，Asset Browser 无入口）永远 `loaded=false`。改为 `ToolModules(force_refresh)` + `GetToolModule` 命中但未加载时**惰性重探**，无需重新注入。<br>③ **✅ pet 验证**：打开粒子编辑器后 `create=base+0x3A2AE0`（与导出表吻合）、tool_system 非 0，CE 只读 RTTI = **`CPetApp`**（与 hammer 返回 `CHammerApp` 对称——App 单例自身实现 ToolSystem2）；ping/hammer_app 回归全绿。<br>④ **⚠️ CE 事故教训**：用 `executeCodeEx` 远程调 pet CreateInterface 时 `allocateMemory` 返回 nil 未判空 + 参数位次错（rcx=name 传成 NULL）→ NULL 解引用 cs2 闪退。立规：CE 只做只读校验，进程内调函数一律走注入桥接层。<br>⑤ **10-10 新版 hammer.dll（MD5 `832119E3…`，39,611,032B）**：差分只补得上函数（34/34 函数 RVA 对），**11 条 vtable/数据全局靠 CE 免注入活体复核修正**（`.rdata` 整体 +0x2000 但 Δ 不统一）；另抓出 `RVA_QT_*` 是 Qt5Widgets/Core 偏移、被旧差分误当 hammer 偏移导致注入闪退。详见 REVERSE_NOTES §21/§22 |
| 36 | **⭐⭐ 三模块 IDA 逆向 + 跨模块接口/bind 枚举（四模块活体全绿，工具数 56→59）** | 用户令「自己打开 IDA 给其他 dll 添加功能」：三个 IDA 9.1 实例（端口 13337/8/9）逆向 met/modeldoc_editor/pet，确认与 hammer 逐字节同构的两条数据链。<br>① **RVA 表**（s_pInterfaceRegs 链头 / bind 描述符链头）：met `0x4A1740`/`0x4A0AD0`、modeldoc `0x1AAB588`/`0x1AA9620`、pet `0x93A1D0`/`0x938408`（hammer `0x2738770`/`0x2731E98`）。接口链头桥接层从 CreateInterface 序言 `4C 8B 0D disp32` 动态解析（SEH 保护，RVA 兜底），活体四模块逐一精确吻合；bind 链头为纯数据全局只能硬编码。met RTTI 具体类 = **`CMaterialEditorTool`**。<br>② **实现**：DLL 侧 `ListModuleInterfaces`/`GetModuleInterface`/`ListModuleBindTargets`，全部 raw 读固定偏移（命令数 +0x40、命令数组 +0x48、命令名 +0x08），**零虚调用**；IPC `module_interfaces`/`module_get_interface`/`module_bind_targets`；MCP 三个同名薄工具。<br>③ **✅ 活体（同会话四模块全加载）**：bind 目标/命令 hammer 69/1194、pet 10/105、modeldoc 23/227、met 1/15（未开材质文档只有全局热键）；名字/类名/源文件:行号/命令均真实；取接口 rc 与单例指针全部正确。另实测修正 §22.1：Asset Browser 顶栏**有** Particle Editor 入口（点击偶发 15s 超时但照常打开）。<br>④ **进程内 RTTI**（无需 CE）：桥接层解析每个模块 ToolSystem 主虚表的实现类名，`tool_modules`/`get_tool_system` 新增 `tool_system_class` —— hammer `CHammerApp` / met `CMaterialEditorTool` / modeldoc `CModelDocEditorApp` / pet `CPetApp`（订正 §22 的 BCD64 偏移：pTypeDescriptor 在 COL `+0x0C`）。<br>⑤ **⚠ 负结论**：核查后**放弃**加 `cs2_module_tools` —— met 对象里的容器元素 RTTI 是 `CQMaterialEditor`（材质**文档**，非工具），且每个「工具」登记的就是一条 bind 描述符，故 `cs2_module_bind_targets` 已是各编辑器工具/命令的权威清单，另立 tools 工具属冗余。详见 REVERSE_NOTES §23.4/§23.5 |
| 37 | **⭐⭐ 跨模块命令执行（`cs2_bind_list/inspect/run` 加 `module`）+ 修正 functor 调用法** | 用户令「执行跨模块命令测试」。把 §17.12 那套只认 hammer 的 `cs2_bind_run` 推广到任意已加载编辑器模块。<br>① **泛化**：三个工具加 `module` 参数（默认 hammer），链头改从 `get_tool_system(module).bind_head` 取（新增模块信息缓存 `_tool_module()`，随管道重连作废）；读逻辑不变（纯只读虚调用）。<br>② **⚠ 关键订正**：§17.8 的「`+0x08`=pmf·`+0x10`=adj·`+0x18`=arg，直接调 `pmf(ctx+adj,arg)`」**只在 lambda 捕获 `[pmf,adj,arg]` 时成立**。实测同一 DLL 还有「只捕 pmf」的（`_Do_call`=`mov rcx,[rdx]; jmp [rax+8]`，`+0x10/+0x18` 是**堆残留**，adj 读到 ASCII 文本 → 盲算会得野 `this`）和 `arg` 为 **bool 1 字节** 的（`movzx edx,byte [rax+18h]`）。→ 改为**调 `_Do_call` 本身**（= `std::function::operator()`，偏移写死在自身代码里，布局无关）：`alloc_memory(8)`→`write_value(cell,ctx)`→`call_function(do_call,[fn,cell])`→`free_memory`。显式传 `arg=` 时才回退到直调 pmf（已标注风险）。<br>③ **跨模块 ctx**：只自动解析**该模块 App 单例**（`target 实现类名 == get_tool_system(module).class` → ctx=tool_system）；非 hammer 的工具实例表（会话→CToolManager）未逆向，需 `ctx=` 显式给。<br>④ **✅ 活体（四模块同会话全加载）**：`GlobalHotkeys.DummyNoOp`（pmf 就是 `retn 0`，零风险）在 **pet/met/modeldoc/hammer 四模块**全部经各自 `_Do_call` 执行成功；真实命令 pet `PetApp.ResetLayout`/`PreviousSession`、modeldoc `ModelDocEditorApp.ClearRecentFiles`、hammer `HammerApp.ToggleShowHelpers`×2（还原）全部成功，**全程 ping ok、无崩溃**。`cs2_sel` 行为不变。<br>⑤ **`GlobalHotkeys`（`CGlobalHotkeyCommands`）**：该类实例按 vtable/RTTI/静态初始化三条路**未定位到**，但 IDA 反汇编其命令（`ShowConsole`/`SwitchToEngineWindow`/`ShowInputDebugger`/`DebugWidgetUnderMouse`/`DummyNoOp`）确认**全部只操作模块全局量、从不触碰 `this`**（且 functor 均为「只捕 pmf」形状）→ `_bind_ctx` 对 `CGlobalHotkeyCommands` **自动回退到本模块 App 单例**。实测 `met.SwitchToEngineWindow`（返回 0x1）、四模块 `ShowConsole`（均 0x1，弹出控制台）全部成功 → **met 从此也能跑真实命令**。<br>⑥ **仍待做**：非 hammer 模块的「工具实例表」（App→会话→CToolManager）未逆向，且需该编辑器先打开文档才有会话（实测四模块 `app+0x58` 现为 0）；故 modeldoc 的 20 个工具类目标仍需 `ctx=` 显式给实例地址。详见 REVERSE_NOTES §23.6 |

### 8.3 待办 / 卡点

| 优先级 | 事项 | 说明 |
| --- | --- | --- |
| ~~P0~~ | ~~**新元素挂进 CMapWorld**~~ | ✅ **已完成并端到端验证**，见 8.2 第 28 行 / REVERSE_NOTES §15.2/§15.4c。官方 API = `sub_180879170(doc, child, 0)`（CMapNode::AddChild）；`cs2_entity_create` 现在按官方序列建实体并挂进世界 |
| ~~P0~~ | ~~**改类名要重建游戏类/helper**~~ | ✅ **已完成并验证**：`cs2_entity_set_classname` 走 `vfn2144` + 属性直写 + `sub_180866D70`；实测 `+0x550` 游戏类重建、CParticleHelper 按类创建/销毁。⚠ 真因纠错见 §15.4b：不是 vfn2144 无效，是 `call_virtual` 丢 `str:` 参数；已用 `_call_vfn` 绕开 |
| ~~P0~~ | ~~**写回实体坐标（place entity 收尾）**~~ | ✅ **已完成**，见 8.2 第 27 行 / REVERSE_NOTES §14.3：写坐标走 `sub_18086B550(entity, "origin"/"angles"/"scales", "x y z", 0)`（属性表变换 pin → 原生 `+0xA0/+0xAC/+0xB8` 成员），实测立即生效；`cs2_entity_set_attr` 已接入 |
| ~~P0~~ | ~~**mesh 坐标读取**~~ | ✅ **已完成**，见 8.2 第 23 行 / REVERSE_NOTES §13。编辑期几何在 `CMapMesh+0x498` 内嵌的 `CHammerPolyMesh`，已按半边缘 DCEL 读出顶点/面环/包围盒 |
| ~~P1~~ | ~~**实体 IO 读取/写入**~~ | ✅ **已完成**，见 8.2 第 21 行 / REVERSE_NOTES §11.13。读 `entity+0x4A0` 原生 `CUtlVector<Conn>`；增/删走 Hammer 自己的 `sub_180986EA0` / `sub_180987AF0`（删除 2026-09-28 换掉手动移位，不再泄漏字符串，且两者均已接 Ctrl+Z） |
| ~~P1~~ | ~~**让 `cs2_map_save()` 真正落盘（脏标记）**~~ | ✅ **已完成**，见 8.2 第 22 行 / REVERSE_NOTES §12。不再依赖脏标记：直接调 `sub_1801639B0(doc, 0, 0, 1, 0, 0)`（a4=1 强制）。原 Qt 菜单方案作废（文档干净时 QAction 是 disabled） |
| ~~P1~~ | ~~**修 DLL 的 `call_virtual`（会丢 `str:` 参数）**~~ | ✅ **已完成并验证**，见 8.2 第 29 行 / REVERSE_NOTES §15.6：`ipc_pipe.cpp` 里 `call_virtual` 与 `call_function` 的参数解析已合并为 `ParseCallArgs`，支持 `str:`，且**解析失败的字符串压 0 保持参数个数**（不再左移）。已重新构建 `cs2_tool.dll` 并注入验证：`arg_count=3`、类名生效、`+0x550` 游戏类对象随类名替换并精确还原。Python 侧的 `_call_vfn` 保留（少一次虚表解析往返，且不依赖 DLL 版本） |
| ~~P1~~ | ~~**IO 编辑的 UI/undo 收尾**~~ | ✅ **已完成并往返验收**（2026-09-28），见 REVERSE_NOTES §11.13.7。逆向确认面板 Add `sub_18020C9E0` / Delete `sub_18020CD40` / Paste / 7 个单元格提交**全部**走 §17.14 同一套：PushStep → `sub_18086D9B0(hist, entity+0xC8, 1)` → 改原生向量；`sub_180206BC0` 是**纯 Qt 表格重建**，与数据/undo/保存无关（开着的 Outputs 面板需重选实体刷新）。`cs2_entity_add_io`/`remove_io` 加 `history=True`（默认），删除改调面板同款 `sub_180987AF0(entity, index<<16)`（正确析构，消除旧实现的字符串泄漏）。活体 7/7：add→77 步、undo conns 1→0、redo 字段逐字节还原、remove(sub_180987AF0)→78 步、undo 完整还原、redo 再删 |
| ~~P0~~ | ~~**mesh 几何读取（新线索）**~~ | ✅ **已完成**，见 8.2 第 23 行 / REVERSE_NOTES §13。官方访问器 = `sub_180CC2830`，`cs2_mesh_get_geometry` 已读运行时几何 |
| **P1** | **非手画 mesh 的完整变换** | 地图自带 tile mesh 的 `+0xA0` 与顶点不在同一参照系（见 §13.6），怀疑还差 `sub_180BFDAA0(a3)` 的矩阵，需要时再查调用点 |
| ~~P2~~ | ~~**贴图 / UV**~~ | ✅ **已完成**（读），见 8.2 第 24 行 / REVERSE_NOTES §13.8。逐角 texcoord + 逐面 scale/axis + 材料名表都能读；笔刷 mesh 的 texcoord/normal/tangent 数组**不是**通道（通道只有 position），在 `poly+0x1240/0x1328/0x1428`，按 `poly+0x1110` 的密集序索引 |
| **P2** | **贴图轴 w 分量** | `textureAxisU/V.w` 代入 VRF 的 `uv=(dot/scale+offset)/texSize` 对不上（见 §13.8.3），含义待定；当前工具直接输出存储的 texcoord（权威值） |
| **P2** | **`CMapStaticOverlay` 的贴花实际数据** | DMX 里只有 `meshData`(编辑期 INVALID) 与 `projectionTargets`，真正的材质/渲染顺序/投影参数在**原生结构**里，未逆向（ze_surf_easy 有 13 个 overlay）。见 REVERSE_NOTES §15.8.6 |
| **P2** | **`type=34` 数组的元素宽度** | 已证实是 CUtlVector（`hiddenFlags` 实测 `count=cap=6069`，且与 `CVisibilityMgr.nodes` 数量一致 → 疑似 1 字节 bool 逐节点标志数组），但缺非空反例，故只报表头不猜。见 §15.8.3 |
| **P2** | **`CMapEntity+0x550` 游戏类对象内部字段** | 只验证过「类名 -> 游戏类对象/helper」的绑定，游戏类对象自身的字段（碰撞/伤害模型等）未展开 |
| ~~P1~~ | ~~**同步 VRF 参考仓库**~~ | ✅ **已完成**：`third_party/ValveResourceFormat` 已有完整源码（`ValveResourceFormat.slnx` + `IO/ContentFormats/ValveMap.cs` 等），§13/§14 的字段口径都据此对齐 |
| ~~P1~~ | ~~**CMapDocHistory 通用 pop**~~ | ✅ **已完成并端到端验证**：新地址 `0x1529E80`，见 8.2 第 28 行 ② / REVERSE_NOTES §15.1。往返验证 `A→undo→B→redo→C→undo→D`：A≠B / C==A / D==B 全部 PASS |
| ~~P1~~ | ~~**`cs2_entity_list` 太慢（~200s）**~~ | ✅ **已完成**：同会话实测 `limit=200` **114.12s / 34,487 次往返 → 2.35s / 3,145 次（48.6×）**。根因不是「往返 2.2ms」而是三块：① 每个子句柄一次**主线程** `call_virtual`（~31ms）② 每实体一次 `get_module`（**40ms**）③ 属性链逐字段往返。已按 ①句柄查元素表 ②属性链块读+驻留串缓存 ③树遍历单区块读 ④管道长连接 ⑤缓存基址 全部解决，见 8.2 第 29 行 / REVERSE_NOTES §15.6 |
| ~~P1~~ | ~~**`_enum_elements` 静默截断（大图漏对象）**~~ | ✅ **已修**，见 8.2 第 30 行 / REVERSE_NOTES §15.7。`limit` 原默认 8192 + `min(cap, limit)`，`ze_surf_easy`（cap=97,102）只扫 8.4% → `cs2_mesh_list` 报 338（实际 4124）、`cs2_area_query` 同一小盒命中 mesh 从 **4 漏成 18**。已改：`_enum_elements` 默认扫全表 + 批量读表；两个工具改走一趟 `_walk_elements` |
| **P2** | **大图性能（`ze_surf_easy` 级别）** | 已知且**本轮按用户要求暂不优化**。实测（繁忙会话 ~3ms/往返）：`cs2_entity_list` 全量 194.40s / 65,602 次往返；`limit=200` 也要 52.86s（**limit 不省成本**，必须先走完整棵树）；`cs2_mesh_list` 单次走树 28.16s；全量读 4124 mesh 几何 701s。优化方向：① `cs2_entity_list` 加 **early-exit**（凑够 limit 就停，标注「已提前停止」）② 树遍历**下行块合并**（元素在池里按 0x1C00 连续分配，一读可覆盖多个，预计 ≥2×）③ mesh 几何的多步读取合并（目前 ~17 次读数/mesh）。详见 REVERSE_NOTES §15.7.4 |
| ~~P1~~ | ~~**把 `cs2_entity_create` / `cs2_entity_delete` 接进 Ctrl+Z 历史**~~ | ✅ **已实现并往返验收**（2026-09-27）。新增 `_hist_push_step` / `_hist_record_object` / `_hist_notify` / `_hist_state` + 4 个 RVA 常量；create 在挂进世界**后**记「新增」、delete 在摘除**前**记「移除」，历史逻辑 try/except 包裹（失败只警告不影响操作）。**自包含往返 `A→undo→B→redo→C→undo→D` 全通**：A 在树内 / B 已移出 / C 回来了 / D 挂回（`GetParent=CMapWorld`），undo 步数 40→41→40→41→42→41。详见 8.2 第 33 行 / REVERSE_NOTES §15.10.9 |
| ~~P1~~ | ~~**删除顺带清理 Hammer 的名字/选择索引**~~ | ✅ **不是 bug，是参数约束**（用户实测判定）：outliner 里只幽灵化过 `mcp_place_test`（早期探针 `notify` 未传），而同样带 targetname 的 `del_tool_a`（工具 `notify=1` 删的）**不在**。→ **`notify=1` 会顺带把索引收拾干净，`notify=0` 不会**，工具默认 `notify=True` 本来就是对的。此约束已写进工具 docstring。见 REVERSE_NOTES §15.10.8 |
| ~~P2~~ | ~~**属性修改如何进 Ctrl+Z 历史**~~ | ✅ **已完成**（2026-09-28）：从 `AlignObjects` 的实现里挖出 Hammer 自己改对象的标准流程 = `PushStep(具名)` → `sub_18086D9B0(hist, element+0xC8, 1)` 递归登记被改节点（含子/父链）→ **然后才改**。无需新 API。`cs2_entity_set_attr` 已加 `history=True`（默认）落地，并加「值未变化不开空步」守卫；自包含往返 `create→set→map_undo→map_redo` 全通（70→69→70 步，属性 `''`↔`'probe2_v2'`）。见 REVERSE_NOTES §17.14 |
| **P2** | 非实体元素的类型化属性 | **实体参数不需要**（keyvalue 全为 AT_STRING，变换走属性 pin，见 §14）。仅 world/mesh 等非实体元素还有类型化属性；如需读写再按 §14.2 的类型码表选 `CUndoAttributeSetValueElement<T>` 对应的 setter |
| ~~P2~~ | ~~清理测试实体~~ | ✅ **已自然消失**：2026-09-27 那批测试实体都**未保存**，重启 Hammer 并重新打开 `cs_script_demo.vmap` 后已不存在（实体数 186→182、场景元素 264→260） |
| ~~**P2**~~ | ~~**笔刷顶点焊接（24 → 8）**~~ ✅ **2026-09-29 完成**：逆向出官方算子 `MergeVerticesWithinDistance` = hammer RVA `0xCD21E0` + `RemoveIsolatedVertices` = `0xCD83C0`（签名/向量布局/标志位见 REVERSE_NOTES §16.10）。新增工具 **`cs2_mesh_weld_vertices(mesh, distance=0.01, history=True)`**；`cs2_mesh_create_box` 新增 **`weld=True`（默认）**，建出来即 **8 顶点 / 6 面**。活体验收：24→8、8 个角点坐标精确、AABB 逐分量不变、undo/redo 往返干净（weld 步 8→24 可回滚；weld=True 的盒子一次 Undo 整盒删除，无中间态） |
| ~~**P2**~~ | ~~**笔刷贴图轴按面朝向拟合（贴图/UV 不对）**~~ ✅ **2026-09-29 完成**：纠正了长期误解——建面算子 `sub_180901F40` 的第 3 参**不是** 32 字节「默认贴图轴常量」，而是**每点 8 字节的 Vec2 UV 数组**（反编译 `sub_1808CAE90`：`a4 + 8*n` 逐点写进 texcoord 流）。旧代码 6 个面共用 `(0,1)(1,1)(1,0)(0,0)` → 每面各铺满一张贴图、不随世界平铺，就是「贴图和 UV 不对」的根因。改为 Hammer 默认的**世界对齐**投影：`uv = dot(主轴轴, 世界坐标)/(0.125×tex_size)`，轴由面法线主轴决定（实测 ±X/±Y/±Z 同轴），`tex_size` 默认 512 ⇒ 64 世界单位/贴图。`cs2_mesh_create_box` / `cs2_mesh_create_arch` 新增 `tex_size` 参数；验收：新建盒 6 个面的 `scale/U/V/offset` 与 UV 与**地图自带笔刷逐项一致**。见 REVERSE_NOTES §16.12 |
| ~~**P1**~~ | ~~**长驻进程读不到「刚建的对象」（元素表快照缓存过期）**~~ ✅ **2026-09-29 完成**：症状是刚建好的笔刷在世界树里（父节点/子句柄数组都正确）但 `cs2_mesh_list` / `cs2_area_query` 查不到。根因：`_dm_table()` 快照缓存键只有 `(base, 数据指针, 容量)`，而新建元素时数组**既不扩容也不换指针**（只填旧空槽）→ 长驻 MCP server 一直用旧快照，新句柄解析成 0 被跳过。修复：把 `g_CDataModel+0x80` 的**存活元素数**并入缓存键（实测建盒 13047→13048）。见 REVERSE_NOTES §19 |
| ~~**P1**~~ | ~~**`cs2_mesh_create_arch` 的 center 被叠加两次**~~ ✅ **2026-09-29 完成**：首版把 `ctr` 加进顶点坐标、又设成元素 origin ⇒ 位移翻倍，`center=(-800,-832,30)` 的拱门实际在 `(-1600,-1664,60)`。改为**顶点写本地坐标**（与 `cs2_mesh_create_box` 一致），位置只由 `el+0xA0` 承担。重建后 AABB `(-880,-844,30)~(-720,-820,222)` 与 `width/height/thickness` 完全对应。见 REVERSE_NOTES §16.11.3 |
| ~~**P1**~~ | ~~**UV 相位：建块应从网格自己的角点起算（不是世界原点）**~~ ✅ **2026-09-29 完成**：用户「方向正确但效果不太一样」→ 拿 **Hammer 手建的块** `0x5c053294000`（同材质同尺寸）逐面比对定案：轴/scale/密度（64 单位/贴图）**全对**，差的是**相位** —— Hammer Block 工具建的块 `u=(x−xmin)/64`、`v=−(y−ymin)/64`（锚在块自己的角上），而我们是世界相位 `u=x/64`，两者差**半个非整数贴图**（−13.5 张）故外观不同。改为 `u=(dot(U,世界坐标)−u_min)/k`、`v=(dot(V,世界坐标)−v_max)/k`（k=0.125×tex_size，锚点取整网格 AABB），`_dot_axis_range()` + `_face_uv_bytes(pts, lo, hi, tex_size)`。⚠ 存回值会与写入值差**整数张贴图**（Hammer 把拟合偏移对 512 取模），判据是"差整数张"而非"值相等"。见 REVERSE_NOTES §16.12.1 |
| ~~**P1**~~ | ~~**焊接后法线被改成平滑平均（盒子看着"反了/圆角感"）**~~ ✅ **2026-09-29 完成**：用户反馈「上下颠倒」，A/B 对照（`weld=True` vs `weld=False`、同材质同尺寸）定位到焊接是唯一变量；两盒 UV/轴/scale/绕序**逐项一致**，唯一差异是**每角法线** —— 官方 `MergeVerticesWithinDistance` 会把半边法线重算成顶点平均法线（方块角 `(±1,±1,±1)/√3`），而 Hammer 原生笔刷存的是**面法线**。修复：新增 `_poly_set_flat_normals(poly)`（逐面走半边环 → Newell 求面法线 → 经「密集序→handle」映射写回 `poly+0x1328` 半边法线流），在 `_mesh_weld_native()` 焊接后自动调用。验收：MCP 建焊接盒 → 24 条半边法线全为面法线，与地图自带笔刷一致。见 REVERSE_NOTES §16.10.5 |
| ~~**P2**~~ | ~~**确认世界对齐轴表（V 轴符号）**~~ ✅ **2026-09-29 完成**：从 Hammer 代码取到权威表（`sub_180AE38A0` 的 `n2_1==1` 分支，取 `qword_1821DDB10`/`qword_1821DDB60`，索引由 `sub_180AE3E60` 按主轴选）：`主轴Z→U(1,0,0)/V(0,-1,0)`、`主轴Y→U(1,0,0)/V(0,0,-1)`、`主轴X→U(0,1,0)/V(0,0,-1)`，**不看正负号** —— 与本工具实现一字不差，§16.12 的结论从「实测拟合」升级为「与 Hammer 代码一致」。见 REVERSE_NOTES §16.12 |
| ~~**P2**~~ | ~~**注入 DLL 支持浮点形参（xmm）**~~ ✅ **2026-09-29 完成**：`FnArg{bits,kind}`（kind 0 整数/1 float32/2 float64）贯通 `CallFunction/CallVirtual/CallFunctionOnMainThread`；`InvokeStub` 先写整数寄存器与栈参数，再按槽覆盖 xmm0..3（float：`mov eax,imm32`+`movd xmmN,eax`；double：`mov rax,imm64`+`movq xmmN,rax`）；IPC `ParseCallArgs` 支持 `"f:"`/`"d:"` 前缀。DLL 已重新编译（build_vs18/Release）并注入 cs2.exe PID 9360，随焊接活体验证 0.01f 阈值真实生效（不是只收到 0）。详见 REVERSE_NOTES §16.10.4 |
| ~~**P2**~~ | ~~**其它笔刷形状（棱柱 / 圆柱 / 楔形）**~~ 🚧 **2026-09-29 拱门已实现**：新增工具 **`cs2_mesh_create_arch(center, width, height, thickness, opening, opening_height, segments, material, name, weld=True)`** —— XZ 截面 U 形凹多边形沿厚度拉伸（前后端面各 1 个凹多边形 + 每条截面边 1 个条带），再走官方焊接。实测 25 面 / 138 顶点 → 焊接 **138 → 46**（= 2n，完全收敛），一次 Undo 整拱删除。<br>**关键纠错**：建面算子**接受凹多边形**，之前「凹面被丢弃」的真因是**截面退化（拱顶与墙顶相切）**，不是凸性要求（见 REVERSE_NOTES §16.11）。<br>仍待办：棱柱 / 圆柱 / 楔形，以及**带旋转**的笔刷要走官方 `vfn136`（设位置）/`vfn144`（设朝向矩阵），不能直接写 `el+0xA0` |
| **P1** | **工具系统 / 可绑定命令（Key Bindings 那套）—— `list`/`inspect`/`run` 已实现** | 用户贴 Key Bindings 截图问「原版这些功能怎么实现」。**结构全摸清（REVERSE_NOTES §17.6~§17.10）**：① `CreateInterface("ToolSystem2_001")` 返回 `CHammerApp` 单例，**对象本体在 `hammer+0x677AE50`**（首字段 = `??_7CHammerApp@@6B@`，RVA `0x1DF0130`）。② 工具类静态注册 `CBaseBindTargetDescriptor` 到全局链表（头 `hammer+0x272D898`）；描述符布局：`+0x08`/`+0x10`/`+0x18` = 名字 hash / 目标名 / 类名，`+0x38` next，`+0x40`+`+0x48` 命令数/数组，`vfn0/1/2/3/4` = 名/类/hash/计数/取命令，`sub_181303250` 把链表序列化成 `bind_targets` KV。③ **命令对象 `CBindableCommand` 分配 `0x240`**：头 `0x40`（`+0x08` 名 / `+0x10` 名 hash / `+0x18` 描述）+ **8 个 `0x40` 的 stage 块**（stage k 在 `+0x40*(k+1)`），每块一个 MSVC `std::function`（内联 functor：`+0x00` vtable / `+0x08` 成员函数指针 / `+0x10` this 调整 / `+0x18` 绑定实参；functor vtable **槽 2 = `_Do_call`**）。④ **执行 = 直接调 `pmf(ctx + adj, arg)`**（等价 `_Do_call`，全整数参数 → DLL 调用桥够用）。⑤ 绑定加载：`CQInputBindManager`（RVA `0x272E520`）读 `tools/keybindings/hammer_key_bindings.txt`，条目 80 字节（`+56`/`+72` = 命令名/上下文名 hash）。<br>**已实现**：`cs2_bind_list`（69 目标 / 1194 命令）、`cs2_bind_inspect`（只读看每个命令绑了什么 + 自动解析 ctx + stage 标签）、`cs2_bind_run`（**任意目标自动解析 ctx 并执行**；`stage` 支持 `press/drag/repeat/release/execute` 名字，留空自动优先 `execute`）、`cs2_sel`（**语义封装 61 个 feature**：对齐 / 吸附 / 钉住 / 枢轴 / Gizmo / Nudge / 网格编辑，全部落在 `ToolSelection`）。<br>**ctx 链路（§17.10）**：`CHammerApp+0x58/+0x60` = 编辑器会话数组 → `会话+0x120` = `CToolManager` → `toolMgr+0x30/+0x38` = 工具实例数/数组；工具实例的类名用 **MSVC RTTI**（`vtable[-8]`→COL→`COL+0xC`→TypeDescriptor→名字）读出，与描述符 `+0x18` 的类名匹配即可。<br>**stage 语义（§17.13）**：`5`=一次性执行（88 条 ToolSelection + 全部 76 条 HammerApp 只绑这档）、`0`=按下、`2`=拖动、`3`=长按连发、`6`=松开、`4/7` 未定、`1` 未出现；同一 pmf 的多条命令靠**命令自带的绑定实参**区分，不能自己传。<br>**实测**：`HammerApp.ToggleShowHelpers/ToggleTextureLock/ToggleTransformSpace`、`ToolSelection.EnlargeGizmo/ShrinkGizmo/SetOrientationToWorld/ClearPivot/NextPivotCycle/PrevPivotCycle/CenterPivotInView/SetPivotToSelectionCenter/GrowSelection/ShrinkSelection` 均执行成功；61 个 `cs2_sel` feature 名已全部校验存在 |
| ~~**P1**~~ | ~~**多文档（同一 addon 同时开多个 .vmap）写错文档**~~ ✅ **2026-09-29 完成**：旧代码所有写入工具默认走 `docs[0]`，导致「在建的对象不在用户看的文档里」→ 界面表现为 **outliner / 3D 视图看不到 mesh**（本会话那个问题的**真因**，不是 VisGroup 未注册），且 Ctrl+Z 历史写进另一图的栈。修复：① `_map_doc(sel)` selector（`""`=docs[0] / 数字=索引 / 其余=路径子串）—— `map_info`/`map_groups`/`map_save`/`map_undo`/`map_redo`/`area_query`/`mesh_list`/`entity_list`/`entity_create`/`mesh_create_box`/`mesh_create_arch` 全部加 `doc` 参数；② `_doc_of_element(el)`（沿 `RVA_NODE_GET_PARENT 0x864EA0` 上溯，与各文档 `CMapDoc+0x88` world 比对）—— `mesh_weld_vertices`/`entity_delete`/`entity_set_attr`/`entity_add_io`/`entity_remove_io` 用它自动定位。**活体验收（ze_surf_easy=doc0 / untitled_2=doc1）**：两文档栈独立（8 步 / 56 步，历史对象各异）；`create_box(doc="1")` 父节点 = untitled_2 world、历史 55→56；`area_query(doc="1")` 命中新盒而 `doc="0"` 0 命中；`map_undo/redo(doc="1")` 56↔55 往返且 doc0 恒为 8 步；**用户界面确认 untitled_2 的 outliner / 3D 视图能看到该盒** ✅。见 REVERSE_NOTES §18 |


### 8.4 工作方式约定（用户明确要求）

* **MCP 必须走底层**：直接调用 `hammer.dll` 内部函数/虚函数，**不要用快捷键、坐标点击等 UI 手段**。
  UI 自动化脚本只作为**测试夹具**时备用。
* **有新进度就写进 md**（本文件 + REVERSE_NOTES.md）。
* 已加载可用：**Cheat Engine**（`cheatengine-x86_64-SSE4-AVX2.exe`，pid 会变）与 **Computer Use MCP**。
  需要**其他 DLL 的 IDA MCP**（pet.dll / particles.dll 等）时提前提出来，由用户添加。


## 10. 2026-10-12 Hammer 优先：实体 mesh 检查与范围查询

- 新增 `cs2_entity_get_meshes(entity, limit)`：按实际子树列出实体拥有的 CMapMesh，支持中间 group，排除嵌套实体的几何；区分无 mesh、几何未就绪及读取失败。
- 修复 `cs2_area_query` 对带 mesh 实体只按 origin 筛选的漏报：现在逐个检查所拥有 mesh 的 AABB；任一相交即命中。只有无 mesh 时回退到 origin。
- `trigger*` 仍归 trigger；其他实际有 mesh 的实体归 brush；保留无 mesh 的 `func_*` 分类。
- `cs2_entity_create` 文档明确：创建 func_button/func_brush 只生成实体节点，不自动生成或绑定 mesh。带笔刷创建/挂接仍待实现，不能宣称已完成。
- 测试：`python tests/test_entity_meshes.py`，8 项通过；Python 语法检查通过。
- 尚未进行本轮实机验证：检查时 CS2 未运行，配置中的 Hammer IDA MCP 13331 端口未监听。MCP 常驻服务需要重启才能加载 Python 修改；无需重编注入 DLL。


### 2026-10-12 活体补验与 mesh 挂接工具

- 启动必须用既有交互任务 `schtasks /run /tn HammerLaunch`；受限 shell 直接启动曾仅出现 Stall Detected/残留进程，并未打开编辑器。清理本轮失败进程后通过任务成功打开 Asset Browser。
- 桥接注入后定位 Hammer 按钮并调用 Qt click；确认 hammer.dll 加载，新建测试文档 untitled_3（本轮测试不修改其他地图）。
- 实测 func_button 创建成功但 mesh=0。创建盒形 mesh（8 顶点/6 面，中心 128,0,0），调用实体 vfn456 挂接成功；父节点 world -> entity。
- 新增 `cs2_entity_attach_mesh`：类型校验、严格文档归属（禁止 docs[0] 回退）、跨文档拒绝、循环校验、重复操作不压历史、修改前 `_hist_record_node` 快照、挂接后父节点与 children 复核。
- 挂接撤销 world <- entity，重做 world -> entity 已实测；origin=(0,0,0) 的实体在范围 (120,-8,-8)~(136,8,8) 中因 mesh 相交正确命中。ping 始终正常。
- Hammer IDA MCP 当前实际端口 13340，配置中 13331 已过期；13337 是 met。该 IDA 数据库是旧版，虚表需用库内旧地址；执行使用运行时虚表，不硬编码旧函数 RVA。
- 变换采用 Hammer 原生挂接语义；非默认旋转/缩放父节点的坐标语义仍待进一步验证。不宣称已完成带 mesh 的单步骤实体创建。


### 2026-10-12 Brush entity automation

- Added cs2_entity_create_brush: validates inputs, supports dry_run, creates entity + box mesh + native attach, verifies document/classname/ownership, returns structured steps and partial addresses on failure. No automatic retry, rollback or save. Three native Undo steps.
- Live untitled_3.vmap test: func_button at (256,0,0), size 32; owned mesh=1, vertices=8, faces=6, AABB=(240,-16,-16)-(272,16,16). Test creation undone, undo history restored to 3; no save.
- Live test exposed missing names argument to _entity_get_attrs; fixed and reverified. Existing 8 tests pass; MCP tools/list now 62.


### 2026-10-12 Rebuild in C:\codex\cs2_tool_mcp

- Copied current source, uncommitted feature work, tests and Git history from C:\cs2_tool_mcp. Original directory retained.
- Added build.ps1 (VS discovery, x64 configure/build), requirements.txt, start_mcp.cmd, mcp.json and README.md. Made bringup root relative and default injection use the root DLL.
- Built Release with MSVC 19.51 and CMake 4.3.1. Verified AMD64 PE and matching root/build DLL bytes.
- 10 unit tests passed; actual MCP stdio initialization, 62-tool listing and cs2_entity_create_brush dry_run passed. New DLL has not been injected into the running editor.


### 2026-10-12 MCP architecture refactor

- Replaced the ~6000-line server with the hammer_mcp package. The legacy entry is 26 lines and delegates imports through compat.py. Protocol/transport/session/runtime, offsets, DMX/scene/history/geometry, domain operations, automation and MCP registration now have explicit boundaries and acyclic dependencies.
- FastMCP is imported only by app.py; registry.py explicitly lists the existing 62 tools. Saved the pre-refactor full tool schema and verified names, descriptions, input/output schemas remain identical.
- BridgeSession owns the connection and all process-specific caches. Connections and explicit initialization invalidate module, symbol, element-table and Qt caches. A session serializes whole tool operations. Transport validates frames/IDs and never replays requests after ambiguous failures.
- Added EditResult for create_entity/create_box/attach_mesh. Automation consumes addresses and statuses directly, pins the selected document, and preserves partial addresses. Public report wrappers and native multi-step Undo remain compatible.
- Migrated VM client away from fake FastMCP injection; RVA maintenance scripts target offsets.py. Smoke tests now return failure for tool errors, including structured ok=false responses.
- Validation: 23 tests passed; full 62-tool contract match; real MCP stdio ping/map listing/dry-run succeeded; negative smoke call returns exit 1; module dependency and unresolved-global checks passed.
- Live untitled_3.vmap verification: func_brush with a 32-unit box at (512,0,0), owned mesh=1, vertices=8, faces=6, AABB=(496,-16,-16)-(528,16,16). Three test Undo steps restored the world child count and history depth. No save; native bridge binary unchanged for this refactor.
- Architecture and extension guide: ARCHITECTURE.md.


## 2026-10-12 — Block Tool 形状与焊接后 UV

- 新增 `cs2_mesh_create_primitive`，覆盖截图中的 `block` / `quad` /
  `cylinder` / `spike` / `sphere`。它们都创建真正的 CMapMesh；
  `quad` 为 XY 单面，其余为闭合网格。圆周分段与球体纬向分段可调。
- 定位到新的 UV 错误：`CreateFaceLocalFromPoints` 写入的逐角 UV 正确，
  但 `MergeVerticesWithinDistance` 焊接后会重新计算它们。现在焊接后按
  面与顶点位置恢复逐半边 texcoord；盒、棱柱、拱门及新形状共用这一修复。
  圆柱/尖锥侧面按周长连续展开，球体按经纬展开。
- 实测创建并立即一步 Undo：盒、quad、cylinder、spike、sphere、棱柱、拱门。
  盒焊接后首面 UV 为 (0,0)/(0,-1.5)/(1,-1.5)/(1,0)，与输入一致。
  28 个单元测试和 MCP stdio 工具清单检查通过（64 个工具）。

## 2026-10-12 — 其他 DLL 的接口发现

- `scenesystem.dll`、`tier0.dll`、`particles.dll` 当前安装版本都导出
  `CreateInterface`，入口开头均为 `4C 8B 0D disp32`，可复用桥接层的
  `s_pInterfaceRegs` 链表头解析。
- `module_interfaces` / `module_get_interface` 现可接收任意**已加载且导出**
  `CreateInterface` 的 DLL 名。只按当前进程的模块表解析，不加载用户路径；
  动态链表头还需落在模块映像内且可读。ToolSystem / bind 目录仍只用于
  hammer、met、modeldoc_editor、pet 四个编辑器 DLL。
- C++ Release 构建成功；Python 28 项测试与 MCP stdio 工具清单通过。
  本轮无运行中的 cs2 进程，新增跨 DLL 路径尚未做进程内读回验证。

## 2026-10-13 — 其他 DLL 接口实机验证

- 将当前构建的 `cs2_tool.dll` 注入运行中的 CS2/Hammer 进程后，桥接层 ping 返回 `initialized=true`。
- `module_interfaces` 从已加载模块读回：`tier0` 4 个接口（含 `VEngineCvar007`）、`scenesystem` 3 个（含 `SceneSystem_002`）、`particles` 1 个（`ParticleSystemMgr003`）、`hammer` 1 个（`ToolSystem2_001`）。
- `module_get_interface` 对 `SceneSystem_002`、`VEngineCvar007`、`ParticleSystemMgr003` 均返回 `return_code=0` 且指针非零。新增的跨 DLL 发现路径已通过进程内验证。
- 同一桥接路径继续覆盖 24 个已加载的运行时/工具 DLL，共读到 93 个注册接口；包括 `engine2` (34)、`filesystem_stdio` (2)、`materialsystem2` (5)、`networksystem` (4)、`client` (9)、`server` (10)、`assetsystem` (2) 等。`HostStateMgr001`、`VFileSystem017`、`SchemaSystem_001`、`VMaterialSystem2_001`、`MeshSystem001`、`AssetSystem001`、`ToolFramework2_002` 的 CreateInterface 调用均返回非零实例和成功码。


## 2026-10-13 — Hammer IDA 接入、ModelDoc 与粒子编辑器操作

- Hammer 的 IDA 批处理分析库已生成；IDA MCP 在 13331 端口提供 66 个工具。tier0 的 13334、scenesystem 的 13332 也已实机连通。
- ModelDoc 与 Particle Editor 的 App 会话数组均使用 `+0x58` 计数、`+0x60` 指针数组，`+0x50` 指向当前会话。新增 `cs2_editor_sessions`，以所属 DLL 的 MSVC RTTI 校验会话类名后返回活动会话；`cs2_bind_run` 对 `ModelDocEditorSession` / `PetSession` 自动取得上下文地址，不再要求用户手填指针。
- 新增 `cs2_modeldoc_action`（18 个命名操作）和 `cs2_particle_editor_action`（15 个命名操作），覆盖模型导入、文件操作、变换模式、撤销/重做、粒子预览与模拟控制、函数/子节点操作。空 action 列出可用项；默认只预览，`confirm=True` 执行。33 个映射均在已加载 DLL 中验证存在真实绑定。
- ModelDoc 活动会话 RTTI 为 `CModelDocEditorSession`，执行 `SetManipulationMode_Selection` 成功；Particle Editor 打开后新建未保存文档，活动会话 RTTI 为 `CPetSession`，空文档执行 `Undo` 成功且会话保持。MCP stdio 实机预览与工具清单通过（67 个工具）；34 项 Python 测试通过。

# 2026-10-13 — 参考文件式地图 MCP 的检查流程

- 参考 [Rmgs123/cs2-map-mcp](https://github.com/Rmgs123/cs2-map-mcp) 的 `check_map` 与“修改—检查”流程，但保留本项目的实时 Hammer 文档架构。
- 新增 `cs2_map_check`：只读扫描当前地图的实体、mesh 和名称，报告缺失笔刷几何、空/未就绪 mesh、非法坐标和重复 targetname；读取故障返回 `ok=false`，不会误报地图干净。
- 37 项单元测试通过。检查工具使用严格场景遍历，读取故障不再被忽略。实机桥接可连通，但当前 Hammer 没有打开地图文档（`count=0`），因此本轮无法做地图内容验证。

# 2026-10-13 — ModelDoc / Particle 源素材树查询

- ModelDoc 与 Particle Editor 会话仍在线，分别验证有 1 个活动会话。当前 bind 操作已经覆盖会话命令；本轮转向节点和属性数据。
- 新增只读 `cs2_asset_tree`，解析保存后的文本 KV3 `.vmdl` / `.vpcf`，支持按 `rootNode.children[0]`、`m_Operators[0]` 等路径查询节点、标量属性、粒子函数、子粒子引用。明确标注它不包含编辑器里未保存的改动；二进制编译资产不支持。
- 39 项单元测试通过；实际 CS2 content 目录抽查 25 个 `.vpcf` 和 10 个 `.vmdl`，全部解析成功。MCP stdio 实机调用 `cs2_asset_tree(m_Children[0])` 读回子粒子资源引用成功（69 个工具）。后续仍需逆向编辑器会话内存和可写节点 API，以支持未保存状态及可靠修改。

# 2026-10-13 — 编辑器内存中的活动文档和根对象

- ModelDoc 活动会话 `+0x118` 指向 `CModelDoc`，文档 `+0x3C0` 指向 `CModelDocRoot`；Particle Editor 活动会话 `+0x108` 指向 `CPetDoc`，文档 `+0x80` 指向 `CPetRootNode`。两条链路的每级都以所属 DLL 的 MSVC RTTI 实机验证。
- 新增只读 `cs2_editor_document`，返回活动会话、文档和根对象地址与验证后的类名，能定位未保存文档；尚未声称读取根节点的子元素或属性。
- 40 项单元测试通过；MCP stdio 对 ModelDoc、Particle Editor 两个活动文档的调用均返回 `ok=true`（70 个工具）。

## 2026-10-13 — 创意工坊模型导入 ModelDoc

- 已安装的创意工坊地图 3600074056 中含 `models/prop_livehouse/live_house_counter.vmdl_c`。本机 Source 2 Viewer CLI 20.0 将它导出为几何 GLB，以及文本 `.vmdl` 与 DMX mesh；后两者已放入当前运行的 `test` add-on 的独立 `models/codex_workshop_probe/workshop_3600074056/` 目录。
- 逆向 ModelDoc 的 FileOpen 绑定确认：文件对话框选择路径后调用 `CModelDocEditorApp` 虚表 `+0x90`，参数为 UTF-8 路径及标志 `1`。新增 `cs2_modeldoc_open`，对 add-on 路径和文本 KV3 预检，默认预览，明确确认后在主线程调用原生方法并读回活动会话、文档及根对象。
- 实机打开该 Workshop 模型后，ModelDoc 窗口标题变为 `live_house_counter`，返回会话 `0x4ad31967c00`，文档和 `CModelDocRoot` 的 RTTI 读回成功；42 项单元测试通过。当前根对象 `+0x10` 的子节点计数仍为零，故尚未宣称完成未保存节点枚举或模型编译验证。
- S2V CLI 20.0 解析该包的 `white_s.vmat_c` 时因当前 CS2 着色器版本 72 超出其 59–71 支持范围而失败。几何已导入，但材质仍需兼容的导出/重建路径。

## 2026-10-13 — ModelDoc 模型编译闭环

- 通过 S2V CLI 的 DATA 块确认缺失材质是 `csgo_complex.vfx`、纯白色颜色贴图和背面/自发光设置；单独提取其 1×1 颜色 PNG，在活动 `test` add-on 内重建最小 `white_s.vmat`。这份本地测试材质并非原材质的完整还原。
- CS2 自带 `resourcecompiler.exe` 第一次明确报缺失材质；补齐后 `live_house_counter.vmdl` 连同材质/纹理编译成功：1 compiled、0 failed。编译后的 `.vmdl_c` 存在，S2V CLI 读回 Model、MVTX/MIDX/MDAT 块和材质引用。
- 新增 `cs2_asset_compile`，允许对 add-on 中单个 `.vmdl`、`.vmat`、`.vpcf` 做默认预览、确认编译与产物检查，不执行上传；44 项单元测试和实机已编译模型调用通过。ModelDoc 内部根节点计数仍未验证出实际子节点，继续只读逆向。

## 2026-10-13 — ModelDoc 新会话复验与交接文档

- 用户亲自关闭 ModelDoc 后，MCP 读到 `sessions: 0`。重新用已验证的 `cs2_modeldoc_open` 打开编译成功的 Workshop 测试模型，获得新会话、`CModelDoc` 和 `CModelDocRoot`；新根对象 `+0x10` 低 32 位仍为零、`+0x18` 为零。这排除了旧会话未刷新作为零计数的原因，但并未找到真实实时子节点容器。
- 新增 `CURRENT_STATE.md`，集中记录仓库/工具入口、实机验证、局限和下轮步骤，以免上下文压缩后重复调查或误把源文件树当成未保存的实时树。

## 2026-10-13 — 下载目录角色模型检查

- 检查 `character_template.zip`、EarthGovSol 和 Neco Arc 的源码/编译包；五个 ZIP CRC 通过、无路径穿越项。源码 `.vmdl` 均为 ModelDoc41；各包的内部 `agents/...` 引用按 Windows 大小写规则可在包内找到。
- 将 Neco Arc 与 EarthGovSol 源文件仅复制到本地 `test` add-on，两个主模型经 CS2 编译器强制编译均返回 1 compiled、0 failed；用 MCP 原生路径打开后读回有效 ModelDoc 文档与根对象。源树分别有 14/16 个根子项，而实时根对象 `+0x10/+0x18` 仍为零，进一步说明这里不是源节点容器。
- 详细包清单、路径和验证边界已写入 `DOWNLOAD_MODELS.md`；第三方模型文件未提交到仓库。

## 2026-10-13 particles.dll 函数目录

运行时注册表 + Schema 解析确认 376 个函数、395 个类。已接入两个只读 MCP 查询工具，记录全部类别、类名、参数类型、友好名与继承；详见 [`PARTICLE_FUNCTIONS.md`](PARTICLE_FUNCTIONS.md)。测试 47 项通过；实机注册表七组计数一致。下一步逆向 Pet 未保存树的节点属性和原生撤销/写入 API。

## 2026-10-13 — Pet 原生打开与非空实时树

IDA 确认 `PetApp.FileOpen` 回调 `pet+0x4203B0` 在选择文件后走 App 虚表 `+0x90(path,1)`。原生打开 `test/particles/spotlight_cone_test.vpcf` 后，Pet 会话从 1→2，第二会话的 `CPetDoc`/`CPetRootNode` RTTI 读回成功。实时九组计数 `1/0/2/2/0/0/1/0/0` 与 `.vpcf` 一致，六个函数节点都是 `CPetFunctionNode`，虚表 `+0x90` 类名与源文件顺序一致。新增 `cs2_particle_editor_open` 和 `cs2_particle_editor_tree`；49 项测试通过。继续追踪函数节点属性对象与未保存状态差分，然后验证原生撤销写入。

## 2026-10-13 — 完整粒子 API/参数导出

新增可重复生成的 `PARTICLE_API_REFERENCE.json`，将 376 个注册函数逐条展开为内部类名、分组、继承链、Schema 参数名/类型/编辑器标签/注解。共 9,467 条按函数展开的参数记录，其中 376 条带 `MPropertySuppressField` 并单独标记，避免误认为必然可编辑。生成脚本在 `scripts/export_particle_api_reference.py`；50 项测试通过。

### 2026-10-13 本地：Particle Editor 实时参数只读接口

新增 `cs2_particle_editor_value(category,index,field)`，通过当前 Pet 会话/函数节点的内嵌 KV3 查询 Schema 字段及嵌套路径；含 DLL PE 版本校验、容器边界和 RTTI 检查。实机对照测试粒子读回输出字段 7、输入字面值 1.0、控制点向量 [1000,0,0] 和纹理路径；53 项测试通过。没有执行粒子写入，也没有验证未保存改动或 Undo/Redo。功能仅留本地，未推 GitHub。详情在 `PET_DLL_OFFSETS.md`。

### 2026-10-14 本地：粒子实时/保存值对照与属性历史追踪

新增只读 `cs2_particle_editor_compare`，对照 VPCF 同组同索引同类节点的叶属性；随后加入 session+0x58 源路径核对，两会话路径偏移已读回，集成后实机复测因进程离线待补。实机三个值与保存文件一致；55 项测试通过。IDA 确认 `CPetKV3PropertyDomain` 的改动前回调会以 `Set %s` 经 `CPetDoc` 历史对象建立快照，改动后回调另发通知。值设置调用约定尚未确认，未运行任何写入或撤销。仅本地保存，不推送。详见 `PET_DLL_OFFSETS.md`。

### 2026-10-14 本地：MET 材质编辑器静态入口

用户要求接着推进 MET。DLL 与副本 SHA 一致；旧 IDA 数据库报损坏，保留原件另建干净数据库。定位 CQMaterialEditor 当前材质候选指针 +0x238、路径/Shader/开关/变量集合及序列化。MET 全部仅静态分析，CS2 进程不在线，未声称实机读写；详情在 MET_DLL_OFFSETS.md。

### 2026-10-14 本地：VRF 源码参考索引

对照 376 项目录生成 153 个源码实现关联（146 模拟、7 渲染），所有关联文件存在，记录来源 HEAD 与文件哈希。Shader 参数描述含默认值/范围/显隐表达式，版本检查接受 VCS 72；未构建运行。说明见 VRF_REFERENCE_NOTES.md，README 已补来源链接。无新增实时写入能力，未推送。

### 2026-10-14 分模块 MCP 与 IDA 固定端口

新增六组 MCP scope、跨进程事务互斥及固定端口表 13341–13347，保持 all 旧工具契约。58 项测试及六组 stdio 验证通过；七个 IDA 数据库保存端口，Pet/MET 两个 HTTP 端点在线且数据库身份正确。Codex/Trae 配置已同步，保留私人备份，未推送。详情在 MCP_MODULES.md。

### 2026-10-14 修正为 DLL 归属

用户指出 Hammer 本身含粒子功能，不能按功能分组。新增显式工具主归属清单，拆为 hammer/pet/particles/met/modeldoc_editor/scenesystem/tier0 和辅助 bridge。Hammer 粒子实体设置保留，Pet 文档与 particles.dll 目录分开。移除功能式客户端别名，保留私人备份及原 IDA 端口。59 项测试、八组实际 stdio 验证通过，未推送。

## 2026-10-14 本地：Soundevent 单文件参考

新增 [SOUNDEVENT_REFERENCE.md](SOUNDEVENT_REFERENCE.md)：208 份 core/csgo 声音资源全部解析，VPK CRC、KV3 缓冲与类型流校验通过，0 失败；251 个声音栈、138 种实际出现的操作函数、1393 条按栈展开的 public 参数。包含写法示例、声明类型、默认值、编辑条件、底层函数字段与资源指纹。底层完整注册签名、未出现字段和输出类型仍需 soundsystem.dll 反射；尚未编译或播放。生成脚本与原始分析数据在 C:\cs2_tool_mcp，仅保存在本地。目录与 Markdown 结构核对通过，敏感信息模式扫描 0 命中。

## 2026-10-14 GitHub 上传准备

用户要求检查并准备上传。本轮 59 项测试、八组 stdio 验证、受控文件及此前 6 个未推送提交敏感模式扫描通过，无第三方资产或私人配置候选；已整理本地提交。详情见 [GITHUB_UPLOAD_CHECK.md](GITHUB_UPLOAD_CHECK.md)。本轮未执行 push；实际上传前需重新核对远端状态。自动化保持暂停。

### 2026-10-14 GitHub 上传完成

用户指示继续后 fetch 无远端新增，7 个本地提交通过普通 push 成功，ls-remote 确认 master 为 77673ae6c727d01c597762caa62ade89dc18b0fd。没有上传第三方资产或私人配置；上传结果已记录到交接与检查文档。

## 2026-10-14 Codex 配置与自动任务

补充两个工作目录的 .codex/config.toml，规范全局八组CS2服务路径与工作目录并保留无关设置，实际配置启动验证通过。公开模板 config/codex.example.toml，私人配置已忽略。目录历史命名与功能缺口见 CODEX_SETUP.md；未把共享源码包误称为物理DLL目录重构。Pet/MET IDA在线且身份正确，其余按需启动。用户要求后恢复 cs2-mcp-10-14 每两小时任务，截止北京时间今晚23:59；后续自动改动仅保留本地。

### 2026-10-14 粒子基础属性只读工具

恢复工具模式桥接，保留原有未保存会话，在独立测试粒子中验证源路径对照。新增cs2_particle_editor_root_value，读取最大粒子数、半径、颜色、边界及有界数组路径。62项测试、八组stdio和真实MCP调用通过，工具归pet.dll。属性域原生设置候选与上下文约束已记录到PET_DLL_OFFSETS.md，未执行写入或Undo/Redo，仅本地保存。

## 2026-10-26 持久构建与产物校验（本地）

新增工程配置、VPK产物校验及build start/status/cancel共五个bridge工具；现84工具、72项测试通过，八组stdio通过。真实快速构建、启动客户端退出后的持续执行/重连查询、真实取消及进程树退出均已验证。初版worker继承MCP父Job导致中断，已修复并加回归测试。源码哈希冲突、安装输入哈希、退出0缺产物及完整模式缺光照均阻止成功判定。完整构建实测因VMware显卡不支持VRAD3光线追踪失败，未将快速构建冒充完整验收。详细使用、任务ID、证据与边界见BUILD_WORKFLOW.md；完整目标见WORKFLOW_GOAL.md。旧自动任务保持暂停，私人配置已忽略，没有提交或推送。

### 2026-10-26 版本/会话自检与原生调用校验

新增cs2_session_selfcheck，源码85工具、bridge36；77项测试及八组stdio通过，VS18 x64 Release桥接编译通过。桥接v0.2.0加载时仅启动IPC，不自动初始化旧偏移；ping增加版本/API/协议/PID/addon/启动地图，未暴露完整命令行。Python按命名管道服务端身份枚举加载模块路径、磁盘SHA及加载PE头，版本/代码/模块/evidence不匹配时在发送原生请求前拒绝。桥接另要求每请求兼容attestation，实测应用中未重载的旧MCP写工具也被桥接拒绝。独立工具模式实例只读验证成功，最终报告C:\CS2_Temp\mcp_version_stdio_report.json。没有兼容profile，不自动批准当前哈希；当前原生写入仍不可用，活动地图/脏状态和允许版本往返写入验证尚待完成。详见VERSION_SELFCHECK.md；未提交或推送。

### 2026-10-26 流式VPK检查

去除整包载荷常驻内存及旧256/512MiB载荷上限，CRC和SHA按1MiB扫描；分卷/预加载全部校验，存储文件变化拒绝，worker在校验阶段可取消。真实地图测试发现并修正CS2新签名头长度与合法空DATA地图根的误拒绝，未将结构解析冒充RSA验签。513MiB样例峰值分配低于16MiB；82项测试通过。真实stdio复测有光照包与快速无光照包，release_ready仍false。详情BUILD_WORKFLOW.md；未推送。

### 2026-10-26 保存后地图FGD/I/O检查

新增cs2_map_io_check归Hammer，使用独立磁盘副本、安装版dmxconvert及FGD include/继承，检查静态目标/过滤器、已知输入类型、连接时序与maker的info_target模板覆盖工程策略。真实stdio读取21实体/2连接、7份FGD/469类，0错误/2个未声明警告；源文件未变化。脚本回调/参数语义、prefab展开、运行目标及未保存状态明确未覆盖，coverage_complete/release_ready保持false。88项测试、八组stdio通过；86工具（Hammer50/bridge36）。UI截图及键盘菜单后的文本观察仍不可靠，未冒用静态dirty候选开启写入。详见MAP_IO_CHECK.md；未提交、未推送。

### 2026-10-26 Qt hook 审查
用户报告CE崩溃并允许直接hook Qt；待决工具均返回连接失败。检查现有主线程派发，记录窗口线程选择和超时栈请求生命周期风险，未将风险认定为CE崩溃原因。QT_HOOK_NOTES.md记录后续实现和验证顺序；本轮仅文档更新，无编辑文档修改、重启或推送。

### 2026-10-26 派发超时生命周期修复
修复栈请求/event和RPC字符串在超时回调期间提前释放风险；在途请求不会被覆盖，执行结果未知禁止重试。增加实际WH_GETMESSAGE独立原生测试，排队取消、运行超时、忙拒绝、延迟释放及后续自检通过；88项Python测试通过。DLL编译成功但复制因旧DLL被CS2锁定失败，未部署、未宣称游戏内验证；Qt线程识别仍待完成。

### 2026-10-26 桥接产物原子部署
移除构建后直接覆盖DLL，改为哈希校验产物留存与同目录原子替换，仅锁冲突标记等待部署。真实锁定文件保留旧内容、解锁替换、首次安装、篡改拒绝与临时文件清理测试通过。实际构建部署磁盘文件成功，未更新运行模块；MCP连接与写入拒绝复测通过。地图依赖发布和Qt点击仍待完成；未推送。

### 2026-10-26 Qt窗口线程候选验证
只读枚举实际CS2原生窗口，确认Qt5152QWindow类及独立watchdog线程。派发改为唯一Qt窗口线程，歧义或已加载Qt但无候选时拒绝；非Qt宿主也不再随意选首线程。真实Win32测试以模拟Qt类名覆盖唯一/歧义/恢复，生命周期测试继续通过。Release构建/磁盘部署成功，运行桥接未更新，控件点击仍未完成。

### 2026-10-26 新派发游戏内验证
核对旧隔离实例身份和无编辑器模块后重启并普通注入新桥接；加载PE与磁盘一致。内部固定自检成为诊断白名单，跨线程返回值实机通过，写入拒绝也通过；89项Python测试通过。新增--verify-dispatch复现参数。中间一次候选发现status2，未执行目标，随后固定自检复测通过，未掩盖暂时失败；详见QT_HOOK_NOTES.md。未推送。

### 2026-10-26 Qt控件只读MCP
新增cs2_qt_widgets归bridge，固定导出适配器在Qt线程枚举、读取objectName与按钮文字，校验支持的Qt ABI并管理QString/QList释放及超时上下文。实际stdio读取337控件，定位Hammer (Map Editor)文本；启动早期无Qt窗口返回status2，未猜测线程。87工具/bridge37，91项Python、原生清理/派发测试与Release构建通过；尚无点击/编辑。详见QT_HOOK_NOTES.md，未推送。

### 2026-10-26 Qt点击启动Hammer
新增固定Qt编辑器启动工具，默认预览、唯一完整文字匹配、可见/启用校验、同线程立即点击、模块已加载不重复点击。实际stdio启动Hammer并独立读回模块/控件变化；原生写入拒绝保持有效。88工具/bridge38，93项Python、原生测试与Release构建通过。只读证实当前CHammerApp存储候选及旧地址无效，但非空会话/dirty仍未验证。未打开地图，未推送；详见QT_HOOK_NOTES.md。

### 2026-10-26 外部Qt文本参考
读取用户指定翻译仓库，新增离线flat/rich文本表加载、双向精确候选与快照注释；不修改观测文字或定位地址，保存表SHA和来源。实测10个按钮有候选；保留重复翻译及语义不准确边界。导出审计发现itemize/translate两个采集点在本机不匹配，未安装或注入外部代码。95项测试通过，MCP工具数不变，详情QT_TEXT_REFERENCE.md；未推送。

### 2026-10-26 Hammer只读布局观察
核对被中断探针的实际输出，确认dirty全局指针应先解引用；新增SHA/加载PE/App虚表校验、有界候选结构解析和重复读取比对。真实stdio返回空会话/空dirty分组，状态保持unknown且禁止写入，不宣称非空文档/原子快照验证。89工具/Hammer51，98项测试通过；未推送，详见HAMMER_DIRTY_ANALYSIS.md。

### 2026-10-26 discover_out采集审查
逐行分析用户58MB采集，发现Hook ID与元数据有13163条冲突，修正初步按ID归属造成的误标风险。新增按记录fn/mod归组的离线分析器，保留冲突/输入SHA及采集边界；325个粒子名字均有文本观察，未误称完整参数API。99项测试通过，89个MCP工具不变；未注入、未推送，见QT_DISCOVERY_REVIEW.md。

### 2026-10-26 Qt菜单查询
新增只读Qt主窗口菜单查询，真实stdio读回Hammer148个动作，发现Open文字包含快捷键tab后缀，已修正匹配归一化并通过原生测试。90工具/bridge39，100项Python测试及Release构建通过。排队Open实验代码尚未执行，最新归一化构建未加载，未打开地图。QAction enabled不能作为命令可用证据；详见QT_HOOK_NOTES.md，未推送。

### 2026-10-26 排队Open及隔离编辑副本
加载新桥接后固定Qt排队File/Open，辅助功能实际观察到原生文件对话框，管道在模态期间仍可自检。新增按工程配置创建唯一隔离地图/项目配置脚本，实际复制hash验证通过。电脑操控路径设置/点击失败，未输入/提交路径，尚无非空文档；实验IPC未冒称公开MCP或地图打开能力。保留模态，后续Qt选择接口；未推送。

### 2026-10-26 实际地图路径与非空文档校验
部署前检测到cs_script_demo非空文档，取消重启并保留窗口。新增Session/Wrapper/Doc主虚表+RTTI与路径读取，selfcheck独立返回实际地图，与配置默认分离；保持dirty未知和写入拒绝。真实stdio与窗口标题吻合，103项测试及原生测试通过。Qt原生文件选择实验已编译并测清理，尚未加载或实测；不得误称地图自动打开成功。详见HAMMER_DIRTY_ANALYSIS.md/QT_HOOK_NOTES.md，未推送。

### 2026-10-26 修复服务器线程自动初始化遗漏
ServerThread在入口修复后仍直接Initialize，现已移除，桥接v0.2.1。以预加载fake hammer+真实独立管道验证启动/ping/无凭据initialize拒绝后工厂调用始终0；原生派发、103项Python测试和Release构建通过。发现Stop无静默屏障，不以其返回为热卸载依据；保留当前游戏v0.2.0及文档，未部署新版本。此前默认启动纯诊断的描述已在BRIDGE_BOOTSTRAP.md纠正；未推送。

### 2026-10-26 用户新采集目录的菜单文字
读取cs2_tool_trans/collect/discover/out/discover_out，确认主calls与旧副本SHA相同。以历史结构化菜单快照交叉匹配，输出10菜单119非空项的MD/JSON及快捷键/采集函数；全部有相同Qt文本，但不把命中当作控件上下文或动作授权。当前管道不在线，保留离线/历史标签；新增提取脚本实际运行及语法检查通过，未改动游戏、未推送。

2026-10-26：新增编辑预检持久基线和领域差异报告，检查配置/源码读取竞争及期望哈希；106测试通过，实际MCP离线失败路径验证。批量执行/dirty语义/回滚仍未完成，详见EDIT_PREFLIGHT.md。

2026-10-26：批量属性预览进入Hammer MCP；实际地图targetname变更只生成计划，executed_count=0。转换前后预检、原图哈希和持久报告验证通过，108测试。实时修改与撤销仍待后续证据。

2026-10-26：v0.2.1启动修复实机部署验证；隔离地图打开失败具体定位到原生文件名字段，目录导航修正已实测，但selectedFiles仍失败。保留明确失败而不绕过读回，详细证据QT_HOOK_NOTES.md。

2026-10-26：修复Windows原生选择器嵌套文件名控件与路径写入，隔离地图首次经自动打开并通过真实MCP路径/RTTI验证；同一工程两次预检matched，原始文件不变。原生相关测试通过。批量写入与撤销验证未完成。

2026-10-26：隔离地图删除/Undo/Redo/保存往返与磁盘内容实测；旧哈希MCP预览明确拒绝。dirty新增直接文档正向变化证据，空列表不证明clean。完整回滚比较仍失败/待证，详见EDIT_CYCLE_VERIFICATION.md。

2026-10-26：编辑往返后类型化节点/网格比较接入MCP，并用同一隔离地图完成快速构建/打包/产物验证。children顺序和metadata差异仍明确阻断完整回滚，114测试通过。

2026-10-26：实机确认VConsole2长包边界与PID绑定echo，接入bridge MCP；实际map加载失败已记录，不能将回显或构建成功等同加载成功。平面快照使用独占创建防碰撞，120测试，下一步工程显式运行安装/挂载验证。

2026-10-26：编辑后快速构建已实际加载游戏并独立MCP核验地图/世界坐标，新增显式运行暂存与固定查询工具。相对路径根因仍待查；发布资源、光照、通用批量回滚和其他运行诊断未完成，124测试。证据RUNTIME_VALIDATION.md。

2026-10-26：运行加载已收进start/status MCP，跨stdio客户端恢复状态和重复请求不重发实机通过。129测试；全目标仍缺完整光照、通用批量回滚、依赖闭合和更多运行诊断，见RUNTIME_VALIDATION.md。

2026-10-26：RERL静态递归依赖检查接入MCP，实际构建引用图与选中资源CRC验证通过；未知/歧义/预算不足分别报告，完整发布覆盖不作成功。132测试，证据BUILD_DEPENDENCIES.md。

2026-10-26：保存后脚本I/O AST检查接入现有Hammer工具；6项新增测试和真实MCP隔离地图/SDK脚本验证通过，总138项测试。虚拟vjs映射、受限相对导入、输入名称匹配、语法错误及动态不完整边界见MAP_IO_CHECK.md；不执行脚本、不宣称运行注册完成。保持本地。

2026-10-26：脚本检查追加边界修正及真实MCP负例（错入口/语法错误/缺Node），新增static_checks_passed独立结果。140测试，139通过、1项符号链接权限测试跳过。源码变更检测通过；保存后AST仍不等同运行注册，详见MAP_IO_CHECK.md。保持本地。
