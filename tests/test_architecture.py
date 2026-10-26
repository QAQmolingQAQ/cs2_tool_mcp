import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))
from hammer_mcp.app import create_server, _bind_session
from hammer_mcp.session import BridgeSession, get_session
from hammer_mcp import diagnostics, runtime
from unittest.mock import patch


class ArchitectureTests(unittest.TestCase):
    def test_existing_tool_contracts_are_unchanged(self):
        expected = json.loads((ROOT / "tests/fixtures/tool_contract.json").read_text(encoding="utf-8"))
        actual = [t.model_dump(mode="json", exclude_none=True) for t in asyncio.run(create_server().list_tools())]
        new_names = ('cs2_mesh_create_prism', 'cs2_mesh_create_primitive', 'cs2_editor_sessions', 'cs2_editor_document', 'cs2_modeldoc_action', 'cs2_modeldoc_open', 'cs2_particle_editor_action', 'cs2_map_check', 'cs2_asset_tree', 'cs2_asset_compile', 'cs2_particle_functions', 'cs2_particle_function_info', 'cs2_particle_editor_tree', 'cs2_particle_editor_value', 'cs2_particle_editor_root_value', 'cs2_particle_editor_compare', 'cs2_particle_editor_open')
        new_names += ('cs2_build_artifact_check', 'cs2_project_info', 'cs2_edit_preflight', 'cs2_edit_preview', 'cs2_map_snapshot_compare', 'cs2_console_probe', 'cs2_runtime_stage_build', 'cs2_runtime_diagnostics', 'cs2_runtime_load_start', 'cs2_runtime_load_status', 'cs2_build_dependencies')
        new_names += ('cs2_build_start', 'cs2_build_status', 'cs2_build_cancel')
        new_names += ('cs2_session_selfcheck', 'cs2_hammer_layout_observe')
        new_names += ('cs2_map_io_check', 'cs2_qt_widgets', 'cs2_qt_open_editor', 'cs2_qt_menu_actions')
        new_names += ('cs2_qt_hammer_outliner',)
        new_names += ('cs2_qt_hammer_select',)
        new_names += ('cs2_hammer_property_fields',)
        new_names += ('cs2_edit_plan_recheck',)
        new_names += ('cs2_hammer_entity_identities',)
        added = [tool for tool in actual if tool['name'] in new_names]
        self.assertEqual(len(added), len(new_names))
        self.assertEqual([tool for tool in actual if tool['name'] not in new_names], expected)

    def test_sessions_and_all_caches_are_isolated_and_reset(self):
        first, second = BridgeSession(), BridgeSession()
        first.cache.hammer_base = 123
        first.cache.tool_modules["hammer"] = {"base": 123}
        first.cache.qt_menus["save"] = (1, 2)
        first.cache.symbol_names[1] = "stale"
        first.cache.dm_table = [1]
        first.cache.dm_table_key = (1, 2, 3, 4)
        default = get_session()
        with first.activate():
            self.assertIs(get_session(), first)
            self.assertIs(runtime._get_pipe(), first.pipe)
            with second.activate():
                self.assertIs(get_session(), second)
                self.assertIsNone(get_session().cache.hammer_base)
            self.assertIs(get_session(), first)
        self.assertIs(get_session(), default)
        first.close()
        self.assertEqual(first.cache, second.cache)

    def test_server_wrapper_serializes_entire_operations(self):
        session = BridgeSession()
        entries = []
        def edit(label):
            self.assertIs(get_session(), session)
            entries.append((label, "start"))
            time.sleep(0.01)
            entries.append((label, "end"))
        invoke = _bind_session(edit, session)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(invoke, (1, 2)))
        self.assertEqual(entries[0][0], entries[1][0])
        self.assertEqual(entries[2][0], entries[3][0])

    def test_initialize_invalidates_address_caches(self):
        session = BridgeSession()
        with session.activate(), patch.object(diagnostics, '_call', return_value='ok'):
            session.cache.hammer_base = 123
            session.cache.symbol_names[123] = 'stale'
            diagnostics.cs2_initialize()
            self.assertIsNone(session.cache.hammer_base)
            self.assertEqual(session.cache.symbol_names, {})

    def test_legacy_and_services_import_without_mcp_framework(self):
        script = r"""
import builtins, sys
sys.path.insert(0, 'mcp_server')
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'mcp' or name.startswith('mcp.'):
        raise AssertionError('service imported MCP framework')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import cs2_mcp_server as legacy
from hammer_mcp import entities, transport
assert legacy.cs2_entity_create is entities.cs2_entity_create
assert legacy.Cs2Pipe is transport.Cs2Pipe
assert legacy.cs2_entity_create_brush(dry_run=True)['ok']
"""
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_dependencies_are_acyclic(self):
        graph = {}
        for path in (ROOT / 'mcp_server/hammer_mcp').glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            graph[path.stem] = {n.module.split('.')[0] for n in ast.walk(tree)
                                if isinstance(n, ast.ImportFrom) and n.level and n.module}
        visiting, done = set(), set()
        def visit(name):
            self.assertNotIn(name, visiting, 'cyclic module dependency: ' + name)
            if name in done:
                return
            visiting.add(name)
            for dependency in graph.get(name, ()):
                visit(dependency)
            visiting.remove(name)
            done.add(name)
        for name in graph:
            visit(name)


if __name__ == '__main__':
    unittest.main()
