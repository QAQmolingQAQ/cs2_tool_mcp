# Qt文本参考与采集接续（2026-10-26）

用户指定参考：https://github.com/QAQmolingQAQ/cs2-tools-trans-cn
只读克隆到C:\cs2_tool_mcp\third_party\cs2-tools-trans-cn，核对提交
f18b6d5e7bbe52316753721e40854677a93f0562；LICENSE为MIT。
未运行其启动器、安装/注入其DLL或改写本机游戏翻译；未复制外部表进主仓库。

## 本地已接入

mcp_server/hammer_mcp/qt_text_catalog.py读取用户显式指定目录的flat或rich JSON；
限定scope文件名和文件大小，记录每文件SHA，按scope/common保留所有候选。
英文/中文双向精确查找不消除歧义，不修改观测到的button_text或对象地址。
元数据明确external_translation_reference_not_observed_ui。
脚本scripts/qt_text_reference.py只创建新的输出文件，不覆盖输入或已有输出。

本次仓库translations目录只有.gitkeep，实际可用表在out。
本地hammer.json有29510个非空翻译，common.json有17923个；两者可能有重叠，
不能相加当作唯一UI条数，更不能当作当前游戏已显示/已支持的API数量。
现有真实Hammer快照128行中，10行按钮得到翻译候选。
个别译法不适合直接使用，例如Add Key译为“添加钥匙”；本接口不背书语义准确性。

复现（参数替换成所需本地文件）：
python scripts/qt_text_reference.py --catalog-root C:\cs2_tool_mcp\third_party\cs2-tools-trans-cn\out --scope hammer --snapshot C:\CS2_Temp\qt_after_hammer_click.json --output <新的JSON路径>
或用--query替换--snapshot，进行英文/中文精确查询。
输出C:\CS2_Temp\qt_hammer_text_reference_20261026.json。
两项新回归测试覆盖歧义保留、原始快照不变、rich格式、非法scope/数据拒绝；
完整95项Python测试通过。MCP工具数保持88，未宣称新增运行时采集工具。

## 当前DLL导出名审计

核对其hook/cs2cnloc.cpp中的11个hookQt符号及1个Core translate符号；
本机导出10个存在、2个缺失：
- ?itemize@QTextEngine@@QEBAXXZ
- ?translate@QCoreApplication@@SAPEB_WPEB_W1H2@Z
本机translate实际导出返回QString，参数是const char*等，不是源码注释描述的QChar*签名。
因此不照搬此采集点，也未推断其在所有版本都失效。
QPainter drawText/drawStaticText的导出名存在仅证明名称匹配，不证明hook参数ABI、
并发/重入/生命周期或完整覆盖已验证。
报告C:\CS2_Temp\qt_translation_hook_export_audit.json。

后续可参考只读绘制采集、重入保护、去重和按DLL归属；每个入口应独立核对ABI。
绘制记录需要与控件/objectName/父链关联，不能作为可操作对象句柄。
仍需实现QAction、属性网格/模型文本等查询；现有快照仅对象名和按钮text。

## 中断前的UI尝试

电脑操控读取Hammer空窗口后发送一次Ctrl+O；随后辅助功能返回null，
list_windows无新对话框，重新捕获报FrameArrived timed out。
未继续输入路径/盲点，未打开地图。中断的只读dirty探针若有输出需重新核对PID，
不把观察超时当作目标退出；下一轮不得凭本记录重放未知编辑动作。
