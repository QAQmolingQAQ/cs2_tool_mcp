"""Read one bounded Qt widget page through the actual MCP stdio service."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--offset',type=int,default=0)
    parser.add_argument('--limit',type=int,default=128)
    parser.add_argument('--report',default='')
    parser.add_argument('--menu-window')
    parser.add_argument('--editor',choices=('hammer','pet','met','modeldoc_editor'))
    parser.add_argument('--confirm',action='store_true')
    args=parser.parse_args()
    if args.editor and args.menu_window:parser.error('choose --editor or --menu-window')
    if args.confirm and not args.editor:parser.error("--confirm requires --editor")
    root=Path(__file__).resolve().parents[1]
    params=StdioServerParameters(command=sys.executable,args=[str(root/'mcp_server/cs2_mcp_server.py'),'--stdio','--scope','bridge'])
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tool='cs2_qt_menu_actions' if args.menu_window else ('cs2_qt_open_editor' if args.editor else 'cs2_qt_widgets')
            payload={'editor':args.editor,'confirm':args.confirm} if args.editor else {'offset':args.offset,'limit':args.limit}
            if args.menu_window:payload={'window_object_name':args.menu_window}
            response=await session.call_tool(tool,payload)
            if response.isError:raise RuntimeError(response.content)
            text=response.content[0].text
            try:result=json.loads(text)
            except json.JSONDecodeError as exc:raise RuntimeError('MCP diagnostic failed: '+text) from exc
            if args.report:Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            if 'error' in result:raise RuntimeError(result)
            print(json.dumps({key:value for key,value in result.items() if key not in ('widgets','actions')},ensure_ascii=False))
            if args.menu_window:print(json.dumps({'actions':len(result.get('actions',[])), 'file_menu':[r for r in result.get('actions',[]) if r['menu']=='File']},ensure_ascii=True))
            print(json.dumps([row['button_text'] for row in result.get('widgets',[]) if row['button_text']],ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
