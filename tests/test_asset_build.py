"""The build helper must stay inside a CS2 add-on and verify output."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server"))
from hammer_mcp.asset_build import cs2_asset_compile


class AssetBuildTests(unittest.TestCase):
    def test_preview_and_successful_compile(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "Counter-Strike Global Offensive"
            compiler = root / "game" / "bin" / "win64" / "resourcecompiler.exe"
            compiler.parent.mkdir(parents=True)
            compiler.touch()
            source = root / "content" / "csgo_addons" / "test" / "models" / "sample.vmdl"
            source.parent.mkdir(parents=True)
            source.write_text("sample")
            compiled = root / "game" / "csgo_addons" / "test" / "models" / "sample.vmdl_c"
            compiled.parent.mkdir(parents=True)
            compiled.touch()
            with patch("hammer_mcp.asset_build.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "OK", "")) as run:
                preview = cs2_asset_compile(str(source))
                self.assertTrue(preview["preview"])
                run.assert_not_called()
                result = cs2_asset_compile(str(source), confirm=True)
                self.assertTrue(result["ok"])
                self.assertEqual(result["output"], str(compiled))
                self.assertEqual(run.call_args.args[0], [str(compiler), "-nop4", "-i", str(source)])

    def test_outside_addon_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.vmdl"
            source.touch()
            with patch("hammer_mcp.asset_build.subprocess.run") as run:
                self.assertFalse(cs2_asset_compile(str(source), confirm=True)["ok"])
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
