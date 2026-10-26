"""Prepare a unique saved map copy and project config for native editor validation."""
import argparse,json,sys,uuid,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.project import load_project,sha256,within
parser=argparse.ArgumentParser();parser.add_argument('--config',default='');parser.add_argument('--profile',default='')
args=parser.parse_args();project=load_project(args.config,args.profile)
source=Path(project['source']);digest=sha256(source);identifier=uuid.uuid4().hex
folder=within(Path(project['source_root'])/'maps/__mcp_edit_tests'/identifier,Path(project['source_root']))
folder.mkdir(parents=True,exist_ok=False);copy=folder/source.name
with source.open('rb') as src,copy.open('xb') as dst:shutil.copyfileobj(src,dst)
if sha256(source)!=digest or sha256(copy)!=digest:raise RuntimeError('source changed while preparing test copy')
state=Path(project['state_root'])/'editor_probes'/identifier;state.mkdir(parents=True,exist_ok=False)
relative=copy.relative_to(Path(project['source_root'])).as_posix()
config={'version':1,'active_profile':'editor_probe','game_root':project['game_root'],'state_root':project['state_root'],
        'profiles':{'editor_probe':{'addon':project['addon'],'map':relative,'release':False}}}
(state/'project.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
report={'id':identifier,'original':str(source),'original_sha256':digest,'isolated_map':str(copy),
        'initial_copy_sha256':digest,'project_config':str(state/'project.json'),'editor_opened':False}
(state/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
