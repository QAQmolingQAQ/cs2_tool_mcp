# CS2 粒子函数目录与查询方式

更新：2026-10-13。数据来自当前安装的 `particles.dll` 的 `ParticleSystemMgr003` 实时注册表与 `SchemaClassInfo`；不是按截图手工转录。

## 已确认范围

| Particle Editor 分组 | 数量 |
|---|---:|
| Pre-Emission Operators | 49 |
| Emitters | 4 |
| Initializers | 98 |
| Operators | 161 |
| Force Generators | 16 |
| Constraints | 13 |
| Renderers | 35 |

合计 **376** 个注册函数（376 个不同的内部类；有 8 组显示名重复，故精确定位应使用类名）。目录解析了 **395** 个相关类及其字段，包括继承的通用字段。

- 二进制 SHA-256：`9dc34a2de4311ec811b381611658fd4010861edc26e717496319a3cda72303b0`；大小：`6460568` 字节。游戏更新后须重新提取并核对哈希。
- 机器可读完整清单：[`mcp_server/hammer_mcp/data/particle_functions.json`](mcp_server/hammer_mcp/data/particle_functions.json)。每个字段含内部名、类型、对象偏移、编辑器友好名称及可用的选择项/范围注解。
- `pet.dll` 管理 Particle Editor 界面和会话；当前 376 条函数的注册表与参数 Schema 来自 `particles.dll`。
- 已用运行中的 `ParticleSystemMgr003` 逐组核对计数 `49/4/98/161/16/13/35`；本机安装的 DLL SHA-256 与目录相符。

## 直接导出的完整 API/参数 JSON

[`PARTICLE_API_REFERENCE.json`](PARTICLE_API_REFERENCE.json) 按函数展开全部 376 条记录。每条包含分组、编辑器显示名、内部类名、继承链，以及 `parameters` 数组；参数记录包含内部字段名、编辑器标签、类型、对象内偏移、声明它的类和原始 Schema 注解。无需自行合并父类即可查到完整参数。该文件由 [`scripts/export_particle_api_reference.py`](scripts/export_particle_api_reference.py) 从版本化目录生成，可重复运行。

总计 9,467 条按函数展开的参数记录（其中 376 条带 `MPropertySuppressField`，在 JSON 中明确标记 `editor_hidden_by_schema=true`）；其余 9,091 条未被该注解隐藏。重复的父类字段会出现在多个函数下，所以这些是**展开次数**，不是唯一字段数。是否在特定编辑器状态显示或可编辑，还可能受条件、行为版本及输入类型影响。

示例：在 JSON 的 `functions` 中查找 `class_name = "C_OP_ContinuousEmitter"`，会直接得到 `m_flEmitRate`（发射率）等 30 条自有与继承参数；`C_OP_RenderSprites` 有 113 条。使用任何参数前先查看 `editor_hidden_by_schema`、`type` 和 `annotations`，再在目标 `.vpcf` 中验证效果。

## MCP 查询

1. `cs2_particle_functions(query="Render sprites")` 查询显示名或内部类名；也可传 `category="Emitters"`、`offset`、`limit` 分页。无须打开粒子编辑器。
2. 取返回的 `class_name` 调 `cs2_particle_function_info(class_name="C_OP_RenderSprites")`，读该函数的全部可见 Schema 字段、类型、友好名称与继承来源。
3. 需要观察某个已保存 `.vpcf` 实际如何组合时，调用 `cs2_asset_tree(path=...)`；这个工具只读保存后的文本 KV3，不代表编辑器中未保存的更改。

例如 `Emit continuously` 对应 `C_OP_ContinuousEmitter`，自有字段含 `m_flEmissionDuration`（持续时间）、`m_flStartTime`（开始时间）、`m_flEmitRate`（发射率），并继承 `CParticleFunctionEmitter` 和 `CParticleFunction` 的公共字段。`Render sprites` 对应 `C_OP_RenderSprites`，也需查看 `CBaseRendererSource2` 的继承字段。

## 使用说明的边界

分组表达函数所处阶段：Emitter 控制粒子产生，Initializer 设置出生时的初值，Operator 持续更新粒子，Force Generator 提供运动相关作用，Constraint 限制状态，Renderer 输出可见效果；Pre-Emission Operator 在发射前处理集合状态。最终效果还取决于材质、控制点、子粒子以及其他函数的组合。

当前能可靠给出**全部注册函数和可编辑参数**，但大多数类没有逐项的人写教程。Schema 的 `MPropertyFriendlyName` 与少量 `MPropertyDescription` 是可验证的用法提示；不可把字段名推测当作完整语义。特别是 `CParticleCollectionFloatInput` 等输入类型可以是常数或表达式，具体合法值应在目标编辑器中读回验证。

`cs2_particle_editor_action` 已有原生新增函数入口，但当前没有可靠的未保存节点读回和带撤销的参数写入 API。目录工具是**只读查询**，不应解读为已支持自动写入每一种粒子函数。

## 复查与重新提取

