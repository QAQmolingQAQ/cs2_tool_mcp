# Hammer Outliner 实体身份读取（2026-10-27）

目标是让批量操作以实体GUID绑定，不能以显示文字、行号或临时地址代替。

## 已验证链路

当前Hammer SHA5901a11c…及QtCore/QtWidgets/propertyeditor版本由property_fields.verify_layout核对；QtGui额外固定SHA2ea37f7655223c5cdf1f28616c601ca58bf8b215e371d6f612cfa1aa34517fbf，已加载PE头匹配磁盘。

1. Outliner模型RTTI为CQOutlinerSortFilterProxyModel、主vtable RVA0x1E17AF8。不同实体的QModelIndex.internalPointer会共享，不能当实体指针。
2. QtCore导出sourceModel（RVA0x1A7150）静态读取QObject+8的private，再private+0x88；实际源模型是QtGui QStandardItemModel、vtable RVA0x4369F0。
3. QtCore mapToSource导出0x1B5810内部0x1B6790确认代理internal+0x28指向映射记录；记录+0x10源父QModelIndex、+0x28映射对象的行/列QVector。按代理行/列映射得到源行/列。
4. 源父QModelIndex.internal指向父item，须先按该index自身row/column取child，才是当前子行的父item；直接把internal当父item会导致边界错误。保留失败证据，未绕过边界检查。
5. QtGui QStandardItem.child（RVA0x33EB70）确认item+8 private，private+0x20/+0x24行列数，+0x18 children QVector。角色表在private+0x10，24字节entry（role i32，+8 QVariant16字节）。
6. 实体行源item RTTI为CQOutlinerItem、vtable RVA0x1E17EE8；role256 QVariant用户类型0x410包含实体指针。实体RTTI CMapEntity、vtable RVA0x175AD00；实体+8为16字节Windows little-endian GUID。

此前属性往返选中代理行[0,3]对应GUID657b42df-8155-4005-9f33-8ff4072e6c70，与保存后属性差分目标完全相同。独立只读探针读取21实体，与最终保存快照restored.kv2的21个实体GUID集合完全一致，缺失/新增均空。

## 可复现入口与边界

scripts/hammer_outliner_identity_probe.py --config <private project.json> --report <private report.json>

要求唯一打开文档为配置地图、依赖版本与RTTI/vtable匹配；最多256行、4096项向量、2MiB总读取。只处理可见直属子行，其他类型标unsupported。每个重复内存读必须一致，结束后重读所有证据并重新核对Outliner及完整preflight。非原子观察，不能排除ABA变化；地址仅当次有效，不保存为长期实体标识。仍safe_to_write=false、coverage_complete=false，没有调用原生函数或修改地图。尚未纳入公开MCP工具（103唯一工具不变）。

3项新增测试覆盖向量计数/偏移边界、无效地址/读取期间变化和错误模型提前拒绝；168测试（167通过/1符号链接权限跳过）。

私人证据均在C:\CS2_Temp：outliner_identity_probe.json、outliner_identity_model.json、outliner_proxy_static.json、outliner_source_model_probe.json、outliner_standard_item_static.json、outliner_source_item_mapping_failure.json、outliner_source_item_roles.json、outliner_entity_identity_probe.json、outliner_guid_verified.json、outliner_guid_saved_comparison.json。不要提交原始内存/第三方二进制。

下一步将这条身份链收进受限只读MCP，覆盖选择前后实体GUID/文档归属，验证排序/筛选/同名实体；再接真实内存属性读回和批量执行，不用保存文件代替未保存值读取。
