# 下载目录模型检查（2026-10-13）

只记录本机检查与 `test` add-on 验证结果，不在本仓库提交第三方模型文件。
源压缩包位于 `C:\Users\ssss\Downloads`。所有五个相关 ZIP 均通过 CRC 校验，
未发现绝对路径或 `..` 路径穿越项。

| 压缩包 | 内容 | ModelDoc 源树 |
| --- | --- | --- |
| `character_template.zip` | 1 个 `.vmdl`、6 个 DMX，角色模板 | ModelDoc41；根节点 15 个子项，194 个 `_class` 节点 |
| `earthgovsol_ag2_src.zip` | 2 个 `.vmdl`、7 个 DMX、5 个材质，以及 PNG/PSD 源贴图和 Blender 文件 | 两个版本各有根节点 16 个子项、284 个 `_class` 节点 |
| `earthgovsol_ag2.zip` | 对应的 2 个 `.vmdl_c`、5 个 `.vmat_c`、20 个 `.vtex_c` | 编译资源包 |
| `neco_arc_animgraph_pt_update_src.zip` | 2 个 `.vmdl`、9 个 DMX、2 个材质、4 个动画图、2 个动画片段及源贴图 | 两个版本各有根节点 14 个子项、276 个 `_class` 节点 |
| `neco_arc_animgraph_pt.zip` | 对应的 2 个 `.vmdl_c`、动画图/片段、材质和贴图编译资源 | 编译资源包 |

使用项目的 KV3 解析器只读检查了四个角色 `.vmdl` 和模板；三份源码 ZIP
中，各自引用的 `agents/...` 内部 DMX、材质及贴图均能在包内找到
（按 Windows 文件名大小写规则核对）。模型还引用 CS2 基础内容中的武器、
手臂、动画图等资源；不能仅凭压缩包完整性保证所有游戏内引用均正确。

## 本地导入与验证

- 仅把 `neco_arc_animgraph_pt_update_src.zip` 和 `earthgovsol_ag2_src.zip` 的
  `agents/...` 源文件复制到当前 `test` add-on 的同名内容路径；复制前确认
  目标文件不存在。没有复制已编译 ZIP，也没有把第三方文件加入 Git。
- 对 `agents/models/s2ze/neco_arc/neco_arc.vmdl` 和
  `agents/models/s2ze/earthgovsol/deadspace_earthgovsol.vmdl` 分别运行 CS2 自带
  `resourcecompiler.exe -nop4 -fshallow`，两次均为 **1 compiled、0 failed**。
  各自的另一个变体也由本地工具生成了 `.vmdl_c`。
- 用 `cs2_modeldoc_open` 在运行中的 ModelDoc 打开上述两个源码模型，均读回
  有效活动会话、`CModelDoc` 文档和 `CModelDocRoot`。打开 EarthGovSol 后
  ModelDoc 有 3 个会话（之前的 Workshop 测试模型和这两个下载模型）。
- 两个复杂模型的文本源树分别有 14/16 个根子项，但实时
  `CModelDocRoot+0x10` 的低 32 位及 `+0x18` 都为零；与之前简单 Workshop
  模型一致。**不要把这两个偏移当作源节点列表。** 本轮完成了编译和
  文档打开验证，尚未确认 ModelDoc 视口中的最终视觉效果或未保存节点读取。

后续若继续逆向，可在这两个已加载的复杂文档上对照保存源树、会话内存和
ModelDoc 属性/树控件，找真实节点容器；不要直接写入未经验证的偏移。
