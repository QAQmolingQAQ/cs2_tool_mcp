"""Named ModelDoc and Particle Editor actions backed by native bind commands."""
from __future__ import annotations

from pathlib import Path

from .bindings import cs2_bind_run, cs2_editor_document, _tool_module
from .session import get_session


_MODELDOC_ACTIONS = {
    "new": ("ModelDocEditorApp", "FileNew"),
    "open": ("ModelDocEditorApp", "FileOpen"),
    "save": ("ModelDocEditorApp", "FileSave"),
    "save_as": ("ModelDocEditorApp", "FileSaveAs"),
    "import_fbx": ("ModelDocEditorApp", "ImportFromFBX"),
    "import_vmdl": ("ModelDocEditorApp", "ImportFromVMDL"),
    "undo": ("ModelDocEditorSession", "Undo"),
    "redo": ("ModelDocEditorSession", "Redo"),
    "select_mode": ("ModelDocEditorSession", "SetManipulationMode_Selection"),
    "translate_mode": ("ModelDocEditorSession", "SetManipulationMode_Translate"),
    "rotate_mode": ("ModelDocEditorSession", "SetManipulationMode_Rotate"),
    "scale_mode": ("ModelDocEditorSession", "SetManipulationMode_Scale"),
    "world_space": ("ModelDocEditorSession", "SetManipulationSpace_World"),
    "local_space": ("ModelDocEditorSession", "SetManipulationSpace_Local"),
    "duplicate_selected": ("ModelDocEditorSession", "DuplicateSelectedNodes"),
    "delete_selected": ("ModelDocEditorSession", "DeleteSelectedNodes"),
    "list_references": ("ModelDocEditorSession", "ListFileReferences"),
    "check_compile": ("ModelDocEditorSession", "SanityCheckCompileState"),
}

_PARTICLE_ACTIONS = {
    "new": ("PetApp", "FileNew"),
    "open": ("PetApp", "FileOpen"),
    "save": ("PetApp", "FileSave"),
    "save_as": ("PetApp", "FileSaveAs"),
    "save_all": ("PetApp", "FileSaveAll"),
    "restart_preview": ("PetApp", "RestartPreview"),
    "restart_global": ("PetApp", "RestartGlobal"),
    "stop_simulation": ("PetApp", "StopSim"),
    "stop_with_endcap": ("PetApp", "StopSimWithEndcap"),
    "undo": ("PetSession", "Undo"),
    "redo": ("PetSession", "Redo"),
    "add_function": ("PetSession", "AddFunction"),
    "add_child": ("PetSession", "AddChild"),
    "add_new_child": ("PetSession", "AddNewChild"),
    "delete_selected": ("PetSession", "Delete"),
}


def _action(module: str, actions: dict[str, tuple[str, str]], action: str, confirm: bool) -> str:
    key = action.strip().lower()
    if not key:
        return f"{module} actions: " + ", ".join(actions)
    binding = actions.get(key)
    if binding is None:
        return f"ERROR unknown {module} action {action!r}; choose: " + ", ".join(actions)
    target, command = binding
    return cs2_bind_run(module, target, command, confirm=confirm)


def cs2_modeldoc_action(action: str = "", confirm: bool = False) -> str:
    """Run a named ModelDoc model-editing action on the active document.

    Empty `action` lists choices. Execution requires `confirm=True`; the default
    previews the native command without changing the model. Selection, transform
    mode, Undo/Redo, duplication, references and compile checks are available.
    """
    return _action("modeldoc", _MODELDOC_ACTIONS, action, confirm)


def cs2_modeldoc_open(path: str, confirm: bool = False) -> dict:
    """Open an existing add-on .vmdl in the live ModelDoc editor by path.

    This invokes CModelDocEditorApp's native file-open virtual method on the
    main thread, avoiding an interactive file dialog. The source file must be
    inside a CS2 add-on content tree. Preview is the default; confirm=True
    performs the open and reads back the active document/root.
    """
    try:
        source = Path(path).resolve(strict=True)
        if not source.is_file() or source.suffix.lower() != ".vmdl":
            raise ValueError("path must name an existing .vmdl file")
        parts = [part.lower() for part in source.parts]
        if not any(parts[i:i + 2] == ["content", "csgo_addons"]
                   and len(parts) > i + 3 for i in range(len(parts) - 1)):
            raise ValueError("source must be inside content/csgo_addons/<addon>")
        with source.open("rb") as handle:
            header = handle.read(256).lstrip().lower()
        if not header.startswith(b"<!-- kv3 ") or b"format:modeldoc" not in header:
            raise ValueError("source is not a text KV3 ModelDoc file")
        if not confirm:
            return {"ok": True, "preview": True, "path": str(source),
                    "action": "open in active ModelDoc"}
        module = _tool_module("modeldoc")
        if module.get("cls") != "CModelDocEditorApp" or not module.get("tool_system"):
            raise RuntimeError("ModelDoc App RTTI validation failed")
        response = get_session().pipe.call("call_virtual", {
            "this": hex(module["tool_system"]), "vtable_offset": 144,
            "args": ["str:" + str(source), 1], "on_main_thread": True,
            "timeout_ms": 20000,
        })
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        result = response["result"]
        if result.get("main_thread_status") != 0 or not result.get("ret"):
            raise RuntimeError(f"native open failed: {result}")
        document = cs2_editor_document("modeldoc")
        if not document.get("ok") or int(document["session"], 16) != int(result["ret"]):
            raise RuntimeError(f"opened session could not be read back: {document}")
        return {"ok": True, "path": str(source), "session": document["session"],
                "document": document["document"], "root": document["root"]}
    except (OSError, ConnectionError, RuntimeError, ValueError, KeyError) as error:
        return {"ok": False, "path": path,
                "error": f"{type(error).__name__}: {error}"}


def cs2_particle_editor_action(action: str = "", confirm: bool = False) -> str:
    """Run a named Particle Editor action on the active particle document.

    Empty `action` lists choices. Execution requires `confirm=True`; the default
    previews the native command. Includes preview/simulation control, Undo/Redo,
    and function/child creation. This controls the Particle Editor (`pet.dll`),
    separate from Hammer's `info_particle_system` entity tools.
    """
    return _action("pet", _PARTICLE_ACTIONS, action, confirm)
