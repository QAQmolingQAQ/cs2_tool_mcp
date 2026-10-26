"""Static cs_script module/input checks; parse JavaScript without executing it."""
import hashlib
import fnmatch
import json
from pathlib import Path
import shutil
import subprocess
import time

from .project import within


HELPER=Path(__file__).resolve().parents[1]/'script_tools/analyze_script.cjs'


def analyze_text(source: str) -> dict:
    node=shutil.which('node')
    if not node:raise ValueError('Node.js is required for static script parsing')
    run=subprocess.run([node,'--max-old-space-size=128',str(HELPER)],
        input=json.dumps({'source':source},ensure_ascii=False).encode('utf-8'),capture_output=True,timeout=5,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if run.returncode or len(run.stdout)>4*1024*1024:
        raise ValueError('script parser unavailable or failed; run npm ci in mcp_server/script_tools')
    return json.loads(run.stdout.decode('utf-8'))


def check_scripts(entities: list[dict], source_root: Path, game_root: Path) -> dict:
    roots=[source_root,game_root/'content/csgo',game_root/'content/core']
    files={};cache={};issues=[];records={};deadline=time.monotonic()+15;total_bytes=0
    def issue(code,entity,severity='warning',**details):
        issues.append({'code':code,'severity':severity,'entity':entity,**details})
    def resolve(name,relative_to=None):
        if not isinstance(name,str) or not name or any(c in name for c in '\0\r\n:'):
            raise ValueError('invalid script source reference')
        name=name.replace('\\','/')
        if name.startswith('/') or '..' in Path(name).parts:
            # Imports may use ../ inside their own source root; validate the final path below.
            if relative_to is None:raise ValueError('script asset reference escapes scope')
        candidates=[]
        if relative_to is not None:
            path=relative_to.parent/name
            owner=next((root for root in roots if relative_to.is_relative_to(root.resolve())),None)
            if owner is None:raise ValueError('import source has no configured root')
            path=within(path,owner)
            candidates=[path.with_suffix('.js'),path] if path.suffix.lower()=='.vjs' else [path]
            candidates=[within(candidate,owner) for candidate in candidates]
        else:
            for root in roots:
                path=within(root/name,root)
                options=[path.with_suffix('.js'),path] if path.suffix.lower()=='.vjs' else [path]
                options=[within(candidate,root) for candidate in options]
                found=[p for p in options if p.is_file()]
                if found:
                    if len(found)>1:raise ValueError('ambiguous .vjs/.js source files')
                    candidates=found;break
        found=[p.resolve() for p in candidates if p.is_file() and p.suffix.lower() in ('.js','.vjs')]
        if len(found)!=1:raise ValueError('script source not found in checked content roots')
        return found[0]
    for entity in entities:
        props=entity['properties']
        if props.get('classname')!='point_script':continue
        identifier=entity['id'];reference=props.get('cs_script','')
        record={'resource':reference,'inputs':[],'registration_analysis_complete':True,'files':[]}
        records[identifier]=record
        if not reference:
            issue('point_script_source_not_configured',identifier);record['registration_analysis_complete']=False;continue
        try:initial=resolve(reference)
        except (OSError,ValueError) as exc:
            issue('script_source_unresolved',identifier,detail=str(exc));record['registration_analysis_complete']=False;continue
        pending=[(initial,0)];seen=set();names=[]
        while pending:
            path,depth=pending.pop()
            if path in seen:continue
            seen.add(path)
            if (path not in cache and len(files)>=64) or depth>8 or time.monotonic()>deadline:
                issue('script_analysis_budget_exhausted',identifier);record['registration_analysis_complete']=False;break
            try:
                if path not in cache:
                    before=path.stat()
                    with path.open('rb') as stream:raw=stream.read(1024*1024+1)
                    if len(raw)>1024*1024 or total_bytes+len(raw)>4*1024*1024:raise ValueError('script source byte budget exceeded')
                    total_bytes+=len(raw)
                    analysis=analyze_text(raw.decode('utf-8-sig'))
                    after=path.stat()
                    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
                        raise ValueError('script changed during parsing')
                    cache[path]=analysis;files[str(path)]=hashlib.sha256(raw).hexdigest()
                analysis=cache[path];record['files'].append(str(path))
            except (OSError,ValueError,subprocess.SubprocessError) as exc:
                issue('script_analysis_unavailable',identifier,detail=str(exc));record['registration_analysis_complete']=False;continue
            if not analysis['syntax_ok']:
                issue('script_syntax_error',identifier,'error',script=str(path),detail=analysis.get('error'))
                record['registration_analysis_complete']=False;continue
            if not analysis['registration_scan_complete'] or analysis.get('error'):
                issue('script_registration_analysis_incomplete',identifier,script=str(path),reasons=analysis.get('dynamic_reasons',[]))
                record['registration_analysis_complete']=False
            for registration in analysis['registrations']:
                names.append(registration['name'])
                if registration['argument_count']!=2 or registration['callback_kind']=='missing':
                    issue('script_registration_signature_mismatch',identifier,script=str(path),entry=registration['name'],line=registration['line'])
            for imported in analysis['imports']:
                if imported=='cs_script/point_script':continue
                if not imported.startswith('.'):
                    issue('script_import_unresolved',identifier,module=imported);record['registration_analysis_complete']=False;continue
                try:pending.append((resolve(imported,path),depth+1))
                except (OSError,ValueError) as exc:
                    issue('script_import_unresolved',identifier,module=imported,detail=str(exc));record['registration_analysis_complete']=False
        record['inputs']=sorted(set(names))
        for name in set(names):
            if names.count(name)>1:issue('script_input_registered_multiple_times',identifier,entry=name)
    by_name={}
    for entity in entities:
        name=entity['properties'].get('targetname','')
        if name:by_name.setdefault(name.casefold(),[]).append(entity['id'])
    for entity in entities:
        for connection in entity['connections']:
            if connection.get('inputName','').casefold()!='runscriptinput':continue
            target=connection.get('targetName','')
            targets=([entity['id']] if target.casefold()=='!self' else
                     [identifier for name, identifiers in by_name.items()
                      if fnmatch.fnmatchcase(name,target.casefold()) for identifier in identifiers])
            for identifier in targets:
                record=records.get(identifier)
                if record is None:continue
                entry=connection.get('overrideParam','')
                if entry not in record['inputs']:
                    issue('script_input_not_statically_declared' if record['registration_analysis_complete'] else 'script_input_registration_unverified',
                          entity['id'],target=identifier,entry=entry)
    for path,digest in files.items():
        with Path(path).open('rb') as stream:raw=stream.read(1024*1024+1)
        if len(raw)>1024*1024 or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('script changed during map inspection')
    complete=all(record['registration_analysis_complete'] for record in records.values())
    return {'issues':issues,'scripts':records,'source_files':files,
            'static_checks_passed':complete and not issues,
            'declaration_analysis_complete':complete,
            'runtime_registration_verified':False,'coverage_complete':False,
            'basis':'saved source AST declarations, not module execution or live registered callbacks'}
