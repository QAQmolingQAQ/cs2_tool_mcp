"""Fixed read-only game queries over a process-bound VConsole2 connection."""
import json
import math
from pathlib import Path
import re
import socket
import time
from uuid import uuid4

from .build_process import process_identity
from .project import load_project, sha256, within
from .session import get_session
from .versioning import inspect_live
from .vconsole import Reader, encode_command, print_text
from .windows_tcp import server_pid


def _diagnostic_lines(reader, marker):
    """Return only the bounded interval; a timeout is never completion evidence."""
    lines=[];started=False;end=marker+'_END'
    for _ in range(10000):
        text=print_text(reader.frame())
        if text is None:continue
        if text.strip()==marker:started=True;continue
        if started and text.strip()==end:return lines
        if started:
            if len(lines)>=4000:raise ValueError('diagnostic line budget exceeded')
            lines.append(text)
    raise ValueError('diagnostic completion marker missing within frame budget')


def summarize(lines: list[str]) -> dict:
    maps=[];position=None;angles=None;cheats=None;unavailable=[]
    for line in lines:
        match=re.search(r'loaded spawngroup\([^)]*\)\s*:\s*SV:\s*\[\d+:\s*([^|]+)\|\s*main lump\s*\|\s*mapload\]',line)
        if match:maps.append(match[1].strip())
        match=re.fullmatch(r'\s*SV:\s*\[\d+:\s*([^|]+)\|\s*main lump\s*\|\s*mapload\]\s*\(ACTIVE\)\s*',line)
        if match:maps.append(match[1].strip())
        match=re.fullmatch(r'\s*setpos ([+-]?[\d.]+) ([+-]?[\d.]+) ([+-]?[\d.]+);setang ([+-]?[\d.]+) ([+-]?[\d.]+) ([+-]?[\d.]+)\s*',line)
        if match:
            values=[float(v) for v in match.groups()]
            if all(math.isfinite(v) for v in values):position=values[:3];angles=values[3:]
        match=re.fullmatch(r'\s*sv_cheats = (true|false)\s*',line)
        if match:cheats=match[1]=='true'
        for command in ('meta','css_plugins'):
            if line.strip()=='Unknown command: '+command:unavailable.append(command)
    return {'observed_maps':sorted(set(maps)), 'client_connected':any(
                line.startswith('Client:  Connected [loopback:') for line in lines),
            'world_position':position,'world_angles':angles,'local_position':None,
            'parent_graph_verified':False,'final_cvars':{'sv_cheats':cheats},
            'plugin_commands_unavailable':sorted(set(unavailable)),
            'plugin_versions':{},'sound_lifetimes_verified':False}


def cs2_runtime_diagnostics(config: str = '', profile: str = '', job_id: str = '') -> dict:
    """Query status/getpos/sv_cheats and plugin-version commands; never set cvars.

    Requires explicit profile.runtime settings. Optional successful build job ID
    checks loaded map name and artifact/source hashes. No arbitrary command input;
    unavailable plugin commands are not proof that plugins are absent.
    """
    report={'ok':False,'runtime_map_verified':False,'release_ready':False,'command_sent':False,
            'diagnostic_batch_completed':False}
    try:
        project=load_project(config,profile)
        if not project['runtime']:raise ValueError('explicit runtime configuration required')
        live=inspect_live(get_session().pipe)
        if Path(live['game_root'])!=Path(project['game_root']):raise ValueError('live game installation mismatch')
        pid,created=live['live']['pid'],live['live']['created']
        artifact=None;expected_hash=None;expected_map=None;source_hash=sha256(Path(project['source']))
        if job_id:
            if not re.fullmatch('[0-9a-f]{32}',job_id):raise ValueError('invalid build id')
            folder=within(Path(project['state_root'])/job_id,Path(project['state_root']))
            request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
            state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
            if (state.get('job_id')!=job_id or request.get('job_id')!=job_id or state['status']!='succeeded'
                    or Path(request['source'])!=Path(project['source']) or request['source_sha256']!=source_hash):
                raise ValueError('successful unchanged build of configured source required')
            artifact=within(Path(request['artifact']),Path(project['install_root']))
            expected_hash=state['validation']['sha256'];expected_map=request['map_name']
            if sha256(artifact)!=expected_hash:raise ValueError('build artifact changed')
        marker='CS2_MCP_DIAG_'+uuid4().hex
        with socket.create_connection(('127.0.0.1',project['runtime']['console_port']),timeout=2) as stream:
            if server_pid(stream)!=pid or process_identity(pid)!=created:raise ValueError('console process mismatch')
            reader=Reader(stream,time.monotonic()+5)
            first=reader.frame()
            if first['type']!='AINF' or first['version']!=212:raise ValueError('unsupported VConsole handshake')
            report.update(server_pid=pid,server_created=created,protocol='vconsole2',dispatch_started=True)
            stream.sendall(encode_command('echo '+marker+'; status; groups; getpos; sv_cheats; meta version; css_plugins list; echo '+marker+'_END',212))
            report['command_sent']=True
            lines=_diagnostic_lines(reader,marker)
        if (process_identity(pid)!=created or sha256(Path(project['source']))!=source_hash
                or sha256(Path(project['config_path']))!=project['config_sha256']):
            raise ValueError('process/source/config changed during observation')
        if artifact is not None and sha256(artifact)!=expected_hash:raise ValueError('artifact changed during observation')
        summary=summarize(lines)
        report.update(ok=True,diagnostic_batch_completed=True,**summary,observation_scope='shared_console_stream_not_atomic',
                      diagnostic_output_sanitized=True,job_id=job_id or None,expected_map=expected_map,
                      artifact_sha256=expected_hash,verification_scope='loaded map name and retained disk artifact hash; not memory-image or quality certification')
        report['runtime_map_verified']=bool(expected_map and summary['observed_maps']==[expected_map] and summary['client_connected'])
    except (OSError,ValueError,KeyError,TypeError,EOFError) as exc:
        report.update(error=str(exc),outcome='unknown_do_not_replay' if report.get('dispatch_started') else 'no_command_sent')
    return report
