# 私有源码副本编译验证（2026-10-27）

## 复制与边界

source_manifest.copy_source_manifest将有身份/SHA清单的addon源码复制到全新目录，拒绝目标位于源树内、路径逃逸/链接、复制前文件身份变化和复制期间变化；用独占写、复制后hash、源树再次扫描及完整副本内容比较，不静默形成混合副本。复制文件设只读位，但这不是不可突破的权限隔离；副本前后哈希仍必须复核。失败目录保留供诊断，不递归清理用户路径。

scripts/probe_frozen_addon_compile.py只用于non-release test工程，创建UUID私有content/csgo_addons/mcp_snapshot_<UUID>及匹配game addon目录。复制整个test内容，独立平面map从私有副本读取并核对原始SHA；编译器按新addon路径推导搜索路径并输出到新game addon。没有修改默认build_start/worker输入策略，也没有加载新地图或关闭/保存Hammer。

## 真实结果

第一次c873a220a4ff48cc9470a57ea1d534ff成功编译私有平面地图，VPK检查通过、副本无变化。该早期探针平面输入仍由原图再次读入并核对SHA；随后已修正为从副本读取，第二次才验证了该修正。

第二次2d82be05251c4473a781c97b43015726完成：
- 从私有副本读取地图输入；快速编译退出0，VPK结构/CRC/VIS通过。
- --probe-material编译私有materials/models/prop_livehouse中的本地最小材质，退出0，非空DATA及资源块检查通过。
- 原生编译日志的map、生成的entity model及材质/纹理构建路径均带私有addon前缀，安装产物位于该私有addon。
- 整个复制内容编译前后added/removed/changed均空；原地图SHA未变。原test工作树不作为本次输出目录。

日志路径不等于全部依赖实际读取路径证明。材料还使用基础默认法线/AO等资源，基础游戏/其他addon/缓存来源并未全部冻结。

## RED2解析失败必须保留

使用本机S2V CLI 20.0的-b RED2检查材质产物，进程退出0但输出UnexpectedMagicException/Unknown KVType26。未将它当成功或空依赖清单。当前本地VRF源码ResourceEditInfo2说明RED2包含InputDependencies及SearchPath，但旧CLI不能解码此资源。完整输入来源证明需要支持该类型的解析器或独立文件读取跟踪；不得仅凭资源头/日志路径声称已冻结全依赖。

196测试（195通过/1符号链接权限跳过），覆盖复制内容独立性、原件之后变化不影响副本、旧清单拒绝、目标嵌套和逃逸拒绝。真实第二次编译覆盖脚本更正/材质分支。公开工具105不变。

## 证据与接续

C:\CS2_Temp\mcp_build_jobs\source_copy_probes/<两个UUID>/record.json、original_manifest.json、copied_manifest.json、after_compile_manifest.json、compiler.log；第二次material_probe/record.json、compiler.log、red2_dump.txt保留失败与编译信息。私有addon复制了本地第三方测试资产，仅留本机，不提交/上传；两个约121MB的私有目录保留便于复核，不在当前test工作目录内。

下一步补可靠RED2/输入依赖来源读取，并将已验证的私有addon副本方案接持久worker及取消/输入身份/产物安装范围；默认流程仍使用原addon加前后变化guard，不能宣传为已启用不可变构建。完整外部依赖、动态脚本/声音、完整光照/运行验证继续保持未完成。
