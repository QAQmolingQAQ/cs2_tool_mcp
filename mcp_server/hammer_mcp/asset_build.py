"""Build one source asset with the installed CS2 resource compiler."""
from __future__ import annotations

from pathlib import Path
import subprocess


_BUILDABLE = {".vmdl", ".vmat", ".vpcf"}


def _paths(path: str) -> tuple[Path, Path, Path]:
    source = Path(path).resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in _BUILDABLE:
        raise ValueError("path must name an existing .vmdl, .vmat, or .vpcf")
    parts = source.parts
    lowered = [part.lower() for part in parts]
    for index in range(len(parts) - 3):
        if lowered[index:index + 2] == ["content", "csgo_addons"]:
            game_root = Path(*parts[:index])
            addon = parts[index + 2]
            relative = Path(*parts[index + 3:])
            compiler = game_root / "game" / "bin" / "win64" / "resourcecompiler.exe"
            compiled = game_root / "game" / "csgo_addons" / addon / relative
            compiled = compiled.with_suffix(source.suffix + "_c")
            if not compiler.is_file():
                raise FileNotFoundError(f"CS2 resource compiler not found: {compiler}")
            return source, compiler, compiled
    raise ValueError("source must be inside content/csgo_addons/<addon>")


def cs2_asset_compile(path: str, confirm: bool = False) -> dict:
    """Compile one add-on model, material, or particle source with CS2.

    Defaults to a preview. When confirmed, runs the installed resourcecompiler
    with `-nop4`, then checks both its exit code and the compiled output file.
    This does not publish or upload the asset.
    """
    try:
        source, compiler, compiled = _paths(path)
        if not confirm:
            return {"ok": True, "preview": True, "source": str(source),
                    "output": str(compiled), "compiler": str(compiler)}
        process = subprocess.run(
            [str(compiler), "-nop4", "-i", str(source)],
            capture_output=True, text=True, errors="replace", timeout=120,
            check=False,
        )
        output = (process.stdout + "\n" + process.stderr).strip()
        exists = compiled.is_file()
        return {"ok": process.returncode == 0 and exists,
                "source": str(source), "output": str(compiled),
                "output_exists": exists, "exit_code": process.returncode,
                "log_tail": output[-5000:]}
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "source": path,
                "error": f"{type(error).__name__}: {error}"}
