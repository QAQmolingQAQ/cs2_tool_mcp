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
