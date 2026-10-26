"""Check the configured disk-map snapshot through the real Hammer stdio MCP."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='')
    parser.add_argument('--profile', default='')
    parser.add_argument('--max-issues', type=int, default=100)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(command=sys.executable, args=[
        str(root / 'mcp_server/cs2_mcp_server.py'), '--stdio', '--scope', 'hammer'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool('cs2_map_io_check', vars(args))
            if result.isError:
                raise RuntimeError(result.content)
            report = json.loads(result.content[0].text)
            print(json.dumps(report, indent=2))
            return 0 if report['ok'] and report['passed'] else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
