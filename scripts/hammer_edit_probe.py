"""One fixed Qt edit command on a UUID-scoped test map; never a general batch API."""
import argparse
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.build_jobs import atomic_json
from hammer_mcp.edit_preflight import collect
from hammer_mcp.project import load_project
from hammer_mcp.session import get_session


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--action',choices=('snapshot','save','select_all','delete_selected','undo','redo'),default='snapshot')
    parser.add_argument('--baseline',default='')
    parser.add_argument('--title',default='')
    parser.add_argument('--confirm',action='store_true')
    args=parser.parse_args()
    project=load_project(args.config)
    relative=Path(project['source']).relative_to(Path(project['source_root']))
    if (project['release'] or project['addon']!='test' or len(relative.parts)!=4 or
            relative.parts[:2]!=('maps','__mcp_edit_tests') or
            not re.fullmatch('[0-9a-f]{32}',relative.parts[2])):
        raise ValueError('probe requires non-release test addon maps/__mcp_edit_tests/<UUID>/<map>')
    root=Path(project['state_root'])/'edit_probe_runs'
    root.mkdir(parents=True,exist_ok=True)
    before=collect(project)
    if before.get('observation_error') or not before['connected']:
        raise ValueError('live observation unavailable')
    docs=before['layout']['sessions']
    if len(docs)!=1 or Path(docs[0]['document_path'])!=Path(project['source']):
        raise ValueError('isolated map must be the only open document')
    if before['runtime']['bridge']['addon']!='test':raise ValueError('live addon mismatch')
    report={'id':uuid4().hex,'action':args.action,'before':before,'executed':False,'effect_verified':False}
    path=root/(report['id']+'.json')
    atomic_json(path,report)
    if args.action!='snapshot':
        if not args.confirm or not re.fullmatch('[0-9a-f]{32}',args.baseline):
            raise ValueError('action requires confirm and a fresh baseline UUID')
        baseline=json.loads((root/(args.baseline+'.json')).read_text(encoding='utf-8'))
        if baseline.get('after',baseline['before'])!=before:
            raise ValueError('probe baseline changed; observe again before executing')
        commands={'save':'File/Save','select_all':'Edit/Select All','delete_selected':'Edit/Delete Selected',
                  'undo':'Edit/Undo','redo':'Edit/Redo'}
        report['dispatch_started']=True
        report['executed']=None
        report['outcome']='unknown_until_response'
        atomic_json(path,report)
        try:
            response=get_session().pipe.call('qt_hammer_probe_action',{
                'action':commands[args.action],'expected_title':args.title,'confirm':True})
        except Exception as exc:
            report['error']=str(exc)
            report['outcome']='unknown_do_not_retry'
            atomic_json(path,report)
            raise
        report['response']=response
        returned=response.get('result',{}).get('status')=='action_returned'
        report['executed']=True if returned else None
        report['outcome']='returned_effect_unverified' if returned else 'rejected_or_unknown_do_not_retry'
        atomic_json(path,report)
    report['after']=collect(project)
    atomic_json(path,report)
    print(json.dumps({'id':report['id'],'path':str(path),'action':args.action,
        'response':report.get('response'),'source_sha256':report['after']['source']['sha256'],
        'dirty_groups':report['after'].get('layout',{}).get('dirty_groups')}))


if __name__=='__main__':main()
