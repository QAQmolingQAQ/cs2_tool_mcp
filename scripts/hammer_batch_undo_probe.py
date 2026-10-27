"""Exact recorded-history rollback experiment; UUID test maps only, never Save."""
import argparse,json,re,sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.build_jobs import atomic_json
from hammer_mcp.committed_properties import read_committed_batch
from hammer_mcp.edit_preflight import file_evidence
from hammer_mcp.history_snapshot import batch_undo_plan,read_history
from hammer_mcp.operation_lock import operation_lock
from hammer_mcp.project import load_project,within
from hammer_mcp.session import get_session
from hammer_batch_targetname_probe import validate


def execute(config,batch_id,batch_hash):
    project=load_project(config)
    if not re.fullmatch('[0-9a-f]{32}',batch_id):raise ValueError('invalid batch id')
    root=Path(project['state_root']);path=within(root/'batch_probe_runs'/(batch_id+'.json'),root)
    evidence=file_evidence(path)
    if evidence['sha256']!=batch_hash or evidence['identity'][2]>2*1024*1024:raise ValueError('batch hash/size mismatch')
    batch=json.loads(path.read_text(encoding='utf-8'))
    if batch['id']!=batch_id:raise ValueError('batch identity mismatch')
    plan_path=within(root/'edit_plans'/batch['plan_id']/'report.json',root)
    validate(project,json.loads(plan_path.read_text(encoding='utf-8')))
    actions=batch_undo_plan(batch);ids=[item['id'] for item in batch['before']['entities']]
    pipe=get_session().pipe
    with operation_lock(pipe.pipe_name):
        folder=root/'batch_probe_rollbacks';folder.mkdir(parents=True,exist_ok=True)
        active=folder/('active_'+batch_id+'.json')
        if active.exists():raise ValueError('prior rollback exists; inspect without replay')
        expected_context=batch['results'][-1]['history_after_write']['context']
        record={'id':uuid4().hex,'batch_id':batch_id,'batch_sha256':batch_hash,
                'status':'preparing','actions':[],'target_properties_restored':False,'full_map_rollback_verified':False}
        output=folder/(record['id']+'.json');atomic_json(output,record);atomic_json(active,{'id':record['id']})
        try:
            for action in actions:
                current=read_history(config)
                if current['context']!=expected_context or current['undo']!=action['before_undo']:
                    raise ValueError('history/context differs from exact recorded transition')
                if read_committed_batch(config,'',ids)!=action['before_properties']:
                    raise ValueError('target properties changed before Undo')
                fresh=read_history(config)
                if fresh!=current or file_evidence(path)!=evidence:raise ValueError('history/batch evidence changed before Undo')
                step={'kind':action['kind'],'index':action['index'],'status':'dispatching_unknown_do_not_replay',
                      'expected_step':action['before_undo'][-1]}
                record['actions'].append(step);atomic_json(output,record)
                step['response']=pipe.call('qt_hammer_probe_action',{'action':'Edit/Undo',
                    'expected_title':'Hammer - ['+Path(project['source']).name+' *]','confirm':True})
                after=read_history(config);observed=read_committed_batch(config,'',ids)
                step.update(history_after=after,properties_after=observed);atomic_json(output,record)
                if (after['undo']!=action['after_undo'] or observed!=action['after_properties'] or
                        len(after['redo'])!=len(current['redo'])+1):
                    raise ValueError('Undo effect/stack mismatch; stopped without further Undo')
                if any(after['context'].get(key)!=value for key,value in current['context'].items() if key!='layout'):
                    raise ValueError('source/process/config changed during Undo')
                step['status']='verified';expected_context=after['context'];atomic_json(output,record)
            record.update(status='target_properties_restored',target_properties_restored=True)
        except Exception as error:record.update(status='stopped_error_do_not_replay',error=str(error))
        atomic_json(output,record)
        return {'id':record['id'],'record_path':str(output),'status':record['status'],
                'verified_actions':sum(x['status']=='verified' for x in record['actions']),
                'target_properties_restored':record['target_properties_restored'],'error':record.get('error')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--batch',required=True);parser.add_argument('--batch-hash',required=True)
    parser.add_argument('--confirm',action='store_true');args=parser.parse_args()
    if not args.confirm:raise SystemExit('explicit --confirm required')
    result=execute(args.config,args.batch,args.batch_hash)
    print(json.dumps(result))
    sys.exit(0 if result['target_properties_restored'] else 1)
