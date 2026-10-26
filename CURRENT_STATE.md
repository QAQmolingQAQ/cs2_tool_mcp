# CS2/Hammer MCP 当前交接状态

更新：2026-10-26（北京时间）。本文件记录下一轮可直接接续的事实；历史细节在
[`PROGRESS.md`](PROGRESS.md) 和 [`REVERSE_NOTES.md`](REVERSE_NOTES.md)。
下载目录的角色模型与实机导入记录见 [`DOWNLOAD_MODELS.md`](DOWNLOAD_MODELS.md)。

## 当前持续目标：构建与产物验证

- 完整目标见 `WORKFLOW_GOAL.md`；旧 `cs2-mcp-10-14` 自动任务保持暂停。
- 新增工程/构建五工具、`cs2_session_selfcheck`及Hammer的 `cs2_map_io_check`，共86工具（Hammer50/bridge36）；最新88项测试通过。测试需统一TEMP/TMP为 `C:\CS2_Temp`，否则两项既有测试因盘符大小写字符串比较失败。
- VPK检查所有条目CRC、资源块边界、地图/世界资源、VXVS及识别的光照贴图集合。真实MCP检查 `cs_script_demo.vpk`（66条目）通过；原 `untitled_2.vpk`（12条目）有VIS但缺光照，完整模式拒绝。新构建仅写隔离副本，不替换原地图。
- `artifact_complete`仅代表包内证据；`release_ready`保持false，尚未完成游戏实测/依赖完整性验证。CRC与SHA已改为1MiB流式扫描，覆盖分卷、预加载与扫描取消，检测存储文件变化；513MiB测试通过且该例峰值分配低于16MiB。保留目录/块表元数据上限，详情BUILD_WORKFLOW.md。
- 配置模板 `config/project.example.json`，私人配置已忽略且指向test/maps/untitled_2.vmap；状态 `C:\CS2_Temp\mcp_build_jobs`。持久worker独立于MCP客户端Job；编译器使用创建时绑定的Job管理后代，取消与worker崩溃清理均测试通过。细节/复现见 `BUILD_WORKFLOW.md`。
- 真实MCP启动后关闭客户端，任务 `b2b99f92cbd24f468749a8d356df641d` 仍成功完成，退出0、VIS/11条目CRC通过；新客户端取消 `ae91ed8aece14954b32ff64560b99b0c`，确认cancelled、退出1223、进程树已退出。
- 完整构建 `a216dcaaae564ac891a9556d939f306e` 退出1：VMware GPU不支持VRAD3 ray tracing，未生成VPK。此硬件限制尚未解决，不能宣称完整编译/光照闭环已完成。
- 已安装游戏为Oct22版本；新增版本自检与传输层写入校验，实机stdio拒绝写入通过。桥接v0.2.0只启动IPC，不自动初始化旧偏移；桥接另要求新客户端attestation，保护未重载的旧服务。没有已验证profile，当前所有原生写入/调用保持禁用，详情 `VERSION_SELFCHECK.md`。
- 已自行打开test addon的工具模式做只读校验；未修改编辑文档，未提交或推送。旧偏移复核、活动地图/脏状态、批量冲突检测及后续I/O、运行诊断、发布检查仍未完成。
- 最终自检报告保存在本地 `C:\CS2_Temp\mcp_version_stdio_report.json`；本轮独立测试进程历史PID7328，当前Asset Browser、无地图，桥接initialized=false。下一轮重新核对进程身份；新客户端发送前拒绝与应用已运行旧客户端的桥接端拒绝均实测通过。不要通过采集当前哈希自动批准兼容profile。
- 用户建议后，以 `-allow_third_party_software` 重启了无编辑文档的测试实例，历史PID22936；CE MCP已连接并成功注入桥接，自检报告已刷新。截图仍超时，未宣称恢复捕获。新Hammer的静态dirty/关联文档与App候选分析见 `HAMMER_DIRTY_ANALYSIS.md`，尚未开放批量写入。
- 新增保存后地图FGD/I/O检查：真实stdio检查21实体/2连接，7份FGD/469类，0错误/2条未声明警告；支持目标/过滤器/已知参数类型与maker模板覆盖。脚本入口/类型、prefab展开、运行目标及未保存状态仍未覆盖，coverage_complete/release_ready=false。细节及报告路径见 `MAP_IO_CHECK.md`。
后续功能优先级与验收条件见 [`MCP_ROADMAP.md`](MCP_ROADMAP.md)。

