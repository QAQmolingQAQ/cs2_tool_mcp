# 隔离地图编辑往返实测（2026-10-26）

仅作用于test addon的`maps/__mcp_edit_tests/f61a8859b90241378cb9120ea21675fe/untitled_2.vmap`。
原始`maps/untitled_2.vmap`未修改，SHA仍为
f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e。

当前本轮PID8408，桥接v0.2.1、SHA
c719b44fce384116eff603cdf80ec789fa2b35fcf2f06af2db3792168c464ef7。
所有PID、地址、标题都是当时证据，后续需重新核对。

实验IPC `qt_hammer_probe_action`只允许File/Save、Edit/Select All、Delete Selected、Undo、Redo。
在已校验Qt ABI主线程上重新定位唯一CQBaseEditorWnd，精确核对标题/可见性，
再匹配唯一可见启用QAction。没有开放任意对象地址、函数或编辑器RVA。
该IPC不是已发布的通用批量修改MCP。其固定Qt通道不改变原生偏移写入profile禁用。

复现控制脚本`scripts/hammer_edit_probe.py`限定非release test addon的UUID隔离路径，
核对唯一打开文档、addon与上次持久证据完全相同，单次执行后记录结果。
派发前落盘；异常结果未知时保留unknown_do_not_retry，不自动重放。
它不认证完整回滚，也不是泛用编辑器权限接口。

## 实际观测

| 阶段 | 文档世代 | 保存世代 | 磁盘内容 |
|---|---:|---:|---|
| 打开/初次Save | 1 | 1 | 原始21实体/136 DMX元素 |
| Select All | 1 | 1 | 未变 |
| Delete Selected | 24 | 1 | 未保存，原哈希未变；标题出现星号 |
| Undo | 47 | 1 | 未保存 |
| Redo | 70 | 1 | 未保存 |
| Save | 70 | 70 | 转换核验0实体/12元素；标题无星号 |
| Undo | 93 | 70 | 标题再次出现星号；磁盘仍为删除版 |
| Save | 93 | 93 | 转换核验恢复21实体/136元素；标题无星号 |

Undo/Redo世代继续递增，不会回到旧数字。因此不能把世代当作Undo栈索引。
直接匹配已验证文档地址且generation>saved的情况，现输出
`direct_document_unsaved_changes`并作为预检阻断原因；列表为空仍不能证明全局clean，
关联文档与主线程原子性尚未验证。`dirty_state=unknown`和`safe_to_write=false`保持不变。

## 内容验证与回滚限制

恢复后的21个实体按nodeID匹配，属性和I/O内容一致（比较I/O时仅排除DMX对象id）；
**实体自身GUID在本次往返保持一致**。部分I/O等内部DMX元素GUID重建，实体遍历顺序反转。
完整解析图和文件哈希均不同，不能宣称字节恢复或全图等价；变换/网格全图比较仍待完成。
初次直接数组比较失败后已保留失败结果，并补充按nodeID限定范围的内容比较，没有放宽为全图成功。
最终副本SHAbb3ded8d5bc9994b170bcaded0d7bd70964cee7dded5eb81d26259c7a1b647ed。

真实Hammer stdio MCP验证：旧文件哈希的预览被preflight conflict拒绝；
使用新哈希重新查询可生成只读计划，executed_count仍0。不能假设实体GUID必变，
也不能仅凭GUID相同复用旧文件基线。通用批量回滚功能仍未完成。

## 证据

- `C:\CS2_Temp\mcp_build_jobs\edit_probe_runs\*.json`：各步before/after、进程/模块/文件身份与调用结果。
- 删除步骤226162d5f06b4a8b9b948bf73bb5baf6，删除保存b8f702f3631d4dfda7c174091d54d14d，恢复保存aaa3024bb74d4efeb76c282cf7f0a9bf。
- `C:\CS2_Temp\mcp_build_jobs\edit_probe_content\93c3e2d5902d41a981ea0fb0e399be10`：原始/删除/恢复KV2及restore_report.json。
- `C:\CS2_Temp\edit_cycle_stale_plan_verification.json`：实际MCP旧哈希拒绝及新哈希重新预览。
- `C:\CS2_Temp\mcp_edit_cycle_final.json`：实际MCP会话路径、自检及原生写入拒绝通过。

109项Python测试与两项原生测试通过。未推送GitHub。
下一步需将逐项属性修改接入文档绑定的执行器、验证变换/网格及完整回滚，
再用同一隔离工程执行构建与实机加载；尚不满足整个流程的完成条件。

## 后续：节点严格比较与编辑后构建

新增Hammer MCP `cs2_map_snapshot_compare(before_kv2, after_kv2, config='', profile='')`，
仅读取工程state_root内有界KV2缓存，前后核对文件身份/哈希，不修改输入。
按唯一nodeID匹配，解析嵌套/引用元素，忽略的只有id且类型为elementid的存储身份。
保留属性类型、数组顺序、标量、变换、完整网格流及节点引用；未知引用、重复nodeID、
循环非节点引用和过深图拒绝。不会将节点值比较等同于别名关系或整个地图恢复证明。

