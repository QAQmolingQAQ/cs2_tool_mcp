"""Read existing map artifacts through the bridge stdio MCP, without game writes."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('map_name')
    parser.add_argument('--mode', choices=('quick', 'full'), default='full')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(command=sys.executable, args=[
        str(root / 'mcp_server/cs2_mcp_server.py'), '--stdio', '--scope', 'bridge'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool('cs2_build_artifact_check', vars(args))
            if result.isError:
                raise RuntimeError(result.content)
            payload = json.loads(result.content[0].text)
            print(json.dumps(payload, indent=2))
            return 0 if payload['ok'] else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
