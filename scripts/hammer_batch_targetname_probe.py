"""UUID test-map batch experiment. No general writer, automatic Undo, or Save."""
import argparse,json,re,sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.build_jobs import atomic_json
from hammer_mcp.committed_properties import read_committed_batch
from hammer_mcp.edit_preflight import collect
from hammer_mcp.edit_preview import cs2_edit_plan_recheck,_plan_hash
from hammer_mcp.operation_lock import operation_lock
from hammer_mcp.outliner_identity import read_identities
from hammer_mcp.project import load_project,within
from hammer_mcp.session import get_session


def validate(project,plan):
    relative=Path(project['source']).relative_to(Path(project['source_root']))
    if (project['release'] or project['addon']!='test' or len(relative.parts)!=4 or
            relative.parts[:2]!=('maps','__mcp_edit_tests') or not re.fullmatch('[0-9a-f]{32}',relative.parts[2])):
        raise ValueError('UUID non-release test map required')
    operations=plan.get('operations',[])
    if plan.get('source_basis')!='live_class_property_storage' or not plan.get('plan_valid') or not 1<=len(operations)<=16:
        raise ValueError('valid live plan with 1..16 items required')
    ids=[]
    for operation in operations:
        if operation['property'].casefold()!='targetname':raise ValueError('only targetname experiment supported')
        for value in (operation['expected'],operation['value']):
            if value and not re.fullmatch('mcp_probe_[a-z0-9_]{1,86}',value):
                raise ValueError('empty or probe-prefixed names required')
        ids.append(operation['entity_id'])
    if len(set(ids))!=len(ids):raise ValueError('one operation per entity required')
    return operations


def execute(config,plan_id,plan_hash,stop_after=None):
    project=load_project(config)
    if not re.fullmatch('[0-9a-f]{32}',plan_id):raise ValueError('invalid plan id')
    path=within(Path(project['state_root'])/'edit_plans'/plan_id/'report.json',Path(project['state_root']))
    if path.stat().st_size>2*1024*1024:raise ValueError('plan size bound')
    plan=json.loads(path.read_text(encoding='utf-8'))
    if plan.get('id')!=plan_id or _plan_hash(plan)!=plan_hash or plan.get('plan_sha256')!=plan_hash:
        raise ValueError('plan hash mismatch')
    operations=validate(project,plan)
    if stop_after is not None and not 1<=stop_after<=len(operations):raise ValueError('invalid test stop index')
    pipe=get_session().pipe
    with operation_lock(pipe.pipe_name):
        check=cs2_edit_plan_recheck(plan_id,plan_hash,config)
        if not check.get('ok') or not check.get('plan_current'):raise ValueError('plan stale or unavailable')
        identifiers=[op['entity_id'] for op in operations]
        expected=read_committed_batch(config,'',identifiers)
        if expected['entities']!=plan['live_entities']:raise ValueError('live values changed after recheck')
        identity=read_identities(config)
        expected_context=collect(project)
        record={'id':uuid4().hex,'plan_id':plan_id,'plan_sha256':plan_hash,'before':expected,
                'selection_before':identity['selected_entity_guid'],'status':'preparing',
                'scope':'UUID targetname probe only','automatic_rollback':False,'executed_count':0,
                'results':[{'index':i,'entity_guid':op['entity_id'],'status':'not_started'} for i,op in enumerate(operations)]}
        output=Path(project['state_root'])/'batch_probe_runs';output.mkdir(parents=True,exist_ok=True)
        active=output/('active_'+plan_id+'.json')
        if active.exists():raise ValueError('plan already dispatched; inspect prior batch journal, do not replay')
        output=output/(record['id']+'.json');atomic_json(output,record)
        atomic_json(active,{'id':record['id'],'record_path':str(output)})
        try:
            for index,operation in enumerate(operations):
                row=record['results'][index]
                if stop_after is not None and index>=stop_after:
                    record['status']='controlled_test_stop';break
                if read_committed_batch(config,'',identifiers)!=expected:raise ValueError('unexpected batch property change')
                context=collect(project)
                if context!=expected_context:raise ValueError('batch document/source/process context changed')
                identity=read_identities(config)
                target=next(item for item in identity['identities'] if item.get('entity_guid')==operation['entity_id'])
                row['status']='selection_dispatching';atomic_json(output,record)
                row['selection_response']=pipe.call('qt_hammer_outliner_select',{
                    'row_path':target['path'],'expected_root':Path(project['source']).as_posix().lower(),
                    'expected_label':target['display_text'],'expected_row_key':target['row_key'],'confirm':True})
                selected=read_identities(config)
                if selected['selected_entity_guid']!=operation['entity_id']:raise ValueError('selected GUID readback mismatch')
                if collect(project)!=context:raise ValueError('context changed while selecting')
                params={'expected_root':Path(project['source']).as_posix().lower(),
                        'selected_row_key':selected['selected_row_key'],'expected_before':operation['expected'],
                        'value':operation['value'],'confirm':False}
                row['native_preview']=pipe.call('qt_hammer_targetname_probe',params)
                if row['native_preview'].get('result',{}).get('status') not in ('preview','no_change'):
                    raise ValueError('native property preview rejected')
                if read_committed_batch(config,'',identifiers)!=expected or collect(project)!=context:
                    raise ValueError('property/context changed before dispatch')
                row['status']='property_dispatching_unknown_do_not_replay';atomic_json(output,record)
                row['response']=pipe.call('qt_hammer_targetname_probe',{**params,'confirm':True})
                observed=read_committed_batch(config,'',identifiers)
                wanted=json.loads(json.dumps(expected))
                wanted['entities'][index]['properties']['targetname']=operation['value']
                if observed!=wanted:raise ValueError('post-write batch readback mismatch; no automatic retry/Undo')
                after_context=collect(project)
                if any(after_context.get(key)!=value for key,value in context.items() if key!='layout'):
                    raise ValueError('source/config/process changed during property commit')
                row.update(status='verified_no_change' if operation['value']==operation['expected'] else 'verified_modified',readback=observed)
                record['executed_count']+=int(row['status']=='verified_modified')
                expected=observed;expected_context=after_context;atomic_json(output,record)
            else:record['status']='verified'
            record['after']=expected
        except Exception as error:
            record.update(status='stopped_error_do_not_replay',error=str(error))
        atomic_json(output,record)
        return {'id':record['id'],'record_path':str(output),'status':record['status'],
                'executed_count':record['executed_count'],'count_scope':'verified modifications only',
                'unknown_property_dispatch_count':sum(r['status']=='property_dispatching_unknown_do_not_replay' for r in record['results']),
                'results':[{'index':r['index'],'status':r['status']} for r in record['results']]}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--plan',required=True);parser.add_argument('--plan-hash',required=True)
    parser.add_argument('--stop-after',type=int);parser.add_argument('--confirm',action='store_true')
    args=parser.parse_args()
    if not args.confirm:raise SystemExit('explicit --confirm required; use live preview first')
    print(json.dumps(execute(args.config,args.plan,args.plan_hash,args.stop_after)))