实际stdio比较原始/恢复快照的25个节点：无缺失/新增，只有CMapWorld nodeID=1的
children属性不同。两网格节点、所有实体变换与其余类型化内容一致；根/编辑器元数据仍不同。
严格结果node_content_equal=false、metadata_equal=false、full_rollback_verified=false。
报告C:\CS2_Temp\map_snapshot_compare_mcp.json；本模块与回归测试没有忽略children顺序。
114项Python测试通过，公开工具增至93个。

同一隔离工程实际MCP快速构建任务759ba3afef6846bab69efa5590c1679d成功。
输入为恢复后保存的SHAbb3ded8d5bc9994b170bcaded0d7bd70964cee7dded5eb81d26259c7a1b647ed，
独立worker/compiler退出，退出码0、source_unchanged=true；任务阶段包含world/phys/vis/validate。
VPK SHAae798e7ab64c255a51157d207f15de163a04345a313cc174b9ca02727ca68243，
11项、40613字节，CRC/资源边界验证通过，VIS=true、lighting=false。
这是保存后磁盘数据的快速构建，不证明编辑器全局clean，也不是完整光照构建或游戏加载通过。
任务日志/状态位于C:\CS2_Temp\mcp_build_jobs\759ba3afef6846bab69efa5590c1679d。
完整光照此前已受VMware GPU不支持VRAD3光追阻断，本轮没有无条件重跑相同失败。

## 2026-10-26：重新建立属性往返测试环境

本轮重新核对后没有运行CS2；Steam在线。启动-insecure -tools -addon test
-allow_third_party_software -condebug，实例PID15744（仅历史身份，下轮重查）。CE MCP连接失败，
改用仓库injector一次加载现有v0.2.1桥接，实际stdio独立确认PID/桥接、主线程自测及原生写入拒绝通过。
未因CE失败重试注入；未调用静态候选写入、未新增兼容profile。

通过固定Qt按钮打开Hammer，新建隔离副本UUID bc1d170dd26541cf80f946e324a3beca。
工程配置C:\CS2_Temp\mcp_build_jobs\editor_probes\bc1d170dd26541cf80f946e324a3beca\project.json。
电脑操控Ctrl+O打开Windows原生选择器；辅助功能可观察文件名编辑框，但set_value报告
“element is not available in cached app state”。刷新后仍失败，未通过其他UIA接口绕过。
随后使用已验证的qt_file_dialog_map适配器，完整路径读回后排队打开。
独立实际MCP核对唯一文档路径、主虚表及RTTI匹配，确认打开的是新UUID副本。

原图和新副本SHA均仍为f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e。
观察dirty世代候选1/saved1，但全局dirty仍unknown，不据此开放通用写入。
实机Qt枚举3443控件；辅助功能间歇返回完整属性面板与Outliner（21实体），
截图仍FrameArrived超时，索引点击info_player_start也遭同类缓存定位错误，没有选择或修改实体。
Ctrl+Shift+F后未验证实体查找对话框出现，不误称快捷键已完成目标动作。

当前仅完成环境恢复、隔离文件打开与身份/拒绝校验；属性修改、读回、Undo/Redo仍待完成。
后续优先补Qt控件的稳定文档/父路径定位和只读属性模型观察；不使用易变地址或旧RVA直接写。
证据C:\CS2_Temp\mcp_property_probe_session.json、mcp_property_open_result.json、
hammer_property_probe_accessibility.txt、property_probe_menus.json；
隔离快照ID b2817f1575bd477e8790243fb6886f9c。
本轮没有功能源码改动，不重复运行未变的147项测试；实际stdio重新验证通过。保持本地。

2026-10-27：在隔离test地图完成targetname文档提交、保存、Undo/Redo和最终Undo保存，原图未动。分别核对控件缓冲/内存文档/磁盘；25节点内容严格相等，元数据仍不同。通用批量与完整回滚未完成，详见HAMMER_PROPERTY_EDIT_VERIFICATION.md；保持本地。

## 2026-10-27：属性往返后的保存地图构建

实际MCP build_start/status任务16a7b0c6556a49b4931c61d599b12799使用属性往返后已保存的隔离地图（SHA6614e9746a6dc654ae57e3c6a0c74b46c15f72c12acfed992af87ccb35c900d6），不是历史ac72任务的旧源码。world/phys/vis快速构建退出0，源码和安装输入保持不变，进程树退出。产物mcp_16a7b0c6556a49b4931c61d5.vpk，SHA5e3e025d74b7d3c262616c613546a6bedc2836300a7b07fea4cfa9337494c3b7；11条目CRC/资源边界通过、VXVS存在、没有光照贴图，因此artifact_complete/release_ready均false。

当前源码依赖查询覆盖19资源/28条RERL引用，0问题、声明引用闭合通过；不覆盖动态引用或发布完整性。报告C:\CS2_Temp\edit_cycle_saved_build_verification.json；构建request/state/compiler.log保存在状态目录的任务ID下。未新增功能源码，本轮不重复无变化的测试。

另以当前源码完整标记诊断核对PID7132：状态为Server Running、Client Connected loopback、Current game，没有loaded spawngroup地图名行。原始输出仅留本地runtime_status_format_private.json，不从缺失地图行推断空闲安全。加载器真实预览返回one unambiguous current runtime map required，未发map命令。这一步证明编辑往返保存后的构建与声明依赖，尚未完成这一产物的游戏加载；下一步需可靠区分工具默认世界/已加载地图状态，或从原生会话取得可交叉核对的运行地图身份。
