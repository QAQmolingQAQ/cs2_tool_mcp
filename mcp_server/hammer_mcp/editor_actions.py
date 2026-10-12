"""Named ModelDoc and Particle Editor actions backed by native bind commands."""
from __future__ import annotations

from .bindings import cs2_bind_run


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


def cs2_particle_editor_action(action: str = "", confirm: bool = False) -> str:
    """Run a named Particle Editor action on the active particle document.

    Empty `action` lists choices. Execution requires `confirm=True`; the default
    previews the native command. Includes preview/simulation control, Undo/Redo,
    and function/child creation. This controls the Particle Editor (`pet.dll`),
    separate from Hammer's `info_particle_system` entity tools.
    """
    return _action("pet", _PARTICLE_ACTIONS, action, confirm)
