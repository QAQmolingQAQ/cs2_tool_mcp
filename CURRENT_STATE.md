# CS2/Hammer MCP 当前交接状态

更新：2026-10-13（北京时间）。本文件记录下一轮可直接接续的事实；历史细节在
[`PROGRESS.md`](PROGRESS.md) 和 [`REVERSE_NOTES.md`](REVERSE_NOTES.md)。
下载目录的角色模型与实机导入记录见 [`DOWNLOAD_MODELS.md`](DOWNLOAD_MODELS.md)。

## 工作位置与验证基线

- 主仓库：`C:\codex\cs2_tool_mcp`；IDA/探针副本：`C:\cs2_tool_mcp\ida_db`。
- 功能提交 `5aecfb5` 已推送至 GitHub；它包含 ModelDoc 原生按路径打开
  (`cs2_modeldoc_open`) 和单资源编译 (`cs2_asset_compile`)。最新 `origin/master`
  请用 `git log -1` 和 `git ls-remote origin refs/heads/master` 核对，避免文档中的哈希过期。
- CS2 以 `-tools -addon test` 运行，PID 11456；最新桥接 DLL 已注入，MCP 具 72 个工具。
  最近 44 项 Python 测试通过。下轮开始先验证进程/PID/桥接状态，不要复用旧绝对地址。
- Hammer、tier0、scenesystem 的 IDA MCP 端口为 13331/13334/13332；
  `modeldoc_editor.dll.i64` 的本地 IDA 数据库在上述 IDA 副本目录，可用 IDA 9.1 批处理。

## ModelDoc / Workshop 模型

- 本机 Steam 订阅的 CS2 Workshop 3600074056 含
  `models/prop_livehouse/live_house_counter.vmdl_c`。S2V CLI 20.0 位于
  `C:\cs2_tool_mcp\third_party\s2v-cli\Source2Viewer-CLI.exe`。
- 源模型、DMX 在当前 `test` add-on 的
  `content\csgo_addons\test\models\codex_workshop_probe\workshop_3600074056\`；
  最小测试材质、1×1 纯白色 PNG 在
  `content\csgo_addons\test\materials\models\prop_livehouse\`。这是本地测试资产，
  **不要提交、上传或宣称完整还原第三方材质**。
- S2V CLI 20.0 对原 `white_s.vmat_c` 的 shader 版本 72 报不支持；但其 DATA 块
  可读，颜色纹理可单独提取。根据该数据重建的最小材质让 CS2 的
  `resourcecompiler.exe` 成功编译：1 compiled、0 failed；生成的 `.vmdl_c`
  被 S2V 读回为含 MVTX/MIDX/MDAT 块的 Model。
- ModelDoc `FileOpen` 绑定在 `modeldoc_editor.dll` RVA `0xB9F500`，对话框选路径后
  调用 `CModelDocEditorApp` 主虚表 `+0x90`，参数 `(UTF-8 path, 1)`。
  `cs2_modeldoc_open` 用桥接层 `str:` 字符串参数在主线程调用，并用 RTTI 读回
  活动会话、`CModelDoc`、`CModelDocRoot`。
- 2026-10-13 用户亲自关闭 ModelDoc 窗口后，MCP 实测 `modeldoc sessions: 0`。
  随后用 `cs2_modeldoc_open` 重新打开上述已编译源文件，创建**新**会话并读回
  有效文档/根对象；根对象 `+0x10` 的低 32 位依然为零，`+0x18` 也为零。
  所以“旧会话未刷新”不能解释零计数。`CModelDocRoot` 虚表 `+0x40` 的
  `sub_1805EBA60` 虽读取 `+0x10/+0x18`，但不能据此认定它是源 KV3 节点列表。
  下一步追踪 ModelDoc 源树实际容器/属性，验证未保存状态，再设计写入与撤销。

## 其他编辑器与待办

- Particle Editor 对象链与九组实时列表偏移已反编译并在空白文档只读验证，详见 [`PET_DLL_OFFSETS.md`](PET_DLL_OFFSETS.md)。`CPetSession +0x108 -> CPetDoc +0x80 -> CPetRootNode`；
  当前仍需非空 `.vpcf` 验证节点 RTTI/属性，写入 API 尚未实机验证。`cs2_asset_tree` 只读取保存后的文本 KV3 `.vmdl/.vpcf`，
  不能代表编辑器未保存改动。
- ModelDoc 当前可读回文档和根对象，**尚不能可靠枚举实时子节点/属性**。
  找到读取结构后才添加修改 API，要求读回、原生撤销及实机验证。
- 下载目录的 Neco Arc、EarthGovSol 源模型已在本地 `test` add-on 中编译并
  打开到 ModelDoc；当前有 3 个会话。两者的源树分别有 14/16 个根子项，
  但实时根对象 `+0x10/+0x18` 仍为零，详见 `DOWNLOAD_MODELS.md`。
- Hammer 当前此前无打开地图；`cs2_map_check` 已实现只读检查，待有地图时做内容验证。
- 用户给出的 Discord 频道网页目前读取失败，不能推测频道内容。
- 用户要求持续自动化至北京时间 2026-10-14 23:59，并在每次改动后跑相关测试、
  实机 MCP 验证，推送 GitHub 前检查敏感信息；仅在有意义进展或失败时通知。

## 可复现检查

1. 仓库：`python -m unittest discover -s tests -q`；`git diff --check`。
2. MCP：先初始化桥接，再查 `cs2_editor_sessions("modeldoc")`、
   `cs2_editor_document("modeldoc")`；不要沿用上次进程地址。
3. 模型编译：`cs2_asset_compile(path, confirm=True)` 对 add-on 源文件运行 CS2
   自带编译器并检查编译产物；`cs2_modeldoc_open(path, confirm=True)` 在实时编辑器打开。
4. 推送前检查提交差异和敏感信息，确认远端 `master` 哈希与本地 HEAD 一致。
