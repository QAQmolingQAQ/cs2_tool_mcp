"""Hammer automation operations."""
from __future__ import annotations
import math
from typing import Any
from .datamodel import (
    _dm_table,
    _entity_get_attrs,
)
from .entities import (
    attach_mesh,
    create_entity,
)
from .geometry import (
    _parse_vec3_arg,
    _poly_ready,
)
from .meshes import (
    create_box,
)
from .scene import (
    _element_doc_strict,
    _entity_meshes,
    _map_doc,
)


def cs2_entity_create_brush(classname: str = "func_brush", center: str = "0 0 0",
                            size: str = "32 32 32", material: str = "materials/tools/toolsnodraw.vmat",
                            name: str = "cs2_brush", doc: str = "", dry_run: bool = False) -> dict[str, Any]:
    """Create entity + box mesh + attach, for func_button/func_brush/trigger.

    dry_run validates without connecting. center is mesh world center; entity uses default transform.
    Multiple native Undo steps. Stops on failure, returns partial addresses; no retry, rollback or save.
    Custom classes require FGD support. Inspect steps and Undo before retrying a failed operation.
    """
    result = dict(ok=False, stage="validate", entity=None, mesh=None, steps=[])
    try:
        if not classname.strip() or any(c.isspace() for c in classname):
            raise ValueError("classname must be nonempty without whitespace")
        ctr = _parse_vec3_arg(center, "center")
        sz = _parse_vec3_arg(" ".join([size.strip()] * 3) if len(size.split()) == 1 else size, "size")
        if not all(math.isfinite(x) for x in (*ctr, *sz)) or min(sz) <= 0:
            raise ValueError("center/size must be finite; size must be positive")
        if not material.strip() or any(chr(0) in x for x in (classname, material, name)):
            raise ValueError("empty material or NUL in strings")
        result["plan"] = dict(classname=classname, center=ctr, size=sz, material=material, name=name, doc=doc)
        if dry_run:
            result.update(ok=True, stage="planned")
            return result
        target_doc = _map_doc(doc)
        for stage, make in (
            ("entity", lambda: create_entity(classname=classname, name=name, document=target_doc)),
            ("mesh", lambda: create_box(center=center, size=size, material=material,
                                       name=name + "_mesh", document=target_doc))):
            result["stage"] = "create_" + stage
            created = make()
            result["steps"].append(created.report)
            if created.element:
                result[stage] = hex(created.element)
            if not created.ok or not created.element:
                raise RuntimeError("creation failed: " + stage + "; " + created.report)
            el = created.element
            if _element_doc_strict(el) != target_doc:
                raise RuntimeError("created object not in target document")
            if stage == "entity" and _entity_get_attrs(el, ["classname"]).get("classname") != classname:
                raise RuntimeError("classname readback mismatch")
            if stage == "mesh" and not _poly_ready(el):
                raise RuntimeError("mesh geometry not ready")
        result["stage"] = "attach_mesh"
        attached = attach_mesh(entity=result["entity"], mesh=result["mesh"])
        result["steps"].append(attached.report)
        if not attached.ok:
            raise RuntimeError(attached.report)
        if int(result["mesh"], 16) not in _entity_meshes(int(result["entity"], 16), *_dm_table()):
            raise RuntimeError("mesh ownership readback mismatch")
        result.update(ok=True, stage="complete", undo="Multiple Ctrl+Z steps; not saved")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["recovery"] = "Stopped; inspect partial addresses and native Undo history before retrying"
    return result
