# CS2 Soundevent 写法、函数和参数参考

提取日期：2026-10-14。范围：本机 CS2 的 game/core 和 game/csgo 两个 pak01_dir.vpk 中全部 soundevents / soundstacks 编译资源，另对照官方 addon_template 源文件及用户提供的 ValveResourceFormat。原始游戏脚本只保存在本地分析副本，没有上传。

## 如何阅读

- “事件类型”是 .vsndevts 中的 type，也就是声音栈名称。
- “操作函数”是 .vsndstck 的 operators[].operator，例如 soundevent_start、vmix_voice_start、math_float。它们不是 C++ 导出函数，表中参数也不是原生调用 ABI。
- 事件参数表列出 public 操作节点的 operator_variables；data_type 来自游戏明确声明，默认值保留原始格式。显示条件仅是编辑器元数据。
- 底层函数参数表收集全部声音栈实际使用的字段。存储类型不等于引擎语义类型：字符串 "1.000000" 可能是浮点输入，"@public.volume" 是连接引用。类型依据和枚举候选会分别标注；候选不是完整枚举。
- 这是本地资源中出现的完整目录，不等于 soundsystem.dll 所有已注册操作函数的全集。未在资源出现的函数、字段、输出及取值范围仍需 DLL 注册表验证。
- 包含诊断、内部和工具栈；存在定义不代表所有类型适合地图作者直接使用。没有进行新声音文件编译、实机播放或原生写入验证。

## 文件写法

官方模板位于 content/csgo_addons/addon_template/soundevents/soundevents_addon.vsndevts。模板注明 addon 声音事件应保留该文件名，将新事件放入其中。路径以 addon 的 content 为基准，引用 .vsnd，不写磁盘绝对路径或 .vsnd_c。

以下是自编示例；把音频路径替换为自己的已导入声音。事件名可自定，在 Hammer 的 soundevent 属性填同一个名字。

```kv3
<!-- kv3 encoding:text:version{e21c7f3c-8a33-41c5-9977-a76d3a32aa0d} format:generic:version{7412167c-06e9-4698-aff2-e63eb59037e7} -->
{
    "Example.Base" =
    {
        type = "csgo_mega"
        volume = 0.8
        pitch = 1.0
        vsnd_files_track_01 = "sounds/example/beep.vsnd"
    }
    "Example.Random" =
    {
        base = "Example.Base"
        volume = 0.5
        vsnd_files_track_01 =
        [
            "sounds/example/beep_a.vsnd",
            "sounds/example/beep_b.vsnd",
        ]
        enable_retrigger = true
        retrigger_interval_min = 3.0
        retrigger_interval_max = 8.0
    }
    "Example.Parent" =
    {
        type = "csgo_mega"
        enable_child_events = true
        set_child_position = true
        soundevent_01 = [ "Example.Base", "Example.Random" ]
    }
}
```

type 是栈名字符串；base 是另一事件的名字，继承其配置，同名参数可以覆盖。base 并不是 .vsndevts 文件路径。普通事件无需自己写 operators；只有制作声音栈时才写操作节点。

vsnd_files_track_01 可以是一个声音路径字符串，或者声音路径数组；csgo_mega 从列表选一条。soundevent_01 可以是事件名或事件名数组，配合 enable_child_events。循环背景音需要音频内的循环标记；enable_retrigger 是间歇重触发，不能替代音频循环标记。以上依据官方模板和本地 VRF CSGOMega 实现。

## 参数类型和曲线

bool 写 true / false；float 写 0.5；int / uint32 / uint64 写整数；float3 写 [x,y,z]。string、string_token、mixgroup、dsppreset、vsnd、sndevt 通常写字符串，后两者可按对应字段使用列表。enum 写该字段允许的符号，不要自行套用数字。

float2/4/8/12/float_max_speakers 是声明的定长/扬声器向量；public_opvar 是操作变量相关声明，不自动当作普通字符串。请按具体栈及字段样本核对。没有声明的变量在表中显示“未声明”，不要猜类型。

曲线字段的 data_type 是 float6，每个控制点含六项，源事件一般写控制点数组：
```kv3
use_distance_volume_mapping_curve = true
distance_volume_mapping_curve =
[
    [ 0.0,    1.0, 0.0, 0.0, 0.0, 0.0 ],
    [ 1500.0, 0.0, 0.0, 0.0, 0.0, 0.0 ],
]
```
依据 VRF SoundEventCurve，六项是 [x, y, 入切线, 出切线, 左曲线类型, 右曲线类型]。
VRF 类型映射为 0 Linear、1 Spline、2 Free、3 Mirror、4 Sine、5 Flat；不是本轮 DLL 枚举反射结果。距离曲线 x 表示距离，时间曲线 x 表示时间；音量曲线 y 表示增益。栈默认值有时以 value1/value2 对象存储，文档保留该内部表达，不能直接当作源文件写法。

volume / pitch 的随机上下界在 VRF csgo_mega 中作为基础值的加法偏移。VRF 还对音高和音量作限制，其限制不能直接认定为游戏引擎允许范围。volume_fade_in / volume_fade_out 是 VRF 通用读取字段，本机 csgo_mega 的公开声明以 time_volume_mapping_curve / fadetime_volume_mapping_curve 为主，不把 VRF 支持字段自动当作 CS2 公共参数。

## 常用功能

| 需求 | 参数 / 操作函数 | 配置方向 |
| --- | --- | --- |
| 播放声音 | vsnd_files_track_01 / vmix_voice_start | 音频路径与启动输入 |
| 调整音量、音调 | volume、pitch、对应 random_min/max | 增益、倍率与随机偏移 |
| 子事件 | enable_child_events、soundevent_01、set_child_position / soundevent_start | 子事件列表与位置继承 |
| 间歇触发 | enable_retrigger、retrigger_interval_min/max、retrigger_count | 开关、间隔、次数；-1 等特殊值保留栈默认语义 |
| 空间位置 | position、position_offset、use_world_position、position_relative_to_player | 向量及定位开关 |
| 距离衰减 | distance_volume_mapping_curve / calc_falloff_curve | 距离到音量 |
| 混响 | reverb_wet、reverb_source_wet、override_dsp_preset、dsp_preset | 源与环境混响 |
| 遮挡 | occlusion_intensity、occlusion_interval、use_baked_occlusion | 强度、采样间隔、烘焙开关 |
| 多普勒 | use_doppler、doppler_factor、doppler_factor_receding | 开关与倍率 |
| 限制重叠 | instance_limit、block_matching_events、block_duration | 实例数量与匹配阻挡 |
| 控制事件 | soundevent_control、soundevent_pause、soundevent_stop_all | 停止、暂停等底层操作；按后表的实际字段写 |
| 运算、连接 | math_float、math_random_float、math_curve_2d、opvar_get/set_* | 操作节点按名字连接 |

底层栈连接语法是字符串 "@节点名.输出或变量名"，例如 input1 = "@public.volume"。
operator 的 name 是当前栈内实例名，operator 是函数种类；sos_import_stack 用 import_stack 引用另一栈。导入变量覆盖项可能省略 data_type；它们不算新的类型声明。后表把导入目标单独列出，不把所有内部变量自动暴露为事件参数。

## 依据与复现