## 工作位置与验证基线

- 主仓库：`C:\codex\cs2_tool_mcp`；IDA/探针副本：`C:\cs2_tool_mcp\ida_db`。
- ModelDoc 原生按路径打开、单资源编译、粒子目录查询均已推送。最新 `origin/master` 请用 `git log -1` 和 `git ls-remote origin refs/heads/master` 核对，不依赖交接文档中的旧哈希。
- 2026-10-14 本轮恢复CS2工具模式桥接，Pet目前两个会话（含原有未保存会话和独立测试粒子）；源码现有79个MCP工具，新工具需MCP服务重载后显示，最近62项Python测试通过。下轮开始先验证进程/PID/桥接状态，不要复用旧绝对地址。
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
- 此前用户要求仅本地；2026-10-14 用户要求检查准备上传并随后指示继续，已完成本轮 GitHub 推送。后续是否推送按新指示判断，不自动发布资产或创建 PR。每次功能改动后跑相关测试和实机 MCP 验证，并检查敏感信息；仅在有意义进展或失败时通知。自动任务已按本轮用户新指示恢复，截止北京时间今晚23:59；不自行延长截止时间。

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

## 2026-10-14 Codex 配置与自动任务

补充两个工作目录的 .codex/config.toml，规范全局八组CS2服务路径与工作目录并保留无关设置，实际配置启动验证通过。公开模板 config/codex.example.toml，私人配置已忽略。目录历史命名与功能缺口见 CODEX_SETUP.md；未把共享源码包误称为物理DLL目录重构。Pet/MET IDA在线且身份正确，其余按需启动。用户要求后恢复 cs2-mcp-10-14 每两小时任务，截止北京时间今晚23:59；后续自动改动仅保留本地。

## 2026-10-14 粒子 Base Properties

新增 pet.dll 只读 cs2_particle_editor_root_value，实际MCP读取最大粒子数8、半径106、颜色[237,57,57,255]和包围盒[-32,-32,-32]。当前79工具、Pet18工具、62项测试、八组stdio通过。原生属性设置候选及40/48字节上下文见PET_DLL_OFFSETS.md，尚未执行属性写入或Undo/Redo。computer-use初始化路径错误，既有Qt桥接可用；用户原有未保存会话保持打开。

## 2026-10-26 Qt hook 接续
用户报告CE崩溃；待决CE工具已返回连接失败，CS2只读检查仍响应。用户允许Qt hook。已审查现有WH_GETMESSAGE派发，发现Qt线程选择未验证及超时请求生命周期竞态；尚未修改或实机验证。实施顺序与边界见QT_HOOK_NOTES.md，不重放结果未知的调用。

主线程派发生命周期源码已修复（共享请求、RPC字符串持有、排队取消/在途未知、忙拒绝）；独立Windows hook测试及88项Python测试通过。VS18编译成功，根目录DLL被旧实例锁定，未部署新桥接。Qt线程身份/专用点击尚待实现，见QT_HOOK_NOTES.md。

桥接build.ps1已改为SHA产物留存及原子文件替换，锁冲突返回deployment_pending；实际文件锁/篡改等PowerShell测试通过。磁盘DLL已原子替换，但运行中模块未更新；真实MCP仍连接且写入拒绝验证通过，报告C:\CS2_Temp\mcp_after_atomic_deploy.json。详见BUILD_WORKFLOW.md。

Qt窗口线程选择已修正：当前实机只读发现Qt5152QWindow类；源码要求唯一Qt候选，歧义/Qt模块存在但无候选时拒绝，删除任意首线程回退。独立原生测试覆盖双线程候选拒绝及恢复，构建通过；尚未游戏内运行新桥接或实现Qt点击。见QT_HOOK_NOTES.md。

新桥接已在确认无编辑器模块后重启隔离CS2并注入，历史PID25944；加载PE与磁盘一致。固定内部main_thread_selftest实机跨线程返回正确，白名单仅此无害自检，不开放任意调用。89项Python测试通过；一次候选发现status2暂时失败后固定自检复测通过，原因未定。报告C:\CS2_Temp\mcp_qt_dispatch_live.json，重查身份后再用；Qt控件点击未完成。

