# 持久构建任务（2026-10-26，本地）

这部分归共享 `bridge`，不属于某个编辑器 DLL。现有 `cs2_asset_compile` 保留原契约。
新工具：`cs2_project_info`、`cs2_build_artifact_check`、`cs2_build_start/status/cancel`。

## 使用与工程范围

复制 `config/project.example.json` 到已忽略的 `config/project.local.json`，设置游戏根目录、
测试/正式profile、addon、地图。也可通过工具config参数或 `CS2_MCP_PROJECT` 指定配置。
source必须是该addon下已有 `.vmap`；构建状态目录必须在源/安装addon外。
本机私人配置指向test/maps/untitled_2.vmap，状态在 `C:\CS2_Temp\mcp_build_jobs`。

1. `cs2_build_start(mode="quick", confirm=false)` 返回源码哈希、命令和隔离输出范围。
2. 将返回哈希传给 `expected_source_hash`，再以 `confirm=true` 启动。哈希失配拒绝。
3. 用返回的job_id调用 `cs2_build_status`；客户端可关闭后重新连接查询。
4. `cs2_build_cancel`只表示已提交取消。必须查询到 `cancelled` 和 `process_tree_exited=true`
   才代表已停止。已结束任务不重新取消或重启。

命令行通过真实stdio调用同一工具：`scripts/build_job_mcp.py preview/start/status/cancel`。
start需 `--source-hash`，status/cancel需 `--job`；`--config`可选择工程。

构建复制磁盘地图到 `maps/__mcp_builds/<job_id>/<原名>.vmap`，只写对应隔离产物，
不替换原地图VPK、不保存编辑器文档。**未读取Hammer未保存状态，未冻结依赖素材**，
不能将构建结果视作当前未保存文档的产物。这两个缺口必须在后续编辑/发布流程补齐。

## 生命周期与证据

每个作业保存request.json、state.json、worker.json、launch.json、compiler.log和worker.log。
状态含UTC阶段事件、PID及创建时间、编译退出码、源码/编译器/关键安装文件哈希和产物校验。
日志完整保存；查询仅返回最多64KiB尾部。源码或安装输入变化会阻止成功判定。
同一源文件只允许一个活动任务；未知进程观察错误保留状态，不据超时自动重启。

Windows MCP SDK在客户端关闭时会终止服务的Job及其后代。worker使用桌面shell作为进程父级，
独立于这个Job；不注册系统服务、计划任务或自启动项。无桌面shell则明确启动失败。
编译器通过 `PROC_THREAD_ATTRIBUTE_JOB_LIST` 在创建时归入worker持有的kill-on-close Job，
再恢复执行；取消终止整个Job并等待退出。worker意外死亡也会终止其编译进程树。
API依据：[Microsoft UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)。

快速模式：`-fshallow -world -phys -vis`。实际编译器拒绝 `-f` 与显式partial builder组合，
故不能共用该参数。完整模式：`-f`，运行安装版gameinfo与原生默认builder；仍需校验最终光照。
每个作业独立设置TEMP/TMP，避免系统遗留无效D盘路径导致原生写入失败。

