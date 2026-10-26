# Hammer 未保存状态调查（2026-10-26）

当前仅静态分析，不是已验证的dirty读取API；不得据此启用批量写入或兼容profile。
目标安装hammer.dll SHA-256：`5901a11ceb483a2a8af05ec576eb5485b96adcb3779875ca3939fe67b28b0de1`。
旧IDA副本与当前文件不同，已创建独立 `C:\cs2_tool_mcp\ida_db\hammer_20261022.dll`。

## 已完成静态工作

- 当前PE RTTI定位CMapDoc主虚表RVA `0x1766188`，CMapDocHistory `0x1765E00`，
  CHammerApp主虚表 `0x1DF2E90`；不凭旧函数地址相同就批准整版布局。
- IDA批处理初次仅分析首基本块，产生JUMPOUT伪代码；已按x64异常表的链式unwind合并函数块后重做。
  脚本、范围、块表、反编译JSON和日志均在上述分析目录的 `*hammer*dirty*` 文件。
- `hammer+0x97F9C0(manager, doc)`：遍历manager的count(+0)/array(+8)，bucket步长0x38；
  bucket的文档数+8、数组+0x10，entry步长0x20、doc指针+0。
  匹配后返回 `entry.qword(+0x10) > bucket.qword(+0x28)`。
- `hammer+0x97F840(manager, doc, force)` 在允许条件下增加bucket的+0x20序号，并写entry+0x10。
- `hammer+0x886870(doc, mode)` 查询0x97F9C0；必要时还查询关联文档。
  这表明仅检查主文档自身还可能漏掉关联资源，不能将单个比较当成完整保存冲突检测。
- 相关manager全局指针在 `hammer+0x21DEE70`；尚未追踪所有保存清理/关联文档路径。
- ToolSystem2_001注册回调RVA `0x122FB0`，从静态工厂指令推导CHammerApp候选存储RVA
  `0x677E450`；现有源码的0x677F440不能默认继续使用。尚未在加载Hammer的进程验证该候选。

## 尚待验证

隔离地图：保存后→改属性但不保存→Undo→Redo→保存，比较UI、主/关联文档序号与磁盘hash。
确认后才实现实时文档快照与批量事务，未找到注册项时必须返回unknown，不返回clean。

## 启动与电脑操控

用户建议后，本轮已用 `-tools -addon test -insecure -allow_third_party_software` 重启一次测试CS2，
实际进程参数确认该开关存在。重启前已核对身份且无Hammer/Pet/MET/ModelDoc加载，未关闭编辑文档。
CE MCP成功连接新进程并注入本地桥接，桥接自检/写入拒绝复测通过。
computer-use截图仍返回 `FrameArrived timed out` / `window capture timed out`；不能宣称开关已修复捕获。
旧实例曾可读取Asset Browser的UIA文本，但点击返回coordinate input geometry is unavailable。
不得在没有新观察的情况下继续用旧坐标；可以使用CE普通只读内存接口辅助后续分析。

## 2026-10-26 只读实机App候选核对

Qt启动Hammer后，当前历史PID22360的hammer基址0x7ffb48850000。
base+0x677E450首qword确实等于base+0x1DF2E90，与静态CHammerApp主虚表匹配；
+0x58候选会话计数0、+0x60候选数组0（未打开地图）。旧base+0x677F440首qword为0。
这证实当前App存储候选；没有验证非空会话布局/文档保存状态，不修改旧偏移或批准写入。
base+0x21DEE70首qword指向模块内base+0x24D64C0，不能直接把这一位置当作count/array；
dirty manager的真实对象/字段仍需结合反编译核对，返回unknown。
报告C:\CS2_Temp\hammer_current_app_probe.json。绝对地址仅本次观察，不复用。

## 2026-10-26 管理器解引用与只读观察工具

上次被用户中断的探针实际留下hammer_dirty_manager_probe.json，核对历史PID22360：
global+0x21DEE70确实是指针，解引用后manager=base+0x24D64C0；manager+0为count=0、
+8为array=0。此前把这个模块内地址疑似当作虚表只是未确定假设，现已排除该误读。
此结果只证明当前空状态与静态布局相符，不证明非空状态dirty比较已验证。

新增Hammer工具cs2_hammer_layout_observe：校验当前模块SHA和加载PE/App主虚表；
有界读取候选会话、文档地址、分组与世代原值，并重复比对所有读取。
不调用任何编辑器函数，不判断clean；所有结果dirty_state=unknown/safe_to_write=false。
不把重复读取相同当作主线程原子快照，也不把候选文档地址当作已验证操作句柄。
非空结构已用内存fixture验证解析边界，尚无实机非空文档证据。

真实stdio返回空会话/空dirty分组、3个读取跨度重复一致；PID22360及模块SHA匹配。
报告C:\CS2_Temp\hammer_layout_mcp_observation.json。
89工具/Hammer51/bridge38；98项Python测试通过（新增3项涵盖空状态unknown、
非空世代原值、计数/虚表/并发变化拒绝）。
下一步仍需隔离地图的保存→修改→Undo→Redo→保存与关联文档验证，不能提前开启批量写入。

## 2026-10-26 非空文档身份及实际地图路径

准备部署文件选择适配器前重新观察当前PID26192，发现已非空：
1个CHammerEditorSession、1个dirty分组。重启前置检查因此失败，未停止/重启进程。
未推断是谁打开文件，也未对该现有文档执行编辑或保存。
电脑操控只读list_windows返回Hammer - [cs_script_demo.vmap]。
内存路径读回test/maps/cs_script_demo.vmap，和配置默认untitled_2.vmap不同。

当前版本链路实机核对：
- session主虚表RVA0x1DF74E8，RTTI .?AVCHammerEditorSession@@。
- wrapper主虚表RVA0x1DFA7C0，RTTI .?AVCMapDocSession@@。
- document=wrapper+0x10，主虚表RVA0x1766188，RTTI .?AVCMapDoc@@。
- document+0x6A0为UTF8路径指针，指向cs_script_demo.vmap绝对源路径。
- dirty entry文档指针与document相同，generation候选1，saved候选1。
  未进行属性修改/Undo/Redo/保存往返，1/1不解释成完整clean证明。

hammer_layout.py新增主虚表/RTTI/路径验证，有界UTF8逐页读取并重复比对所有实际字段；
完成后再核对管道PID。路径数据与对象身份已实机读回，原子性和dirty语义仍不保证。
cs2_session_selfcheck在独立只读版本布局匹配时读实际文档路径，不要求开启任意原生调用。
一个有路径的会话才返回current_map；多会话或无路径时不猜测活动文档。
布局失败保持connected=true并单独报告current_map_error，不误标整个连接断开。
配置地图继续明确configuration_only_not_current_editor_state。

真实stdio自检报告C:\CS2_Temp\mcp_nonempty_document_selfcheck.json，
current_map=.../test/maps/cs_script_demo.vmap，writes_enabled=false、hammer_dirty_state=unknown，
写入拒绝与无害跨线程自检复测通过。原始探针hammer_nonempty_first_observation.json。
103项Python测试通过（补充RTTI不符/无效UTF8拒绝、配置与实图分离、多文档不猜测、
布局失败不误标断连），原生测试继续通过。MCP仍90工具。
现有地图保留，不得为部署新桥接直接关闭该会话。
