# met.dll 材质编辑器分析（2026-10-14）

安装文件大小 4,758,168 字节，SHA-256：
`f67648b9c95e5cda772f9402cca356232ae07fe639910215e5c3002e08ce1a3d`。
下列为**静态分析候选**，尚未实机读回，不用于未经验证的写入。

## 数据库

旧 `C:\cs2_tool_mcp\ida_db\met.dll.id0` 报损坏，保留原件另建
`met_clean_20261014.dll.i64`，DLL 副本与安装文件哈希一致。
结果在该目录的 `met_clean_scan.json`、`met_entry_decomp.json`、
`met_document_paths.json`、`met_variables_layout.json`。

## 入口（RVA）

- `0x1FBE0`：明确标识 CQMaterialEditor::LoadMaterialFromBuffer，调用 LoadKV3FromKV3OrKV1；需要材质记录及原生缓冲区。
- `0x202D0`：按路径加载材质的包装，设置记录+0x20，读取文件后调用上述入口。
- `0x21160`：Shader 描述查找。
- `0x212F0 / 0x277C0`：从 Shader 元数据构造开关/变量集合。
- `0x30130 / 0x2F200`：材质/变量序列化；输出 Layer0、shader、Attributes，前者会更新 PreviewModel，不能当作无副作用查询。
- `0x331F0 / 0x34310`：编辑器设置读写，不能当作保存材质入口。

## 候选布局

多个方法读取 CQMaterialEditor+0x238（568）作为当前材质。先定位
CMaterialEditorTool→CQMaterialEditor，不能套用 Pet Session/Doc 布局。

| 材质记录偏移 | 用途 |
| --- | --- |
| +0x20 | 源路径字符串 |
| +0x28 / +0x30 | Shader 名 / 描述对象 |
| +0x38 | 初始源内容 |
| +0x40 / +0x48 | 开关集合 / 变量集合 |
| +0x68 / +0x70 | StateHistory / VariableState KV3 |
| +0x88 / +0x90 | Attributes 数量 / 数组 |

开关与变量容器均为+0x08数量、+0x10连续数组；开关元素80字节，
+0x08名称、+0x18分组、+0x24当前整数值；+0x20比较基准的默认/下限语义待核对。
变量元素248字节，+0名称、+0x24类型ID、+0x48分组、
+0x80非空时优先输出的表达式、+0x90当前值字符串。类型ID含义尚未逐项确认。

## 下轮

1. 打开独立测试材质，定位窗口、记录、路径与 Shader。
2. 只读枚举开关和参数，对照 UI 及保存输出。
3. 查原生属性回调、历史快照、预览刷新和编译通知。
4. 修改→读回→Undo→原值→Redo→新值通过后再开放写入。

本轮后段 CS2 进程不在线、管道不存在；MET 尚未实机验证，仅留本地。
