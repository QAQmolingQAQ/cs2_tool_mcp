# CS2/Hammer MCP 当前交接状态

更新：2026-10-14（北京时间）。本文件记录下一轮可直接接续的事实；历史细节在
[`PROGRESS.md`](PROGRESS.md) 和 [`REVERSE_NOTES.md`](REVERSE_NOTES.md)。
下载目录的角色模型与实机导入记录见 [`DOWNLOAD_MODELS.md`](DOWNLOAD_MODELS.md)。
后续功能优先级与验收条件见 [`MCP_ROADMAP.md`](MCP_ROADMAP.md)。

## 工作位置与验证基线

- 主仓库：`C:\codex\cs2_tool_mcp`；IDA/探针副本：`C:\cs2_tool_mcp\ida_db`。
- ModelDoc 原生按路径打开、单资源编译、粒子目录查询均已推送。最新 `origin/master` 请用 `git log -1` 和 `git ls-remote origin refs/heads/master` 核对，不依赖交接文档中的旧哈希。
- 此前 CS2 工具模式在线；2026-10-14 本轮后段实测进程不在线、管道不存在，下一轮先恢复运行环境；源码现有 78 个 MCP 工具（新工具需 MCP 进程重连后显示），最近 59 项 Python 测试通过。下轮开始先验证进程/PID/桥接状态，不要复用旧绝对地址。
- IDA MCP 固定端口为 Hammer 13341、Pet 13342、MET 13343、ModelDoc 13344、particles 13345、scenesystem 13346、tier0 13347，详见 MCP_MODULES.md；
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

## particles.dll 函数目录（2026-10-13）

- 当前 DLL 的 `ParticleSystemMgr003` 实时注册了 376 个粒子函数，七组计数 49/4/98/161/16/13/35；从 `SchemaClassInfo` 解析了 395 个相关类、字段类型、友好名及继承链。完整索引与用法边界见 [`PARTICLE_FUNCTIONS.md`](PARTICLE_FUNCTIONS.md)；按函数展开的完整参数导出见 [`PARTICLE_API_REFERENCE.json`](PARTICLE_API_REFERENCE.json)。
- 新增只读 `cs2_particle_functions`（分页搜索）与 `cs2_particle_function_info`（类参数及继承）及版本化 JSON 目录。数据取自 DLL SHA-256 `9dc34a2de4311ec811b381611658fd4010861edc26e717496319a3cda72303b0`；游戏更新后重抽。
- 这能回答全部已注册函数及其可编辑参数；尚不能保证逐函数的人写语义教程，也尚未实现安全的未保存粒子节点属性写入。

## 其他编辑器与待办

- Particle Editor 对象链与九组实时列表偏移已反编译并在空白文档只读验证，详见 [`PET_DLL_OFFSETS.md`](PET_DLL_OFFSETS.md)。`CPetSession +0x108 -> CPetDoc +0x80 -> CPetRootNode`；
  已用非空 `.vpcf` 验证九组计数、六个 `CPetFunctionNode` RTTI、函数类名以及部分参数值；新增 `cs2_particle_editor_open`、只读 `cs2_particle_editor_tree`、`cs2_particle_editor_value` 和 `cs2_particle_editor_compare`。静态追踪到 `CPetKV3PropertyDomain` 的历史前后通知，仍需验证未保存变更差分，写入 API 尚未实机验证。`cs2_asset_tree` 只读取保存后的文本 KV3 `.vmdl/.vpcf`，
  不能代表编辑器未保存改动。
- ModelDoc 当前可读回文档和根对象，**尚不能可靠枚举实时子节点/属性**。
  找到读取结构后才添加修改 API，要求读回、原生撤销及实机验证。
- 下载目录的 Neco Arc、EarthGovSol 源模型已在本地 `test` add-on 中编译并
  打开到 ModelDoc；当前有 3 个会话。两者的源树分别有 14/16 个根子项，
  但实时根对象 `+0x10/+0x18` 仍为零，详见 `DOWNLOAD_MODELS.md`。
