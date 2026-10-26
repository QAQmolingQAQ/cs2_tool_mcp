"""Annotate a saved Qt snapshot or look up text in an external local catalog."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.qt_text_catalog import load_catalog,lookup,annotate_snapshot,SCOPES

parser=argparse.ArgumentParser()
parser.add_argument('--catalog-root',required=True)
parser.add_argument('--scope',choices=sorted(SCOPES),required=True)
parser.add_argument('--snapshot')
parser.add_argument('--query')
parser.add_argument('--output',required=True)
args=parser.parse_args()
if bool(args.snapshot)==(args.query is not None):parser.error('choose exactly one of --snapshot or --query')
catalog=load_catalog(args.catalog_root,args.scope)
if args.snapshot:
    source=Path(args.snapshot)
    if source.stat().st_size>8*1024*1024:raise ValueError('snapshot exceeds 8 MiB')
    snapshot=json.loads(source.read_text(encoding='utf-8-sig'))
    if 'result' in snapshot:snapshot=snapshot['result']
    result=annotate_snapshot(snapshot,catalog)
else:
    result={'query':args.query,'matches':lookup(catalog,args.query),'files':catalog['files']}
output=Path(args.output)
# Explicit new output only: never overwrite the input snapshot or an existing reference.
with output.open('x',encoding='utf-8') as stream:
    json.dump(result,stream,ensure_ascii=False,indent=2)
print(json.dumps({'output':str(output),'files':catalog['files'],
    'matches':len(result.get('matches',[])),
    'annotated_buttons':sum(bool(r.get('text_reference')) for r in result.get('widgets',[]))},ensure_ascii=False))
