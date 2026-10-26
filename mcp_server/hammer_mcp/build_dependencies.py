"""Bounded static RERL dependency closure; availability is not release certification."""
from collections import deque
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import zlib

from .build_artifact import VpkEntry, inspect_vpk, resource_ranges, _stamp
from .edit_preflight import file_evidence
from .project import load_project, sha256, within


def compiled_name(name: str) -> str:
    name=name.replace('\\','/').casefold()
    path=PurePosixPath(name)
    if (not name or len(name.encode('utf-8'))>4096 or ':' in name or path.is_absolute()
            or '..' in path.parts or any(c in name for c in '\0\r\n') or not path.suffix):
        raise ValueError('unsafe or non-file resource reference')
    return (name if name.endswith('_c') else name+'_c').casefold()


def external_refs(resource: bytes | VpkEntry) -> list[dict]:
    ranges=resource_ranges(resource)
    if 'RERL' not in ranges:return []
    start,size=ranges['RERL']
    if not size:return []
    data=resource.read_range(start,size) if isinstance(resource,VpkEntry) else resource[start:start+size]
    if len(data)<8:raise ValueError('truncated RERL header')
    offset,count=struct.unpack_from('<II',data)
    if count>65536 or (count and (offset<8 or offset+16*count>len(data))):
        raise ValueError('RERL reference table outside bounds')
    result=[];identities={}
    for index in range(count):
        row=offset+16*index
        identifier,relative=struct.unpack_from('<Qi',data,row)
        position=row+8+relative
        if not 0<=position<len(data):raise ValueError('RERL string outside bounds')
        end=data.find(b'\0',position,min(len(data),position+4097))
        if end<0:raise ValueError('RERL reference string lacks bounded terminator')
        raw=data[position:end].decode('utf-8')
        if identifier in identities and identities[identifier]!=raw:raise ValueError('conflicting RERL resource identity')
        identities[identifier]=raw
        result.append({'resource_id':f'{identifier:016x}','name':raw,'compiled':compiled_name(raw)})
    return result


def _category(name):
    if name.startswith('materials/skybox/'):return 'sky_material'
    suffix=PurePosixPath(name.removesuffix('_c')).suffix
    return {'.vmat':'material','.vtex':'texture','.vsnd':'sound','.vsndevts':'soundevent',
            '.vjs':'script','.vpcf':'particle','.vmdl':'model'}.get(suffix,'resource')


