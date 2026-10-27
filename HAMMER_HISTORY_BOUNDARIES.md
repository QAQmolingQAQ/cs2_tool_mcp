# Hammer 历史边界与受限Undo验证（2026-10-27）

## 已查明的根因与读取链

上轮两次Name提交之间确有独立Modify Selection步骤。只按提交数Undo会消耗选择步骤而不恢复预期属性。当前直接读取历史栈可区分Modify Selection与Change: Name；不据名称独自授权撤销。

只读核心history_snapshot.py：唯一配置文档→doc+0x80 CMapRootElement（vtable0x1766058）→root+0x240/+0x248 CMapDocHistory（vtable0x1765E00）。历史+0x78必须回指doc+8，+8计数、+0x10步骤指针表；最多1024步。步骤+0命令数（最多4096）、+8命令表地址、+0x18所属history回指、+0x20编号候选、+0x24有界名称。完整读取前后复核内存与进程/源码/配置/文档证据。只是步骤身份，不包含完整命令内容，ABA及非原子窗口未排除，safe_to_undo保持false。

批量探针现在记录每项选择前/后、提交前/后历史；batch_undo_plan只接受逐步严格追加的Modify Selection及Change: Name，原栈前缀必须完整一致、相邻操作之间不得有未记录步骤，合并/裁剪/其他名称拒绝。按这些具体步骤构造逆序计划，绝不按提交数估计Undo数量。

## 两次真实验证与边界

第一批812ba98e47b24647b98ca2480db2a84c产生了完整历史记录，但在其运行期间修改了MCP源码，导致implementation_sha256变化。撤销记录5cda899e799147be83831c9e6457af30在派发前因context不匹配拒绝、0次Undo；历史内容相同不掩盖版本变化。原测试值通过CAS反向提交清理，报告history_version_rejection_cleanup.json。

源码稳定后新批a0a50e3367dc4692ad34a402153576dc两项提交逐项读回通过。受限脚本hammer_batch_undo_probe.py要求UUID test地图、批次文件SHA、精确步骤/属性/进程上下文匹配；持锁逐步Undo，派发前落盘、派发后核对完整undo列表/redo数量变化/目标属性和非布局上下文，每个动作不符就停止。相同批次的active记录阻止再次派发。CLI失败返回非零；无自动重试、无Save。

撤销a67fac52ecd145fbb7fdd5d4aa98fb34验证四步：
- property：步骤 30 / Change: Name，撤销后undo数量 15
- selection：步骤 29 / Modify Selection，撤销后undo数量 14
- property：步骤 28 / Change: Name，撤销后undo数量 13
- selection：步骤 27 / Modify Selection，撤销后undo数量 12

独立最终复查：两个目标全部属性等于batch.before；selected_entity_guid等于selection_before；完整undo列表等于首次选择前列表。源SHA6614e9746a6dc654ae57e3c6a0c74b46c15f72c12acfed992af87ccb35c900d6、原图SHAf489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e均未变化。当前dirty候选23/saved5，不代表clean。Redo栈新增本次撤销步骤，并未恢复为最初Redo内容；full_map_rollback_verified=false。

183测试（182通过/1符号链接权限跳过），覆盖历史归属/数量边界、按记录生成选择/属性步骤及插入未知历史拒绝。最后CLI退出码整理后做py_compile和diff检查；功能实机与全测试在此前同逻辑完成。

私人证据history_stack_layout_probe.json、history_steps_probe.json、history_snapshot_verified.json、history_undo_preflight_conflict.json、stable_history_batch_cycle.json、history_aware_final_validation.json和两个batch_probe_runs/rollbacks目录，均在C:\CS2_Temp，不提交原始内存。

## 剩余工作

本轮只是隔离targetname测试批次的目标属性/选择/undo栈恢复，公开工具仍105；任意属性、隐藏/嵌套实体、步骤合并、异步中断/进程崩溃后恢复、地图完整语义/元数据回滚均未验收。读回到Qt派发仍非原子且人工UI编辑不受MCP锁约束，因此未开放生产批量写入，native_compatibility仍空。下一步先验证部分执行停止的日志与按确切已完成步骤恢复，再接实际受限执行工具。其他玩家上下文/CS2Fixes/声音/依赖快照/完整光照目标继续保持。
