# 地图 VPK 的 RED2 输入来源调查

## 实机范围

对私有源码构建任务 `3cf6af8ef7ca4c068115ff0a8c29d614` 的发布 VPK 进行只读检查。先验证 VPK 各条目 CRC，再将条目复制到同一私有 game addon 内的独立 UUID 检查目录，调用游戏自带 `resourceinfo.exe` 和 `input_dependencies.inspect_inputs`。检查结束后再次确认 VPK 存储文件身份未变化。检查副本仅保留本机，不属于仓库。

11 个条目均包含非空 RED2。9 个条目的普通输入检查匹配，其中地图 `.vmap_c` 记录的私有源码快照 CRC 匹配；另外两个条目分别声明下列输入，但检查时对应文件不存在：

* `worldnodes/n0.vrman_c`：`maps/mcp_3cf6af8ef7ca4c068115ff0a/worldnodes/n0.vrman`。
* `world_physics.vrman_c`：`maps/mcp_3cf6af8ef7ca4c068115ff0a/world_physics.vrman`。

两者的 `m_SearchPath` 均为该任务私有 addon，检查器给出 `required_or_recorded_input_missing`，因此不能通过普通输入匹配门禁。其余 8 个通过的资源没有声明普通输入；空列表只表示元数据未列出普通输入，不证明没有依赖。所有条目合计还声明 15 项特殊依赖，当前检查器只计数，未验证其身份或内容。

## 限制与下一步

目前没有证据足以确认缺失的 `.vrman` 是编译中间文件、为何消失、或其内容是否参与最终产物。不能按扩展名跳过，不能把缺失改成可选，也不能因为其他资源通过而宣称整包依赖闭合。现有 worker 行为保持不变，地图 RED2 尚未成为构建成功门禁，`dependency_snapshot_complete` 和 `release_ready` 仍为 false。

下一步在新的隔离任务中观察 resourcecompiler 的工作目录与生成文件生命周期，尝试在消失前保存文件身份、CRC 和内容证据；确认生成阶段与来源后，再设计覆盖编译期间及之后变化的门禁。还须检查基础游戏及特殊依赖，动态字符串引用和加载界面资源也不在本次覆盖范围。

私人原始输出及逐项报告位于 `C:\CS2_Temp\map_red2_probe\input_dependency_checks`。本次未修改 Hammer 文档、未保存地图、未切换游戏地图。
