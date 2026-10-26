"""Read typed property-row bindings for the configured Hammer document."""
from pathlib import Path
import struct
import time

from .edit_preflight import collect
from .project import load_project
from .session import get_session

HASHES = {
    'propertyeditor.dll':'ac06e2668947608fb2c879e211c8ea65e3e86ff33204b89fe848e7e91780894d',
    'hammer.dll':'5901a11ceb483a2a8af05ec576eb5485b96adcb3779875ca3939fe67b28b0de1',
    'qt5core.dll':'b72018655360463896edbd86b120be6dfa7235ae8a0aaa728165cb496573acb9',
    'qt5widgets.dll':'e619823dad8db291f9da78eb81938da3f74a08d2318d660a8f2f9757b862dd0b',
}


def verify_layout(modules):
    for name,digest in HASHES.items():
        module=modules.get(name,{})
        if module.get('sha256')!=digest or not module.get('loaded_matches_disk_headers'):
            raise ValueError('unsupported property binding layout: '+name)


class BindingReader:
    def __init__(self,pipe,modules):
        self.pipe=pipe
        self.modules=modules

    def read(self,address,size):
        response=self.pipe.call('read_memory',{'address':address,'size':size})
        if 'error' in response:raise ValueError(str(response['error']))
        raw=bytes.fromhex(response['result']['hex'].removeprefix('0x'))
        if len(raw)!=size:raise ValueError('short property binding read')
        return raw

    def ptr(self,address):
        return struct.unpack('<Q',self.read(address,8))[0]

    def text(self,address,limit=256):
        if not address:raise ValueError('null property string')
        raw=bytearray()
        while len(raw)<limit:
            part=self.read(address+len(raw),min(16,limit-len(raw)))
            if b'\0' in part:
                raw.extend(part.split(b'\0',1)[0])
                return raw.decode('utf-8')
            raw.extend(part)
        raise ValueError('unterminated property string exceeds bound')

    def type_of(self,obj):
        vt=self.ptr(obj)
        for name,module in self.modules.items():
            base=int(module['base'],16)
            if not base<=vt<base+module['image_size']:continue
            col=self.ptr(vt-8)
            if not base<=col<=base+module['image_size']-24:
                raise ValueError('RTTI locator outside loaded module')
            header=struct.unpack('<6I',self.read(col,24))
            if header[0]!=1 or col-header[5]!=base or not 0<header[3]<module['image_size']-16:
                raise ValueError('invalid property RTTI identity')
            return name,self.text(base+header[3]+16),vt-base
        raise ValueError('property widget vtable outside inspected modules')

    def binding(self,editor):
        obj=editor;seen=set();chain=[]
        for _ in range(16):
            if not obj:return None
            if obj in seen:raise ValueError('cyclic QObject property chain')
            seen.add(obj)
            owner,kind,rva=self.type_of(obj);chain.append(kind)
            if owner=='propertyeditor.dll' and kind=='.?AVCQPropRow@@':
                if rva!=0x10f900:raise ValueError('property row vtable mismatch')
                item=self.ptr(obj+0x68)
                if self.type_of(item)!=('propertyeditor.dll','.?AVCPropItem_Attr@@',0x109488):
                    raise ValueError('unsupported property item type')
                if self.ptr(item+0x18)!=obj:raise ValueError('property item row backreference mismatch')
                key=self.text(self.ptr(item+0x28),128)
                if not key or any(ord(c)<32 for c in key):raise ValueError('invalid property key')
                label=self.text(self.ptr(item+0x30))
                return {'property':key,'display_name':label,'editor_types':chain,
                        'row_address':hex(obj),'item_address':hex(item)}
            private=self.ptr(obj+8)
            obj=self.ptr(private+0x10) if private else 0
        raise ValueError('QObject property chain exceeds bound')


def cs2_hammer_property_fields(config: str = '', profile: str = '') -> dict:
    """Read visible Hammer text controls with verified property-row key bindings.

    Uses pinned propertyeditor/Qt/Hammer layouts and RTTI, never native calls.
    Values are text currently displayed by QLineEdit, not proof of committed
    document values. Class/filter controls without property rows are separate.
    Does not edit, save or authorize property writes; observation is not atomic.
    """
    try:
        project=load_project(config,profile)
        before=collect(project)
        if not before['connected'] or before.get('observation_error'):
            raise ValueError('live document observation unavailable')
        docs=before['layout']['sessions']
        if len(docs)!=1 or Path(docs[0]['document_path'])!=Path(project['source']):
            raise ValueError('configured source must be the only verified open Hammer document')
        modules=before['runtime']['live']['modules'];verify_layout(modules)
        pipe=get_session().pipe;reader=BindingReader(pipe,modules)
        selection=pipe.call('qt_hammer_outliner',{}).get('result',{})
        if not selection.get('shared_model_and_selection'):
            raise ValueError('shared Outliner selection unavailable')
        fields=[];unbound=[];seen=set();deadline=time.monotonic()+30
        offset=0;total=None
        while True:
            if time.monotonic()>deadline:raise ValueError('property widget scan time budget exceeded')
            reply=pipe.call('qt_widgets_snapshot',{'offset':offset,'limit':128})
            page=reply.get('result',{})
            if page.get('pid')!=before['runtime']['bridge']['pid'] or 'widgets' not in page:
                raise ValueError('widget scan process changed or unavailable')
            if total is None:total=page['total']
            if total>4096 or total!=page['total']:raise ValueError('widget count changed or exceeds 4096')
            for widget in page['widgets']:
                if (not widget.get('visible') or widget.get('kind')!='QLineEdit' or
                        not any(a['object_name']=='HammerObjectPropertyDockWidget' for a in widget.get('ancestors',[]))):continue
                address=int(widget['address'],16)
                if address in seen:continue
                seen.add(address)
                binding=reader.binding(address)
                if binding is None:
                    unbound.append({'object_name':widget['object_name'],'display_text':widget['display_text']})
                    continue
                binding.update(editor_address=widget['address'],display_text=widget['display_text'],
                               text_redacted=widget['text_redacted'],enabled=widget['enabled'])
                fields.append(binding)
                if len(fields)>64:raise ValueError('property field count exceeds bound')
            offset+=128
            if offset>=total:break
        # Re-read descriptors; a changed property selection must not borrow old keys.
        for field in fields:
            again=reader.binding(int(field['editor_address'],16))
            if again!={key:field[key] for key in again}:
                raise ValueError('property binding changed during inspection')
        if pipe.call('qt_hammer_outliner',{}).get('result')!=selection or collect(project)!=before:
            raise ValueError('document or selection changed during property inspection')
        return {'ok':True,'pid':before['runtime']['bridge']['pid'],'source':project['source'],
                'fields':fields,'unbound_text_controls':unbound,'selection':selection,
                'binding_module':'propertyeditor.dll','module_hashes':dict(HASHES),
                'value_basis':'visible QLineEdit display text, not committed document property values',
                'coverage':'visible text editors with CPropItem_Attr bindings only',
                'coverage_complete':False,'addresses_are_ephemeral':True,
                'snapshot_atomic':False,'safe_to_write':False}
    except (OSError,ValueError,KeyError,TypeError,struct.error) as exc:
        return {'ok':False,'safe_to_write':False,'error':str(exc)}