- Hammer 当前此前无打开地图；`cs2_map_check` 已实现只读检查，待有地图时做内容验证。
- 用户给出的 Discord 频道网页目前读取失败，不能推测频道内容。
- 此前用户要求仅本地；2026-10-14 用户要求检查准备上传并随后指示继续，已完成本轮 GitHub 推送。后续是否推送按新指示判断，不自动发布资产或创建 PR。每次功能改动后跑相关测试和实机 MCP 验证，并检查敏感信息；仅在有意义进展或失败时通知。既有持续自动化目前保持暂停状态，不自行恢复。

## 可复现检查

1. 仓库：`python -m unittest discover -s tests -q`；`git diff --check`。
2. MCP：先初始化桥接，再查 `cs2_editor_sessions("modeldoc")`、
   `cs2_editor_document("modeldoc")`；不要沿用上次进程地址。
3. 模型编译：`cs2_asset_compile(path, confirm=True)` 对 add-on 源文件运行 CS2
   自带编译器并检查编译产物；`cs2_modeldoc_open(path, confirm=True)` 在实时编辑器打开。
4. 推送前检查提交差异和敏感信息，确认远端 `master` 哈希与本地 HEAD 一致。

## 本轮接续（2026-10-14）

两会话分别读回 CPetSession+0x58 源路径，对照工具已加入该路径核对；集成后的完整实机复测因进程离线待补。55 项测试通过。用户接着要求推进 MET，静态入口及候选布局见 [MET_DLL_OFFSETS.md](MET_DLL_OFFSETS.md)，尚未开放材质写入。旧 met.dll.id0 报损坏，改用本地 met_clean_20261014.dll.i64。

## VRF 本地参考（2026-10-14）

已读取用户提供的 ValveResourceFormat。当前工厂表覆盖 153/376 个粒子函数；源实现及参数引用索引在 VRF_PARTICLE_REFERENCE.json，用法边界与 MET Shader 元数据入口在 VRF_REFERENCE_NOTES.md。源码 VCS 检查接受 59–72，尚未构建或复测旧 CLI 失败素材。继续实时编辑器架构，不把文件解析当作安全写入。

## 按 DLL 拆分 MCP（2026-10-14）

用户纠正划分依据：按目标 DLL，不按功能。现有 hammer/pet/particles/met/modeldoc_editor/scenesystem/tier0 七组 DLL 服务，另有共享 bridge 辅助服务。Hammer 粒子实体设置仍属 hammer.dll，Pet 文档属 pet.dll，函数目录与 Schema 属 particles.dll。所有 78 个工具有显式主归属，登记在 mcp_server/hammer_mcp/data/tool_ownership.json；不再根据 Python 文件名或功能名称猜归属。59 项测试及八组 stdio 验证通过，客户端配置已同步，IDA 端口不变。详情见 MCP_MODULES.md。

## 2026-10-14 本地：Soundevent 单文件参考

新增 [SOUNDEVENT_REFERENCE.md](SOUNDEVENT_REFERENCE.md)：208 份 core/csgo 声音资源全部解析，VPK CRC、KV3 缓冲与类型流校验通过，0 失败；251 个声音栈、138 种实际出现的操作函数、1393 条按栈展开的 public 参数。包含写法示例、声明类型、默认值、编辑条件、底层函数字段与资源指纹。底层完整注册签名、未出现字段和输出类型仍需 soundsystem.dll 反射；尚未编译或播放。生成脚本与原始分析数据在 C:\cs2_tool_mcp，仅保存在本地。目录与 Markdown 结构核对通过，敏感信息模式扫描 0 命中。

## 2026-10-14 GitHub 上传准备

用户要求检查并准备上传。本轮 59 项测试、八组 stdio 验证、受控文件及此前 6 个未推送提交敏感模式扫描通过，无第三方资产或私人配置候选；已整理本地提交。详情见 [GITHUB_UPLOAD_CHECK.md](GITHUB_UPLOAD_CHECK.md)。本轮未执行 push；实际上传前需重新核对远端状态。自动化保持暂停。

## 2026-10-14 GitHub 上传完成

用户指示继续后重新核对远端，7 个已检查提交通过普通 push 上传；远端 master 读回与 77673ae6c727d01c597762caa62ade89dc18b0fd 一致。上传记录另作提交，不依赖提示中的旧哈希。59 项测试、八组 stdio 验证结果及实机验证限制见 GITHUB_UPLOAD_CHECK.md；自动化保持暂停。
