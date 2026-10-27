"""Save native resource input provenance without loading it in the editor."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.input_dependencies import inspect_inputs
from hammer_mcp.project import load_project
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--path',required=True);args=parser.parse_args();project=load_project(args.config)
    result=inspect_inputs(args.path,project['game_root'],project['state_root'])
    print(json.dumps({'declared_inputs_match':result['declared_inputs_match'],'inputs':len(result['inputs']),
        'statuses':[row['status'] for row in result['inputs']],'evidence_path':result['evidence_path']}))
