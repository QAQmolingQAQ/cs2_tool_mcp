# Hammer MCP

Project root: `C:\codex\cs2_tool_mcp`.

## Workflow status

The MCP now provides durable `cs2_build_start/status/cancel`, quick/full build
profiles, VPK entry/resource validation, project configuration and live version
selfchecks. Copy [config/project.example.json](config/project.example.json) to
the ignored `config/project.local.json` and select an existing addon/map.
See [BUILD_WORKFLOW.md](BUILD_WORKFLOW.md) and [VERSION_SELFCHECK.md](VERSION_SELFCHECK.md).

Hammer also provides read-only edit baselines, per-property batch previews and
typed saved-map snapshot comparisons. These expose conflicts without granting
permission to apply changes. Native editor offsets require an exact verified
compatibility profile; the shipped profile list is intentionally empty.
Fixed Qt UI adapters use a separate checked Qt ABI path.

An isolated map completed edit/Undo/Redo/save tests, a quick build with validated
VIS, and a local game-load smoke check. Durable runtime load start/status now
checks map identity after loading without replaying unknown commands; see
[RUNTIME_VALIDATION.md](RUNTIME_VALIDATION.md). Complete rollback, full lighting,
dependency coverage and gameplay validation remain unfinished. See [EDIT_PREFLIGHT.md](EDIT_PREFLIGHT.md),
[EDIT_CYCLE_VERIFICATION.md](EDIT_CYCLE_VERIFICATION.md) and
[WORKFLOW_GOAL.md](WORKFLOW_GOAL.md). Local evidence paths and historical process
IDs in these reports are examples of recorded runs, not reusable live handles.

## Build

Requires Windows x64, Visual Studio C++ Build Tools with CMake, and Python.

```powershell
python -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\build.ps1
python -m unittest discover -s tests
python injector/mcp_smoke.py
```

`cs2_map_check` performs read-only structural checks on an open Hammer map:
missing geometry on `func_button`/`func_brush`/trigger entities, empty or
unavailable meshes, invalid entity origins, and duplicate targetnames. Duplicate
names are informational because Source I/O may intentionally use them. This
check does not compile or playtest the map.

`cs2_asset_tree` reads saved text-KV3 `.vmdl` and `.vpcf` source files. It can
show ModelDoc node attributes and Particle Editor function/child arrays by path
(for example `rootNode.children[0]` or `m_Operators[0]`). It does not include
unsaved changes in an open editor session.

`cs2_editor_document` identifies the active ModelDoc or Particle Editor's live
document and root object using module-specific RTTI checks. It works for an
unsaved document, but child-node and attribute enumeration are still pending.

The build creates `cs2_tool.dll` at the project root and under
`injected_dll/build_vs18/Release/` when using Visual Studio 18.

## MCP connection

Copy `mcp.example.json` to a private `mcp.json` and set the server path for your
machine, or run `start_mcp.cmd` for stdio.
The MCP server requires the bridge DLL loaded in the Hammer tools process for live operations.
`python injector/inject_dll.py PID DLL_PATH` injects an explicit build.
An already loaded older bridge is not replaced by rebuilding; restart the editor after saving work before loading a new build.

`cs2_entity_create_brush` creates an entity, a box mesh and the parent relationship.
Use `dry_run=true` to validate without connecting. Creation records three native Undo steps.

`cs2_mesh_create_primitive` accepts Hammer Block Tool's five shape names:
`block`, `quad`, `cylinder`, `spike`, and `sphere`.
`quad` is a single XY face; the others are closed meshes. Set `size` in
world units, `segments` for the circumference, and `rings` for a sphere.
All creation tools record a native Undo step. Newly created welded meshes
restore their per-corner UVs after Hammer's vertex merge; cylinder and spike
sides unwrap continuously, and sphere faces use latitude/longitude UVs.
Set `tex_size` to the material texture's pixel dimension when it differs
from the default 512.

`cs2_module_interfaces` and `cs2_module_get_interface` also work with loaded
runtime DLLs that export `CreateInterface`, including `scenesystem`, `tier0`,
and `particles`. These tools list registered interfaces or request a named
interface. Editor-only ToolSystem and key-binding commands remain scoped to
Hammer, Material Editor, ModelDoc, and Particle Editor.

`cs2_editor_sessions(module="modeldoc")` lists validated ModelDoc sessions and marks
its active one. `cs2_bind_run` now resolves the active context automatically for
`ModelDocEditorSession` and `PetSession` commands after checking the session RTTI.
Use `module="pet"` after opening the Particle Editor. Other editor tool targets
still require an explicit `ctx` address. Calls remain dry runs until
`confirm=true` is provided. `cs2_modeldoc_action` and
`cs2_particle_editor_action` expose common native actions by simple names;
call either with an empty action to see its choices.

`cs2_modeldoc_open(path, confirm=true)` opens an existing text KV3 `.vmdl`
inside `content/csgo_addons/<addon>` in the running ModelDoc. It uses the
editor's native path-open method on the main thread and reads back the active
session, document, and root. Without `confirm=true`, it only previews the path.
For compiled Workshop `.vmdl_c` files, first use Source 2 Viewer CLI to extract
the `.vmdl` and its referenced mesh source into the active add-on content tree.
`cs2_asset_compile(path, confirm=true)` then runs CS2's installed resource
compiler for one add-on `.vmdl`, `.vmat`, or `.vpcf` and verifies that its
compiled output exists. It previews paths without `confirm=true`.

## Architecture

The Python implementation lives in `mcp_server/hammer_mcp/`. The original
`mcp_server/cs2_mcp_server.py` remains the compatible script/import entry point.
See [ARCHITECTURE.md](ARCHITECTURE.md) for module boundaries, session ownership,
structured editing results, and extension rules.
For the latest live-editor findings and next steps, see
[CURRENT_STATE.md](CURRENT_STATE.md).

Source-format and behavior references: [Source 2 Viewer](https://s2v.app) ([ValveResourceFormat](https://github.com/ValveResourceFormat/ValveResourceFormat)). Local reference coverage is recorded in [VRF_REFERENCE_NOTES.md](VRF_REFERENCE_NOTES.md).

按 DLL 拆分的 MCP 配置与固定 IDA 端口见 [MCP_MODULES.md](MCP_MODULES.md)。默认兼容入口仍可用，客户端已改为独立模块组。

## Soundevent 参考

[Soundevent 写法、函数与参数](SOUNDEVENT_REFERENCE.md) 包含本地 CS2 声音栈的公开参数声明及底层操作样本；完整注册 API 与未验证部分在文档中单独标明。

Codex 客户端配置见 [CODEX_SETUP.md](CODEX_SETUP.md)；可复制模板为 [config/codex.example.toml](config/codex.example.toml)。
