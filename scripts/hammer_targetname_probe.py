"""Experimental Qt targetname commit on a UUID-scoped test document only."""
import argparse
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.build_jobs import atomic_json
from hammer_mcp.edit_preflight import collect
from hammer_mcp.project import load_project
from hammer_mcp.property_fields import verify_layout
from hammer_mcp.session import get_session


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--expected-before',default='')
    parser.add_argument('--value',default=None)
    parser.add_argument('--confirm',action='store_true')
    args=parser.parse_args()
    project=load_project(args.config)
    relative=Path(project['source']).relative_to(Path(project['source_root']))
    if (project['release'] or project['addon']!='test' or len(relative.parts)!=4 or
            relative.parts[:2]!=('maps','__mcp_edit_tests') or not re.fullmatch('[0-9a-f]{32}',relative.parts[2])):
        raise ValueError('only a UUID-scoped non-release test document is supported')
    value=args.value if args.value is not None else 'mcp_probe_'+uuid4().hex
    if value and not re.fullmatch('mcp_probe_[a-z0-9_]{1,86}',value):raise ValueError('probe-prefixed value required')
    before=collect(project)
    if before.get('observation_error') or not before['connected']:
        raise ValueError('process/document observation changed')
    docs=before['layout']['sessions']
    if len(docs)!=1 or Path(docs[0]['document_path'])!=Path(project['source']):
        raise ValueError('configured test document must be the only open document')
    verify_layout(before['runtime']['live']['modules'])
    pipe=get_session().pipe
    selection=pipe.call('qt_hammer_outliner',{}).get('result',{})
    keys={v['current_row_key'] for v in selection['views']}
    if len(keys)!=1 or not selection['shared_model_and_selection']:raise ValueError('selection unavailable')
    params={'expected_root':Path(project['source']).as_posix().lower(),
            'selected_row_key':keys.pop(),'expected_before':args.expected_before,'value':value,'confirm':args.confirm}
    identifier=uuid4().hex
    folder=Path(project['state_root'])/'property_probe_runs';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(identifier+'.json')
    report={'id':identifier,'before':before,'selection_before':selection,'params':params,
            'dispatch_started':False,'outcome':'not_dispatched','effect_verified':False}
    atomic_json(path,report)
    try:
        report['native_preview']=pipe.call('qt_hammer_targetname_probe',{**params,'confirm':False})
        atomic_json(path,report)
        if report['native_preview'].get('result',{}).get('status') not in ('preview','no_change'):
            raise ValueError('typed native binding/value preview rejected; see '+str(path))
        if collect(project)!=before:raise ValueError('preflight changed after native preview')
        report['dispatch_started']=True;report['outcome']='unknown_do_not_replay';atomic_json(path,report)
        report['response']=pipe.call('qt_hammer_targetname_probe',params);atomic_json(path,report)
        status=report['response'].get('result',{}).get('status')
        report['outcome']=({'preview':'preview_no_write','no_change':'no_change',
            'text_inserted_commit_queued':'insert_returned_commit_unverified'}.get(status,'error_or_unknown_do_not_replay'))
        atomic_json(path,report)
    except Exception as exc:
        report['error']=str(exc);atomic_json(path,report);raise
    finally:pipe.close()
    print(json.dumps({'id':identifier,'report_path':str(path),'value':value,'response':report['response'],
                      'effect_verified':False}))
    return 0 if report['outcome'] in ('preview_no_write','no_change','insert_returned_commit_unverified') else 1


if __name__=='__main__':sys.exit(main())
