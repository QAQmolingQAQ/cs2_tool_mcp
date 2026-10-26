"""Durable one-shot map loading; status only observes and never replays a load."""
import json
from pathlib import Path
import re
import socket
import time
from uuid import uuid4

from .build_jobs import atomic_json, now
from .build_process import process_identity
from .operation_lock import operation_lock
from .project import load_project, sha256, within
from .runtime_diagnostics import cs2_runtime_diagnostics
from .runtime_stage import cs2_runtime_stage_build
from .vconsole import Reader, encode_command, print_text
from .windows_tcp import server_pid


PENDING = {'preparing', 'dispatching', 'requested', 'unknown'}


def _folder(project):
    return within(Path(project['state_root'])/'runtime_loads',Path(project['state_root']))


def _read(path):
    if path.stat().st_size>2*1024*1024:raise ValueError('load record exceeds bound')
    return json.loads(path.read_text(encoding='utf-8'))


def _send(record, path, project):
    """A returned marker acknowledges the command batch, not map readiness."""
    artifact=record['artifact']
    if any(c in artifact for c in '\0\r\n";'):raise ValueError('unsupported artifact path characters')
    with socket.create_connection(('127.0.0.1',project['runtime']['console_port']),timeout=2) as stream:
        if (server_pid(stream)!=record['pid'] or
                process_identity(record['pid'])!=record['created']):
            raise ValueError('console server identity changed before load')
        reader=Reader(stream,time.monotonic()+5)
        first=reader.frame()
        if first['type']!='AINF' or first['version']!=212:raise ValueError('unsupported VConsole handshake')
        if (sha256(Path(artifact))!=record['artifact_sha256'] or
                sha256(Path(project['source']))!=record['source_sha256'] or
                sha256(Path(project['config_path']))!=record['config_sha256']):
            raise ValueError('load inputs changed before dispatch')
        record.update(status='dispatching',dispatch_started=True,updated_at=now())
        atomic_json(path,record)
        command='map "'+artifact.replace('\\','/')+'"; echo '+record['ack_marker']
        stream.sendall(encode_command(command,212))
        record['command_sent']=True
        atomic_json(path,record)
        for _ in range(10000):
            text=print_text(reader.frame())
            if text is not None and text.strip()==record['ack_marker']:
                record.update(batch_acknowledged=True,status='requested',updated_at=now())
                atomic_json(path,record)
                return
        raise ValueError('load acknowledgement frame budget exhausted')


