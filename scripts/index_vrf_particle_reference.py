"""Index local VRF particle implementations against the versioned CS2 catalog."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

def generate(vrf: Path, catalog: Path) -> dict:
    data = json.loads(catalog.read_text(encoding="utf-8"))
    factory = vrf / "ValveResourceFormat/Particles/ParticleControllerFactory.cs"
    renderer = vrf / "Renderer/Particles/ParticleRendererFactory.cs"
    text = factory.read_text(encoding="utf-8")
    implementations = dict(re.findall(
        r'\["(C_[A-Za-z0-9_]+)"\]\s*=\s*[^\n]*?=>\s*new\s+([A-Za-z0-9_.]+)\(', text))
    implementations.update(re.findall(
        r'"(C_[A-Za-z0-9_]+)"\s*=>\s*new\s+([A-Za-z0-9_.]+)\(',
        renderer.read_text(encoding="utf-8")))
    folders = ["PreEmissionOperators", "Emitters", "Initializers", "Operators",
               "ForceGenerators", "Constraints"]
    rows = []
    for row in data["functions"]:
        name = row["class_name"]
        implementation = implementations.get(name)
        entry = {"class_name": name, "category": row["category"],
                 "has_vrf_factory_implementation": implementation is not None}
        if implementation:
            folder = ("Renderer/Particles/Renderers" if row["category"] == 6 else
                      "ValveResourceFormat/Particles/" + folders[row["category"]])
            path = folder + "/" + implementation.split(".")[-1] + ".cs"
            file = vrf / path
            if not file.is_file():
                pattern = r"\bclass\s+" + re.escape(implementation.split(".")[-1]) + r"\b"
                matches = [f for f in (vrf / folder).glob("*.cs")
                           if re.search(pattern, f.read_text(encoding="utf-8"))]
                if len(matches) == 1:
                    file = matches[0]
                    path = file.relative_to(vrf).as_posix()
            entry.update({"implementation_class": implementation, "source_file": path,
                          "source_file_found": file.is_file()})
            if file.is_file():
                source = file.read_text(encoding="utf-8")
                entry["mentioned_parameter_names"] = sorted(set(re.findall(r'"(m_[A-Za-z0-9_]+)"', source)))
                entry["source_sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
        rows.append(entry)
    head = subprocess.run(["git", "-C", str(vrf), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    status = subprocess.run(["git", "-C", str(vrf), "status", "--porcelain"],
                            capture_output=True, text=True)
    return {"reference_project": "ValveResourceFormat / Source 2 Viewer",
            "reference_url": "https://github.com/ValveResourceFormat/ValveResourceFormat",
            "reference_commit": head.stdout.strip() if head.returncode == 0 else None,
            "reference_worktree_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
            "catalog_sha256": data["sha256"],
            "scope": "Source-code references; not native CS2 behavior or editor-write verification",
            "registered_count": len(rows),
            "referenced_count": sum(r["has_vrf_factory_implementation"] for r in rows),
            "functions": rows}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("vrf", type=Path)
    parser.add_argument("--output", type=Path, default=Path("VRF_PARTICLE_REFERENCE.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = generate(args.vrf, root / "mcp_server/hammer_mcp/data/particle_functions.json")
    assert result["registered_count"] == 376
    assert all(r.get("source_file_found", True) for r in result["functions"])
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f'{result["referenced_count"]}/{result["registered_count"]} function source references')

if __name__ == "__main__":
    main()
