"""Module-specific MCP inventories over the shared bridge services."""
from __future__ import annotations
from functools import wraps
import inspect
from .registry import TOOL_FUNCTIONS

SCOPES = ("all", "hammer", "pet", "met", "modeldoc", "assets", "runtime")
_COMMON = {"cs2_pipe_ping", "cs2_initialize", "cs2_tool_modules"}
_MODULE = {"cs2_bind_list", "cs2_bind_inspect", "cs2_bind_run",
           "cs2_module_interfaces", "cs2_module_get_interface", "cs2_module_bind_targets"}
_DOCUMENT = {"cs2_editor_document", "cs2_editor_sessions"}
_HAMMER_SERVICES = {"automation", "entities", "entity_io", "history", "maps", "meshes", "particles"}
_HAMMER_DIAGNOSTICS = {"cs2_hammer_status", "cs2_map_list_docs", "cs2_get_hammer_app"}
_PET = {"cs2_particle_editor_action", "cs2_particle_editor_open", "cs2_particle_editor_tree",
        "cs2_particle_editor_value", "cs2_particle_editor_compare",
        "cs2_particle_functions", "cs2_particle_function_info"}
_MODEL = {"cs2_modeldoc_action", "cs2_modeldoc_open"}
_ASSET = {"cs2_asset_tree", "cs2_asset_compile"}

def _owner(function) -> str:
    name = function.__name__
    service = function.__module__.rsplit(".", 1)[-1]
    if service in _HAMMER_SERVICES or name in _HAMMER_DIAGNOSTICS or name == "cs2_sel":
        return "hammer"
    if name in _PET:
        return "pet"
    if name in _MODEL:
        return "modeldoc"
    if name in _ASSET:
        return "assets"
    return "runtime"

def _bind_module(function, module):
    signature = inspect.signature(function)
    if "module" not in signature.parameters:
        raise ValueError(f"{function.__name__} has no module argument")
    signature = signature.replace(parameters=[
        p.replace(kind=inspect.Parameter.KEYWORD_ONLY, default=module) if p.name == "module"
        else p.replace(kind=inspect.Parameter.KEYWORD_ONLY)
        for p in signature.parameters.values()
    ])
    @wraps(function)
    def bound(*args, **kwargs):
        values = signature.bind(*args, **kwargs)
        values.apply_defaults()
        if values.arguments["module"] != module:
            raise ValueError(f"This MCP is bound to {module}; use that module's server")
        return function(*values.args, **values.kwargs)
    bound.__signature__ = signature
    return bound

def select_tools(scope: str = "all") -> tuple:
    if scope not in SCOPES:
        raise ValueError(f"unknown MCP scope: {scope}")
    if scope == "all":
        return TOOL_FUNCTIONS
    selected = []
    for function in TOOL_FUNCTIONS:
        name = function.__name__
        if name in _MODULE and scope in ("hammer", "pet", "met", "modeldoc"):
            selected.append(_bind_module(function, scope))
        elif name in _DOCUMENT and scope in ("pet", "modeldoc"):
            selected.append(_bind_module(function, scope))
        elif name in _COMMON or _owner(function) == scope:
            selected.append(function)
    return tuple(selected)