VPK验证全部条目CRC、边界、地图与world DATA、VIS的VXVS块以及已识别的光照贴图组。
CRC与SHA-256均按1MiB块读取，不再把全部条目载荷放入内存；分卷也参与CRC与文件指纹。
目录上限64MiB/250000条，单资源块表上限1MiB；这些是元数据上限，不是包载荷上限。
校验前后比较每个存储文件的身份、大小、修改/变更时间，检测中途替换或更改。
大包CRC及SHA计算期间可响应取消，worker明确记录cancelled，不等待整个文件扫描结束。
CS2新签名的20字节只计签名头，密钥/签名载荷另计；已按实际文件与
[ValvePak读取器](https://github.com/ValveResourceFormat/ValvePak/blob/master/ValvePak/ValvePak/Package.Read.cs)核对。
这里只校验签名结构边界，未做RSA验签或验证VPK的MD5/Blake3摘要段，结果明确标记cryptographic_validation=false。
地图根文件允许合法空DATA块及非空RERL引用清单；world DATA、VIS VXVS、光照DATA须非空。
`artifact_complete`仅表示包内证据；`release_ready`一直为false，尚无发布依赖/游戏实测通过门禁。

## 已验证结果与后续

- 2026-10-26最新82项测试通过（含版本自检），含真实Windows子进程、后代终止、worker意外退出清理、父Job结束后worker存活、
  新Python进程恢复查询、重复构建、源码冲突、退出0但缺产物、完整模式缺光照拒绝。
- 八组stdio启动通过；源码84工具，bridge35工具，其余组数量不变。
- 真实快速构建 `051b1cbe6c7c4043bea8b40a9bf98e47` 成功，退出0，11条目CRC与VIS通过，无光照。
- 真实完整构建 `a216dcaaae564ac891a9556d939f306e` 失败，退出1；日志确认VMware SVGA 3D
  不支持VRAD3 GPU ray tracing；没有VPK，不能宣称完整构建已验收。不关闭或规避光照来制造成功。
- 真实MCP启动后关闭客户端，再由新客户端取消 `ae91ed8aece14954b32ff64560b99b0c`；
  返回accepted，随后查询为cancelled、退出1223、process_tree_exited=true。
- 早期 `d33c55bbbef54c8599d7b6fb7e62f694` 因MCP父Job关闭而中断，是触发启动方式修复的反例。
- 修复后真实MCP任务 `b2b99f92cbd24f468749a8d356df641d` 在启动客户端退出后继续完成；
  新客户端查询为succeeded、退出0、源码/安装输入未变化、11条目CRC与VIS通过。

新增513MiB单条目CRC+SHA测试，其Python tracemalloc峰值低于16MiB；另覆盖分卷/预加载CRC、
分卷缺失/变更、截断签名、空DATA地图根与空VXVS拒绝，以及扫描中取消。
真实MCP复测cs_script_demo.vpk通过（66条目，校验9753842载荷字节，CS2签名头550字节公钥+512字节签名）；
untitled_2.vpk快速模式通过，完整模式仍须光照证据。

尚待：依赖冻结与发布、编辑器脏状态/批量事务、允许版本的写入复核、FGD/脚本检查、
运行诊断及真实地图加载验证。完整目标仍为 `WORKFLOW_GOAL.md`，不能据上述测试标记整体完成。

## 2026-10-26 桥接构建文件的安全替换

build.ps1调用scripts/publish_bridge_artifact.ps1：先复制到按SHA256命名的产物目录，
重新校验，再用目标同目录的唯一临时文件执行File.Replace（首次安装用Move）。
不以Copy-Item直接覆盖已存在DLL。仅共享/锁冲突返回deployment_pending，
其他错误仍失败；已存在的哈希产物若被篡改会拒绝。
输出status、reason、sha256、artifact、destination、running_process_updated=false。
不保证任意外部发布者的并发顺序，也不替换运行中已加载的模块。
这仅完成桥接DLL部署文件这一层，不代表地图依赖发布与游戏实测完成。

PowerShell测试tests/test_bridge_publish.ps1实测文件锁保留旧字节、产物哈希、
解锁原子替换、首次安装、篡改拒绝及候选清理，全部通过。
实际build.ps1成功：磁盘DLL允许原子替换，SHA256
45ecfd58a37382f8c35bfec836945abe0a5eaf68e4c7108218f147b77e240a74。
当前CS2未重启且未注入新模块；实际MCP自检仍连接、initialized=false、writes_enabled=false，
原生写入发送前拒绝验证通过。报告C:\CS2_Temp\mcp_after_atomic_deploy.json。

2026-10-27：新增addon源码树编译前后变化检测，真实RC变更负例拒绝成功及暂存；见BUILD_SOURCE_GUARD.md。未完成不可变依赖镜像/完整外部依赖冻结，不能仅凭guard无变化称全依赖闭合。

2026-10-27：私有源码副本已作为non-release显式private_source_copy配置接持久worker，实际复制取消/发布及加载身份验证通过，详见BUILD_PRIVATE_WORKER.md。默认false、依赖完整冻结与全验收仍未完成。