def cs2_build_dependencies(job_id: str, config: str = '', profile: str = '', max_resources: int = 1000) -> dict:
    """Inspect static compiled references and CRC-check reached package resources.

    Uses bounded directory-only indexes for installed csgo/core pak01; only reached
    entries are payload-verified. Loose candidate presence is not proof of runtime
    mount order. Dynamic scripts/sounds and implicit map UI assets remain uncovered.
    """
    try:
        if not re.fullmatch('[0-9a-f]{32}',job_id):raise ValueError('invalid build id')
        if isinstance(max_resources,bool) or not isinstance(max_resources,int) or not 1<=max_resources<=5000:raise ValueError('invalid resource budget')
        project=load_project(config,profile)
        folder=within(Path(project['state_root'])/job_id,Path(project['state_root']))
        request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
        state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
        if (request.get('job_id')!=job_id or state.get('job_id')!=job_id or state['status']!='succeeded'
                or Path(request['source'])!=Path(project['source']) or sha256(Path(project['source']))!=request['source_sha256']):
            raise ValueError('successful unchanged build of configured source required')
        artifact=within(Path(request['artifact']),Path(project['install_root']))
        before=file_evidence(artifact)
        if before['sha256']!=state['validation']['sha256']:raise ValueError('artifact hash changed')
        package=inspect_vpk(artifact)
        map_root=compiled_name('maps/'+request['map_name']+'.vmap')
        if map_root not in package.entries:raise ValueError('built map root is absent from package')
        game=Path(project['game_root'])
        if Path(request['project']['game_root'])!=game:raise ValueError('build installation mismatch')
        installation=request['installation_hashes']
        if any(sha256(game/path)!=digest for path,digest in installation.items()):
            raise ValueError('installation changed since build')
        indexes=[];index_reports=[]
        for mod in ('csgo','core'):
            directory=game/'game'/mod
            candidates=[p for p in (directory/'pak01_dir.vpk',directory/'pak01.vpk') if p.is_file()]
            if not candidates:continue
            if len(candidates)>1:raise ValueError('ambiguous installed pak01 index')
            path=candidates[0];identity=_stamp(path)
            index=inspect_vpk(path,verify_payloads=False)
            indexes.append((path,index,identity))
            index_reports.append({'path':str(path),'directory_sha256':index.directory_sha256,
                                  'entries':len(index.entries),'all_payloads_verified':False})
        roots=[name for name in package.entries if name.endswith('_c')]
        queue=deque(roots);seen=set();resources=[];edges=[];issues=[];bytes_read=0;loose_stamps=[]
        while queue:
            name=queue.popleft()
            if name in seen:continue
            if len(seen)>=max_resources:
                issues.append({'code':'resource_budget_exhausted','remaining':len(queue)+1});break
            seen.add(name)
            candidates=[]
            if name in package.entries:
                candidates=[('build_package',package.entries[name],None)]
            else:
                for root in (Path(project['install_root']),game/'game/csgo',game/'game/core'):
                    path=within(root/name,root)
                    if path.is_file():
                        stamp=_stamp(path);loose_stamps.append((path,stamp))
                        candidates.append((str(path),VpkEntry(path,0,path.stat().st_size,b'',0),None))
                for path,index,_ in indexes:
                    if name in index.entries:candidates.append((str(path),index.entries[name],index.entries[name].crc))
            if len(candidates)!=1:
                issues.append({'code':'unresolved_in_checked_locations' if not candidates else 'ambiguous_candidates',
                               'resource':name,'candidate_count':len(candidates)})
                continue
            provider,entry,crc=candidates[0]
            if entry.size>64*1024*1024 or bytes_read+entry.size>256*1024*1024:
                issues.append({'code':'payload_budget_exhausted','resource':name});continue
            actual=0;digest=hashlib.sha256()
            for chunk in entry.chunks():actual=zlib.crc32(chunk,actual);digest.update(chunk)
            bytes_read+=entry.size
            expected=entry.crc if provider=='build_package' else crc
            if expected is not None and actual&0xffffffff!=expected:raise ValueError('dependency CRC mismatch: '+name)
            refs=external_refs(entry)
            resources.append({'name':name,'category':_category(name),'provider':provider,'sha256':digest.hexdigest(),
                              'size':entry.size,'crc_verified':expected is not None,'reference_count':len(refs)})
            if len(edges)+len(refs)>100000:
                issues.append({'code':'reference_edge_budget_exhausted','resource':name});break
            for ref in refs:
                edges.append({'from':name,**ref});queue.append(ref['compiled'])
        package.unchanged()
        for path,index,identity in indexes:
            index.unchanged()
            if _stamp(path)!=identity:raise ValueError('installed package directory changed')
        if any(_stamp(path)!=stamp for path,stamp in loose_stamps):raise ValueError('loose dependency changed')
        if (file_evidence(artifact)!=before or sha256(Path(project['source']))!=request['source_sha256']
                or sha256(Path(project['config_path']))!=project['config_sha256']
                or any(sha256(game/path)!=digest for path,digest in installation.items())):raise ValueError('build inputs changed during dependency inspection')
        return {'ok':True,'job_id':job_id,'artifact_sha256':before['sha256'],'resources':resources,'references':edges,
                'issues':issues,'checked_payload_bytes':bytes_read,'installed_package_indexes':index_reports,
                'declared_reference_closure_complete':not issues,'coverage_complete':False,'release_ready':False,
                'limitations':['RERL references only; dynamic script/sound strings not covered',
                               'implicit radar/overview/map icons/configs not covered',
                               'disk availability is not verified runtime mount precedence or visual quality']}
    except (OSError,ValueError,KeyError,TypeError,struct.error) as exc:
        return {'ok':False,'coverage_complete':False,'release_ready':False,'error':str(exc)}