def cs2_runtime_load_start(job_id: str, config: str = '', profile: str = '',
                           confirm: bool = False, expected_artifact_hash: str = '',
                           expected_current_map: str = '') -> dict:
    """Preview/request one successful build's absolute-path load on a local test runtime.

    Confirmation requires artifact hash and exact current map from preview.
    Creates a durable record before dispatch. Unknown outcomes are never retried;
    use load_status. Already loaded maps are observed without issuing another map.
    """
    record=None;path=None
    try:
        if not isinstance(confirm,bool):raise ValueError('confirm must be bool')
        project=load_project(config,profile)
        plan=cs2_runtime_stage_build(job_id,config,profile)
        if not plan.get('ok'):raise ValueError(plan.get('error','build validation failed'))
        observation=cs2_runtime_diagnostics(config,profile,job_id)
        if not observation.get('ok') or not observation.get('client_connected'):
            raise ValueError('verified local loopback runtime required')
        maps=observation['observed_maps']
        if len(maps)!=1:raise ValueError('one unambiguous current runtime map required')
        current=maps[0]
        preview={'ok':True,'preview':not confirm,'job_id':job_id,'map_name':plan['map_name'],
                 'artifact_sha256':plan['artifact_sha256'],'artifact':plan['source'],
                 'current_map':current,'pid':observation['server_pid'],
                 'created':observation['server_created'],'release_ready':False}
        if not confirm:return preview
        if expected_artifact_hash!=plan['artifact_sha256']:
            raise ValueError('expected artifact hash required; preview again')
        if current!=plan['map_name'] and expected_current_map!=current:
            raise ValueError('current runtime map changed or was not confirmed')
        root=_folder(project);root.mkdir(parents=True,exist_ok=True)
        with operation_lock('runtime-load:'+str(preview['pid'])+':'+str(preview['created'])):
            active=root/('active_'+str(preview['pid'])+'.json')
            if active.exists():
                pointer=_read(active)
                if not re.fullmatch('[0-9a-f]{32}',pointer.get('load_id','')):
                    raise ValueError('invalid active load pointer')
                previous=_read(root/(pointer['load_id']+'.json'))
                if previous['created']==preview['created'] and previous['status'] in PENDING:
                    return {'ok':False,'error':'prior load needs status inspection; no replay',
                            'load_id':previous['load_id'],'status':previous['status'],'release_ready':False}
            fresh=cs2_runtime_diagnostics(config,profile,job_id)
            if (not fresh.get('ok') or not fresh.get('client_connected') or
                    fresh.get('server_pid')!=preview['pid'] or fresh.get('server_created')!=preview['created']
                    or fresh.get('observed_maps')!=maps):
                raise ValueError('runtime changed while acquiring the load lock; preview again')
            if (sha256(Path(project['source']))!=plan['source_sha256'] or
                    sha256(Path(plan['source']))!=plan['artifact_sha256'] or
                    sha256(Path(project['config_path']))!=project['config_sha256']):
                raise ValueError('load inputs changed during preflight')
            identifier=uuid4().hex;path=root/(identifier+'.json')
            record={**preview,'preview':False,'load_id':identifier,'status':'preparing',
                    'config_path':project['config_path'],'profile':project['profile'],
                    'source':project['source'],'source_sha256':plan['source_sha256'],
                    'config_sha256':project['config_sha256'],'created_at':now(),'updated_at':now(),
                    'runtime_map_verified':False,'dispatch_started':False,'command_sent':False,
                    'ack_marker':'CS2_MCP_LOAD_'+identifier,'do_not_replay':True}
            record.pop('ok',None)
            record['previous_map']=record.pop('current_map')
            record['current_map']=None
            atomic_json(path,record)
            atomic_json(active,{'load_id':identifier})
            if fresh['runtime_map_verified']:
                record.update(status='loaded',runtime_map_verified=True,observation=fresh,
                              load_command_issued=False,current_map=current,updated_at=now())
                atomic_json(path,record)
            else:
                _send(record,path,project)
        return {**record,'ok':True,'record_path':str(path)}
    except (OSError,ValueError,KeyError,TypeError,EOFError,RuntimeError) as exc:
        if record is not None:
            record.update(status='unknown' if record['dispatch_started'] else 'rejected',
                          error=str(exc),updated_at=now())
            atomic_json(path,record)
            return {**record,'ok':False,'record_path':str(path)}
        return {'ok':False,'runtime_map_verified':False,'release_ready':False,'error':str(exc)}


def cs2_runtime_load_status(load_id: str, config: str = '', profile: str = '') -> dict:
    """Read a durable load and run fresh diagnostics; never issue a map command."""
    try:
        if not re.fullmatch('[0-9a-f]{32}',load_id):raise ValueError('invalid load id')
        project=load_project(config,profile);path=_folder(project)/(load_id+'.json')
        initial=_read(path)
        with operation_lock('runtime-load:'+str(initial['pid'])+':'+str(initial['created'])):
            record=_read(path)
            if (record['load_id']!=load_id or Path(record['source'])!=Path(project['source']) or
                    record['profile']!=project['profile'] or record['config_sha256']!=project['config_sha256']):
                raise ValueError('load belongs to a different or changed project scope')
            if record['status'] in ('preparing','dispatching','requested','unknown','loaded'):
                observation=cs2_runtime_diagnostics(config,profile,record['job_id'])
                same=(observation.get('server_pid')==record['pid'] and observation.get('server_created')==record['created'])
                verified=same and observation.get('runtime_map_verified',False)
                record.setdefault('previous_map',record.get('current_map'))
                maps=observation.get('observed_maps',[])
                record.update(observation=observation,runtime_map_verified=verified,updated_at=now())
                record['current_map']=maps[0] if len(maps)==1 else None
                if verified:record['status']='loaded'
                elif observation.get('ok') and not same:record['status']='process_changed'
                elif record['status']=='loaded':record['status']='no_longer_verified'
                # An observation failure/timeout cannot prove a pending map command failed.
                atomic_json(path,record)
            return {**record,'ok':True,'record_path':str(path)}
    except (OSError,ValueError,KeyError,TypeError,EOFError,RuntimeError) as exc:
        return {'ok':False,'runtime_map_verified':False,'release_ready':False,'error':str(exc)}
