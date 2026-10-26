# discover_out 离线采集审查（2026-10-26）

用户提供目录C:\cs2_tool_mcp\third_party\discover_out，保持原文件不变。

| 文件 | 大小/内容 |
|---|---|
| calls.jsonl | 58,825,810字节，227,126条记录 |
| functions.json | 58,479字节，248个模块、155个Hook元数据 |
| discovery.log | 308,781字节，安装/命中/参数探测日志 |
| particle_operators.txt | 10,286字节，325个不重复名字 |

JSONL逐行解析0个JSON错误、0个结构错误；72种Hook ID产生记录，201,800种不同文本。
这不是201,800个UI控件或API：tier0 CUtlString::Set占184,057条，含大量引擎/调试信息。
QStandardItem(QString)有27,005条；Qt5Widgets setText有6,707条、setToolTip有3,862条。
短fn名称合并了不同重载，这些数是采集记录数，不是去重后的原始调用次数。

## 关键问题：历史Hook ID不能稳定关联

13,163条记录的hook ID与当前functions.json中的short/module不匹配。例如：
- ID154的9007条记录自报tier0.dll/CUtlString::Set，元数据却是Qt5Widgets/QWhatsThis::showText。
- ID24的2356条记录自报Qt5Gui/QStandardItem(QString)，元数据却是Qt5Core/QTranslator::translate。
- ID132的893条记录自报setToolTip，元数据却是setTitle。

可能是不同采集批次的JSONL追加、而functions.json更新；当前文件本身不足以证明具体原因。
因此分析按每条记录自身fn/mod归组，保留冲突；不把错配ID强行贴上元数据的完整符号。
即使fn/mod匹配，也缺少逐条session_id、PID、DLL SHA/版本，不能证明一定属于元数据对应实例。
原日志历史PID59964，与本聊天当前实例不同；所有绝对地址/RVA均不得据此直接调用。

## 能用于下一步的证据

- QStyle::drawItemText、QPainter::drawText、QStandardItem构造、setText、setToolTip、
  QComboBox插入项等覆盖面比按钮getter广，可为菜单、属性表、列表文本采集选择入口。
- 调用栈出现Hammer、Pet、MET、ModelDoc、toolframework2等；可帮助确定宿主DLL。
  first_noninfra_stack_modules只是启发式首个非Qt/系统/采集模块，不保证文本主归属。
- particle_operators.txt的325个名字均在JSONL中出现；它是已观察名称清单，
  不是完整粒子函数注册表，不含参数类型/默认值/读写或效果验证。
- 当前记录无QObject this/objectName/父链等关联，不足以作为可点击控件或安全写入句柄。

采集器下一版宜增加session_id、PID/进程创建时间、DLL SHA、完整符号、线程、
来源对象身份及时间戳；需要独立验证ABI和对象生命周期，不能把记录地址当作当前地址。
本轮未安装/注入采集DLL，未改动编辑文档。

## 可复现分析

新增scripts/analyze_qt_discovery.py及共享模块qt_discovery.py：逐行读JSONL、记录ID冲突、
按记录字段归组、校验分析前后输入大小/mtime，输出新的报告，拒绝覆盖已有输出。
只统计不同文本数量，不将全部原始文本或调用栈复制进主仓库。

python scripts/analyze_qt_discovery.py C:\cs2_tool_mcp\third_party\discover_out --output <新JSON路径>

结果C:\CS2_Temp\discover_out_verified_analysis.json。
输入calls.jsonl SHA256：9bf1ef3aabd472604a129696913eb7738a766031449e8714a9962a21f385391c。
混合ID回归测试覆盖按自报fn/mod分组、冲突保留、坏行统计和操作符观察。
完整99项Python测试通过；MCP工具数保持89，没有新增运行时能力声明。
