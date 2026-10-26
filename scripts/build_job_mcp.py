"""Use persisted build jobs through the real bridge stdio MCP."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('preview', 'start', 'status', 'cancel'))
    parser.add_argument('--config', default='')
    parser.add_argument('--profile', default='')
    parser.add_argument('--mode', choices=('quick', 'full'), default='quick')
    parser.add_argument('--job', default='')
    parser.add_argument('--source-hash', default='')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(command=sys.executable, args=[
        str(root / 'mcp_server/cs2_mcp_server.py'), '--stdio', '--scope', 'bridge'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if args.action in ('preview', 'start'):
                tool = 'cs2_build_start'
                values = dict(mode=args.mode, config=args.config, profile=args.profile,
                              confirm=args.action == 'start', expected_source_hash=args.source_hash)
            else:
                tool = 'cs2_build_' + args.action
                values = dict(job_id=args.job, config=args.config)
            result = await session.call_tool(tool, values)
            if result.isError:
                raise RuntimeError(result.content)
            payload = json.loads(result.content[0].text)
            print(json.dumps(payload, indent=2))
            return 0 if payload['ok'] else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
