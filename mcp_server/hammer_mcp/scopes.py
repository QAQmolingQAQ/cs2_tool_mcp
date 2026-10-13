"""MCP inventories selected by target DLL, with explicit tool ownership."""
from __future__ import annotations
from functools import wraps
import inspect
import json
from pathlib import Path
from .registry import TOOL_FUNCTIONS

_MANIFEST = json.loads((Path(__file__).with_name("data") / "tool_ownership.json").read_text(encoding="utf-8"))
DLL_PROFILES = _MANIFEST["targets"]
SCOPES = ("all", *DLL_PROFILES, "bridge")
_EDITORS = {"hammer", "pet", "met", "modeldoc_editor"}
_COMMON = {"cs2_pipe_ping", "cs2_initialize"}
_EXPORT = {"cs2_module_interfaces", "cs2_module_get_interface"}
_EDITOR_API = {"cs2_bind_list", "cs2_bind_inspect", "cs2_bind_run",
               "cs2_module_bind_targets", "cs2_get_tool_system"}
_DOCUMENT = {"cs2_editor_document", "cs2_editor_sessions"}

def tool_owners() -> dict[str, str]:
    owners = {}
    for owner, names in _MANIFEST["owners"].items():
        for name in names:
            if name in owners:
                raise ValueError(f"Duplicate tool ownership: {name}")
            owners[name] = owner
    if set(owners) != {f.__name__ for f in TOOL_FUNCTIONS}:
        raise ValueError("DLL ownership manifest must cover every registered tool exactly once")
    return owners

def _bind_target(function, parameter, value):
    signature = inspect.signature(function)
    signature = signature.replace(parameters=[
        p.replace(kind=inspect.Parameter.KEYWORD_ONLY, default=value) if p.name == parameter
        else p.replace(kind=inspect.Parameter.KEYWORD_ONLY)
        for p in signature.parameters.values()
    ])
    @wraps(function)
    def bound(*args, **kwargs):
        values = signature.bind(*args, **kwargs)
        values.apply_defaults()
        if values.arguments[parameter] != value:
            raise ValueError(f"This MCP is bound to {value}; use that DLL's server")
        return function(*values.args, **values.kwargs)
    bound.__signature__ = signature
    return bound

def select_tools(scope: str = "all") -> tuple:
    if scope not in SCOPES:
        raise ValueError(f"unknown DLL MCP scope: {scope}")
    owners = tool_owners()
    if scope == "all":
        return TOOL_FUNCTIONS
    selected = []
    module = "modeldoc" if scope == "modeldoc_editor" else scope
    for function in TOOL_FUNCTIONS:
        name = function.__name__
        if scope in DLL_PROFILES and name == "cs2_get_module":
            selected.append(_bind_target(function, "name", DLL_PROFILES[scope]))
        elif scope in DLL_PROFILES and name in _EXPORT:
            selected.append(_bind_target(function, "module", module))
        elif scope in _EDITORS and name in _EDITOR_API:
            selected.append(_bind_target(function, "module", module))
        elif scope in ("pet", "modeldoc_editor") and name in _DOCUMENT:
            selected.append(_bind_target(function, "module", module))
        elif name in _COMMON or owners[name] == scope:
            selected.append(function)
    return tuple(selected)
