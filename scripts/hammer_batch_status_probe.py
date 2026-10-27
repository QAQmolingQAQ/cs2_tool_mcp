"""Read a durable test-batch journal and current memory; never replay or Undo."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.batch_observation import observe_batch
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--batch',required=True);parser.add_argument('--report',required=True)
    args=parser.parse_args();result=observe_batch(args.config,args.batch)
    Path(args.report).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key!='observed_properties'}))
