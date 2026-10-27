"""Observe research batch journals without replay, Undo, or rewriting evidence."""
import json,re
from pathlib import Path
from .build_process import process_identity
from .committed_properties import read_committed_batch
from .edit_preflight import file_evidence
from .project import load_project,within


def writer_state(record):
    producer=record.get('producer')
    if producer is None:return 'not_recorded'
    pid,created=producer['pid'],producer['created']
    if isinstance(pid,bool) or not isinstance(pid,int) or pid<=0 or not isinstance(created,str) or not created.isdecimal():
        raise ValueError('invalid producer identity')
    current=process_identity(pid)
    return 'running' if current==created else 'exited' if current is None else 'pid_reused'


def classify(record,writer):
    rows=record['results']
    if not isinstance(rows,list) or not 1<=len(rows)<=16:raise ValueError('invalid batch result bound')
    known={'not_started','selection_dispatching','property_dispatching_unknown_do_not_replay',
           'verified_modified','verified_no_change'}
    if any(row.get('index')!=index or row.get('status') not in known for index,row in enumerate(rows)):
        raise ValueError('invalid batch result schema')
    pending=[row['index'] for row in rows if row['status'] in ('selection_dispatching','property_dispatching_unknown_do_not_replay')]
    terminal=record.get('status') in ('verified','controlled_test_stop','stopped_error_do_not_replay')
    state='recorded_terminal' if terminal else 'in_progress' if writer=='running' else 'stopped_or_unobserved_unknown'
    return {'journal_status':record.get('status'),'producer_state':writer,'observation_state':state,
            'verified_modified_count':sum(row['status']=='verified_modified' for row in rows),
            'not_started_indexes':[row['index'] for row in rows if row['status']=='not_started'],
            'unknown_dispatch_indexes':pending,'replay_allowed':False,'recovery_authorized':False,
            'attribution_verified':False}


def observe_batch(config,batch_id):
    if not re.fullmatch('[0-9a-f]{32}',batch_id):raise ValueError('invalid batch id')
    project=load_project(config);root=Path(project['state_root'])
    path=within(root/'batch_probe_runs'/(batch_id+'.json'),root)
    evidence=file_evidence(path)
    if evidence['identity'][2]>2*1024*1024:raise ValueError('batch record size bound')
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('id')!=batch_id:raise ValueError('batch identity mismatch')
    # An access error is unknown, not evidence of producer death.
    try:writer=writer_state(record);writer_error=None
    except (OSError,ValueError,KeyError,TypeError) as error:writer='unknown';writer_error=str(error)
    result=classify(record,writer)
    contexts=[row.get('history_before_selection',{}).get('context') for row in record['results']]
    context=next((item for item in contexts if item),None)
    scope_match=bool(context and context['profile']==project['profile'] and
                     Path(context['source']['path'])==Path(project['source']) and
                     context['config']['sha256']==project['config_sha256'])
    ids=[entity['id'] for entity in record['before']['entities']]
    result.update(batch_id=batch_id,record_sha256=evidence['sha256'],writer_observation_error=writer_error,
                  current_memory_available=False,current_matches_before=None,current_matches_recorded_after=None,
                  safe_to_write=False,mutation_command_sent=False,project_scope_matches=scope_match,
                  atomic_snapshot=False,producer_sample_scope='before_memory_read')
    try:
        if not scope_match:raise ValueError('recorded project scope missing or differs; current memory not inspected')
        observed=read_committed_batch(config,'',ids)
        result.update(current_memory_available=True,current_matches_before=observed==record['before'],
                      current_matches_recorded_after=observed==record.get('after'),observed_properties=observed)
    except (OSError,ValueError,KeyError,TypeError) as error:result['memory_observation_error']=str(error)
    if file_evidence(path)!=evidence:raise ValueError('journal changed during observation; query again without replay')
    result['note']='Current values do not prove which command produced them or whether a queued edit can still run.'
    return result
