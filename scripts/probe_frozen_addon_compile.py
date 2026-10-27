"""Compile a private UUID add-on source mirror; research only, no map loading."""
import argparse,json,sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.asset_build import _compile
from hammer_mcp.build_artifact import verify_map_artifact,VpkEntry,resource_blocks
from hammer_mcp.build_jobs import atomic_json
from hammer_mcp.project import load_project,sha256
from hammer_mcp.source_manifest import source_manifest,copy_source_manifest,manifest_changes


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--probe-material',action='store_true');args=parser.parse_args()
    project=load_project(args.config)
    if project['release'] or project['addon']!='test':raise ValueError('non-release test profile required')
    identifier=uuid4().hex;name='mcp_snapshot_'+identifier[:16]
    original=Path(project['source_root']);private=original.parent/name
    installed=Path(project['install_root']).parent/name
    folder=Path(project['state_root'])/'source_copy_probes'/identifier;folder.mkdir(parents=True,exist_ok=False)
    record={'id':identifier,'addon':name,'status':'copying','source_root':str(original),
            'private_source_root':str(private),'private_install_root':str(installed),
            'original_map_sha256':sha256(Path(project['source']))}
    atomic_json(folder/'record.json',record)
    try:
        baseline=source_manifest(original);atomic_json(folder/'original_manifest.json',baseline)
        copied=copy_source_manifest(baseline,private);atomic_json(folder/'copied_manifest.json',copied)
        installed.mkdir(exist_ok=False)
        (installed/'addoninfo.txt').write_text('<!-- kv3 encoding:text:version{e21c7f3c-8a33-41c5-9977-a76d3a32aa0d} format:generic:version{7412167c-06e9-4698-aff2-e63eb59037e7} -->\n{}\n',encoding='utf-8')
        map_name='mcp_'+identifier[:24];input_map=private/'maps'/(map_name+'.vmap')
        frozen_map=private/Path(project['source']).relative_to(original)
        with input_map.open('xb') as output:output.write(frozen_map.read_bytes())
        if sha256(input_map)!=record['original_map_sha256']:raise ValueError('map snapshot hash mismatch')
        command=[project['compiler'],'-nop4','-i',str(input_map),'-fshallow','-world','-phys','-vis']
        record.update(command=command,status='compiling',copied_files=copied['file_count'],copied_bytes=copied['bytes_hashed'])
        atomic_json(folder/'record.json',record)
        code=_compile(command,Path(project['compiler']),folder,record)
        artifact=installed/'maps'/(map_name+'.vpk')
        if args.probe_material:
            candidates=[path for path in (private/'materials/models/prop_livehouse').glob('*.vmat')
                        if not path.name.startswith('mcp_asset_')]
            if len(candidates)!=1:raise ValueError('one local test material required')
            material=candidates[0];material_folder=folder/'material_probe';material_folder.mkdir()
            material_record={'source':str(material)}
            material_code=_compile([project['compiler'],'-nop4','-i',str(material),'-fshallow'],
                                   Path(project['compiler']),material_folder,material_record)
            output=(installed/material.relative_to(private)).with_suffix('.vmat_c')
            blocks=resource_blocks(VpkEntry(output,0,output.stat().st_size,b'',0),nonempty=True)
            material_record.update(exit_code=material_code,output=str(output),resource_blocks=blocks)
            atomic_json(material_folder/'record.json',material_record)
            if material_code!=0 or 'DATA' not in blocks:raise ValueError('private material did not validate')
            record['material_probe']=material_record
        after=source_manifest(private,[input_map]);atomic_json(folder/'after_compile_manifest.json',after)
        record.update(exit_code=code,artifact=str(artifact),private_source_changes=manifest_changes(copied,after),
                      validation=verify_map_artifact(str(artifact),map_name,'quick') if artifact.is_file() else {'ok':False,'error':'private output missing'},
                      original_map_unchanged=sha256(Path(project['source']))==record['original_map_sha256'])
        record['status']='compiled_private_copy' if code==0 and record['validation']['ok'] and not any(record['private_source_changes'].values()) else 'not_verified'
    except Exception as error:record.update(status='failed',error=str(error))
    atomic_json(folder/'record.json',record)
    print(json.dumps({'id':identifier,'record_path':str(folder/'record.json'),'status':record['status'],
                      'exit_code':record.get('exit_code'),'private_source_changes':record.get('private_source_changes'),
                      'validation':record.get('validation',{}).get('ok'),'error':record.get('error')}))
