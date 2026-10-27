"""Pinned read-only map history identity; not an Undo authorization."""
import struct
import copy
from .edit_preflight import collect
from .outliner_identity import Reader
from .project import load_project
from .property_fields import verify_layout
from .session import get_session
from pathlib import Path


def appended_step(before,after,name):
    if len(after)!=len(before)+1 or after[:-1]!=before or after[-1]['name']!=name:
        raise ValueError('history is not one verified append: '+name)
    return after[-1]


def completed_prefix(batch):
    """Only explicit terminal stops with a known modified prefix are recoverable."""
    rows=batch.get('results',[])
    if batch.get('status') not in ('verified','controlled_test_stop') or not rows:
        raise ValueError('verified batch or controlled terminal stop required')
    prefix=[];stopped=False
    for index,row in enumerate(rows):
        if row.get('index')!=index:raise ValueError('batch result indexes are not contiguous')
        if row['status']=='not_started':stopped=True
        elif row['status']=='verified_modified' and not stopped:prefix.append(row)
        else:raise ValueError('unknown, unsupported, or non-prefix batch outcome')
    if not prefix or (batch['status']=='verified' and stopped) or (batch['status']=='controlled_test_stop' and not stopped):
        raise ValueError('inconsistent terminal batch status')
    return prefix


def batch_undo_plan(batch):
    """Derive exact stack/property transitions, including recorded selection steps."""
    completed=completed_prefix(batch)
    actions=[];expected=copy.deepcopy(batch['after'])
    previous=None
    for row in completed:
        if row['status']!='verified_modified':raise ValueError('only modified test rows supported')
        start=row['history_before_selection']['undo']
        selected=row['history_after_selection']['undo']
        writing=row['history_before_write']['undo']
        finished=row['history_after_write']['undo']
        if previous is not None and start!=previous:raise ValueError('unrecorded intervening history')
        if selected!=writing:raise ValueError('history changed before property dispatch')
        if selected!=start:appended_step(start,selected,'Modify Selection')
        appended_step(writing,finished,'Change: Name')
        previous=finished
    for row in reversed(completed):
        before_properties=copy.deepcopy(expected)
        index=row['index']
        expected['entities'][index]=copy.deepcopy(batch['before']['entities'][index])
        actions.append({'kind':'property','index':index,'before_undo':row['history_after_write']['undo'],
                        'after_undo':row['history_before_write']['undo'],
                        'before_properties':before_properties,'after_properties':copy.deepcopy(expected)})
        if row['history_after_selection']['undo']!=row['history_before_selection']['undo']:
            actions.append({'kind':'selection','index':index,'before_undo':row['history_after_selection']['undo'],
                            'after_undo':row['history_before_selection']['undo'],
                            'before_properties':copy.deepcopy(expected),'after_properties':copy.deepcopy(expected)})
    if expected!=batch['before']:raise ValueError('incomplete property restoration plan')
    return actions


def stack(reader,history,doc):
    if reader.type_of(history)!=('hammer.dll','.?AVCMapDocHistory@@',0x1765e00):
        raise ValueError('history RTTI mismatch')
    if reader.ptr(history+0x78)!=doc+8:raise ValueError('history document owner mismatch')
    header=reader.read(history,24);count=struct.unpack_from('<I',header,8)[0]
    array=struct.unpack_from('<Q',header,16)[0]
    if count>1024 or count and not array:raise ValueError('history count/pointer bound')
    rows=[];seen=set()
    for index in range(count):
        step=reader.ptr(array+index*8)
        if step in seen:raise ValueError('duplicate history step')
        seen.add(step);raw=reader.read(step,40)
        command_count=struct.unpack_from('<I',raw)[0]
        if command_count>4096:raise ValueError('history command count bound')
        if struct.unpack_from('<Q',raw,24)[0]!=history:raise ValueError('history step owner mismatch')
        name=reader.text(step+0x24,128)
        if not name or any(ord(c)<32 for c in name):raise ValueError('history step name unsupported')
        rows.append({'address':hex(step),'id_candidate':struct.unpack_from('<I',raw,32)[0],
                     'name':name,'command_count':command_count,
                     'commands_address':hex(struct.unpack_from('<Q',raw,8)[0])})
    return rows


def read_history(config,profile=''):
    project=load_project(config,profile);before=collect(project)
    if not before['connected'] or before.get('observation_error'):raise ValueError('live history context unavailable')
    sessions=before['layout']['sessions']
    if len(sessions)!=1 or Path(sessions[0]['document_path'])!=Path(project['source']):
        raise ValueError('configured map must be uniquely open')
    modules=before['runtime']['live']['modules'];verify_layout(modules)
    reader=Reader(get_session().pipe,modules)
    doc=int(sessions[0]['document_candidate'],16);root=reader.ptr(doc+0x80)
    if reader.type_of(root)!=('hammer.dll','.?AVCMapRootElement@@',0x1766058):
        raise ValueError('map root RTTI mismatch')
    result={'undo':stack(reader,reader.ptr(root+0x240),doc),
            'redo':stack(reader,reader.ptr(root+0x248),doc),'context':before,
            'safe_to_undo':False,'atomic_snapshot':False}
    for (address,size),raw in reader.watched.items():
        if super(Reader,reader).read(address,size)!=raw:raise ValueError('history changed during observation')
    if collect(project)!=before:raise ValueError('history document context changed')
    return result
