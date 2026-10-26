"""Conservative read-only observations for the current Hammer layout investigation."""
import json
import struct
from .session import get_session
from .versioning import inspect_live

HAMMER_SHA256 = '5901a11ceb483a2a8af05ec576eb5485b96adcb3779875ca3939fe67b28b0de1'
APP_RVA = 0x677E450
APP_VTABLE_RVA = 0x1DF2E90
MANAGER_POINTER_RVA = 0x21DEE70


def direct_dirty_documents(groups: list, sessions: list) -> list:
    """Positive direct-document evidence only; absence never proves clean."""
    known = {row.get('document_candidate') for row in sessions if row.get('document_candidate')}
    return [dict(row, saved_generation_candidate=group['saved_generation_candidate'])
            for group in groups for row in group['documents']
            if row['document'] in known and row['generation_candidate'] > group['saved_generation_candidate']]


def sample_layout(read, base: int) -> dict:
    watched = []
    def observe(address, size):
        if not 0x10000 <= address < 0x7FFFFFFFFFFF or not 0 <= size <= 8192:
            raise ValueError('invalid read bounds')
        raw = read(address,size)
        if len(raw) != size:raise ValueError('short layout read')
        watched.append((address,raw))
        return raw
    def u64(raw,offset=0):return struct.unpack_from('<Q',raw,offset)[0]
    def cstring(address, maximum=1024):
        data=bytearray()
        while len(data)<maximum:
            size=min(64,4096-address%4096,maximum-len(data))
            raw=read(address,size)
            if len(raw)!=size:raise ValueError('short string read')
            end=raw.find(b'\0')
            used=raw if end<0 else raw[:end+1]
            watched.append((address,used))
            data.extend(used[:-1] if end>=0 else used)
            if end>=0:return data.decode('utf-8')
            address+=size
        raise ValueError('unterminated layout string')
    def identity(address, expected_vtable, expected_type):
        vt=u64(observe(address,8))
        if vt!=base+expected_vtable:raise ValueError('document/session vtable mismatch')
        col=u64(observe(vt-8,8))
        header=observe(col,24)
        signature,offset,ctor,td,hierarchy,self_rva=struct.unpack('<6I',header)
        if signature!=1 or offset!=0 or col-self_rva!=base or not 0<td<0x7000000:
            raise ValueError('invalid primary RTTI locator')
        if cstring(base+td+16,128)!=expected_type:raise ValueError('document/session RTTI mismatch')
    app=observe(base+APP_RVA,0x68)
    if u64(app) != base+APP_VTABLE_RVA:raise ValueError('CHammerApp vtable mismatch')
    count=struct.unpack_from('<i',app,0x58)[0]
    if not 0 <= count <= 32:raise ValueError('session count exceeds observation bound')
    sessions=[]
    if count:
        array=observe(u64(app,0x60),count*8)
        for index in range(count):
            address=u64(array,index*8)
            header=observe(address,0x140)
            wrapper=u64(header,0x138)
            identity(address,0x1DF74E8,'.?AVCHammerEditorSession@@')
            if not wrapper:
                sessions.append({'session':hex(address),'document_candidate':None,'document_path':None})
                continue
            identity(wrapper,0x1DFA7C0,'.?AVCMapDocSession@@')
            document=wrapper+0x10
            identity(document,0x1766188,'.?AVCMapDoc@@')
            path_pointer=u64(observe(document+0x6A0,8))
            path=cstring(path_pointer) if path_pointer else None
            sessions.append({'session':hex(address),'session_vtable':hex(u64(header)),
                'document_wrapper_candidate':hex(wrapper),'document_candidate':hex(document),
                'document_path':path,'identity_verified':'module_hash_primary_vtable_and_RTTI'})
    pointer=observe(base+MANAGER_POINTER_RVA,8)
    manager=u64(pointer)
    raw=observe(manager,16)
    buckets=struct.unpack_from('<i',raw)[0]
    if not 0 <= buckets <= 128:raise ValueError('dirty bucket count exceeds observation bound')
    groups=[]
    if buckets:
        data=observe(u64(raw,8),buckets*0x38)
        for index in range(buckets):
            bucket=data[index*0x38:(index+1)*0x38]
            entries=struct.unpack_from('<i',bucket,8)[0]
            if not 0 <= entries <= 128:raise ValueError('dirty document count exceeds observation bound')
            items=[]
            if entries:
                docs=observe(u64(bucket,0x10),entries*0x20)
                for i in range(entries):
                    items.append({'document':hex(u64(docs,i*0x20)),
                        'generation_candidate':u64(docs,i*0x20+0x10)})
            groups.append({'saved_generation_candidate':u64(bucket,0x28),'documents':items})
    # Re-read every observed span; this detects changes, not atomic main-thread coherence.
    for address,raw in watched:
        if read(address,len(raw)) != raw:raise ValueError('layout changed during observation')
    return {'session_count_candidate':count,'sessions':sessions,'dirty_bucket_count_candidate':buckets,
        'dirty_groups':groups,'read_spans':len(watched),'repeat_reads_matched':True,
        'direct_document_unsaved_changes':direct_dirty_documents(groups,sessions),
        'atomic_snapshot':False,'dirty_state':'unknown','safe_to_write':False,
        'verification':'static_layout_and_read_only_observation_no_edit_undo_save_validation'}


def observe_live_layout(pipe,live: dict) -> dict:
    module=live['live']['modules'].get('hammer.dll')
    if not module:raise ValueError('hammer.dll not loaded')
    if module.get('sha256')!=HAMMER_SHA256 or not module.get('loaded_matches_disk_headers'):
        raise ValueError('unsupported Hammer read-only layout identity')
    base=int(module['base'],16)
    def read(address,size):
        response=pipe.call('read_memory',{'address':hex(address),'size':size})
        if 'error' in response:raise ValueError(response['error'])
        return bytes.fromhex(response['result']['hex'].removeprefix('0x'))
    result=sample_layout(read,base)
    ping=pipe.call('ping')
    if ping.get('result',{}).get('pid')!=live['live']['pid']:
        raise ValueError('pipe process changed during layout observation')
    result.update(pid=live['live']['pid'],hammer_sha256=module['sha256'])
    return result


def cs2_hammer_layout_observe() -> str:
    """只读观察已校验Hammer的会话/文档路径与dirty世代，不判断clean或批准写入。

    校验模块SHA/加载PE及App虚表；非空对象还校验主虚表与RTTI，路径有界读取。
    所有跨度重复比对并核对PID；仍不是主线程原子快照。
    未完成修改/Undo/Redo/保存验证，dirty_state始终unknown。
    """
    pipe=get_session().pipe
    try:
        result=observe_live_layout(pipe,inspect_live(pipe))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result={'error':str(exc),'dirty_state':'unknown','safe_to_write':False}
    return json.dumps(result,ensure_ascii=False,indent=2)
