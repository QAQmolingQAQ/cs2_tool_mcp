# 分模块 MCP 与 IDA 端口（2026-10-14）

CS2 MCP 现在按 `--scope` 分别启动，服务实现复用现有桥接 DLL。
`all` 保留原来的 78 个工具契约；模块组不暴露其他编辑器的高层修改工具。
共享诊断接口会重复出现，不把各组数量相加作为新增工具数。

| 客户端名称 | scope | 工具数 |
| --- | --- | ---: |
| cs2-hammer | hammer | 48 |
| cs2-particles | pet | 18 |
| cs2-materials | met | 9 |
| cs2-models | modeldoc | 13 |
| cs2-assets | assets | 5 |
| cs2-runtime | runtime | 28 |

MET 组当前提供连接/接口/原生绑定检查；9 个工具不代表材质参数写入已完成。
编辑器通用命令的 module 默认值绑定到本组，传错模块时拒绝执行。
完整调用以 Windows 命名互斥量跨 MCP 进程序列化，避免历史事务相互穿插。
这不限制高级 runtime 工具原有的底层能力。

## IDA 固定端口

| 分析模块 | 端口 | 数据库 |
| --- | ---: | --- |
| Hammer | 13341 | hammer.dll.i64 |
| Pet | 13342 | pet.dll.i64 |
| MET | 13343 | met_clean_20261014.dll.i64 |
| ModelDoc | 13344 | modeldoc_editor.dll.i64 |
| particles.dll | 13345 | particles.dll.i64 |
| scenesystem | 13346 | scenesystem.dll.i64 |
| tier0 | 13347 | tier0.dll.i64 |

权威表在 `config/ida_modules.json`；对应客户端 URL 是
`http://127.0.0.1:<port>/mcp`。CS2 六组使用 stdio，不占 TCP 端口。
七个 IDA 数据库都已保存插件端口与自动启动设置。
本轮 Pet、MET HTTP MCP 已实际在线，并读回数据库身份；其余五个按需启动。

## 配置与验证

已同步 Codex 的用户 config.toml、Trae User/mcp.json 和仓库本地 mcp.json。
原通用 cs2-tool/ida-pro-mcp 在 Codex 中禁用，Trae 改为明确模块名；
其他配置保留，私人备份留在配置目录或本地 scratch，未提交。
配置格式参照 [官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。
当前聊天已加载的旧工具需客户端重新加载后才能改用新名称。

- `python scripts/check_module_mcp.py`：六组真实 stdio 初始化、工具清单、错模块拒绝及离线目录查询。
- `python scripts/ida_module.py status met`：核对 HTTP MCP 与数据库身份。
- `python scripts/ida_module.py start met`：隐藏启动该分析库；固定端口被未知服务占用时拒绝启动。
- `configure <模块>`：在数据库未被打开时保存端口。不要对正在使用的数据库运行批处理配置。

58 项测试通过，包含跨进程互斥量验证。此次未重启或编辑 CS2；实时写入能力不因服务拆分而扩大。
只保留本地，不推 GitHub。
