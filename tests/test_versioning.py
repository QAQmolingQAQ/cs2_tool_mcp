"""Version mismatch must stop native requests before their frame is written."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp.versioning import evaluate_native, NativeVersionError, implementation_hash
from hammer_mcp.transport import Cs2Pipe
from test_transport import FakePipe


class GatedFakePipe(FakePipe):
    _authorize = Cs2Pipe._authorize


class VersioningTests(unittest.TestCase):
    def fixture(self):
        modules = {name: {'sha256': name + '-hash', 'loaded_matches_disk_headers': True}
                   for name in ('cs2.exe', 'cs2_tool.dll', 'hammer.dll')}
        live = {'pid': 123, 'modules': modules}
        bridge = {'pid': 123, 'bridge_version': 'test', 'bridge_api_version': 1, 'protocol_version': 1}
        profile = {'id': 'fixture', 'source_revision': '12345', 'bridge_version': 'test',
                   'implementation_sha256': 'implementation', 'verification': 'write_readback_undo_redo',
                   'evidence': 'isolated test fixture', 'module_hashes': {name: value['sha256'] for name, value in modules.items()},
                   'allowed_methods': ['write_value', 'call_function']}
        return {'SourceRevision': '12345'}, live, bridge, profile

    def test_matching_fixture_and_every_identity_mismatch(self):
        version, live, bridge, profile = self.fixture()
        self.assertTrue(evaluate_native(version, live, bridge, 'implementation', [profile])['writes_enabled'])
        for field, value in (('source_revision', 'old'), ('bridge_version', 'old'),
                             ('implementation_sha256', 'old'), ('verification', 'static_only'), ('evidence', '')):
            changed = {**profile, field: value}
            self.assertFalse(evaluate_native(version, live, bridge, 'implementation', [changed])['writes_enabled'])
        for changed in ({**bridge, 'pid': 124}, {**bridge, 'bridge_api_version': 0}, {**bridge, 'protocol_version': 0}):
            self.assertFalse(evaluate_native(version, live, changed, 'implementation', [profile])['writes_enabled'])
        changed = copy.deepcopy(live)
        changed['modules']['hammer.dll']['loaded_matches_disk_headers'] = False
        self.assertFalse(evaluate_native(version, changed, bridge, 'implementation', [profile])['writes_enabled'])
        changed['modules']['hammer.dll'] = {'sha256': 'updated', 'loaded_matches_disk_headers': True}
        self.assertFalse(evaluate_native(version, changed, bridge, 'implementation', [profile])['writes_enabled'])

    def test_unregistered_loaded_dependency_blocks_and_observation_never_approves(self):
        version, live, bridge, profile = self.fixture()
        self.assertFalse(evaluate_native(version, live, bridge, 'implementation', [])['writes_enabled'])
        live['modules']['qt5widgets.dll'] = {'sha256': 'new', 'loaded_matches_disk_headers': True}
        self.assertFalse(evaluate_native(version, live, bridge, 'implementation', [profile])['writes_enabled'])

    def test_blocked_native_frame_is_never_written(self):
        pipe = GatedFakePipe()
        with patch('hammer_mcp.versioning.inspect_live', return_value={'writes_enabled': False, 'allowed_methods': []}):
            for method in ('write_value', 'call_function', 'write_memory', 'alloc_memory', 'initialize', 'map_list_docs', 'future_mutation'):
                with self.assertRaisesRegex(NativeVersionError, 'blocked before dispatch'):
                    pipe.call(method, {})
        self.assertEqual(pipe.writes, [])
        pipe.call('ping')
        self.assertEqual(len(pipe.writes), 1)

    def test_fixed_selftest_needs_no_offset_profile(self):
        pipe = GatedFakePipe()
        with patch('hammer_mcp.versioning.inspect_live', side_effect=AssertionError('must not inspect offsets')):
            pipe.call('main_thread_selftest', {})
        self.assertEqual(len(pipe.writes), 1)

    def test_fixed_ui_adapter_is_distinct_from_arbitrary_native_calls(self):
        pipe = GatedFakePipe()
        with patch('hammer_mcp.versioning.inspect_live', side_effect=AssertionError('Qt adapter has its own fixed ABI guard')):
            pipe.call('qt_open_editor', {'editor':'hammer','confirm':False})
        self.assertEqual(len(pipe.writes), 1)
        with patch('hammer_mcp.versioning.inspect_live', return_value={'writes_enabled':False,'allowed_methods':[]}):
            with self.assertRaises(NativeVersionError):pipe.call('call_function', {})
        self.assertEqual(len(pipe.writes), 1)

    def test_permission_is_method_specific(self):
        pipe = GatedFakePipe()
        with patch('hammer_mcp.versioning.inspect_live', return_value={'writes_enabled': True, 'allowed_methods': ['write_value'],
                'profile': 'fixture', 'live': {'pid': 123}, 'implementation_sha256': 'a' * 64}):
            with self.assertRaises(NativeVersionError):
                pipe.call('call_function', {})
            self.assertEqual(pipe.call('write_value', {})['result']['status'], 'ok')
        self.assertEqual(len(pipe.writes), 1)

    def test_implementation_digest_is_reproducible(self):
        self.assertEqual(implementation_hash(), implementation_hash())
        self.assertEqual(len(implementation_hash()), 64)


if __name__ == '__main__':
    unittest.main()
