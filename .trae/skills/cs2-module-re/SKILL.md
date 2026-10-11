---
name: cs2-module-re
description: Reverse-engineer CS2 editor DLLs (hammer, met, modeldoc, pet) in IDA and add cross-module bridge tools. Use when adding features for another editor DLL or reversing a new module. Not for map/entity/mesh work.
---

# CS2 编辑器模块逆向 + 桥接层扩展

给 `hammer / met / modeldoc_editor / pet` 里**尚未覆盖**的编辑器 DLL 逆向出对称结构，
并在注入桥接层（`cs2_tool.dll`）里加跨模块能力，最后活体验证 + 落文档。

已完成的模块能力见 `REVERSE_NOTES.md` §22 / §23，别重复做。

## 铁律（违反会崩 cs2 或白干）

- **CE 只读**：Cheat Engine 只用于读字节 / RTTI / AOB / 反汇编。**绝不用 `executeCodeEx`
  远程调进程内函数**（`allocateMemory` 返回 nil 未判空 + 参数位次错 → NULL 解引用，cs2 当场闪退）。
  要在目标进程里调函数，一律走注入 DLL 的桥接层。
- **别解引用哨兵值**：Python 侧遍历容器时，先过滤非指针值（`0xffffffffffffffff` 是 vector
  未用槽的哨兵）。曾在 Python 里对它解引用，导致 cs2 退出。
- **进程内虚调用 / 调函数都要走 DLL**：`ReadMem` 已有 `IsRangeReadable` 保护；
  上层遍历仍要先过滤非法值。
- **别加冗余工具**：每个「工具」静态注册的就是一条 bind 描述符，所以
  `cs2_module_bind_targets` 已是「工具+命令」的权威清单，不要再单列 tools 工具。

## 步骤

### 1. 确认目标 DLL 已加载

```
python injector\mcp_smoke.py cs2_tool_modules
```
`loaded=false` 说明进程里没有该 DLL。编辑器 DLL **按需加载**，要先用 Asset Browser 打开
对应编辑器（顶栏图标可自动化）：

```
python injector\qt_button.py find                 # 列出所有 tip='...' 的按钮 + 地址
python injector\qt_button.py click 0x<addr>       # 点 Particle Editor / Material Editor / ModelDoc Editor
```

点击偶发 `status=1 超时` 属正常，编辑器仍会打开；过后重查 `cs2_tool_modules` 即可见。
拿不到基址时也可用 `python injector\bringup.py` 一键拉起环境。

### 2. 逆向前准备

```
copy game\bin\win64\tools\<mod>.dll  ida_db\
```
启动 **IDA 9.1 自主实例**（`-A`），MCP 插件自启，端口从 13337 起自动递增避让；
实例注册在 `%APPDATA%\Hex-Rays\IDA Pro\mcp\instances\instance_<port>.json`。
等自动分析完成（`auto_state == 0`）再查。

### 3. 用 ida_eval 查询（唯一的 IDA 入口）

```powershell
@'
import idc
def _main():
    print(hex(idc.get_name_ea_simple("main")))
_main()
'@ | python injector\ida_eval.py 13337
```

- 脚本**必须是 `def _main(): ...` + `_main()`** 的形式（官方 py_eval 走 `compile+eval`）。
- cwd 固定为 `c:\cs2_tool_mcp`；端口按模块：13337=met / 13338=pet / 13339=modeldoc（当轮可能不同，先看实例注册文件）。
- PowerShell 多行 python 用 `@'...'@ | python -`；`python -c "多行"` 会报 ScriptBlock 错误。
- IDA 9.1 里 `idc.find_binary` / `ida_search.find_binary` 都没了 → 用
  `ida_bytes.get_bytes(start, n)` + `bytes.find(pattern)` 自己扫。
- `idautils.Strings()` 要先 `.setup()`，迭代项是 `StringItem`（有 `.ea`），不能 unpack。

### 4. 找与 hammer 对称的东西

四个 DLL 是**同一套框架**静态链进去的，结构与 hammer 逐字节相同，只有全局地址不同。
要找的三件套（具体 RVA、结构布局见 `references/module_rvas.md`）：

