# ValveResourceFormat 本地参考（2026-10-14）

来源：`C:\cs2_tool_mcp\third_party\ValveResourceFormat`。
本地 HEAD：`f3ad9fba9c58ffe2659a441506b1e81662d15429`，检查时工作树干净。
参考 [Source 2 Viewer / ValveResourceFormat](https://github.com/ValveResourceFormat/ValveResourceFormat)；
本轮只读源码，没有修改该仓库、编译运行新版本或验证其预览与 CS2 一致。

## 粒子用途与配置参考

`ParticleControllerFactory.cs` 有 146 个与当前 DLL 目录匹配的模拟实现；
`Renderer/Particles/ParticleRendererFactory.cs` 另有 7 个匹配渲染实现。
合计 **153/376**，七组为 15/3/41/79/6/2/7。
其余 223 项未在这两个工厂表找到实现，不推断它们的完整用途或行为。

对应源文件、实现类、文件中出现的参数名与文件哈希已保存到
[VRF_PARTICLE_REFERENCE.json](VRF_PARTICLE_REFERENCE.json)。
参数名是文件级引用，不保证覆盖父类或所有编辑器选项。
可用 `scripts/index_vrf_particle_reference.py <本地VRF目录>` 重建索引。
它提供阅读入口，尚未自动附加到 MCP 参数查询结果。

两个可优先补说明的例子：

- `C_INIT_InitFloat`：根据输入值设置指定标量属性；源码读取
  m_nOutputField、m_InputValue、m_InputStrength、m_nSetMethod。
  VRF 实现把 strength 用于当前值与目标值插值；角度字段在部分设置方式下从度转弧度。
  这些是 VRF 行为参考，尚未完成 CS2 原生效果对照。
- `C_OP_SetControlPointPositions`：设置最多四个控制点位置，
  用 m_bUseWorldLocation 选择世界坐标或相对头控制点变换，
  m_bSetOnce 控制是否只执行一次；m_nHeadLocation 指定头控制点。
  对应实时测试参数读取已存在，但本轮没有修改或预览验证。

## MET 参考

`CompiledShader/Blocks/VfxVariableDescription.cs` 可提供变量名、类型、
UI分组/控件、步长、整数/浮点默认值与上下限、默认纹理、
动态表达式及显隐表达式。`VfxCombo.cs` 提供 Shader 开关组合描述。
`Misc/ShaderCatalog/Program.cs` 展示从 features.vcs 建立开关/变量目录的流程。

`Resource/ResourceTypes/Material.cs` 解析编译材质的整数、浮点、向量、
纹理参数和属性，并反编译动态表达式；其注释明确说表达式没有被求值，
渲染时仍保留静态烘焙值。不能把该预览当成完整引擎效果。

`VfxProgramData.cs` 的版本检查接受 VCS 59–72，包含之前旧 CLI 20.0
报不支持的 72。这是源码支持声明；尚未构建并对失败素材复测。
MET 记录内的参数类型 ID 不能直接套用 VfxVariableType 枚举，需逐项对照。

下一步：用 Shader 文件元数据建立参数目录，并与 MET 实时值/原生修改路径结合；
VRF 文件解析不替代实时编辑器架构。
