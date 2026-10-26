# 隔离地图的 targetname 修改、保存与撤销验证

2026-10-27。本轮完成一次实际属性往返，不代表通用批量执行或完整地图回滚已经完成。
未新增公开属性写入工具；实验IPC和测试脚本仅支持UUID隔离test地图及生成的`mcp_probe_*`名称。

## 三层状态

1. Qt编辑框缓冲：输入文字可能尚未提交给Hammer文档。
2. Hammer内存文档：提交后由Outliner名字、属性绑定和文档世代变化交叉验证，可Undo/Redo。
3. 磁盘.vmap：只有明确执行保存后才比较文件内容。文件哈希未变不能证明没有内存修改。

测试地图：`test/maps/__mcp_edit_tests/bc1d170dd26541cf80f946e324a3beca/untitled_2.vmap`。
原始`test/maps/untitled_2.vmap`始终未改，SHA仍为
`f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e`。

## 实际结果

测试名：`mcp_probe_proxy_20261027`。
保存后确认对应实体GUID为`657b42df-8155-4005-9f33-8ff4072e6c70`。

| 步骤 | 内存targetname | 文档/已保存世代候选 | 磁盘快照 |
|---|---|---|---|
| 打开隔离副本 | 空 | 1 / 1 | 初始f489… |
| 提交属性 | 测试名 | 2 / 1 | 仍为初始f489… |
| 保存修改 | 测试名 | 2 / 2 | 712c… |
| Undo | 空 | 3 / 2 | 仍为712c… |
| Redo | 测试名 | 4 / 2 | 仍为712c… |
| 最终Undo | 空 | 5 / 2 | 仍为712c… |
| 保存恢复值 | 空 | 5 / 5 | 6614… |

完整修改快照SHA：`712c52c44e98e9b0c460a0def05facb07285ae79da4d32f6168b4daaca8de0fa`。
恢复后SHA：`6614e9746a6dc654ae57e3c6a0c74b46c15f72c12acfed992af87ccb35c900d6`。

安装版dmxconvert转换独立副本后逐GUID核对：21实体中只有上述实体的targetname发生预期变化，
其余实体属性一致。最终保存恢复值后，21实体全部属性一致，两条I/O的业务字段一致。
两条I/O的存储GUID在保存时重新生成，不能将文件差异全部视为目标属性差异。

真实MCP `cs2_map_snapshot_compare`比较初始/恢复快照：25个节点，无缺失、增加或节点内容差异，
变换、网格流、子节点顺序均一致；节点规范化SHA均为
`95a85f629741b06d3c87f999b3d50abe75c33290be1171b80a73fcc3d3ef6c34`。
比较政策只省略类型为elementid的存储id，仍保留顺序、类型和标量。
metadata_equal=false、full_rollback_verified=false，未将元数据差异隐藏或降级成完整成功。

## 通过的提交路径

固定Qt适配器重新定位targetname所属CQPropRow/CPropItem_Attr，核对行反向指针、真实键名、
当前值、唯一控件及共享Outliner选择，拒绝复用调用者对象地址。
Python控制器检查四个依赖DLL完整磁盘SHA/加载头、配置、唯一文档和进程身份；
原生适配器另限制UUID test地图、生成名称及固定Qt/propertyeditor ABI。

名称编辑框的focusProxy是直属CQEntityNameCombo，不能要求QApplication的焦点对象一定等于QLineEdit。
适配器仅接受编辑框自身或其直属父控件作为代理目标，拒绝循环、过深或越界代理。
使用Qt setActiveWindow进入窗口活动生命周期、setFocus进入编辑焦点，再重新定位核对控件。
使用selectAll/insert产生用户编辑信号，并排队returnPressed/editingFinished。
排队通过Qt自己的receiver生命周期管理；文字回调后不再解引用旧控件。
返回仅表示调用/排队返回，实际提交由后续独立读取验证，未知结果不自动重发。

首次setText+editingFinished以及insert+editingFinished只取得控件文字变化，未取得文档提交证据；
两次输入都按预期值校验后清回空值，未用Undo猜测恢复。后续严格焦点检查曾在插入前拒绝；
只读诊断发现代理焦点以及Qt焦点指针为空，修复活动窗口/代理检查后才通过实际文档提交。
两次全控件预检拒绝的原始详细原因未完整保留；控制器随后改用针对性的原生只读预览，
同时保留四DLL哈希、唯一文档/选择/字段值及前后预检，不再依赖全应用分页扫描来批准实验。

测试脚本：`scripts/hammer_targetname_probe.py`。先持久记录再派发，记录预览、参数、响应和未知阶段。
确认修改前还会做独立原生预览和再次预检；响应失败返回非零状态，不自动重放。
本轮最终运行桥接SHA：`2282f05a4d854906b6af27ef18166b452f327a3c515ddf4ff1aab5674f60789e`。
常规原生偏移写入仍被拒绝，未新增native兼容profile。

## 证据与复现位置

当前历史测试PID7132，下一轮重新验证创建身份，不复用地址。
配置：`C:\CS2_Temp\mcp_build_jobs\editor_probes\bc1d170dd26541cf80f946e324a3beca\project.json`。

- 主实验记录：`property_probe_runs/adb0ed53f42d480ca5bfa1daa3975e48.json`，已追加独立验证及证据SHA。
- 保存修改808717ab7e04494bb07b9a08dbd3ab1c；Undo800ac78f97fb438599fb8597d0e0b546；
  Redo13a6feb313d94792b6dde9a8a0202dd7；最终Undo53229afd301b4b6e8667320fb6dc333e；
  保存恢复d64f2d69baf440009979ae3817311d02，记录在state_root/edit_probe_runs。
- `C:\CS2_Temp\targetname_proxy_after.json`：首次内存提交证据。
- `targetname_disk_comparison.json`、`targetname_undo_readback.json`、`targetname_redo_readback.json`、
  `targetname_final_undo_readback.json`、`targetname_rollback_comparison.json`：各阶段证据。
- `targetname_strict_rollback_stdio.json`：严格实际MCP节点比较；`targetname_cycle_final_session.json`：
  当前唯一隔离文档、原生写入拒绝及线程派发自测。

156项Python测试：155通过、1项符号链接权限测试跳过；Release构建和dispatch/bootstrap原生测试通过。
新增原生用例覆盖隔离路径/名称限制、错误属性行/反向指针及代理链截断/循环。
测试脚本语法检查通过。只有本地改动，不推送第三方资产或私人配置。

## 尚未完成

未形成通用批量属性执行器、实体GUID实时绑定、逐项失败回滚或全地图回滚证明。
Qt行标识仍非实体GUID；单次保存后定位到GUID不能推广为任意地图的预先身份匹配。
本轮没有对该新快照编译/加载，后续继续将已验证的属性执行与构建任务、实机验证串联。
完整光照仍受已记录的虚拟GPU限制，其余目标也保持未完成状态。