1. **接口注册表链头 `s_pInterfaceRegs`**：`CreateInterface` 序言
   `48/4C 8B 0D/05 <disp32>` → `head = fn + 7 + disp32`。
2. **bind 描述符链头**：纯数据全局，IDL 无法从导出推导；从该模块的 bind 枚举函数
   （遍历 `node = *(node+0x38)`、`vfn0` 取名）的引用反推。
3. **RTTI 实现类名**：`obj → *(obj) = vtable → *(vtable-8) = COL → COL+0xC = TD 的 32 位 RVA
   （相对**模块加载基址**）→ TD+0x10 = 名字`。剥掉前缀 `.?AV` 与尾部 `@@`。

### 5. 桥接层实现

- `injected_dll/hammer_bridge.h`：`ToolModule` 加字段；必要时加 `ModuleXxx` 结构与方法声明。
- `injected_dll/hammer_bridge.cpp`：
  - `kToolModuleSpecs[]` —— 每行 = `{dll 名, 短名, ToolSystem 接口名, CreateInterface RVA,
    s_pInterfaceRegs 链头 RVA, bind 描述符链头 RVA}`。接口名：modeldoc = `ToolSystem2_ModelDoc`，
    其余 = `ToolSystem2_001`。
  - 枚举方法一律 **raw 读固定偏移 + `IsRangeReadable` 保护**，别对其它模块发虚调用；
    节点上限、命令上限、自指保护都要有。
  - `RefreshToolModules()` 里链头优先序言动态解析，失败回退表里的 RVA。
- `injected_dll/ipc_pipe.cpp`：加 `method == "xxx"` 分支（`JsonMakeObject/Array/String/Int/Bool`），
  **并把方法名登记进返回列表 `list_tools`**。
- `mcp_server/cs2_mcp_server.py`：加 `@mcp.tool()` 薄封装（拼好可读文本，别把原始 JSON 丢给模型）。

### 6. 重编 + 重注入

DLL 被运行中的 cs2 占用，**先改名再编**，否则 `LNK1104: 无法打开文件`：

```powershell
cd injected_dll
Rename-Item build_vs18\Release\cs2_tool.dll cs2_tool_live.dll -Force -ErrorAction SilentlyContinue
& "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" --build build_vs18 --config Release
```

然后重启环境（`Get-Process cs2 | Stop-Process -Force` 后 `python injector\bringup.py`），
或对现有 pid 直接 `python injector\inject_dll.py <pid>`。收尾删掉改名的临时 DLL。

### 7. 验证

优先用**管道直连**（`mcp_smoke` 会截断长 JSON）：

```python
import sys; sys.path.insert(0, "mcp_server")
import cs2_mcp_server as S
p = S._get_pipe()
for m in p.call("tool_modules")["result"]:
    print(m["label"], m["loaded"], m["base_hex"], m["tool_system_class"])
print(p.call("module_interfaces", {"module": "pet"})["result"])
print(p.call("module_bind_targets", {"module": "pet", "include_commands": False})["result"])
print(p.call("ping")["result"])          # 每次调用后确认存活
```

链头正确性判据：`get_tool_system(module)` 返回的 `iface_list_head_hex / bind_head_hex - base`
应等于 IDA 里算出的 RVA。

### 8. 落文档

- `REVERSE_NOTES.md`：新加一节（RVA 表、链表布局、RTTI 解析法、活体验收）。
- `PROGRESS.md` §8.2：追加一行（编号顺延），含工具数变化。

## 参考

- `references/module_rvas.md`：四模块 RVA 表、节点/描述符/命令对象布局、命令执行（`_Do_call`）语义。
- 仓库内已有：`injector/ida_eval.py`（IDA 入口）、`injector/bringup.py`（一键环境）、
  `injector/qt_button.py`（点编辑器图标）、`injector/mcp_smoke.py`（冒烟）、
  `injector/inject_dll.py`（注入）、`injector/open_map.py`（开图，会话/工具实例用）。