本地读取格式参考 [ValveResourceFormat](https://github.com/ValveResourceFormat/ValveResourceFormat)，MIT；本地源码 HEAD f3ad9fba9c58ffe2659a441506b1e81662d15429。相关文件：Resource/ResourceTypes/BinaryKV3.cs、BinaryKV3.NodeType.cs、Renderer/Audio/SoundEventDefinition.cs、SoundEvents/SoundEventCSGOMega.cs、SoundEventCurve.cs。KV3 文本语法亦见 [ValveKeyValue](https://github.com/ValveResourceFormat/ValveKeyValue)。

只读脚本位于本地分析目录 sound_probe.py、extract_sound_inventory.py、generate_sound_reference.py。输入清单 sound_inventory.local.json 仅为本地副本。解析支持本次实际遇到的 KV3 v4/v5，无二进制 blob；遇到不支持格式即记错误。每份资源记录 SHA-256，下面附完整来源清单。解析检查缓冲区消费、类型流和结束标记；不依赖失效的 S2V CLI。此方法只提取文件内容，不调用 soundsystem.dll。


## 本次统计

资源 208 份；解析失败 0 份。声音栈类型 251 个；实际出现的操作函数 138 种；事件定义 21853 个（按名字去重）。

## 事件类型索引

| 类型 | public 参数数 | 导入栈 | 来源 |
| --- | ---: | --- | --- |
| Diagnostic.GetMixGraphInput | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| Diagnostic.TestCrossfade | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| Diagnostic.TestCurve2d | 12 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| Diagnostic.register_sound_area | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| Diagnostic.test_mixgraph_output | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| Diagnostic.test_sound_area | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| Diagnostic.test_threshold_logic | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| Diagnostic.test_wait_time | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| Diagnostic.test_wait_time_test | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| base_event_multiple_vsnd_files | 4 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| beatpattern_4x4 | 13 |  | core/soundstacks/soundstacks_beat_pattern.vsndstck_c |
| child_stack | 4 | parent_stack, parent_stack_2 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| container_arg_test | 4 |  | core/soundstacks/soundstacks_containers_test.vsndstck_c |
| container_env_test | 3 |  | core/soundstacks/soundstacks_containers_test.vsndstck_c |
| container_oneshot_test | 3 |  | core/soundstacks/soundstacks_containers_test.vsndstck_c |
| core_beatpattern_start_pattern | 6 |  | core/soundstacks/soundstacks_beat_pattern.vsndstck_c |
| core_distance_limiter | 2 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_doppler | 5 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_empty | 0 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_global_stack | 0 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_import_test_import | 5 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| core_import_test_import_recursive | 2 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| core_import_test_import_recursive_scope | 2 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| core_import_test_import_scope | 5 | core_import_test_parent1 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| core_import_test_parent1 | 2 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| core_import_test_parent2 | 2 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| core_import_test_parent3 | 2 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| core_max_multiple | 7 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_null_timed | 1 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_pause_soundevent | 7 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_preload_soundevents | 2 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_sampler_base | 35 | core_distance_limiter | core/soundstacks/soundstacks_core.vsndstck_c |
| core_sampler_event | 4 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_set_playerdsp | 3 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_setter_AHR_base | 7 |  | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_AHR_game_volume | 1 | core_setter_AHR_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_AHR_mixgraph_input | 2 | core_setter_AHR_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_AHR_mixlayer_amount | 2 | core_setter_AHR_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_AHR_stack_opvar | 4 | core_setter_AHR_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_curve_base | 3 |  | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_curve_mixgraph_input | 2 | core_setter_curve_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_curve_mixlayer_amount | 2 | core_setter_curve_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_curve_mixlayer_trigger_amount | 2 | core_setter_curve_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_curve_stack_opvar | 4 | core_setter_curve_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_mixgraph_input | 2 |  | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_mixlayer_amount | 2 |  | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_ramp_to_value_base | 6 |  | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_ramp_to_value_mixgraph_input | 1 | core_setter_mixgraph_input, core_setter_ramp_to_value_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_ramp_to_value_mixlayer_amount | 1 | core_setter_mixlayer_amount, core_setter_ramp_to_value_base | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_ramp_to_value_stack_opvar | 1 | core_setter_ramp_to_value_base, core_setter_stack_opvar | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_setter_stack_opvar | 4 |  | core/soundstacks/soundstacks_core_setters.vsndstck_c |
| core_simple_2d | 3 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_simple_3d | 8 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_soundevent_blocker | 6 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_start_oneshot | 7 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_start_simple_oneshot | 9 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_stop_all_soundevents | 4 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_stop_at_time | 1 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_stop_soundevents | 5 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_test_sound | 0 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_valve_default | 9 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_voip | 3 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| core_volume_limiter | 2 |  | core/soundstacks/soundstacks_core.vsndstck_c |
| csgo_ambient | 116 |  | csgo/soundstacks/soundstacks_csgo_ambient.vsndstck_c |
| csgo_mega | 114 |  | csgo/soundstacks/soundstacks_csgo_mega.vsndstck_c |
| csgo_movie | 3 |  | csgo/soundstacks/soundstacks_csgo_core.vsndstck_c |
| csgo_music | 51 |  | csgo/soundstacks/soundstacks_csgo_music.vsndstck_c |
| csgo_music_globals | 0 |  | csgo/soundstacks/soundstacks_csgo_music.vsndstck_c |
| csgo_surf | 93 |  | csgo/soundstacks/soundstacks_csgo_surf.vsndstck_c |
| csgo_voip | 3 |  | csgo/soundstacks/soundstacks_csgo_core.vsndstck_c |
| curve_test_01 | 2 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| curve_test_multi_import | 2 | curve_test_01 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| dave_sb_bang | 0 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| dave_test_floatness | 4 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| dave_test_random_pos | 3 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| dave_test_sb | 0 | soundscape_scalebang | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| dave_test_soundscapes | 22 | soundscape_play_looping, soundscape_play_random | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| dave_timer_test | 0 | util_timer | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| dave_timer_test_reset | 0 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| dave_timer_test_run | 0 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| dave_timer_test_stop | 0 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| dave_timer_test_stop_reset | 0 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| diagnostic.animate_float3_gallery | 4 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostic.self_exciting_column | 14 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostic.self_exciting_gallery | 2 | core_start_oneshot, diagnostic.self_exciting_column | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostic.start_n_soundevents | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostic.timed_beeper | 3 | core_start_oneshot | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostic.timed_silence | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostic.timed_soundevent | 5 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostic.usable_float_range | 5 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostic_globals | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostics_arrays | 12 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| diagnostics_vsnd_lists | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| example_start_oneshot_import_test | 6 | core_start_oneshot | core/soundstacks/soundstacks_examples.vsndstck_c |
| example_timetriggered_simple_oneshot | 5 | core_start_simple_oneshot | core/soundstacks/soundstacks_examples.vsndstck_c |
| group_soundevent_cluster_default_3d_test | 0 |  | core/soundstacks/soundstacks_core_test.vsndstck_c |
| inner_1 | 3 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| inner_2 | 3 | inner_1 | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| no_scope_inner | 2 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| no_scope_main | 1 | no_scope_outer | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| no_scope_outer | 1 | no_scope_inner | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| outer | 2 | inner_2 | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| outer_multi | 2 | inner_2 | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| parent_stack | 1 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| parent_stack_2 | 1 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| soundscape_2d_sound | 12 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_2rand_1loop | 100 | soundscape_play_looping, soundscape_play_random | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_3d_sound | 14 | core_distance_limiter | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_globals | 0 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_looping_sound_2D | 1 | soundscape_2d_sound | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_looping_sound_3D | 1 | soundscape_3d_sound | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_opvar_percentage | 12 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_opvar_switch | 12 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_play_burst | 11 | util_timer | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_play_looping | 18 | soundscape_opvar_switch | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_play_random | 32 | soundscape_opvar_percentage, soundscape_opvar_switch | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_play_soundscape | 3 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_random_sound | 2 | soundscape_3d_sound | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_scalebang | 5 | util_timer | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_test_play_soundscape | 3 | soundscape_play_soundscape | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| soundscape_test_weather | 86 | soundscape_play_looping, soundscape_play_random | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| src1_2d | 19 |  | core/soundstacks/soundstacks_src1.vsndstck_c |
| src1_3d | 25 | core_distance_limiter | core/soundstacks/soundstacks_src1.vsndstck_c |
| src1_soundscape_2d | 19 |  | core/soundstacks/soundstacks_src1.vsndstck_c |
| src1_soundscape_3d | 22 | core_distance_limiter | core/soundstacks/soundstacks_src1.vsndstck_c |
| test_1_layer_1 | 1 | test_1_layer_2 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_1_layer_2 | 3 | test_1_layer_3 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_1_layer_3 | 3 | test_1_layer_4 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_1_layer_4 | 4 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_2_layer_1 | 1 | test_2_layer_2 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_2_layer_2 | 3 | test_2_layer_3 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_2_layer_3 | 3 | test_2_layer_4 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_2_layer_4 | 4 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_3_layer_1 | 2 | test_3_layer_2 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_3_layer_2 | 1 | test_3_layer_3 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_3_layer_3 | 3 | test_3_layer_4 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_3_layer_4 | 1 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_5_layer_0 | 2 | test_5_layer_1 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_5_layer_1 | 2 | test_5_layer_2 | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_5_layer_2 | 2 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |
| test_LFO | 4 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_beep_on_track | 10 | diagnostic.timed_beeper | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_empty | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_entity_aabb | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_enum_opvar | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_eval | 7 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_get_parent_space | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_goto_exit | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_goto_loop_head | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_goto_loop_operator | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_goto_namespace_operator | 0 | test_goto_namespace_operator_import | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_goto_namespace_operator_import | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_group_stop | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_groups_branch_string | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_groups_branch_string_variables | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_groups_entindex_invert | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_groups_envelope | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_groups_opvar_invert | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_groups_persist | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_groups_read_envelope | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_groups_subname_invert | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_harmonic_tools | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_import_get_parent_space | 0 | test_soundevent_start_opvar_get_parent_space | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_import_opvar_field | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_import_random_multiple | 0 | test_random_multiple | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_inverse_vec3 | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_random_multiple | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_ryan_imported | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_ryan_outer | 1 | test_ryan_imported | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_simple_public_field | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_block | 3 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_control_lfo_stop_at_time | 0 | core_stop_at_time, update_test_start_vsnd_lfo | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_field_override | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_group_simple | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_group_simple_opvar | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_groups | 7 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_limiter_lfo | 3 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_start_lfo | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_start_multi | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_start_oneshot | 5 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_start_opvar_get_ancestor | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_start_opvar_get_parent | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_start_opvar_get_parent_space | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_soundevent_start_random_multiple | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_start_soundevent | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_start_soundevent_loop | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_stop_track | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_switch_case_12 | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_system_properties | 9 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_timers | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_usable_float_range | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_vmix_8track | 22 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_vmix_voice_sends | 9 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_vmix_vsnd_info | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_vsnd_loop_xfade | 10 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_vsnd_on_track | 13 | update_test_start_vsnd_rand_oneshot | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| test_vsnd_on_track2 | 10 | update_test_start_vsnd_rand_oneshot | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_array_index_event_increment | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_array_index_event_sequence | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_array_index_global_stack_sequence | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_array_index_stack_increment | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_calc_distance | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_convar | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_delta | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_distant_dsp | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_entity_info | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_env_beep_mixlayer_timing | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_env_beep_timing | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_env_timing | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_falloff | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_float_filter | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_import_op | 1 | update_test_overrides | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_iterate_merge_speakers | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_lfo_beep | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_lfo_beep_env_trigger | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_lfo_beep_timing | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_lfo_timing | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_listener_velocity | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_math_string | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_mixer | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_mixgroup_timing | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_mixlayer | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_occlusion | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_opvar | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_opvar_event_max_multi_sequence | 9 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_opvar_event_multi_sequence | 3 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_opvar_event_sequence | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_opvar_global_stack_sequence | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_opvar_stack_sequence | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_opvar_types | 10 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_overrides | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_simple_import_op | 1 | update_test_simple_public | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_simple_nest_import_op1 | 1 | update_test_simple_public | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_simple_nest_import_op2 | 1 | update_test_simple_nest_import_op1 | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_simple_nest_import_op3 | 1 | update_test_simple_nest_import_op2 | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_simple_nest_import_op4 | 1 | update_test_simple_nest_import_op3 | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_simple_public | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_simple_serial_import_op | 3 | update_test_simple_public | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_simple_serial_import_op2 | 1 | update_test_simple_public | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_start_event_vsnd_rand_oneshot | 3 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_start_event_vsnd_rand_weighted_oneshot | 4 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_start_stack_vsnd_rand_oneshot | 5 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_start_vsnd_lfo | 8 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_start_vsnd_rand_oneshot | 7 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_start_vsnd_tracks | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_utils | 0 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_vsnd_envelope | 1 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| update_test_vsnd_simple_loop | 2 |  | core/soundstacks/soundstacks_diagnostics.vsndstck_c |
| util_float3_lerp | 12 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| util_timer | 3 |  | core/soundstacks/soundstacks_soundscapes_core.vsndstck_c |
| vsnd_base_stack | 4 |  | core/soundstacks/soundstacks_import_opvars_test.vsndstck_c |

## 事件类型的可设定参数


### csgo_mega

来源：csgo/soundstacks/soundstacks_csgo_mega.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| mixgroup | string | "Dialog" | Mixer / normal |   |
| set_mixlayer_amount_enable | bool | "false" | Mixer / normal |   |
| set_mixlayer_layer | string | "" | Mixer / normal |   |
| time_mixlayer_amount_curve | float6 | {"value1":"[0.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[1.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value3":"[2.000000,0.000000,0.000000,0.000000,2.000000,3.000000]"} | Mixer / normal | public.set_mixlayer_amount_enable  |
| volume | float | "1.000000" | Volume /  |   |
| volume_random_min | float | "0.000000" | Volume /  |   |
| volume_random_max | float | "0.000000" | Volume /  |   |
| use_distance_volume_mapping_curve | bool | "true" | Volume / normal |   |
| distance_volume_mapping_curve | float6 | "" | Volume / normal | public.use_distance_volume_mapping_curve  |
| ducking_bypass | float | "0.000000" | Volume / normal |   |
| vsnd_files_track_01 | vsnd | "sounds/common/null.vsnd" | VSNDS /  |   |
| pitch | float | "1.000000" | Pitch /  |   |
| pitch_random_min | float | "0.000000" | Pitch /  |   |
| pitch_random_max | float | "0.000000" | Pitch /  |   |
| use_distance_pitch_mapping_curve | bool | "false" | Pitch / normal |   |
| distance_pitch_mapping_curve | float6 | "" | Pitch / normal | public.use_distance_pitch_mapping_curve  |
| enable_child_events | bool | "false" | Children / normal |   |
| set_child_position | bool | "true" | Children / normal |   |
| soundevent_01 | sndevt | "" | Children / normal |   |
| delay | float | "0" | Time / normal |   |
| self_destruct_time | float | "-1" | Time / normal |   |
| randomize_start_time | bool | "false" | Time / normal |   |
| use_fadetime_volume_mapping_curve | bool | "true" | Time / normal |   |
| fadetime_volume_mapping_curve | float6 | "" | Time / normal | public.use_fadetime_volume_mapping_curve  |
| use_time_volume_mapping_curve | bool | "false" | Time / normal |   |
| time_volume_mapping_curve | float6 | {"value1":"[0.000000,0.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[0.500000,0.500000,0.000000,0.000000,2.000000,3.000000]","value3":"[1.000000,1.000000,0.000000,0.000000,2.000000,3.000000]"} | Time / normal | public.use_time_volume_mapping_curve  |
| use_distance_unfiltered_stereo_mapping_curve | bool | "false" | Spread / normal |   |
| distance_unfiltered_stereo_mapping_curve | float6 | "" | Spread / normal | public.use_distance_unfiltered_stereo_mapping_curve  |
| use_time_unfiltered_stereo_mapping_curve | bool | "false" | Spread / normal |   |
| time_unfiltered_stereo_mapping_curve | float6 | "" | Spread / normal | public.use_time_unfiltered_stereo_mapping_curve  |
| position | float3 | "[0.0, 0.0, 0.0]" | Position /  |   |
| position_offset | float3 | "[0.0, 0.0, 0.0]" | Position /  |   |
| position_offset_relative | bool | "false" | Position /  |   |
| is_ui_sound | bool | "false" | Position /  |   |
| use_uiposition | bool | "false" | Position /  |   |
| uiposition | float3 | "[0.0, 0.0, 0.0]" | Position /  |   |
| source_soundscape | int | "-1" | Position / advanced |   |
| ambient_position_override | int | "-1" | Position / normal |   |
| use_world_position | bool | "false" | Position /  |   |
| position_relative_to_player | bool | "false" | Position /  |   |
| use_entity_position_if_local_player | bool | "false" | Position /  |   |
| distance_multiplier | float | "1" | Position / normal |   |
| randomize_position_min_radius | float | "0.000000" | Position / normal |   |
| randomize_position_max_radius | float | "0.000000" | Position / normal |   |
| randomize_position_hemisphere | bool | "false" | Position / normal |   |
| attachment | string_token | "" | Position / locked |   |
| vsnd_pause_with_game | bool | "true" | Gameplay /  |   |
| display_broadcast | bool | "false" | Gameplay / normal |   |
| broadcast_distance_override | float | "0" | Gameplay / normal |   |
| relevant_player | int | "-1" | Gameplay / normal |   |
| enable_retrigger | bool | "false" | Retrigger / normal |   |
| retrigger_interval_min | float | "1.000000" | Retrigger / normal |   |
| retrigger_interval_max | float | "1.000000" | Retrigger / normal |   |
| retrigger_radius | float | "1000.000000" | Retrigger / normal |   |
| retrigger_count | float | "-1" | Retrigger / normal |   |
| instance_limit | float | "0" | Voice Management / normal |   |
| block_matching_events | bool | "true" | Voice Management / normal |   |
| block_match_entity | bool | "true" | Voice Management / normal |   |
| block_duration | float | "0.010000" | Voice Management / normal |   |
| block_distance | float | "12.000000" | Voice Management / normal |   |
| block_other | bool | "false" | Voice Management / normal |   |
| block_other_name | string | "" | Voice Management / normal |   |
| block_other_distance | float | "0.000000" | Voice Management / normal |   |
| block_other_duration | float | "0.000000" | Voice Management / normal |   |
| voice_fade_out_time | float | "0.200000" | Voice Management / normal |   |
| voice_culling_threshold | float | "0.001000" | Voice Management / normal |   |
| voice_looped_culling_update_time | float | "0.500000" | Voice Management / normal |   |
| reverb_wet | float | "0.000000" | Reverb / normal |   |
| reverb_source_wet | float | "1.000000" | Reverb / normal |   |
| distance_effect_mix | float | "1.000000" | Reverb / normal |   |
| override_dsp_preset | bool | "false" | Reverb / normal |   |
| dsp_preset | dsppreset | "" | Reverb / normal |   |
| dsp_bypass | float | "0.000000" | Reverb / normal |   |
| dsp_blend | float | "-1.000000" | Reverb / normal |   |
| restrict_source_reverb | bool | "false" | Reverb / normal |   |
| occlusion_intensity | float | "0.000000" | Occlusion / normal |   |
| occlusion_interval | float | "1.000000" | Occlusion / normal |   |
| occlusion_frequency_scale | float | "1.000000" | Occlusion / normal |   |
| use_baked_occlusion | bool | "false" | Occlusion /  |   |
| occlusion_path_curve | float6 | "" | Occlusion / normal | public.use_baked_occlusion  |
| use_doppler | bool | "false" | Doppler / normal |   |
| doppler_factor | float | "1.000000" | Doppler / normal |   |
| doppler_factor_receding | float | "1.000000" | Doppler / normal |   |
| impact_speed_input | float | "1.000000" | Physics /  |   |
| use_impact_speed_input_volume_mapping_curve | bool | "false" | Physics / normal |   |
| impact_speed_input_volume_mapping_curve | float6 | "" | Physics / normal | public.use_impact_speed_input_volume_mapping_curve  |
| use_velocity_volume_curve | bool | "false" | Physics /  |   |
| velocity_magnitude | float | "0" | Physics /  |   |
| velocity_volume_seek_speed | float | "100" | Physics /  |   |
| velocity_volume_curve | float6 | "" | Physics / normal | public.use_velocity_volume_curve  |
| metadata | string | {"value":"meta"} | Tags /  |   |
| use_volume_convar | bool | "false" | Convar / normal |   |
| volume_convar | string | "" | Convar / normal |   |
| retrigger_keepalive_override | float | "0.0" |  / advanced |   |
| use_ambient_entity_position | bool | "0.0" | Position / normal |   |
| ambient_entity_name | string | "" | Position / normal |   |
| input_field5 | float | "0.0" |  / advanced |   |
| input_field6 | float | "0.0" |  / advanced |   |
| input_field7 | float | "0.0" |  / advanced |   |
| input_field8 | float | "0.0" |  / advanced |   |
| input_field9 | float | "0.0" |  / advanced |   |
| input_field10 | float | "0.0" |  / advanced |   |
| input_field11 | float | "0.0" |  / advanced |   |
| input_field12 | float | "0.0" |  / advanced |   |
| input_field13 | float | "0.0" |  / advanced |   |
| input_field14 | float | "0.0" |  / advanced |   |
| input_field15 | float | "0.0" |  / advanced |   |
| suppressed | bool | "0.0" | advanced /  |   |
| suppression_enable | bool | "0.0" | Suppression /  |   |
| suppression_volume_multiplier | float | "1" | Suppression /  |   |
| suppression_falloff_multiplier | float | "1" | Suppression /  |   |
| suppression_vsnd_override | vsnd | "0.0" | Suppression /  |   |
| input_field1 | float | "0.0" |  /  |   |
| input_field2 | float | "0.0" |  /  |   |

### csgo_ambient

来源：csgo/soundstacks/soundstacks_csgo_ambient.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| mixgroup | string | "Dialog" | Mixer / normal |   |
| set_mixlayer_amount_enable | bool | "false" | Mixer / normal |   |
| set_mixlayer_layer | string | "" | Mixer / normal |   |
| time_mixlayer_amount_curve | float6 | {"value1":"[0.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[1.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value3":"[2.000000,0.000000,0.000000,0.000000,2.000000,3.000000]"} | Mixer / normal | public.set_mixlayer_amount_enable  |
| volume | float | "1.000000" | Volume /  |   |
| volume_random_min | float | "0.000000" | Volume /  |   |
| volume_random_max | float | "0.000000" | Volume /  |   |
| use_distance_volume_mapping_curve | bool | "true" | Volume / normal |   |
| distance_volume_mapping_curve | float6 | "" | Volume / normal | public.use_distance_volume_mapping_curve  |
| ducking_bypass | float | "0.000000" | Volume / normal |   |
| vsnd_files_track_01 | vsnd | "sounds/common/null.vsnd" | VSNDS /  |   |
| pitch | float | "1.000000" | Pitch /  |   |
| pitch_random_min | float | "0.000000" | Pitch /  |   |
| pitch_random_max | float | "0.000000" | Pitch /  |   |
| use_distance_pitch_mapping_curve | bool | "false" | Pitch / normal |   |
| distance_pitch_mapping_curve | float6 | "" | Pitch / normal | public.use_distance_pitch_mapping_curve  |
| enable_child_events | bool | "false" | Children / normal |   |
| set_child_position | bool | "true" | Children / normal |   |
| soundevent_01 | sndevt | "" | Children / normal |   |
| delay | float | "0" | Time / normal |   |
| self_destruct_time | float | "-1" | Time / normal |   |
| randomize_start_time | bool | "false" | Time / normal |   |
| use_fadetime_volume_mapping_curve | bool | "true" | Time / normal |   |
| fadetime_volume_mapping_curve | float6 | "" | Time / normal | public.use_fadetime_volume_mapping_curve  |
| use_time_volume_mapping_curve | bool | "false" | Time / normal |   |
| time_volume_mapping_curve | float6 | {"value1":"[0.000000,0.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[0.500000,0.500000,0.000000,0.000000,2.000000,3.000000]","value3":"[1.000000,1.000000,0.000000,0.000000,2.000000,3.000000]"} | Time / normal | public.use_time_volume_mapping_curve  |
| use_distance_unfiltered_stereo_mapping_curve | bool | "false" | Spread / normal |   |
| distance_unfiltered_stereo_mapping_curve | float6 | "" | Spread / normal | public.use_distance_unfiltered_stereo_mapping_curve  |
| use_time_unfiltered_stereo_mapping_curve | bool | "false" | Spread / normal |   |
| time_unfiltered_stereo_mapping_curve | float6 | "" | Spread / normal | public.use_time_unfiltered_stereo_mapping_curve  |
| position | float3 | "[0.0, 0.0, 0.0]" | Position /  |   |
| position_offset | float3 | "[0.0, 0.0, 0.0]" | Position /  |   |
| position_offset_relative | bool | "false" | Position /  |   |
| is_ui_sound | bool | "false" | Position /  |   |
| use_uiposition | bool | "false" | Position /  |   |
| uiposition | float3 | "[0.0, 0.0, 0.0]" | Position /  |   |
| source_soundscape | int | "-1" | Position / advanced |   |
| ambient_position_override | int | "-1" | Position / normal |   |
| use_world_position | bool | "false" | Position /  |   |
| position_relative_to_player | bool | "false" | Position /  |   |
| use_entity_position_if_local_player | bool | "false" | Position /  |   |
| distance_multiplier | float | "1" | Position / normal |   |
| randomize_position_min_radius | float | "0.000000" | Position / normal |   |
| randomize_position_max_radius | float | "0.000000" | Position / normal |   |
| randomize_position_hemisphere | bool | "false" | Position / normal |   |
| attachment | string_token | "" | Position / locked |   |
| vsnd_pause_with_game | bool | "true" | Gameplay /  |   |
| display_broadcast | bool | "false" | Gameplay / normal |   |
| broadcast_distance_override | float | "0" | Gameplay / normal |   |
| relevant_player | int | "-1" | Gameplay / normal |   |
| enable_retrigger | bool | "false" | Retrigger / normal |   |
| retrigger_interval_min | float | "1.000000" | Retrigger / normal |   |
| retrigger_interval_max | float | "1.000000" | Retrigger / normal |   |
| retrigger_radius | float | "1000.000000" | Retrigger / normal |   |
| retrigger_count | float | "-1" | Retrigger / normal |   |
| instance_limit | float | "0" | Voice Management / normal |   |
| block_matching_events | bool | "true" | Voice Management / normal |   |
| block_match_entity | bool | "true" | Voice Management / normal |   |
| block_duration | float | "0.010000" | Voice Management / normal |   |
| block_distance | float | "12.000000" | Voice Management / normal |   |
| block_other | bool | "false" | Voice Management / normal |   |
| block_other_name | string | "" | Voice Management / normal |   |
| block_other_distance | float | "0.000000" | Voice Management / normal |   |
| block_other_duration | float | "0.000000" | Voice Management / normal |   |
| voice_fade_out_time | float | "0.200000" | Voice Management / normal |   |
| voice_culling_threshold | float | "0.001000" | Voice Management / normal |   |
| voice_looped_culling_update_time | float | "0.500000" | Voice Management / normal |   |
| reverb_wet | float | "0.000000" | Reverb / normal |   |
| reverb_source_wet | float | "1.000000" | Reverb / normal |   |
| distance_effect_mix | float | "1.000000" | Reverb / normal |   |
| override_dsp_preset | bool | "false" | Reverb / normal |   |
| dsp_preset | dsppreset | "" | Reverb / normal |   |
| dsp_bypass | float | "0.000000" | Reverb / normal |   |
| dsp_blend | float | "-1.000000" | Reverb / normal |   |
| restrict_source_reverb | bool | "false" | Reverb / normal |   |
| occlusion_intensity | float | "0.000000" | Occlusion / normal |   |
| occlusion_interval | float | "1.000000" | Occlusion / normal |   |
| occlusion_frequency_scale | float | "1.000000" | Occlusion / normal |   |
| use_baked_occlusion | bool | "false" | Occlusion /  |   |
| occlusion_path_curve | float6 | "" | Occlusion / normal | public.use_baked_occlusion  |
| use_doppler | bool | "false" | Doppler / normal |   |
| doppler_factor | float | "1.000000" | Doppler / normal |   |
| doppler_factor_receding | float | "1.000000" | Doppler / normal |   |
| impact_speed_input | float | "1.000000" | Physics /  |   |
| use_impact_speed_input_volume_mapping_curve | bool | "false" | Physics / normal |   |
| impact_speed_input_volume_mapping_curve | float6 | "" | Physics / normal | public.use_impact_speed_input_volume_mapping_curve  |
| use_velocity_volume_curve | bool | "false" | Physics /  |   |
| velocity_magnitude | float | "0" | Physics /  |   |
| velocity_volume_seek_speed | float | "100" | Physics /  |   |
| velocity_volume_curve | float6 | "" | Physics / normal | public.use_velocity_volume_curve  |
| metadata | string | {"value":"meta"} | Tags /  |   |
| use_volume_convar | bool | "false" | Convar / normal |   |
| volume_convar | string | "" | Convar / normal |   |
| retrigger_keepalive_override | float | "0.0" |  / advanced |   |
| use_ambient_entity_position | bool | "0.0" | Position / normal |   |
| ambient_entity_name | string | "" | Position / normal |   |
| input_field5 | float | "0.0" |  / advanced |   |
| input_field6 | float | "0.0" |  / advanced |   |
| input_field7 | float | "0.0" |  / advanced |   |
| input_field8 | float | "0.0" |  / advanced |   |
| input_field9 | float | "0.0" |  / advanced |   |
| input_field10 | float | "0.0" |  / advanced |   |
| input_field11 | float | "0.0" |  / advanced |   |
| input_field12 | float | "0.0" |  / advanced |   |
| input_field13 | float | "0.0" |  / advanced |   |
| input_field14 | float | "0.0" |  / advanced |   |
| input_field15 | float | "0.0" |  / advanced |   |
| suppressed | bool | "0.0" | advanced /  |   |
| suppression_enable | bool | "0.0" | Suppression /  |   |
| suppression_volume_multiplier | float | "1" | Suppression /  |   |
| suppression_falloff_multiplier | float | "1" | Suppression /  |   |
| suppression_vsnd_override | vsnd | "0.0" | Suppression /  |   |
| input_field1 | float | "0.0" |  /  |   |
| input_field2 | float | "0.0" |  /  |   |
| ambient_entity_index | float | "-1" | Position /  |   |
| child_entity_spawned | bool | "0.0" | Position /  |   |

### csgo_movie

来源：csgo/soundstacks/soundstacks_csgo_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.0" |  /  |   |
| vsnd_files | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| memory_type | float | "0" |  /  |   |

### csgo_music

来源：csgo/soundstacks/soundstacks_csgo_music.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| mixgroup | string | "Music" |  / normal |   |
| volume | float | "1.0" |  /  |   |
| pitch | float | "1.0" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| vsnd_selection_type | enum | "random_exclusive" |  /  |  opvar_get_vsnd.array_selection_type |
| vsnd_weights | float | "0" |  /  |   |
| startpoint_01 | float | "0.0" |  /  |   |
| startpoint_02 | float | "0.0" |  /  |   |
| startpoint_03 | float | "0.0" |  /  |   |
| restart_startpoint_01 | float | "0.0" |  /  |   |
| restart_startpoint_02 | float | "0.0" |  /  |   |
| restart_startpoint_03 | float | "0.0" |  /  |   |
| endpoint_01 | float | "0.0" |  /  |   |
| endpoint_02 | float | "0.0" |  /  |   |
| endpoint_03 | float | "0.0" |  /  |   |
| syncpoints_01 | float | 未指定 |  /  |   |
| syncpoints_02 | float | 未指定 |  /  |   |
| syncpoints_03 | float | 未指定 |  /  |   |
| sync_action_to_startround | float | "0" |  /  |   |
| volume_convar | string | "snd_musicvolume" |  /  |   |
| use_mode_music_volume | bool | "true" |  /  |   |
| volume_fade_initial_input_min | float | "0.0" |  /  |   |
| volume_fade_initial_input_max | float | "0.0" |  /  |   |
| volume_fade_initial_input_map_min | float | "1.0" |  /  |   |
| volume_fade_initial_input_map_max | float | "1.0" |  /  |   |
| volume_fade_out_input_max | float | "1.0" |  /  |   |
| stop_music | bool | "false" |  /  |   |
| stop_music_except_mvp | bool | "false" |  /  |   |
| stop_all_non_music | bool | "false" |  /  |   |
| priority | float | "0.0" |  /  |   |
| priority_override | bool | "false" |  /  |   |
| stop_at_time | float | "-1.0" |  /  |   |
| loop_track | bool | "false" |  /  |   |
| stop_tensec_count | bool | "false" |  /  |   |
| stop_bomb_planted | bool | "false" |  /  |   |
| stop_got_hostage | bool | "false" |  /  |   |
| stop_start_round | bool | "false" |  /  |   |
| check_for_classic_deathcam | bool | "false" |  /  |   |
| should_queue_track | bool | "false" |  /  |   |
| update_track_syncpoint_index | bool | "false" |  /  |   |
| stop_selection_music | bool | "false" |  /  |   |
| stop_won_mvp | bool | "false" |  /  |   |
| stop_match_end | bool | "false" |  /  |   |
| stop_loading | bool | "false" |  /  |   |
| skip_if_muted | bool | "false" |  /  |   |
| block_won_lost | bool | "false" |  /  |   |
| test_mvp_block | bool | "false" |  /  |   |
| join_non_mvp_group | bool | "false" |  /  |   |
| set_mixlayer_amount_enable | bool | "false" | Mixer / normal |   |
| set_mixlayer_layer | string | "" | Mixer / normal |   |
| time_mixlayer_amount_curve | float6 | {"value1":"[0.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[1.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value3":"[2.000000,0.000000,0.000000,0.000000,2.000000,3.000000]"} | Mixer / normal | public.set_mixlayer_amount_enable  |

### csgo_music_globals

来源：csgo/soundstacks/soundstacks_csgo_music.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### csgo_surf

来源：csgo/soundstacks/soundstacks_csgo_surf.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| mixgroup | string | "Dialog" |  / normal |   |
| volume | float | "1.000000" |  /  |   |
| volume_random_min | float | "0.000000" |  /  |   |
| volume_random_max | float | "0.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| pitch_random_min | float | "0.000000" |  /  |   |
| pitch_random_max | float | "0.000000" |  /  |   |
| vsnd_files_track_01 | vsnd | "sounds/common/null.vsnd" |  /  |   |
| impact_speed_input | float | "1.000000" |  /  |   |
| delay | float | "0" |  / normal |   |
| instance_limit | float | "0" |  / normal |   |
| display_broadcast | bool | "false" | Sound Events / normal |   |
| broadcast_distance_override | float | "0" | Sound Events / normal |   |
| enable_child_events | bool | "false" | Sound Events / normal |   |
| set_child_position | bool | "true" | Sound Events / normal |   |
| soundevent_01 | sndevt | "" | Sound Events / normal |   |
| position | float3 | "[0.0, 0.0, 0.0]" | Position /  |   |
| position_offset | float3 | "[0.0, 0.0, 0.0]" | Position /  |   |
| position_offset_relative | bool | "false" | Position /  |   |
| is_ui_sound | bool | "false" |  /  |   |
| use_uiposition | bool | "false" |  /  |   |
| uiposition | float3 | "[0.0, 0.0, 0.0]" | Position /  |   |
| source_soundscape | int | "-1" | Position /  |   |
| use_baked_occlusion | bool | "false" | Position /  |   |
| occlusion_path_curve | float6 | {"value1":"1.0000 0.3000 0.0000 0.000 0.000 0.000","value2":"2.0000 0.8000 0.0000 0.000 0.000 0.000","value3":"4.0000 1.00000 0.0000 0.000 0.000 0.000"} |  / advanced | public.use_baked_occlusion  |
| use_world_position | bool | "false" | Position /  |   |
| position_relative_to_player | bool | "false" | Position /  |   |
| use_entity_position_if_local_player | bool | "false" | Position /  |   |
| vsnd_pause_with_game | bool | "true" |  /  |   |
| self_destruct_time | float | "-1" |  / normal |   |
| block_matching_events | bool | "true" | block:Block Events / normal |   |
| block_match_entity | bool | "true" | block:Block Events / normal |   |
| block_duration | float | "0.010000" | block:Block Events / normal |   |
| block_distance | float | "12.000000" | block:Block Events / normal |   |
| block_other | bool | "false" | block:Block Other Events / normal |   |
| block_other_name | string | "" | block:Block Other Events / normal |   |
| block_other_distance | float | "0.000000" | block:Block Other Events / normal |   |
| block_other_duration | float | "0.000000" | block:Block Other Events / normal |   |
| distance_multiplier | float | "1" | Position / normal |   |
| attachment | string_token | "" |  / locked |   |
| use_doppler | bool | "false" | Doppler / normal |   |
| doppler_factor | float | "1.000000" | Doppler / normal |   |
| doppler_factor_receding | float | "1.000000" | Doppler / normal |   |
| reverb_wet | float | "0.000000" | Reverb / normal |   |
| reverb_source_wet | float | "1.000000" | Reverb / normal |   |
| override_dsp_preset | bool | "false" | Reverb / normal |   |
| dsp_preset | dsppreset | "" | Reverb / normal |   |
| dsp_bypass | float | "0.000000" | Player DSP / normal |   |
| dsp_blend | float | "-1.000000" | Player DSP / normal |   |
| ducking_bypass | float | "0.000000" | Player DSP / normal |   |
| randomize_position_min_radius | float | "0.000000" | Position / normal |   |
| randomize_position_max_radius | float | "0.000000" | Position / normal |   |
| randomize_position_hemisphere | bool | "false" | Position / normal |   |
| occlusion_intensity | float | "0.000000" | Reverb / normal |   |
| occlusion_interval | float | "1.000000" | Reverb / normal |   |
| occlusion_frequency_scale | float | "1.000000" | Reverb / normal |   |
| metadata | string | {"value":"meta"} |  /  |   |
| relevant_player | int | "-1" |  / advanced |   |
| distance_effect_mix | float | "1.000000" | Position / normal |   |
| restrict_source_reverb | bool | "false" | Reverb / normal |   |
| voice_fade_out_time | float | "0.200000" | Voice Management / normal |   |
| voice_culling_threshold | float | "0.001000" | Voice Management / normal |   |
| voice_looped_culling_update_time | float | "0.500000" | Voice Management / normal |   |
| enable_retrigger | bool | "false" | Retrigger / normal |   |
| retrigger_interval_min | float | "1.000000" | Retrigger / normal |   |
| retrigger_interval_max | float | "1.000000" | Retrigger / normal |   |
| retrigger_radius | float | "1000.000000" | Retrigger / normal |   |
| retrigger_count | float | "-1" | Retrigger / normal |   |
| distance_volume_mapping_curve | float6 | {"value1":"[0.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[150.000000,0.500000,0.000000,0.000000,2.000000,3.000000]","value3":"[300.000000,0.000000,0.000000,0.000000,2.000000,3.000000]"} |  / advanced | public.use_distance_volume_mapping_curve  |
| use_distance_volume_mapping_curve | bool | "true" | Curves / normal |   |
| distance_unfiltered_stereo_mapping_curve | float6 | {"value1":"[0.000000,0.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[150.000000,0.000000,0.000000,0.000000,2.000000,3.000000]","value3":"[300.000000,1.000000,0.000000,0.000000,2.000000,3.000000]"} |  / advanced | public.use_distance_unfiltered_stereo_mapping_curve  |
| use_distance_unfiltered_stereo_mapping_curve | bool | "false" | Curves / normal |   |
| fadetime_volume_mapping_curve | float6 | {"value1":"[0.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[0.500000,0.500000,0.000000,0.000000,2.000000,3.000000]","value3":"[1.000000,0.000000,0.000000,0.000000,2.000000,3.000000]"} |  / advanced | public.use_fadetime_volume_mapping_curve  |
| use_fadetime_volume_mapping_curve | bool | "true" | Curves / normal |   |
| time_volume_mapping_curve | float6 | {"value1":"[0.000000,0.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[0.500000,0.500000,0.000000,0.000000,2.000000,3.000000]","value3":"[1.000000,1.000000,0.000000,0.000000,2.000000,3.000000]"} |  / advanced | public.use_time_volume_mapping_curve  |
| use_time_volume_mapping_curve | bool | "false" | Curves / normal |   |
| impact_speed_input_volume_mapping_curve | float6 | {"value1":"[0.000000,0.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[0.500000,0.500000,0.000000,0.000000,2.000000,3.000000]","value3":"[1.000000,1.000000,0.000000,0.000000,2.000000,3.000000]"} |  / advanced | public.use_impact_speed_input_volume_mapping_curve  |
| use_impact_speed_input_volume_mapping_curve | bool | "false" | Curves / normal |   |
| distance_pitch_mapping_curve | float6 | {"value1":"[0.000000,0.800000,0.000000,0.000000,2.000000,3.000000]","value2":"[150.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value3":"[300.000000,1.200000,0.000000,0.000000,2.000000,3.000000]"} |  / advanced | public.use_distance_pitch_mapping_curve  |
| use_distance_pitch_mapping_curve | bool | "false" | Curves / normal |   |
| time_unfiltered_stereo_mapping_curve | float6 | {"value1":"[0.000000,0.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[2.500000,0.000000,0.000000,0.000000,2.000000,3.000000]","value3":"[5.000000,1.000000,0.000000,0.000000,2.000000,3.000000]"} |  / advanced | public.use_time_unfiltered_stereo_mapping_curve  |
| use_time_unfiltered_stereo_mapping_curve | bool | "false" | Curves / normal |   |
| use_volume_convar | bool | "false" | Sound Events / normal |   |
| volume_convar | string | "" | Sound Events / normal |   |
| set_mixlayer_amount_enable | bool | "false" | Mixlayer / normal |   |
| set_mixlayer_layer | string | "" | Mixlayer / normal |   |
| time_mixlayer_amount_curve | float6 | {"value1":"[0.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[1.000000,1.000000,0.000000,0.000000,2.000000,3.000000]","value3":"[2.000000,0.000000,0.000000,0.000000,2.000000,3.000000]"} |  / advanced | public.set_mixlayer_amount_enable  |
| use_velocity_volume_curve | bool | "false" | Velocity /  |   |
| use_velocity_eq | bool | "false" | Velocity /  |   |
| velocity_magnitude | float | "0" | Velocity /  |   |
| velocity_volume_seek_speed | float | "100" | Velocity /  |   |
| velocity_volume_curve | float6 | {"value1":"[0.000000,0.000000,0.000000,0.000000,2.000000,3.000000]","value2":"[150.000000,0.000000,0.000000,0.000000,2.000000,3.000000]","value3":"[300.000000,1.000000,0.000000,0.000000,2.000000,3.000000]"} |  / advanced | public.use_velocity_volume_curve  |
| keepalive | float | "0" |  / advanced |   |

### csgo_voip

来源：csgo/soundstacks/soundstacks_csgo_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.0" |  /  |   |
| vsnd_files | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| memory_type | float | "0" |  /  |   |

### Diagnostic.GetMixGraphInput

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| input_name | string | "PlayerDSP" |  /  |   |

### Diagnostic.TestCrossfade

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| input | float | "0.000000" |  /  |   |
| equal_power_amount | float | "0.000000" |  /  |   |

### Diagnostic.TestCurve2d

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| input | float | "0.000000" |  /  |   |
| curve | float6 | ["[ 0.0, 0.0, 0, 0, 0, 0 ]","[ 0.0, 1.0, 0, 0, 0, 0 ]"] |  /  |   |
| curve_4knot_array | float8 | ["[ 0.0, 0.0, 0.33, 0.0, 0.66, 0, 1.0, 0 ]","[ 0.0, 0.5, 0.33, 0.5, 0.66, 0.5, 1.0, 0.5 ]","[ 0.0, 1.0, 0.33, 1, 0.66, 1, 1.0, 1.0 ]"] |  /  |   |
| curve_6knot_array | float12 | ["[ 0.0, 0.0, 0.33, 0.0, 0.5, 0, 0.66, 0, 0.75, 0, 1.0, 0.0 ]","[ 0.0, 0.5, 0.33, 0.5, 0.5, 0.5, 0.66, 0.5, 0.75, 0.5, 1.0, 0.5 ]","[ 0.0, 1, 0.33, 1, 0.5, 1, 0.66, 1, 0.75, 1, 1.0, 1 ]"] |  /  |   |
| curve_4knot_X1 | float | "0.000000" |  / advanced |   |
| curve_4knot_Y1 | float | "0.000000" |  /  |   |
| curve_4knot_X2 | float | "0.33" |  /  |   |
| curve_4knot_Y2 | float | "0.33" |  /  |   |
| curve_4knot_X3 | float | "0.66" |  /  |   |
| curve_4knot_Y3 | float | "0.66" |  /  |   |
| curve_4knot_X4 | float | "1.0" |  /  |   |
| curve_4knot_Y4 | float | "1.000000" |  /  |   |

### Diagnostic.register_sound_area

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### Diagnostic.test_mixgraph_output

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### Diagnostic.test_sound_area

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### Diagnostic.test_threshold_logic

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### Diagnostic.test_wait_time

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### Diagnostic.test_wait_time_test

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### base_event_multiple_vsnd_files

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files_1 | vsnd | "sounds/common/null.vsnd" |  /  |   |
| vsnd_files_2 | vsnd | "sounds/common/null.vsnd" |  /  |   |
| vsnd_files_3 | vsnd | "sounds/common/null.vsnd" |  /  |   |
| vsnd_files_4 | vsnd | "sounds/common/null.vsnd" |  /  |   |

### beatpattern_4x4

来源：core/soundstacks/soundstacks_beat_pattern.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| track_01 | string | "main" |  /  |   |
| pattern_01 | string | "branch_sync" |  /  |   |
| pattern_01_play_event_type | enum | "invalid" |  /  |  beatpattern_pattern_start.play_event_type |
| pattern_01_queue_event_type | enum | "invalid" |  /  |  beatpattern_pattern_start.queue_event_type |
| pattern_01_play_mult | float | "1.0" |  /  |   |
| pattern_01_queue_mult | float | "1.0" |  /  |   |
| track_02 | string | "main" |  /  |   |
| pattern_02 | string | "transition_short_sync" |  /  |   |
| pattern_02_play_event_type | enum | "invalid" |  /  |  beatpattern_pattern_start.play_event_type |
| pattern_02_queue_event_type | enum | "invalid" |  /  |  beatpattern_pattern_start.queue_event_type |
| pattern_02_play_mult | float | "1.0" |  /  |   |
| pattern_02_queue_mult | float | "1.0" |  /  |   |
| play_pattern_02 | bool | "false" |  /  |   |

### child_stack

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：parent_stack, parent_stack_2。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value3 | float | "3.0" |  /  |   |
| import_parent_field | public_opvar | "parent_stack" |  /  |   |
| import_parent_field_2 | public_opvar | "parent_stack_2" |  /  |   |
| value4 | float | "4.0" |  /  |   |

### container_arg_test

来源：core/soundstacks/soundstacks_containers_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| memory_type | float | "1.0" |  /  |   |
| index_override | float | -1.0 |  /  |   |

### container_env_test

来源：core/soundstacks/soundstacks_containers_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| vsnd_env | vsnd | "sounds/common/null.vsnd" |  /  |   |
| memory_type | float | "0" |  /  |   |

### container_oneshot_test

来源：core/soundstacks/soundstacks_containers_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| memory_type | float | "0" |  /  |   |

### core_beatpattern_start_pattern

来源：core/soundstacks/soundstacks_beat_pattern.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| track_01 | string | "main" |  /  |   |
| pattern_01 | string | "branch_sync" |  /  |   |
| pattern_01_play_event_type | enum | "invalid" |  /  |  beatpattern_pattern_start.play_event_type |
| pattern_01_queue_event_type | enum | "invalid" |  /  |  beatpattern_pattern_start.queue_event_type |
| pattern_01_play_mult | float | "1.0" |  /  |   |
| pattern_01_queue_mult | float | "1.0" |  /  |   |

### core_distance_limiter

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| distance | float | "0.000000" |  /  |   |
| distance_max | float | "5000.000000" |  /  |   |

### core_doppler

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| doppler_scalar | float | "1.000000" |  /  |   |
| enable_spew | float | "0.000000" |  /  |   |
| player_pos | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| sound_pos | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| output_doppler_amount | float | "1.000000" |  /  |   |

### core_empty

来源：core/soundstacks/soundstacks_core.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### core_global_stack

来源：core/soundstacks/soundstacks_core.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### core_import_test_import

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value8 | float | "8.0" |  /  |   |
| snd_event_param | sndevt | "" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| core_import_test_parent | public_opvar | "core_import_test_parent1" |  /  |   |
| core_import_test_parent2 | public_opvar | "core_import_test_parent2" |  /  |   |

### core_import_test_import_recursive

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value9 | float | "8.0" |  /  |   |
| core_import_test_import | public_opvar | "core_import_test_import" |  /  |   |

### core_import_test_import_recursive_scope

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value9 | float | "8.0" |  /  |   |
| core_import_test_import_scope | public_opvar | "core_import_test_import_scope" |  /  |   |

### core_import_test_import_scope

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：core_import_test_parent1。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value8 | float | "8.0" |  /  |   |
| snd_event_param | sndevt | "" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| core_import_test_parent | public_opvar | "core_import_test_parent1" |  /  |   |
| core_import_test_parent2 | public_opvar | "core_import_test_parent2" |  /  |   |

### core_import_test_parent1

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value1 | float | "1.0" |  /  |   |
| value2 | float | "2.0" |  /  |   |

### core_import_test_parent2

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value3 | float | "3.0" |  /  |   |
| value4 | float | "4.0" |  /  |   |

### core_import_test_parent3

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value5 | float | "5.0" |  /  |   |
| value6 | float | "6.0" |  /  |   |

### core_max_multiple

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| input1 | float | "1.000000" |  /  |   |
| input2 | float | "1.000000" |  /  |   |
| input3 | float | "1.000000" |  /  |   |
| input4 | float | "1.000000" |  /  |   |
| input5 | float | "1.000000" |  /  |   |
| input6 | float | "1.000000" |  /  |   |
| output | float | "1.000000" |  /  |   |

### core_null_timed

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| time | float | "0.100000" |  /  |   |

### core_pause_soundevent

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| pause | bool | "true" |  /  |   |
| event_guid | int | "0" |  /  |   |
| event_type | float | "-1.000000" |  /  |   |
| entity | float | "0.000000" |  /  |   |
| event_name | string | "" |  /  |   |
| match_substring | bool | "false" |  /  |   |
| invert_match | bool | "false" |  /  |   |

### core_preload_soundevents

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| priority | float | "10" |  /  |   |
| soundevents | string | "" |  /  |   |

### core_sampler_base

来源：core/soundstacks/soundstacks_core.vsndstck_c。

导入栈：core_distance_limiter。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.000000" |  /  |   |
| attack | float | "0.000000" |  /  |   |
| release | float | "0.000000" |  /  |   |
| volume_rand_range | float | "0.000000" |  /  |   |
| volume_noise_range | float | "0.000000" |  /  |   |
| volume_noise_freq | float | "0.000000" |  /  |   |
| mixgroup | string | "music" |  /  |   |
| volume_atten | float | "1.000000" |  /  |   |
| volume_game_atten | float | "1.000000" |  /  |   |
| falloff_dist_mult | float | "1.000000" |  /  |   |
| falloff_min_dist | float | "84.000000" |  /  |   |
| falloff_max_dist | float | "3000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| pitch_rand_min | float | "0.000000" |  /  |   |
| pitch_rand_max | float | "0.000000" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| event_type | float | "0.000000" |  /  |   |
| position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| play_local_to_player | bool | "false" |  /  |   |
| spread_min_dist | float | "48" |  /  |   |
| spread_max_dist | float | "192" |  /  |   |
| reverb_send | float | "1" |  /  |   |
| occlusion_radius | float | "96" |  /  |   |
| occlusion_scale | float | "1.000000" |  /  |   |
| distance_limiter_on | float | "1.000000" |  /  |   |
| limiter_on | float | "0.000000" |  /  |   |
| limiter_max | float | "16.000000" |  /  |   |
| limiter_match_type | float | "0" |  /  |   |
| limiter_match_entity | float | "0" |  /  |   |
| limiter_match_this | float | "1" |  /  |   |
| block_on | float | "0" |  /  |   |
| block_event_name | string | "" |  /  |   |
| sample | vsnd | ["sounds/common/null.vsnd"] |  /  |   |
| use_layer2 | bool | "false" |  /  |   |
| layer2 | string | "NULL" |  /  |   |

### core_sampler_event

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| sampler | string | "kalimba_attack" |  /  |   |
| event | float | "1.000000" |  /  |   |
| data1 | float | "1.000000" |  /  |   |
| data2 | float | "1.000000" |  /  |   |

### core_set_playerdsp

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| dsp_preset | string | "core.null" |  /  |   |
| mix | float | "0" |  /  |   |
| enable | float | "1" |  /  |   |

### core_setter_AHR_base

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value | float | "0.000000" |  /  |   |
| start_value | float | "0.000000" |  /  |   |
| hold_time | float | "0.000000" |  /  |   |
| fade_in | float | "0.000000" |  /  |   |
| fade_out | float | "0.000000" |  /  |   |
| mult_value | bool | "false" |  /  |   |
| stop_after_hold | bool | "true" |  /  |   |

### core_setter_AHR_game_volume

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_AHR_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | "core_setter_AHR_base" | | |

### core_setter_AHR_mixgraph_input

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_AHR_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | "core_setter_AHR_base" | | |
| mixgraph_input | string | "" |  /  |   |

### core_setter_AHR_mixlayer_amount

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_AHR_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | "core_setter_AHR_base" | | |
| mixlayer_name | string | "core_global_opvars" |  /  |   |

### core_setter_AHR_stack_opvar

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_AHR_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | "core_setter_AHR_base" | | |
| stack_name | string | "core_global_opvars" |  /  |   |
| operator_name | string | "opvars" |  /  |   |
| opvar_name | string | "test" |  /  |   |

### core_setter_curve_base

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value_curve | float6 | ["[ 0.00, 0.0, 1.083, 1.083, 2.0, 3.0 ]","[ 1.0, 1.0, 0.227125, 0.227125, 2.0, 3.0 ]"] |  / advanced |   |
| time | float | "0" |  /  |   |
| stop_value | float | "0" |  /  |   |

### core_setter_curve_mixgraph_input

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_curve_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | "core_setter_curve_base" | | |
| mixgraph_input | string | "" |  /  |   |

### core_setter_curve_mixlayer_amount

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_curve_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | "core_setter_curve_base" | | |
| mixlayer_name | string | "" |  /  |   |

### core_setter_curve_mixlayer_trigger_amount

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_curve_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | "core_setter_curve_base" | | |
| mixer_mixgroup | mixgroup | "All" |  /  |   |

### core_setter_curve_stack_opvar

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_curve_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | "core_setter_curve_base" | | |
| stack_name | string | "core_global_opvars" |  /  |   |
| operator_name | string | "opvars" |  /  |   |
| opvar_name | string | "test" |  /  |   |

### core_setter_mixgraph_input

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| mixgraph_input | string | "" |  /  |   |
| value | float | "0" |  /  |   |

### core_setter_mixlayer_amount

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| mixlayer_name | string | "" |  /  |   |
| value | float | "0" |  /  |   |

### core_setter_ramp_to_value_base

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start_value | float | "0" |  /  |   |
| end_value | float | "1" |  /  |   |
| ramp_time | float | "0.000000" |  /  |   |
| stack_name | string | "core_global_opvars" |  /  |   |
| operator_name | string | "opvars" |  /  |   |
| opvar_name | string | "test" |  /  |   |

### core_setter_ramp_to_value_mixgraph_input

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_mixgraph_input, core_setter_ramp_to_value_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | ["core_setter_ramp_to_value_base","core_setter_mixgraph_input"] | | |

### core_setter_ramp_to_value_mixlayer_amount

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_mixlayer_amount, core_setter_ramp_to_value_base。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | ["core_setter_ramp_to_value_base","core_setter_mixlayer_amount"] | | |

### core_setter_ramp_to_value_stack_opvar

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

导入栈：core_setter_ramp_to_value_base, core_setter_stack_opvar。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | ["core_setter_ramp_to_value_base","core_setter_stack_opvar"] | | |

### core_setter_stack_opvar

来源：core/soundstacks/soundstacks_core_setters.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value | float | "0" |  /  |   |
| stack_name | string | "core_global_opvars" |  /  |   |
| operator_name | string | "opvars" |  /  |   |
| opvar_name | string | "test" |  /  |   |

### core_simple_2d

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | ["sounds/common/null.vsnd"] |  /  |   |
| memory_type | float | "0" |  /  |   |

### core_simple_3d

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| distance_min | float | "24" |  /  |   |
| distance_max | float | "360" |  /  |   |
| position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| vsnd_files | vsnd | ["sounds/common/null.vsnd"] |  /  |   |
| delay | float | "0.000000" |  /  |   |
| memory_type | float | "0" |  /  |   |

### core_soundevent_blocker

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| on | float | "1.000000" |  /  |   |
| match_soundevent | string | "NONE" |  /  |   |
| match_substring | float | "0" |  /  |   |
| match_event_type | float | "-1" |  /  |   |
| min_time | float | "0.100000" |  /  |   |
| max_time | float | "0.100000" |  /  |   |

### core_start_oneshot

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start | float | "1.000000" |  /  |   |
| volume_min | float | "0.900000" |  /  |   |
| volume_max | float | "1.000000" |  /  |   |
| pitch_min | float | "0.950000" |  /  |   |
| pitch_max | float | "1.050000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| memory_type | float | "0" |  /  |   |

### core_start_simple_oneshot

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start | float | "1.000000" |  /  |   |
| volume | float | "1.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| test_print | float | "1.111000" |  /  |   |
| test_print2 | float | "2.222000" |  /  |   |
| test_print3 | float | "3.333000" |  /  |   |
| test_print4 | float | "4.444000" |  /  |   |
| memory_type | float | "0" |  /  |   |

### core_stop_all_soundevents

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| wait_time | float | "0" |  /  |   |
| immediate | float | "0" |  /  |   |
| voice_layer | enum | "game" |  /  |  vmix_voice_start.voice_layer |
| exclude_group | string | "" |  /  |   |

### core_stop_at_time

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| time | float | "0.000000" |  /  |   |

### core_stop_soundevents

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| event_type | float | "-1.000000" |  /  |   |
| entity | float | "0.000000" |  /  |   |
| event_name | string | "" |  /  |   |
| match_substring | bool | "false" |  /  |   |
| invert_match | bool | "false" |  /  |   |

### core_test_sound

来源：core/soundstacks/soundstacks_core.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### core_valve_default

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start | float | "1.000000" |  /  |   |
| volume | float | "1.000000" |  /  |   |
| volume_rand_min | float | "0.000000" |  /  |   |
| volume_rand_max | float | "0.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| pitch_rand_min | float | "-0.050000" |  /  |   |
| pitch_rand_max | float | "0.050000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| memory_type | float | "0" |  /  |   |

### core_voip

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| memory_type | float | "0" |  /  |   |

### core_volume_limiter

来源：core/soundstacks/soundstacks_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume_input | float | "0.000000" |  /  |   |
| volume_block_min_threshold | float | "-1.000000" |  /  |   |

### curve_test_01

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| curve_standard | float6 | ["[ 0.0, 1.0, 0.0, 0.0, 1.0, 1.0 ]","[ 1.0, 1.0, 1.0, 1.0, 0.0, 1.0 ]"] | Filter / advanced |   |
| curve_array | float12 | ["[ 0.0, 0.0, 0.33, 0.0, 0.5, 0, 0.66, 0, 0.75, 0, 1.0, 0.0 ]","[ 0.0, 0.5, 0.33, 0.5, 0.5, 0.5, 0.66, 0.5, 0.75, 0.5, 1.0, 0.5 ]"] |  / advanced |   |

### curve_test_multi_import

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：curve_test_01。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_curve_test_01_01 | public_opvar | "curve_test_01" |  /  |   |
| import_curve_test_01_02 | public_opvar | "curve_test_01" |  /  |   |

### dave_sb_bang

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### dave_test_floatness

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| float3_1 | float3 | "[0.0, 1.0, 2.0]" |  /  |   |
| float_1 | float | "25.000000" |  /  |   |
| float_2 | float | "26.000000" |  /  |   |
| float_3 | float | "27.000000" |  /  |   |

### dave_test_random_pos

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| position | float3 | "[0.0, 922.0, 159.0]" |  /  |   |
| radius_min | float | "50" |  /  |   |
| radius_max | float | "150" |  /  |   |

### dave_test_sb

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_scalebang。本表只列当前 public 声明，导入栈请另查对应章节。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### dave_test_soundscapes

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_play_looping, soundscape_play_random。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| soundscape_scalar | float | "1.000000" |  /  |   |
| rand01_volume_max | float | "1.000000" |  /  |   |
| rand01_volume_min | float | "0.500000" |  /  |   |
| rand01_delay_min | float | "5.000000" |  /  |   |
| rand01_delay_max | float | "10.000000" |  /  |   |
| rand01_position_random | bool | "1" |  /  |   |
| rand01_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| rand01_position_random_min_radius | float | "10.000000" |  /  |   |
| rand01_position_random_max_radius | float | "1000.000000" |  /  |   |
| rand01_entry_name | string | "foo.bar" |  /  |   |
| rand02_delay_min | float | "5.000000" |  /  |   |
| rand02_delay_max | float | "10.000000" |  /  |   |
| rand02_position_random | bool | "1" |  /  |   |
| rand02_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| rand02_position_random_min_radius | float | "10.000000" |  /  |   |
| rand02_position_random_max_radius | float | "1000.000000" |  /  |   |
| rand02_entry_name | string | "foo.bar" |  /  |   |
| lp_volume_max | float | "1.000000" |  /  |   |
| lp_volume_min | float | "1.000000" |  /  |   |
| lp_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| lp_soundevent_name | string | "foo.bar" |  /  |   |
| lp_distance_max | float | "-1.000000" |  /  |   |

### dave_timer_test

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：util_timer。本表只列当前 public 声明，导入栈请另查对应章节。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### dave_timer_test_reset

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### dave_timer_test_run

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### dave_timer_test_stop

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### dave_timer_test_stop_reset

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### diagnostic.animate_float3_gallery

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| period | float | "6.000000" |  /  |   |
| revolutions | float | "5.000000" |  /  |   |
| sphere_radius | float | "7.000000" |  /  |   |
| bezier_control_offset | float3 | "[0.0, -140.0, 0.0]" |  /  |   |

### diagnostic.self_exciting_column

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| cell_offset | float3 | "[0.0, 0.0, 64.0]" |  /  |   |
| cluster_period | float | "15.000000" |  /  |   |
| excite | float | "1.500000" |  /  |   |
| tau | float | "0.500000" |  /  |   |
| refractory | float | "0.000000" |  /  |   |
| mode | enum | "scheduled" |  /  |  math_random_self_exciting.mode |
| start_mode | enum | "wait_gap" |  /  |  math_random_self_exciting.start_mode |
| tension_max | float | "3.000000" |  /  |   |
| flash_rgb | float3 | "[255, 140, 0]" |  /  |   |
| label | string | "column" |  /  |   |
| flash_duration | float | "0.250000" |  /  |   |
| sphere_radius | float | "12.000000" |  /  |   |
| spawn_radius_min | float | "40.000000" |  /  |   |
| spawn_radius_max | float | "140.000000" |  /  |   |

### diagnostic.self_exciting_gallery

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：core_start_oneshot, diagnostic.self_exciting_column。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| beep_column | float | "4.000000" |  /  |   |
| beep_vsnd | vsnd | "sounds/diagnostics/sin_1k_0p005_oneshot.vsnd" |  /  |   |

### diagnostic.start_n_soundevents

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| soundevent_number | float | "100.000000" |  /  |   |

### diagnostic.timed_beeper

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：core_start_oneshot。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| interval | float | "1.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/diagnostics/beep.vsnd" |  /  |   |

### diagnostic.timed_silence

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| interval | float | "1.000000" |  /  |   |

### diagnostic.timed_soundevent

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| interval | float | "1.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| soundevent | string | "NULLSOUNDEVENT" |  /  |   |
| count | float | "0.000000" |  /  |   |

### diagnostic.usable_float_range

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| print_interval | float | "1.000000" |  /  |   |
| source_min | float | "0.000000" |  /  |   |
| source_max | float | "1.000000" |  /  |   |
| percentile_lower | float | "5.000000" |  /  |   |
| percentile_upper | float | "95.000000" |  /  |   |

### diagnostic_globals

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### diagnostics_arrays

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| zero_length | float | [] |  /  |   |
| event_vsnds | vsnd | ["sounds/weapons/bullet_impacts/wpn_bullet_impact_dry_zombie_01.vsnd","sounds/weapons/bullet_impacts/wpn_bullet_impact_dry_zombie_02.vsnd","sounds/weapons/bullet_impacts/wpn_bullet_impact_dry_zombie_03.vsnd"] |  /  |   |
| wave_type | enum | ["mytri","mysqr","none"] |  /  |   |
| event_ints | float | ["0","1","2","3"] |  /  |   |
| event_bools | bool | ["true","false","true","false"] |  /  |   |
| event_floats | float | ["0","1","2","3"] |  /  |   |
| event_float2s | float2 | ["[ 0.0, 0.0 ]","[ 1.0, 1.0 ]","[ 2.0, 2.0 ]","[ 3.0, 3.0 ]"] |  /  |   |
| event_float3s | float3 | ["[ 1.0, 1.0, 1.0 ]","[ 2.0, 2.0, 2.0 ]","[ 3.0, 3.0, 3.0 ]","[ 4.0, 4.0, 4.0 ]"] |  /  |   |
| event_float4s | float4 | ["[ 1.0, 1.0, 1.0, 1.0 ]","[ 2.0, 2.0, 2.0, 2.0 ]","[ 3.0, 3.0, 3.0, 3.0 ]","[ 4.0, 4.0, 4.0, 4.0 ]"] |  /  |   |
| event_float6s | float6 | ["[ 1.0, 1.0, 1.0, 1.0, 1.0, 1.0 ]","[ 2.0, 2.0, 2.0, 2.0, 2.0, 2.0 ]","[ 3.0, 3.0, 3.0, 3.0, 3.0, 3.0 ]","[ 4.0, 4.0, 4.0, 4.0, 4.0, 4.0 ]"] |  /  |   |
| event_speakers | float_max_speakers | ["[ 1.0, 1.0, 1.0, 1.0, 1.0, 1.0 ]","[ 2.0, 2.0, 2.0, 2.0, 2.0, 2.0 ]","[ 3.0, 3.0, 3.0, 3.0, 3.0, 3.0 ]","[ 4.0, 4.0, 4.0, 4.0, 4.0, 4.0 ]"] |  /  |   |
| array_vsnds | vsnd | ["sounds/weapons/bullet_impacts/wpn_bullet_impact_dry_zombie_01.vsnd","sounds/weapons/bullet_impacts/wpn_bullet_impact_dry_zombie_02.vsnd","sounds/weapons/bullet_impacts/wpn_bullet_impact_dry_zombie_03.vsnd"] |  /  |   |

### diagnostics_vsnd_lists

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### example_start_oneshot_import_test

来源：core/soundstacks/soundstacks_examples.vsndstck_c。

导入栈：core_start_oneshot。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start | float | "1.000000" |  /  |   |
| volume_min | float | "0.900000" |  /  |   |
| volume_max | float | "1.000000" |  /  |   |
| pitch_min | float | "0.500000" |  /  |   |
| pitch_max | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |

### example_timetriggered_simple_oneshot

来源：core/soundstacks/soundstacks_examples.vsndstck_c。

导入栈：core_start_simple_oneshot。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| time | float | "0.000000" |  /  |   |
| start_time | float | "0.000000" |  /  |   |
| unstopped | float | "1.000000" |  /  |   |
| volume | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |

### group_soundevent_cluster_default_3d_test

来源：core/soundstacks/soundstacks_core_test.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### inner_1

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| opvars | string | "" | Opvars / normal |   |
| opvars_use_namespace | bool | "false" | Opvars / advanced |   |
| public_namespace | string | "" |  /  |   |

### inner_2

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：inner_1。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_opvars | string | "" | Opvars / normal |   |
| public_namespace | string | "" | Opvars / normal |   |
| opvars_use_namespace | bool | "false" | Opvars / advanced |   |

### no_scope_inner

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| global_opvar_names | string | "min_vol_inverse_val" | Opvars / normal |   |
| opvars_use_namespace | bool | "true" |  /  |   |

### no_scope_main

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：no_scope_outer。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| no_scope_outer | public_opvar | "no_scope_outer" |  /  |   |

### no_scope_outer

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：no_scope_inner。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| no_scope_inner | public_opvar | "no_scope_inner" |  /  |   |

### outer

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：inner_2。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_opvars | 未声明 | ["inner_2"] | | |
| test_opvars | string | "" | Opvars / normal |   |

### outer_multi

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：inner_2。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| inner_2_1 | public_opvar | "inner_2" |  /  |   |
| inner_2_2 | public_opvar | "inner_2" |  /  |   |

### parent_stack

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value1 | float | "1.0" |  /  |   |

### parent_stack_2

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value2 | float | "2.0" |  /  |   |

### soundscape_2d_sound

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start | float | "1.000000" |  /  |   |
| mixgroup | string | "EMPTYERROR" |  /  |   |
| volume_min | float | "1.000000" |  /  |   |
| volume_max | float | "1.000000" |  /  |   |
| pitch_min | float | "1.000000" |  /  |   |
| pitch_max | float | "1.000000" |  /  |   |
| event_type | float | "0.000000" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| seed | float | "-1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| memory_type | float | "0" |  /  |   |
| volume_slider | float | "1.000000" |  /  |   |

### soundscape_2rand_1loop

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_play_looping, soundscape_play_random。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| soundscape_scalar | float | "1.000000" |  /  |   |
| loop_01_pitch_max | float | "1.000000" |  /  |   |
| loop_01_pitch_min | float | "0.900000" |  /  |   |
| loop_01_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| loop_01_soundevent_name | string | "foo.bar" |  /  |   |
| loop_01_soundlevel | float | "75.000000" |  /  |   |
| loop_01_volume_max | float | "1.000000" |  /  |   |
| loop_01_volume_min | float | "1.000000" |  /  |   |
| loop_01_use_vol_opvar | bool | "1.000000" |  /  |   |
| loop_01_remap_vol_opvar_ymin | float | "0.000000" |  /  |   |
| loop_01_remap_vol_opvar_ymax | float | "1.000000" |  /  |   |
| loop_01_remap_vol_opvar_xmin | float | "0.000000" |  /  |   |
| loop_01_remap_vol_opvar_xmax | float | "1.000000" |  /  |   |
| loop_01_vol_opvar | string | "foo" |  /  |   |
| loop_01_remap_vol_opvar_x1 | float | "1.000000" |  /  |   |
| loop_01_remap_vol_opvar_y1 | float | "1.000000" |  /  |   |
| loop_01_remap_vol_opvar_x2 | float | "1.000000" |  /  |   |
| loop_01_remap_vol_opvar_y2 | float | "1.000000" |  /  |   |
| loop_01_remap_vol_opvar_x3 | float | "1.000000" |  /  |   |
| loop_01_remap_vol_opvar_y3 | float | "1.000000" |  /  |   |
| loop_01_remap_vol_opvar_x4 | float | "1.000000" |  /  |   |
| loop_01_remap_vol_opvar_y4 | float | "1.000000" |  /  |   |
| random_01_delay_max | float | "60.000000" |  /  |   |
| random_01_delay_min | float | "0.010000" |  /  |   |
| random_01_pitch_max | float | "1.000000" |  /  |   |
| random_01_pitch_min | float | "0.900000" |  /  |   |
| random_01_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| random_01_position_random | bool | "1.000000" |  /  |   |
| random_01_position_random_max_radius | float | "1000.000000" |  /  |   |
| random_01_position_random_min_radius | float | "100.000000" |  /  |   |
| random_01_soundevent_name | string | "foo.bar" |  /  |   |
| random_01_volume_max | float | "1.000000" |  /  |   |
| random_01_volume_min | float | "1.000000" |  /  |   |
| random_01_use_pct_opvar | bool | "1.000000" |  /  |   |
| random_01_remap_pct_opvar_ymin | float | "0.000000" |  /  |   |
| random_01_remap_pct_opvar_ymax | float | "1.000000" |  /  |   |
| random_01_remap_pct_opvar_xmin | float | "0.000000" |  /  |   |
| random_01_remap_pct_opvar_xmax | float | "1.000000" |  /  |   |
| random_01_pct_opvar | string | "foo" |  /  |   |
| random_01_remap_pct_opvar_x1 | float | "1.000000" |  /  |   |
| random_01_remap_pct_opvar_y1 | float | "1.000000" |  /  |   |
| random_01_remap_pct_opvar_x2 | float | "1.000000" |  /  |   |
| random_01_remap_pct_opvar_y2 | float | "1.000000" |  /  |   |
| random_01_remap_pct_opvar_x3 | float | "1.000000" |  /  |   |
| random_01_remap_pct_opvar_y3 | float | "1.000000" |  /  |   |
| random_01_remap_pct_opvar_x4 | float | "1.000000" |  /  |   |
| random_01_remap_pct_opvar_y4 | float | "1.000000" |  /  |   |
| random_01_remap_vol_opvar_ymin | float | "0.000000" |  /  |   |
| random_01_remap_vol_opvar_ymax | float | "1.000000" |  /  |   |
| random_01_remap_vol_opvar_xmin | float | "0.000000" |  /  |   |
| random_01_remap_vol_opvar_xmax | float | "1.000000" |  /  |   |
| random_01_use_vol_opvar | bool | "1.000000" |  /  |   |
| random_01_vol_opvar | string | "foo" |  /  |   |
| random_01_remap_vol_opvar_x1 | float | "1.000000" |  /  |   |
| random_01_remap_vol_opvar_y1 | float | "1.000000" |  /  |   |
| random_01_remap_vol_opvar_x2 | float | "1.000000" |  /  |   |
| random_01_remap_vol_opvar_y2 | float | "1.000000" |  /  |   |
| random_01_remap_vol_opvar_x3 | float | "1.000000" |  /  |   |
| random_01_remap_vol_opvar_y3 | float | "1.000000" |  /  |   |
| random_01_remap_vol_opvar_x4 | float | "1.000000" |  /  |   |
| random_01_remap_vol_opvar_y4 | float | "1.000000" |  /  |   |
| random_02_delay_max | float | "60.000000" |  /  |   |
| random_02_delay_min | float | "0.010000" |  /  |   |
| random_02_pitch_max | float | "1.000000" |  /  |   |
| random_02_pitch_min | float | "0.900000" |  /  |   |
| random_02_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| random_02_position_random | bool | "1.000000" |  /  |   |
| random_02_position_random_max_radius | float | "1000.000000" |  /  |   |
| random_02_position_random_min_radius | float | "100.000000" |  /  |   |
| random_02_soundevent_name | string | "foo.bar" |  /  |   |
| random_02_volume_max | float | "1.000000" |  /  |   |
| random_02_volume_min | float | "1.000000" |  /  |   |
| random_02_use_pct_opvar | bool | "1.000000" |  /  |   |
| random_02_remap_pct_opvar_ymin | float | "0.000000" |  /  |   |
| random_02_remap_pct_opvar_ymax | float | "1.000000" |  /  |   |
| random_02_remap_pct_opvar_xmin | float | "0.000000" |  /  |   |
| random_02_remap_pct_opvar_xmax | float | "1.000000" |  /  |   |
| random_02_pct_opvar | string | "foo" |  /  |   |
| random_02_remap_pct_opvar_x1 | float | "1.000000" |  /  |   |
| random_02_remap_pct_opvar_y1 | float | "1.000000" |  /  |   |
| random_02_remap_pct_opvar_x2 | float | "1.000000" |  /  |   |
| random_02_remap_pct_opvar_y2 | float | "1.000000" |  /  |   |
| random_02_remap_pct_opvar_x3 | float | "1.000000" |  /  |   |
| random_02_remap_pct_opvar_y3 | float | "1.000000" |  /  |   |
| random_02_remap_pct_opvar_x4 | float | "1.000000" |  /  |   |
| random_02_remap_pct_opvar_y4 | float | "1.000000" |  /  |   |
| random_02_remap_vol_opvar_ymin | float | "0.000000" |  /  |   |
| random_02_remap_vol_opvar_ymax | float | "1.000000" |  /  |   |
| random_02_remap_vol_opvar_xmin | float | "0.000000" |  /  |   |
| random_02_remap_vol_opvar_xmax | float | "1.000000" |  /  |   |
| random_02_use_vol_opvar | bool | "1.000000" |  /  |   |
| random_02_vol_opvar | string | "foo" |  /  |   |
| random_02_remap_vol_opvar_x1 | float | "1.000000" |  /  |   |
| random_02_remap_vol_opvar_y1 | float | "1.000000" |  /  |   |
| random_02_remap_vol_opvar_x2 | float | "1.000000" |  /  |   |
| random_02_remap_vol_opvar_y2 | float | "1.000000" |  /  |   |
| random_02_remap_vol_opvar_x3 | float | "1.000000" |  /  |   |
| random_02_remap_vol_opvar_y3 | float | "1.000000" |  /  |   |
| random_02_remap_vol_opvar_x4 | float | "1.000000" |  /  |   |
| random_02_remap_vol_opvar_y4 | float | "1.000000" |  /  |   |

### soundscape_3d_sound

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：core_distance_limiter。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| mixgroup | string | "EMPTYERROR" |  /  |   |
| volume_min | float | "0.900000" |  /  |   |
| volume_max | float | "1.000000" |  /  |   |
| pitch_min | float | "0.950000" |  /  |   |
| pitch_max | float | "1.050000" |  /  |   |
| level_min | float | "65" |  /  |   |
| level_max | float | "75" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| event_type | float | "0.000000" |  /  |   |
| distance_max | float | "-1.000000" |  /  |   |
| position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| memory_type | float | "0" |  /  |   |
| volume_slider | float | "1.000000" |  /  |   |

### soundscape_globals

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### soundscape_looping_sound_2D

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_2d_sound。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |

### soundscape_looping_sound_3D

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_3d_sound。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |

### soundscape_opvar_percentage

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| input_execute_float | float | "1.000000" |  /  |   |
| opvar_name | string | "foo" |  /  |   |
| remap_opvar_x1 | float | "1.000000" |  /  |   |
| remap_opvar_y1 | float | "1.000000" |  /  |   |
| remap_opvar_x2 | float | "1.000000" |  /  |   |
| remap_opvar_y2 | float | "1.000000" |  /  |   |
| remap_opvar_x3 | float | "1.000000" |  /  |   |
| remap_opvar_y3 | float | "1.000000" |  /  |   |
| remap_opvar_x4 | float | "1.000000" |  /  |   |
| remap_opvar_y4 | float | "1.000000" |  /  |   |
| filter_speed | float | "0.060000" |  /  |   |
| output_float | float | "1.000000" |  /  |   |

### soundscape_opvar_switch

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| input_float | float | "1.000000" |  /  |   |
| opvar_name | string | "" |  /  |   |
| remap_opvar_x1 | float | "1.000000" |  /  |   |
| remap_opvar_y1 | float | "1.000000" |  /  |   |
| remap_opvar_x2 | float | "1.000000" |  /  |   |
| remap_opvar_y2 | float | "1.000000" |  /  |   |
| remap_opvar_x3 | float | "1.000000" |  /  |   |
| remap_opvar_y3 | float | "1.000000" |  /  |   |
| remap_opvar_x4 | float | "1.000000" |  /  |   |
| remap_opvar_y4 | float | "1.000000" |  /  |   |
| filter_speed | float | "0.060000" |  /  |   |
| output_float | float | "1.000000" |  /  |   |

### soundscape_play_burst

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：util_timer。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| burst_length | float | "1.000000" |  /  |   |
| delay_time_low | float | "1.000000" |  /  |   |
| delay_time_high | float | "1.000000" |  /  |   |
| soundevent_name | string | "foo.bar" |  /  |   |
| position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| position_random | bool | "1" |  /  |   |
| position_random_max_radius | float | "1000.000000" |  /  |   |
| position_random_min_radius | float | "10.000000" |  /  |   |
| pitch_max | float | "1.000000" |  /  |   |
| pitch_min | float | "1.000000" |  /  |   |
| soundscape_scalar | float | "1.000000" |  /  |   |

### soundscape_play_looping

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_opvar_switch。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume_max | float | "1.000000" |  /  |   |
| volume_min | float | "1.000000" |  /  |   |
| pitch_max | float | "1.000000" |  /  |   |
| pitch_min | float | "1.000000" |  /  |   |
| position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| soundevent_name | string | "foo.bar" |  /  |   |
| soundscape_scalar | float | "1.000000" |  /  |   |
| soundlevel | float | "75" |  /  |   |
| vol_opvar | string | "foo" |  /  |   |
| remap_vol_opvar_x1 | float | "1.000000" |  /  |   |
| remap_vol_opvar_y1 | float | "1.000000" |  /  |   |
| remap_vol_opvar_x2 | float | "1.000000" |  /  |   |
| remap_vol_opvar_y2 | float | "1.000000" |  /  |   |
| remap_vol_opvar_x3 | float | "1.000000" |  /  |   |
| remap_vol_opvar_y3 | float | "1.000000" |  /  |   |
| remap_vol_opvar_x4 | float | "1.000000" |  /  |   |
| remap_vol_opvar_y4 | float | "1.000000" |  /  |   |
| distance_max | float | "-1.000" |  /  |   |

### soundscape_play_random

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_opvar_percentage, soundscape_opvar_switch。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume_max | float | "1.000000" |  /  |   |
| volume_min | float | "0.500000" |  /  |   |
| pitch_max | float | "1.000000" |  /  |   |
| pitch_min | float | "0.500000" |  /  |   |
| delay_max | float | "10.000000" |  /  |   |
| delay_min | float | "5.000000" |  /  |   |
| position_random | float | "1.000000" |  /  |   |
| position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| position_random_max_radius | float | "1000.000000" |  /  |   |
| position_random_min_radius | float | "10.000000" |  /  |   |
| soundevent_name | string | "foo.bar" |  /  |   |
| soundscape_scalar | float | "1.000000" |  /  |   |
| random_seed | float | "-1.000000" |  /  |   |
| pct_opvar | string | "foo" |  /  |   |
| remap_pct_opvar_x1 | float | "1.000000" |  /  |   |
| remap_pct_opvar_y1 | float | "1.000000" |  /  |   |
| remap_pct_opvar_x2 | float | "1.000000" |  /  |   |
| remap_pct_opvar_y2 | float | "1.000000" |  /  |   |
| remap_pct_opvar_x3 | float | "1.000000" |  /  |   |
| remap_pct_opvar_y3 | float | "1.000000" |  /  |   |
| remap_pct_opvar_x4 | float | "1.000000" |  /  |   |
| remap_pct_opvar_y4 | float | "1.000000" |  /  |   |
| vol_opvar | string | "foo" |  /  |   |
| remap_vol_opvar_x1 | float | "1.000000" |  /  |   |
| remap_vol_opvar_y1 | float | "1.000000" |  /  |   |
| remap_vol_opvar_x2 | float | "1.000000" |  /  |   |
| remap_vol_opvar_y2 | float | "1.000000" |  /  |   |
| remap_vol_opvar_x3 | float | "1.000000" |  /  |   |
| remap_vol_opvar_y3 | float | "1.000000" |  /  |   |
| remap_vol_opvar_x4 | float | "1.000000" |  /  |   |
| remap_vol_opvar_y4 | float | "1.000000" |  /  |   |
| random_opvar | string | "foo" |  /  |   |

### soundscape_play_soundscape

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| soundscape_volume | float | "1.000000" |  /  |   |
| soundscape_scalar | float | "1.000000" |  /  |   |
| soundscape_name | string | "0" |  /  |   |

### soundscape_random_sound

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_3d_sound。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| level | float | "75" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |

### soundscape_scalebang

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：util_timer。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| opvar_name | string | "none" |  /  |   |
| delay_time | float | "10.000000" |  /  |   |
| ramp_time | float | "10.000000" |  /  |   |
| bang | float | "0.000000" |  /  |   |
| output_ramp | float | "0.000000" |  /  |   |

### soundscape_test_play_soundscape

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_play_soundscape。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| soundscape_name | string | "NONE" |  /  |   |
| soundscape_volume | float | "0.900000" |  /  |   |
| soundscape_scalar | float | "1.000000" |  /  |   |

### soundscape_test_weather

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

导入栈：soundscape_play_looping, soundscape_play_random。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| heavy_rain_lp_pitch_max | float | "1.000000" |  /  |   |
| heavy_rain_lp_pitch_min | float | "1.000000" |  /  |   |
| heavy_rain_lp_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| heavy_rain_lp_soundevent_name | string | "Soundscapes.loop_rain_heavy" |  /  |   |
| heavy_rain_lp_soundlevel | float | "70.000000" |  /  |   |
| heavy_rain_lp_volume_max | float | "1.000000" |  /  |   |
| heavy_rain_lp_volume_min | float | "1.000000" |  /  |   |
| light_rain_lp_pitch_max | float | "1.000000" |  /  |   |
| light_rain_lp_pitch_min | float | "1.000000" |  /  |   |
| light_rain_lp_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| light_rain_lp_soundevent_name | string | "Soundscapes.loop_rain_light" |  /  |   |
| light_rain_lp_soundlevel | float | "70.000000" |  /  |   |
| light_rain_lp_volume_max | float | "1.000000" |  /  |   |
| light_rain_lp_volume_min | float | "1.000000" |  /  |   |
| light_wind_lp_pitch_max | float | "1.000000" |  /  |   |
| light_wind_lp_pitch_min | float | "1.000000" |  /  |   |
| light_wind_lp_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| light_wind_lp_soundevent_name | string | "Soundscapes.loop_wind_light" |  /  |   |
| light_wind_lp_soundlevel | float | "75.000000" |  /  |   |
| light_wind_lp_volume_max | float | "0.900000" |  /  |   |
| light_wind_lp_volume_min | float | "0.900000" |  /  |   |
| med_wind_lp_pitch_max | float | "1.000000" |  /  |   |
| med_wind_lp_pitch_min | float | "1.000000" |  /  |   |
| med_wind_lp_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| med_wind_lp_soundevent_name | string | "Soundscapes.loop_wind_medium" |  /  |   |
| med_wind_lp_soundlevel | float | "75.000000" |  /  |   |
| med_wind_lp_volume_max | float | "0.850000" |  /  |   |
| med_wind_lp_volume_min | float | "0.850000" |  /  |   |
| thunder_far_delay_max | float | "60.000000" |  /  |   |
| thunder_far_delay_min | float | "30.000000" |  /  |   |
| thunder_far_pitch_max | float | "1.000000" |  /  |   |
| thunder_far_pitch_min | float | "0.900000" |  /  |   |
| thunder_far_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| thunder_far_position_random | float | "1.000000" |  /  |   |
| thunder_far_position_random_max_radius | float | "500" |  /  |   |
| thunder_far_position_random_min_radius | float | "10" |  /  |   |
| thunder_far_pct_opvar | string | "g_rain" |  /  |   |
| thunder_far_remap_pct_opvar_x1 | float | "0.000000" |  /  |   |
| thunder_far_remap_pct_opvar_x2 | float | "0.320000" |  /  |   |
| thunder_far_remap_pct_opvar_x3 | float | "0.750000" |  /  |   |
| thunder_far_remap_pct_opvar_x4 | float | "0.860000" |  /  |   |
| thunder_far_remap_pct_opvar_y1 | float | "0.000000" |  /  |   |
| thunder_far_remap_pct_opvar_y2 | float | "1.000000" |  /  |   |
| thunder_far_remap_pct_opvar_y3 | float | "0.600000" |  /  |   |
| thunder_far_remap_pct_opvar_y4 | float | "0.300000" |  /  |   |
| thunder_far_remap_vol_x1 | float | "0.000000" |  /  |   |
| thunder_far_remap_vol_x2 | float | "0.240000" |  /  |   |
| thunder_far_remap_vol_x3 | float | "0.630000" |  /  |   |
| thunder_far_remap_vol_x4 | float | "1.000000" |  /  |   |
| thunder_far_remap_vol_y1 | float | "0.680000" |  /  |   |
| thunder_far_remap_vol_y2 | float | "0.900000" |  /  |   |
| thunder_far_remap_vol_y3 | float | "1.000000" |  /  |   |
| thunder_far_remap_vol_y4 | float | "1.000000" |  /  |   |
| thunder_far_soundevent_name | string | "Soundscapes.thunder_far" |  /  |   |
| thunder_far_vol_opvar | string | "g_clouds" |  /  |   |
| thunder_far_volume_max | float | "1.000000" |  /  |   |
| thunder_far_volume_min | float | "0.700000" |  /  |   |
| thunder_near_delay_max | float | "45.000000" |  /  |   |
| thunder_near_delay_min | float | "30.000000" |  /  |   |
| thunder_near_pitch_max | float | "1.000000" |  /  |   |
| thunder_near_pitch_min | float | "0.900000" |  /  |   |
| thunder_near_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| thunder_near_position_random | float | "1.000000" |  /  |   |
| thunder_near_position_random_max_radius | float | "100.000000" |  /  |   |
| thunder_near_position_random_min_radius | float | "0.000000" |  /  |   |
| thunder_near_pct_opvar | string | "g_clouds" |  /  |   |
| thunder_near_remap_pct_opvar_x1 | float | "0.360000" |  /  |   |
| thunder_near_remap_pct_opvar_x2 | float | "0.460000" |  /  |   |
| thunder_near_remap_pct_opvar_x3 | float | "0.660000" |  /  |   |
| thunder_near_remap_pct_opvar_x4 | float | "1.000000" |  /  |   |
| thunder_near_remap_pct_opvar_y1 | float | "0.000000" |  /  |   |
| thunder_near_remap_pct_opvar_y2 | float | "0.590000" |  /  |   |
| thunder_near_remap_pct_opvar_y3 | float | "0.870000" |  /  |   |
| thunder_near_remap_pct_opvar_y4 | float | "1.000000" |  /  |   |
| thunder_near_remap_vol_x1 | float | "0.300000" |  /  |   |
| thunder_near_remap_vol_x2 | float | "0.520000" |  /  |   |
| thunder_near_remap_vol_x3 | float | "0.670000" |  /  |   |
| thunder_near_remap_vol_x4 | float | "1.000000" |  /  |   |
| thunder_near_remap_vol_y1 | float | "0.620000" |  /  |   |
| thunder_near_remap_vol_y2 | float | "0.860000" |  /  |   |
| thunder_near_remap_vol_y3 | float | "0.960000" |  /  |   |
| thunder_near_remap_vol_y4 | float | "1.000000" |  /  |   |
| thunder_near_soundevent_name | string | "Soundscapes.thunder_near" |  /  |   |
| thunder_near_vol_opvar | string | "g_rain" |  /  |   |
| thunder_near_volume_max | float | "1.000000" |  /  |   |
| thunder_near_volume_min | float | "0.650000" |  /  |   |

### src1_2d

来源：core/soundstacks/soundstacks_src1.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start | float | "1.000000" |  /  |   |
| mixgroup | string | "USEPATHMATCH" |  /  |   |
| volume | float | "1.000000" |  /  |   |
| volume_rand_min | float | "0.000000" |  /  |   |
| volume_rand_max | float | "0.000000" |  /  |   |
| volume_atten | float | "1.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| pitch_rand_min | float | "0.000000" |  /  |   |
| pitch_rand_max | float | "0.000000" |  /  |   |
| event_type | float | "0.000000" |  /  |   |
| limiter_on | float | "1.000000" |  /  |   |
| limiter_max | float | "0.000000" |  /  |   |
| limiter_match_type | float | "0" |  /  |   |
| limiter_match_entity | float | "0" |  /  |   |
| limiter_match_this | float | "1" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| seed | float | "-1.000000" |  /  |   |
| vsnd_files | vsnd | ["sounds/common/null.vsnd"] |  /  |   |
| memory_type | float | "0" |  /  |   |

### src1_3d

来源：core/soundstacks/soundstacks_src1.vsndstck_c。

导入栈：core_distance_limiter。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| mixgroup | string | "USEPATHMATCH" |  /  |   |
| volume | float | "1.000000" |  /  |   |
| volume_rand_min | float | "0.000000" |  /  |   |
| volume_rand_max | float | "0.000000" |  /  |   |
| volume_atten | float | "1.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| pitch_rand_min | float | "0.000000" |  /  |   |
| pitch_rand_max | float | "0.000000" |  /  |   |
| soundlevel | float | "70" |  /  |   |
| soundlevel_rand_min | float | "0" |  /  |   |
| soundlevel_rand_max | float | "0" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| event_type | float | "0.000000" |  /  |   |
| distance_max | float | "-1.000000" |  /  |   |
| position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| limiter_on | float | "1.000000" |  /  |   |
| limiter_max | float | "0.000000" |  /  |   |
| limiter_match_type | float | "0" |  /  |   |
| limiter_match_entity | float | "0" |  /  |   |
| limiter_match_this | float | "1" |  /  |   |
| vsnd_files | vsnd | ["sounds/common/null.vsnd"] |  /  |   |
| gender | string | "vsnd_files" |  /  |   |
| male | vsnd | ["sounds/common/null.vsnd"] |  /  |   |
| female | vsnd | ["sounds/common/null.vsnd"] |  /  |   |
| memory_type | float | "0" |  /  |   |

### src1_soundscape_2d

来源：core/soundstacks/soundstacks_src1.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start | float | "1.000000" |  /  |   |
| mixgroup | string | "USEPATHMATCH" |  /  |   |
| volume | float | "1.000000" |  /  |   |
| volume_rand_min | float | "0.000000" |  /  |   |
| volume_rand_max | float | "0.000000" |  /  |   |
| volume_atten | float | "1.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| pitch_rand_min | float | "0.000000" |  /  |   |
| pitch_rand_max | float | "0.000000" |  /  |   |
| event_type | float | "0.000000" |  /  |   |
| limiter_on | float | "1.000000" |  /  |   |
| limiter_max | float | "0.000000" |  /  |   |
| limiter_match_type | float | "0" |  /  |   |
| limiter_match_entity | float | "0" |  /  |   |
| limiter_match_this | float | "1" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| seed | float | "-1.000000" |  /  |   |
| vsnd_files | vsnd | ["sounds/common/null.vsnd"] |  /  |   |
| memory_type | float | "0" |  /  |   |

### src1_soundscape_3d

来源：core/soundstacks/soundstacks_src1.vsndstck_c。

导入栈：core_distance_limiter。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| mixgroup | string | "USEPATHMATCH" |  /  |   |
| volume | float | "1.000000" |  /  |   |
| volume_rand_min | float | "0.000000" |  /  |   |
| volume_rand_max | float | "0.000000" |  /  |   |
| volume_atten | float | "1.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| pitch_rand_min | float | "0.000000" |  /  |   |
| pitch_rand_max | float | "0.000000" |  /  |   |
| soundlevel | float | "70" |  /  |   |
| soundlevel_rand_min | float | "0" |  /  |   |
| soundlevel_rand_max | float | "0" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| event_type | float | "0.000000" |  /  |   |
| distance_max | float | "-1.000000" |  /  |   |
| position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| limiter_on | float | "1.000000" |  /  |   |
| limiter_max | float | "0.000000" |  /  |   |
| limiter_match_type | float | "0" |  /  |   |
| limiter_match_entity | float | "0" |  /  |   |
| limiter_match_this | float | "1" |  /  |   |
| vsnd_files | vsnd | ["sounds/common/null.vsnd"] |  /  |   |
| memory_type | float | "0" |  /  |   |

### test_1_layer_1

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_1_layer_2。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_1_layer_2_field | public_opvar | "test_1_layer_2" |  /  |   |

### test_1_layer_2

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_1_layer_3。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_1_layer_3_field | public_opvar | "test_1_layer_3" |  /  |   |
| parent_string_lookup_2 | string | ["opvar_name_4"] |  /  |   |
| parent_curve_lookup_2 | float6 | ["[ 0.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]","[ 1.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]"] |  /  |   |

### test_1_layer_3

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_1_layer_4。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| parent_string_lookup | string | ["opvar_name_1"] |  /  |   |
| parent_curve_lookup | float6 | ["[ 0.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]","[ 1.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]"] |  /  |   |
| test_1_layer_4_field | public_opvar | "test_1_layer_4" |  /  |   |

### test_1_layer_4

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| opvar_parent_field | string | "" |  /  |   |
| opvar_parent_curve | string | "" |  /  |   |
| local_field | string | "core_exterior" |  /  |   |
| local_curve | float6 | ["[ 0.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]","[ 1.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]"] |  /  |   |

### test_2_layer_1

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_2_layer_2。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_2_layer_2_field | public_opvar | "test_2_layer_2" |  /  |   |

### test_2_layer_2

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_2_layer_3。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_2_layer_3_field | public_opvar | "test_2_layer_3" |  /  |   |
| parent_string_lookup_2 | string | ["opvar_name_4"] |  /  |   |
| parent_curve_lookup_2 | float6 | ["[ 0.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]","[ 1.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]"] |  /  |   |

### test_2_layer_3

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_2_layer_4。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| parent_string_lookup | string | ["opvar_name_2"] |  /  |   |
| parent_curve_lookup | float6 | ["[ 0.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]","[ 1.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]"] |  /  |   |
| test_2_layer_4_field | public_opvar | "test_2_layer_4" |  /  |   |

### test_2_layer_4

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| opvar_parent_field | string | "" |  /  |   |
| opvar_parent_curve | string | "" |  /  |   |
| local_field | string | "core_exterior" |  /  |   |
| local_curve | float6 | ["[ 0.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]","[ 1.0, 1.0, 0.0, 0.0, 0.0, 0.0 ]"] |  /  |   |

### test_3_layer_1

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_3_layer_2。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_3_layer_2 | public_opvar | "test_3_layer_2" |  /  |   |
| vsnd_files_base_field | vsnd | "sounds/common/null.vsnd" |  /  |   |

### test_3_layer_2

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_3_layer_3。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_3_layer_3 | public_opvar | "test_3_layer_3" |  /  |   |

### test_3_layer_3

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_3_layer_4。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_3_layer_4 | public_opvar | "test_3_layer_4" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| vsnd_files_nested_field | string | "vsnd_files" |  /  |   |

### test_3_layer_4

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files_field_name | string | "vsnd_files" |  /  |   |

### test_5_layer_0

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_5_layer_1。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_5_layer_1 | public_opvar | "test_5_layer_1" |  /  |   |
| vsnd_files_outer_field | vsnd | "sounds/diagnostics/ambient/pink_quad_-10_rs.vsnd" |  /  |   |

### test_5_layer_1

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

导入栈：test_5_layer_2。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_5_layer_2 | public_opvar | "test_5_layer_2" |  /  |   |
| vsnd_files_base_field | vsnd | "sounds/common/noise.vsnd" |  /  |   |

### test_5_layer_2

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files_field_name | string | "vsnd_files_base_field" |  /  |   |
| value1 | float | "1.0" |  /  |   |

### test_LFO

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| frequency | float | "1.000000" |  /  |   |
| scale | float | "1.000000" |  /  |   |
| center | float | "0.000000" |  /  |   |
| wave_type | enum | "sin" |  /  |  mod_lfo.wave_type |

### test_beep_on_track

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：diagnostic.timed_beeper。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| track | string | "default_track" |  /  |   |
| sync_track | string | "none" |  /  |   |
| sync_field | string | "none" |  /  |   |
| start_point | float | "0.000000" |  /  |   |
| end_point | float | "0.000000" |  /  |   |
| sync_points | float | ["0.000000","1.000000"] |  /  |   |
| priority | float | "0.000000" |  /  |   |
| priority_override | float | "0.000000" |  /  |   |
| block_equal_priority | float | "0.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |

### test_empty

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| input1 | float | "0" |  / Normal |   |

### test_entity_aabb

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_enum_opvar

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| math_enum | enum | "mult" |  /  |  math_float.apply |

### test_eval

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| expr | string | "_1 + _2*_3 + 5" |  /  |   |
| input1 | float | "0" |  / Normal |   |
| input2 | float | "2" |  / Normal |   |
| input3 | float | "0" |  / Normal |   |
| input4 | float | "0" |  / Normal |   |
| input5 | float | "0" |  / Normal |   |
| output_curve | float6 | ["[ -10, 0.0, 1.0, 1.0, 1.0, 1.0 ]","[ 10.0, 0.0, 1.0, 1.0, 0.0, 1.0 ]"] |  / Normal |   |

### test_get_parent_space

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_goto_exit

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_goto_loop_head

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_goto_loop_operator

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_goto_namespace_operator

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：test_goto_namespace_operator_import。本表只列当前 public 声明，导入栈请另查对应章节。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_goto_namespace_operator_import

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_group_stop

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_groups_branch_string

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| string | string | "string_test1" |  /  |   |
| string2 | string | "string_test2" |  /  |   |

### test_groups_branch_string_variables

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_groups_entindex_invert

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| invert | float | "0.000000" |  /  |   |
| entity_index | float | "777" |  /  |   |

### test_groups_envelope

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_groups_opvar_invert

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| invert | float | "0.000000" |  /  |   |
| opvar | float | "666" |  /  |   |

### test_groups_persist

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| invert | float | "0.000000" |  /  |   |
| opvar | float | "666" |  /  |   |

### test_groups_read_envelope

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_groups_subname_invert

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| invert | float | "0.000000" |  /  |   |

### test_harmonic_tools

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_import_get_parent_space

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：test_soundevent_start_opvar_get_parent_space。本表只列当前 public 声明，导入栈请另查对应章节。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_import_opvar_field

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import_public_field_test | public_opvar | "test_simple_public_field" |  /  |   |

### test_import_random_multiple

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：test_random_multiple。本表只列当前 public 声明，导入栈请另查对应章节。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_inverse_vec3

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| position | float3 | "[0.0, 0.0, 0.0]" |  / locked |   |

### test_random_multiple

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_ryan_imported

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| global_opvar_names | string | "min_vol_inverse_val" | Opvars / normal |   |
| opvars_use_namespace | bool | "true" |  /  |   |

### test_ryan_outer

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：test_ryan_imported。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_ryan_imported | public_opvar | "test_ryan_imported" |  /  |   |

### test_simple_public_field

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_float_for_import_1.111 | float | "1.111000" |  /  |   |

### test_soundevent_block

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| duration | float | "5.000000" |  /  |   |
| match_substring | float | "1.000000" |  /  |   |
| match_event_name | string | "Diagnostic" |  /  |   |

### test_soundevent_control_lfo_stop_at_time

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：core_stop_at_time, update_test_start_vsnd_lfo。本表只列当前 public 声明，导入栈请另查对应章节。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_soundevent_field_override

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_soundevent_group_simple

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_soundevent_group_simple_opvar

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_soundevent_groups

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| on | float | "1.000000" |  /  |   |
| limiter_max | float | "2.000000" |  /  |   |
| limit_opvar | float | "0.000000" |  /  |   |
| event_type | float | "666" |  /  |   |
| entity_index | float | "0" |  /  |   |
| match_this | float | "0" |  /  |   |
| lifespan | float | "-1" |  /  |   |

### test_soundevent_limiter_lfo

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| max_count | float | "0.000000" |  /  |   |
| match_substring | float | "0.000000" |  /  |   |
| invert_match | float | "0.000000" |  /  |   |

### test_soundevent_start_lfo

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| time | float | "8.000000" |  /  |   |

### test_soundevent_start_multi

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| soundevent_1 | sndevt | "default.null" |  /  |   |
| soundevent_2 | sndevt | "default.null" |  /  |   |

### test_soundevent_start_oneshot

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| duration | float | "5.000000" |  /  |   |
| test_value | float | "6.111000" |  /  |   |
| test_value2 | float | "6.222000" |  /  |   |
| test_value3 | float | "6.333000" |  /  |   |
| test_value4 | float | "6.444000" |  /  |   |

### test_soundevent_start_opvar_get_ancestor

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| duration | float | "5.000000" |  /  |   |

### test_soundevent_start_opvar_get_parent

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| duration | float | "5.000000" |  /  |   |

### test_soundevent_start_opvar_get_parent_space

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_float | float | "5.000000" |  /  |   |

### test_soundevent_start_random_multiple

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_start_soundevent

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_start_soundevent_loop

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| soundevent_01 | sndevt | "" | Sound Events / normal |   |

### test_stop_track

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| track | string | "default_track" |  /  |   |

### test_switch_case_12

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_system_properties

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start | float | "1.000000" |  / advanced |   |
| volume | float | "1.000000" |  /  |   |
| volume_rand_min | float | "0.000000" |  / advanced |   |
| volume_rand_max | float | "0.000000" |  / advanced |   |
| pitch | float | "1.000000" |  / advanced |   |
| pitch_rand_min | float | "-0.050000" |  / advanced |   |
| pitch_rand_max | float | "0.050000" |  / advanced |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |
| memory_type | float | "0" |  / locked |   |

### test_timers

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_usable_float_range

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### test_vmix_8track

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.000000" |  /  |   |
| balance | float | "1.000000" |  /  |   |
| vgraph | string | "test_mix8" |  /  |   |
| input | string | "test_input" |  /  |   |
| track1 | string | "sounds/misc/null.vsnd" |  /  |   |
| track2 | string | "sounds/misc/null.vsnd" |  /  |   |
| track3 | string | "sounds/misc/null.vsnd" |  /  |   |
| track4 | string | "sounds/misc/null.vsnd" |  /  |   |
| track5 | string | "sounds/misc/null.vsnd" |  /  |   |
| track6 | string | "sounds/misc/null.vsnd" |  /  |   |
| track7 | string | "sounds/misc/null.vsnd" |  /  |   |
| track8 | string | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files1 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files2 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files3 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files4 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files5 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files6 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files7 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files8 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| volume_test_input | float | "1.000000" |  /  |   |
| memory_type | float | "0" |  /  |   |

### test_vmix_voice_sends

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| volume | float | "1.000000" |  /  |   |
| balance | float | "1.000000" |  /  |   |
| vgraph | string | "test_mix8" |  /  |   |
| track1 | string | "sounds/misc/null.vsnd" |  /  |   |
| track2 | string | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files1 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| vsnd_files2 | vsnd | "sounds/misc/null.vsnd" |  /  |   |
| volume_test_input | float | "1.000000" |  /  |   |
| memory_type | float | "0" |  /  |   |

### test_vmix_vsnd_info

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | "sounds/misc/null.vsnd" |  /  |   |

### test_vsnd_loop_xfade

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| loop_start | float | 0.0 |  /  |   |
| loop_end | float | 3.0 |  /  |   |
| loop_on | float | 1.0 |  /  |   |
| play_head | float | 0.0 |  /  |   |
| stop_tail | float | 0.0 |  /  |   |
| xfade_in | float | 0.0 |  /  |   |
| xfade_out | float | 0.0 |  /  |   |
| in_vsnd | vsnd | "sounds/common/null.vsnd" | Vsnd / basic |   |
| in_vsnd2 | vsnd | "sounds/common/null.vsnd" | Vsnd / basic |   |
| playback_rate | float | 0.0 |  /  |   |

### test_vsnd_on_track

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_start_vsnd_rand_oneshot。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| track | string | "" |  /  |   |
| sync_track | string | "none" |  /  |   |
| sync_field | string | "none" |  /  |   |
| wait_for_track | float | "1.000000" |  /  |   |
| sync_points | float | ["10000.000000"] |  /  |   |
| start_point | float | "0.000000" |  /  |   |
| end_point | float | "0.000000" |  /  |   |
| priority | float | "0.000000" |  /  |   |
| priority_override | float | "0.000000" |  /  |   |
| block_equal_priority | float | "0.000000" |  /  |   |
| use_queue | float | "0.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |

### test_vsnd_on_track2

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_start_vsnd_rand_oneshot。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| track | string | "" |  /  |   |
| sync_track | string | "none" |  /  |   |
| sync_field | string | "none" |  /  |   |
| wait_for_track | float | "1.000000" |  /  |   |
| sync_points | float | ["10000.000000"] |  /  |   |
| priority | float | "0.000000" |  /  |   |
| priority_override | float | "0.000000" |  /  |   |
| block_equal_priority | float | "0.000000" |  /  |   |
| pitch | float | "1.000000" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |

### update_test_array_index_event_increment

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| float_sequence | float | ["11.000000"] |  /  |   |

### update_test_array_index_event_sequence

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| float_sequence | float | ["11.000000"] |  /  |   |

### update_test_array_index_global_stack_sequence

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_array_index_stack_increment

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| float_sequence | float | ["0.000000"] |  /  |   |

### update_test_calc_distance

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_convar

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_delta

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_distant_dsp

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_entity_info

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_env_beep_mixlayer_timing

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_env_beep_timing

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_env_timing

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start_time | float | "0" |  /  |   |
| last_lfo_value | float | "0" |  /  |   |

### update_test_falloff

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_float_filter

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_import_op

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_overrides。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_public_float0 | float | "777.000000" |  /  |   |

### update_test_iterate_merge_speakers

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_lfo_beep

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_lfo_beep_env_trigger

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| start_time | float | "0" |  /  |   |
| last_lfo_value | float | "0" |  /  |   |

### update_test_lfo_beep_timing

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_lfo_timing

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_listener_velocity

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_math_string

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_mixer

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_mixgroup_timing

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_mixlayer

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_occlusion

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_opvar

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_opvar_event_max_multi_sequence

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| float_sequence1 | float | ["0.000000"] |  /  |   |
| float_sequence2 | float | ["0.000000"] |  /  |   |
| float_sequence3 | float | ["0.000000"] |  /  |   |
| float_sequence4 | float | ["0.000000"] |  /  |   |
| float_sequence5 | float | ["0.000000"] |  /  |   |
| float_sequence6 | float | ["0.000000"] |  /  |   |
| float_sequence7 | float | ["0.000000"] |  /  |   |
| float_sequence8 | float | ["0.000000"] |  /  |   |
| float_sequence9 | float | ["0.000000"] |  /  |   |

### update_test_opvar_event_multi_sequence

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| float_sequence1 | float | ["0.000000"] |  /  |   |
| float_sequence2 | float | ["0.000000"] |  /  |   |
| float_sequence3 | float | ["0.000000"] |  /  |   |

### update_test_opvar_event_sequence

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| float_sequence_01 | float | ["0.000000"] |  /  |   |
| float_sequence_02 | float | ["0.000000"] |  /  |   |

### update_test_opvar_global_stack_sequence

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_opvar_stack_sequence

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| float_sequence | float | ["11.000000","22.000000","33.000000","44.000000","55.000000","66.000000","77.000000","88.000000","99.000000"] |  /  |   |

### update_test_opvar_types

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_enum_field | enum | "three" |  /  |   |
| test_bool_field | bool | "666.000000" |  /  |   |
| test_float_field | float | "666.000000" |  /  |   |
| test_float2_field | float2 | "[666.000000, 777]" |  /  |   |
| test_float3_field | float3 | "[666.000000, 777, 888]" |  /  |   |
| test_float4_field | float4 | "[666.000000, 777, 888, 999]" |  /  |   |
| test_float6_field | float6 | "[666.000000, 777, 888, 999, 000, 111]" |  /  |   |
| test_int_field | int | "666.000000" |  /  |   |
| test_uint32_field | uint32 | "666.000000" |  /  |   |
| test_uint64_field | uint64 | "666.000000" |  /  |   |

### update_test_overrides

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_public_float1 | float | "666.000000" |  /  |   |

### update_test_simple_import_op

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_simple_public。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import1_float | float | "666.000000" |  /  |   |

### update_test_simple_nest_import_op1

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_simple_public。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import1_float | float | "111.000000" |  /  |   |

### update_test_simple_nest_import_op2

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_simple_nest_import_op1。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import2_float | float | "222.000000" |  /  |   |

### update_test_simple_nest_import_op3

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_simple_nest_import_op2。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import3_float | float | "333.000000" |  /  |   |

### update_test_simple_nest_import_op4

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_simple_nest_import_op3。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| import4_float | float | "444.000000" |  /  |   |

### update_test_simple_public

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| public_float | float | "777.000000" |  /  |   |
| override_float | float | "111.000000" |  /  |   |

### update_test_simple_serial_import_op

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_simple_public。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| serial_float | float | "222.000000" |  /  |   |
| serial_float2 | float | "333.000000" |  /  |   |
| import1_float | float | "666.000000" |  /  |   |

### update_test_simple_serial_import_op2

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

导入栈：update_test_simple_public。本表只列当前 public 声明，导入栈请另查对应章节。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| serial_float | float | "222.000000" |  /  |   |

### update_test_start_event_vsnd_rand_oneshot

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | "sounds/diagnostics/ambient/random_amb_sfx/forest_bird01.vsnd" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| memory_type | float | "0" |  /  |   |

### update_test_start_event_vsnd_rand_weighted_oneshot

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | "sounds/diagnostics/ambient/random_amb_sfx/forest_bird01.vsnd" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| memory_type | float | "0" |  /  |   |
| weights | float | "0" |  /  |   |

### update_test_start_stack_vsnd_rand_oneshot

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| file_list_stack_name | string | "" |  /  |   |
| file_list_operator_name | string | "" |  /  |   |
| file_list_field_name | string | "" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| memory_type | float | "0" |  /  |   |

### update_test_start_vsnd_lfo

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| test_float | float | "111.111000" |  /  |   |
| test_floatB | float | "666.666016" |  /  |   |
| test_float2 | float2 | "[ 111.111, 222.222 ]" |  /  |   |
| test_float3 | float3 | "[ 111.111, 222.222, 333.333 ]" |  /  |   |
| test_float4 | float4 | "[ 111.111, 222.222, 333.333, 444.444 ]" |  /  |   |
| test_string | string | "string" |  /  |   |
| test_float_array | float | ["1.000000","2.000000","3.000000","4.000000"] |  /  |   |
| memory_type | float | "0" |  /  |   |

### update_test_start_vsnd_rand_oneshot

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | ["sounds/diagnostics/ambient/random_amb_sfx/forest_bird01.vsnd","sounds/diagnostics/ambient/random_amb_sfx/forest_bird01b.vsnd","sounds/diagnostics/ambient/random_amb_sfx/forest_bird02.vsnd","sounds/diagnostics/ambient/random_amb_sfx/forest_bird02b.vsnd","sounds/diagnostics/ambient/random_amb_sfx/forest_bird03.vsnd"] |  /  |   |
| restart_time | float | "0.000000" |  /  |   |
| fade_out | float | "0.000000" |  /  |   |
| time_scale | float | "1.000000" |  /  |   |
| delay | float | "0.000000" |  /  |   |
| memory_type | float | "0" |  /  |   |
| wave_type | enum | "tri" |  /  |   |

### update_test_start_vsnd_tracks

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | ["sounds/diagnostics/bell.vsnd"] |  /  |   |

### update_test_utils

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

没有当前栈直接声明的 public 参数；不据此断言不能接受参数。

### update_test_vsnd_envelope

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | ["sounds/diagnostics/enveloped_noise_01.vsnd"] |  /  |   |

### update_test_vsnd_simple_loop

来源：core/soundstacks/soundstacks_diagnostics.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| vsnd_files | vsnd | "sounds/diagnostics/click4_4sec_lp-01.vsnd" |  /  |   |
| restart_time | float | "0.000000" |  /  |   |

### util_float3_lerp

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| position1 | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| position2 | float3 | "[1.0, 1.0, 1.0]" |  /  |   |
| percentage | float | "0.500000" |  /  |   |
| output_position | float3 | "[0.0, 0.0, 0.0]" |  /  |   |
| remap_x1 | float | "0.000000" |  /  |   |
| remap_y1 | float | "0.000000" |  /  |   |
| remap_x2 | float | "1.000000" |  /  |   |
| remap_y2 | float | "1.000000" |  /  |   |
| remap_x3 | float | "1.000000" |  /  |   |
| remap_y3 | float | "1.000000" |  /  |   |
| remap_x4 | float | "1.000000" |  /  |   |
| remap_y4 | float | "1.000000" |  /  |   |

### util_timer

来源：core/soundstacks/soundstacks_soundscapes_core.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| running | float | "0.000000" |  /  |   |
| output_time | float | "0.000000" |  /  |   |
| reset | float | "0.000000" |  /  |   |

### vsnd_base_stack

来源：core/soundstacks/soundstacks_import_opvars_test.vsndstck_c。

| 参数 | 声明类型 | 栈默认值（内部表示） | 分组 / 显示级别 | 编辑条件 / 枚举来源 |
| --- | --- | --- | --- | --- |
| value1 | float | "1.0" |  /  |   |
| value2 | float | "2.0" |  /  |   |
| value3 | float | "3.0" |  /  |   |
| vsnd_files | vsnd | "sounds/common/null.vsnd" |  /  |   |

## 底层操作函数及实际出现的参数

类型依据：引用声明类型只说明连接源的类型；字段真实签名仍待 DLL 注册表确认。存储类型是资源里的实际编码。样本常量仅用于观察已用写法，不是默认值、完整枚举或允许范围。


### accumulate_indexed_speakers

出现于：update_test_iterate_merge_speakers。

样本没有额外参数；不代表函数没有其他参数。


### beatpattern_pattern_start

出现于：beatpattern_4x4, core_beatpattern_start_pattern。

已被引用的输出：output_event_happened。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input_play_beat_mult | string | float | 有 |  |
| input_queue_beat_mult | string | float | 有 |  |
| input_start | string | bool | 有 |  |
| input_stop | string | 未确认 | 有 |  |
| pattern_name | string | string | 有 |  |
| play_event_type | string | enum | 有 |  |
| queue_event_type | string | enum | 有 |  |
| track_name | string | string | 有 |  |

### calc_distance

出现于：core_doppler, core_sampler_base, core_simple_3d, csgo_ambient, csgo_mega, csgo_surf, soundscape_3d_sound, src1_3d, src1_soundscape_3d, update_test_calc_distance。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input_position1 | string | float3 | 有 | "[ 110.0, 120.0 ]" |
| input_position2 | string | float3 | 有 | "[ 0.0, 0.0, 0.0 ]" |

### calc_distant_dsp

出现于：update_test_distant_dsp。

样本没有额外参数；不代表函数没有其他参数。


### calc_falloff

出现于：soundscape_3d_sound, src1_3d, src1_soundscape_3d, update_test_falloff。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_distance | string | 未确认 | 有 |  |
| input_level | string | 未确认 | 有 |  |

### calc_falloff_curve

出现于：core_sampler_base。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_atten | string | 未确认 | 未观察到 | "1.000000" |
| input_curve_amount | string | 未确认 | 未观察到 | "0.890000" |
| input_distance | string | 未确认 | 有 |  |
| input_max | string | 未确认 | 有 |  |
| input_min | string | 未确认 | 有 |  |

### calc_occlusion_info

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input_execute | string | 未确认 | 有 |  |
| input_indirect_override | string | 未确认 | 有 |  |
| input_listener_position | string | 未确认 | 有 |  |
| input_source_position | string | 未确认 | 有 |  |

### calc_occlusion_src1

出现于：core_sampler_base, src1_3d, update_test_occlusion。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_listener_position | string | 未确认 | 有 |  |
| input_radius | string | float | 有 |  |
| input_scalar | string | float | 有 | "1.000000" |
| input_source_position | string | 未确认 | 有 |  |

### calc_spatialize_speakers

出现于：core_simple_3d, csgo_ambient, csgo_mega, csgo_surf, soundscape_3d_sound, src1_3d, src1_soundscape_3d。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input_distance | string | 未确认 | 有 |  |
| input_listener_left | string | 未确认 | 有 |  |
| input_listener_position | string | 未确认 | 有 |  |
| input_master_volume | string | 未确认 | 有 | "1" |
| input_radius | string | 未确认 | 未观察到 | "15"; "300" |
| input_rear_stereo_scale | string | 未确认 | 有 | "1.000000" |
| input_source_position | string | 未确认 | 有 |  |

### calc_spatialize_vr

出现于：core_sampler_base。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_distance | string | 未确认 | 有 |  |
| input_listener_forward | string | 未确认 | 有 |  |
| input_listener_left | string | 未确认 | 有 |  |
| input_listener_position | string | 未确认 | 有 |  |
| input_listener_up | string | 未确认 | 有 |  |
| input_master_volume | string | 未确认 | 有 |  |
| input_source_position | string | 未确认 | 有 |  |
| input_spread_max | string | 未确认 | 有 |  |
| input_spread_min | string | 未确认 | 有 |  |

### container_sample_curve

出现于：container_env_test, update_test_env_timing, update_test_lfo_beep_env_trigger, update_test_vsnd_envelope。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_container | string | vsnd | 有 | "sounds/diagnostics/containers/beep_test_container.vsnd" |
| input_default | string | 未确认 | 未观察到 | "0.0" |
| input_time | string | 未确认 | 有 |  |

### convar_get

出现于：core_setter_AHR_game_volume, csgo_ambient, csgo_mega, csgo_music, csgo_surf, update_test_convar。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| convar | string | string | 有 | "snd_gain"; "snd_music_mode"; "snd_op_test_convar"; "snd_rear_stereo_scale"; "snd_spatialize_lerp"; "snd_surf_volume_map"; "snd_use_baked_occlusion"; "sv_surf_sounds" |
| execute_once | string | 未确认 | 未观察到 | "0"; "false"; "true" |
| input_execute | string | bool | 有 |  |
| output | string | 未确认 | 未观察到 | "1.0" |

### convar_set

出现于：core_setter_AHR_game_volume, update_test_convar。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| convar | string | 未确认 | 未观察到 | "snd_gain"; "snd_musicvolume" |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 有 |  |

### ctrl_switch12_float

出现于：csgo_music, diagnostic.self_exciting_gallery。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input0 | string | 未确认 | 有 | "0.0" |
| input1 | string | 未确认 | 有 |  |
| input2 | string | 未确认 | 有 |  |
| input3 | string | 未确认 | 有 |  |
| input4 | string | 未确认 | 有 |  |
| input5 | string | 未确认 | 有 |  |
| input6 | string | 未确认 | 有 |  |
| input_index | string | float | 有 |  |

### ctrl_switch3_string

出现于：csgo_music。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input1 | string | 未确认 | 未观察到 | "endpoint_01"; "public.endpoint_01"; "public.startpoint_01"; "public.syncpoints_01"; "restart_startpoint_01"; "startpoint_01" |
| input2 | string | 未确认 | 未观察到 | "endpoint_02"; "public.endpoint_02"; "public.startpoint_02"; "public.syncpoints_02"; "restart_startpoint_02"; "startpoint_02" |
| input3 | string | 未确认 | 未观察到 | "endpoint_03"; "public.endpoint_03"; "public.startpoint_03"; "public.syncpoints_03"; "restart_startpoint_03"; "startpoint_03" |
| input_execute | string | bool | 有 |  |
| input_index | string | 未确认 | 有 |  |

### ctrl_switch_float

出现于：core_doppler, core_sampler_base, core_setter_AHR_base, csgo_ambient, csgo_mega, csgo_music, csgo_surf, soundscape_opvar_percentage, soundscape_opvar_switch, soundscape_scalebang, soundscape_test_weather, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_vsnd_loop_xfade。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "0" |
| input1 | string | float | 有 | "-1"; "-1.000000"; "0"; "0.000000"; "1"; "1.0"; "1.000000"; "5" |
| input2 | string | float | 有 | "-1"; "0"; "0.0"; "0.16"; "1.0"; "1.000000"; "7" |
| input_execute | string | 未确认 | 未观察到 | "1"; "1.000000" |
| input_switch | string | bool, float | 有 |  |
| output | string | 未确认 | 未观察到 | "0.000000" |

### ctrl_switch_float3

出现于：csgo_ambient, csgo_mega, csgo_surf, soundscape_play_random。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "0" |
| input1 | string | float3 | 有 |  |
| input2 | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1.000000" |
| input_switch | string | bool, float | 有 |  |

### ctrl_switch_string

出现于：csgo_ambient, csgo_mega, csgo_music, csgo_surf。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input1 | string | 未确认 | 有 | "" |
| input2 | string | 未确认 | 有 | "reverb_0_null" |
| input_execute | string | bool | 有 | "1" |
| input_switch | string | bool | 有 |  |

### ctrl_threshold_logic3

出现于：Diagnostic.test_threshold_logic。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_threshold_high | float | 未确认 | 未观察到 | 0.75 |
| input_threshold_low | float | 未确认 | 未观察到 | 0.15 |
| input_threshold_mid | float | 未确认 | 未观察到 | 0.5 |
| threshold_type | string | 未确认 | 未观察到 | "greater_than"; "greater_than_or_equal"; "less_than"; "less_than_or_equal" |

### game_entity_info

出现于：core_sampler_base, core_simple_3d, csgo_ambient, csgo_mega, csgo_surf, soundscape_3d_sound, src1_3d, src1_soundscape_3d, update_test_entity_info。

已被引用的输出：output_entity_is_actual_player_entity, output_entity_is_player, output_id_deleted, output_position, output_success。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| attachment | string | string_token | 有 |  |
| execute_once | string | 未确认 | 未观察到 | "1" |
| input_add_velocity_on_deleted_entity | string | 未确认 | 未观察到 | "false" |
| input_default_local_position | string | 未确认 | 有 |  |
| input_default_world_position | string | float3 | 有 |  |
| input_entity_index | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 有 | "1" |
| input_hold_position_on_deleted_entity | string | 未确认 | 未观察到 | "true" |
| use_entity_position_if_local_player | string | bool | 有 |  |
| use_world_position | string | bool | 有 |  |
| use_world_position_if_dormant | string | 未确认 | 未观察到 | "true" |

### game_entity_world_aabb

出现于：test_entity_aabb。

已被引用的输出：output_pos_max, output_pos_min。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_entity_index | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1.000000" |

### game_find_entities_list_by_name

出现于：csgo_ambient。

已被引用的输出：output_entity_index_01, output_entity_index_02, output_entity_index_03, output_entity_index_04, output_entity_index_05, output_entity_index_06, output_entity_index_07, output_entity_index_08, output_entity_index_09, output_entity_index_10, output_entity_index_11, output_entity_index_12, output_entity_index_13, output_entity_index_14, output_entity_index_15, output_entity_index_16, output_success。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| entity_name | string | string | 有 |  |
| execute_once | string | 未确认 | 未观察到 | "1" |
| input_execute | string | bool | 有 |  |

### game_find_entity_by_name

出现于：csgo_mega。

已被引用的输出：output_entity_index, output_success。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| entity_name | string | string | 有 |  |
| execute_once | string | 未确认 | 未观察到 | "1" |
| input_execute | string | bool | 有 |  |

### game_get_soundscape_local_position

出现于：csgo_ambient, csgo_mega。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_position_index | string | int | 有 |  |

### game_get_source_info

出现于：core_simple_3d, csgo_ambient, csgo_mega, csgo_surf, soundscape_2d_sound, soundscape_3d_sound, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_entity_aabb。

已被引用的输出：output_entity_classname, output_entity_index。输出类型尚未从 DLL 反射。

样本没有额外参数；不代表函数没有其他参数。


### game_get_source_player_info

出现于：csgo_ambient, csgo_mega。

已被引用的输出：output_is_stealthy。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "1" |
| input_execute | string | bool | 有 |  |

### get_system_globals

出现于：Diagnostic.test_sound_area, core_sampler_base, core_simple_3d, csgo_ambient, csgo_mega, csgo_music, csgo_surf, csgo_voip, diagnostic.animate_float3_gallery, diagnostic.self_exciting_column, soundscape_2d_sound, soundscape_3d_sound, soundscape_play_random, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_inverse_vec3, update_test_listener_velocity。

已被引用的输出：output_listener_forward, output_listener_front, output_listener_left, output_listener_position, output_listener_up, output_snd_gain_convar, output_snd_musicvolume_convar。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_listener_index | string | 未确认 | 未观察到 | "0" |

### harmonic_tools_delta_harmonic_response

出现于：test_harmonic_tools。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | float | 未确认 | 未观察到 | 0.25 |
| input_max_val | float | 未确认 | 未观察到 | 1.0 |
| input_multiplier_negative | string | 未确认 | 未观察到 | "[ 4.2, 2.2, 3.2, 5.2, 6.2, 7.2, 8.2, 1.2, 9.2, 10.2, 11.2, 12.2, 13.2, 14.2, 15.2, 16.2 ]" |
| input_multiplier_positive | string | 未确认 | 未观察到 | "[ -4.2, 2.2, 3.2, 5.2, 6.2, 7.2, 8.2, 1.2, 9.2, 10.2, 11.2, -2.2, -3.2, -4.2, -5.2, -6.2 ]" |
| input_num_harmonics | int | 未确认 | 未观察到 | 12 |
| input_threshold_end_negative | string | 未确认 | 未观察到 | "[ -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0 ]" |
| input_threshold_end_positive | string | 未确认 | 未观察到 | "[ 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0 ]" |
| input_threshold_start_negative | string | 未确认 | 未观察到 | "[ -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1, -0.1 ]" |
| input_threshold_start_positive | string | 未确认 | 未观察到 | "[ 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1 ]" |

### harmonic_tools_harmonic_lfos

出现于：test_harmonic_tools。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | float | 未确认 | 未观察到 | 0.2 |
| input_depth_max | float | 未确认 | 未观察到 | 0.5 |
| input_depth_min | float | 未确认 | 未观察到 | 0.1 |
| input_depth_multiplier | string | 未确认 | 未观察到 | "[ 4.0, 2.0, 3.0, 5.0, 6.0, 7.0, 8.0, 1.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0 ]" |
| input_lfo_center | string | 未确认 | 未观察到 | "[ 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7 ]" |
| input_max_val | float | 未确认 | 未观察到 | 1.0 |
| input_min_val | float | 未确认 | 未观察到 | -1.0 |
| input_num_harmonics | int | 未确认 | 未观察到 | 12 |
| input_rate_max | float | 未确认 | 未观察到 | 0.8 |
| input_rate_min | float | 未确认 | 未观察到 | 0.2 |
| input_rate_multiplier | string | 未确认 | 未观察到 | "[ 4.0, 2.0, 3.0, 5.0, 6.0, 7.0, 8.0, 1.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0 ]" |
| lfo_shape | string | 未确认 | 未观察到 | "sine" |

### harmonic_tools_odds_and_evens

出现于：test_harmonic_tools。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | float | 未确认 | 未观察到 | 0.22 |
| input_curve_amount | float | 未确认 | 未观察到 | 1.0 |
| input_max_val | float | 未确认 | 未观察到 | 1.0 |
| input_min_val | float | 未确认 | 未观察到 | 0.5 |
| input_num_harmonics | int | 未确认 | 未观察到 | 12 |
| input_odds_level | float | 未确认 | 未观察到 | 0.0 |
| use_independant_levels | string | 未确认 | 未观察到 | "false" |

### harmonic_tools_spectral_spread

出现于：test_harmonic_tools。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | float | 未确认 | 未观察到 | 0.35 |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_max_val | float | 未确认 | 未观察到 | 1.2 |
| input_min_val | float | 未确认 | 未观察到 | 0.5 |
| input_num_harmonics | int | 未确认 | 未观察到 | 12 |
| input_spread | float | 未确认 | 未观察到 | 0.15 |

### is_local_player_slot

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | int | 有 |  |

### logic_string_match_12

出现于：test_switch_case_12。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | 未确认 | 未观察到 | "loose_brick_gravel" |
| input_default | int | 未确认 | 未观察到 | 4 |
| string0 | string | 未确认 | 未观察到 | "true false etc" |
| string1 | string | 未确认 | 未观察到 | "foo bar biz baz" |
| string3 | string | 未确认 | 未观察到 | "gravel gravel_brick hard_gravel_brick loose_brick_gravel viscera" |
| string7 | string | 未确认 | 未观察到 | "electricity forcefield futuretech_bs alientech_bs" |

### math_accumulate12_float

出现于：core_sampler_base, core_simple_3d, csgo_ambient, csgo_mega, csgo_surf, csgo_voip, soundscape_2d_sound, soundscape_3d_sound, soundscape_play_looping, soundscape_play_random, soundscape_play_soundscape, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| apply | string | 未确认 | 未观察到 | "mult" |
| input1 | string | float | 有 |  |
| input10 | string | 未确认 | 未观察到 | "1.000000" |
| input11 | string | 未确认 | 未观察到 | "1.000000" |
| input12 | string | 未确认 | 未观察到 | "1.000000" |
| input2 | string | float | 有 | "1.000000" |
| input3 | string | 未确认 | 有 | "1.000000" |
| input4 | string | 未确认 | 有 | "1.000000" |
| input5 | string | float | 有 | "1.000000" |
| input6 | string | float | 有 | "1.000000" |
| input7 | string | float | 有 | "1.000000" |
| input8 | string | 未确认 | 未观察到 | "1.000000" |
| input9 | string | float | 有 | "1.000000" |

### math_accumulate16_float16

出现于：test_harmonic_tools。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| apply | string | 未确认 | 未观察到 | "mult" |
| input1 | string | 未确认 | 有 |  |
| input2 | string | 未确认 | 有 |  |
| input3 | string | 未确认 | 有 |  |
| input4 | string | 未确认 | 有 |  |

### math_animate_float3

出现于：diagnostic.animate_float3_gallery。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| anim_type | string | 未确认 | 未观察到 | "bezier"; "bezier_bounce"; "bezier_even"; "bezier_even_bounce"; "circle"; "circle_bounce"; "lerp"; "lerp_bounce"；另有 6 项 |
| input_animation_direction | string | 未确认 | 未观察到 | "0" |
| input_animation_pct | string | 未确认 | 有 |  |
| input_distance_scalar | string | 未确认 | 未观察到 | "1.0" |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_float3_center | string | 未确认 | 有 |  |
| input_float3_end | string | 未确认 | 有 |  |
| input_float3_start | string | 未确认 | 有 |  |
| input_revolutions | string | float | 有 |  |

### math_calc_angle_from_3_vec3

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_center_position | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_position_01 | string | 未确认 | 有 |  |
| input_position_02 | string | 未确认 | 有 |  |

### math_calc_directional_vec3

出现于：test_inverse_vec3。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input_center_position | string | 未确认 | 有 |  |
| input_start_position | string | float3 | 有 |  |

### math_calc_doppler

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_doppler_factor | string | float | 有 |  |
| input_doppler_factor_receding | string | float | 有 |  |
| input_doppler_observer_scale | string | 未确认 | 未观察到 | "0.050000" |
| input_execute | string | bool | 有 |  |
| input_observer_position | string | 未确认 | 有 |  |
| input_source_position | string | 未确认 | 有 |  |

### math_crossfade_float

出现于：Diagnostic.TestCrossfade, csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output1, output2。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| equal_power_amount | string | float | 有 | "1" |
| input | string | float | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1" |

### math_curve_2d

出现于：Diagnostic.TestCurve2d, core_setter_curve_base, csgo_ambient, csgo_mega, csgo_music, csgo_surf, test_eval。

已被引用的输出：output, output_x_max。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | float | 有 |  |
| input_execute | string | bool | 有 |  |
| input_scale_X | string | 未确认 | 未观察到 | "1.000000" |
| input_scale_Y | string | 未确认 | 未观察到 | "1.000000" |
| input_scale_x | string | 未确认 | 未观察到 | "1.0"; "1.000000" |
| input_scale_y | string | 未确认 | 未观察到 | "1.0"; "1.000000" |
| output | string | 未确认 | 未观察到 | "-1.000000"; "0.0"; "0.000000"; "1"; "1.0" |
| public_field_name | string | 未确认 | 未观察到 | "public.curve"; "public.distance_pitch_mapping_curve"; "public.distance_unfiltered_stereo_mapping_curve"; "public.distance_volume_mapping_curve"; "public.fadetime_volume_mapping_curve"; "public.impact_speed_input_volume_mapping_curve"; "public.occlusion_path_curve"; "public.output_curve"；另有 5 项 |

### math_curve_2d_4knot

出现于：Diagnostic.TestCurve2d, soundscape_opvar_percentage, soundscape_opvar_switch, soundscape_play_burst, soundscape_scalebang, util_float3_lerp。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| curve_defintion_type | string | 未确认 | 未观察到 | "vector" |
| curve_type | string | 未确认 | 未观察到 | "linear"; "spline" |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "0"; "1.000000" |
| input | string | float | 有 |  |
| input_X1 | string | float | 有 | "0" |
| input_X2 | string | float | 有 |  |
| input_X3 | string | float | 有 |  |
| input_X4 | string | float | 有 |  |
| input_Y1 | string | float | 有 | "0.000000"; "0.850000"; "1.000000" |
| input_Y2 | string | float | 有 | "0.600000"; "1.000000"; "2.000000" |
| input_Y3 | string | float | 有 | "0.600000"; "1.000000"; "2.000000" |
| input_Y4 | string | float | 有 | "0.600000"; "1.000000"; "2.000000" |
| input_execute | string | float | 有 | "1"; "1.000000" |
| input_vector | string | 未确认 | 有 |  |
| output | string | 未确认 | 未观察到 | "0" |

### math_curve_2d_6knot

出现于：Diagnostic.TestCurve2d。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| curve_type | string | 未确认 | 未观察到 | "spline" |
| execute_once | string | 未确认 | 未观察到 | "1.000000" |
| input | string | float | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_vector | string | 未确认 | 有 |  |

### math_delta

出现于：core_doppler, soundscape_scalebang, update_test_delta, util_timer。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "0" |
| input | string | float | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1.000000" |
| output | string | 未确认 | 未观察到 | "0" |

### math_filter_float

出现于：core_sampler_base, csgo_ambient, csgo_mega, csgo_surf, soundscape_opvar_percentage, soundscape_opvar_switch, update_test_float_filter。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input | string | float | 有 |  |
| input_execute | string | bool | 有 |  |
| input_max_velocity | string | float | 有 | "1.000000" |
| input_reset | string | 未确认 | 未观察到 | "1" |

### math_float

出现于：Diagnostic.test_threshold_logic, beatpattern_4x4, core_distance_limiter, core_doppler, core_max_multiple, core_null_timed, core_sampler_base, core_setter_AHR_base, core_setter_curve_base, core_soundevent_blocker, core_stop_at_time, core_valve_default, core_volume_limiter, csgo_ambient, csgo_mega, csgo_music, csgo_surf, dave_sb_bang, dave_timer_test, diagnostic.animate_float3_gallery, diagnostic.self_exciting_column, diagnostic.start_n_soundevents, diagnostic.timed_silence, example_timetriggered_simple_oneshot, soundscape_3d_sound, soundscape_opvar_percentage, soundscape_play_burst, soundscape_play_looping, soundscape_play_random, soundscape_scalebang, src1_3d, src1_soundscape_3d, test_beep_on_track, test_enum_opvar, test_goto_loop_head, test_goto_loop_operator, test_soundevent_start_lfo, test_system_properties, test_vsnd_loop_xfade, update_test_import_op, update_test_lfo_beep, update_test_lfo_beep_env_trigger, update_test_overrides, update_test_simple_import_op, update_test_simple_nest_import_op1, update_test_simple_nest_import_op2, update_test_simple_nest_import_op3, update_test_simple_nest_import_op4, update_test_simple_public, update_test_start_vsnd_lfo, util_timer。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| apply | string | enum | 有 | "add"; "and"; "div"; "equal"; "greater_than"; "greater_than_or_equal"; "invert"; "invert_scale"；另有 10 项 |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | array, string | 未确认 | 未观察到 | "0"; "1"; "false"; "true" |
| input1 | string | bool, float | 有 | "1"; "1.0"; "1.000000"; "662" |
| input2 | string | bool, float | 有 | "-0.5"; "-1.000000"; "0"; "0.0"; "0.00"; "0.000000"; "0.01"; "0.100000"；另有 14 项 |
| input_execute | string | bool, float | 有 | "1"; "1.000000" |
| output | string | 未确认 | 未观察到 | "0"; "1"; "1.000000"; "100" |

### math_float3

出现于：csgo_ambient, csgo_mega, csgo_surf, dave_test_random_pos, diagnostic.animate_float3_gallery, diagnostic.self_exciting_column, update_test_listener_velocity, util_float3_lerp。

已被引用的输出：output, output_float。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| apply | string | 未确认 | 未观察到 | "add"; "distance"; "mult"; "sub" |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "0" |
| input1 | string | float3 | 有 |  |
| input2 | string | float3 | 有 | "[ 1.0, 1.0, 0.0 ]"; "[-120.0, -240.0, 0.0]"; "[-120.0, -480.0, 0.0]"; "[-120.0, 0.0, 0.0]"; "[-120.0, 240.0, 0.0]"; "[-120.0, 480.0, 0.0]"; "[-24.0, 0.0, 128.0]"; "[-360.0, -240.0, 0.0]"；另有 10 项 |
| input_execute | string | bool | 有 | "1.000000" |
| output | string | 未确认 | 未观察到 | "0" |

### math_float_eval

出现于：csgo_ambient, csgo_mega, csgo_music, test_eval, update_test_env_timing, update_test_lfo_beep_env_trigger。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | bool, string | 未确认 | 未观察到 | "1"; true |
| expression | string | string | 有 | "(_3 && _4) ? 0 : (_1+_2)"; "1.0 - _1"; "_1 - _2"; "_1 <= 0 &#124;&#124; _2 >= _3"; "_1 ? _2 : 1"; "min( max(_1, 0) , (_2 == 0))" |
| input1 | string | float | 有 |  |
| input2 | string | float | 有 |  |
| input3 | string | float | 有 |  |
| input4 | string | bool, float | 有 |  |
| input5 | string | float | 有 |  |
| input_execute | string | bool | 有 |  |
| output | string | 未确认 | 未观察到 | "1.0" |

### math_func_float

出现于：Diagnostic.test_threshold_logic, update_test_start_vsnd_lfo。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| function | string | 未确认 | 未观察到 | "cos"; "fabs"; "sin" |
| input1 | string | 未确认 | 有 |  |
| normalize_trig | string | 未确认 | 未观察到 | "false" |

### math_lerp_float3

出现于：diagnostic.animate_float3_gallery。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_factor | string | 未确认 | 未观察到 | "0.5" |
| input_position_a | string | 未确认 | 有 |  |
| input_position_b | string | 未确认 | 有 |  |

### math_lerp_speakers

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | 未确认 | 有 |  |
| input1 | string | 未确认 | 有 |  |
| input2 | string | 未确认 | 有 |  |

### math_opvar_curve_2d

出现于：test_1_layer_4, test_2_layer_4。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | string | 未确认 | 未观察到 | "1.0" |
| input_field_name | string | string | 有 | "local_curve"; "parent_curve_lookup_2" |
| input_operator_name | string | 未确认 | 未观察到 | "public" |
| input_use_namespace | string | 未确认 | 未观察到 | "false"; "true" |

### math_perlin_noise

出现于：core_sampler_base。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_x | string | 未确认 | 有 |  |
| input_z | string | 未确认 | 有 |  |
| noise_type | string | 未确认 | 未观察到 | "perlin" |

### math_random_float

出现于：core_soundevent_blocker, core_start_oneshot, csgo_ambient, csgo_mega, csgo_surf, diagnostic.usable_float_range, soundscape_2d_sound, soundscape_3d_sound, soundscape_opvar_percentage, soundscape_play_burst, soundscape_play_looping, soundscape_play_random, test_random_multiple, test_usable_float_range。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | int, string | 未确认 | 未观察到 | "0"; "1"; "false"; "true"; 1 |
| input_execute | int, string | bool, float | 有 | "1.000000"; 1 |
| input_max | string | float | 有 | "0"; "1.000000"; "100.0" |
| input_min | string | float | 有 | "-10.0"; "-1000"; "0.000000" |
| output | string | 未确认 | 未观察到 | "0"; "0.000000" |
| round_to_int | string | 未确认 | 未观察到 | "0" |

### math_random_float3

出现于：csgo_ambient, csgo_mega, csgo_surf, dave_test_random_pos, diagnostic.self_exciting_column, soundscape_play_random。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | string | 未确认 | 有 |  |
| input_force_positive_z | string | bool | 有 | "1" |
| input_position | string | float3 | 有 |  |
| input_radius_max | string | float | 有 |  |
| input_radius_min | string | float | 有 |  |

### math_random_self_exciting

出现于：diagnostic.self_exciting_column。

已被引用的输出：output_excitation, output_next_gap, output_trigger。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_cluster_period | string | float | 有 |  |
| input_excite | string | float | 有 |  |
| input_refractory | string | float | 有 |  |
| input_tau | string | float | 有 |  |
| mode | string | enum | 有 |  |
| start_mode | string | enum | 有 |  |

### math_randomize_float

出现于：core_sampler_base, core_valve_default, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_system_properties。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input | string | float | 有 | "1" |
| input_rand_max | string | float | 有 |  |
| input_rand_min | string | float | 有 |  |

### math_remap_float

出现于：core_sampler_base, core_setter_AHR_base, core_setter_ramp_to_value_base, core_simple_3d, csgo_music, diagnostic.self_exciting_column。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| default_to_max | string | 未确认 | 未观察到 | "false"; "true" |
| input | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_map_max | string | float | 有 | "0.0"; "0.000000"; "0.700000"; "1.0"; "1.000000"; "48.000000" |
| input_map_min | string | float | 有 | "0.0"; "0.000000"; "0.350000"; "1.000000"; "3.000000" |
| input_max | string | float | 有 | "0.0"; "1440" |
| input_min | string | float | 有 | "0.0"; "0.000000"; "16" |

### math_scale_float3

出现于：csgo_ambient, csgo_mega, csgo_surf, diagnostic.self_exciting_column。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input1 | string | float3 | 有 |  |
| input2 | string | 未确认 | 有 | "0.350000" |
| input_execute | string | bool | 有 |  |

### math_speakers

出现于：csgo_ambient, csgo_mega, csgo_surf, soundscape_3d_sound, src1_3d, src1_soundscape_3d, test_vmix_8track, test_vmix_voice_sends。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| apply | string | 未确认 | 未观察到 | "mult" |
| center | string | 未确认 | 未观察到 | "1.000000"; "1.500000" |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input1 | string | 未确认 | 有 |  |
| input2 | string | 未确认 | 有 |  |
| left_front | string | 未确认 | 未观察到 | "1.000000"; "1.500000" |
| left_rear | string | 未确认 | 未观察到 | "1.000000"; "1.500000" |
| left_side | string | 未确认 | 未观察到 | "1.500000" |
| lfe | string | 未确认 | 未观察到 | "0.666000"; "1.000000"; "1.500000" |
| right_front | string | 未确认 | 未观察到 | "0.666000"; "1.000000"; "1.500000" |
| right_rear | string | 未确认 | 未观察到 | "0.666000"; "1.000000"; "1.500000" |
| right_side | string | 未确认 | 未观察到 | "1.500000" |

### math_string

出现于：csgo_ambient, csgo_mega, csgo_music, soundscape_opvar_percentage, soundscape_opvar_switch, update_test_math_string。

已被引用的输出：output, output_string。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| apply | string | 未确认 | 未观察到 | "add"; "equal"; "not_equal" |
| execute_once | string | 未确认 | 未观察到 | "1"; "false" |
| input1 | string | string | 有 | "test3" |
| input2 | string | 未确认 | 未观察到 | "Ambient"; "_armsrace"; "_casual"; "_deathmatch"; "_rush"; "foo"; "snd_musicvolume"; "test3" |
| input_execute | string | bool | 有 |  |

### math_velocity

出现于：core_doppler, update_test_listener_velocity。

已被引用的输出：output_velocity。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_position | string | float3 | 有 |  |

### mod_LFO

出现于：test_LFO, update_test_env_timing, update_test_lfo_beep, update_test_lfo_beep_env_trigger, update_test_lfo_timing, update_test_start_vsnd_rand_oneshot, update_test_start_vsnd_tracks。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_center | string | float | 有 | "0.5"; "1" |
| input_frequency | string | float | 有 | "0.75"; "1"; "1.300000" |
| input_scale | string | float | 有 | "0.5" |
| wave_type | string | enum | 有 | "sqr" |

### opvar_get_float

出现于：core_setter_AHR_stack_opvar, csgo_music, dave_test_sb, dave_timer_test, no_scope_inner, soundscape_looping_sound_2D, soundscape_looping_sound_3D, soundscape_opvar_percentage, soundscape_opvar_switch, soundscape_random_sound, soundscape_test_weather, test_get_parent_space, test_ryan_imported, update_test_env_timing, update_test_lfo_beep_env_trigger, update_test_opvar, update_test_opvar_event_max_multi_sequence, update_test_opvar_event_multi_sequence, update_test_opvar_event_sequence, update_test_opvar_stack_sequence, update_test_opvar_types, update_test_simple_public。

已被引用的输出：output, output_opvar_exists。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| array_selection_type | string | 未确认 | 未观察到 | "max_value"; "random_exclusive" |
| check_event_data | string | 未确认 | 未观察到 | "false"; "true" |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_execute | string | float | 有 |  |
| input_field_name | string | string | 有 | "current_track_syncpoint_index"; "float_sequence"; "float_sequence1"; "float_sequence2"; "float_sequence3"; "float_sequence4"; "float_sequence5"; "float_sequence6"；另有 18 项 |
| input_get_ancestor | string | 未确认 | 未观察到 | "true" |
| input_get_parent | string | 未确认 | 未观察到 | "true" |
| input_operator_name | string | string | 有 | ""; "daves_test_opvars"; "looping_soundevent_info"; "oneshot_soundevent_info"; "opvars"; "public"; "scoped_opvars"; "soundscape_soundevent_info"；另有 2 项 |
| input_stack_name | string | string | 有 | ""; "csgo_music_globals"; "diagnostic_globals"; "soundscape_globals" |
| input_use_namespace | string | bool | 有 | "false"; "true" |

### opvar_get_float12

出现于：Diagnostic.TestCurve2d。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| array_selection_type | string | 未确认 | 未观察到 | "index" |
| check_event_data | string | 未确认 | 未观察到 | "true" |
| input_field_name | string | 未确认 | 未观察到 | "curve_6knot_array" |
| input_index | string | 未确认 | 未观察到 | "1" |
| input_operator_name | string | 未确认 | 未观察到 | "public" |

### opvar_get_float3

出现于：soundscape_looping_sound_3D, soundscape_random_sound。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_field_name | string | 未确认 | 未观察到 | "position" |
| input_get_parent | string | 未确认 | 未观察到 | "true" |
| input_operator_name | string | 未确认 | 未观察到 | "looping_soundevent_info"; "oneshot_soundevent_info" |
| input_stack_name | string | 未确认 | 未观察到 | "" |
| input_use_namespace | string | 未确认 | 未观察到 | "true" |

### opvar_get_float8

出现于：Diagnostic.TestCurve2d。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| array_selection_type | string | 未确认 | 未观察到 | "index" |
| check_event_data | string | 未确认 | 未观察到 | "true" |
| input_field_name | string | 未确认 | 未观察到 | "curve_4knot_array" |
| input_index | string | 未确认 | 未观察到 | "1" |
| input_operator_name | string | 未确认 | 未观察到 | "public" |

### opvar_get_info

出现于：core_preload_soundevents, inner_1, test_start_soundevent_loop。

已被引用的输出：output_element_count。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| check_event_data | string | 未确认 | 未观察到 | "true" |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_field_name | string | string | 有 | "soundevent_01"; "soundevents" |
| input_operator_name | string | 未确认 | 未观察到 | "public" |
| input_use_namespace | string | bool | 有 | "false" |

### opvar_get_random_array_index

出现于：csgo_music, update_test_array_index_event_sequence, update_test_array_index_global_stack_sequence。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| array_selection_type | string | enum | 有 | "random_exclusive" |
| check_event_data | string | 未确认 | 未观察到 | "true" |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_field_name | string | 未确认 | 未观察到 | "float_sequence"; "vsnd_files" |
| input_operator_name | string | 未确认 | 未观察到 | "bird_variations"; "public" |
| input_stack_name | string | 未确认 | 未观察到 | "diagnostics_vsnd_lists" |
| input_use_namespace | string | 未确认 | 未观察到 | "0.000000"; "false" |
| weights_field_name | string | 未确认 | 未观察到 | "public.vsnd_weights" |

### opvar_get_sndevt

出现于：test_start_soundevent_loop。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| array_selection_type | string | 未确认 | 未观察到 | "index" |
| check_event_data | string | 未确认 | 未观察到 | "true" |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_field_name | string | 未确认 | 未观察到 | "soundevent_01" |
| input_index | string | 未确认 | 有 |  |
| input_operator_name | string | 未确认 | 未观察到 | "public" |
| input_use_namespace | string | 未确认 | 未观察到 | "false" |

### opvar_get_string

出现于：core_preload_soundevents, inner_1, no_scope_inner, test_1_layer_4, test_2_layer_4, test_ryan_imported。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| array_selection_type | string | 未确认 | 未观察到 | "index" |
| check_event_data | string | 未确认 | 未观察到 | "true" |
| input_execute | int, string | 未确认 | 未观察到 | "1.0"; 1 |
| input_field_name | string | string | 有 | "global_opvar_names"; "local_field"; "parent_string_lookup_2"; "soundevents" |
| input_get_parent | string | 未确认 | 未观察到 | "false" |
| input_index | string | 未确认 | 有 | "0" |
| input_operator_name | string | 未确认 | 未观察到 | "public" |
| input_use_namespace | string | bool | 有 | "false"; "true" |

### opvar_get_vsnd

出现于：base_event_multiple_vsnd_files, core_simple_2d, core_simple_3d, csgo_ambient, csgo_mega, csgo_music, csgo_surf, soundscape_2d_sound, soundscape_3d_sound, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_5_layer_2, test_vmix_vsnd_info, update_test_opvar_global_stack_sequence, update_test_start_event_vsnd_rand_oneshot, update_test_start_event_vsnd_rand_weighted_oneshot, update_test_start_stack_vsnd_rand_oneshot, update_test_start_vsnd_rand_oneshot, update_test_vsnd_envelope, vsnd_base_stack。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| array_selection_type | string | 未确认 | 未观察到 | "forward"; "index"; "random"; "random_exclusive"; "random_weighted" |
| check_event_data | string | 未确认 | 未观察到 | "true" |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_execute | string | 未确认 | 未观察到 | "1.0" |
| input_field_name | string | string | 有 | "vsnd_files"; "vsnd_files_1"; "vsnd_files_2"; "vsnd_files_3"; "vsnd_files_4"; "vsnd_files_track_01" |
| input_index | string | 未确认 | 有 | "0" |
| input_operator_name | string | string | 有 | "bird_variations"; "public" |
| input_stack_name | string | string | 有 | "diagnostics_vsnd_lists" |
| input_use_namespace | string | 未确认 | 未观察到 | "false" |
| weights_field_name | string | 未确认 | 未观察到 | "public.weights" |

### opvar_increment_float

出现于：diagnostic.timed_soundevent, update_test_array_index_event_increment, update_test_array_index_stack_increment, update_test_opvar。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| array_selection_type | string | 未确认 | 未观察到 | "index" |
| check_event_data | string | 未确认 | 未观察到 | "false"; "true" |
| input | string | 未确认 | 未观察到 | "1.000000"; "10" |
| input_execute | string | 未确认 | 有 |  |
| input_field_name | string | 未确认 | 未观察到 | "count"; "float_sequence"; "test_float" |
| input_operator_name | string | 未确认 | 未观察到 | "public"; "test_opvars" |
| input_stack_name | string | 未确认 | 未观察到 | "diagnostic_globals" |
| input_use_namespace | string | 未确认 | 未观察到 | "0.000000" |

### opvar_set_float

出现于：core_doppler, core_max_multiple, core_setter_AHR_stack_opvar, core_setter_curve_stack_opvar, core_setter_stack_opvar, csgo_music, dave_sb_bang, dave_timer_test_reset, dave_timer_test_run, dave_timer_test_stop, dave_timer_test_stop_reset, no_scope_inner, soundscape_opvar_percentage, soundscape_opvar_switch, soundscape_play_burst, soundscape_play_random, soundscape_scalebang, test_ryan_imported, update_test_env_timing, update_test_lfo_beep_env_trigger, update_test_opvar, update_test_opvar_types, util_timer。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| check_event_data | string | 未确认 | 未观察到 | "false" |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "0"; "true" |
| input | string | float | 有 | "0.000000"; "1.000000"; "1111"; "200.0"; "6"; "666"; "6666"; "999" |
| input_execute | string | bool, float | 有 | "1.000000" |
| input_field_name | string | string | 有 | "cached_time"; "current_time"; "current_track_syncpoint_index"; "last_lfo_value"; "need_random_pick"; "output"; "output_doppler_amount"; "output_float"；另有 15 项 |
| input_get_ancestor | string | 未确认 | 未观察到 | "true" |
| input_get_parent | string | 未确认 | 未观察到 | "true" |
| input_index | string | 未确认 | 未观察到 | "0" |
| input_operator_name | string | string | 有 | ""; "daves_test_opvars"; "opvars"; "private_stack_opvars"; "public"; "scoped_opvars"; "test_opvars"; "update_test_opvar_null" |
| input_stack_name | string | string | 有 | ""; "csgo_music_globals"; "diagnostic_globals"; "soundscape_globals" |
| input_use_namespace | string | bool | 有 | "false"; "true" |

### orient_vector_to_entity

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_entity_index | string | 未确认 | 有 |  |
| input_use_entity | string | bool | 有 |  |
| input_vector | string | float3 | 有 |  |

### sampler_event

出现于：core_sampler_event。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_data1 | string | float | 有 |  |
| input_data2 | string | float | 有 |  |
| input_event_type | string | float | 有 |  |
| input_sampler | string | string | 有 |  |
| input_start | string | 未确认 | 未观察到 | "1" |

### sos_goto

出现于：core_distance_limiter, core_preload_soundevents, core_volume_limiter, csgo_music, diagnostic.start_n_soundevents, test_goto_exit, test_goto_loop_head, test_goto_loop_operator, test_goto_namespace_operator_import, test_start_soundevent_loop。

已被引用的输出：output_goto_count。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_execute | int, string | 未确认 | 有 | "0.000000"; "1.000000"; 1 |
| input_goto_end | string | 未确认 | 未观察到 | "0.000000"; "1.0"; "true" |
| input_goto_head | string | 未确认 | 未观察到 | "1"; "true" |
| input_goto_operator | string | 未确认 | 未观察到 | "get_soundevent"; "get_soundevent_01"; "if_less_than_3"; "target_op" |
| input_max_loop_count | string | 未确认 | 有 |  |
| use_local_namespace | string | 未确认 | 未观察到 | "true" |

### sos_import_stack

出现于：child_stack, core_import_test_import_scope, core_sampler_base, core_setter_AHR_game_volume, core_setter_AHR_mixgraph_input, core_setter_AHR_mixlayer_amount, core_setter_AHR_stack_opvar, core_setter_curve_mixgraph_input, core_setter_curve_mixlayer_amount, core_setter_curve_mixlayer_trigger_amount, core_setter_curve_stack_opvar, core_setter_ramp_to_value_mixgraph_input, core_setter_ramp_to_value_mixlayer_amount, core_setter_ramp_to_value_stack_opvar, curve_test_multi_import, dave_test_sb, dave_test_soundscapes, dave_timer_test, diagnostic.self_exciting_gallery, diagnostic.timed_beeper, example_start_oneshot_import_test, example_timetriggered_simple_oneshot, inner_2, no_scope_main, no_scope_outer, outer, outer_multi, soundscape_2rand_1loop, soundscape_3d_sound, soundscape_looping_sound_2D, soundscape_looping_sound_3D, soundscape_play_burst, soundscape_play_looping, soundscape_play_random, soundscape_random_sound, soundscape_scalebang, soundscape_test_play_soundscape, soundscape_test_weather, src1_3d, src1_soundscape_3d, test_1_layer_1, test_1_layer_2, test_1_layer_3, test_2_layer_1, test_2_layer_2, test_2_layer_3, test_3_layer_1, test_3_layer_2, test_3_layer_3, test_5_layer_0, test_5_layer_1, test_beep_on_track, test_goto_namespace_operator, test_import_get_parent_space, test_import_random_multiple, test_ryan_outer, test_soundevent_control_lfo_stop_at_time, test_vsnd_on_track, test_vsnd_on_track2, update_test_import_op, update_test_simple_import_op, update_test_simple_nest_import_op1, update_test_simple_nest_import_op2, update_test_simple_nest_import_op3, update_test_simple_nest_import_op4, update_test_simple_serial_import_op, update_test_simple_serial_import_op2。

已被引用的输出：output_float, output_time。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| auto_connect_field_scope | string | 未确认 | 未观察到 | "core_import_test_parent"; "import_curve_test_01_01"; "import_curve_test_01_02"; "import_parent_field"; "import_parent_field_2"; "inner_2_1"; "inner_2_2"; "no_scope_inner"；另有 6 项 |
| auto_connect_public_fields | string | 未确认 | 未观察到 | "true" |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "0"; "0.000000" |
| import_stack | string | 未确认 | 未观察到 | "core_distance_limiter"; "core_import_test_parent1"; "core_setter_AHR_base"; "core_setter_curve_base"; "core_setter_mixgraph_input"; "core_setter_mixlayer_amount"; "core_setter_ramp_to_value_base"; "core_setter_stack_opvar"；另有 43 项 |
| input_execute | string | float | 有 | "0.000000"; "1.000000" |

### sos_set_builtins

出现于：csgo_ambient, csgo_mega, csgo_movie, csgo_music, csgo_surf, csgo_voip, test_vmix_8track, test_vmix_voice_sends。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | string | float | 有 |  |
| input_voicegraph | string | string | 有 | "csgo_dsp_bypass"; "csgo_movie"; "csgo_music"; "csgo_voice_main"; "csgo_voip" |

### sos_set_voice_position

出现于：csgo_ambient, csgo_mega, csgo_surf。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_position | string | 未确认 | 有 |  |

### sound_area_contains_point

出现于：Diagnostic.test_sound_area。

已被引用的输出：output_point_in_sound_area, output_sound_areas_exist。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| area_type | string | 未确认 | 未观察到 | "any"; "ice_sphere" |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_execute | string | 未确认 | 未观察到 | "1.0" |
| input_position | string | 未确认 | 有 |  |

### sound_area_register

出现于：Diagnostic.register_sound_area。

已被引用的输出：output_guid。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| area_shape | string | 未确认 | 未观察到 | "sphere" |
| area_type | string | 未确认 | 未观察到 | "ice_sphere"; "time_sphere" |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_position | array | 未确认 | 未观察到 |  |
| input_radius | float | 未确认 | 未观察到 | 200.0; 250.0; 350.0 |

### sound_area_unregister

出现于：Diagnostic.register_sound_area。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_execute | string | 未确认 | 有 |  |
| input_guid | string | 未确认 | 有 |  |

### soundevent_block

出现于：core_sampler_base, core_soundevent_blocker, csgo_ambient, csgo_mega, csgo_music, csgo_surf, test_soundevent_block。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| allow_empty_match | float | 未确认 | 未观察到 | 1.0 |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_active | int | 未确认 | 未观察到 | 1 |
| input_distance | string | float | 有 |  |
| input_duration | string | float | 有 | "0.100000" |
| input_entity_index | string | 未确认 | 有 | "0"; "666" |
| input_event_type | string | float | 有 | "3" |
| input_execute | string | bool, float | 有 | "1.000000" |
| input_position | string | 未确认 | 有 |  |
| is_untimed | int, string | 未确认 | 未观察到 | "0"; "1"; 1 |
| match_event_name | string | string | 有 | "Music.LostRound."; "Music.WonRound." |
| match_substring | string | float | 有 | "true" |
| match_this_event | string | 未确认 | 未观察到 | "1"; "true" |

### soundevent_block_test

出现于：core_sampler_base, csgo_ambient, csgo_mega, csgo_music, csgo_surf, test_soundevent_block。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| event_name | string | string | 有 |  |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_entity_index | string | 未确认 | 有 | "666" |
| input_event_type | string | float | 有 | "3" |
| input_execute | string | bool | 有 |  |
| input_position | string | 未确认 | 有 |  |
| match_this_event | string | 未确认 | 未观察到 | "1"; "true" |

### soundevent_control

出现于：Diagnostic.register_sound_area, Diagnostic.test_mixgraph_output, Diagnostic.test_threshold_logic, Diagnostic.test_wait_time, Diagnostic.test_wait_time_test, core_global_stack, core_null_timed, core_sampler_base, core_setter_AHR_base, core_setter_curve_base, core_setter_ramp_to_value_base, core_soundevent_blocker, core_stop_all_soundevents, core_stop_at_time, csgo_ambient, csgo_mega, csgo_music, dave_sb_bang, dave_timer_test, diagnostic.animate_float3_gallery, diagnostic.self_exciting_gallery, diagnostic.timed_beeper, diagnostic.timed_silence, diagnostic.timed_soundevent, diagnostic.usable_float_range, soundscape_play_burst, soundscape_play_looping, soundscape_play_random, soundscape_play_soundscape, soundscape_scalebang, test_LFO, test_eval, test_groups_branch_string, test_groups_branch_string_variables, test_groups_entindex_invert, test_groups_envelope, test_groups_opvar_invert, test_groups_persist, test_groups_read_envelope, test_groups_subname_invert, test_inverse_vec3, test_soundevent_group_simple, test_soundevent_group_simple_opvar, test_soundevent_groups, test_start_soundevent, test_timers, test_usable_float_range, update_test_array_index_event_increment, update_test_array_index_event_sequence, update_test_array_index_global_stack_sequence, update_test_array_index_stack_increment, update_test_env_beep_mixlayer_timing, update_test_env_beep_timing, update_test_lfo_beep, update_test_lfo_beep_env_trigger, update_test_lfo_beep_timing, update_test_listener_velocity, update_test_opvar_event_sequence, update_test_opvar_global_stack_sequence, update_test_opvar_stack_sequence, update_test_start_vsnd_lfo, update_test_start_vsnd_tracks。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_add_dependent | string | float | 有 | "1"; "1.000000" |
| input_clear_dependencies | string | 未确认 | 有 |  |
| input_execute | string | bool | 有 | "1" |
| input_stop | string | 未确认 | 有 | "1.000000" |
| input_stop_at_time | string | float | 有 | "3" |
| input_wait_time | int, string | 未确认 | 有 | 5 |

### soundevent_get_info

出现于：Diagnostic.register_sound_area, Diagnostic.test_mixgraph_output, Diagnostic.test_threshold_logic, Diagnostic.test_wait_time, Diagnostic.test_wait_time_test, beatpattern_4x4, container_arg_test, container_env_test, container_oneshot_test, core_beatpattern_start_pattern, core_null_timed, core_sampler_base, core_set_playerdsp, core_setter_AHR_base, core_setter_curve_base, core_setter_ramp_to_value_base, core_simple_2d, core_simple_3d, core_soundevent_blocker, core_stop_at_time, core_voip, csgo_ambient, csgo_mega, csgo_movie, csgo_music, csgo_surf, csgo_voip, dave_sb_bang, dave_timer_test, diagnostic.animate_float3_gallery, diagnostic.self_exciting_gallery, diagnostic.timed_beeper, diagnostic.timed_silence, diagnostic.timed_soundevent, diagnostic.usable_float_range, soundscape_2d_sound, soundscape_3d_sound, soundscape_play_looping, soundscape_play_random, soundscape_play_soundscape, soundscape_scalebang, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_LFO, test_beep_on_track, test_eval, test_groups_branch_string, test_groups_branch_string_variables, test_groups_entindex_invert, test_groups_envelope, test_groups_opvar_invert, test_groups_persist, test_groups_read_envelope, test_groups_subname_invert, test_inverse_vec3, test_soundevent_group_simple, test_soundevent_group_simple_opvar, test_soundevent_groups, test_soundevent_start_lfo, test_soundevent_start_multi, test_start_soundevent, test_timers, test_usable_float_range, test_vmix_8track, test_vmix_voice_sends, test_vsnd_loop_xfade, update_test_array_index_event_increment, update_test_array_index_event_sequence, update_test_array_index_global_stack_sequence, update_test_array_index_stack_increment, update_test_env_beep_mixlayer_timing, update_test_env_beep_timing, update_test_env_timing, update_test_lfo_beep, update_test_lfo_beep_env_trigger, update_test_lfo_beep_timing, update_test_lfo_timing, update_test_mixgroup_timing, update_test_opvar_event_sequence, update_test_opvar_global_stack_sequence, update_test_opvar_stack_sequence, update_test_start_event_vsnd_rand_oneshot, update_test_start_event_vsnd_rand_weighted_oneshot, update_test_start_stack_vsnd_rand_oneshot, update_test_start_vsnd_lfo, update_test_start_vsnd_rand_oneshot, update_test_start_vsnd_tracks, update_test_vsnd_envelope, update_test_vsnd_simple_loop, util_timer。

已被引用的输出：output_elapsed_time, output_entity_index, output_host_elapsed_time, output_stop_elapsed_time, output_stopped, output_unstopped。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "0" |
| input_execute | string | 未确认 | 未观察到 | "1.000000" |

### soundevent_group_find

出现于：test_groups_read_envelope, test_soundevent_groups。

已被引用的输出：output_result。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_group_name | string | 未确认 | 未观察到 | "branch_eventtype"; "match_all_envelope" |

### soundevent_group_get_float

出现于：test_groups_branch_string_variables, test_groups_envelope, test_groups_read_envelope。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false"; "true" |
| input_group_result | string | 未确认 | 有 |  |
| input_name | string | 未确认 | 未观察到 | "envelope_result"; "grp1_var1"; "grp1_var2" |

### soundevent_group_info

出现于：test_soundevent_groups。

已被引用的输出：output_match_count, output_match_time。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_group_result | string | 未确认 | 有 |  |

### soundevent_group_join

出现于：csgo_music, test_groups_branch_string, test_groups_branch_string_variables, test_groups_entindex_invert, test_groups_envelope, test_groups_opvar_invert, test_groups_persist, test_groups_subname_invert, test_soundevent_group_simple_opvar, test_soundevent_groups。

已被引用的输出：output_result。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_entity_index | string | float | 有 |  |
| input_group_name | string | 未确认 | 未观察到 | "branch_eventtype"; "branch_opvar_string"; "match_all"; "match_all_count_envelope"; "match_all_persists"; "match_entityindex"; "match_eventtype"; "match_opvar_invert"；另有 3 项 |
| input_invert_match | string | float | 有 |  |
| input_lifespan_time | int, string | float | 有 | 4 |
| input_match_float | string | float | 有 |  |
| input_match_string | string | string | 有 | "branch1"; "branch2" |

### soundevent_group_set_float

出现于：test_groups_branch_string_variables。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input | string | 未确认 | 未观察到 | "1"; "1.1"; "2.2" |
| input_group_result | string | 未确认 | 有 |  |
| input_name | string | 未确认 | 未观察到 | "grp1_var1"; "grp1_var2" |

### soundevent_group_stop

出现于：csgo_music, test_group_stop。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_execute | string | bool | 有 |  |
| input_group_name | string | 未确认 | 未观察到 | "non_mvp_music_group"; "static_group3" |

### soundevent_limiter

出现于：core_sampler_base, core_stop_soundevents, csgo_ambient, csgo_mega, csgo_music, csgo_surf, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_soundevent_limiter_lfo。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_execute | string | bool, float | 有 |  |
| input_max_events | string | float | 有 | "0" |
| invert_match | string | bool, float | 有 |  |
| invert_string_match | string | 未确认 | 未观察到 | "true" |
| match_duration_type | string | 未确认 | 未观察到 | "less_than_or_equal" |
| match_entity | string | float | 有 | "1"; "false" |
| match_event_duration | string | 未确认 | 未观察到 | "0.01" |
| match_event_name | string | string | 有 | "Music."; "Music.BombPlanted"; "Music.GotHostage"; "Music.LoadingScreen"; "Music.LostRound"; "Music.MVPAnthem"; "Music.MatchEnd"; "Music.Selection"；另有 4 项 |
| match_event_type | string | float | 有 |  |
| match_substring | string | bool, float | 有 | "0.000000"; "true" |
| match_this_event | string | float | 有 | "1"; "false" |
| stop_oldest | string | 未确认 | 未观察到 | "1" |

### soundevent_param

出现于：test_soundevent_start_oneshot。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_guid | string | 未确认 | 有 |  |

### soundevent_parent_info

出现于：csgo_ambient。

已被引用的输出：output_parent_stopped。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | string | bool | 有 |  |

### soundevent_pause

出现于：core_pause_soundevent。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_event_guid | string | int | 有 |  |
| input_pause | string | bool | 有 |  |
| invert_match | string | bool | 有 |  |
| match_entity | string | float | 有 |  |
| match_event_name | string | string | 有 |  |
| match_event_type | string | float | 有 |  |
| match_substring | string | bool | 有 |  |

### soundevent_start

出现于：beatpattern_4x4, core_sampler_base, csgo_ambient, csgo_mega, csgo_music, diagnostic.start_n_soundevents, diagnostic.timed_soundevent, soundscape_play_burst, soundscape_play_looping, soundscape_play_random, soundscape_play_soundscape, test_soundevent_start_lfo, test_soundevent_start_multi, test_soundevent_start_oneshot, test_soundevent_start_opvar_get_ancestor, test_soundevent_start_opvar_get_parent, test_soundevent_start_opvar_get_parent_space, test_soundevent_start_random_multiple, test_start_soundevent, test_start_soundevent_loop, update_test_env_beep_mixlayer_timing, update_test_env_beep_timing, update_test_lfo_beep_timing。

已被引用的输出：output_current_guid。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "false"; "true" |
| input_execute | int, string | bool | 有 | "1"; 1 |
| input_spawn_oneshots | string | 未确认 | 未观察到 | "0"; "0.000000"; "1"; "1.000000" |
| input_start | int, string | 未确认 | 有 | "1"; "1.000000"; 1 |
| input_update_opvar1 | string | 未确认 | 未观察到 | "1" |
| input_update_opvar2 | string | 未确认 | 未观察到 | "0" |
| input_update_opvar3 | string | 未确认 | 未观察到 | "1" |
| input_update_opvar4 | string | 未确认 | 未观察到 | "0" |
| input_update_opvar_args | string | 未确认 | 未观察到 | "true" |
| input_use_parent_seed | string | 未确认 | 未观察到 | "0"; "1.000000" |
| pass_opvar_args | float, string | 未确认 | 未观察到 | "true"; 1.0 |
| retrigger_current_event | string | 未确认 | 未观察到 | "true" |
| soundevent_name | string | sndevt, string | 有 | "Diagnostic.1k_short"; "Diagnostic.2k_short"; "Diagnostic.core_start_simple_oneshot"; "Diagnostic.test_get_parent_space"; "Diagnostic.test_random_multiple"; "Diagnostic.test_soundevent_start_opvar_get_parent"; "Diagnostic.test_stop_soundevents_lfo_at_time"; "Diagnostic.test_timers"；另有 8 项 |
| spawn_orphans | int, string | 未确认 | 未观察到 | "0"; "true"; 1 |

### soundevent_stop_all

出现于：core_stop_all_soundevents。

已被引用的输出：output_waiting。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| exclude_group_name | string | string | 有 |  |
| input_stop_immediate | string | float | 有 |  |
| input_wait_time | string | float | 有 |  |
| voice_layer | string | enum | 有 |  |

### soundeventdata_start

出现于：csgo_ambient, csgo_mega, csgo_surf。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| check_event_data | string | 未确认 | 未观察到 | "true" |
| input_execute | string | 未确认 | 有 |  |
| input_field_name | string | 未确认 | 未观察到 | "soundevent_01" |
| input_operator_name | string | 未确认 | 未观察到 | "public" |
| input_start | string | 未确认 | 有 |  |
| pass_opvar_args | string | bool | 有 |  |

### soundmixer_get_current_dsp_effect

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output_effect_name。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_effect | string | 未确认 | 未观察到 | "RoomDSP" |
| input_execute | string | 未确认 | 未观察到 | "1" |

### soundmixer_get_dsp_mixgroup_modifier

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_distance | string | 未确认 | 有 |  |
| input_effect_name | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_mixgroup | string | string | 有 |  |

### soundmixer_get_mixgroup

出现于：core_sampler_base, core_setter_curve_mixlayer_trigger_amount, csgo_ambient, csgo_mega, csgo_music, csgo_surf, csgo_voip, soundscape_2d_sound, soundscape_3d_sound, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, update_test_lfo_beep_env_trigger, update_test_mixer, update_test_mixgroup_timing。

已被引用的输出：output_dsp, output_level, output_mixgroups, output_volume。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_class_name | string | 未确认 | 有 |  |
| input_event_type | string | float | 有 |  |
| input_is_player | string | 未确认 | 有 | "0.000000" |
| input_soundlevel | string | 未确认 | 有 | "65.000000" |
| input_vsnd | string | 未确认 | 有 |  |
| mixgroup | string | mixgroup, string | 有 | "bullethit"; "layer_amount_target"; "layer_amount_trigger"; "voip" |

### soundmixer_get_mixlayer_amount

出现于：core_setter_AHR_mixlayer_amount。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | bool | 未确认 | 未观察到 | true |
| mixlayer | string | string | 有 |  |

### soundmixer_get_source_dsp_preset

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output, output_mix。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| blend_ratio | string | float | 有 |  |
| input_distance | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_listener_effect_name | string | 未确认 | 有 |  |
| input_mixgroup | string | string | 有 |  |

### soundmixer_set_mixlayer

出现于：update_test_mixlayer。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| field | string | 未确认 | 未观察到 | "dsp" |
| mixgroup | string | 未确认 | 未观察到 | "All" |
| mixlayer | string | 未确认 | 未观察到 | "All" |

### soundmixer_set_mixlayer_amount

出现于：core_setter_AHR_mixlayer_amount, core_setter_curve_mixlayer_amount, core_setter_mixlayer_amount, csgo_ambient, csgo_mega, csgo_music, csgo_surf。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | float | 有 |  |
| input_execute | string | bool | 有 |  |
| mixlayer | string | string | 有 |  |

### soundmixer_set_trigger

出现于：core_sampler_base, core_setter_curve_mixlayer_trigger_amount, csgo_ambient, csgo_mega, csgo_music, csgo_surf, csgo_voip, soundscape_2d_sound, soundscape_3d_sound, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, update_test_lfo_beep_env_trigger。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | string | 未确认 | 有 |  |
| input_mixgroups | string | 未确认 | 有 |  |
| input_trigger | string | 未确认 | 有 |  |

### soundmixer_set_vmix

出现于：csgo_voip。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_mixgroups | string | 未确认 | 有 |  |

### steamaudio_compute_customdata

出现于：csgo_ambient, csgo_mega, csgo_surf。

已被引用的输出：output_occlusion_value。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input_compute_occlusion | string | 未确认 | 未观察到 | "true" |
| input_execute | string | 未确认 | 有 |  |
| input_listener_position | string | 未确认 | 有 |  |
| input_query_position | string | 未确认 | 有 |  |

### track_queue

出现于：csgo_music, test_beep_on_track, test_vsnd_on_track, test_vsnd_on_track2。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| block_equal_priority | string | float | 有 |  |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_execute | string | bool | 有 |  |
| input_priority | string | float | 有 |  |
| input_sync_end_point_field_name | string | 未确认 | 有 |  |
| input_sync_field_name | string | string | 有 |  |
| input_sync_start_point_field_name | string | 未确认 | 有 |  |
| input_sync_track_name | string | string | 有 | "main" |
| input_track_name | string | string | 有 | "main" |
| priority_override | string | bool, float | 有 |  |
| use_queue | string | float | 有 | "1" |
| wait_for_track | string | float | 有 |  |

### track_stop

出现于：test_stop_track。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_track_name | string | string | 有 |  |
| stop_queue | string | 未确认 | 未观察到 | "1" |

### util_draw_debug_sphere

出现于：diagnostic.animate_float3_gallery, diagnostic.self_exciting_column。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| detail_label_1 | string | 未确认 | 未观察到 | "excite" |
| detail_label_2 | string | 未确认 | 未观察到 | "gap" |
| detail_value_1 | string | 未确认 | 有 |  |
| detail_value_2 | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 有 | "1" |
| input_label | string | string | 有 | "bezier"; "bezier_bounce"; "bezier_even"; "bezier_even_bounce"; "circle"; "circle_bounce"; "lerp"; "lerp_bounce"；另有 6 项 |
| input_position | string | 未确认 | 有 |  |
| input_radius | string | float | 有 |  |
| input_rgb_color | string | float3 | 有 | "[120, 200, 120]"; "[160, 110, 255]"; "[200, 200, 120]"; "[200, 80, 255]"; "[230, 230, 230]"; "[230, 60, 20]"; "[255, 140, 0]"; "[255, 190, 90]"；另有 6 项 |
| input_show_detailed_info | string | 未确认 | 未观察到 | "1" |

### util_draw_radius

出现于：test_entity_aabb, test_inverse_vec3。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_name | string | 未确认 | 未观察到 | "max"; "min"; "result"; "src" |
| input_position | string | float3 | 有 |  |
| input_radius_max | string | 未确认 | 未观察到 | "10.000000" |
| input_radius_min | string | 未确认 | 未观察到 | "1.000000"; "10.000000" |

### util_elements_float16

出现于：test_harmonic_tools。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | 未确认 | 有 |  |

### util_elements_float3

出现于：csgo_ambient, csgo_mega, csgo_surf, dave_test_floatness。

已被引用的输出：output_0, output_1, output_2。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | float3 | 有 |  |
| input_execute | string | bool | 有 | "1.000000" |

### util_float_to_speakers

出现于：container_arg_test, container_env_test, container_oneshot_test, core_simple_2d, core_start_oneshot, core_start_simple_oneshot, core_valve_default, core_voip, csgo_ambient, csgo_mega, csgo_movie, csgo_music, csgo_surf, csgo_voip, soundscape_2d_sound, soundscape_3d_sound, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_system_properties, test_vmix_8track, test_vmix_voice_sends, test_vmix_vsnd_info, update_test_start_vsnd_lfo。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false"; "true" |
| input | string | float | 有 | "1"; "1.0" |

### util_interval_timer

出现于：csgo_ambient, csgo_mega, csgo_surf, diagnostic.self_exciting_column, diagnostic.timed_beeper, diagnostic.timed_soundevent, diagnostic.usable_float_range, test_timers。

已被引用的输出：output, output_interval_elapsed, output_interval_not_elapsed。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_interval | string | float | 有 | "100" |
| input_start | string | 未确认 | 有 | "1"; "1.000000" |
| input_start_resets | string | 未确认 | 未观察到 | "1" |
| input_stop_at_interval | string | 未确认 | 未观察到 | "1" |
| output_interval_elapsed | string | 未确认 | 未观察到 | "1.000000" |

### util_null

出现于：Diagnostic.GetMixGraphInput, Diagnostic.TestCrossfade, Diagnostic.TestCurve2d, base_event_multiple_vsnd_files, beatpattern_4x4, child_stack, container_arg_test, container_env_test, container_oneshot_test, core_beatpattern_start_pattern, core_distance_limiter, core_doppler, core_empty, core_import_test_import, core_import_test_import_recursive, core_import_test_import_recursive_scope, core_import_test_import_scope, core_import_test_parent1, core_import_test_parent2, core_import_test_parent3, core_max_multiple, core_null_timed, core_pause_soundevent, core_preload_soundevents, core_sampler_base, core_sampler_event, core_set_playerdsp, core_setter_AHR_base, core_setter_AHR_game_volume, core_setter_AHR_mixgraph_input, core_setter_AHR_mixlayer_amount, core_setter_AHR_stack_opvar, core_setter_curve_base, core_setter_curve_mixgraph_input, core_setter_curve_mixlayer_amount, core_setter_curve_mixlayer_trigger_amount, core_setter_curve_stack_opvar, core_setter_mixgraph_input, core_setter_mixlayer_amount, core_setter_ramp_to_value_base, core_setter_ramp_to_value_mixgraph_input, core_setter_ramp_to_value_mixlayer_amount, core_setter_ramp_to_value_stack_opvar, core_setter_stack_opvar, core_simple_2d, core_simple_3d, core_soundevent_blocker, core_start_oneshot, core_start_simple_oneshot, core_stop_all_soundevents, core_stop_at_time, core_stop_soundevents, core_valve_default, core_voip, core_volume_limiter, csgo_ambient, csgo_mega, csgo_movie, csgo_music, csgo_music_globals, csgo_surf, csgo_voip, curve_test_01, curve_test_multi_import, dave_sb_bang, dave_test_floatness, dave_test_random_pos, dave_test_sb, dave_test_soundscapes, dave_timer_test, dave_timer_test_reset, dave_timer_test_run, dave_timer_test_stop, dave_timer_test_stop_reset, diagnostic.animate_float3_gallery, diagnostic.self_exciting_column, diagnostic.self_exciting_gallery, diagnostic.start_n_soundevents, diagnostic.timed_beeper, diagnostic.timed_silence, diagnostic.timed_soundevent, diagnostic.usable_float_range, diagnostic_globals, diagnostics_arrays, diagnostics_vsnd_lists, example_start_oneshot_import_test, example_timetriggered_simple_oneshot, inner_1, inner_2, no_scope_inner, no_scope_main, no_scope_outer, outer, outer_multi, parent_stack, parent_stack_2, soundscape_2d_sound, soundscape_2rand_1loop, soundscape_3d_sound, soundscape_globals, soundscape_looping_sound_2D, soundscape_looping_sound_3D, soundscape_opvar_percentage, soundscape_opvar_switch, soundscape_play_burst, soundscape_play_looping, soundscape_play_random, soundscape_play_soundscape, soundscape_random_sound, soundscape_scalebang, soundscape_test_play_soundscape, soundscape_test_weather, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_1_layer_1, test_1_layer_2, test_1_layer_3, test_1_layer_4, test_2_layer_1, test_2_layer_2, test_2_layer_3, test_2_layer_4, test_3_layer_1, test_3_layer_2, test_3_layer_3, test_3_layer_4, test_5_layer_0, test_5_layer_1, test_5_layer_2, test_LFO, test_beep_on_track, test_empty, test_enum_opvar, test_eval, test_groups_branch_string, test_groups_branch_string_variables, test_groups_entindex_invert, test_groups_envelope, test_groups_opvar_invert, test_groups_persist, test_groups_read_envelope, test_groups_subname_invert, test_harmonic_tools, test_import_get_parent_space, test_import_opvar_field, test_inverse_vec3, test_ryan_imported, test_ryan_outer, test_simple_public_field, test_soundevent_block, test_soundevent_field_override, test_soundevent_groups, test_soundevent_limiter_lfo, test_soundevent_start_lfo, test_soundevent_start_multi, test_soundevent_start_oneshot, test_soundevent_start_opvar_get_ancestor, test_soundevent_start_opvar_get_parent, test_soundevent_start_opvar_get_parent_space, test_start_soundevent_loop, test_stop_track, test_switch_case_12, test_system_properties, test_usable_float_range, test_vmix_8track, test_vmix_voice_sends, test_vmix_vsnd_info, test_vsnd_loop_xfade, test_vsnd_on_track, test_vsnd_on_track2, update_test_array_index_event_increment, update_test_array_index_event_sequence, update_test_array_index_stack_increment, update_test_env_timing, update_test_import_op, update_test_lfo_beep, update_test_lfo_beep_env_trigger, update_test_lfo_timing, update_test_mixgroup_timing, update_test_opvar, update_test_opvar_event_max_multi_sequence, update_test_opvar_event_multi_sequence, update_test_opvar_event_sequence, update_test_opvar_stack_sequence, update_test_opvar_types, update_test_overrides, update_test_simple_import_op, update_test_simple_nest_import_op1, update_test_simple_nest_import_op2, update_test_simple_nest_import_op3, update_test_simple_nest_import_op4, update_test_simple_public, update_test_simple_serial_import_op, update_test_simple_serial_import_op2, update_test_start_event_vsnd_rand_oneshot, update_test_start_event_vsnd_rand_weighted_oneshot, update_test_start_stack_vsnd_rand_oneshot, update_test_start_vsnd_lfo, update_test_start_vsnd_rand_oneshot, update_test_start_vsnd_tracks, update_test_utils, update_test_vsnd_envelope, update_test_vsnd_simple_loop, util_float3_lerp, util_timer, vsnd_base_stack。

已被引用的输出：output_time。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| error | string | 未确认 | 未观察到 | "0" |
| execute_once | string | 未确认 | 未观察到 | "0"; "0.000000"; "1.000000" |
| input_execute | string | 未确认 | 未观察到 | "0"; "1"; "1.000000" |

### util_pack_float3

出现于：dave_test_floatness, util_float3_lerp。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_0 | string | float | 有 |  |
| input_1 | string | float | 有 |  |
| input_2 | string | float | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1.000000" |

### util_print_float

出现于：Diagnostic.GetMixGraphInput, Diagnostic.TestCrossfade, Diagnostic.TestCurve2d, Diagnostic.test_mixgraph_output, core_doppler, core_import_test_import, core_import_test_import_recursive, core_import_test_import_recursive_scope, core_import_test_import_scope, core_import_test_parent1, core_import_test_parent2, core_import_test_parent3, dave_test_random_pos, diagnostic.timed_soundevent, diagnostic.usable_float_range, parent_stack, parent_stack_2, soundscape_play_burst, soundscape_play_random, soundscape_scalebang, test_LFO, test_goto_exit, test_goto_loop_head, test_goto_loop_operator, test_goto_namespace_operator_import, test_groups_branch_string_variables, test_groups_envelope, test_groups_read_envelope, test_soundevent_group_simple, test_soundevent_groups, test_timers, test_usable_float_range, test_vmix_vsnd_info, update_test_array_index_event_increment, update_test_array_index_event_sequence, update_test_array_index_global_stack_sequence, update_test_array_index_stack_increment, update_test_listener_velocity, update_test_opvar_event_max_multi_sequence, update_test_opvar_event_multi_sequence, update_test_opvar_event_sequence, update_test_opvar_stack_sequence, update_test_opvar_types, update_test_utils, update_test_vsnd_envelope, vsnd_base_stack。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input | string | bool, enum, float | 有 | "0.000000"; "666" |
| input_execute | string | float | 有 | "1"; "1.000000" |

### util_print_float3

出现于：dave_test_random_pos, soundscape_play_random, util_float3_lerp。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 有 | "1.000000" |

### util_print_string

出现于：Diagnostic.test_sound_area, no_scope_inner, soundscape_play_looping, soundscape_play_random, test_1_layer_3, test_2_layer_3, test_3_layer_4, test_ryan_imported。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input | string | string | 有 | ":thumbsup:" |
| input_execute | string | 未确认 | 有 | "1" |

### util_print_vsnd

出现于：base_event_multiple_vsnd_files, test_5_layer_2, update_test_opvar_global_stack_sequence, vsnd_base_stack。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input | string | 未确认 | 有 |  |

### util_timer

出现于：test_timers。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_start | string | 未确认 | 未观察到 | "1" |

### util_timer_ramp

出现于：test_timers。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_duration | string | 未确认 | 未观察到 | "100" |
| input_end_value | string | 未确认 | 未观察到 | "100" |
| input_start | string | 未确认 | 未观察到 | "1" |

### util_usable_float_range

出现于：diagnostic.usable_float_range, test_usable_float_range。

已被引用的输出：output_max, output_min, output_usable_max, output_usable_min。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_percentile_lower | int, string | float | 有 | 5 |
| input_percentile_upper | int, string | float | 有 | 95 |

### vmix_mixgraph_input

出现于：core_set_playerdsp, core_setter_AHR_mixgraph_input, core_setter_curve_mixgraph_input, core_setter_mixgraph_input, update_test_env_timing, update_test_lfo_timing, update_test_mixgroup_timing。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "false" |
| input | string | float | 有 |  |
| input_execute | string | float | 有 |  |
| input_name | string | string | 有 | "AllVoices_amp_volume_input"; "PlayerDSP.mix"; "amped_volume_input" |

### vmix_mixgraph_input_dsp_preset

出现于：core_set_playerdsp, csgo_ambient, csgo_mega, csgo_surf。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_dsp_preset_name | string | dsppreset, string | 有 |  |
| input_execute | string | bool, float | 有 |  |
| input_name | string | 未确认 | 未观察到 | "PlayerDSP"; "RoomDSP" |

### vmix_mixgraph_input_get_float

出现于：Diagnostic.GetMixGraphInput, core_setter_AHR_mixgraph_input。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input_name | string | string | 有 |  |

### vmix_mixgraph_output_float

出现于：Diagnostic.test_mixgraph_output。

已被引用的输出：output。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_name | string | 未确认 | 未观察到 | "main_mix_out" |

### vmix_mixgraph_send

出现于：core_sampler_base, core_voip, csgo_ambient, csgo_mega, csgo_movie, csgo_music, csgo_surf, csgo_voip, test_vmix_voice_sends, test_vsnd_loop_xfade, update_test_env_timing, update_test_lfo_beep, update_test_lfo_beep_env_trigger, update_test_lfo_timing, update_test_mixgroup_timing。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input | string | 未确认 | 有 | "0"; "0.0"; "1"; "1.0"; "1.000000" |
| input_execute | string | float | 有 | "1"; "1.0"; "1.000000" |
| send_type | string | 未确认 | 未观察到 | "facing"; "named" |
| submix_name | string | 未确认 | 未观察到 | "AllVoices"; "Occlusion"; "Reverb"; "VOIP"; "amped"; "amped_buss"; "dsp_bypass"; "ducking_bypass_reverb"；另有 5 项 |

### vmix_preload_soundevent

出现于：core_preload_soundevents。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | int | 未确认 | 未观察到 | 1 |
| input_memory_priority | string | float | 有 |  |
| input_soundevent_name | string | 未确认 | 有 |  |

### vmix_voice_start

出现于：container_arg_test, container_env_test, container_oneshot_test, core_sampler_base, core_simple_2d, core_simple_3d, core_start_oneshot, core_start_simple_oneshot, core_test_sound, core_valve_default, core_voip, csgo_ambient, csgo_mega, csgo_movie, csgo_music, csgo_surf, csgo_voip, group_soundevent_cluster_default_3d_test, soundscape_2d_sound, soundscape_3d_sound, src1_2d, src1_3d, src1_soundscape_2d, src1_soundscape_3d, test_system_properties, test_vmix_8track, test_vmix_voice_sends, test_vmix_vsnd_info, test_vsnd_loop_xfade, update_test_env_timing, update_test_lfo_beep, update_test_lfo_beep_env_trigger, update_test_lfo_timing, update_test_mixgroup_timing, update_test_start_event_vsnd_rand_oneshot, update_test_start_event_vsnd_rand_weighted_oneshot, update_test_start_stack_vsnd_rand_oneshot, update_test_start_vsnd_lfo, update_test_start_vsnd_rand_oneshot, update_test_start_vsnd_tracks, update_test_vsnd_envelope, update_test_vsnd_simple_loop。

已被引用的输出：output_voice_finished。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | bool, string | 未确认 | 未观察到 | "false"; "true"; true |
| input_delay | string | float | 有 | "0.000000" |
| input_execute | string | float | 有 | "1"; "1.0"; "1.000000" |
| input_fade_out | string | float | 有 |  |
| input_max_gain_change_per_second | int | 未确认 | 未观察到 | 87; 96000 |
| input_memory_type | string | float | 有 |  |
| input_pitch | string | float | 有 | "1.0"; "1.000000" |
| input_reset_event_time_on_restart | string | 未确认 | 未观察到 | "0.0" |
| input_restart_preroll | string | 未确认 | 有 |  |
| input_restart_start_time | string | 未确认 | 有 |  |
| input_restart_time | string | float | 有 |  |
| input_should_pause | string | bool | 有 | "0"; "1" |
| input_should_save | string | 未确认 | 未观察到 | "1" |
| input_speaker_volumes | string | 未确认 | 有 | "[ 1, 1,1,1,1,1,1,1]"; "[ 1.0, 1.0, 1.0, 1.0, 1.0, 1.0 ]"; "[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]"; "[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]" |
| input_start | float, string | float | 有 | "1"; 1.0 |
| input_start1 | string | 未确认 | 未观察到 | "1"; "1.0"; "1.000000" |
| input_start2 | string | 未确认 | 未观察到 | "0.000000" |
| input_start3 | string | 未确认 | 未观察到 | "0.000000" |
| input_start4 | string | 未确认 | 未观察到 | "0.000000" |
| input_start5 | string | 未确认 | 未观察到 | "0.000000" |
| input_start6 | string | 未确认 | 未观察到 | "0.000000" |
| input_start7 | string | 未确认 | 未观察到 | "0.000000" |
| input_start8 | string | 未确认 | 未观察到 | "0.000000" |
| input_time_scale | string | 未确认 | 有 |  |
| input_track1 | string | string | 有 | "track_01" |
| input_track2 | string | string | 有 | "track_02" |
| input_track3 | string | string | 有 | "track_03" |
| input_track4 | string | string | 有 | "track_04" |
| input_track5 | string | string | 有 | "track_05" |
| input_track6 | string | string | 有 | "track_06" |
| input_track7 | string | string | 有 | "track_07" |
| input_track8 | string | string | 有 | "track_08" |
| input_vsnd1 | string | vsnd | 有 | "sounds/ambient/abstract/amb_gen_low_metallic_05.vsnd"; "sounds/diagnostics/beep.vsnd"; "sounds/diagnostics/bell.vsnd"; "sounds/diagnostics/sin_1024hz_-3db_lp.vsnd"; "sounds/diagnostics/sin_1k_0p005_lp-01.vsnd" |
| input_vsnd2 | string | vsnd | 有 |  |
| input_vsnd3 | string | vsnd | 有 |  |
| input_vsnd4 | string | vsnd | 有 |  |
| input_vsnd5 | string | vsnd | 有 |  |
| input_vsnd6 | string | vsnd | 有 |  |
| input_vsnd7 | string | vsnd | 有 |  |
| input_vsnd8 | string | vsnd | 有 |  |

### vmix_voice_time

出现于：container_env_test。

已被引用的输出：output_voice_seek_time。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_execute | string | 未确认 | 有 |  |

### vmix_voicegraph_input

出现于：csgo_ambient, csgo_mega, csgo_surf, csgo_voip, test_vmix_8track。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| execute_once | string | 未确认 | 未观察到 | "true" |
| input | string | bool, float | 有 | "0" |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_name | string | 未确认 | 未观察到 | "ang_y"; "distance_effect_mix"; "eq_occlusion"; "eq_occlusion_mix"; "player_voip_volume"; "source_wet"; "steamaudio_relative_position"; "unfiltered_stereo"；另有 3 项 |

### vmix_voicegraph_name_input

出现于：csgo_ambient, csgo_mega, csgo_surf。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_dsp_preset_name | string | 未确认 | 有 |  |
| input_execute | string | 未确认 | 未观察到 | "1" |
| input_name | string | 未确认 | 未观察到 | "source_effect" |

### vmix_vsnd_info

出现于：container_env_test, csgo_ambient, csgo_mega, csgo_music, csgo_surf, test_vmix_vsnd_info。

已被引用的输出：output_duration, output_has_envelope, output_is_looped, output_is_valid。输出类型尚未从 DLL 反射。

| 参数 | 资源存储类型 | 引用源声明类型 | 允许连接引用的样本 | 样本常量（最多 8 项） |
| --- | --- | --- | --- | --- |
| input_vsnd | string | vsnd | 有 |  |

## 原始资源指纹

| 资源 | SHA-256 |
| --- | --- |
| core/soundevents/soundevents_addon.vsndevts_c | 242e4c827a83536f6a9245bf2d7cf4712d64cdd994e96941ffa48e2383abe986 |
| core/soundevents/soundevents_beat_pattern.vsndevts_c | 5b125f0c38d88a71d4069ce89522d39b16141db8bf6b2a9a7009b2fc3ddb7f83 |
| core/soundevents/soundevents_containers_test.vsndevts_c | 5c69e531860796b4befc024f756e99c16780b267e816f51b791059d122fc7f05 |
| core/soundevents/soundevents_core.vsndevts_c | 6b0a072c7b4604fe35a000f1f2aa54bd2a530c099801aea92a375b5354d81c86 |
| core/soundevents/soundevents_core_setters.vsndevts_c | 57c38887b7ca79f5f153b5d8fa1e8c0b9a08133dac5fd1e904e33717e3723a96 |
| core/soundevents/soundevents_diagnostics.vsndevts_c | 0333f4908ae8ec15ae238623164b287c2f37e27a782908749d343b5bc1221387 |
| core/soundevents/soundevents_examples.vsndevts_c | 1239ff7279f05ddfdc7b95a9157776436ee6316c31ddf2e448002e5f209efe21 |
| core/soundevents/soundevents_import_opvars_test.vsndevts_c | 55b991bce54d5cd3b928f2415c571b5a70d52a128feec38d39a4045dc97b253a |
| core/soundevents/soundevents_soundscapes_core.vsndevts_c | f06792b07807ec63afe29bbcdda08983c83e322e263f507408aa63d0f737acd6 |
| core/soundevents/testkv3_soundevents_diagnostics.vsndevts_c | 6c968e24c3956de71f442b6996e38590176b23abf9c31aaaf3355d52ead0252b |
| core/soundstacks/soundstacks_beat_pattern.vsndstck_c | 6dc5ccb9ad1f0dc369fd5220687bc19f5d7952eb54d8714bda678eb19668c056 |
| core/soundstacks/soundstacks_containers_test.vsndstck_c | 21c4d7ebefc001f1dee7d14b9d27db44519f0d91f1dbe30b8c78d718c240dc9f |
| core/soundstacks/soundstacks_core.vsndstck_c | 43e8592e0e2c90e62122b0115fbd2db8ddca486f87f61ffb200c05090959cef0 |
| core/soundstacks/soundstacks_core_setters.vsndstck_c | 8429a08162f007f08bb0e5610706a58df6c4e427be230ed56683245fe422c4f6 |
| core/soundstacks/soundstacks_core_test.vsndstck_c | b289d3df42b4f10c708437be6cb59ba3ec7ae01016f60d0e70ec26871f3fb986 |
| core/soundstacks/soundstacks_diagnostics.vsndstck_c | 85aeb7621310b1c264991fb1979eae1c1661ce29c98465424ac549ea8a4752d4 |
| core/soundstacks/soundstacks_examples.vsndstck_c | 63816e015bb31bc2d3c0ea88440c8f360bbc8eb6fe4cbf91923b344fa68f7c68 |
| core/soundstacks/soundstacks_import_opvars_test.vsndstck_c | 6b526820ab9f08d602b074ee1e6bf1e22a88970d0db55e077c0baaebff63e7ed |
| core/soundstacks/soundstacks_soundscapes_core.vsndstck_c | a33c68a18282d9a0cdd213e75eec54d386f6ef6c20c453e418661871c376b33c |
| core/soundstacks/soundstacks_src1.vsndstck_c | 188ac4fa915db5bae0fc8856fc82b407100d664e77c6efafa57953df882465b0 |
| csgo/soundevents/game_sounds_diagnostics.vsndevts_c | 54afe9fff79b5ba2e034a2c613d5657087396634008a2f3b37941275ebcacc35 |
| csgo/soundevents/game_sounds_footsteps.vsndevts_c | ae98b09cac5978787f5866796f18d4437c060b99a4ce9094f6b44e8e07ea639a |
| csgo/soundevents/game_sounds_physics.vsndevts_c | bc6142861b66b6cef74a27360608c4413dcde7cada8f5690a7cafd4d32333637 |
| csgo/soundevents/game_sounds_player.vsndevts_c | 2408be34e284133481e3f311df8c006e459ecb8f59c69c624ecfa053c6a0daae |
| csgo/soundevents/game_sounds_stopsoundevents.vsndevts_c | 4fa111286da9b63d54e16f54583d01d9d2f5bf3cc565b29d0e30138df44cd3fb |
| csgo/soundevents/game_sounds_ui.vsndevts_c | b83fe9d339479c838b3b575cdaf9cb95875f19c4c5509d84336f73a8ee1b8c35 |
| csgo/soundevents/game_sounds_weapons.vsndevts_c | 43783bf047a6ad803a4bffd6980fc53ec7f4dcefd3a00d674e4c3ba260ff49a1 |
| csgo/soundevents/game_sounds_world.vsndevts_c | ce8d5bf5c52acdd5e8d7932db1d8548380af7c11bfc66efd4e373a0f048b86d4 |
| csgo/soundevents/soundevents_from_tools.vsndevts_c | 6409b6f83cac24f8c9ac3f982dcedf8fe910dd9cb373ba8f89f0b9b280370120 |
| csgo/soundevents/ambience/game_sounds_amb_common.vsndevts_c | 4b62b6b2f3c7f49fc14cf38b1d68f91d623582de85189e1678992a3a97288cac |
| csgo/soundevents/ambience/game_sounds_ancient_night.vsndevts_c | ce2b6fae6fe360b186d4dc7ed978a670157aa1f2f809e9a606f6dad387f2a4c9 |
| csgo/soundevents/ambience/game_sounds_anubis.vsndevts_c | c1c95d12b0ef65971e54fdbfa757154cc8db4a57582c2c996d1083cef1db6294 |
| csgo/soundevents/ambience/game_sounds_assault.vsndevts_c | 562fcb6596f41a46ead25ce1fb64fef573450773f2ad11ad639213b0ce915fd9 |
| csgo/soundevents/ambience/game_sounds_aztec.vsndevts_c | c5f60039edc83e3c9eb5bca9f003e8d51ae7cc74bc4216f03d6608b6dc184539 |
| csgo/soundevents/ambience/game_sounds_baggage.vsndevts_c | 204b5132cb5cce609e9db1738c6c4ace5716149782de3fc667741e217d86e9df |
| csgo/soundevents/ambience/game_sounds_bank.vsndevts_c | d0ec32f734fba5c6ed5d2c6cd0abcf8528ef6f36c4283214732b22491a8c3f18 |
| csgo/soundevents/ambience/game_sounds_boathouse.vsndevts_c | 86381a92d1bf1914a78c074913650ac6f7949a6a8d943bda22c87dc7fbab05ec |
| csgo/soundevents/ambience/game_sounds_cache.vsndevts_c | d963b6113af45a6cfbde7c8ab6acefefcb46da4c15033a104812781e55b59022 |
| csgo/soundevents/ambience/game_sounds_canals.vsndevts_c | b1efb516d895162d430c500836275f5bffc81cc9bd8048c186c95afc2a51a7fd |
| csgo/soundevents/ambience/game_sounds_cbbl.vsndevts_c | d879df88cdff9c0349c97e4a6e935fc0ef06e50df2f046f8efe015a03be99f2d |
| csgo/soundevents/ambience/game_sounds_chateau.vsndevts_c | b6d3c80f1f1b9a6b15c555df0053bfbb23939d38cc2a2a0d27da99f64a9d157f |
| csgo/soundevents/ambience/game_sounds_compound.vsndevts_c | 64502a015fa3b2d26c50143357ec143c0fbfd242591821dcc896f965c07d1e5a |
| csgo/soundevents/ambience/game_sounds_coop.vsndevts_c | 9d3cc8fe21c153d83f65da441cb357f2f90fe12330b60f8ffca7595506d71b52 |
| csgo/soundevents/ambience/game_sounds_dust.vsndevts_c | 930b32e3c62256c1c782d88e7a5788d381d9c8383b696f67743165cde9898a02 |
| csgo/soundevents/ambience/game_sounds_dust2.vsndevts_c | 24218e2d19323aa3ca6ee39888afaa12222be5e7cbac20ab4840cc17838d6e6f |
| csgo/soundevents/ambience/game_sounds_havana.vsndevts_c | ff0323acd903b251dc836a0af130e8ebdbb858a1bce39e13e84935e9f639cdab |
| csgo/soundevents/ambience/game_sounds_house.vsndevts_c | e6383077dff4fa103fee748398ab42ed0ba647eabe9c2b1e95414184b054a357 |
| csgo/soundevents/ambience/game_sounds_inferno.vsndevts_c | c8b432ae93874a322fd9176d2e896a6207cbeb534569ce7b1f96030d0397ee25 |
| csgo/soundevents/ambience/game_sounds_island.vsndevts_c | 37932434a508cee85c7325f4609da111de505d49f4c730a6ee5d8d01d72e4a02 |
| csgo/soundevents/ambience/game_sounds_island_dust.vsndevts_c | e81c41fd2475c036a75f2446786790bd2834c42dd0dfebc1322b2c1187c3056c |
| csgo/soundevents/ambience/game_sounds_italy.vsndevts_c | 437d6b7bc39c31972a941be0dff0ab37563ef9e0682ad7d1b0639a2b3e597526 |
| csgo/soundevents/ambience/game_sounds_lunacy.vsndevts_c | 7d47035f70eb66e9d4c2e0bf55eab79817a24b5d69a43d1a0d62f18abc7fb4f7 |
| csgo/soundevents/ambience/game_sounds_militia.vsndevts_c | cf7cd09728faf2f3d7fc32c0f272ff28e521d1b955d6b36afb8550230f9dac35 |
| csgo/soundevents/ambience/game_sounds_mill.vsndevts_c | 545b2527cdb5b2fdf702969f43fc9fd414ae53de68dc9d3b615188d10fa8a27a |
| csgo/soundevents/ambience/game_sounds_mirage.vsndevts_c | 559da22482cd8d5978f03fca1b3e50edf75fa94ff7033557eb0946e4aca7735c |
| csgo/soundevents/ambience/game_sounds_monestary.vsndevts_c | 5ea53cbe60779711eae2828387357cf1f66c75e2160265949e2e99fff0c42fc3 |
| csgo/soundevents/ambience/game_sounds_nuke.vsndevts_c | 1a97a6eea358b47828ac6c16ced39de4eadf229449828bb5ffb0930448a38cb3 |
| csgo/soundevents/ambience/game_sounds_office.vsndevts_c | edadc2403e9e202b5f57b3451ffaeab2e8016970eb3f0b1ba1e69ab5d96857fb |
| csgo/soundevents/ambience/game_sounds_overpass.vsndevts_c | d12567c76ee020b9c28738c197a171f1d2e9e8dbe762ea8c227860d3b7f19876 |
| csgo/soundevents/ambience/game_sounds_piranesi.vsndevts_c | 83b0fe00093f8d999bddad2e527e979f6e0f9cc2926b18a33d3f1a5bd7073f75 |
| csgo/soundevents/ambience/game_sounds_port.vsndevts_c | 6df447014e80006bce75c28053f40240cf452e7c548cf6965434fca2df5af53b |
| csgo/soundevents/ambience/game_sounds_prodigy.vsndevts_c | fed0da24a5951360b70eaaf137af56e8dc39ba6d30c0ef8188616b94c48b539e |
| csgo/soundevents/ambience/game_sounds_rush.vsndevts_c | 7f887e86d475979a9856d1222b0b9f33ae5c853c484bccd4730d2663e53c96bb |
| csgo/soundevents/ambience/game_sounds_shacks.vsndevts_c | 6fc3c4354f23802dfe84fdf3b711630f8f1f9ef65cc62808e3f5540e492a2a0f |
| csgo/soundevents/ambience/game_sounds_shoots.vsndevts_c | cd2849ed9989a17f395f109d7780eb166b588cd5d93afd825e8e804288e017a7 |
| csgo/soundevents/ambience/game_sounds_train.vsndevts_c | 6a65b6e32072a00b3a4e9e6649cc2bc345937cef419b8747a5a6863cb1787c55 |
| csgo/soundevents/ambience/game_sounds_training.vsndevts_c | 6455b63682664c0711f3c8cbd8d3cd8ef0fa41ebbc9a1f9a06856f0ad57556d8 |
| csgo/soundevents/ambience/game_sounds_tuscan.vsndevts_c | ebe08b07f77e689a662813bac53e10675989dd785a93094d5e6565149ec5e7fd |
| csgo/soundevents/ambience/game_sounds_vertigo.vsndevts_c | 64d7166d5faa1389af8ec0ae98c290107efe543febffb517744c5e4a9c845f8d |
| csgo/soundevents/music/3kliksphilip_01/game_sounds_music.vsndevts_c | b372f31f871e1ac4ffd4ce6a52122b4ff769ca73d3e512d7967bbdf3c21f162c |
| csgo/soundevents/music/adambeyer_01/game_sounds_music.vsndevts_c | 3c8027a075a3711e882f4a6057f8fa13a0c6ba881b98f4e6c527f6c5b0b8e753 |
| csgo/soundevents/music/alrt_01/game_sounds_music.vsndevts_c | 73154ba33499c55279f66c6f5d699957359d8256c535822378084227356034ff |
| csgo/soundevents/music/altare_01/game_sounds_music.vsndevts_c | 6f875df561b8a8080bd557de169fd677568c3d480e575362ed2c54b8757bfd8e |
| csgo/soundevents/music/amontobin_01/game_sounds_music.vsndevts_c | f351a6bf1a7bfe28c885f204e786567927fae2ae10390e8f480c9e92380f1650 |
| csgo/soundevents/music/austinwintory_01/game_sounds_music.vsndevts_c | 618923f59a9be5a3fa12f0d79aeb831cbeaf56b369d2e306d4624173ea4df615 |
| csgo/soundevents/music/austinwintory_02/game_sounds_music.vsndevts_c | 92fc68507f85c4dc2bac4528ae356f88e124883567c815ea72211099dc188356 |
| csgo/soundevents/music/austinwintory_03/game_sounds_music.vsndevts_c | aeb81e7587af0ddb150b2e2fff96df224136a15c147b3f8654e6ac08a53b5bb1 |
| csgo/soundevents/music/austinwintory_04/game_sounds_music.vsndevts_c | 69c237dd2266e7513e80390502bdaecadd7da7dac2080c2e74ad287db5c61c67 |
| csgo/soundevents/music/awolnation_01/game_sounds_music.vsndevts_c | 56a4595152c2cf7421e1242c22b4a415c9ae38e464c89f49c347cf99bf3eea42 |
| csgo/soundevents/music/bbnos_01/game_sounds_music.vsndevts_c | 3b0cc6b35b7f242feee4915336d95b3f615d3cd470f02da27f7ab4f3baaacad9 |
| csgo/soundevents/music/beartooth_01/game_sounds_music.vsndevts_c | 1f8abb03f3aa030d8fe54682cae13222f4f8c296b79e3680b62c1a259098a9cc |
| csgo/soundevents/music/beartooth_02/game_sounds_music.vsndevts_c | 1f4491f0cfa5d0aa90bdd6e346149e6452a484596dce6f00798a87e778d55901 |
| csgo/soundevents/music/benbromfield_01/game_sounds_music.vsndevts_c | 6588e25be01572b81e4bb8c0009d9263ccbca3e11d5c9d7c59a637589abbdefb |
| csgo/soundevents/music/blitzkids_01/game_sounds_music.vsndevts_c | 7a5ee557616ed76d0dede7db1eaa74525b6b2e04151b7e6df93e394e037304b8 |
| csgo/soundevents/music/borne_01/game_sounds_music.vsndevts_c | 5cf89d8dcd44644f8a85ed1233aec6d12ab4d0e1829061855ce96399dece8049 |
| csgo/soundevents/music/chipzel_01/game_sounds_music.vsndevts_c | 81749ac98d2d36d9924649604b292a78a29810f6ce74db76a7de9bdaeabae532 |
| csgo/soundevents/music/damjanmravunac_01/game_sounds_music.vsndevts_c | aaac523c711ac900710c765c8ef19888946c205ae24729581f29b80d4e4d6cb2 |
| csgo/soundevents/music/danielsadowski_01/game_sounds_music.vsndevts_c | 5bfef7f8851ea291620e078d72c1fe7f3c8ac649023425efac0d04620644926e |
| csgo/soundevents/music/danielsadowski_02/game_sounds_music.vsndevts_c | a5dc67ae54cc75b69fd8459f987200eecb7e92ee06d6e45f9b853a36aa859051 |
| csgo/soundevents/music/danielsadowski_03/game_sounds_music.vsndevts_c | d137bdd6284cc9a604f045d1f74f371b4d2dccc3ba960114e6cff4b691d397ed |
| csgo/soundevents/music/danielsadowski_04/game_sounds_music.vsndevts_c | dd7de8f898f2eb70211ffd7f4e067ad00c16d540b3c99e03073c02aa539edd46 |
| csgo/soundevents/music/danielsadowski_05/game_sounds_music.vsndevts_c | a5590a3b1e9d6e1c563fcd32907f4d1292cac3a8d40880d63cb3cfca34d16b1a |
| csgo/soundevents/music/darude_01/game_sounds_music.vsndevts_c | b827e26892470c66ea5cd0de1b437830484e9dcfa92c38263fd2224d31b44390 |
| csgo/soundevents/music/denzelcurry_01/game_sounds_music.vsndevts_c | 77e0a1a777d75c63d07b0651967b46ce84468979068c20b08ee55e9328e284f8 |
| csgo/soundevents/music/dren_01/game_sounds_music.vsndevts_c | 16c16436c8bec26826ffcc993d0ef87e3b0470ba280355e71e2e911d0ea2e882 |
| csgo/soundevents/music/dren_02/game_sounds_music.vsndevts_c | e9ecd07eea430a0911ba4c1e3a53fcbb835d5239f7019bd1ff371edeadb9eba7 |
| csgo/soundevents/music/dren_03/game_sounds_music.vsndevts_c | d62bee311f4c63cadd878ecfaddc6c2b82c4b2f0eb4e19fcc9fe4d25b5dfb0a6 |
| csgo/soundevents/music/dryden_01/game_sounds_music.vsndevts_c | 60fc705986a6f5ceb87fc3e3f525bc6ec996fabc8dc19ec74dee6a61d2308019 |
| csgo/soundevents/music/feedme_01/game_sounds_music.vsndevts_c | 4181d54f1bdd446024792cec89ecb2c49ef24f9a8376c426c5416fdb447ba000 |
| csgo/soundevents/music/freakydna_01/game_sounds_music.vsndevts_c | d0b708f7e9bb0cc90ba98da35487df51fddb086c453e72a53c8224f9abc7cae0 |
| csgo/soundevents/music/ghost_01/game_sounds_music.vsndevts_c | dcccd7fe335ddb9c4f4dda907df05d803982bea0fa34949460a84c4c6ebba1f2 |
| csgo/soundevents/music/hades_01/game_sounds_music.vsndevts_c | eff5d400ab685674c38e12e4ac7cfe164d27867d8396f14bf01ea4c0a7e2daf5 |
| csgo/soundevents/music/halo_01/game_sounds_music.vsndevts_c | 3a07a816b24b66c06f1cb6f07584098390272d73b34f3fb707ec4e7a55ae89f8 |
| csgo/soundevents/music/health_01/game_sounds_music.vsndevts_c | 5de82079ad2628afca3fb26ba2881d81742a75c8897c8a1678a369dcba78ed81 |
| csgo/soundevents/music/hlalyx_01/game_sounds_music.vsndevts_c | d5bfbfc8f34f4a59f919c49ef949489dde26b8939aa594bd1afd73b0bf1992bf |
| csgo/soundevents/music/hlb_01/game_sounds_music.vsndevts_c | 85f96314ed555451fa66593750fa147d938c6ebf16912d212ec4267b4e77b18c |
| csgo/soundevents/music/hotlinemiami_01/game_sounds_music.vsndevts_c | 2291252fd8b9020b357fd58817d69d493306907e4aae973edbed0a2b7a7d2726 |
| csgo/soundevents/music/hundredth_01/game_sounds_music.vsndevts_c | 852a0dc9585be50b611328ce8a98b363bc0bab9203a48d8c1956ce450eb3c473 |
| csgo/soundevents/music/ianhultquist_01/game_sounds_music.vsndevts_c | 17bd5cce68d6e4ff1a73b23a7c1e38549f47e29765019923d0c6cb2e46972506 |
| csgo/soundevents/music/isoxo_01/game_sounds_music.vsndevts_c | a8b9596b8ba658f4c53c6b2ebc65ff784458a7623e8de5c0388d0701eb127468 |
| csgo/soundevents/music/jamesandthecoldgun_01/game_sounds_music.vsndevts_c | 86c81876280c9d884b79ae56de4c5f932d1e355bdd8627aa7ebf7dd538f028b2 |
| csgo/soundevents/music/jesseharlin_01/game_sounds_music.vsndevts_c | e3ffdb18a85745691e04327c90e70a78800759e3d96114ca6f8e75e67f94077a |
| csgo/soundevents/music/jonathanyoung_01/game_sounds_music.vsndevts_c | 63aa052dcab106ab3d56d82dab7824a36a28e02c98185da15d938bf23180b037 |
| csgo/soundevents/music/juelz_01/game_sounds_music.vsndevts_c | 9a671a76797a6d7efef842f79178ebac3b1523228dcef4fdb047f11bdb689f8a |
| csgo/soundevents/music/juelz_02/game_sounds_music.vsndevts_c | 7757f19ce0ae15c441de67d9fa727f639b71feadf92aba2202e76b03d1e1535f |
| csgo/soundevents/music/kellybailey_01/game_sounds_music.vsndevts_c | 6486f7438c5895bd50b73841b79c1461dc82f8ab96ccf7e1c783c36472114548 |
| csgo/soundevents/music/killermike_01/game_sounds_music.vsndevts_c | 82fb1e7c26c4e3fa57d0fb423c28084afa4bebf3f9ae56bbb9f297861bd8f47e |
| csgo/soundevents/music/killscript_01/game_sounds_music.vsndevts_c | e6d621d5900cc1d8a21f164d0f86330b9519a006979dae44c2a2c1399b53c383 |
| csgo/soundevents/music/kitheory_01/game_sounds_music.vsndevts_c | 9a4783772c7085511dda725fcf801bae8c250ee3237cfc72c1e96272dbbae375 |
| csgo/soundevents/music/knock2_01/game_sounds_music.vsndevts_c | ea740b7957944d759bda1fc11df5f90f046e86b4e367ed2905d4bb3d292293d5 |
| csgo/soundevents/music/knock2_02/game_sounds_music.vsndevts_c | 26e52e9dedb198ee97157c87f6daa03350e370c388f4918512d7d5b179d3af19 |
| csgo/soundevents/music/laurashigihara_01/game_sounds_music.vsndevts_c | 40717b6472bea7a22b0cc4f623ff8079db3801626a167fc360f38b96f6483ca1 |
| csgo/soundevents/music/lenniemoore_01/game_sounds_music.vsndevts_c | 0e88a7a0edea6b3f8351e196962f4c4e141c8898a3a2385f69eabff13403bd61 |
| csgo/soundevents/music/mateomessina_01/game_sounds_music.vsndevts_c | cbd02cbfcedc18005294cfbd10ae29bbf551cb1f7a3ba5390d2ef3d9d3478c2e |
| csgo/soundevents/music/mattlange_01/game_sounds_music.vsndevts_c | 7b322d59720d794a463c882a8ae405cb43fff84b919ba1e02f8b2894eefdf15f |
| csgo/soundevents/music/mattlevine_01/game_sounds_music.vsndevts_c | ab832544ff32bdff666abb423cc88027f224c5f28650c87e0a9419e1a7c22d0d |
| csgo/soundevents/music/mattlevine_02/game_sounds_music.vsndevts_c | a1d3681e7b07097c4fff514c574f8e9ae9def07166cf5817a61f45723c931e82 |
| csgo/soundevents/music/meechydarko_01/game_sounds_music.vsndevts_c | dc1b75af5d2843127bf029c2dd58e23c810ef559c50d50cedae74a888c78ce47 |
| csgo/soundevents/music/michaelbross_01/game_sounds_music.vsndevts_c | 44da2e1daded088fe74df7ed08e4ca758bf62a799e434395f7f3e9102de20219 |
| csgo/soundevents/music/midnightriders_01/game_sounds_music.vsndevts_c | fe3a98956361323659364a2f4c009f411bc33f06d0de00203015f7a72ea90b15 |
| csgo/soundevents/music/mordfustang_01/game_sounds_music.vsndevts_c | 6d43463e79883c4b9849def9bc904456a3ec2a925f938e20ff7778001e02504a |
| csgo/soundevents/music/neckdeep_01/game_sounds_music.vsndevts_c | 14d3311cb29376cae6b60a19c1ff45a68f970544c9a71817bd30a3d941e9f993 |
| csgo/soundevents/music/neckdeep_02/game_sounds_music.vsndevts_c | ce7350c11edd6d3e97392b4c47604e591872cbbdaee3b0171ff78e414e555437 |
| csgo/soundevents/music/newbeatfund_01/game_sounds_music.vsndevts_c | 264870e87858116f69c9d8dbfe2e8b1d6c1b652ab36bc0af88b7944a3b576f92 |
| csgo/soundevents/music/noisia_01/game_sounds_music.vsndevts_c | 2227905a86ee618ff75791d35fe8edc7d6f31b0da1b079d4de115a2ccc684744 |
| csgo/soundevents/music/perfectworld_01/game_sounds_music.vsndevts_c | d0fa39a60dee756af5a7270039b5bdeb3a43316c6dc73a752d21268efba07b32 |
| csgo/soundevents/music/perfectworld_02/game_sounds_music.vsndevts_c | 040b265ced765a6d2b99dd02c1a231c26ccac5e2cff718c57235a3ff609f8a46 |
| csgo/soundevents/music/pirapus_01/game_sounds_music.vsndevts_c | 4a6b14a4ac99d9494befbef96e0abbfb6fc38babbaffc9420348da6d5c7fb13d |
| csgo/soundevents/music/proxy_01/game_sounds_music.vsndevts_c | 8a7afbedbbc3fe5ea183db1e18484a3642793fb6520ccd7207aa1e8523e4718c |
| csgo/soundevents/music/pvris_01/game_sounds_music.vsndevts_c | 185f3bbeecd466fec80191d1943fb5d16136b32f71fe9232d94c7c75f59ba696 |
| csgo/soundevents/music/radcat_01/game_sounds_music.vsndevts_c | 473121022c641e5617f1b81d700bfad9c4e8c9a227da805de377445c0de64eb2 |
| csgo/soundevents/music/repiet_01/game_sounds_music.vsndevts_c | 94012c31a286f92ab213a72c4f4b45cfb700ad8cdc96ef971c55b05f3edc513b |
| csgo/soundevents/music/roam_01/game_sounds_music.vsndevts_c | 8c1893ff5062b364d2b5b5700fb35aa665a0478979f8bd3920c32d9c4f99055a |
| csgo/soundevents/music/robertallaire_01/game_sounds_music.vsndevts_c | 465305c700618764a4af6d07e35c896bc1eab1dc6add98d7d2f3efcc7aea246f |
| csgo/soundevents/music/sammarshall_01/game_sounds_music.vsndevts_c | 25208a408b7120a4e0f0ab41a4d101c6a7d295099ffda667db2d10a9379b09e5 |
| csgo/soundevents/music/sammarshall_02/game_sounds_music.vsndevts_c | 27091468d47fc8502a76c77edcec8e9f6a99d32d89391cc35a636e0c38bf1b7a |
| csgo/soundevents/music/sarahschachner_01/game_sounds_music.vsndevts_c | a8997a32853203e9fb02b54415573d66f20a0d322d3fac7445f583235a84ab61 |
| csgo/soundevents/music/sasha_01/game_sounds_music.vsndevts_c | 5d6b739f6c27337790cc3dac5f41d57cf347678dd0bab64529e283e3425111e5 |
| csgo/soundevents/music/scarlxrd_01/game_sounds_music.vsndevts_c | be8e8ed0c5ed4b1a9e1f959475642784720b55be46a0ca9a2cfbba1e67c0ee65 |
| csgo/soundevents/music/scarlxrd_02/game_sounds_music.vsndevts_c | 0ae26863163ace0ed92e4de3e38b25b4078585919cc62a863a379397c33a3192 |
| csgo/soundevents/music/seanmurray_01/game_sounds_music.vsndevts_c | 3e90a670942f3331835784c76633a97faf2c1c3fc358b43bec19ab80ed312519 |
| csgo/soundevents/music/selectiveresponse_01/game_sounds_music.vsndevts_c | 31a9ef1b419ab0c91ede4a598d9160e607091cee3e24ea57c9fb8804f1a46ac1 |
| csgo/soundevents/music/shockone_01/game_sounds_music.vsndevts_c | bc6588dd95a2f4435eddb26b466bafcf69ee31e44044367fbd3212abd801713c |
| csgo/soundevents/music/skog_01/game_sounds_music.vsndevts_c | 569d415893a1df2a3995a525c7681f6599b2279e8fda8e34bd394a0b1d5795bd |
| csgo/soundevents/music/skog_02/game_sounds_music.vsndevts_c | f36d12b507c4929c37f9d5c4acdf6e8ad47a9d8fdd24039dc5638f5ee8016025 |
| csgo/soundevents/music/skog_03/game_sounds_music.vsndevts_c | 8646d71ed2ab14f1b2095b6c20d98523131d9d89ff43ecb67954264c30f74fee |
| csgo/soundevents/music/starjunk95_01/game_sounds_music.vsndevts_c | 0543c2da65e1787558ae46ab8a6d6eeec73b381ad9d82f8f55307112ea279246 |
| csgo/soundevents/music/sullivanking_01/game_sounds_music.vsndevts_c | ff1bf90866c5bf984ec9833b7521478d4ffa3fe8b21f477337f8992608eba5e3 |
| csgo/soundevents/music/theverkkars_01/game_sounds_music.vsndevts_c | e160913a201687b30d4d4495e90c6ef0c2eda8540633ebb06a9e0dc7de0c1f0f |
| csgo/soundevents/music/theverkkars_02/game_sounds_music.vsndevts_c | 5d49ac283386d81f729b06e2ed5877507f96dbce97654debcb1269265f8a5037 |
| csgo/soundevents/music/tigercub_01/game_sounds_music.vsndevts_c | bdf390d3196da99bca5f2509f920b4013d17ddba40e50a9fce90bc4634149818 |
| csgo/soundevents/music/timhuling_01/game_sounds_music.vsndevts_c | 92d3cdc4420ff45d9d05f31d3588b55d5a2302d12854bdf5c21e73e8ee0c6281 |
| csgo/soundevents/music/timhuling_02/game_sounds_music.vsndevts_c | 46d84be9c14e4df9ea85c3372352114d380d220c2fa575d583b7c00982679203 |
| csgo/soundevents/music/treeadams_01/game_sounds_music.vsndevts_c | 6c19687747be9f296f6dacf8d72e7da738336bf77fe3c0f6ccb5948fbfb93a9e |
| csgo/soundevents/music/treeadams_benbromfield_01/game_sounds_music.vsndevts_c | e4b081358d0ebfe9c6d34977d44177503388e06100f7cbdef0597096f0c57e24 |
| csgo/soundevents/music/troelsfolmann_01/game_sounds_music.vsndevts_c | cf933abe4ad50cfdd2b9711cdad7560ca524eaddc54ca380b537a4b07269c391 |
| csgo/soundevents/music/twerl_01/game_sounds_music.vsndevts_c | b409154928ada9b0cb8ea34e20ee2022b160662094eb3e1b76ea1e586af10bc5 |
| csgo/soundevents/music/twinatlantic_01/game_sounds_music.vsndevts_c | 0755263f99f7b57cf4df00d74cdb9dfe54a82a6402862884f629421e80debc6e |
| csgo/soundevents/music/valve_01/game_sounds_music.vsndevts_c | fa13bc4245fa8e6b6f5f723b042221308372438f59321f92ea29ce6f7ab15eb3 |
| csgo/soundevents/music/valve_02/game_sounds_music.vsndevts_c | fea0d533e45fb01d0c2d7570bf379cb7001aea4c63862185cc077722b85c5b32 |
| csgo/soundevents/music/valve_cs2_01/game_sounds_music.vsndevts_c | 3811fa58e4be4255a68de6e8b1d08ab90d8c7276cb9a8654050421b7ea81cc23 |
| csgo/soundevents/vo/game_sounds_commander.vsndevts_c | 317673849abea1d5c02a590491791ea4c6218628cfcf633a2ebd581d8aaa04ab |
| csgo/soundevents/vo/game_sounds_felix.vsndevts_c | 124f7d162faf595a3c14f97786b257bb4fd63f9ab9e1834dfa25f1228d9f25a3 |
| csgo/soundevents/vo/game_sounds_hostage.vsndevts_c | 623f1bc36fe2b271b371c78403a27ccb46a9bebe7068d3a6da899710af8ae977 |
| csgo/soundevents/vo/agents/game_sounds_balkan.vsndevts_c | b4f451d050cee918087b2c7438b78cc00ae4980671077f55d2a40a6cbc08dbe8 |
| csgo/soundevents/vo/agents/game_sounds_balkan_epic.vsndevts_c | 1f3d33ec0b3ec0bedc94e32df8419fa459ede314c43dbd52326801bcb60d231b |
| csgo/soundevents/vo/agents/game_sounds_fbihrt.vsndevts_c | af41bf8af1525a9e7a146dd903dab719f3acf12674d336985bfce7b5e539b324 |
| csgo/soundevents/vo/agents/game_sounds_fbihrt_epic.vsndevts_c | 2bec4333d71004436861b1462e3be7069582aa3867ca63071a034805bd7a4c87 |
| csgo/soundevents/vo/agents/game_sounds_gendarmerie_fem.vsndevts_c | 2628d86ab93edad7a1ced9de74841a6134c045eb14dccf23ef8be6dbe8343024 |
| csgo/soundevents/vo/agents/game_sounds_gendarmerie_fem_epic.vsndevts_c | 316b279edb9e08f1595906f0c7acd19951dd7cbd4bee5d22598f242830b55eca |
| csgo/soundevents/vo/agents/game_sounds_gendarmerie_male.vsndevts_c | a64d82f06999c8e7f9019560f0aee751d67c8e418c1b2234c7e80af1836d0cd3 |
| csgo/soundevents/vo/agents/game_sounds_gsg9.vsndevts_c | 566281e7b1502365d5dca65fb711ca34e4fe6691924d2b06b02c819a2878e2e5 |
| csgo/soundevents/vo/agents/game_sounds_jungle_fem.vsndevts_c | 167b47f50d90938cc2be951a402cda4320d5613d4fd23726217b25d4f0891c40 |
| csgo/soundevents/vo/agents/game_sounds_jungle_fem_epic.vsndevts_c | ccfb4ac5b322be4267c3c524885eda7026890b55dc223e2e962c60c1ae7c14c2 |
| csgo/soundevents/vo/agents/game_sounds_jungle_male.vsndevts_c | e8a91c08e5ce107033bb4dec715aa8028296dc47c1d69a4f39cdf3646082cc6c |
| csgo/soundevents/vo/agents/game_sounds_jungle_male_epic.vsndevts_c | 878878b5a847f539fc4c6b650687980833093a69c5016ec0c6d3f4b542ace7c0 |
| csgo/soundevents/vo/agents/game_sounds_leet.vsndevts_c | 5066e641c41e555e50d5a14da90bceaccab51371c4ab3ab3f3b40e8216bef67d |
| csgo/soundevents/vo/agents/game_sounds_leet_epic.vsndevts_c | 1156b6b686f350c0a70d03dbf5ed16901f1847d7b29edc74c03f28132a62b013 |
| csgo/soundevents/vo/agents/game_sounds_phoenix.vsndevts_c | 9b22f32595adf1cc70e0584a356dee0e5f4ff04a80919f486f28e3b55a5487c0 |
| csgo/soundevents/vo/agents/game_sounds_professional.vsndevts_c | d53c56df105504ad7a174c2ed27e487c6da80ac8272634582dcf0e5ad273e459 |
| csgo/soundevents/vo/agents/game_sounds_professional_epic.vsndevts_c | d20a959471231c434575d9babcb054d0730439cab75400bd947bd93dd1c58e34 |
| csgo/soundevents/vo/agents/game_sounds_professional_fem.vsndevts_c | 365b92dfec32963590be6f0c6eb151c0831bf6d459ac5c49791316f51a68f2e7 |
| csgo/soundevents/vo/agents/game_sounds_sas.vsndevts_c | 1b0506b10de0ae4a962d4d5fa8c92f88ee4197042565b6a15366430eb475b711 |
| csgo/soundevents/vo/agents/game_sounds_seal.vsndevts_c | 6ec9c3d757efb7d950de94f5990291be3f5a7e8d911da9e27f826fee8a2d9d46 |
| csgo/soundevents/vo/agents/game_sounds_seal_diver_01.vsndevts_c | c021755d48c3ace1db2e7a0c17e6fffaa7660ce0f56b52193c5d23de4d2f47cd |
| csgo/soundevents/vo/agents/game_sounds_seal_diver_02.vsndevts_c | 63052cc4d6014c175fd7fc407e11a42c2f6496d36175ef38bad27e68655f72fd |
| csgo/soundevents/vo/agents/game_sounds_seal_diver_03.vsndevts_c | d62c538b627b77479bf0ac15b395b2485156bdd5acdaf4fa10ced6397c912be5 |
| csgo/soundevents/vo/agents/game_sounds_seal_epic.vsndevts_c | 99928b8ea6369dc82cb6d397543ae1486f550856bd75de980fc3dfa5dce86a04 |
| csgo/soundevents/vo/agents/game_sounds_seal_fem.vsndevts_c | 78c3395ff4a67a9052cfe1f00b403954ad171b07c5b3b74ef4a6c0e860052727 |
| csgo/soundevents/vo/agents/game_sounds_swat.vsndevts_c | 9d44f225679f5d2280217f8a2086ac98c0f240b9296d1c4e80e96bd824d0eb78 |
| csgo/soundevents/vo/agents/game_sounds_swat_epic.vsndevts_c | f9d1457c50d8de8242f07dee77afa7ed8f25f77e56ed8ae27ebc66d052196d0d |
| csgo/soundevents/vo/agents/game_sounds_swat_fem.vsndevts_c | 7e448d97325ae1fdc39e6917b444287b5ed8bffa84af05ac488fdc3c210b2bfa |
| csgo/soundevents/vo/announcer/game_sounds_cs2_classic.vsndevts_c | 1133ec8fb687c58852cc5dff02c383cfb48606c4b727c8c74d4417a66c1e2845 |
| csgo/soundstacks/soundstacks_csgo_ambient.vsndstck_c | 5aabf26311e0ebfea12264597f2c9b6e52ad7fb5884922032d17c244228ecb02 |
| csgo/soundstacks/soundstacks_csgo_core.vsndstck_c | 4c526455ad22157f86133589751683ad23ca00fa81c60494b8d2bb878a8cff12 |
| csgo/soundstacks/soundstacks_csgo_mega.vsndstck_c | 9fa32349e05774aed963c25d0c7d38b6204d4d99c6d3c6a50f88675240fb4a9e |
| csgo/soundstacks/soundstacks_csgo_music.vsndstck_c | 83db719ca5c384b54ff2835876dfe5abc3dcd09ebcd66fcb6639fb94d989581d |
| csgo/soundstacks/soundstacks_csgo_surf.vsndstck_c | 8961458a6464dbe14c6c58e38e89b718914cafd7ac16a985aba80308adbc680e |