当前版本的 `ParticleSystemMgr003` 虚表 `+0xC0` 接受分组号并返回该组函数数，`+0xC8` 接受 `(分组号, 索引)` 返回函数描述符。描述符 `+0x20` 指向显示名；其虚表 `+0x10` 可取得 Schema 类信息。`SchemaClassInfo +0x08` 是类名，`+0x20` 的第 32–47 位是本类字段数，`+0x30` 是 0x20 字节字段记录数组，`+0x38` 可追踪父类。每个字段的类型描述符 `+0x08` 指向类型名；注解包含 `MPropertyFriendlyName` 等。上述偏移只适用于目录哈希对应的当前版本，更新 DLL 后不可直接复用。

本轮只对注册表和 Schema 做只读遍历，没有向运行中粒子对象写内存。重新提取时先校验 DLL 哈希及七组数量，再逐类检查字段数、继承链，并以现有 `.vpcf` 的 `_class` 交叉验证。分析探针保留在本机 `C:\cs2_tool_mcp\ida_db\probe_particle_catalog.py`、`extract_particle_schema.py` 和 `enrich_particle_catalog.py`；探针包含机器路径，不随仓库发布。

## 注册函数索引

| 分组 | 显示名称 | 内部类名 |
|---|---|---|
| Pre-Emission Operators | Remap CP speed to CP | `C_OP_RemapSpeedtoCP` |
| Pre-Emission Operators | Remap model volume to CP | `C_OP_RemapModelVolumetoCP` |
| Pre-Emission Operators | Remap particle bbox volume to CP | `C_OP_RemapBoundingVolumetoCP` |
| Pre-Emission Operators | Set control point component from scalar statistical expression | `C_OP_RemapAverageScalarValuetoCP` |
| Pre-Emission Operators | Remap dot product to control point | `C_OP_RemapDotProductToCP` |
| Pre-Emission Operators | Ramp control point linear random | `C_OP_RampCPLinearRandom` |
| Pre-Emission Operators | Set per child control point from parent control points | `C_OP_SetParentControlPointsToChildCP` |
| Pre-Emission Operators | Set control point positions | `C_OP_SetControlPointPositions` |
| Pre-Emission Operators | Set single control point position | `C_OP_SetSingleControlPointPosition` |
| Pre-Emission Operators | Set control point to random position | `C_OP_SetRandomControlPointPosition` |
| Pre-Emission Operators | Set control point orientation | `C_OP_SetControlPointOrientation` |
| Pre-Emission Operators | Set control point from CP object scale | `C_OP_SetControlPointFromObjectScale` |
| Pre-Emission Operators | Remap distance between two control points to CP | `C_OP_DistanceBetweenCPsToCP` |
| Pre-Emission Operators | Set control point to player | `C_OP_SetControlPointToPlayer` |
| Pre-Emission Operators | Set control point to hand | `C_OP_SetControlPointToHand` |
| Pre-Emission Operators | Set control point to HMD | `C_OP_SetControlPointToHMD` |
| Pre-Emission Operators | Set control point to time-of-day value | `C_OP_SetControlPointPositionToTimeOfDayValue` |
| Pre-Emission Operators | Set control point to particle bbox center | `C_OP_SetControlPointToCenter` |
| Pre-Emission Operators | Stop effect after duration | `C_OP_StopAfterCPDuration` |
| Pre-Emission Operators | Set control point rotation | `C_OP_SetControlPointRotation` |
| Pre-Emission Operators | Remap CP component to CP component | `C_OP_RemapCPtoCP` |
| Pre-Emission Operators | HSV Shift to control point | `C_OP_HSVShiftToCP` |
| Pre-Emission Operators | Set control point to impact point | `C_OP_SetControlPointToImpactPoint` |
| Pre-Emission Operators | Set CP orientation to point at second CP | `C_OP_SetCPOrientationToPointAtCP` |
| Pre-Emission Operators | Enable children from parent particle count | `C_OP_EnableChildrenFromParentParticleCount` |
| Pre-Emission Operators | Drive CP from global sound float | `C_OP_DriveCPFromGlobalSoundFloat` |
| Pre-Emission Operators | Set dest CP field 1 if source CP is in water | `C_OP_SetControlPointFieldToWater` |
| Pre-Emission Operators | Play EndCap when Finished | `C_OP_PlayEndCapWhenFinished` |
| Pre-Emission Operators | Set control point component to scalar expression | `C_OP_SetControlPointFieldToScalarExpression` |
| Pre-Emission Operators | Set control point to vector expression | `C_OP_SetControlPointToVectorExpression` |
| Pre-Emission Operators | Set control point component to vector expression | `C_OP_SetControlPointFieldFromVectorExpression` |
| Pre-Emission Operators | Repeatedly Trigger Child Group | `C_OP_RepeatedTriggerChildGroup` |
| Pre-Emission Operators | Use Random Children in Group | `C_OP_ChooseRandomChildrenInGroup` |
| Pre-Emission Operators | Force Control Point In Pet | `C_OP_ForceControlPointStub` |
| Pre-Emission Operators | Selectively Enable Children | `C_OP_SelectivelyEnableChildren` |
| Pre-Emission Operators | Set Simulation Timescale | `C_OP_SetSimulationRate` |
| Pre-Emission Operators | Cp to Radial direction of Screen Space | `C_OP_ControlPointToRadialScreenSpace` |
| Pre-Emission Operators | Lightning Snapshot Generator | `C_OP_LightningSnapshotGenerator` |
| Pre-Emission Operators | Remap External Wind to Control Point | `C_OP_RemapExternalWindToCP` |
| Pre-Emission Operators | Set control point to cp velocity | `C_OP_SetControlPointToCPVelocity` |
| Pre-Emission Operators | Set control point orientation to cp velocity | `C_OP_SetControlPointOrientationToCPVelocity` |
| Pre-Emission Operators | Remap Hitbox Data to CP | `C_OP_RemapAverageHitboxSpeedtoCP` |
| Pre-Emission Operators | Quantize Float to Control Point Component | `C_OP_QuantizeCPComponent` |
| Pre-Emission Operators | Set Control Point to Water Surface | `C_OP_SetControlPointToWaterSurface` |
| Pre-Emission Operators | Set Control Point to Random Active Control Point | `C_OP_SetControlPointPositionToRandomActiveCP` |
| Pre-Emission Operators | Set Variable | `C_OP_SetVariable` |
| Pre-Emission Operators | Set Control Point to Gravity | `C_OP_SetGravityToCP` |
| Pre-Emission Operators | Model Surface UV Snapshot Generator | `C_OP_ModelSurfaceSnapshotGenerator` |
| Pre-Emission Operators | Multi-Segment Display Snapshot Generator | `C_OP_MultiSegmentDisplaySnapshotGenerator` |
| Emitters | Emit continuously | `C_OP_ContinuousEmitter` |
| Emitters | Emit instantaneously | `C_OP_InstantaneousEmitter` |
| Emitters | Emit noise | `C_OP_NoiseEmitter` |
| Emitters | Emit to maintain count | `C_OP_MaintainEmitter` |
| Initializers | Init vector attribute from a list of values | `C_INIT_PointList` |
| Initializers | Position along ring | `C_INIT_RingWave` |
| Initializers | Position along path random | `C_INIT_CreateAlongPath` |
| Initializers | Move particles between 2 control points | `C_INIT_MoveBetweenPoints` |
| Initializers | Position within sphere random | `C_INIT_CreateWithinSphereTransform` |
| Initializers | Position within capsule random | `C_INIT_CreateWithinCapsuleTransform` |
| Initializers | Velocity random | `C_INIT_VelocityRandom` |
| Initializers | Position on model random | `C_INIT_CreateOnModel` |
| Initializers | Position within box random | `C_INIT_CreateWithinBox` |
| Initializers | Color random | `C_INIT_RandomColor` |
| Initializers | Color lit per particle | `C_INIT_ColorLitPerParticle` |
| Initializers | Sequence random | `C_INIT_RandomSequence` |
| Initializers | Named model sequence random | `C_INIT_RandomNamedModelSequence` |
| Initializers | Named model body part random | `C_INIT_RandomNamedModelBodyPart` |
| Initializers | Named model mesh group random | `C_INIT_RandomNamedModelMeshGroup` |
| Initializers | Position modify offset random | `C_INIT_PositionOffset` |
| Initializers | Position modify warp random | `C_INIT_PositionWarp` |
| Initializers | Position modify warp from scalar | `C_INIT_PositionWarpScalar` |
| Initializers | Position modify place on ground | `C_INIT_PositionPlaceOnGround` |
| Initializers | Remap noise to scalar | `C_INIT_CreationNoise` |
| Initializers | Velocity noise | `C_INIT_InitialVelocityNoise` |
| Initializers | Remap particle count to scalar | `C_INIT_RemapParticleCountToScalar` |
| Initializers | Remap particle count to named model sequence-based scalar | `C_INIT_RemapParticleCountToNamedModelSequenceScalar` |
| Initializers | Remap particle count to named model body-part-based scalar | `C_INIT_RemapParticleCountToNamedModelBodyPartScalar` |
| Initializers | Remap particle count to named model mesh-group-based scalar | `C_INIT_RemapParticleCountToNamedModelMeshGroupScalar` |
| Initializers | Remap named model sequence to scalar | `C_INIT_RemapNamedModelSequenceToScalar` |
| Initializers | Remap named model body part to scalar | `C_INIT_RemapNamedModelBodyPartToScalar` |
| Initializers | Remap named model mesh group to scalar | `C_INIT_RemapNamedModelMeshGroupToScalar` |
| Initializers | Velocity inherit from control point | `C_INIT_InheritVelocity` |
| Initializers | Lifetime pre-age noise | `C_INIT_AgeNoise` |
| Initializers | Lifetime from sequence | `C_INIT_SequenceLifeTime` |
| Initializers | Remap scalar to vector | `C_INIT_RemapScalarToVector` |
| Initializers | Position along path sequential | `C_INIT_CreateSequentialPath` |
| Initializers | Position along path sequential | `C_INIT_CreateSequentialPathV2` |
| Initializers | Velocity repulse from world | `C_INIT_InitialRepulsionVelocity` |
| Initializers | Rotation yaw flip random | `C_INIT_RandomYawFlip` |
| Initializers | Sequence two random | `C_INIT_RandomSecondSequence` |
| Initializers | Remap a transform to vector | `C_INIT_RemapTransformToVector` |
| Initializers | Position from parent particles | `C_INIT_CreateFromParentParticles` |
| Initializers | Remap initial distance to control point to scalar | `C_INIT_DistanceToCPInit` |
| Initializers | Lifetime from time to impact | `C_INIT_LifespanFromVelocity` |
| Initializers | Position from parent cache | `C_INIT_CreateFromPlaneCache` |
| Initializers | Position from chaotic attractor | `C_INIT_ChaoticAttractor` |
| Initializers | Cull relative to model | `C_INIT_ModelCull` |
| Initializers | Cull relative to ray trace environment | `C_INIT_RtEnvCull` |
| Initializers | Normal align to CP | `C_INIT_NormalAlignToCP` |
| Initializers | Normal modify offset random | `C_INIT_NormalOffset` |
| Initializers | Velocity set from control point | `C_INIT_VelocityFromCP` |
| Initializers | Sequence from control point | `C_INIT_SequenceFromCP` |
| Initializers | Init from CP snapshot | `C_INIT_InitFromCPSnapshot` |
| Initializers | Init from parent particle event | `C_INIT_InitFromParentKilled` |
| Initializers | Set hitbox position on model | `C_INIT_SetHitboxToModel` |
| Initializers | Inherit initial value from parent particle | `C_INIT_InheritFromParentParticles` |
| Initializers | Vector component random | `C_INIT_RandomVectorComponent` |
| Initializers | Position along epitrochoid | `C_INIT_CreateInEpitrochoid` |
| Initializers | Position with phyllotaxis distribution | `C_INIT_CreatePhyllotaxis` |
| Initializers | Set hitbox to closest hitbox | `C_INIT_SetHitboxToClosest` |
| Initializers | Remap initial direction to transform to vector | `C_INIT_RemapInitialDirectionToTransformToVector` |
| Initializers | Remap Transform orientation to rotation | `C_INIT_RemapInitialTransformDirectionToRotation` |
| Initializers | Position from control points | `C_INIT_CreateFromCPs` |
| Initializers | Sequence random from model activity | `C_INIT_RandomModelSequence` |
| Initializers | Position on spiral sphere | `C_INIT_CreateSpiralSphere` |
| Initializers | Remap QAngle in CP to rotations | `C_INIT_RemapQAnglesToRotation` |
| Initializers | Init transform orientation to rotations | `C_INIT_RemapTransformOrientationToRotations` |
| Initializers | Position set rigid attachment to CP | `C_INIT_SetRigidAttachment` |
| Initializers | Position on model at specified height | `C_INIT_CreateOnModelAtHeight` |
| Initializers | Position modify offset relative to control point | `C_INIT_PositionOffsetToCP` |
| Initializers | Radius from CP object | `C_INIT_RadiusFromCPObject` |
| Initializers | Velocity away from hitbox random | `C_INIT_InitialVelocityFromHitbox` |
| Initializers | Rotation orient initial rotation relative to CP | `C_INIT_Orient2DRelToCP` |
| Initializers | Remap initial game visibility to scalar | `C_INIT_RemapInitialVisibilityScalar` |
| Initializers | Velocity radial random | `C_INIT_VelocityRadialRandom` |
| Initializers | Remap model sequence to initial scalar | `C_INIT_InitialSequenceFromModel` |
| Initializers | Position skin to bones from CP snapshot | `C_INIT_InitSkinnedPositionFromCPSnapshot` |
| Initializers | Velocity from normal random | `C_INIT_VelocityFromNormal` |
| Initializers | Globally Scale Initial Attributes | `C_INIT_GlobalScale` |
| Initializers | Init Status Effect | `C_INIT_StatusEffect` |
| Initializers | Init Status Effect (Citadel) | `C_INIT_StatusEffectCitadel` |
| Initializers | Init Status Effect (Tf) | `C_INIT_StatusEffectTf` |
| Initializers | Position On Grid | `C_INIT_CreateOnGrid` |
| Initializers | Create External Particle Impulse | `C_INIT_CreateParticleImpulse` |
| Initializers | Quantize Float | `C_INIT_QuantizeFloat` |
| Initializers | Init Float | `C_INIT_InitFloat` |
| Initializers | Init System-Wide Float | `C_INIT_InitFloatCollection` |
| Initializers | Init Vector | `C_INIT_InitVec` |
| Initializers | Init System-Wide Vec | `C_INIT_InitVecCollection` |
| Initializers | Cull relative to sphere | `C_INIT_DistanceCull` |
| Initializers | Cull relative to plane | `C_INIT_PlaneCull` |
| Initializers | Velocity Scale | `C_INIT_ScaleVelocity` |
| Initializers | Cull or modify relative to neighboring particles | `C_INIT_DistanceToNeighborCull` |
| Initializers | Init vector attribute to vector expression | `C_INIT_SetVectorAttributeToVectorExpression` |
| Initializers | Init float attribute to scalar expression | `C_INIT_SetAttributeToScalarExpression` |
| Initializers | Init from Vector Field snapshot | `C_INIT_InitFromVectorFieldSnapshot` |
| Initializers | Init float attribute from vector expression | `C_INIT_SetFloatAttributeToVectorExpression` |
| Initializers | Screen Space Position of Target | `C_INIT_ScreenSpacePositionOfTarget` |
| Initializers | Remap touching water to scalar | `C_INIT_CheckParticleForWater` |
| Initializers | Cull relative to sky visibility | `C_INIT_SkyVisCull` |
| Initializers | Position within Cone random | `C_INIT_CreateWithinCone` |
| Operators | Lock vector attribute to a list of values | `C_OP_LockToPointList` |
| Operators | Movement basic | `C_OP_BasicMovement` |
| Operators | Lifespan decay | `C_OP_Decay` |
| Operators | Lifespan from endcap decay | `C_OP_EndCapDecay` |
| Operators | Lifespan endcap timed decay | `C_OP_EndCapTimedDecay` |
| Operators | Lifespan maintain count decay | `C_OP_DecayMaintainCount` |
| Operators | Lifespan minimum velocity decay | `C_OP_VelocityDecay` |
| Operators | Lifespan minimum alpha decay | `C_OP_AlphaDecay` |
| Operators | Alpha fade and decay | `C_OP_FadeAndKill` |
| Operators | Alpha fade and decay for tracers | `C_OP_FadeAndKillForTracers` |
| Operators | Alpha fade in random | `C_OP_FadeIn` |
| Operators | Alpha fade in simple | `C_OP_FadeInSimple` |
| Operators | Alpha fade out random | `C_OP_FadeOut` |
| Operators | Alpha fade out simple | `C_OP_FadeOutSimple` |
| Operators | Rotation spin roll | `C_OP_Spin` |
| Operators | Rotation basic | `C_OP_SpinUpdate` |
| Operators | Rotation spin yaw | `C_OP_SpinYaw` |
| Operators | Rotation orient to 2d direction | `C_OP_OrientTo2dDirection` |
| Operators | Rotation orient relative to CP | `C_OP_Orient2DRelToCP` |
| Operators | Radius scale | `C_OP_InterpolateRadius` |
| Operators | Color fade | `C_OP_ColorInterpolate` |
| Operators | Color fade random | `C_OP_ColorInterpolateRandom` |
| Operators | Oscillate scalar | `C_OP_OscillateScalar` |
| Operators | Oscillate scalar simple | `C_OP_OscillateScalarSimple` |
| Operators | Oscillate vector | `C_OP_OscillateVector` |
| Operators | Oscillate vector simple | `C_OP_OscillateVectorSimple` |
| Operators | Movement dampen relative to control point | `C_OP_DampenToCP` |
| Operators | Movement lock to control point | `C_OP_PositionLock` |
| Operators | Movement lock to bone | `C_OP_LockToBone` |
| Operators | Remap distance between two transforms to scalar | `C_OP_DistanceBetweenTransforms` |
| Operators | Remap percentage between two transforms to scalar | `C_OP_PercentageBetweenTransforms` |
| Operators | Remap percentage between two transforms to vector | `C_OP_PercentageBetweenTransformsVector` |
| Operators | Remap percentage between two transforms to lerp CPs to scalar | `C_OP_PercentageBetweenTransformLerpCPs` |
| Operators | Remap distance to transform to scalar | `C_OP_DistanceToTransform` |
| Operators | Set child control points from particle positions | `C_OP_SetChildControlPoints` |
| Operators | Set control points from particle positions | `C_OP_SetControlPointsToParticle` |
| Operators | Set CP offset to CP percentage between two control points | `C_OP_CPOffsetToPercentageBetweenCPs` |
| Operators | Cull when crossing plane | `C_OP_PlaneCull` |
| Operators | Cull relative to model | `C_OP_ModelCull` |
| Operators | Cull random | `C_OP_Cull` |
| Operators | Cull when crossing sphere | `C_OP_DistanceCull` |
| Operators | Color light from control point | `C_OP_ControlpointLight` |
| Operators | Remap scalar | `C_OP_RemapScalar` |
| Operators | Remap density to vector | `C_OP_RemapDensityToVector` |
| Operators | Diffuse particle attributes | `C_OP_Diffusion` |
| Operators | Remap speed to scalar | `C_OP_RemapSpeed` |
| Operators | Noise scalar | `C_OP_Noise` |
| Operators | Noise vector | `C_OP_VectorNoise` |
| Operators | Movement match particle velocities | `C_OP_VelocityMatchingForce` |
| Operators | Movement max velocity | `C_OP_MaxVelocity` |
| Operators | Movement maintain position along path | `C_OP_MaintainSequentialPath` |
| Operators | Movement maintain offset | `C_OP_MovementMaintainOffset` |
| Operators | Movement place on ground | `C_OP_MovementPlaceOnGround` |
| Operators | Movement set to control point | `C_OP_SetToCP` |
| Operators | Remap dot product to scalar | `C_OP_RemapDotProductToScalar` |
| Operators | Remap control point to scalar | `C_OP_RemapCPtoScalar` |
| Operators | Remap control point to vector | `C_OP_RemapCPtoVector` |
| Operators | Remap direction to CP to vector | `C_OP_RemapDirectionToCPToVector` |
| Operators | Remap velocity to vector | `C_OP_RemapVelocityToVector` |
| Operators | Remap CP velocity to vector | `C_OP_RemapCPVelocityToVector` |
| Operators | Remap control point direction to vector | `C_OP_RemapControlPointDirectionToVector` |
| Operators | Remap difference of sequential particle vector to scalar | `C_OP_DifferencePreviousParticle` |
| Operators | Ramp scalar linear random | `C_OP_RampScalarLinear` |
| Operators | Ramp scalar spline random | `C_OP_RampScalarSpline` |
| Operators | Ramp scalar spline simple | `C_OP_RampScalarSplineSimple` |
| Operators | Ramp scalar linear simple | `C_OP_RampScalarLinearSimple` |
| Operators | Normal lock to control point | `C_OP_NormalLock` |
| Operators | Normalize vector | `C_OP_NormalizeVector` |
| Operators | Rotate vector random | `C_OP_RotateVector` |
| Operators | Set CP orientation to CP direction | `C_OP_SetCPOrientationToDirection` |
| Operators | Restart effect after duration | `C_OP_RestartAfterDuration` |
| Operators | Movement lerp to hitbox | `C_OP_MoveToHitbox` |
| Operators | Clamp scalar | `C_OP_ClampScalar` |
| Operators | Clamp vector | `C_OP_ClampVector` |
| Operators | Lifespan minimum radius decay | `C_OP_RadiusDecay` |
| Operators | Movement lock to saved position along path | `C_OP_LockToSavedSequentialPath` |
| Operators | Movement lock to saved position along path | `C_OP_LockToSavedSequentialPathV2` |
| Operators | Set per child control point from particle positions | `C_OP_SetPerChildControlPoint` |
| Operators | Lerp initial vector | `C_OP_LerpVector` |
| Operators | Lerp initial scalar | `C_OP_LerpScalar` |
| Operators | Lerp endcap scalar | `C_OP_LerpEndCapScalar` |
| Operators | Lerp endcap vector | `C_OP_LerpEndCapVector` |
| Operators | Inherit attribute from parent particle | `C_OP_InheritFromParentParticles` |
| Operators | Inherit attribute from parent particle | `C_OP_InheritFromParentParticlesV2` |
| Operators | Remap game visibility scalar | `C_OP_RemapVisibilityScalar` |
| Operators | Movement lag compensation | `C_OP_LagCompensation` |
| Operators | Movement rotate particle around axis | `C_OP_MovementRotateParticleAroundAxis` |
| Operators | Reinitialize on endcap scalar random | `C_OP_ReinitializeScalarEndCap` |
| Operators | Remap on endcap scalar | `C_OP_RemapScalarEndCap` |
| Operators | Remap scalar once timed | `C_OP_RemapScalarOnceTimed` |
| Operators | Remap named model sequence once timed | `C_OP_RemapNamedModelSequenceOnceTimed` |
| Operators | Remap named body part once timed | `C_OP_RemapNamedModelBodyPartOnceTimed` |
| Operators | Remap named mesh group once timed | `C_OP_RemapNamedModelMeshGroupOnceTimed` |
| Operators | Remap named model sequence on endcap | `C_OP_RemapNamedModelSequenceEndCap` |
| Operators | Remap named body part on endcap | `C_OP_RemapNamedModelBodyPartEndCap` |
| Operators | Remap named mesh group on endcap | `C_OP_RemapNamedModelMeshGroupEndCap` |
| Operators | Set CP orientation to ground normal | `C_OP_SetCPOrientationToGroundNormal` |
| Operators | Rotation from CP forward orientation | `C_OP_RemapTransformOrientationToYaw` |
| Operators | Movement rigid attach to control point | `C_OP_MovementRigidAttachToCP` |
| Operators | Remap CP orientation to rotations | `C_OP_RemapTransformOrientationToRotations` |
| Operators | Remap vector to CP | `C_OP_RemapVectortoCP` |
| Operators | Remap game visibility of CP to scalar | `C_OP_RemapTransformVisibilityToScalar` |
| Operators | Remap game visibility of CP to vector | `C_OP_RemapTransformVisibilityToVector` |
| Operators | Remap model sequence to scalar | `C_OP_SequenceFromModel` |
| Operators | Remap particle count on endcap scalar | `C_OP_RemapParticleCountOnScalarEndCap` |
| Operators | Movement loop inside sphere | `C_OP_MovementLoopInsideSphere` |
| Operators | Remap control point to velocity | `C_OP_RemapTransformToVelocity` |
| Operators | Movement skin to bones | `C_OP_SnapshotSkinToBones` |
| Operators | Movement skin to bones rigid | `C_OP_SnapshotRigidSkinToBones` |
| Operators | Set child control points objects to model particles | `C_OP_SetControlPointsToModelParticles` |
| Operators | Set vector from control point | `C_OP_SetCPtoVector` |
| Operators | Set from CP snapshot | `C_OP_SetFromCPSnapshot` |
| Operators | Remap control point orientation to rotation | `C_OP_RemapControlPointOrientationToRotation` |
| Operators | Movement Lerp to Initial Position relative to CP | `C_OP_LerpToInitialPosition` |
| Operators | Set per child control point from particle attribute | `C_OP_SetPerChildControlPointFromAttribute` |
| Operators | Remap particle count to scalar | `C_OP_RemapParticleCountToScalar` |
| Operators | Lerp attribute to other attribue | `C_OP_LerpToOtherAttribute` |
| Operators | Set Float | `C_OP_SetFloat` |
| Operators | Set Vector | `C_OP_SetVec` |
| Operators | Set System-Wide Float | `C_OP_SetFloatCollection` |
| Operators | read attribute from neighboring particle | `C_OP_ReadFromNeighboringParticle` |
| Operators | inherit attribute from peer particle systems | `C_OP_InheritFromPeerSystem` |
| Operators | remap vector component to scalar | `C_OP_RemapVectorComponentToScalar` |
| Operators | Set float attribute to scalar expression | `C_OP_SetAttributeToScalarExpression` |
| Operators | Pin Particle to control point | `C_OP_PinParticleToCP` |
| Operators | Point vector at next particle position | `C_OP_PointVectorAtNextParticle` |
| Operators | Remap cylindrical distance to transform to scalar | `C_OP_CylindricalDistanceToTransform` |
| Operators | Movement Lerp to skinned position from CP snapshot | `C_OP_MovementSkinnedPositionFromCPSnapshot` |
| Operators | Quantize Float | `C_OP_QuantizeFloat` |
| Operators | Movement Move Along Skinned Snapshot | `C_OP_MovementMoveAlongSkinnedCPSnapshot` |
| Operators | Endcap timed system freeze | `C_OP_EndCapTimedFreeze` |
| Operators | Remap cross product of two vectors to vector | `C_OP_RemapCrossProductOfTwoVectorsToVector` |
| Operators | Lifespan decay when offscreen | `C_OP_DecayOffscreen` |
| Operators | Lifespan clamp count decay | `C_OP_DecayClampCount` |
| Operators | Remap Chladni Wave to Scalar | `C_OP_ChladniWave` |
| Operators | Remap distance between two vectors to scalar | `C_OP_DistanceBetweenVecs` |
| Operators | Remap direction between two vectors to vector | `C_OP_DirectionBetweenVecsToVec` |
| Operators | Cull relative to ray trace environment | `C_OP_RtEnvCull` |
| Operators | Set vector attribute to vector expression | `C_OP_SetVectorAttributeToVectorExpression` |
| Operators | Set float attribute from vector expression | `C_OP_SetFloatAttributeToVectorExpression` |
| Operators | Dampen Movement relative to model | `C_OP_ModelDampenMovement` |
| Operators | Set from vector field snapshot | `C_OP_VectorFieldSnapshot` |
| Operators | Dampen Movement Relative to Plane | `C_OP_DragRelativeToPlane` |
| Operators | Set Event | `C_OP_SetUserEvent` |
| Operators | Remap Gravity To Vector | `C_OP_RemapGravityToVector` |
| Operators | Lazily Cull on Float Comparison | `C_OP_LazyCullCompareFloat` |
| Operators | Screen Space Position of Target | `C_OP_ScreenSpacePositionOfTarget` |
| Operators | Screen Space Distance To Edge | `C_OP_ScreenSpaceDistanceToEdge` |
| Operators | Screen Space Rotate Toward Target | `C_OP_ScreenSpaceRotateTowardTarget` |
| Operators | Pin Rope Segment Particle to Parent Particle | `C_OP_PinRopeSegmentParticleToParent` |
| Operators | Remap Vector to rotations | `C_OP_RemapVectorToRotations` |
| Operators | Update lights | `C_OP_UpdateLightSource` |
| Operators | Calculate vector attribute | `C_OP_CalculateVectorAttribute` |
| Operators | Cycle Scalar | `C_OP_CycleScalar` |
| Operators | Remap distance to line between 2 control points to scalar | `C_OP_RemapDistanceToLineSegmentToScalar` |
| Operators | Remap distance to line between 2 control points to vector | `C_OP_RemapDistanceToLineSegmentToVector` |
| Operators | Teleport Beam | `C_OP_TeleportBeam` |
| Operators | Set closest particle parent to control point pairs | `C_OP_ConnectParentParticleToNearest` |
| Operators | Lock a subsection of particles to control point | `C_OP_LockPoints` |
| Operators | Color Adjust | `C_OP_ColorAdjustHSL` |
| Operators | Remap density gradient to vector | `C_OP_RemapDensityGradientToVectorAttribute` |
| Force Generators | Random force | `C_OP_RandomForce` |
| Force Generators | Twist around axis | `C_OP_TwistAroundAxis` |
| Force Generators | Create vortices from parent particles | `C_OP_ParentVortices` |
| Force Generators | Pull towards control point | `C_OP_AttractToControlPoint` |
| Force Generators | Time varying force | `C_OP_TimeVaryingForce` |
| Force Generators | Turbulent force | `C_OP_TurbulenceForce` |
| Force Generators | Noise force | `C_OP_CurlNoiseForce` |
| Force Generators | Force based on distance from plane | `C_OP_ForceBasedOnDistanceToPlane` |
| Force Generators | Normal Scaling Force | `C_OP_WindForce` |
| Force Generators | External game force | `C_OP_ExternalWindForce` |
| Force Generators | Local acceleration force | `C_OP_LocalAccelerationForce` |
| Force Generators | Control Point Velocity Force | `C_OP_CPVelocityForce` |
| Force Generators | Per-Particle Force | `C_OP_PerParticleForce` |
| Force Generators | External game impulse force | `C_OP_ExternalGameImpulseForce` |
| Force Generators | Density-based force | `C_OP_DensityForce` |
| Force Generators | Intra-particle force | `C_OP_IntraParticleForce` |
| Constraints | Constrain distance to transform | `C_OP_ConstrainDistance` |
| Constraints | Prevent passing through a plane | `C_OP_PlanarConstraint` |
| Constraints | Prevent passing through static part of world | `C_OP_WorldCollideConstraint` |
| Constraints | Collision via traces | `C_OP_WorldTraceConstraint` |
| Constraints | Constrain distance to path between two control points | `C_OP_ConstrainDistanceToPath` |
| Constraints | Constrain distance to user specified path | `C_OP_ConstrainDistanceToUserSpecifiedPath` |
| Constraints | Constrain particles to a box | `C_OP_BoxConstraint` |
| Constraints | Line length constraint | `C_OP_ConstrainLineLength` |
| Constraints | Rope Spring constraint | `C_OP_RopeSpringConstraint` |
| Constraints | Collide with Parent Particles | `C_OP_CollideWithParentParticles` |
| Constraints | Collide with Self Simple Per-Particle | `C_OP_CollideWithSelf` |
| Constraints | Spring to Vector constraint | `C_OP_SpringToVectorConstraint` |
| Constraints | Constrain particles to initial shape | `C_OP_ShapeMatchingConstraint` |
| Renderers | Render sprite trail | `C_OP_RenderTrails` |
| Renderers | Render sprites | `C_OP_RenderSprites` |
| Renderers | Render rope | `C_OP_RenderRopes` |
| Renderers | Render Cables | `C_OP_RenderCables` |
| Renderers | Render lights | `C_OP_RenderLights` |
| Renderers | Render screen velocity rotate | `C_OP_RenderScreenVelocityRotate` |
| Renderers | Render models | `C_OP_RenderModels` |
| Renderers | Render deferred light | `C_OP_RenderDeferredLight` |
| Renderers | Render standard light | `C_OP_RenderStandardLight` |
| Renderers | Render omni2 lights | `C_OP_RenderOmni2Light` |
| Renderers | Render light beam | `C_OP_RenderLightBeam` |
| Renderers | Render projected | `C_OP_RenderProjected` |
| Renderers | Render blobs | `C_OP_RenderBlobs` |
| Renderers | Render Gpu Implicit | `C_OP_RenderGpuImplicit` |
| Renderers | Render cloth force | `C_OP_RenderClothForce` |
| Renderers | Render screen shake | `C_OP_RenderScreenShake` |
| Renderers | Render sound | `C_OP_RenderSound` |
| Renderers | Render Status Effect | `C_OP_RenderStatusEffect` |
| Renderers | Render Status Effect (Citadel) | `C_OP_RenderStatusEffectCitadel` |
| Renderers | Render Status Effect (Tf) | `C_OP_RenderStatusEffectTf` |
| Renderers | Render Flatten Grass | `C_OP_RenderFlattenGrass` |
| Renderers | Render Tree Shake | `C_OP_RenderTreeShake` |
| Renderers | Render Text | `C_OP_RenderText` |
| Renderers | Render Callback | `C_OP_Callback` |
| Renderers | Render VR Haptic Event | `C_OP_RenderVRHapticEvent` |
| Renderers | Render Post Processing | `C_OP_RenderPostProcessing` |
| Renderers | Render material attribute proxy | `C_OP_RenderMaterialProxy` |
| Renderers | Render Simple Model Collection | `C_OP_RenderSimpleModelCollection` |
| Renderers | Render Client Physics Objects | `C_OP_ClientPhysics` |
| Renderers | Render client physics radial impulse | `C_OP_RenderClientPhysicsImpulse` |
| Renderers | Render Game Decal Trace From Event | `C_OP_GameDecalRenderer` |
| Renderers | Render Water Ripple Impulse from Event | `C_OP_WaterImpulseRenderer` |
| Renderers | Render Liquid Spill | `C_OP_GameLiquidSpill` |
| Renderers | Render Create Particle System From Event | `C_OP_CreateParticleSystemRenderer` |
| Renderers | Render volumetric smoke | `C_OP_RenderVolumetricEmitter` |
