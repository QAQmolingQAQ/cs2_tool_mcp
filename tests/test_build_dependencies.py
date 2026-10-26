import json
from pathlib import Path
import struct
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.build_dependencies import compiled_name,external_refs,cs2_build_dependencies
from hammer_mcp.build_artifact import inspect_vpk,VpkEntry
from hammer_mcp.project import sha256
from test_build_artifact import package,resource


def references(names):
    table=bytearray();strings=bytearray()
    for i,name in enumerate(names):
        offset=len(names)*16+len(strings)-(i*16+8)
        table+=struct.pack('<QiI',i+1,offset,0);strings+=name.encode()+b'\0'
    body=struct.pack('<II',8,len(names))+table+strings
    return struct.pack('<IHHII',28+len(body),12,0,8,1)+struct.pack('<4sII',b'RERL',8,len(body))+body


class DependencyTests(unittest.TestCase):
    def test_rerl_bounds_path_and_case(self):
        data=references(['materials/test.vmat','TEXTURES/TEST.VTEX_C'])
        self.assertEqual([r['compiled'] for r in external_refs(data)],['materials/test.vmat_c','textures/test.vtex_c'])
        bad=bytearray(data);struct.pack_into('<i',bad,44,0x7fffffff)
        with self.assertRaisesRegex(ValueError,'outside bounds'):external_refs(bytes(bad))
        for path in ('../escape.vmat','C:/outside.vmat','/absolute.vmat','extensionless'):
            with self.assertRaises(ValueError):compiled_name(path)
        no_terminator=data[:-1]+b'x'
        with self.assertRaisesRegex(ValueError,'terminator'):external_refs(no_terminator)
    def test_index_is_not_payload_proof_and_ranges_cross_preload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.vpk';package(path,{'a.vtex_c':resource()})
            raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
            index=inspect_vpk(path,verify_payloads=False)
            self.assertFalse(index.payloads_verified);self.assertEqual(index.validated_bytes,0)
            self.assertEqual(len(index.directory_sha256),64)
            with self.assertRaisesRegex(ValueError,'CRC'):inspect_vpk(path)
            payload=Path(tmp)/'entry';payload.write_bytes(b'0123456789')
            entry=VpkEntry(payload,2,5,b'abc',0)
            self.assertEqual(entry.read_range(1,5),b'bc234')
            with self.assertRaises(ValueError):entry.read_range(7,2)
    def test_transitive_indexed_reference_unresolved_and_budget_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';src=game/'content/csgo_addons/test/maps/source.vmap'
            src.parent.mkdir(parents=True);src.write_text('source')
            install=game/'game/csgo_addons/test';install.mkdir(parents=True)
            compiler=game/'game/bin/win64/resourcecompiler.exe';compiler.parent.mkdir(parents=True);compiler.write_bytes(b'compiler')
            base=game/'game/csgo';base.mkdir(parents=True)
            basepak=base/'pak01_dir.vpk';package(basepak,{'textures/test.vtex_c':resource()})
            job='b'*32;name='maps/mcp_example.vmap_c';artifact=install/'map.vpk'
            package(artifact,{name:references(['materials/test.vmat']),
                              'materials/test.vmat_c':references(['textures/test.vtex'])})
            config=root/'config.json';config.write_text(json.dumps({'version':1,'game_root':str(game),'active_profile':'test',
                'state_root':str(root/'state'),'profiles':{'test':{'addon':'test','map':'maps/source.vmap'}}}))
            folder=root/'state'/job;folder.mkdir(parents=True)
            (folder/'request.json').write_text(json.dumps({'job_id':job,'source':str(src),'source_sha256':sha256(src),
                'project':{'game_root':str(game)},'artifact':str(artifact),'map_name':'mcp_example','installation_hashes':{}}))
            (folder/'state.json').write_text(json.dumps({'job_id':job,'status':'succeeded','validation':{'sha256':sha256(artifact)}}))
            result=cs2_build_dependencies(job,str(config));self.assertTrue(result['ok'],result)
            self.assertEqual(len(result['resources']),3);self.assertTrue(result['declared_reference_closure_complete'])
            self.assertTrue(all(row['crc_verified'] for row in result['resources']))
            self.assertFalse(result['coverage_complete']);self.assertFalse(result['release_ready'])
            limited=cs2_build_dependencies(job,str(config),max_resources=1)
            self.assertFalse(limited['declared_reference_closure_complete'])
            self.assertEqual(limited['issues'][0]['code'],'resource_budget_exhausted')
            package(basepak,{'textures/another.vtex_c':resource()})
            missing=cs2_build_dependencies(job,str(config))
            self.assertEqual(missing['issues'][0]['code'],'unresolved_in_checked_locations')
            self.assertFalse(missing['declared_reference_closure_complete'])
