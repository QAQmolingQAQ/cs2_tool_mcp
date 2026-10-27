"""Pinned read-only entity keyvalue investigation; no compatibility write approval."""
import struct
from uuid import UUID

from .outliner_identity import Reader,read_identities
from .session import get_session


def attributes(reader,element):
    current=reader.ptr(element+0x48);seen=set();found={}
    while current:
        if current in seen or len(seen)>=512:raise ValueError('attribute cycle or count bound')
        seen.add(current)
        raw=reader.read(current,40)
        following,value,owner=struct.unpack_from('<3Q',raw)
        if owner!=element:raise ValueError('attribute owner mismatch')
        name=reader.text(struct.unpack_from('<Q',raw,32)[0],128)
        if not name or name in found:raise ValueError('empty or duplicate attribute key')
        found[name]={'type':raw[28]&63,'value_pointer':value}
        current=following
    return found


def _read_values(reader,modules,entity,identifier):
    if reader.type_of(entity)!=('hammer.dll','.?AVCMapEntity@@',0x175ad00):
        raise ValueError('entity RTTI mismatch')
    if str(UUID(bytes_le=reader.read(entity+8,16)))!=identifier:raise ValueError('entity GUID changed')
    fields=attributes(reader,entity)
    reference=fields.get('entity_properties')
    if not reference or reference['type']!=1:raise ValueError('typed entity_properties reference missing')
    handle=struct.unpack('<I',reader.read(reference['value_pointer'],4))[0]
    if handle in (0,0xffffffff):raise ValueError('invalid property handle')
    base=int(modules['hammer.dll']['base'],16);dm=base+0x24bae00
    if reader.type_of(dm)!=('hammer.dll','.?AVCDataModel@@',0x16c45d8):
        raise ValueError('current datamodel RTTI mismatch')
    header=reader.read(dm+0x80,24)
    count=struct.unpack_from('<I',header)[0];capacity=struct.unpack_from('<I',header,8)[0]
    table=struct.unpack_from('<Q',header,16)[0];index=handle&0x3fffff
    if not 0<count<=capacity<=1000000 or index>=capacity:raise ValueError('datamodel bounds')
    props=reader.ptr(table+index*16+8)
    if reader.type_of(props)!=('hammer.dll','.?AVCEditGameClassProps@@',0x17602b8):
        raise ValueError('property container RTTI mismatch')
    if struct.unpack('<I',reader.read(props+0x28,4))[0]!=handle:
        raise ValueError('property handle generation mismatch')
    values={}
    for name,field in attributes(reader,props).items():
        if field['type']!=5:raise ValueError('non-string class property unsupported')
        pointer=reader.ptr(field['value_pointer'])
        values[name]=reader.text(pointer,16384) if pointer else ''
    return values


def read_committed_batch(config,profile,entity_guids):
    if not isinstance(entity_guids,list) or not 1<=len(entity_guids)<=256:
        raise ValueError('between 1 and 256 entity GUIDs required')
    identifiers=[str(UUID(value)) for value in entity_guids]
    if len(set(identifiers))!=len(identifiers):raise ValueError('duplicate requested GUID')
    before=read_identities(config,profile)
    modules=before['before']['runtime']['live']['modules']
    reader=Reader(get_session().pipe,modules)
    values={}
    for identifier in identifiers:
        matches=[item for item in before['identities'] if item.get('entity_guid')==identifier]
        if len(matches)!=1:raise ValueError('entity GUID not uniquely covered by current Outliner')
        values[identifier]=_read_values(reader,modules,int(matches[0]['entity_address'],16),identifier)
    for (address,size),raw in reader.watched.items():
        if super(Reader,reader).read(address,size)!=raw:raise ValueError('committed property memory changed')
    if read_identities(config,profile)!=before:raise ValueError('document/entity context changed')
    return {'entities':[{'id':identifier,'properties':values[identifier]} for identifier in identifiers],
            'source_basis':'live_class_property_storage','safe_to_write':False,'atomic_snapshot':False}


def read_committed_properties(config,profile,entity_guid):
    result=read_committed_batch(config,profile,[entity_guid])
    entity=result['entities'][0]
    return {'entity_guid':entity['id'],'properties':entity['properties'],
            'source_basis':result['source_basis'],'safe_to_write':False,'atomic_snapshot':False,
            'unsaved_change_validation_complete':False}
