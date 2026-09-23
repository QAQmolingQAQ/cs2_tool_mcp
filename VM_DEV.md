# VM 内开发快速上手（CS2 Hammer MCP）

> 这是「在虚拟机内直接开发」的入口文档。
> 项目背景与逆向细节见 **REVERSE_NOTES.md**；进度与待办见 **PROGRESS.md**。
> 先读本文，再看那两份。

---

## 0. 为什么改成「在 VM 内开发」

早期形态是：实体机写代码 → `scp` 推到 VM → 走 SSH 远端执行验证。两跳模式成本很高：

- SSH 里的 JSON 引号/转义反复打架（所以才有了 `vm_pipe.py` 的免 JSON 子命令）
- 远程 PowerShell 的中文/编码坑（`.ps1` 无 BOM 时按 GBK 解码，**中文注释会把下一行代码吞掉**）
- 一次排查要来回好几轮才能定位

现在改为**直接在本机（VM）用 Trae 开发**：编辑器、运行环境、目标进程都在同一台机器上，
改完立刻能验证。

---

## 1. 目录布局

| 路径 | 用途 |
| --- | --- |
| `C:\cs2_tool_mcp\` | **开发仓库 + 运行时目录**（本文件所在；`input.txt`/`input.out`/`vm_input.ps1` 由计划任务调用） |
| `C:\cs2_tool_mcp\injected_dll\` | 注入 DLL 的 C++ 源码 |
| `C:\cs2_tool_mcp\injected_dll\build_msvc\` | DLL 编译输出（`cs2_tool.dll`） |
| `C:\cs2_tool_mcp\mcp_server\` | MCP 服务（FastMCP，对外提供工具） |
| `C:\cs2_tool_mcp\injector\` | 注入器 + 调试/探测脚本 |

**CS2 安装路径**：`C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\`

---

## 2. 架构一览

```
┌──────────────────┐   命名管道 \\.\pipe\CS2ToolMCP   ┌────────────────┐
│ Python MCP Server│◄───────────────────────────────►│ cs2_tool.dll   │
│ (FastMCP, 工具集) │   <I 长度前缀 + UTF-8 JSON-RPC    │ (注入进 cs2.exe)│
└──────────────────┘                                 └───────┬────────┘
                                                             │ 直接调用
                                                             ▼
                                                   hammer.dll（Hammer 全部内部状态）
```

- **DLL 侧**：内存原语（读/写/分配）、调用原语（`call_function` / `call_virtual`）、
  主线程派发（`WH_GETMESSAGE` 钩子）、SEH 保护
- **MCP 侧**：工具分组、参数校验、以及「实体枚举 / 属性读写 / Qt 自动化」这类高层逻辑

---

## 3. 拉起 Hammer（⚠️ 新版流程已变）

新版 CS2 的 `-tools` **不再直接进 Hammer**，而是先进 **Asset Browser**（Mod Tools 启动器），
需要**点 Hammer 图标**才会加载 `hammer.dll`。全自动流程（已验证）：

```powershell
# 1) 启动 Asset Browser（必须投到 Session 1：SSH 所在 Session 0 没有显卡，直接 Start-Process 会秒退）
#    用 schtasks /create ... /it 投递

# 2) 注入 DLL
python injector\inject_dll.py

# 3) 用 Qt 自动化点 Hammer 图标（详见 REVERSE_NOTES §2.14）
python injector\vm_pipe.py qt-buttons hammer      # 列出按钮，找到 Hammer 的地址
python injector\vm_pipe.py qt-click 0x........    # 点击它 → hammer.dll 被加载

# 4) 建图 / 开图（走菜单 QAction）
python injector\vm_pipe.py qt-menu                # 列出菜单栏
python injector\vm_pipe.py qt-actions 0x...File   # 列出 File 菜单项
python injector\vm_pipe.py qt-trigger 0x...       # 触发 &New 建一张空图

