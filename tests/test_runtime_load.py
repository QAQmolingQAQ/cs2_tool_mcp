import json
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp import runtime_load as rl
from hammer_mcp.project import sha256
from hammer_mcp.vconsole import HEADER


class RuntimeLoadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'source.vmap';self.source.write_bytes(b'source')
        self.config=self.root/'project.json';self.config.write_text('{}')
        self.artifact=self.root/'map.vpk';self.artifact.write_bytes(b'artifact')
        self.project={'source':str(self.source),'config_path':str(self.config),'profile':'test',
                      'config_sha256':sha256(self.config),'state_root':str(self.root/'state'),
                      'runtime':{'console_port':29000}}
        self.job='a'*32;self.name='mcp_'+'a'*24
        self.plan={'ok':True,'map_name':self.name,'artifact_sha256':sha256(self.artifact),'source':str(self.artifact)}
        self.plan['source_sha256']=sha256(self.source)
        self.before={'ok':True,'client_connected':True,'observed_maps':['<empty>'],
                     'server_pid':123,'server_created':'creation','runtime_map_verified':False}
        self.patches=[patch.object(rl,'load_project',return_value=self.project),
                      patch.object(rl,'cs2_runtime_stage_build',return_value=self.plan),
                      patch.object(rl,'cs2_runtime_diagnostics',return_value=self.before)]
        self.mocks=[p.start() for p in self.patches]
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def start(self,**changes):
        args=dict(confirm=True,expected_artifact_hash=self.plan['artifact_sha256'],expected_current_map='<empty>')
        args.update(changes);return rl.cs2_runtime_load_start(self.job,**args)
    def test_preview_and_conflict_do_not_send(self):
        with patch.object(rl,'_send') as send:
            self.assertTrue(self.start(confirm=False)['preview'])
            self.assertFalse(self.start(expected_current_map='another')['ok'])
            self.assertFalse(self.start(expected_artifact_hash='wrong')['ok'])
            send.assert_not_called()
        self.assertFalse((self.root/'state/runtime_loads').exists())
    def test_unknown_is_durable_blocks_replay_and_status_recovers_without_send(self):
        def timeout(record,path,project):
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text())['status'],'preparing')
            record['dispatch_started']=True
            raise TimeoutError('lost after dispatch')
        with patch.object(rl,'_send',side_effect=timeout) as send:
            first=self.start();self.assertEqual(first['status'],'unknown');self.assertFalse(first['ok'])
            again=self.start();self.assertEqual(again['load_id'],first['load_id']);self.assertFalse(again['ok'])
            self.assertEqual(send.call_count,1)
            self.mocks[2].return_value={**self.before,'observed_maps':[self.name],'runtime_map_verified':True}
            status=rl.cs2_runtime_load_status(first['load_id'])
            self.assertEqual(status['status'],'loaded');self.assertTrue(status['runtime_map_verified'])
            self.assertEqual(send.call_count,1)
    def test_already_loaded_and_process_changed_status(self):
        self.mocks[2].return_value={**self.before,'observed_maps':[self.name],'runtime_map_verified':True}
        with patch.object(rl,'_send') as send:
            result=self.start();self.assertEqual(result['status'],'loaded')
            self.assertFalse(result['load_command_issued']);send.assert_not_called()
            self.mocks[2].return_value={**self.before,'server_pid':999,'server_created':'new'}
            status=rl.cs2_runtime_load_status(result['load_id'])
            self.assertEqual(status['status'],'process_changed');self.assertFalse(status['runtime_map_verified'])
            send.assert_not_called()
    def test_current_map_change_during_lock_does_not_dispatch(self):
        self.mocks[2].side_effect=[self.before,{**self.before,'observed_maps':['changed']}]
        with patch.object(rl,'_send') as send:
            self.assertFalse(self.start()['ok']);send.assert_not_called()
    def test_exact_wire_load_ack_and_pre_send_record(self):
        marker='CS2_MCP_LOAD_test';body=bytes(28)+marker.encode()+b'\0'
        data=HEADER.pack(b'AINF',212,12,0)+HEADER.pack(b'PRNT',212,12+len(body),0)+body
        record={'artifact':str(self.artifact),'artifact_sha256':sha256(self.artifact),
                'source_sha256':sha256(self.source),'config_sha256':sha256(self.config),
                'pid':123,'created':'creation','ack_marker':marker}
        path=self.root/'record.json'
        class Stream:
            def __init__(self):self.data=data
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def settimeout(self,t):pass
            def recv(self,n):
                out=self.data[:min(n,7)];self.data=self.data[len(out):];return out
            def sendall(inner,payload):
                saved=json.loads(path.read_text());self.assertTrue(saved['dispatch_started'])
                self.assertEqual(saved['status'],'dispatching')
                self.assertIn(('map "'+str(self.artifact).replace('\\','/')+'"').encode(),payload)
        with patch.object(rl.socket,'create_connection',return_value=Stream()),patch.object(rl,'server_pid',return_value=123),patch.object(rl,'process_identity',return_value='creation'):
            rl._send(record,path,self.project)
        self.assertEqual(record['status'],'requested');self.assertTrue(record['batch_acknowledged'])
        self.assertNotIn('runtime_map_verified',record)
