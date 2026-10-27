"""Read live property storage by entity GUID; never edit or save."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.committed_properties import read_committed_properties

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--profile',default='');parser.add_argument('--entity-guid',required=True)
    parser.add_argument('--report',required=True);args=parser.parse_args()
    result=read_committed_properties(args.config,args.profile,args.entity_guid)
    Path(args.report).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
