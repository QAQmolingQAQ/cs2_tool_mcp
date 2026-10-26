"""Read-only research probe: pinned Qt proxy rows -> source items -> entity GUIDs.

Not a public writer. Direct children only; addresses and row keys are ephemeral.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
from uuid import UUID

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.edit_preflight import collect
from hammer_mcp.project import load_project
from hammer_mcp.property_fields import BindingReader,verify_layout
from hammer_mcp.session import get_session

GUI_SHA='2ea37f7655223c5cdf1f28616c601ca58bf8b215e371d6f612cfa1aa34517fbf'


class Reader(BindingReader):
    def __init__(self,pipe,modules):
        super().__init__(pipe,modules)
        self.watched={};self.total=0

    def read(self,address,size):
        if not 0x10000<=address<0x7fffffffffff or not 0<=size<=32768:
            raise ValueError('invalid identity read bounds')
        self.total+=size
        if self.total>2*1024*1024:raise ValueError('identity read budget exceeded')
        raw=super().read(address,size);key=(address,size)
        if key in self.watched and self.watched[key]!=raw:raise ValueError('identity data changed')
        self.watched[key]=raw
        return raw

    def vector(self,address,width):
        header=self.read(address,24)
        count=struct.unpack_from('<i',header,4)[0]
        offset=struct.unpack_from('<q',header,16)[0]
        if not 0<=count<=4096 or not 24<=offset<=1024:
            raise ValueError('unsupported Qt vector header')
        return self.read(address+offset,count*width)

    def child(self,item,row,column):
        if self.type_of(item)[1] not in ('.?AVQStandardItem@@','.?AVCQOutlinerItem@@'):
            raise ValueError('unsupported source parent item')
        private=self.ptr(item+8)
        rows,columns=struct.unpack('<ii',self.read(private+0x20,8))
        if not 0<=row<rows or not 0<=column<columns or rows*columns>4096:
            raise ValueError('source child bounds')
        children=self.vector(self.ptr(private+0x18),8)
        return struct.unpack_from('<Q',children,(row*columns+column)*8)[0]

    def entity(self,row):
        model,internal,proxy_row,proxy_column=row['row_key'].split(':')
        model=int(model,16)
        if self.type_of(model)!=('hammer.dll','.?AVCQOutlinerSortFilterProxyModel@@',0x1e17af8):
            raise ValueError('unsupported proxy model')
        source=self.ptr(self.ptr(model+8)+0x88)
        if self.type_of(source)!=('qt5gui.dll','.?AVQStandardItemModel@@',0x4369f0):
            raise ValueError('unsupported source model')
        mapping=self.ptr(int(internal,16)+0x28)
        if self.ptr(mapping+0x20)!=source:raise ValueError('source parent model mismatch')
        vectors=self.ptr(mapping+0x28)
        indices=[]
        for offset,index in ((0,int(proxy_row)),(8,int(proxy_column))):
            raw=self.vector(self.ptr(vectors+offset),4)
            if not 0<=index<len(raw)//4:raise ValueError('proxy index out of bounds')
            indices.append(struct.unpack_from('<i',raw,index*4)[0])
        parent_row,parent_column=struct.unpack('<ii',self.read(mapping+0x10,8))
        parent=self.child(self.ptr(mapping+0x18),parent_row,parent_column)
        item=self.child(parent,*indices)
        if self.type_of(item)!=('hammer.dll','.?AVCQOutlinerItem@@',0x1e17ee8):
            raise ValueError('unsupported outliner item')
        values=self.vector(self.ptr(self.ptr(item+8)+0x10),24)
        roles=[values[o+8:o+24] for o in range(0,len(values),24)
               if struct.unpack_from('<i',values,o)[0]==256]
        if len(roles)!=1 or struct.unpack_from('<I',roles[0],8)[0]&0x3fffffff!=0x410:
            raise ValueError('unsupported entity role variant')
        entity=struct.unpack_from('<Q',roles[0])[0]
        kind=self.type_of(entity)
        if kind!=('hammer.dll','.?AVCMapEntity@@',0x175ad00):
            return {'path':row['path'],'kind':kind[1],'supported':False}
        guid=str(UUID(bytes_le=self.read(entity+8,16)))
        if guid==str(UUID(int=0)):raise ValueError('null entity GUID')
        return {'path':row['path'],'row_key':row['row_key'],'display_text':row['display_text'],
                'entity_address':hex(entity),'entity_guid':guid,'supported':True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
    parser.add_argument('--report',required=True);args=parser.parse_args()
    project=load_project(args.config);before=collect(project)
    if not before['connected'] or before.get('observation_error'):raise ValueError('live evidence unavailable')
    docs=before['layout']['sessions']
    if len(docs)!=1 or Path(docs[0]['document_path'])!=Path(project['source']):
        raise ValueError('configured map must be the only open document')
    modules=before['runtime']['live']['modules'];verify_layout(modules)
    gui=modules.get('qt5gui.dll',{})
    if gui.get('sha256')!=GUI_SHA or not gui.get('loaded_matches_disk_headers'):
        raise ValueError('QtGui layout mismatch')
    pipe=get_session().pipe;out=pipe.call('qt_hammer_outliner',{})['result']
    if not out['shared_model_and_selection'] or not out['views']:raise ValueError('outliner not shared')
    rows=out['views'][0]['rows']
    if len(rows)>256:raise ValueError('row bound')
    reader=Reader(pipe,modules)
    identities=[reader.entity(row) for row in rows if len(row['path'])==2]
    guids=[item['entity_guid'] for item in identities if item['supported']]
    if len(guids)!=len(set(guids)):raise ValueError('duplicate entity GUID')
    for (address,size),raw in reader.watched.items():
        if BindingReader.read(reader,address,size)!=raw:raise ValueError('identity changed during recheck')
    if pipe.call('qt_hammer_outliner',{})['result']!=out or collect(project)!=before:
        raise ValueError('document/outliner context changed')
    report={'identities':identities,'before':before,'outliner':out,'coverage_complete':False,
            'scope':'visible direct-child entity rows only','safe_to_write':False,'atomic_snapshot':False}
    Path(args.report).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'entities':len(guids),'rows':len(identities),'report':args.report,'safe_to_write':False}))


if __name__=='__main__':main()