新增只读bridge工具cs2_qt_widgets，87工具/bridge37，91项Python及原生测试通过。当前隔离历史PID20952运行新桥接，实际stdio读回Asset Browser337控件，含Hammer/Particle/ModelDoc按钮文字；主线程自检及写入拒绝复测通过。尚无点击功能，地址短期且分页顺序不稳定；状态与证据详见QT_HOOK_NOTES.md，报告C:\CS2_Temp\qt_widgets_mcp_page*.json。

新增cs2_qt_open_editor归bridge固定Qt UI通道（非只读），88工具/bridge38、93项Python及原生测试通过。当前历史PID22360已实际通过Qt点击启动Hammer，模块加载/1844控件读回确认；重复请求already_loaded_no_click，尚无地图。只读核对App候选+0x677E450虚表匹配+0x1DF2E90，旧App地址为空；dirty manager解释仍不明确，不开放原生写入。报告及细节见QT_HOOK_NOTES.md/HAMMER_DIRTY_ANALYSIS.md。

用户提供cs2-tools-trans-cn，已只读克隆并核对MIT/提交；离线文本对照读取out/hammer.json/common.json，保留原始文字、歧义与文件SHA。真实快照10个按钮获得翻译参考；发现部分译法不准确及两个采集导出名与本机不符，未注入外部DLL。95项Python测试通过，MCP仍88工具。见QT_TEXT_REFERENCE.md。此前Ctrl+O后UI观察为空、截图超时，未输入地图路径。

新增Hammer只读cs2_hammer_layout_observe，89工具/Hammer51/bridge38，98项Python测试通过。真实stdio校验模块SHA/App虚表后读回空会话和空dirty分组，重复读取一致；全局dirty指针解引用后布局与静态分析相符。输出始终dirty_state=unknown/safe_to_write=false，不将空值或重复读取当作已保存/原子状态。非空地图实测尚待完成，报告C:\CS2_Temp\hammer_layout_mcp_observation.json，见HAMMER_DIRTY_ANALYSIS.md。

已审查用户discover_out：227126记录、201800不同文本、325粒子名称均被记录；13163条Hook ID与functions元数据不符，按记录fn/mod归组，禁止复用历史地址或声称完整API。新增可复现离线分析及混合ID回归测试，99项测试通过；报告C:\CS2_Temp\discover_out_verified_analysis.json，详见QT_DISCOVERY_REVIEW.md。

新增cs2_qt_menu_actions，90工具/Hammer51/bridge39，100项Python及原生测试通过。当前隔离历史PID27972实际读回Hammer10菜单/148动作；Open文字含tab+Ctrl+O，已在磁盘新构建修正匹配归一化，运行模块仍为修正前版本。QAction enabled不等于命令就绪。固定排队Open对话框实验IPC尚未执行，不算已实现MCP动作；报告与下一步见QT_HOOK_NOTES.md。

排队Qt File/Open已实机验证：当前隔离历史PID26192出现原生Open对话框（在Hammer辅助功能子树中），管道/主线程自检与写入拒绝均通过。已生成隔离地图及独立工程配置，UUID f61a8859b90241378cb9120ea21675fe，原/副本SHA不变；地图尚未打开。电脑操控设值/点击失败且焦点未转移，未输入路径，Open模态仍保留；下一步Qt原生文件选择接口，见QT_HOOK_NOTES.md。

重要更新：当前历史PID26192已打开cs_script_demo.vmap，部署前只读检查发现非空后取消重启。Session→Wrapper→Doc主虚表/RTTI及+0x6A0路径实机验证，selfcheck现在返回实际地图，配置默认仍untitled_2；多文档不猜活动项，dirty仍unknown/禁止写入。103项Python/原生测试通过。新QtFileDialogMap仅磁盘源码实验，未部署实测；保留当前文档，报告C:\CS2_Temp\mcp_nonempty_document_selfcheck.json。

启动安全修正：审查发现ServerThread仍有未受版本校验的Initialize，已移除并升v0.2.1。新增真实独立管道+预加载fake hammer工厂计数测试，ping/拒绝initialize后工厂调用0；原生派发及103项Python测试通过。当前游戏仍v0.2.0且保留cs_script_demo文档，未部署/卸载；Stop的detach语义不构成热卸载屏障。详见BRIDGE_BOOTSTRAP.md，MCP仍90工具。

