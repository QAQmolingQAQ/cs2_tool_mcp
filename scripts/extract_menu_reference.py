"""Cross-reference a saved, structured menu snapshot with offline text observations."""
import argparse,collections,hashlib,json
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--capture',required=True);parser.add_argument('--menus',required=True)
parser.add_argument('--output-prefix',required=True)
a=parser.parse_args();source=Path(a.capture);before=source.stat()
menus=json.loads(Path(a.menus).read_text(encoding='utf-8-sig'))
rows=menus['actions'];counts=collections.Counter();methods=collections.defaultdict(set);digest=hashlib.sha256()
def label(text):
    text=text.split('\t',1)[0];result=[];i=0
    while i<len(text):
        if text[i]=='&':
            if i+1<len(text) and text[i+1]=='&':result.append('&');i+=2
            else:i+=1
        else:result.append(text[i]);i+=1
    return ''.join(result)
known={label(row['text']) for row in rows if row['text']}
with source.open('rb') as stream:
    for line in stream:
        digest.update(line);r=json.loads(line.decode('utf-8-sig'))
        # Self-reported module/function only: historical Hook IDs are not stable.
        if not r.get('mod','').startswith('Qt5') or not isinstance(r.get('t'),str):continue
        text=label(r['t'])
        if text in known:counts[text]+=1;methods[text].add(r.get('fn',''))
if (before.st_size,before.st_mtime_ns)!=(source.stat().st_size,source.stat().st_mtime_ns):raise RuntimeError('capture changed during analysis')
result={'role':'historical_menu_reference_not_current_ui','snapshot_pid':menus['pid'],
    'capture_sha256':digest.hexdigest(),'snapshot_file':Path(a.menus).name,
    'actions':[]}
for row in rows:
    if not row['text']:continue
    text=row['text'];name=label(text)
    result['actions'].append({'menu':row['menu'],'raw_text':text,'label':name,
        'shortcut':text.split('\t',1)[1] if '\t' in text else '',
        'matching_qt_capture_records':counts[name],'capture_functions':sorted(methods[name])})
result['menu_count']=len({r['menu'] for r in rows})
result['snapshot_actions_including_separators']=len(rows)
result['menu_items_excluding_separators']=len(result['actions'])
result['items_with_text_match']=sum(r['matching_qt_capture_records']>0 for r in result['actions'])
output=Path(a.output_prefix)
with output.with_suffix('.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
def escape(t):return t.replace('|','\\|').replace('\n','<br>').replace('\r','')
lines=['# Hammer 菜单文字参考','',
       '来自历史Qt菜单快照，与用户指定discover_out/calls.jsonl按文本交叉核对。不是当前窗口状态，也不是动作API或可执行权限。',
       '快捷键从原始文字的制表符后拆出；分隔线不列入表。采集命中不证明属于同一个控件/菜单，Hook ID不参与归属。','',
       f"共{result['menu_count']}个菜单、{result['menu_items_excluding_separators']}个非空菜单项；{result['items_with_text_match']}项在Qt采集记录中有相同文字。",'',
       f"采集SHA256：{result['capture_sha256']}",'',
       '原始文字、快捷键、命中函数和来源信息在同名JSON；Qt enabled/visible不等于编辑命令就绪。','']
for menu in dict.fromkeys(r['menu'] for r in rows):
    lines+=['## '+escape(menu),'','| 菜单项 | 快捷键 | 采集记录命中 |','|---|---|---:|']
    for row in result['actions']:
        if row['menu']==menu:lines.append('| '+escape(row['label'])+' | '+escape(row['shortcut'])+' | '+str(row['matching_qt_capture_records'])+' |')
    lines.append('')
with output.with_suffix('.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines))
print(json.dumps({k:v for k,v in result.items() if k!='actions'},ensure_ascii=True))
