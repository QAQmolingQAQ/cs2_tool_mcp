from .build_dependencies import cs2_build_dependencies
from .runtime_load import cs2_runtime_load_start, cs2_runtime_load_status
from .runtime_diagnostics import cs2_runtime_diagnostics
from .runtime_stage import cs2_runtime_stage_build
from .vconsole import cs2_console_probe
from .map_compare import cs2_map_snapshot_compare
from .edit_preview import cs2_edit_preview, cs2_edit_plan_recheck
from .outliner_identity import cs2_hammer_entity_identities
from .property_fields import cs2_hammer_property_fields
from .edit_preflight import cs2_edit_preflight
"""Explicit MCP tool inventory. Services do not import the MCP framework."""
from .build_artifact import cs2_build_artifact_check
from .project import cs2_project_info
from .build_jobs import cs2_build_start, cs2_build_status, cs2_build_cancel
from .session_check import cs2_session_selfcheck
from .map_io_check import cs2_map_io_check
from .hammer_layout import cs2_hammer_layout_observe
from .qt_diagnostics import cs2_qt_widgets, cs2_qt_open_editor, cs2_qt_menu_actions, cs2_qt_hammer_outliner, cs2_qt_hammer_select
from .automation import (
    cs2_entity_create_brush,
)
from .asset_tree import (
    cs2_asset_tree,
)
from .asset_build import (
    cs2_asset_compile,
)
from .bindings import (
    cs2_bind_list,
    cs2_bind_inspect,
    cs2_bind_run,
    cs2_editor_sessions,
    cs2_editor_document,
    cs2_sel,
)
from .editor_actions import (
    cs2_modeldoc_action,
    cs2_modeldoc_open,
    cs2_particle_editor_action,
)
from .diagnostics import (
    cs2_pipe_ping,
    cs2_hammer_status,
    cs2_initialize,
    cs2_list_tools,
    cs2_list_interfaces,
    cs2_get_interface,
    cs2_list_modules,
    cs2_get_module,
    cs2_tool_modules,
    cs2_get_tool_system,
    cs2_module_interfaces,
    cs2_module_get_interface,
    cs2_module_bind_targets,
    cs2_read_memory,
    cs2_read_qword,
    cs2_read_value,
    cs2_write_value,
    cs2_read_string,
    cs2_read_ptr_chain,
    cs2_find_pattern,
    cs2_call_function,
    cs2_call_virtual,
    cs2_map_list_docs,
    cs2_get_hammer_app,
    cs2_mem_scan,
    cs2_find_by_vtable,
)
from .entities import (
    cs2_entity_list,
    cs2_entity_get_meshes,
    cs2_entity_attach_mesh,
    cs2_entity_get_transform,
    cs2_entity_get_attr,
    cs2_entity_find_attr,
    cs2_entity_attrs,
    cs2_entity_remove_attr,
    cs2_entity_set_attr,
    cs2_entity_set_transform,
    cs2_entity_create,
    cs2_entity_delete,
    cs2_entity_set_classname,
)
from .entity_io import (
    cs2_entity_get_io,
    cs2_entity_add_io,
    cs2_entity_remove_io,
)
from .history import (
    cs2_undo,
    cs2_redo,
    cs2_map_undo,
    cs2_map_redo,
)
from .maps import (
    cs2_map_info,
    cs2_map_check,
    cs2_map_groups,
    cs2_map_save,
    cs2_area_query,
)
from .meshes import (
    cs2_mesh_scale,
    cs2_mesh_weld_vertices,
    cs2_mesh_create_box,
    cs2_mesh_create_arch,
    cs2_mesh_create_prism,
    cs2_mesh_create_primitive,
    cs2_mesh_list,
    cs2_mesh_get_geometry,
)
from .particle_editor_open import (
    cs2_particle_editor_open,
)
from .particle_editor_tree import (
    cs2_particle_editor_tree,
)
from .particle_editor_root import (
    cs2_particle_editor_root_value,
)
from .particle_editor_value import (
    cs2_particle_editor_value,
)
from .particle_editor_compare import (
    cs2_particle_editor_compare,
)
from .particle_catalog import (
    cs2_particle_functions,
    cs2_particle_function_info,
)
from .particles import (
    cs2_particle_set_definition,
)
TOOL_FUNCTIONS = (
    cs2_build_dependencies,
    cs2_runtime_load_start,
    cs2_runtime_load_status,
    cs2_runtime_diagnostics,
    cs2_runtime_stage_build,
    cs2_console_probe,
    cs2_map_snapshot_compare,
    cs2_edit_preview,
    cs2_edit_plan_recheck,
    cs2_hammer_entity_identities,
    cs2_hammer_property_fields,
    cs2_edit_preflight,
    cs2_hammer_layout_observe,
    cs2_qt_widgets,
    cs2_qt_hammer_outliner,
    cs2_qt_hammer_select,
    cs2_qt_open_editor,
    cs2_qt_menu_actions,
    cs2_map_io_check,
    cs2_session_selfcheck,
    cs2_build_start,
    cs2_build_status,
    cs2_build_cancel,
    cs2_build_artifact_check,
    cs2_project_info,
    cs2_asset_compile,
    cs2_asset_tree,
    cs2_pipe_ping,
    cs2_hammer_status,
    cs2_initialize,
    cs2_list_tools,
    cs2_list_interfaces,
    cs2_get_interface,
    cs2_list_modules,
    cs2_get_module,
    cs2_tool_modules,
    cs2_get_tool_system,
    cs2_module_interfaces,
    cs2_module_get_interface,
    cs2_module_bind_targets,
    cs2_read_memory,
    cs2_read_qword,
    cs2_read_value,
    cs2_write_value,
    cs2_read_string,
    cs2_read_ptr_chain,
    cs2_find_pattern,
    cs2_call_function,
    cs2_call_virtual,
    cs2_undo,
    cs2_redo,
    cs2_map_list_docs,
    cs2_get_hammer_app,
    cs2_map_undo,
    cs2_map_redo,
    cs2_map_info,
    cs2_map_check,
    cs2_map_groups,
    cs2_map_save,
    cs2_entity_list,
    cs2_entity_get_meshes,
    cs2_entity_attach_mesh,
    cs2_entity_create_brush,
    cs2_entity_get_transform,
    cs2_entity_get_attr,
    cs2_entity_find_attr,
    cs2_entity_attrs,
    cs2_entity_remove_attr,
    cs2_entity_set_attr,
    cs2_entity_set_transform,
    cs2_mem_scan,
    cs2_find_by_vtable,
    cs2_entity_get_io,
    cs2_entity_add_io,
    cs2_entity_remove_io,
    cs2_mesh_scale,
    cs2_mesh_weld_vertices,
    cs2_mesh_create_box,
    cs2_mesh_create_arch,
    cs2_mesh_create_prism,
    cs2_mesh_create_primitive,
    cs2_bind_list,
    cs2_bind_inspect,
    cs2_bind_run,
    cs2_editor_sessions,
    cs2_editor_document,
    cs2_modeldoc_action,
    cs2_modeldoc_open,
    cs2_particle_editor_action,
    cs2_sel,
    cs2_area_query,
    cs2_mesh_list,
    cs2_mesh_get_geometry,
    cs2_entity_create,
    cs2_entity_delete,
    cs2_entity_set_classname,
    cs2_particle_set_definition,
    cs2_particle_functions,
    cs2_particle_function_info,
    cs2_particle_editor_tree,
    cs2_particle_editor_value,
    cs2_particle_editor_root_value,
    cs2_particle_editor_compare,
    cs2_particle_editor_open,
)
