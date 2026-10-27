"""Real detached worker and Windows Job Object lifecycle tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from hammer_mcp import build_jobs
from hammer_mcp.build_process import CompilerProcess, process_identity
from hammer_mcp import build_process
from test_build_artifact import package, resource


@unittest.skipUnless(os.name == 'nt', 'Windows process tree ownership')
class BuildJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'game/content/csgo_addons/test/maps/example.vmap'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('test source')
        (self.root / 'game/game/csgo_addons/test').mkdir(parents=True)
        compiler = self.root / 'game/game/bin/win64/resourcecompiler.exe'
        compiler.parent.mkdir(parents=True)
        compiler.write_bytes(b'fixture executable identity')
        self.config = self.root / 'project.json'
        self.config.write_text(json.dumps({'version': 1, 'game_root': str(self.root / 'game'),
            'active_profile': 'test', 'state_root': str(self.root / 'jobs'),
            'profiles': {'test': {'addon': 'test', 'map': 'maps/example.vmap'}}}))
        self.jobs = []

    def tearDown(self):
        for job in self.jobs:
            result = build_jobs.cs2_build_cancel(job, str(self.config))
            if result.get('accepted'):
                self.wait(job)
        self.temp.cleanup()

    def wait(self, job):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = build_jobs.cs2_build_status(job, str(self.config))
            if result.get('status') in build_jobs.TERMINAL:
                return result
            time.sleep(0.05)
        self.fail(f'worker did not finish: {result}')

    def start(self, *, sleep=0.3, code=0, output=True, mode='quick'):
        original = build_jobs._plan

        def fake_plan(*args):
            plan = original(*args)
            fixture = self.root / (plan['job_id'] + '.vpk')
            prefix = 'maps/' + plan['map_name']
            package(fixture, {prefix + '.vmap_c': resource(), prefix + '/world.vwrld_c': resource(),
                              prefix + '/world_visibility.vvis_c': resource(b'VXVS')})
            script = f"import time,pathlib,shutil;print(\"... Building 'world'\",flush=True);time.sleep({sleep});"
            if output:
                destination=plan.get('compiled_artifact',plan['artifact'])
                script += f"p=pathlib.Path({destination!r});p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile({str(fixture)!r},p);"
            script += f'raise SystemExit({code})'
            plan['command'] = [sys.executable, '-c', script]
            return plan

        with patch.object(build_jobs, '_plan', side_effect=fake_plan):
            preview = build_jobs.cs2_build_start(mode, str(self.config))
            self.assertTrue(preview['ok'], preview)
            result = build_jobs.cs2_build_start(mode, str(self.config), confirm=True,
                                               expected_source_hash=preview['source_sha256'])
        self.assertTrue(result['ok'], result)
        self.jobs.append(result['job_id'])
        return result['job_id']

    def test_private_addon_copy_compiles_then_publishes_verified_artifact(self):
        data=json.loads(self.config.read_text());data['profiles']['test']['private_source_copy']=True
        self.config.write_text(json.dumps(data))
        job=self.start();result=self.wait(job)
        self.assertEqual(result['status'],'succeeded',result)
        self.assertTrue(result['private_copy_unchanged'])
        self.assertTrue(Path(result['artifact']).is_file())
        self.assertTrue(Path(result['compiled_artifact']).is_file())
        self.assertNotEqual(result['artifact'],result['compiled_artifact'])
        stages=[event['stage'] for event in result['events']]
        self.assertIn('copy_sources',stages);self.assertIn('publish',stages)
        self.assertEqual(self.source.read_text(),'test source')

    def test_private_copy_setting_requires_bool_nonrelease(self):
        data=json.loads(self.config.read_text())
        for private,release in (('true',False),(True,True)):
            data['profiles']['test'].update(private_source_copy=private,release=release)
            self.config.write_text(json.dumps(data))
            result=build_jobs.cs2_build_start(config=str(self.config))
            self.assertFalse(result['ok']);self.assertIn('private_source_copy',result['error'])

    def test_script_changed_while_compiler_runs_rejects_mixed_source_build(self):
        script=self.source.parent/'logic.js';script.write_text('before')
        job=self.start(sleep=2)
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            state=build_jobs.cs2_build_status(job,str(self.config),0)
            if state.get('compiler_pid'):break
            if state.get('status') in build_jobs.TERMINAL:self.fail(state)
            time.sleep(0.05)
        self.assertTrue(state.get('compiler_pid'),state)
        script.write_text('changed while compiler was running')
        result=self.wait(job)
        self.assertEqual(result['compiler_exit_code'],0)
        self.assertEqual(result['status'],'dependencies_changed',result)
        self.assertIn('maps/logic.js',result['dependency_changes']['changed'])
        self.assertFalse(result['dependency_guard_unchanged'])

    def test_durable_success_in_new_python_process(self):
        job = self.start()
        result = self.wait(job)
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(result['compiler_exit_code'], 0)
        self.assertTrue(result['process_tree_exited'])
        self.assertTrue(result['validation']['visibility'])
        code = ('from hammer_mcp.build_jobs import cs2_build_status;import json;'
                f'print(json.dumps(cs2_build_status({job!r},{str(self.config)!r},0)))')
        env = dict(os.environ, PYTHONPATH=str(Path(build_jobs.__file__).parents[1]))
        fresh = json.loads(subprocess.check_output([sys.executable, '-c', code], env=env))
        self.assertEqual(fresh['status'], 'succeeded')
        self.assertEqual(fresh['source_sha256'], result['source_sha256'])

    def test_flat_runtime_name_and_snapshot_collision_preserves_existing_file(self):
        original=build_jobs._plan
        snapshots=[]
        def collision(*args):
            plan=original(*args)
            self.assertRegex(plan['map_name'],r'^mcp_[0-9a-f]{24}$')
            snapshot=Path(plan['snapshot'])
            self.assertEqual(snapshot.parent,self.source.parent)
            self.assertNotEqual(snapshot,self.source)
            snapshot.write_bytes(b'owned by another operation')
            snapshots.append(snapshot)
            return plan
        with patch.object(build_jobs,'_plan',side_effect=collision):
            result=build_jobs.cs2_build_start(config=str(self.config),confirm=True,
                                             expected_source_hash=build_jobs.sha256(self.source))
        self.assertTrue(result['ok'],result)
        self.jobs.append(result['job_id'])
        terminal=self.wait(result['job_id'])
        self.assertEqual(terminal['status'],'failed')
        self.assertIn('FileExistsError',terminal['error'])
        self.assertEqual(snapshots[0].read_bytes(),b'owned by another operation')
        self.assertEqual(self.source.read_text(),'test source')

    def test_zero_exit_missing_artifact_and_full_missing_light_fail(self):
        result = self.wait(self.start(output=False))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['compiler_exit_code'], 0)
        result = self.wait(self.start(mode='full'))
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['validation']['lighting'])

    def test_cancel_duplicate_and_source_conflict(self):
        job = self.start(sleep=5)
        preview = build_jobs.cs2_build_start(config=str(self.config))
        duplicate = build_jobs.cs2_build_start(config=str(self.config), confirm=True,
                                               expected_source_hash=preview['source_sha256'])
        self.assertFalse(duplicate['ok'])
        self.assertEqual(duplicate['job_id'], job)
        self.assertTrue(build_jobs.cs2_build_cancel(job, str(self.config))['accepted'])
        self.assertEqual(self.wait(job)['status'], 'cancelled')
        job = self.start(sleep=1)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = build_jobs.cs2_build_status(job, str(self.config), 0)
            if state.get('compiler_pid'):
                break
            time.sleep(0.05)
        self.assertIn('compiler_pid', state)
        self.source.write_text('changed during compile')
        self.assertEqual(self.wait(job)['status'], 'source_changed')

    def test_job_terminates_descendant(self):
        child_file = self.root / 'child.json'
        child_code = 'import time;time.sleep(60)'
        parent_code = (f'import subprocess,sys,json,time; p=subprocess.Popen([sys.executable,"-c",{child_code!r}]);'
                       f'open({str(child_file)!r},"w").write(json.dumps(p.pid));time.sleep(60)')
        with (self.root / 'process.log').open('ab', buffering=0) as log:
            process = CompilerProcess([sys.executable, '-c', parent_code], str(self.root), dict(os.environ), log)
            try:
                deadline = time.monotonic() + 5
                while not child_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                child = json.loads(child_file.read_text())
                self.assertIsNotNone(process_identity(child))
                process.terminate()
                deadline = time.monotonic() + 5
                while process.active_count() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(process.active_count(), 0)
                deadline = time.monotonic() + 5
                while process_identity(child) is not None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertIsNone(process_identity(child))
                self.assertIsNotNone(process.poll())
            finally:
                process.close()

    def test_preview_hash_and_path_guards(self):
        result = build_jobs.cs2_build_start(config=str(self.config), confirm=True)
        self.assertFalse(result['ok'])
        self.assertFalse(build_jobs.cs2_build_status('../escape', str(self.config))['ok'])

    def test_worker_death_kills_owned_compiler(self):
        job = self.start(sleep=60)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = build_jobs.cs2_build_status(job, str(self.config), 0)
            if state.get('compiler_pid'):
                break
            time.sleep(0.05)
        self.assertIn('compiler_pid', state)
        kernel = build_process.kernel
        handle = kernel.OpenProcess(0x1 | 0x100000, False, state['worker_pid'])
        self.assertTrue(handle)
        try:
            self.assertTrue(kernel.TerminateProcess(handle, 99))
            self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
        finally:
            kernel.CloseHandle(handle)
        result = self.wait(job)
        self.assertEqual(result['status'], 'interrupted', result)
        deadline = time.monotonic() + 5
        while process_identity(state['compiler_pid']) == state['compiler_created'] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertNotEqual(process_identity(state['compiler_pid']), state['compiler_created'])

    def test_desktop_worker_survives_mcp_style_parent_job(self):
        identity_file = self.root / 'independent.json'
        child = [sys.executable, '-c', 'import time;time.sleep(60)']
        helper = (f'import sys,json,time;sys.path.insert(0,{str(Path(build_jobs.__file__).parents[1])!r});'
                  'from hammer_mcp.build_process import spawn_worker;'
                  f'identity=spawn_worker({child!r},{str(self.root)!r});'
                  f'open({str(identity_file)!r},"w").write(json.dumps(identity));time.sleep(60)')
        identity = None
        with (self.root / 'parent.log').open('ab', buffering=0) as log:
            parent = CompilerProcess([sys.executable, '-c', helper], str(self.root), dict(os.environ), log)
            try:
                deadline = time.monotonic() + 5
                while not identity_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                identity = json.loads(identity_file.read_text())
                parent.terminate()
                deadline = time.monotonic() + 5
                while parent.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertIsNotNone(parent.poll())
                self.assertEqual(process_identity(identity['pid']), identity['created'])
            finally:
                parent.close()
                if identity:
                    kernel = build_process.kernel
                    handle = kernel.OpenProcess(0x1 | 0x100000, False, identity['pid'])
                    if handle:
                        kernel.TerminateProcess(handle, 0)
                        kernel.WaitForSingleObject(handle, 5000)
                        kernel.CloseHandle(handle)


if __name__ == '__main__':
    unittest.main()
