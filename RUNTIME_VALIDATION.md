# 构建后的运行验证（2026-10-26）

## 新工具与工程范围

`profile.runtime`是可选的显式配置；缺失时不自动选择安装目录或运行连接。
示例位于config/project.example.json，test profile含：

```json
"runtime": {"staging_root": "game/csgo/maps", "console_port": 29000}
```

staging_root必须为游戏安装内现有maps目录；release profile不允许此测试暂存操作。
配置解析前后核对同一份原始内容哈希，避免用旧配置范围配新配置哈希。

bridge工具`cs2_runtime_stage_build(job_id, config='', profile='', confirm=false, expected_artifact_hash='')`：
验证成功构建、当前源码、安装输入、VPK结构/CRC与任务哈希；只接受唯一平面mcp_地图名和单文件VPK。
默认预览，确认需传入产物哈希。用同目录临时文件、fsync、完整读回和不替换已有路径的硬链接发布。
既有文件不覆盖；只有已完成回执且哈希一致才能返回already_staged；未完成回执不自动重试。
发布中源图/配置变化会保留pending回执并返回失败，不伪称完成。
这不是通用发布替换或依赖闭合检查，且不会自动加载地图。

bridge工具`cs2_runtime_diagnostics(config='', profile='', job_id='')`：
绑定当前桥接进程与TCP服务器四元组、PID创建身份及VConsole2握手；只发送固定status/getpos/
sv_cheats/meta version/css_plugins list查询。返回经过筛选的地图、世界坐标/cvar和命令可用性，
不返回hostname、Steam标识或玩家名。控制台流共享且非原子，不声称对象父子/局部坐标或声音寿命已验证。
带job_id时检查构建/源文件/产物哈希，并将实际加载地图名与该任务比对。

## 实机加载的失败与成功

任务49bbcf0f73014a9dac5bd2657f2c324d：快速构建成功，VIS=true、lighting=false。
地图名mcp_49bbcf0f73014a9dac5bd265；VPK SHA
10b6fdf4c98fe647fb09000afae99034fd3fc495b738083aa1b75d00a7cc0afb。
实际MCP将其唯一副本安装到配置的game/csgo/maps，回执runtime_staging/<job_id>.json。
仅安装后使用相对地图名仍返回invalid map name；**不能声称暂存操作解决了加载问题**。

随后只读静态检查engine2.dll中invalid map name字符串引用及校验分支：
字符串RVA0x6122C8、引用0x1CE863，验证函数起点0x1CD5E0及其连续分块。
可观察到FixSlashes/StripExtension、追加.vpk、GAME查找、V_IsAbsolutePath及绝对路径分支。
这只用于理解命令规则，没有调用这些地址，未创建其原生写入profile。

使用构建产物的绝对路径执行一次VConsole map命令后，实际日志出现：
Loading map、Spawn Server、Created physics、Host activate，地图名均匹配。
相对路径在该运行实例仍失败的完整原因尚未确定，不仅归因于名称或目录层级。
加载命令由本地受控验证脚本发送；尚未收进专门的MCP加载任务控制器，不暴露任意console command。

独立的**实际MCP** cs2_runtime_diagnostics随后读回：

- runtime_map_verified=true：loaded spawngroup为预期地图，本地loopback客户端已连接。
- 世界位置[0,0,0.015625]，世界角度[0,0,0]，sv_cheats=true。
- meta/css_plugins命令不可用，plugin_versions为空；不能据此断言插件一定没有安装。
- local_position=null，parent_graph_verified=false，sound_lifetimes_verified=false。
- release_ready=false。所验证的是地图名/本地连接和保留的磁盘产物哈希，不是内存映像或视觉质量证明。

原maps/untitled_2.vmap SHA仍为
f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e。
Hammer隔离文档仍打开，当前本轮PID8408；后续必须重新核对进程/文件，不复用地址。

## 已知运行限制及证据

日志报告地图图标/截图、雷达、overview、camera_nodes和地图cfg缺失，还有Steam/本地化诊断。
本轮地图加载与坐标烟雾检查通过，不等于无警告、完整发布、完整光照或玩法验证通过。
基础游戏目录新增的唯一测试VPK保留供运行验证，没有覆盖原文件；清理需核对回执、哈希和卸载状态。

