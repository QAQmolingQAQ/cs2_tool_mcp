# Hammer 菜单文字参考

来自历史Qt菜单快照，与用户指定discover_out/calls.jsonl按文本交叉核对。不是当前窗口状态，也不是动作API或可执行权限。
快捷键从原始文字的制表符后拆出；分隔线不列入表。采集命中不证明属于同一个控件/菜单，Hook ID不参与归属。

共10个菜单、119个非空菜单项；119项在Qt采集记录中有相同文字。

采集SHA256：9bf1ef3aabd472604a129696913eb7738a766031449e8714a9962a21f385391c

原始文字、快捷键、命中函数和来源信息在同名JSON；Qt enabled/visible不等于编辑命令就绪。

## File

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| New | Ctrl+N | 17 |
| New From Template |  | 9 |
| Open | Ctrl+O | 12 |
| Reload From Disk | Ctrl+Shift+F12 | 12 |
| Recent Files |  | 7 |
| Save | Ctrl+S | 14 |
| Save As... | Ctrl+Shift+S | 12 |
| Save Copy As Text... |  | 9 |
| Save Active Prefab | Shift+Alt+S | 8 |
| Close |  | 18 |
| Import File... |  | 9 |
| Export File... |  | 9 |
| Export Selected... |  | 9 |
| Reload .FGD Files |  | 9 |
| Build map... | F9 | 8 |
| Exit |  | 5 |

## Edit

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| Undo |  | 34 |
| Redo |  | 24 |
| Disable Undo/Redo |  | 8 |
| Repeat Command |  | 11 |
| Find entities... |  | 11 |
| Replace... |  | 8 |
| Cut |  | 25 |
| Copy |  | 30 |
| Paste |  | 30 |
| Paste Special... |  | 11 |
| Delete Selected |  | 12 |
| Move Props to World |  | 11 |
| Insert New Image Plane |  | 8 |
| Clear Selection |  | 11 |
| Select All |  | 11 |
| Invert Selection |  | 11 |
| Select Parent |  | 11 |

## Map

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| Entity Gallery |  | 9 |
| Check Map For Problems |  | 9 |
| Map Information |  | 9 |
| Map Properties | Ctrl+Shift+P | 11 |
| Map Variables | Ctrl+Shift+M | 9 |
| Map Relays |  | 9 |
| Entity Report | Ctrl+Alt+R | 8 |
| Map Manifest | Ctrl+Alt+M | 8 |
| Load Compiled Vis Data |  | 9 |
| Clear Compiled Vis Data |  | 9 |
| Load Map In Engine |  | 9 |

## View

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| Toolbars |  | 5 |
| Show 2D Grid |  | 9 |
| Show 3D Grid |  | 9 |
| Smaller Grid |  | 12 |
| Bigger Grid |  | 12 |
| Center Views on Selection |  | 12 |
| Center 2D Views on Selection |  | 12 |
| Frame All Views on Selection |  | 12 |
| Align Active View to Selection |  | 9 |
| Align Selection to Active View |  | 9 |
| Re-orient camera to workplane |  | 12 |
| Reset camera to world orientation |  | 9 |
| Create Saved Camera |  | 12 |
| Go to Coordinates |  | 9 |
| Show Entity Names |  | 7 |
| Show Editor Only Objects | Shift+O | 8 |
| Show Vis Contributors Only |  | 9 |
| Show Tools Materials | Ctrl+Shift+F2 | 8 |
| Show Collision Models |  | 12 |
| Show LPV Sample Vis |  | 9 |
| Show Light Overlap |  | 9 |
| Quick Hide Selection |  | 12 |
| Quick Hide Unselected Objects |  | 12 |
| Show Quick-Hide Objects |  | 12 |
| Selection set from quick hide |  | 11 |
| Create selection set |  | 11 |
| Hide unselected |  | 11 |
| Take Large Screenshot... |  | 8 |

## Tools

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| Group |  | 20 |
| Ungroup |  | 13 |
| Ungroup All |  | 13 |
| Parent |  | 13 |
| Un-parent |  | 13 |
| Create World Layer |  | 10 |
| Create Lattice Deformer |  | 13 |
| Create Simple Deformer |  | 13 |
| Create Path Deformer |  | 13 |
| Deformer Creation Axis |  | 4 |
| Create Instance |  | 13 |
| Collapse Instance |  | 13 |
| Tie To Entity |  | 13 |
| Untie From Entity |  | 13 |
| Snap Selected To Grid |  | 13 |
| Snap Selected To Grid Individually |  | 13 |
| Flip Selection Horizontally |  | 13 |
| Flip Selection Vertically |  | 13 |
| Create Mesh Around Selection |  | 13 |
| Remap Blend Data |  | 10 |
| Options... |  | 4 |

## Prefabs

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| Import Prefab |  | 8 |
| New Prefab From Selection (Maintain World Offset) |  | 8 |
| New Prefab From Selection (Center On Origin) |  | 8 |
| Collapse prefabs |  | 4 |
| Display Prefabs |  | 8 |

## Preview Baked Lighting

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| Bake All Lighting |  | 9 |
| Bake All Cubemaps |  | 9 |
| Bake Fog Indirect Lighting |  | 9 |
| Clear All Lighting |  | 9 |
| Bake Lighting On Selection |  | 12 |
| Bake Selected Cubemaps |  | 9 |
| Clear Lighting On Selection |  | 9 |

## Steam Audio

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| Preview Scene |  | 7 |
| Export Scene to OBJ... |  | 7 |
| Create Probe Generation Volume |  | 7 |
| Create Probe Exclusion Volume |  | 7 |
| Generate Probes... |  | 7 |
| Generate Single Probe |  | 7 |
| Toggle Probe Visualization |  | 7 |
| Change Settings... |  | 7 |
| Bake Data... |  | 7 |

## 窗户

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| Toolbars |  | 5 |

## Help

| 菜单项 | 快捷键 | 采集记录命中 |
|---|---|---:|
| Show Key Bindings... |  | 1 |
| Help... |  | 2 |
| About Qt |  | 2 |
| About |  | 2 |
