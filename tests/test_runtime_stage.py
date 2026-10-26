import json
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.runtime_stage import cs2_runtime_stage_build,publish_new
from hammer_mcp.project import sha256
from test_build_artifact import package,resource


class RuntimeStageTests(unittest.TestCase):
    def test_atomic_new_publication_preserves_collision_and_rejects_bad_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'source.vpk';dst=root/'target.vpk';src.write_bytes(b'new')
            dst.write_bytes(b'existing')
            with self.assertRaises(FileExistsError):publish_new(src,dst,sha256(src))
            self.assertEqual(dst.read_bytes(),b'existing')
            with self.assertRaises(ValueError):publish_new(src,root/'bad.vpk','0'*64)
            self.assertFalse((root/'bad.vpk').exists())
            publish_new(src,root/'new.vpk',sha256(src))
            self.assertEqual((root/'new.vpk').read_bytes(),b'new')
            self.assertFalse(list(root.glob('*.pending')))

    def test_preview_install_receipt_and_source_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';source=game/'content/csgo_addons/test/maps/source.vmap'
            source.parent.mkdir(parents=True);source.write_text('source')
            install=game/'game/csgo_addons/test';install.mkdir(parents=True)
            compiler=game/'game/bin/win64/resourcecompiler.exe';compiler.parent.mkdir(parents=True);compiler.write_bytes(b'compiler')
            target_root=game/'game/csgo/maps';target_root.mkdir(parents=True)
            config=root/'project.json';config.write_text(json.dumps({'version':1,'game_root':str(game),'active_profile':'test',
                'state_root':str(root/'state'),'profiles':{'test':{'addon':'test','map':'maps/source.vmap',
                'runtime':{'staging_root':'game/csgo/maps'}}}}))
            job='a'*32;name='mcp_'+job[:24];artifact=install/'maps'/(name+'.vpk');artifact.parent.mkdir()
            prefix='maps/'+name
            package(artifact,{prefix+'.vmap_c':resource(),prefix+'/world.vwrld_c':resource(),prefix+'/world_visibility.vvis_c':resource(b'VXVS')})
            folder=root/'state'/job;folder.mkdir(parents=True)
            request={'job_id':job,'project':{'source':str(source),'game_root':str(game)},'source_sha256':sha256(source),
                     'map_name':name,'artifact':str(artifact),'mode':'quick','installation_hashes':{}}
            (folder/'request.json').write_text(json.dumps(request))
            (folder/'state.json').write_text(json.dumps({'job_id':job,'status':'succeeded','validation':{'sha256':sha256(artifact)}}))
            preview=cs2_runtime_stage_build(job,str(config));self.assertTrue(preview['ok'],preview)
            self.assertFalse(Path(preview['target']).exists())
            original_config=config.read_text()
            data=json.loads(original_config);data['profiles']['test'].pop('runtime')
            config.write_text(json.dumps(data))
            self.assertFalse(cs2_runtime_stage_build(job,str(config))['ok'])
            data=json.loads(original_config);data['profiles']['test']['runtime']['staging_root']=str(root/'outside/maps')
            config.write_text(json.dumps(data))
            self.assertFalse(cs2_runtime_stage_build(job,str(config))['ok'])
            config.write_text(original_config)
            self.assertFalse(cs2_runtime_stage_build(job,str(config),confirm=True)['ok'])
            staged=cs2_runtime_stage_build(job,str(config),confirm=True,expected_artifact_hash=preview['artifact_sha256'])
            self.assertEqual(staged.get('status'),'staged',staged)
            again=cs2_runtime_stage_build(job,str(config),confirm=True,expected_artifact_hash=preview['artifact_sha256'])
            self.assertEqual(again['status'],'already_staged')
            receipt=Path(staged['receipt_path']);data=json.loads(receipt.read_text());data['status']='publishing_outcome_not_yet_verified';receipt.write_text(json.dumps(data))
            refused=cs2_runtime_stage_build(job,str(config),confirm=True,expected_artifact_hash=preview['artifact_sha256'])
            self.assertFalse(refused['ok']);self.assertIn('not overwritten',refused['error'])
            source.write_text('changed')
            self.assertFalse(cs2_runtime_stage_build(job,str(config))['ok'])
            self.assertEqual(sha256(Path(staged['target'])),preview['artifact_sha256'])
