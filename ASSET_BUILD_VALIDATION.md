# 单资源编译可靠性（2026-10-27）

用户代码审查指出原实现仅凭退出0和文件存在可接受旧文件/空文件；原单测也确实将空文件作为成功。现已移除该成功条件。

## 本轮实现与证据

cs2_asset_compile默认预览；确认后使用同目录mcp_asset_<UUID>.<ext>独占源快照，编译到UUID对应的独立产物路径，绝不以原文件存在代表本次生成。现有编译器-help没有通用输出目录选项；同目录源快照是为了保持相对DMX/纹理等引用基准，尚未实现独立目录的完整依赖镜像。快照和测试产物保留以便诊断，不自动删除或替换原产物。

复用build_jobs.atomic_json/now和build_process.CompilerProcess：编译启动在Job Object内绑定PID/创建时间，等待主进程及后代退出，120秒超时后关闭所属Job。每次任务在临时目录cs2_asset_jobs/<UUID>保留record.json、compiler.log和临时目录；保存源/编译器文件身份和SHA、命令、退出码、进程状态、产物哈希及资源块。仍为同步接口；客户端断开不保证持续编译，不能把它称为已接入持久start/status/cancel队列，异常遗留记录也不自动重试。

源文件/快照/编译器前后校验一致才接受；本次UUID产物必须存在，并通过现有resource_blocks资源头/版本/块表边界检查且具有非空DATA块。校验前后文件证据必须一致。尚不验证整个类型的语义/运行效果/依赖冻结。

真实新stdio MCP材质编译任务138f625bb0434125be0dea770153d5f5退出0、process_tree_exited=true，RERL/RED2/DATA/INSG有效。私人报告C:\CS2_Temp\asset_fresh_compile_stdio.json；对应record.json在cs2_asset_jobs任务目录。没有上传或发布测试资源。

174项测试（173通过/1符号链接权限跳过）。新增/重写测试覆盖新产物成功、保留原产物、仅旧产物存在、空/畸形新产物及编译期间输入变化。契约测试将描述inspect.cleandoc后比较，参数/其他结构独立严格比较，不忽略描述内容变化。CURRENT_STATE旧上传阶段AST文字已改为历史快照并说明目前map_io_check已调用check_scripts。

## 用户审查后续清单（保持原范围）

1. 单资源任务纳入持久worker/start/status/cancel，独立依赖目录镜像及更多资源语义验证。
2. 按真实编译规则补vsndevts/soundevents_addon、vtex、音频、JS；当前仍只支持vmdl/vmat/vpcf，不凭扩展名扩表。
3. Hammer按GUID读取真实属性后的未保存修改→回读→Undo→Redo；当前committed_properties.py研究代码已能读目标7项class props，当前CDataModel RVA0x24BAE00、vtable0x16C45D8，旧0x24BBE00实测失效。仅只读研究、未保存差分未验收、native_compatibility仍空。此前Qt属性保存/Undo/Redo证据不等于任意原生写入profile通过。
4. activator/caller→RunScriptInput→可观察结果的玩家上下文验收，以及CS2Fixes真实版本/关键cvar；plugin_versions仍未实现。
5. VMAP之外的脚本/材质/粒子等依赖快照与前后哈希；动态声音/脚本文本引用及UI资源检查。
6. 声音RMS/LUFS/true peak工具与版本绑定声音栈倍率；不能把snd_musicvolume双重乘算作为所有音乐事件固定规则。
7. 继续区分参数契约/描述格式、保持当前状态文档及时更新。

本轮未提交的committed_properties.py、hammer_committed_properties_probe.py、test_committed_properties.py是上一轮被打断的只读研究成果，原样保留，尚未公开MCP或声称完成未保存属性验证。

## 2026-10-27：普通RED2输入成为单资源成功条件

cs2_asset_compile在唯一产物结构校验后调用游戏原生RED2来源检查，普通/Additional输入的搜索路径、存在性和CRC必须匹配；不匹配、resourceinfo不可用或文本无法完整解析均不返回成功。结果保留input_dependency_validation（普通输入是否匹配、数量、特殊依赖计数、覆盖标志及独立报告路径）。依赖检查结束后再次核对主源、源快照、编译器及产物身份，避免检查过程中的替换被忽略。

201项测试（200通过/1符号链接权限跳过）。新增退出0+有效DATA但普通依赖检查失败仍status=failed且原产物不变；原旧文件/空文件/畸形资源拒绝测试继续通过。

实际新stdio MCP分别验证：
- 材质367eabb2aee84e3781b5ad205e0ff1f2：9普通输入匹配，10特殊依赖未全覆盖。
- 模型099f4c8845234027bbc0238186bb06ee：2普通输入匹配，1特殊依赖未全覆盖。
- 粒子eec3ca0b1c874af68e48f7d8566d68ec：1普通输入匹配，2特殊依赖未全覆盖。

私人总报告C:\CS2_Temp\asset_dependency_gate_stdio.json；各自cs2_asset_jobs/<UUID>/record.json与input_dependency_checks报告保存校验细节。三项均唯一源快照/产物名，不替换原编译资产、未在编辑器打开或预览、不上传模型等第三方资源。

普通输入匹配仍不等于完整特殊/shader/VPK/动态引用闭合或视觉效果正确；dependency_snapshot_complete/coverage_complete/release_ready保持false。单资源仍同步，尚未接持久start/status/cancel worker；整图worker默认仍用源码树guard，私有副本尚未变默认。声音、纹理、音频、JS的真实编译规则亦未补齐，后续按原审查清单继续。
