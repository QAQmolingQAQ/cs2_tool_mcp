"""Operate durable runtime loads through the actual bridge MCP stdio service."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('preview','start','status'))
    parser.add_argument('--config',default='')
    parser.add_argument('--profile',default='')
    parser.add_argument('--job',default='')
    parser.add_argument('--load',default='')
    parser.add_argument('--artifact-hash',default='')
    parser.add_argument('--current-map',default='')
    parser.add_argument('--report',default='')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    params=StdioServerParameters(command=sys.executable,args=[str(root/'mcp_server/cs2_mcp_server.py'),'--stdio','--scope','bridge'])
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            values={'config':args.config,'profile':args.profile}
            if args.action=='status':
                tool='cs2_runtime_load_status';values['load_id']=args.load
            else:
                tool='cs2_runtime_load_start';values.update(job_id=args.job,confirm=args.action=='start',
                    expected_artifact_hash=args.artifact_hash,expected_current_map=args.current_map)
            reply=await session.call_tool(tool,values)
            if reply.isError:raise RuntimeError(reply.content)
            report=json.loads(reply.content[0].text)
            if args.report:Path(args.report).write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2))
            return 0 if report['ok'] else 1


if __name__=='__main__':sys.exit(asyncio.run(main()))
