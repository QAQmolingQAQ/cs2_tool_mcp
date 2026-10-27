"""Native RED2 input provenance and CRC checks; no complete-closure claim."""
import subprocess,zlib
from pathlib import Path,PurePosixPath,PureWindowsPath
from uuid import uuid4
from .asset_tree import _Parser,_tokens
from .build_jobs import atomic_json
from .edit_preflight import file_evidence
from .project import within


def parse_inputs(text):
    if len(text.encode('utf-8'))>8*1024*1024:raise ValueError('RED2 text exceeds bound')
    marker='--- RED2 Block (CResourceEditInfo) ---'
    if not text.lstrip().startswith(marker):raise ValueError('native RED2 header missing')
    body=text.lstrip()[len(marker):].strip()
    data=_Parser(_tokens(body),reject_duplicates=True).parse()
    rows=[]
    for group in ('m_InputDependencies','m_AdditionalInputDependencies'):
        values=data[group]
        if not isinstance(values,list) or len(rows)+len(values)>10000:raise ValueError('input dependency array bound')
        for value in values:
            name=value['m_RelativeFilename'];search=value['m_SearchPath'];crc=value['m_nFileCRC']
            if not isinstance(name,str) or not isinstance(search,str):raise ValueError('dependency paths must be strings')
            for path in (name,search):
                normalized=path.replace('\\','/')
                if len(path)>1024 or '\0' in path or PureWindowsPath(path).drive or PurePosixPath(normalized).is_absolute() or '..' in PurePosixPath(normalized).parts:
                    raise ValueError('unsafe input dependency path')
            if not name or isinstance(crc,bool) or not isinstance(crc,int) or not 0<=crc<=0xffffffff:
                raise ValueError('invalid input name/CRC')
            flags=[value[key] for key in ('m_bOptional','m_bFileExists','m_bIsGameFile')]
            if not all(isinstance(flag,bool) for flag in flags):raise ValueError('dependency flags must be bool')
            rows.append({'name':name.replace('\\','/'),'search_path':search.replace('\\','/'),
                         'crc32':crc,'optional':flags[0],'recorded_exists':flags[1],'is_game_file':flags[2],'group':group})
    special=data.get('m_SpecialInputDependencies')
    if not isinstance(special,list):raise ValueError('special input array missing')
    return rows,{'special_input_count':len(special),'special_dependency_count':len(data.get('m_SpecialDependencies',[]))}


def inspect_inputs(path,game_root,evidence_root):
    game=Path(game_root).resolve(strict=True);resource=within(Path(path),game/'game')
    tool=game/'game/bin/win64/resourceinfo.exe'
    source_before=file_evidence(resource);tool_before=file_evidence(tool)
    if resource.stat().st_size>64*1024*1024:raise ValueError('resource inspection size bound')
    folder=Path(evidence_root)/'input_dependency_checks'/uuid4().hex;folder.mkdir(parents=True,exist_ok=False)
    log=folder/'native_red2.txt'
    with log.open('wb') as output:
        run=subprocess.run([str(tool),'-i',str(resource),'-b','RED2','-baremode','-maxelements','20000'],
            stdout=output,stderr=subprocess.STDOUT,timeout=20,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if run.returncode or log.stat().st_size>8*1024*1024:raise ValueError('resourceinfo failed or output bound; '+str(log))
    rows,special=parse_inputs(log.read_text(encoding='utf-8-sig'))
    results=[];watched=[];absent=[];total=0
    for row in rows:
        base=game/('game' if row['is_game_file'] else 'content')
        if not row['search_path']:
            results.append({**row,'status':'search_path_unresolved'});continue
        target=within(base/row['search_path']/row['name'],base)
        if not target.is_file():
            absent.append(target)
            status='optional_absent_verified' if row['optional'] and not row['recorded_exists'] else 'required_or_recorded_input_missing'
            results.append({**row,'status':status});continue
        before=file_evidence(target);total+=before['identity'][2]
        if total>256*1024*1024:raise ValueError('input payload budget exceeded')
        crc=0
        with target.open('rb') as stream:
            while chunk:=stream.read(1024*1024):crc=zlib.crc32(chunk,crc)
        if file_evidence(target)!=before:raise ValueError('input changed during inspection')
        watched.append((target,before))
        results.append({**row,'status':'crc_verified' if row['recorded_exists'] and crc&0xffffffff==row['crc32'] else 'input_crc_or_existence_changed',
                        'file':before})
    if (file_evidence(resource)!=source_before or file_evidence(tool)!=tool_before or
            any(file_evidence(path)!=identity for path,identity in watched)):
        raise ValueError('resource/tool/input changed during dependency inspection')
    if any(path.exists() for path in absent):raise ValueError('missing input appeared during inspection')
    result={'ok':True,'resource':source_before,'inspector':tool_before,'inputs':results,**special,
            'declared_inputs_match':all(row['status'] in ('crc_verified','optional_absent_verified') for row in results),
            'checked_input_bytes':total,'coverage_complete':False,'release_ready':False,
            'evidence_path':str(folder/'report.json')}
    atomic_json(folder/'report.json',result)
    return result
