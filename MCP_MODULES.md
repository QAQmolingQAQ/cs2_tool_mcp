# 按 DLL 拆分 MCP（2026-10-14）

划分依据是目标 DLL、文档对象与原生入口的归属，不能根据“粒子/模型/材质”功能名称分组。
每个现有工具的主归属明确登记在
`mcp_server/hammer_mcp/data/tool_ownership.json`；新增工具未登记或重复登记会报错。
原 `all` 保留 78 个工具契约。

| 客户端名称 | 目标 DLL / scope | 当前工具数 |
| --- | --- | ---: |
| cs2-hammer | hammer.dll / hammer | 49 |
| cs2-pet | pet.dll / pet | 17 |
| cs2-particles | particles.dll / particles | 7 |
| cs2-met | met.dll / met | 10 |
| cs2-modeldoc-editor | modeldoc_editor.dll / modeldoc_editor | 14 |
| cs2-scenesystem | scenesystem.dll / scenesystem | 5 |
| cs2-tier0 | tier0.dll / tier0 | 5 |
| cs2-bridge | 共享桥接与辅助服务 / bridge | 30 |

通用接口检查被绑定到相应 DLL，连接诊断会重复出现，各组工具数不能相加当作新增工具数。
依赖其他 DLL 不自动改变工具的主归属；目前还没有独立高层操作的 DLL 组仅提供接口/加载信息，
不把服务已建立当作已实现安全写入。

## 粒子功能的三个归属

- Hammer 的 `cs2_particle_set_definition` 修改地图中的粒子实体属性并刷新 Hammer CParticleHelper，
  使用 Hammer 文档与撤销链，归 `hammer.dll`。
- 实时粒子文档、函数节点树、参数读取与保存值对照，归 `pet.dll`。
- 从 ParticleSystemMgr003 / Schema 得到的函数目录与参数查询，归 `particles.dll`。

源码文件解析、外部 resourcecompiler 编译、原始内存诊断属于共享桥接辅助服务，
不是 Assets/Runtime 两个伪 DLL。原按功能命名的客户端项已移除。
跨进程命名互斥量继续保护完整操作，避免历史事务穿插。

## IDA 固定端口

Hammer 13341；Pet 13342；MET 13343；ModelDoc 13344；
particles.dll 13345；scenesystem 13346；tier0 13347。
权威表为 `config/ida_modules.json`。七个数据库已保存端口；
Pet/MET 已读回在线端点的数据库身份，其余按需启动。此次未改变端口。

CS2 MCP 使用 stdio，不占 TCP 端口。Codex、Trae 和本地配置已同步并保留私人备份；
客户端重新加载配置后使用新的 DLL 名称。
配置方式见 [官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

`python scripts/check_module_mcp.py` 验证七个 DLL 服务与桥接的真实 stdio 清单、错 DLL 拒绝及目录读取。
`python scripts/ida_module.py start met` 可隐藏启动对应分析库；status 会核对数据库身份。
configure 只能对未打开的数据库执行。

59 项测试通过，八个 stdio 服务验证通过。此次未操作 CS2，未新增未经验证的粒子/MET 写入；仅留本地。
