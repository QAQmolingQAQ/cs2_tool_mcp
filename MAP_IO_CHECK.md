# 保存后地图的FGD/I/O检查（2026-10-26，本地）

工具 `cs2_map_io_check(config="", profile="", max_issues=100)` 归hammer.dll服务。
它只检查工程配置指定地图的磁盘副本，不保存/修改Hammer，不替代实时文档检查。
当前86个工具；Hammer组50个。`scripts/check_map_io_mcp.py`通过真实stdio调用同一工具。

## 流程与已实现检查

1. 复制 `.vmap` 到状态目录checks/<作业ID>/input.vmap，复制前后核对源码SHA。
2. 用安装版dmxconvert转换副本到明确指定的独立map.kv2输出路径；绝不省略-o，
   因为工具帮助明确说明省略输出会覆盖输入。不使用-upconvert选项；日志保留。
3. 解析DMX keyvalues2 4、内嵌对象/扁平element引用、entity_properties与connectionsData。
4. 载入安装版csgo.fgd及其include，解析类/继承、input/output类型及属性类型（含resource:vjs）。
5. 检查静态I/O目标、过滤器、target_destination属性/输入参数、point_template引用；
   检查已声明输入的整数/布尔/浮点/向量/颜色参数及连接延时/触发次数。
6. 对ForceSpawnAtEntityOrigin指向的info_target，检查它是否属于maker引用模板的TemplateNN集合。
   缺少覆盖记为用户要求的工程策略警告，不宣称这是所有地图通用的引擎硬性要求。
7. 检查后再次核对地图、FGD与converter哈希，保存结构化report.json和转换日志。

include限定在安装game目录，检测include与继承环及缺失基类；不静默忽略坏结构。
转换超时120秒，文本上限128MiB，token上限400万，嵌套上限128层；超限返回ok=false。
问题展示有数量上限，但error/warning/info总计仍完整，截断不改变passed判定。

## 结果含义及未覆盖范围

- ok：解析/检查过程成功；passed：已覆盖的静态检查没有error。
- FGD未声明的输入/输出仅作warning。真实info_player_start的FGD没有通用I/O声明，
  因此不能把未声明直接当作引擎不存在该接口。
- !self可静态定位；!activator等依赖运行事件的目标标记deferred，不误报为磁盘实体缺失。
- FGD的api参数类型没有完整签名时标记unsupported，不强行当作string通过。
- Script实体标记script_semantics_not_yet_validated。尚未验证OnScriptInput回调、脚本入口、
  参数签名、脚本资源依赖、实例/prefab展开、脚本动态创建目标或游戏运行行为。
- coverage_complete与release_ready都保持false；passed不代表整张地图I/O已验收。
- source_basis=saved_disk_snapshot，不能代表Hammer未保存状态，也不能据此批准批量写入。

## 验证

88项Python测试通过，含DMX内嵌与扁平引用、损坏/缺失引用、FGD include/继承/资源类型、
继承环、缺失过滤器/目标、数值类型、动态目标、问题截断及maker模板覆盖。
真实MCP检查test/maps/untitled_2.vmap：21实体、2连接，7份FGD、469个唯一类；
0个error、2个FGD未声明警告（info_player_start上的OnUser1/Kill），没有脚本实体。
源码SHA仍为f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e。
本轮报告在 `C:\CS2_Temp\mcp_build_jobs\checks\a83c6bfbaf6640ec8e36fd6e9325f856\report.json`。
八组stdio启动验证另见CURRENT_STATE/PROGRESS。只保留本地，未提交或推送。
