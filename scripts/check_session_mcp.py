"""Read live selfcheck through stdio; optionally prove native writes are denied."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default='')
    parser.add_argument('--verify-denial', action='store_true')
    parser.add_argument('--verify-dispatch', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(command=sys.executable, args=[
        str(root / 'mcp_server/cs2_mcp_server.py'), '--stdio', '--scope', 'bridge'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.call_tool('cs2_session_selfcheck', {})
            if response.isError:
                raise RuntimeError(response.content)
            report = json.loads(response.content[0].text)
            if args.verify_denial:
                if not report.get('connected') or report.get('writes_enabled'):
                    raise RuntimeError('denial probe requires a connected, blocked live session')
                result = await session.call_tool('cs2_write_value', {'address': '0x0', 'value': 0, 'type': 'u8'})
                text = '\n'.join(getattr(item, 'text', '') for item in result.content)
                if 'NativeVersionError' not in text or 'blocked before dispatch' not in text:
                    raise RuntimeError('version gate denial was not confirmed: ' + text)
                report['native_write_denial_verified'] = True
            if args.verify_dispatch:
                sys.path.insert(0, str(root / 'mcp_server'))
                from hammer_mcp.transport import Cs2Pipe
                pipe = Cs2Pipe()
                try:
                    ping = pipe.call('ping', {})['result']
                    if ping['pid'] != report['bridge']['pid']:
                        raise RuntimeError('bridge changed before dispatch probe')
                    dispatch = pipe.call('main_thread_selftest', {})
                    result = dispatch.get('result', {})
                    if (result.get('main_thread_status') != 0 or
                        result.get('ret_hex', '').lower() != '0x43533254434f4445' or
                        not result.get('different_threads')):
                        raise RuntimeError('dispatch selftest failed: ' + str(dispatch))
                    report['dispatch_selftest'] = result
                finally:
                    pipe.close()
            if args.report:
                Path(args.report).write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps({key: value for key, value in report.items()
                              if key not in ('installed_modules', 'live')}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
