"""Read an offline discover_out capture; create a separate analysis JSON."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.qt_discovery import analyze_discovery
parser=argparse.ArgumentParser()
parser.add_argument('directory');parser.add_argument('--output',required=True)
args=parser.parse_args()
result=analyze_discovery(args.directory)
with Path(args.output).open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
print(json.dumps({k:v for k,v in result.items() if k not in ('functions_by_record_fields','metadata_mismatches','first_noninfra_stack_modules','limitations')},ensure_ascii=True))