证据在本地C:\CS2_Temp：runtime_stage_preview.json、runtime_stage_installed.json、
runtime_staged_load_observation.json（相对路径失败）、runtime_absolute_load_observation.json（加载日志）、
runtime_diagnostics_mcp.json、post_runtime_hammer_session.json。原始status日志含运行身份信息，未纳入仓库。

124项Python测试通过，含配置范围、碰撞不覆盖、幂等回执/未完成回执拒绝、
源码变化、控制台协议与查询摘要边界。唯一工具96个，bridge42。
加载任务接口的后续实现见下节。依赖检查、通用属性执行与完整回滚、完整光照及其他运行诊断仍未完成。
本轮只保存本地，不自动推送。

## 持久加载任务：实际MCP验证

新增bridge工具cs2_runtime_load_start/status。start默认预览；确认时要求产物SHA和精确的
当前运行地图，范围限已成功构建且源图/安装输入/产物未变的非release工程。
进程与本地loopback连接验证后取得该进程加载锁，重新查询当前地图并再次核对输入。
仅使用已验证产物绝对路径，不接收任意console command。

发送前创建runtime_loads/<UUID>.json和进程active指针，记录源/配置/产物SHA、PID创建身份、
原地图及确认参数。map命令批次得到唯一echo回显后仅标记requested，不标记loaded。
status使用固定只读诊断确认目标地图和客户端；它从不发送或重放map命令。
结果未知保留unknown并阻止后续重复加载，只有状态查询证据可恢复为loaded。
同一目标已加载时记录loaded但不再发map。没有提供伪取消或热卸载操作。
历史current_map预览值移入previous_map，状态结果current_map来自最新观察，避免显示旧地图。

复现入口scripts/runtime_load_mcp.py，支持preview/start/status及独立报告文件。
真实MCP新构建任务ac72ac0b72a84b3a8ace4022403800c6快速编译成功，
产物SHA8c84982801783f7d72a5935793217fe3b7099493f83ec347962b096fd352169f。
preview核对原运行地图mcp_49bbcf0f73014a9dac5bd265，start实际发送一次绝对路径加载，
生成load_id=23b20a7a43df4d78a0125bdfc465bdf1，返回requested/批次确认，runtime_map_verified=false。
该stdio客户端退出后，新客户端status读回同一持久任务，确认mcp_ac72ac0b72a84b3a8ace4022、
本地客户端和世界位置[0,0,0.015625]，状态loaded/runtime_map_verified=true。
随后实际MCP重复start生成观察记录0461038c715b4d4ab09a5402c64ab6df，
load_command_issued=false、dispatch_started=false、command_sent=false，没有再次切图。

本地证据runtime_load_task_preview.json、runtime_load_task_start.json、runtime_load_task_status.json、
runtime_load_already_loaded.json以及mcp_build_jobs/runtime_loads/<load_id>.json。
129项Python测试通过，含发送前落盘、未知结果不重放、只读状态恢复、错误地图/哈希拒绝、
获取锁期间地图变化拒绝、精确命令帧及ack、已加载不重发和进程切换。
唯一工具98个，bridge44。原地图SHA保持f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e，
Hammer仍为原隔离文档；本轮不推送。加载任务通过不提升release_ready，也不替代完整目标验收。

## 2026-10-27：诊断批次完整性

固定诊断命令追加独立结束echo标记，仅在起止标记之间收集输出。缺少结束标记、超时、EOF或预算耗尽均不能返回ok；diagnostic_batch_completed明确区别完整返回和部分输出。保留精确进程绑定、输入哈希复核与共享控制台非原子范围，不把结束标记当作整图或画质验收。

新增3项测试覆盖结束标记前后的排除、起始后超时、帧与行预算；159项测试通过（1项符号链接权限跳过）。直接调用当前源码的诊断函数对实际PID7132/创建时间134375068170658822实测，完整标记返回成功，客户端loopback已连接、observed_maps为空，因此runtime_map_verified=false。私人报告C:\CS2_Temp\runtime_completed_batch_probe.json；使用独立私人配置副本，未改原工程配置，未切图/设置cvar。此轮不是重载后的公开MCP服务验证。

仍需查明当前无地图名输出的实际运行状态；不得仅根据observed_maps=[]推断可安全切图的空闲状态。现有加载器保留单一当前地图前置条件。
