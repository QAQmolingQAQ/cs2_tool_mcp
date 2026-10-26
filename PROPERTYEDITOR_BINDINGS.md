# Hammer 属性行绑定：propertyeditor.dll

2026-10-26，本地。新增Hammer工具`cs2_hammer_property_fields(config='', profile='')`。
只读取配置指定且唯一打开的Hammer文档的可见文本控件，不修改或保存。
工具归属Hammer文档上下文；底层共享属性行实现来自propertyeditor.dll，尚未提供通用属性编辑器服务。

## 实机取得的类型链与字段

- 过滤框：propertyeditor.dll的QLineEdit → CQPropertyEditorToolbar → CQPropertyEditor。
- 类名框：hammer.dll的CQSmartLineEdit → CQEntityClassComboBox。
- Name框：CQSmartLineEdit → CQEntityNameCombo → CQAttributeEditor_EntityPicker → propertyeditor.dll的CQPropRow。

Name框对应行的`CQPropRow+0x68`为CPropItem_Attr；反向`item+0x18`必须指回该行。
`item+0x28`指向UTF-8键名targetname，`item+0x30`指向显示名Name。
这是实际键名证据，不以空文本、控件顺序或名称相似度推断属性。

| 只读布局 | 当前值 |
|---|---|
| CQPropRow主虚表RVA | 0x10F900 |
| CPropItem_Attr主虚表RVA | 0x109488 |
| QObject父指针 | [object+8]得到private，再读[private+0x10] |

QObject父指针布局由安装版Qt5Core的parent导出汇编核对。
propertyeditor.dll中0x3B5F0构造函数引用CQPropRow主虚表；初始反汇编因遇到节内非指令数据停止，
启用跳过数据后才找到该引用，未将首次无结果误判为没有构造函数。
字段语义主要来自实际RTTI、字符串与反向引用验证，不能推广到其他类型属性行。

## 版本和读取限制

propertyeditor.dll SHA：`ac06e2668947608fb2c879e211c8ea65e3e86ff33204b89fe848e7e91780894d`。
实现还固定当前Hammer、Qt5Core、Qt5Widgets完整磁盘SHA，并要求加载PE头与磁盘一致；
不是全内存映像哈希证明。propertyeditor.dll已纳入版本自检的监视模块，未来原生兼容profile也须包含它。
任何依赖失配拒绝此布局查询，不从新观察自动批准写入。

每次读取检查模块归属、MSVC RTTI定位器、主虚表RVA、属性项类型、反向行指针，
父链最多16级、字符串有界且必须NUL结束/有效UTF-8；循环、坏指针、截断和未知类型均拒绝。
扫描上限4096控件、64绑定字段、30秒。扫描前后核对完整Outliner观察、文档/源码/进程/模块证据，
并重复读取绑定描述符。分页和内存读取不是原子快照，地址仅在当前观察内有意义。

`display_text`是可见QLineEdit的显示文字，可能尚未提交到属性域。
它不证明文档的提交值、实体GUID归属或Undo记录；不覆盖复选框、数值/向量编辑器、隐藏属性或全部API。
类名/过滤控件作为unbound_text_controls返回，不能据其值执行属性修改。
coverage_complete=false、safe_to_write=false，查询不改变已有原生写入拒绝策略。

## 验证与接续

真实Hammer stdio在隔离地图选中info_player_start后读到一项`targetname / Name / 空值`，
类名和过滤框分开报告；错误默认工程范围明确拒绝。102唯一工具、Hammer57。
156项测试：155通过、1项Windows符号链接权限测试跳过。新增6项覆盖键名读取、旧反向引用、
父链循环/无绑定、RTTI伪配、未终止/非法UTF-8字符串、每个依赖SHA和加载身份失配。

证据保存在C:\CS2_Temp：hammer_property_fields_stdio.json、property_fields_wrong_scope.json、
property_fields_session.json、property_qobject_rtti_chains.json、property_row_member_types.json、
property_item_fields.json和propertyeditor_row_static.json。
原图与隔离副本SHA均仍为`f489c4112a3380b898b1267929c32c5a7241af64ef9b06c6ada013381ab80b9e`。
本轮没有桥接重载、属性改写或新原生profile，保持本地。

下一步通过这个明确绑定的控件验证Qt提交信号路径，独立读取提交后的属性/脏状态和Undo/Redo。
还需把选择对象绑定到实体GUID，才能将其用于通用批量执行；Qt行索引不能代替实体身份。

2026-10-27：在隔离test地图完成targetname文档提交、保存、Undo/Redo和最终Undo保存，原图未动。分别核对控件缓冲/内存文档/磁盘；25节点内容严格相等，元数据仍不同。通用批量与完整回滚未完成，详见HAMMER_PROPERTY_EDIT_VERIFICATION.md；保持本地。