已按用户新目录C:\codex\cs2_tool_trans\collect\discover\out\discover_out交叉整理菜单文字，calls哈希与此前副本一致。历史Hammer快照10菜单/148动作中119非空项均有Qt采集文本命中，已输出HAMMER_MENU_TEXT.md/.json（含原文、快捷键、来源函数；仅一层非动态菜单）。当前管道WaitNamedPipe err2未连接，没有为读取菜单重启或注入。复现脚本extract_menu_reference.py；未推送。

新增只读 cs2_edit_preflight，按工程持久化文件/版本/会话证据并重查基线，始终safe_to_write=false。106项Python测试通过；实际Hammer stdio记录成功，当前管道err2离线，未执行编辑或回滚。见EDIT_PREFLIGHT.md；91个唯一工具，未推送。

新增cs2_edit_preview：已有实体字符串属性的逐项before/expected/after清单，冲突/重复/无效目标明示，转换前后复查预检及副本/转换器哈希。108项测试通过，实际MCP转换并预览真实地图，原SHA不变；92个工具。桥接离线，执行/dirty语义/回滚未完成，见EDIT_PREFLIGHT.md。

实机更新：新启动test addon并加载v0.2.1桥接，早期Qt未就绪后自检/写入拒绝通过。当前本轮PID10268在线，Hammer零文档/Open模态；Qt文件选择setDirectory已实测导航正确，selectFile仍填C:/完整路径导致原生文件名无效，未成功打开地图。新DLL SHA2f2cb2a0c20f7bf7cbc19607c82e8ba376e194f560efa77105b9e6544233d24c；108项Python与两原生测试通过，原/副本SHA不变。见QT_HOOK_NOTES.md，未推送。

关键实机进展：Windows原生文件名适配器解决Qt完整路径失败，当前本轮PID2064已打开隔离地图f61a8859b90241378cb9120ea21675fe/untitled_2.vmap，实际MCP主虚表/RTTI/路径及自检/写入拒绝通过。最新桥接SHAe00f79e6fbe7df47b10200cc219674d2802697a05300419fb5b8c6d5e01bfe9a。原/副本SHA未变，隔离工程预检连续两次matched；dirty世代1/1不作为clean证据。原生嵌套控件/歧义/禁用测试通过，详见QT_HOOK_NOTES.md。本地manifest已更新editor_opened，后续保留此文档做编辑/Undo/保存验证；未推送。

隔离编辑实测：本轮PID8408/桥接SHA c719b44fce384116eff603cdf80ec789fa2b35fcf2f06af2db3792168c464ef7。固定实验Qt菜单动作完成SelectAll/Delete/Undo/Redo/Save，世代1→24→47→70→93，保存同步70/70及93/93。磁盘21实体→0→21；按nodeID属性/I/O一致，但顺序反转及部分内部DMX GUID重建，完整回滚未证明；实体自身GUID本次稳定。原图SHA不变，副本新SHA bb3ded8d5bc9994b170bcaded0d7bd70964cee7dded5eb81d26259c7a1b647ed。109测试和原生测试通过。详见EDIT_CYCLE_VERIFICATION.md；当前仍保留隔离文档，未推送。

新增Hammer cs2_map_snapshot_compare，严格保留类型/children顺序/变换/网格，实际MCP核验25节点无缺失新增，唯一节点差异world.children；metadata仍不同，完整回滚false。114测试通过，93工具。同一编辑后隔离工程MCP快速构建任务759ba3afef6846bab69efa5590c1679d成功，VPK11项/VIS有效/无光照；source未变。详见EDIT_CYCLE_VERIFICATION.md，仍缺完整光照和实机加载；未推送。

2026-10-26 用户重新授权更新GitHub：阶段功能提交1af037abb2e0b48d93e2d0397010e334b642821f已普通push并ls-remote核对一致，包含此前2个本地提交。114测试、原生派发/bootstrap/发布替换测试、八组stdio通过；83文件敏感扫描无命中，私人配置/二进制/第三方资产未上传。上传回执另作提交，详见GITHUB_UPLOAD_CHECK.md；完整目标仍继续，后续不将本次授权视为无限自动推送授权。
