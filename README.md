# Hammer MCP

Project root: `C:\codex\cs2_tool_mcp`.

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

## Architecture

The Python implementation lives in `mcp_server/hammer_mcp/`. The original
`mcp_server/cs2_mcp_server.py` remains the compatible script/import entry point.
See [ARCHITECTURE.md](ARCHITECTURE.md) for module boundaries, session ownership,
structured editing results, and extension rules.
