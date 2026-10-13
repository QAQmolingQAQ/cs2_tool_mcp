"""Check module MCP startup and inventories through the actual stdio protocol."""
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp_server"))
from hammer_mcp.scopes import SCOPES, select_tools

async def check(scope):
    params = StdioServerParameters(command=sys.executable,
        args=[str(ROOT / "mcp_server/cs2_mcp_server.py"), "--stdio", "--scope", scope])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            expected = {f.__name__ for f in select_tools(scope)}
            assert {t.name for t in tools.tools} == expected
            if scope == "pet":
                result = await session.call_tool("cs2_particle_functions", {"limit": 1})
                assert not result.isError
                assert json.loads(result.content[0].text)["ok"]
            if scope in ("hammer", "pet", "met", "modeldoc"):
                result = await session.call_tool("cs2_bind_list", {"module": "incorrect"})
                assert result.isError
            print(json.dumps({"scope": scope, "tools": len(tools.tools), "stdio_verified": True}), flush=True)

async def main():
    for scope in SCOPES[1:]:
        await check(scope)

if __name__ == "__main__":
    asyncio.run(main())
