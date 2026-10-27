# 原生RED2输入来源与CRC验证（2026-10-27）

## 解决旧CLI兼容性问题

本机S2V20.0和本地VRF f3ad9fb的KV3枚举仅到25；官方master已将26/27定义为UINT32_ZERO/ONE，官方20.1发布说明包含两类型与shader72支持：
https://github.com/ValveResourceFormat/ValveResourceFormat/releases/tag/20.1
https://raw.githubusercontent.com/ValveResourceFormat/ValveResourceFormat/master/ValveResourceFormat/Resource/ResourceTypes/BinaryKV3.NodeType.cs

已查到官方Windows x64 zip SHA67aaf8a67a85ca60fd09ff343e62103a4cdf3a2d177fc656231d7d734c5b3aa3，但本机urllib/curl到GitHub TLS握手失败、GitHub连接器请求也失败。没有关闭TLS校验、使用镜像或执行未校验下载；没有安装20.1、没有改原CLI或第三方源码。dotnet只有runtime无SDK，不以缺SDK停止其他工作。

替代方式来自游戏自带resourceinfo.exe -help：支持-i、-b RED2、-baremode及-dep compile。对旧CLI失败的同一材质，原生工具正确输出完整CResourceEditInfo文本，不再受外部KV3枚举版本限制。

## 可复用检查器

input_dependencies.py调用受路径约束的本地resourceinfo，只读、20秒超时/8MiB文本/64MiB资源/256MiB输入载荷上限，记录工具和产物前后文件身份与SHA。原始输出和report保存状态目录input_dependency_checks/<UUID>。脚本inspect_native_input_dependencies.py接受工程配置与已编译资源，不接任意命令，不改默认构建器或地图。

严格检查RED2头、完整文本解析、输入数组与类型、CRC范围及相对路径；拒绝重复KV3键、逃逸路径、无类型flags和截断/错误文本。复用既有KV3 parser增加可选reject_duplicates，原资产树行为保持。普通与Additional输入逐项解析name/SearchPath/CRC/optional/exists/is_game_file，分别在content或game根下定位。现存文件CRC及文件身份/SHA必须匹配；可选且记录不存在的输入检查实际缺失，并在结尾再核对仍未出现。搜索路径不明、缺失必需文件或CRC不符均不会返回declared_inputs_match=true。

ok只表示检查过程完成；是否匹配看declared_inputs_match。coverage_complete/release_ready始终false，特殊输入/特殊依赖仅统计，不当作已闭合。

## 实机结果

目标为私有addon mcp_snapshot_2d82be05251c4473的white_s.vmat_c：原生RED2声明9条普通输入、Additional0条、SpecialInput0条、SpecialDependency10条。6条现存输入CRC全部通过，3条缺失可选.txt确实不存在，declared_inputs_match=true。

其中white_s.vmat及white_s_color.png的SearchPath明确为私有addon且CRC与副本一致；默认ao来自core，normal/rough及normal.txt来自csgo。由此能将私有输入与外部基础输入分开，不再仅根据编译日志猜测来源。shader VPK/编译器版本等10条特殊依赖没有全部逐资源验证，因此未证明全输入不可变或运行挂载完全一致。

证据C:\CS2_Temp\native_input_dependencies_verified.json；完整报告input_dependency_checks/53e14c6046594929ab74992be9962fa6/report.json、native_red2.txt。原生help和编译依赖原始文本也在先前source_copy_probes材质子目录。均仅本地，不提交资产/个人绝对路径原始输出。

200测试（199通过/1符号链接权限跳过），新增正确元数据、错误/空/截断CLI输出、路径/类型/重复键拒绝及CRC实际变化不匹配验证。没有修改游戏源码或当前地图，公开工具105不变。

## 下一步

将普通输入CRC/SearchPath核对接入持久worker的私有源码副本流程，继续验证地图VPK内世界资源和关联材质的输入；补特殊依赖/VPK内容身份，再决定默认流程切换。当前reader为研究/复用层，未接资产编译成功门禁或宣布默认不可变构建完成。

2026-10-27后续：普通输入来源/CRC检查现已接入单资源cs2_asset_compile成功门禁，材质/模型/粒子各一实机样例通过；特殊依赖未全覆盖、整图默认worker未切换。详见ASSET_BUILD_VALIDATION.md最新段。
