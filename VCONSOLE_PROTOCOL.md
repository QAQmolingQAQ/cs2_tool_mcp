# 控制台协议与实机加载状态（2026-10-26）

后续更新：绝对路径加载已实测成功并经独立MCP核验；相对路径失败仍保留，详见
[RUNTIME_VALIDATION.md](RUNTIME_VALIDATION.md)。下文记录此前调查时的阶段状态。

新增bridge MCP `cs2_console_probe(port=29000)`。目标仅为127.0.0.1，连接后通过
Windows TCP四元组表核对服务器PID，并核对桥接进程创建身份；拒绝错进程、未知握手和版本。
只发送随机生成的echo，在PRNT中精确匹配回显，不发送任意用户命令，不重试未知结果。
TCP连接、协议握手、echo成功均不证明地图已加载，输出runtime_map_verified=false。

## 帧边界

实机抓取确认12字节大端头：fourcc(4)、version(uint16)、总长度(uint32)、handle(uint16)。
普通帧版本212；初始CVRB版本2，总长754658字节。
短帧若误解为uint32版本+uint16长度，看起来也能工作，却会在此长包处错位。
本实现保留真正的32位长度，不扫描字节猜测下一个帧头，长包、分片、截断、大小和时间预算均测试。
PRNT正文先经过28字节元数据，再读取NUL终止的UTF8文字。

初步查阅的实现参考：
[oxijoined/vconsole-python](https://github.com/oxijoined/vconsole-python)、
[theokyr/CS2RemoteConsole](https://github.com/theokyr/CS2RemoteConsole)。
这里的帧宽度结论来自本机完整流边界核验，不照搬短包假设；未复制或执行参考项目代码。
原始二进制抓取包含进程/路径等运行数据，仅保留在本机临时目录，不提交。

当前本轮PID8408端口29000：AINF/CHAN/ADON/CVRB/PRNT完整解析、随机echo成功，
实际MCP报告C:\CS2_Temp\vconsole_probe_mcp.json及vconsole_and_flat_build_mcp.json。
另一个24981监听端口无已验证握手；不能把它称为文本netconsole，也没有发送文本探针。
文本netconsole是另一种连接格式，当前没有已验证的文本端点，不自动回退或向未知服务写入。

## 地图加载仍未完成

原快速构建759ba3afef6846bab69efa5590c1679d成功/VIS有效，但
`map __mcp_builds/<UUID>/untitled_2`返回invalid map name，未加载。

新构建改用28字符平面名mcp_<24位UUID>，源地图仍复制隔离，xb独占创建保护碰撞文件。
这方便未来显式运行安装，**单凭平面名不保证可加载**。
实际MCP新任务49bbcf0f73014a9dac5bd2657f2c324d快速编译/打包/VIS验证成功，
map_name=mcp_49bbcf0f73014a9dac5bd265；原图与编辑后源图未变。
但`map <该名>`及带addon=test参数均返回invalid map name。
本机help证实map存在，addon_tools_map/addon_play不存在，不能臆测其用法。

`path`只读查询看到CONTENT与DEFAULT_WRITE_PATH含test addon，GAME搜索路径没有其构建目录。
这提供了下一步调查依据，但不证明是唯一原因；需显式工程运行安装/挂载并验证地图解析。
当前不复制覆盖基础游戏文件，不将失败命令自动重放，也不声称运行测试通过。
本地加载回执runtime_load_759ba3afef6846bab69efa5590c1679d.json、
runtime_load_49bbcf0f73014a9dac5bd2657f2c324d.json和runtime_addon_map_load.json保留失败。

120项Python测试通过，包括长包分片、错误边界/时限、错误握手/进程不发送命令、
TCP身份歧义拒绝以及平面快照碰撞不覆盖。唯一工具94个，bridge40。
本轮仅保存本地改动，GitHub仍为上轮已核对的e3f55f0；后续不自动推送。

2026-10-27：真实会话初始PRNT回放在第11987帧后才echo；统一观察帧数上限100000，保持原5秒/16MiB/单帧限制与精确标记。证据及加载衔接见BUILD_PRIVATE_WORKER.md。
