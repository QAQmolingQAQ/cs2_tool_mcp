# 编辑前冲突证据

`cs2_edit_preflight(config='', profile='', baseline_id='', expected_source_hash='')`
属于 hammer.dll 服务。默认范围读取工程配置；不修改地图或编辑器。

首次调用返回 `id`，记录配置与源地图 SHA-256、文件身份，以及可获取的桥接、
进程创建身份、模块身份、版本、文档路径与原始 dirty 世代。
后续传入 `baseline_id`，返回新的独立记录及变化领域；旧记录保留。
状态文件位于工程 `state_root/edit_preflights/<id>.json`，不包含私人配置正文。
读取前后重查文件身份和哈希，并比较两次运行身份；这不是原子快照。

`ok=true` 仅表示证据记录成功；离线也可以记录明确失败信息。
`conflict_check=matched` 仅表示观察记录一致，不证明无未保存编辑。
`safe_to_write` 始终为 false：dirty 语义、批量执行和验证后的回滚仍待实现。
基线文件是本地证据而非防篡改凭证，不能用来绕过原生版本校验。

2026-10-26：106 项 Python 测试通过，包含持久基线、磁盘修改、期望哈希失配、
配置竞争与输入范围检查。实际 stdio Hammer MCP 调用成功生成记录
`7f81341b364544ea8553bb16d7db985e`；当前管道 err=2，返回 connected=false、
live_observation_unavailable 和写入禁用。报告：
`C:\CS2_Temp\edit_preflight_mcp.json`。
尚未取得在线编辑/Undo/Redo/保存及回滚证据，不代表批量修改功能完成。

## 批量变更预览

`cs2_edit_preview(operations_json, expected_source_hash, config='', profile='', baseline_id='')`
同属 Hammer 服务，使用工程范围内已保存地图的唯一副本，不保存原编辑器。
操作格式为 `[{"entity_id":"DMX元素ID","property":"targetname","expected":"旧值","value":"新值"}]`。
最多256项，现阶段仅规划已有字符串属性，不支持创建实体、删除属性或改 classname。
每项结果包含 before/expected/after，状态为 planned、no_change、conflict 或 invalid；
同一属性重复操作明确拒绝。所有项 executed=false，整批 executed_count=0。

转换前后重新预检，检查源文件/配置/运行证据变化，并校验转换器和副本未变。
持久报告位于 `state_root/edit_plans/<id>/report.json`，包含操作摘要哈希与前后预检ID。
`plan_valid` 只表示保存后数据上的变更清单成立；不代表实时文档一致、FGD类型已验证、
可执行或已具备回滚。safe_to_write始终false，blockers仍保留。

2026-10-26：108项Python测试通过。实际stdio调用处理untitled_2.vmap副本，
实体60164751-290b-4430-b44c-2e14fd2b9df8的空targetname预览为mcp_preview_only，
结果planned；原地图SHA前后仍为f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e。
报告 `C:\CS2_Temp\edit_preview_mcp.json`，计划ID47af49e9636349bb96aebd7b48693f32。
当前桥接离线，未执行属性修改。

## 2026-10-26：撤销准备失败与文档归属修复（本地）

发现旧属性setter和I/O增删捕获撤销准备异常后仍继续修改；历史辅助函数还忽略了_call_fn返回的错误。
现压步、登记对象/节点和通知均检查派发错误，错误或未知结果向上传播；默认history=True时属性和I/O增删
在准备失败后立即返回ERROR，不分配连接缓冲或执行内容写入。历史自身可能已部分改变，因此报告勿重试，
不声称自动清理撤销栈或已完成回滚。history=False仍为既有显式调用约定，不代表批量执行已验证。

_doc_of_element取消找不到归属时选择首个文档的回退：父链查询失败、循环、超64跳、缺失或多文档匹配
均拒绝；唯一世界节点匹配才返回归属。旧REVERSE_NOTES§18.2的回退描述仅为历史行为。

新增5项测试，模拟每个历史准备阶段失败，确认后续内容setter、I/O分配/增删不发生；覆盖第二文档匹配、
无归属、父链错误/循环和歧义。145项测试：144通过、1项Windows符号链接权限测试跳过。
当前未发现CS2/IDA进程，IDA13341连接拒绝；未启动或关闭用户编辑器，也未变更原生兼容profile。
真实Hammer stdio MCP离线调用返回ERROR/未执行keyvalue写入，报告C:\CS2_Temp\edit_history_offline_mcp.json。
该旧接口的MCP isError仍为false，调用方须读取ERROR正文；不将传输成功视为编辑成功。
首次探针曾因缺少ERROR前缀而断言失败，已把不可用/未验证entity_properties的返回统一为明确ERROR并重测通过。
本次没有完成当前版本原生写入、Undo/Redo或通用批量回滚验证；下一步仍需隔离文档实测。

## 2026-10-27：持久计划复查

新增Hammer归属只读cs2_edit_plan_recheck(plan_id, expected_plan_hash, config, profile)。cs2_edit_preview额外返回plan_sha256，对除可移动报告路径外的完整报告做规范JSON SHA-256。复查仅接受UUID、精确外部期望哈希、报告schema/id/内容哈希一致；报告上限2MiB、1至256操作，状态目录路径受限，读取前后报告身份一致。旧计划没有哈希时须重新预览。

通过预览结束时的preflight_after重新比较工程配置、源码身份/SHA、进程/模块与文档布局证据。返回plan_current、冲突域、阻塞原因及各项recheck_status；只有计划本身有效且证据无变化才标unchanged，否则stale_or_invalid。结果另存edit_plan_rechecks/<UUID>.json，原计划不覆盖。无原生修改、无保存、无执行器；executed_count=0、safe_to_write=false始终保持。plan_current只表示已保存计划及上下文证据仍匹配，不表示未保存属性已逐项读取、全局dirty已确证或可安全写入。

165项测试：164通过/1符号链接权限跳过；新增测试覆盖无变化、layout/source冲突、错误哈希/内容篡改和非法ID。实际新stdio Hammer MCP生成计划6fe67924d7b04435bd5cdc4ba62fcd59，GUID657b42df-8155-4005-9f33-8ff4072e6c70的targetname空值到mcp_probe_plan_recheck仅planned；复查383997a9e9c0411794e5e3934bb9c98f返回plan_current=true且三个写入阻塞仍在，错误期望哈希拒绝。完整私人报告C:\CS2_Temp\edit_plan_recheck_stdio.json。103唯一工具/Hammer58；其余DLL归属不变。本轮没有编辑地图或切换运行地图。

下一步仍是把真实内存属性值、实体GUID与选择模型对应起来，然后接执行/逐项回读/Undo验证；本工具不代替通用批量执行与回滚。