# 5) 验证
python injector\vm_pipe.py map-info
python injector\vm_pipe.py entities
```

**为什么要用 Qt 而不是模拟鼠标/键盘**：点击不依赖窗口焦点，一次调用就能命中；
而模拟按键必须先抢前台，且「置前 + 发键」必须在**同一个任务**里完成
（否则新起的 powershell 窗口会把前台抢回去）。见 §6.6。

---

## 4. 编译注入 DLL

```powershell
cd C:\cs2_tool_mcp\injected_dll\build_msvc
& "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" --build . --config Release
```

- ⚠️ `CMakeLists.txt` 必须带 `/utf-8`，否则源码里的中文注释会报 `C2187/C3484`
- 改完 DLL 要**重新注入**才生效（重启目标进程后一并注入最省事）

---

## 5. 验证链路速查（`injector\vm_pipe.py`）

`vm_pipe.py` 是免 JSON 的调试入口，直接打子命令即可：

| 子命令 | 作用 |
| --- | --- |
| `module <名字>` | 查模块基址 |
| `map-info` | 当前地图路径 / CMapDoc / CMapWorld |
| `entities` | 枚举地图实体（引擎全枚举 + 按 vtable 筛 CMapEntity） |
| `attr <实体> <属性名>` | 读实体属性 |
| `findattr <实体>` | 列出实体属性 |
| `setattr <实体> <名> <值>` | 写实体属性（自动进 Datamodel 撤销栈） |
| `dm-info` / `dm-undo` / `dm-redo` | Datamodel 撤销栈信息 / 撤销 / 重做 |
| `map-undo` / `map-redo` / `map-save` | Hammer 地图历史 / 保存 |
| `qt-types [词]` | 列 Qt widget 类名 |
| `qt-buttons [词]` | 列按钮（toolTip/text） |
| `qt-click <w>` | 调 `QAbstractButton::click()` |
| `qt-menu` / `qt-actions <menu>` / `qt-trigger <action>` | 菜单树 / 子菜单 / 触发菜单项 |
| `qt-str <w> <rva>` | 调返回 QString 的成员函数 |
| `vc <obj> <vtable_offset> [args]` | 免 JSON 调虚函数（默认走主线程） |
| `cls <obj>` | 读任意 Qt 对象的类名 |
| `tl` | 测 `QApplication::topLevelWidgets()` |

UI 自动化相关的独立入口：
`vm_ui.py windows`（列可见窗口）、`vm_ui.py keyto "<窗口> | <按键>"`（抢前台+发键）。

---

## 6. 关键陷阱（务必先读）

1. **改文档/UI 的调用必须 `on_main_thread=True`** —— 否则执行成功但永不返回，留下 busy 态。
2. **主线程派发是「串行槽位」机制**：短时间内发太多 `on_main_thread` 调用会积压并超时。
   → 遍历大量对象时，先用 `read_memory`（**不走主线程**）读 vtable 去重，
   只对每种类型问一次；并且优先用 `topLevelWidgets()`（实测 299 个）
   而不是 `allWidgets()`（打开地图后有 5400+ 个）。
3. **Qt 非平凡返回类型（QString / QList）必须传隐藏返回缓冲区，且缓冲区在 `rdx` 而非 `rcx`** ——
   传错会直接崩进程。
4. **`QList` 元素地址 = `d + 0x10 + 8*(begin+i)`** —— `d+0x10` 处存的是元素 0 的**值**，
   不是数组指针（按二级指针去读会拿到垃圾）。
5. **`QAction` 不是 widget**，`allWidgets()` 拿不到，必须经 `QWidget::actions()` 取。
   **`QAction::trigger()` 在钩子上下文里遇到模态对话框会永不返回**（嵌套消息循环），
   所以它只适合不会弹窗的菜单项（如 `&New`）。
6. **模拟键盘要用 `vm_ui.py keyto "窗口 | 按键"`**：置前与发键必须在同一个 ps1 进程内完成。
   另外 `vm_input.ps1` 必须存成 **UTF-8 with BOM**，否则中文注释会被按 GBK 错解、
   把紧随其后的代码行吞进注释里。
7. **僵尸进程**：CS2 崩溃后 PID 会残留（枚举不到任何模块），注入与管道调用会假失败。
   判据是 `EnumProcessModules` 返回 0。
8. **`className` 过滤参数是驻留符号指针**，不是 `const char*` —— 传字符串常量恒返回 0。
   实体枚举要传 `NULL` 全枚举、再本地按 vtable 过滤。
9. **不要拿陌生函数当冒烟测试** —— 曾因此把 Hammer 卡死。用 `main_thread_selftest` 验证派发链路。

---

## 7. 相关工具（本机已装）

- **IDA Professional 9.1** + `ida-pro-mcp`：静态分析 `hammer.dll`（端口见
  `%APPDATA%\Hex-Rays\IDA Pro\mcp\instances`）
- **Cheat Engine** + `ce_mcp_tcp.dll`：运行时内存分析
- `injector\ce_call.py` / `injector\ida_mcp_call.py`：免手写 JSON 的调用封装
