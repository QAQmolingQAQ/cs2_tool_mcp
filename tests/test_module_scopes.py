import asyncio
import inspect
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))
from hammer_mcp.app import create_server
from hammer_mcp.operation_lock import operation_lock
from hammer_mcp.scopes import SCOPES, select_tools, tool_owners

class ModuleScopeTests(unittest.TestCase):
    def test_inventory_and_no_editor_leaks(self):
        combined = set()
        for scope in SCOPES[1:]:
            names = {f.__name__ for f in select_tools(scope)}
            combined.update(names)
            self.assertEqual(names, {t.name for t in asyncio.run(create_server(scope=scope).list_tools())})
            if scope in ("met", "modeldoc_editor", "pet", "particles", "scenesystem", "tier0"):
                self.assertNotIn("cs2_entity_delete", names)
                self.assertNotIn("cs2_mesh_create_box", names)
        self.assertEqual(combined, {f.__name__ for f in select_tools()})
        self.assertIn("cs2_particle_editor_value", {f.__name__ for f in select_tools("pet")})
        self.assertNotIn("cs2_particle_editor_value", {f.__name__ for f in select_tools("met")})

    def test_bound_defaults_and_wrong_module_rejection(self):
        for scope in ("hammer", "met", "pet", "modeldoc_editor"):
            f = next(f for f in select_tools(scope) if f.__name__ == "cs2_bind_list")
            self.assertEqual(inspect.signature(f).parameters["module"].default, "modeldoc" if scope == "modeldoc_editor" else scope)
            with self.assertRaises(ValueError):
                f(module="incorrect")
        with self.assertRaises(ValueError):
            select_tools("unknown")

    def test_particle_functions_follow_target_dll(self):
        names = lambda scope: {f.__name__ for f in select_tools(scope)}
        self.assertIn("cs2_particle_set_definition", names("hammer"))
        self.assertNotIn("cs2_particle_set_definition", names("pet"))
        self.assertNotIn("cs2_particle_set_definition", names("particles"))
        self.assertIn("cs2_particle_function_info", names("particles"))
        self.assertNotIn("cs2_particle_function_info", names("pet"))
        self.assertEqual(tool_owners()["cs2_particle_set_definition"], "hammer")
        self.assertIn("cs2_asset_compile", names("bridge"))
        for scope in ("particles", "scenesystem", "tier0"):
            self.assertNotIn("cs2_bind_run", names(scope))
        for scope in ("assets", "runtime", "modeldoc"):
            with self.assertRaises(ValueError):
                select_tools(scope)

    @unittest.skipUnless(os.name == "nt", "Windows mutex")
    def test_mutex_across_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "acquired"
            code = """import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from hammer_mcp.operation_lock import operation_lock
print("waiting", flush=True)
with operation_lock(sys.argv[2]):
    Path(sys.argv[3]).write_text("yes")
"""
            pipe = "cs2_scope_test_" + str(os.getpid())
            with operation_lock(pipe):
                child = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "mcp_server"), pipe, str(file)],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.assertEqual(child.stdout.readline().strip(), "waiting")
                time.sleep(0.1)
                self.assertFalse(file.exists())
            _, error = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, error)
            self.assertTrue(file.exists())
