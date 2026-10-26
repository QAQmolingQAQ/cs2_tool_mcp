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
