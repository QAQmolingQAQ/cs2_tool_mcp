# 版本与会话自检（2026-10-26，本地）

新增共享bridge工具 `cs2_session_selfcheck(config="")`。这是诊断结果与版本校验，
不是当前版本的原生写入已经验收。当前没有任何已复核的兼容profile，原生写入被禁用。

## 返回证据

- 安装/运行游戏的steam.inf版本（PatchVersion、SourceRevision、日期等）。
- 配置中选择的addon/map明确标成configuration_only，不冒充当前活动文档。
- 实际命名管道服务端PID及创建时间；用Windows GetNamedPipeServerProcessId取得，
  不从进程名猜测目标，也不沿用历史PID或模块基址。
- Windows Toolhelp列举的加载模块路径与基址，路径文件的SHA-256及PE标识；
  通过ReadProcessMemory比较加载映像的PE时间戳/SizeOfImage与磁盘头。
  **SHA是加载路径文件的哈希，不是整个内存映像哈希**。
- 新桥接ping返回 `cs2_tool v0.2.0`、bridge API=1、协议=1、PID、addon与launch_map。
  仅提取这两个启动参数，不返回可能包含私人参数的完整命令行。
- 运行addon来自实际进程参数；launch_map仅表示启动参数。当前地图必须用匹配布局读取
  实时文档清单；未匹配时返回null和 `not_read_without_verified_offsets`。

Windows API依据：[Toolhelp模块快照](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot)。

## 校验与限制

`data/native_compatibility.json`存放人工复核的兼容记录。当前profiles为空，
因为Oct22更新后没有完成写入→读回→Undo→Redo复核；不能用“采到当前哈希”自动批准。
profile需要游戏SourceRevision、桥接版本、全部加载的受关注模块SHA、Python实现摘要、
允许的原生方法列表以及实际复核证据。加载模块PE头与磁盘不符也拒绝。
实现摘要覆盖Python服务与数据文件，排除兼容记录自身，避免修改布局后继续用旧批准。

在Cs2Pipe传输层，原生调用、内存写入/分配/释放、初始化、偏移相关文档入口及未知新方法
均须通过校验；拒绝发生在该请求写入管道之前。ping、模块列表与原始只读诊断仍可用。
已批准的方法也不能给未批准的方法提供通行权。没有环境变量或工具参数用于跳过校验。

新版桥接加载时只启动IPC，不再自动Initialize旧偏移；Cs2Tool_Init也仅启动IPC。
桥接对非诊断请求另要求新客户端提供匹配PID/API的每请求attestation，
所以未重载的旧MCP服务不能直接写入或初始化。它是兼容性握手，不是针对自定义恶意客户端的认证边界。
新的Python客户端只在本地兼容记录全部匹配后生成attestation；拒绝时不发送目标写请求。

## 验证与使用

- `build.ps1`以VS18 x64 Release编译通过；生成DLL保留本地，未上传。
- 77项Python测试通过，覆盖版本/模块/PE头/实现/evidence失配、未登记依赖、
  方法级权限、拒绝前零请求写入，以及原有协议不重放测试。
- 八组实际stdio通过；源码85工具，bridge36，其余组不变。
- 实机CS2安装为1.41.9.2 / SourceRevision 11162119 / Oct22；新桥接已注入本轮独立启动的
  `-tools -addon test -insecure` 测试进程。观察过9个受关注模块，加载/磁盘PE头一致。
  没有加载编辑器DLL，未修改地图或编辑文档。
- `scripts/check_session_mcp.py --verify-denial --report <本地文件>` 通过真实stdio读取
  自检，并验证无匹配版本时写请求返回 `NativeVersionError ... blocked before dispatch`。
  它要求已连接且写入受限，不会在已批准可写的会话中执行拒绝探针。
- 最终桥接复测：本轮测试进程PID7328（历史值，不可复用），Asset Browser/test addon，
  initialized=false、native_attestation_required=true。新stdio客户端写请求在Python发送前被拒绝；
  应用中已运行的旧 `cs2_bridge` 客户端直接调用写工具，也收到桥接端
  `native request blocked: current client version attestation required`，未执行写入。

剩余：当前版本的编辑器布局复核、允许版本的原生写入/Undo/Redo实测、活动地图与脏状态读取。
自检和拒绝已通过，不代表P0版本/会话要求或整个WORKFLOW_GOAL已完成。

固定Qt UI适配器qt_open_editor使用单独STABLE_UI_METHODS集合，不冒称只读。
它在Qt ABI/导出检查后只允许四种编辑器启动按钮、唯一匹配/可见启用校验；
不接受函数/对象地址，不打开文档，不赋予任何Hammer/Pet/MET/ModelDoc偏移兼容资格。
原有任意调用及编辑操作仍须完整原生profile；实机写入拒绝复测通过。

实际地图路径现在可在受支持的只读布局中独立校验：单一会话的Session/Wrapper/Doc
主虚表和RTTI及UTF8路径均匹配，真实stdio返回cs_script_demo.vmap，与默认配置地图分离。
多文档/路径缺失/版本不符明确unknown，不以读回路径自动批准写入或dirty语义。
现有100项基线扩展到103项测试，实机写入拒绝仍通过。

2026-10-26补正：ServerThread残留的自动Initialize已移除，v0.2.1经预加载fake hammer/真实独立管道测试证明工厂调用为0；此前仅移除DllMain路径不足以证明所有启动路径纯诊断。当前游戏未部署新版本；详见BRIDGE_BOOTSTRAP.md。
