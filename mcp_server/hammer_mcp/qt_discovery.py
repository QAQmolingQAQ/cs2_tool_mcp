"""Analyze offline Qt hook captures without treating historical IDs as stable identities."""
from collections import Counter
import hashlib
import json
from pathlib import Path


def analyze_discovery(root: str | Path) -> dict:
    root=Path(root).resolve(strict=True)
    paths=[root/name for name in ('functions.json','calls.jsonl','particle_operators.txt')]
    before={p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in paths}
    if paths[0].stat().st_size>8*1024*1024:raise ValueError('metadata exceeds 8 MiB')
    metadata=json.loads(paths[0].read_text(encoding='utf-8-sig'))
    hooks={item['id']:item for item in metadata['hooked']}
    functions=Counter();mismatch=Counter();unique=set();exact=True
    active=set();rows=invalid=bad_schema=0;digest=hashlib.sha256();seen_operators=set()
    operators={x.strip() for x in paths[2].read_text(encoding='utf-8-sig').splitlines() if x.strip()}
    stack_owners=Counter()
    infrastructure={'cs2discover.dll','qt5core.dll','qt5gui.dll','qt5widgets.dll','tier0.dll',
        'user32.dll','gdi32.dll','gdi32full.dll','win32u.dll','ntdll.dll','kernel32.dll','kernelbase.dll'}
    with paths[1].open('rb') as stream:
        for line in stream:
            rows+=1;digest.update(line)
            if len(line)>1024*1024:invalid+=1;continue
            try:row=json.loads(line.decode('utf-8-sig'))
            except (UnicodeError,json.JSONDecodeError):invalid+=1;continue
            if not isinstance(row,dict) or not all(isinstance(row.get(k),str) for k in ('fn','mod','t')) or not isinstance(row.get('hook'),int):
                bad_schema+=1;continue
            key=(row['mod'],row['fn']);functions[key]+=1;active.add(row['hook'])
            h=hooks.get(row['hook'],{})
            if row['fn']!=h.get('short') or row['mod'].lower()!=h.get('module','').lower():
                mismatch[(row['hook'],*key,h.get('module',''),h.get('short',''))]+=1
            text=row['t']
            if text not in unique:
                if len(unique)<250000:unique.add(text)
                else:exact=False
            if text in operators:seen_operators.add(text)
            stack=row.get('stack',[])
            if isinstance(stack,list):
                for frame in stack:
                    if not isinstance(frame,str):continue
                    name=frame.split('+',1)[0].lower()
                    if name not in infrastructure:stack_owners[name]+=1;break
    for p in paths:
        if before[p.name]!=(p.stat().st_size,p.stat().st_mtime_ns):raise ValueError('capture changed during analysis: '+p.name)
    return {'module_count':len(metadata['modules']),'hook_metadata_count':len(hooks),
        'distinct_hook_addresses':len({str(h.get('addr')).lower() for h in hooks.values()}),
        'call_lines':rows,'invalid_json_lines':invalid,'invalid_schema_rows':bad_schema,
        'call_file_sha256':digest.hexdigest(),'active_hook_ids':len(active),
        'unique_texts':len(unique),'unique_count_is_exact':exact,
        'metadata_mismatch_rows':sum(mismatch.values()),
        'functions_by_record_fields':[{'module':k[0],'function':k[1],'records':v} for k,v in functions.most_common()],
        'metadata_mismatches':[{'hook':k[0],'record_module':k[1],'record_function':k[2],
            'metadata_module':k[3],'metadata_short':k[4],'records':v} for k,v in mismatch.most_common()],
        'first_noninfra_stack_modules':dict(stack_owners.most_common()),
        'listed_particle_operator_names':len(operators),'operator_names_seen_in_capture':len(seen_operators),
        'limitations':['historical capture; addresses are not reusable',
            'group by record fn/mod; short names may still merge overloads',
            'missing session ID and DLL hashes prevent reliable cross-run attribution',
            'observations are not original call counts or writable APIs',
            'captured text is not a widget/action identity']}
