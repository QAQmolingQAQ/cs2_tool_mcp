"""Persist the same read-only identity result used by Hammer MCP."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.outliner_identity import cs2_hammer_entity_identities

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--report',required=True);args=parser.parse_args()
    report=cs2_hammer_entity_identities(args.config)
    Path(args.report).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'ok':report['ok'],'entities':len([x for x in report.get('identities',[]) if x['supported']]),'report':args.report}))
    return 0 if report['ok'] else 1

if __name__=='__main__':sys.exit(main())
