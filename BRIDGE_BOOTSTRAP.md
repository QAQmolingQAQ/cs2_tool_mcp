# 桥接启动与卸载边界（2026-10-26）

## 修复后台自动初始化遗漏

源码审查发现：DllMain/InitThread已移除初始化，但IpcPipeServer::ServerThread仍直接调用
HammerBridge::Initialize()。如果注入时Hammer或其他编辑器模块已加载，仍可能触发工厂/旧RVA。
因此此前“启动仅IPC”的描述不完整，不能用当时initialized=false推导所有启动路径都安全。

现已移除ServerThread中的Initialize。默认启动只建立诊断IPC；显式initialize请求仍需版本
兼容attestation。桥接版本更新v0.2.1，API/协议仍1。
Release构建SHA3f4c54dfc7af4d4454426aa537123c5af3bda0b27623730757b59432a16b4303。

新增独立原生bootstrap_test及fake_hammer测试DLL：
1. 在独立测试宿主预先加载名为hammer.dll且带CreateInterface计数器的测试模块。
2. 启动实际IpcPipeServer，并通过真实命名管道完成ping。
3. 无attestation的initialize请求必须被桥接拒绝。
4. 再次ping成功，工厂调用次数保持0，bridge未初始化。
测试使用独立CS2ToolMCP_BootstrapTest管道，不连接或替换当前游戏管道。
实际输出PASS real pipe startup + ping + rejected initialize; factory calls=0。
CTest名称diagnostic_bootstrap，超时15秒；既有dispatch_lifetime测试也继续通过。
这验证进程内真实服务器启动路径，不是源代码字符串匹配测试。

## 当前进程未部署新版本

当前历史PID26192仍加载v0.2.0，并打开cs_script_demo.vmap；不尝试热卸载或重启。
真实MCP复测仍可读地图、写入拒绝/固定主线程自检通过。
报告C:\CS2_Temp\mcp_bootstrap_fix_pending_live.json。
磁盘更新不等于加载模块更新，新启动行为尚未在当前游戏实例运行。
103项Python测试通过；原生bootstrap/dispatch测试及Release构建通过。

## 不批准现有关闭接口用于热卸载

IpcPipeServer::Stop目前只置running=false、尝试取消服务器同步IO，并detach服务器线程；
客户端线程本就detach，缺少完整的活动请求/线程退出证明。
它不提供可用于FreeLibrary的静默屏障，不能凭Cs2Tool_Shutdown返回就卸载旧DLL。
取消同步IO的线程句柄权限也应另行复核，不能把Stop等同于请求已全部终止。
本轮未调用该关闭接口，未建立双版本共享管道，未卸载模块。

下一步可继续独立完善编辑前哈希/会话冲突检查；未来若实现在线升级，必须有独立
停接入、取消阻塞IO、等待客户端/回调完成、模块身份与回滚协议及实测证据。
现有文档的dirty/Undo/Redo/保存语义仍待验证，目标没有完成。
