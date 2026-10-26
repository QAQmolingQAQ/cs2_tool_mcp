// Fixed Qt 5 x64 ABI adapters: diagnostics and bounded editor UI actions.
// No caller-supplied function/object addresses.
#include "qt_snapshot.h"
#include "hammer_bridge.h"
#include <algorithm>
#include <memory>
#include <stdexcept>

namespace cs2tool {
namespace {
using ListGetter = void* (*)(void*);
using StringGetter = void* (*)(void*, void*);
using StringDestructor = void (*)(void*);
using Inherits = bool (*)(void*, const char*);
using Dispose = void (*)(void*);
using Predicate = bool (*)(void*);
using Click = void (*)(void*);
using ParentGetter = void* (*)(void*);
using IntGetter = int (*)(void*);

bool Readable(const void* ptr, size_t size) {
    const uintptr_t start = reinterpret_cast<uintptr_t>(ptr);
    if (!start || size > UINTPTR_MAX - start) return false;
    uintptr_t next = start;
    while (next < start + size) {
        MEMORY_BASIC_INFORMATION m{};
        if (!VirtualQuery(reinterpret_cast<void*>(next), &m, sizeof(m)) ||
            m.State != MEM_COMMIT || (m.Protect & (PAGE_GUARD | PAGE_NOACCESS))) return false;
        const auto end = reinterpret_cast<uintptr_t>(m.BaseAddress) + m.RegionSize;
        if (end <= next) return false;
        next = end;
    }
    return true;
}
bool Matches(HMODULE module, DWORD timestamp, DWORD size) {
    if (!module || !Readable(module, 4096)) return false;
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(module);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew < 0 || dos->e_lfanew > 3000) return false;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(reinterpret_cast<char*>(module) + dos->e_lfanew);
    return nt->Signature == IMAGE_NT_SIGNATURE && nt->FileHeader.TimeDateStamp == timestamp &&
        nt->OptionalHeader.SizeOfImage == size && nt->OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR64_MAGIC;
}
struct Api {
    ListGetter widgets = nullptr;
    StringGetter object_name = nullptr, button_text = nullptr;
    StringDestructor destroy_string = nullptr;
    Inherits inherits = nullptr;
    Dispose dispose = nullptr;
    Predicate visible = nullptr, enabled = nullptr;
    Click click = nullptr;
    ParentGetter parent_widget = nullptr;
    StringGetter label_text = nullptr, line_text = nullptr;
    IntGetter echo_mode = nullptr;
    StringGetter variant_to_string = nullptr;
    StringDestructor destroy_variant = nullptr;
};
Api LoadApi() {
    HMODULE core = GetModuleHandleW(L"Qt5Core.dll"), widgets = GetModuleHandleW(L"Qt5Widgets.dll");
    // This is a supported ABI identity, not an editor-offset write compatibility profile.
    if (!Matches(core, 1615841026, 6324224) || !Matches(widgets, 1615842770, 5640192))
        throw std::runtime_error("unsupported loaded Qt ABI identity");
    Api a;
    a.widgets = reinterpret_cast<ListGetter>(GetProcAddress(widgets, "?allWidgets@QApplication@@SA?AV?$QList@PEAVQWidget@@@@XZ"));
    a.object_name = reinterpret_cast<StringGetter>(GetProcAddress(core, "?objectName@QObject@@QEBA?AVQString@@XZ"));
    a.button_text = reinterpret_cast<StringGetter>(GetProcAddress(widgets, "?text@QAbstractButton@@QEBA?AVQString@@XZ"));
    a.destroy_string = reinterpret_cast<StringDestructor>(GetProcAddress(core, "??1QString@@QEAA@XZ"));
    a.inherits = reinterpret_cast<Inherits>(GetProcAddress(core, "?inherits@QObject@@QEBA_NPEBD@Z"));
    a.dispose = reinterpret_cast<Dispose>(GetProcAddress(core, "?dispose@QListData@@SAXPEAUData@1@@Z"));
    a.visible = reinterpret_cast<Predicate>(GetProcAddress(widgets, "?isVisible@QWidget@@QEBA_NXZ"));
    a.enabled = reinterpret_cast<Predicate>(GetProcAddress(widgets, "?isEnabled@QWidget@@QEBA_NXZ"));
    a.click = reinterpret_cast<Click>(GetProcAddress(widgets, "?click@QAbstractButton@@QEAAXXZ"));
    a.parent_widget = reinterpret_cast<ParentGetter>(GetProcAddress(widgets, "?parentWidget@QWidget@@QEBAPEAV1@XZ"));
    a.label_text = reinterpret_cast<StringGetter>(GetProcAddress(widgets, "?text@QLabel@@QEBA?AVQString@@XZ"));
    a.line_text = reinterpret_cast<StringGetter>(GetProcAddress(widgets, "?text@QLineEdit@@QEBA?AVQString@@XZ"));
    a.echo_mode = reinterpret_cast<IntGetter>(GetProcAddress(widgets, "?echoMode@QLineEdit@@QEBA?AW4EchoMode@1@XZ"));
    a.variant_to_string = reinterpret_cast<StringGetter>(GetProcAddress(core,"?toString@QVariant@@QEBA?AVQString@@XZ"));
    a.destroy_variant = reinterpret_cast<StringDestructor>(GetProcAddress(core,"??1QVariant@@QEAA@XZ"));
    if (!a.widgets || !a.object_name || !a.button_text || !a.destroy_string || !a.inherits || !a.dispose)
        throw std::runtime_error("required Qt exports missing");
    return a;
}
struct StringResult {
    void* data = nullptr;
    StringDestructor destroy;
    ~StringResult() { if (data) destroy(&data); }
};
std::string DecodeString(void* data) {
    if (!Readable(data, 24)) throw std::runtime_error("invalid QString header");
    auto* bytes = static_cast<char*>(data);
    int count = *reinterpret_cast<int*>(bytes + 4);
    auto offset = *reinterpret_cast<intptr_t*>(bytes + 16);
    if (count < 0 || count > 1048576 || offset < -1048576 || offset > 1048576)
        throw std::runtime_error("invalid QString bounds");
    count = (std::min)(count, 256);
    auto* chars = reinterpret_cast<const wchar_t*>(reinterpret_cast<uintptr_t>(bytes) + offset);
    if (!count) return "";
    if (!Readable(chars, count * sizeof(wchar_t))) throw std::runtime_error("invalid QString data");
    int length = WideCharToMultiByte(CP_UTF8, 0, chars, count, nullptr, 0, nullptr, nullptr);
    std::string result(length, '\0');
    WideCharToMultiByte(CP_UTF8, 0, chars, count, result.data(), length, nullptr, nullptr);
    return result;
}
std::string Text(void* object, StringGetter getter, const Api& a) {
    StringResult value{nullptr,a.destroy_string};
    getter(object,&value.data);
    return DecodeString(value.data);
}
std::string WidgetKind(void* widget, const Api& a) {
    for (const char* name : {"QLineEdit", "QLabel", "QTreeView", "QTableView", "QComboBox",
                            "QAbstractButton", "QDockWidget", "QMainWindow"})
        if (a.inherits(widget,name)) return name;
    return "QWidget";
}
struct Ancestry { std::vector<std::string> rows; bool complete = false; };
Ancestry WidgetAncestry(void* widget, const Api& a) {
    Ancestry result;
    std::vector<void*> seen;
    void* current = a.parent_widget(widget);
    while (current && result.rows.size()<32) {
        if (!Readable(current,sizeof(void*)) || std::find(seen.begin(),seen.end(),current)!=seen.end())
            throw std::runtime_error("invalid or cyclic Qt parent path");
        seen.push_back(current);
        result.rows.push_back(JsonMakeObject({{"kind",JsonMakeString(WidgetKind(current,a))},
            {"object_name",JsonMakeString(Text(current,a.object_name,a))}}));
        current=a.parent_widget(current);
    }
    result.complete=current==nullptr;
    std::reverse(result.rows.begin(),result.rows.end());
    return result;
}
struct ListResult {
    void* data = nullptr;
    Dispose dispose;
    ~ListResult() {
        if (!data) return;
        auto* refs = static_cast<volatile LONG*>(data);
        if (*refs != -1 && (*refs == 0 || InterlockedDecrement(refs) == 0)) dispose(data);
    }
};
std::vector<void*> ListItems(void* data) {
    if (!Readable(data, 16)) throw std::runtime_error("invalid action QList");
    auto* p = static_cast<char*>(data);
    const int allocation = *reinterpret_cast<int*>(p+4), begin = *reinterpret_cast<int*>(p+8), end = *reinterpret_cast<int*>(p+12);
    if (begin < 0 || end < begin || end > allocation || allocation > 20000)
        throw std::runtime_error("invalid action QList bounds");
    auto** items = reinterpret_cast<void**>(p+16);
    if (!Readable(items, size_t(end)*sizeof(void*))) throw std::runtime_error("invalid action QList storage");
    return std::vector<void*>(items+begin,items+end);
}
std::string MenuLabel(std::string text) {
    auto shortcut=text.find('\t');
    if (shortcut!=std::string::npos) text.resize(shortcut);
    text.erase(std::remove(text.begin(),text.end(),'&'),text.end());
    if (text.size()>=3 && text.compare(text.size()-3,3,"\xe2\x80\xa6")==0) text.resize(text.size()-3);
    while (!text.empty() && (text.back()=='.' || text.back()==' ')) text.pop_back();
    return text;
}
struct StringListResult {
    void* data=nullptr;
    Api* api=nullptr;
    ~StringListResult() {
        if (!data) return;
        auto* refs=static_cast<volatile LONG*>(data);
        if (*refs==-1 || (*refs!=0 && InterlockedDecrement(refs)!=0)) return;
        auto* p=static_cast<char*>(data);
        int begin=*reinterpret_cast<int*>(p+8),end=*reinterpret_cast<int*>(p+12);
        if (begin>=0 && end>=begin && end<=20000) {
            auto** items=reinterpret_cast<void**>(p+16);
            for (int i=begin;i<end;++i) api->destroy_string(items+i);
        }
        api->dispose(data);
    }
};
struct Query {
    int offset = 0, limit = 128;
    std::string label, module;
    bool confirm = false;
    std::string menu_window;
    std::string probe_action, expected_title;
    bool open_dialog = false;
    std::string map_path;
    bool outliner = false;
    bool select_outliner = false;
    std::vector<int> row_path;
    std::string expected_root, expected_label, expected_row_key;
    bool targetname_probe=false;
    std::string expected_before, probe_value;
    std::string result, error;
};
// Qt 5 MSVC x64 ABI, independently checked against hasIndex/sibling/itemData.
// These virtual slots belong to QAbstractItemModel, never an editor offset profile.
struct ModelIndex { int row=-1, column=-1; uintptr_t internal=0; void* model=nullptr; };
static_assert(sizeof(ModelIndex)==24,"unexpected QModelIndex ABI");
using ModelGetter=void* (*)(void*);
using ModelCount=int (*)(void*,const ModelIndex*);
using ModelIndexGetter=void* (*)(void*,ModelIndex*,int,int,const ModelIndex*);
using ModelDataGetter=void* (*)(void*,void*,const ModelIndex*,int);
std::string RowKey(const ModelIndex& index) {
    char key[112];snprintf(key,sizeof(key),"%llx:%llx:%d:%d",
        (unsigned long long)index.model,(unsigned long long)index.internal,index.row,index.column);
    return key;
}
std::string ModelDisplay(void* model,const ModelIndex& child,const Api& a) {
    auto** table=*reinterpret_cast<void***>(model);
    auto data=reinterpret_cast<ModelDataGetter>(table[0x88/8]);
    alignas(8) unsigned char value[16]{};
    data(model,value,&child,0);
    struct Guard {void* value;StringDestructor destroy;~Guard(){destroy(value);}} guard{value,a.destroy_variant};
    return Text(value,a.variant_to_string,a);
}
ModelIndex ResolveModelPath(void* model,const std::vector<int>& path) {
    auto** table=*reinterpret_cast<void***>(model);
    auto count=reinterpret_cast<ModelCount>(table[0x70/8]);
    auto index=reinterpret_cast<ModelIndexGetter>(table[0x58/8]);
    ModelIndex current;
    for(int row:path) {
        const int total=count(model,&current);
        if(total<0 || total>100000 || row<0 || row>=total)throw std::runtime_error("outliner path changed or out of range");
        ModelIndex child;index(model,&child,row,0,&current);
        if(child.model!=model || child.row!=row || child.column!=0)throw std::runtime_error("outliner path index mismatch");
        current=child;
    }
    return current;
}
ModelIndex VerifyOutlinerTarget(void* model,const std::vector<int>& path,const std::string& root,
    const std::string& label,const std::string& key,const Api& a) {
    const auto rootIndex=ResolveModelPath(model,{0});
    const auto target=ResolveModelPath(model,path);
    if(ModelDisplay(model,rootIndex,a)!=root || ModelDisplay(model,target,a)!=label || RowKey(target)!=key)
        throw std::runtime_error("outliner document, label or row identity changed; selection not issued");
    return target;
}
bool ProbeName(const std::string& value) {
    return value.empty() || (value.size()<=96 && value.rfind("mcp_probe_",0)==0 &&
        std::all_of(value.begin(),value.end(),[](unsigned char c){return (c>='a' && c<='z') || (c>='0' && c<='9') || c=='_';}));
}
void* ResolveFocusTarget(void* widget,ParentGetter proxy) {
    std::vector<void*> seen;
    while(widget && seen.size()<16) {
        if(std::find(seen.begin(),seen.end(),widget)!=seen.end())throw std::runtime_error("cyclic Qt focus proxy");
        seen.push_back(widget);void* next=proxy(widget);
        if(!next)return widget;
        widget=next;
    }
    throw std::runtime_error("Qt focus proxy chain exceeds bound");
}
bool ProbeMap(const std::string& root) {
    const std::string marker="/content/csgo_addons/test/maps/__mcp_edit_tests/";
    auto start=root.find(marker);
    if(root.size()<8 || root[1]!=':' || root[2]!='/' || start==std::string::npos)return false;
    start+=marker.size();
    if(root.size()<start+34 || root[start+32]!='/')return false;
    if(!std::all_of(root.begin()+start,root.begin()+start+32,[](char c){return (c>='0'&&c<='9') || (c>='a'&&c<='f');}))return false;
    const auto file=root.substr(start+33);
    return file.size()>5 && file.substr(file.size()-5)==".vmap" &&
        std::all_of(file.begin(),file.end(),[](unsigned char c){return (c>='a'&&c<='z') || (c>='0'&&c<='9') || c=='_' || c=='-' || c=='.';}) && file.find("..") == std::string::npos;
}
std::string SmallCString(const char* value) {
    std::string text;
    for(size_t i=0;i<128;++i) {
        if(!Readable(value+i,1))throw std::runtime_error("unreadable property key");
        if(!value[i])return text;
        text.push_back(value[i]);
    }
    throw std::runtime_error("property key exceeds bound");
}
bool TargetnameRow(void* row,HMODULE property) {
    auto* bytes=static_cast<char*>(row);auto base=reinterpret_cast<uintptr_t>(property);
    if(!Readable(row,0x70) || *reinterpret_cast<uintptr_t*>(row)!=base+0x10f900)return false;
    auto* item=*reinterpret_cast<char**>(bytes+0x68);
    if(!Readable(item,0x38) || *reinterpret_cast<uintptr_t*>(item)!=base+0x109488 ||
        *reinterpret_cast<void**>(item+0x18)!=row)throw std::runtime_error("property row binding changed");
    return SmallCString(*reinterpret_cast<char**>(item+0x28))=="targetname";
}
void* FindTargetnameEditor(const std::vector<void*>& items,const Api& a,HMODULE property) {
    void* target=nullptr;int matches=0;
    for(void* widget:items) {
        if(!a.inherits(widget,"QLineEdit") || !a.visible(widget) || !a.enabled(widget))continue;
        bool row=false,dock=false,window=false;void* parent=widget;std::vector<void*> seen;
        while(parent && seen.size()<16) {
            if(std::find(seen.begin(),seen.end(),parent)!=seen.end())throw std::runtime_error("property parent cycle");
            seen.push_back(parent);row=row || TargetnameRow(parent,property);
            const auto name=Text(parent,a.object_name,a);
            if(name=="HammerObjectPropertyDockWidget")dock=true;
            if(name=="CQBaseEditorWnd")window=true;
            parent=a.parent_widget(parent);
        }
        if(!parent && row && dock && window) {target=widget;++matches;}
    }
    if(matches!=1)throw std::runtime_error("unique targetname text editor unavailable; matches="+std::to_string(matches));
    return target;
}
std::string ModelRows(void* model,const Api& a,const ModelIndex* current=nullptr) {
    if (!Readable(model,sizeof(void*)) || !a.inherits(model,"QAbstractItemModel"))
        throw std::runtime_error("invalid outliner model");
    auto** table=*reinterpret_cast<void***>(model);
    if (!Readable(table,0x90)) throw std::runtime_error("invalid model virtual table");
    auto count=reinterpret_cast<ModelCount>(table[0x70/8]);
    auto index=reinterpret_cast<ModelIndexGetter>(table[0x58/8]);
    auto data=reinterpret_cast<ModelDataGetter>(table[0x88/8]);
    auto toString=a.variant_to_string;
    auto destroy=a.destroy_variant;
    if (!toString || !destroy) throw std::runtime_error("QVariant exports missing");
    struct Pending {ModelIndex parent;std::vector<int> path;};
    std::vector<Pending> pending{{ModelIndex{}, {}}};
    std::vector<std::string> rows;
    bool complete=true;
    while (!pending.empty()) {
        auto entry=pending.back();pending.pop_back();
        const int total=count(model,&entry.parent);
        if (total<0 || total>100000) throw std::runtime_error("invalid outliner row count");
        if (entry.path.size()>=8) {if(total)complete=false;continue;}
        for (int row=0;row<total;++row) {
            if (rows.size()>=256) {complete=false;pending.clear();break;}
            ModelIndex child;
            index(model,&child,row,0,&entry.parent);
            if (child.model!=model || child.row!=row || child.column!=0)
                throw std::runtime_error("outliner index identity mismatch");
            alignas(8) unsigned char value[16]{};
            data(model,value,&child,0); // Qt::DisplayRole only, never setData.
            struct VariantGuard {void* value;StringDestructor destroy;~VariantGuard(){destroy(value);}} guard{value,destroy};
            auto text=Text(value,toString,a);
            auto path=entry.path;path.push_back(row);
            std::vector<std::string> jsonPath;for(int part:path)jsonPath.push_back(JsonMakeInt(part));
            rows.push_back(JsonMakeObject({{"path",JsonMakeArray(jsonPath)}, {"display_text",JsonMakeString(text)},
                {"row_key",JsonMakeString(RowKey(child))}}));
            pending.push_back({child,path});
        }
    }
    return JsonMakeObject({{"rows",JsonMakeArray(rows)},{"traversal_complete",JsonMakeBool(complete)},
        {"current_row_key",JsonMakeString(current?RowKey(*current):"")},
        {"current_text",JsonMakeString(current && current->model==model?ModelDisplay(model,*current,a):"")},
        {"row_limit",JsonMakeInt(256)},{"depth_limit",JsonMakeInt(8)}});
}
HWND NativeFileDialog() {
    std::vector<HWND> matches;
    EnumThreadWindows(GetCurrentThreadId(), [](HWND window, LPARAM context)->BOOL {
        wchar_t cls[128]{}; GetClassNameW(window,cls,128);
        DWORD pid=0;
        if (GetWindowThreadProcessId(window,&pid)!=GetCurrentThreadId() ||
            pid!=GetCurrentProcessId() || !IsWindowVisible(window) || wcscmp(cls,L"#32770")) return TRUE;
        if (!GetDlgItem(window,1148) || !GetDlgItem(window,1136) ||
            !GetDlgItem(window,IDOK) || !GetDlgItem(window,IDCANCEL)) return TRUE;
        HWND owner=GetWindow(window,GW_OWNER);
        if (!owner || GetWindowThreadProcessId(owner,&pid)!=GetCurrentThreadId() || pid!=GetCurrentProcessId()) return TRUE;
        GetClassNameW(owner,cls,128);
        if (wcsncmp(cls,L"Qt5",3)!=0 || !wcsstr(cls,L"QWindow")) return TRUE;
        reinterpret_cast<std::vector<HWND>*>(context)->push_back(window);
        return TRUE;
    },reinterpret_cast<LPARAM>(&matches));
    if (matches.size()>1) throw std::runtime_error("ambiguous native file dialogs");
    return matches.empty()?nullptr:matches[0];
}
std::string SetNativeMapFilename(HWND dialog,const std::string& path,bool submit) {
    const int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path.data(),static_cast<int>(path.size()),nullptr,0);
    if (!count) throw std::runtime_error("invalid native path UTF8");
    std::wstring wide(count,L'\0');
    MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path.data(),static_cast<int>(path.size()),wide.data(),count);
    std::replace(wide.begin(),wide.end(),L'/',L'\\');
    HWND combo=GetDlgItem(dialog,1148);
    // Explorer's file-name control can be ComboBoxEx32 -> ComboBox -> Edit.
    // Search only this fixed control's descendants and require one editable leaf.
    std::vector<HWND> edits;
    EnumChildWindows(combo,[](HWND child,LPARAM context)->BOOL {
        wchar_t cls[64]{};GetClassNameW(child,cls,64);
        if (!wcscmp(cls,L"Edit")) reinterpret_cast<std::vector<HWND>*>(context)->push_back(child);
        return TRUE;
    },reinterpret_cast<LPARAM>(&edits));
    HWND edit=edits.size()==1?edits[0]:nullptr;
    if (!edit || !IsWindowEnabled(edit) || !IsWindowEnabled(GetDlgItem(dialog,IDOK)))
        throw std::runtime_error("native filename field or Open button unavailable");
    if (!SetWindowTextW(edit,wide.c_str())) throw std::runtime_error("native filename set failed");
    const int length=GetWindowTextLengthW(edit);
    if (length!=static_cast<int>(wide.size())) throw std::runtime_error("native filename length mismatch");
    std::wstring actual(length+1,L'\0');
    if (GetWindowTextW(edit,actual.data(),length+1)!=length) throw std::runtime_error("native filename read failed");
    actual.resize(length);
    if (actual!=wide) throw std::runtime_error("native filename readback mismatch; Open not queued");
    if (submit && !PostMessageW(dialog,WM_COMMAND,MAKEWPARAM(IDOK,BN_CLICKED),reinterpret_cast<LPARAM>(GetDlgItem(dialog,IDOK))))
        throw std::runtime_error("native Open queue failed");
    std::string normalized=path;std::replace(normalized.begin(),normalized.end(),'/','\\');
    return normalized;
}
uint64_t Collect(Query* q) {
    try {
        Api a = LoadApi();
        ListResult list{nullptr, a.dispose};
        a.widgets(&list.data); // MSVC static ABI: hidden return pointer
        if (!Readable(list.data, 16)) throw std::runtime_error("invalid QList header");
        auto* p = static_cast<char*>(list.data);
        int allocation = *reinterpret_cast<int*>(p + 4), begin = *reinterpret_cast<int*>(p + 8), end = *reinterpret_cast<int*>(p + 12);
        if (begin < 0 || end < begin || end > allocation || allocation > 20000)
            throw std::runtime_error("invalid QList bounds");
        auto** items = reinterpret_cast<void**>(p + 16);
        if (!Readable(items, size_t(end) * sizeof(void*))) throw std::runtime_error("invalid QList storage");
        if (q->outliner) {
            if (!a.visible || !a.enabled || !a.parent_widget) throw std::runtime_error("Qt inspection exports missing");
            auto widgets=GetModuleHandleW(L"Qt5Widgets.dll");
            auto modelGetter=reinterpret_cast<ModelGetter>(GetProcAddress(widgets,"?model@QAbstractItemView@@QEBAPEAVQAbstractItemModel@@XZ"));
            auto selectionGetter=reinterpret_cast<ModelGetter>(GetProcAddress(widgets,"?selectionModel@QAbstractItemView@@QEBAPEAVQItemSelectionModel@@XZ"));
            auto currentGetter=reinterpret_cast<StringGetter>(GetProcAddress(widgets,"?currentIndex@QAbstractItemView@@QEBA?AVQModelIndex@@XZ"));
            if (!modelGetter || !selectionGetter || !currentGetter) throw std::runtime_error("Qt item view exports missing");
            std::vector<std::string> views;
            void* firstView=nullptr;void* firstModel=nullptr;void* firstSelection=nullptr;bool shared=true,current_matches=true;
            for(int i=begin;i<end;++i) {
                void* widget=items[i];
                if (!a.inherits(widget,"QTreeView") || !a.visible(widget)) continue;
                void* ancestor=widget;bool dock=false,window=false;
                std::vector<void*> seen;
                while(ancestor && seen.size()<32) {
                    if(std::find(seen.begin(),seen.end(),ancestor)!=seen.end())throw std::runtime_error("cyclic outliner ancestry");
                    seen.push_back(ancestor);auto name=Text(ancestor,a.object_name,a);
                    if(name=="HammerMapOutlineDockWidget" && a.inherits(ancestor,"QDockWidget"))dock=true;
                    if(name=="CQBaseEditorWnd" && a.inherits(ancestor,"QMainWindow"))window=true;
                    ancestor=a.parent_widget(ancestor);
                }
                if(!dock || !window || ancestor)continue;
                if(views.size()>=4)throw std::runtime_error("too many outliner views");
                void* model=modelGetter(widget);void* selection=selectionGetter(widget);
                ModelIndex current;currentGetter(widget,&current);
                if(current.model!=model || RowKey(current)!=q->expected_row_key)current_matches=false;
                const auto tree=ModelRows(model,a,&current);
                if(!firstView) {firstView=widget;firstModel=model;firstSelection=selection;}
                else if(model!=firstModel || selection!=firstSelection)shared=false;
                views.push_back(tree);
            }
            if(q->targetname_probe) {
                if(!firstView || !firstSelection || !shared || !current_matches)throw std::runtime_error("selected row changed; probe not issued");
                if(ModelDisplay(firstModel,ResolveModelPath(firstModel,{0}),a)!=q->expected_root)
                    throw std::runtime_error("isolated document root changed; probe not issued");
                auto property=GetModuleHandleW(L"propertyeditor.dll");
                if(!Matches(property,1792684908,1826816))throw std::runtime_error("unsupported propertyeditor ABI identity");
                void* editor=FindTargetnameEditor(std::vector<void*>(items+begin,items+end),a,property);
                auto readOnly=reinterpret_cast<Predicate>(GetProcAddress(widgets,"?isReadOnly@QLineEdit@@QEBA_NXZ"));
                if(!readOnly || !a.echo_mode || !a.line_text || readOnly(editor) || a.echo_mode(editor)!=0 || Text(editor,a.line_text,a)!=q->expected_before)
                    throw std::runtime_error("targetname control state/value changed; probe not issued");
                if(q->expected_before==q->probe_value) {
                    q->result=JsonMakeObject({{"status",JsonMakeString("no_change")},{"effect_verified",JsonMakeBool(false)}});return 1;
                }
                if(q->confirm) {
                    using Utf8=void* (*)(void*,const char*,int);using Insert=void (*)(void*,const void*);
                    using SingleShot=void (*)(int,const void*,const char*);
                    auto core=GetModuleHandleW(L"Qt5Core.dll");
                    auto utf8=reinterpret_cast<Utf8>(GetProcAddress(core,"?fromUtf8@QString@@SA?AV1@PEBDH@Z"));
                    auto insert=reinterpret_cast<Insert>(GetProcAddress(widgets,"?insert@QLineEdit@@QEAAXAEBVQString@@@Z"));
                    auto selectAll=reinterpret_cast<Click>(GetProcAddress(widgets,"?selectAll@QLineEdit@@QEAAXXZ"));
                    using Focus=void (*)(void*,int);using Focused=void* (*)();
                    auto focus=reinterpret_cast<Focus>(GetProcAddress(widgets,"?setFocus@QWidget@@QEAAXW4FocusReason@Qt@@@Z"));
                    auto focused=reinterpret_cast<Focused>(GetProcAddress(widgets,"?focusWidget@QApplication@@SAPEAVQWidget@@XZ"));
                    auto proxy=reinterpret_cast<ParentGetter>(GetProcAddress(widgets,"?focusProxy@QWidget@@QEBAPEAV1@XZ"));
                    auto windowGetter=reinterpret_cast<ParentGetter>(GetProcAddress(widgets,"?window@QWidget@@QEBAPEAV1@XZ"));
                    auto activate=reinterpret_cast<Click>(GetProcAddress(widgets,"?setActiveWindow@QApplication@@SAXPEAVQWidget@@@Z"));
                    auto shot=reinterpret_cast<SingleShot>(GetProcAddress(core,"?singleShot@QTimer@@SAXHPEBVQObject@@PEBD@Z"));
                    if(!utf8 || !insert || !selectAll || !shot || !focus || !focused || !proxy || !windowGetter || !activate)throw std::runtime_error("Qt insert/focus/queued commit exports missing");
                    StringResult value{nullptr,a.destroy_string};utf8(&value.data,q->probe_value.data(),static_cast<int>(q->probe_value.size()));
                    void* focusTarget=ResolveFocusTarget(editor,proxy);
                    if(focusTarget!=editor && focusTarget!=a.parent_widget(editor))throw std::runtime_error("targetname focus proxy is outside its editor/parent");
                    void* owner=windowGetter(editor);
                    if(!owner || Text(owner,a.object_name,a)!="CQBaseEditorWnd")throw std::runtime_error("targetname owner window changed");
                    activate(owner);
                    focus(editor,7); // Qt::OtherFocusReason: enter the real editor focus lifecycle.
                    ListResult focusWidgets{nullptr,a.dispose};a.widgets(&focusWidgets.data);
                    if(FindTargetnameEditor(ListItems(focusWidgets.data),a,property)!=editor || focused()!=focusTarget)
                        throw std::runtime_error("targetname focus not acquired or editor rebuilt; insert not issued");
                    selectAll(editor);
                    ListResult refreshed{nullptr,a.dispose};a.widgets(&refreshed.data);
                    if(FindTargetnameEditor(ListItems(refreshed.data),a,property)!=editor || Text(editor,a.line_text,a)!=q->expected_before)
                        throw std::runtime_error("property editor changed after text selection; insert not issued");
                    // Qt strips the 0/1/2 prefix and posts invokeMethod(QueuedConnection).
                    // Queue first so QObject destruction cancels the pending receiver safely.
                    shot(0,editor,"2returnPressed()");
                    shot(0,editor,"2editingFinished()");
                    insert(editor,&value.data);
                    // insert emits the user-edit signal; no object access after its handlers.
                }
                q->result=JsonMakeObject({{"status",JsonMakeString(q->confirm?"text_inserted_commit_queued":"preview")},
                    {"pid",JsonMakeInt(GetCurrentProcessId())},{"effect_verified",JsonMakeBool(false)},
                    {"commit_execution_verified",JsonMakeBool(false)}});return 1;
            }
            if(q->select_outliner) {
                if(!firstView || !firstSelection || !shared)throw std::runtime_error("outliner views do not share a verified selection model");
                const auto target=VerifyOutlinerTarget(firstModel,q->row_path,q->expected_root,q->expected_label,q->expected_row_key,a);
                if(q->confirm) {
                    using Setter=void (*)(void*,const ModelIndex*);
                    auto setCurrent=reinterpret_cast<Setter>(GetProcAddress(widgets,"?setCurrentIndex@QAbstractItemView@@QEAAXAEBVQModelIndex@@@Z"));
                    if(!setCurrent)throw std::runtime_error("Qt current index setter missing");
                    setCurrent(firstView,&target);
                    // Selection handlers may rebuild views. Do not dereference them again.
                }
                q->result=JsonMakeObject({{"pid",JsonMakeInt(GetCurrentProcessId())},
                    {"status",JsonMakeString(q->confirm?"selection_call_returned":"preview")},
                    {"effect_verified",JsonMakeBool(false)},{"document_modified_by_adapter",JsonMakeBool(false)}});
                return 1;
            }
            q->result=JsonMakeObject({{"pid",JsonMakeInt(GetCurrentProcessId())},{"views",JsonMakeArray(views)},
                {"shared_model_and_selection",JsonMakeBool(firstView && firstSelection && shared)},
                {"selection_changed",JsonMakeBool(false)},{"snapshot_atomic",JsonMakeBool(false)}});
            return 1;
        }
        if (!q->map_path.empty()) {
            auto core=GetModuleHandleW(L"Qt5Core.dll"),widgets=GetModuleHandleW(L"Qt5Widgets.dll");
            using Mode=int (*)(void*);
            using Select=void (*)(void*,const void*);
            using Utf8=void* (*)(void*,const char*,int);
            using MemberList=void* (*)(void*,void*);
            auto acceptMode=reinterpret_cast<Mode>(GetProcAddress(widgets,"?acceptMode@QFileDialog@@QEBA?AW4AcceptMode@1@XZ"));
            auto fileMode=reinterpret_cast<Mode>(GetProcAddress(widgets,"?fileMode@QFileDialog@@QEBA?AW4FileMode@1@XZ"));
            auto select=reinterpret_cast<Select>(GetProcAddress(widgets,"?selectFile@QFileDialog@@QEAAXAEBVQString@@@Z"));
            auto setDirectory=reinterpret_cast<Select>(GetProcAddress(widgets,"?setDirectory@QFileDialog@@QEAAXAEBVQString@@@Z"));
            auto utf8=reinterpret_cast<Utf8>(GetProcAddress(core,"?fromUtf8@QString@@SA?AV1@PEBDH@Z"));
            auto selected=reinterpret_cast<MemberList>(GetProcAddress(widgets,"?selectedFiles@QFileDialog@@QEBA?AVQStringList@@XZ"));
            using SingleShot=void (*)(int,const void*,const char*);
            auto shot=reinterpret_cast<SingleShot>(GetProcAddress(core,"?singleShot@QTimer@@SAXHPEBVQObject@@PEBD@Z"));
            if (!acceptMode || !fileMode || !select || !setDirectory || !utf8 || !selected || !shot || !a.visible)
                throw std::runtime_error("file dialog exports unavailable");
            void* dialog=nullptr;int matches=0;
            for (int i=begin;i<end;++i) if (a.inherits(items[i],"QFileDialog") && a.visible(items[i])) {
                dialog=items[i];++matches;
            }
            if (matches!=1) throw std::runtime_error("visible QFileDialog must match exactly once; matches="+std::to_string(matches));
            if (acceptMode(dialog)!=0 || fileMode(dialog)!=1) throw std::runtime_error("dialog must be AcceptOpen/ExistingFile");
            if (!q->confirm) {
                q->result=JsonMakeObject({{"status",JsonMakeString("preview")},{"accept_mode",JsonMakeInt(0)},
                    {"file_mode",JsonMakeInt(1)},{"pid",JsonMakeInt(GetCurrentProcessId())}});
                return 1;
            }
            if (HWND native=NativeFileDialog()) {
                const auto actual=SetNativeMapFilename(native,q->map_path,true);
                q->result=JsonMakeObject({{"status",JsonMakeString("native_map_open_queued")},
                    {"filename_readback",JsonMakeString(actual)}, {"pid",JsonMakeInt(GetCurrentProcessId())},
                    {"document_open_verified",JsonMakeBool(false)}});
                return 1;
            }
            // Native Windows helper can place a slash-normalized full path in
            // its filename field, then reject it as an invalid filename.
            // Set the directory separately and select only the basename.
            const auto separator=q->map_path.find_last_of("/\\");
            if (separator==std::string::npos || separator+1==q->map_path.size())
                throw std::runtime_error("absolute map directory required");
            std::string directory=q->map_path.substr(0,separator);
            std::replace(directory.begin(),directory.end(),'/','\\');
            const auto filename=q->map_path.substr(separator+1);
            StringResult dir{nullptr,a.destroy_string},name{nullptr,a.destroy_string};
            utf8(&dir.data,directory.data(),static_cast<int>(directory.size()));
            utf8(&name.data,filename.data(),static_cast<int>(filename.size()));
            setDirectory(dialog,&dir.data);
            select(dialog,&name.data);
            StringListResult files{nullptr,&a};selected(dialog,&files.data);
            auto values=ListItems(files.data);
            if (values.size()!=1) throw std::runtime_error("selected file count did not read back as one");
            std::string actual=DecodeString(values[0]);
            auto normalize=[](std::string p) {std::replace(p.begin(),p.end(),'/','\\');return p;};
            if (_stricmp(normalize(actual).c_str(),normalize(q->map_path).c_str())!=0)
                throw std::runtime_error("selected file readback differs; accept was not queued");
            shot(0,dialog,"1accept()");
            q->result=JsonMakeObject({{"status",JsonMakeString("map_accept_queued")},
                {"selected_file_readback",JsonMakeString(actual)}, {"pid",JsonMakeInt(GetCurrentProcessId())},
                {"document_open_verified",JsonMakeBool(false)}});
            return 1;
        }
        if (!q->menu_window.empty()) {
            auto widgets = GetModuleHandleW(L"Qt5Widgets.dll");
            using ObjectGetter = void* (*)(void*);
            using MemberListGetter = void* (*)(void*,void*);
            auto menuBar = reinterpret_cast<ObjectGetter>(GetProcAddress(widgets,"?menuBar@QMainWindow@@QEBAPEAVQMenuBar@@XZ"));
            auto actions = reinterpret_cast<MemberListGetter>(GetProcAddress(widgets,"?actions@QWidget@@QEBA?AV?$QList@PEAVQAction@@@@XZ"));
            auto menu = reinterpret_cast<ObjectGetter>(GetProcAddress(widgets,"?menu@QAction@@QEBAPEAVQMenu@@XZ"));
            auto actionText = reinterpret_cast<StringGetter>(GetProcAddress(widgets,"?text@QAction@@QEBA?AVQString@@XZ"));
            auto enabled = reinterpret_cast<Predicate>(GetProcAddress(widgets,"?isEnabled@QAction@@QEBA_NXZ"));
            auto visible = reinterpret_cast<Predicate>(GetProcAddress(widgets,"?isVisible@QAction@@QEBA_NXZ"));
            if (!menuBar || !actions || !menu || !actionText || !enabled || !visible)
                throw std::runtime_error("Qt menu exports missing");
            void* window = nullptr; int matches=0;
            std::vector<std::string> candidates;
            for (int i=begin;i<end;++i) {
                void* w=items[i];
                if (a.inherits(w,"QMainWindow")) {
                    auto name=Text(w,a.object_name,a); candidates.push_back(JsonMakeString(name));
                    if (name==q->menu_window) { window=w; ++matches; }
                }
            }
            if (matches!=1) {
                q->result=JsonMakeObject({{"error",JsonMakeString("main window objectName must match exactly once")},
                    {"matches",JsonMakeInt(matches)}, {"main_window_names",JsonMakeArray(candidates)}});
                return 0;
            }
            if (!q->probe_action.empty()) {
                auto title=reinterpret_cast<StringGetter>(GetProcAddress(widgets,"?windowTitle@QWidget@@QEBA?AVQString@@XZ"));
                if (!title || Text(window,title,a)!=q->expected_title || !a.visible(window))
                    throw std::runtime_error("probe window title/visibility changed");
            }
            void* bar=menuBar(window);
            if (!bar) throw std::runtime_error("menu bar unavailable");
            ListResult top{nullptr,a.dispose}; actions(bar,&top.data);
            std::vector<std::string> rows;
            void* openAction=nullptr; int openMatches=0;
            void* probeAction=nullptr; int probeMatches=0;
            for (void* parent:ListItems(top.data)) {
                auto parentText=Text(parent,actionText,a);
                void* childMenu=menu(parent);
                if (!childMenu) continue;
                ListResult child{nullptr,a.dispose}; actions(childMenu,&child.data);
                for (void* action:ListItems(child.data)) {
                    auto text=Text(action,actionText,a);
                    if (rows.size()>=384) throw std::runtime_error("too many menu actions");
                    const bool ready=enabled(action) && visible(action);
                    rows.push_back(JsonMakeObject({{"menu",JsonMakeString(parentText)},
                        {"text",JsonMakeString(text)}, {"enabled",JsonMakeBool(enabled(action))},
                        {"visible",JsonMakeBool(visible(action))}}));
                    if (MenuLabel(parentText)=="File" && MenuLabel(text)=="Open") {
                        ++openMatches; if (ready) openAction=action;
                    }
                    const auto key=MenuLabel(parentText)+"/"+MenuLabel(text);
                    if (!q->probe_action.empty() && key==q->probe_action) {
                        ++probeMatches;if (ready) probeAction=action;
                    }
                }
            }
            if (!q->probe_action.empty()) {
                if (probeMatches!=1 || !probeAction) throw std::runtime_error("unique ready probe action unavailable");
                if (q->confirm) {
                    using Trigger=void (*)(void*);
                    auto trigger=reinterpret_cast<Trigger>(GetProcAddress(widgets,"?trigger@QAction@@QEAAXXZ"));
                    if (!trigger) throw std::runtime_error("QAction trigger export missing");
                    trigger(probeAction);
                }
                q->result=JsonMakeObject({{"status",JsonMakeString(q->confirm?"action_returned":"preview")},
                    {"action",JsonMakeString(q->probe_action)}, {"pid",JsonMakeInt(GetCurrentProcessId())},
                    {"effect_verified",JsonMakeBool(false)}});
            } else if (q->open_dialog) {
                if (openMatches!=1 || !openAction) throw std::runtime_error("unique enabled visible File/Open action unavailable");
                if (q->confirm) {
                    using SingleShot=void (*)(int,const void*,const char*);
                    auto shot=reinterpret_cast<SingleShot>(GetProcAddress(GetModuleHandleW(L"Qt5Core.dll"),"?singleShot@QTimer@@SAXHPEBVQObject@@PEBD@Z"));
                    if (!shot) throw std::runtime_error("QTimer singleShot export missing");
                    shot(0,openAction,"1trigger()");
                }
                q->result=JsonMakeObject({{"status",JsonMakeString(q->confirm?"open_dialog_queued":"preview")},
                    {"dialog_ready_verified",JsonMakeBool(false)}, {"pid",JsonMakeInt(GetCurrentProcessId())}});
            } else q->result=JsonMakeObject({{"pid",JsonMakeInt(GetCurrentProcessId())},
                {"window_object_name",JsonMakeString(q->menu_window)}, {"actions",JsonMakeArray(rows)}});
            return 1;
        }
        if (!q->label.empty()) {
            if (!a.visible || !a.enabled || !a.click) throw std::runtime_error("Qt action exports missing");
            if (GetModuleHandleA(q->module.c_str())) {
                q->result = JsonMakeObject({{"status", JsonMakeString("already_loaded_no_click")},
                    {"module", JsonMakeString(q->module)}, {"pid", JsonMakeInt(GetCurrentProcessId())}});
                return 1;
            }
            void* target = nullptr;
            int matches = 0;
            for (int i = begin; i < end; ++i) {
                void* widget = items[i];
                if (!Readable(widget, sizeof(void*))) throw std::runtime_error("invalid QWidget");
                if (a.inherits(widget, "QAbstractButton") && Text(widget, a.button_text, a) == q->label) {
                    ++matches; target = widget;
                }
            }
            if (matches != 1) throw std::runtime_error("editor button must match exactly once; matches=" + std::to_string(matches));
            if (!a.visible(target) || !a.enabled(target)) throw std::runtime_error("editor button is hidden or disabled");
            if (q->confirm) a.click(target);
            // No object access after click: the button may have been destroyed by its handler.
            q->result = JsonMakeObject({{"status", JsonMakeString(q->confirm ? "click_returned" : "preview")},
                {"button_text", JsonMakeString(q->label)}, {"module", JsonMakeString(q->module)},
                {"pid", JsonMakeInt(GetCurrentProcessId())}, {"thread_id", JsonMakeInt(GetCurrentThreadId())},
                {"editor_ready_verified", JsonMakeBool(false)}});
            return 1;
        }
        std::vector<std::string> rows;
        if (!a.parent_widget || !a.visible || !a.enabled || !a.label_text || !a.line_text || !a.echo_mode)
            throw std::runtime_error("Qt widget inspection exports missing");
        const int total = end - begin;
        for (int i = q->offset; i < total && i < q->offset + q->limit; ++i) {
            void* widget = items[begin + i];
            if (!Readable(widget, sizeof(void*))) throw std::runtime_error("invalid QWidget");
            const bool button = a.inherits(widget, "QAbstractButton");
            const auto kind=WidgetKind(widget,a);
            const auto ancestry=WidgetAncestry(widget,a);
            const bool visible=a.visible(widget);
            bool redacted=false;
            std::string display;
            if (visible && button) display=Text(widget,a.button_text,a);
            else if (visible && kind=="QLabel") display=Text(widget,a.label_text,a);
            else if (visible && kind=="QLineEdit") {
                redacted=a.echo_mode(widget)!=0;
                if (!redacted) display=Text(widget,a.line_text,a);
            }
            char address[32]; snprintf(address, sizeof(address), "0x%llx", (unsigned long long)widget);
            rows.push_back(JsonMakeObject({
                {"address", JsonMakeString(address)},
                {"kind", JsonMakeString(kind)},
                {"object_name", JsonMakeString(Text(widget, a.object_name, a))},
                {"button_text", JsonMakeString(button ? Text(widget, a.button_text, a) : "")},
                {"display_text",JsonMakeString(display)}, {"text_redacted",JsonMakeBool(redacted)},
                {"visible",JsonMakeBool(visible)}, {"enabled",JsonMakeBool(a.enabled(widget))},
                {"ancestors",JsonMakeArray(ancestry.rows)}, {"ancestry_complete",JsonMakeBool(ancestry.complete)},
                {"locator_unique_verified",JsonMakeBool(false)}
            }));
        }
        q->result = JsonMakeObject({{"pid", JsonMakeInt(GetCurrentProcessId())},
            {"thread_id", JsonMakeInt(GetCurrentThreadId())}, {"total", JsonMakeInt(total)},
            {"offset", JsonMakeInt(q->offset)}, {"returned", JsonMakeInt(rows.size())},
            {"order_stable", JsonMakeBool(false)}, {"addresses_are_ephemeral", JsonMakeBool(true)},
            {"text_limit_utf16", JsonMakeInt(256)}, {"widgets", JsonMakeArray(rows)}});
        return 1;
    } catch (const std::exception& e) { q->error = e.what(); return 0; }
}
}
namespace {
std::string RunQuery(const std::shared_ptr<Query>& query) {
    auto& bridge = HammerBridge::Instance();
    bridge.CallFunctionOnMainThread(reinterpret_cast<uintptr_t>(&Collect),
        {FnArg(reinterpret_cast<uintptr_t>(query.get()))}, 5000, query);
    const int status = bridge.LastMainThreadStatus();
    if (status != 0) return JsonMakeObject({{"error", JsonMakeString("Qt dispatch failed")},
        {"main_thread_status", JsonMakeInt(status)}, {"retry_action", JsonMakeBool(false)}});
    if (!query->error.empty()) return JsonMakeObject({{"error", JsonMakeString(query->error)}});
    return query->result;
}
}
std::string QtWidgetsSnapshot(int offset, int limit) {
    if (offset < 0 || offset > 20000 || limit < 1 || limit > 128)
        return JsonMakeObject({{"error", JsonMakeString("offset must be 0..20000; limit 1..128")}});
    auto query = std::make_shared<Query>(); query->offset = offset; query->limit = limit;
    return RunQuery(query);
}
std::string QtOpenEditor(const std::string& editor, bool confirm) {
    auto query = std::make_shared<Query>();
    if (editor == "hammer") { query->label = "Hammer (Map Editor)"; query->module = "hammer.dll"; }
    else if (editor == "pet") { query->label = "Particle Editor"; query->module = "pet.dll"; }
    else if (editor == "met") { query->label = "Material Editor"; query->module = "met.dll"; }
    else if (editor == "modeldoc_editor") { query->label = "ModelDoc Editor"; query->module = "modeldoc_editor.dll"; }
    else return JsonMakeObject({{"error", JsonMakeString("unsupported editor")}});
    query->confirm = confirm;
    return RunQuery(query);
}
std::string QtMenuActions(const std::string& window) {
    if (window.empty() || window.size()>128) return JsonMakeObject({{"error",JsonMakeString("invalid window objectName")}});
    auto query=std::make_shared<Query>(); query->menu_window=window;
    return RunQuery(query);
}
std::string QtHammerOpenDialog(bool confirm) {
    auto query=std::make_shared<Query>(); query->menu_window="CQBaseEditorWnd";
    query->open_dialog=true; query->confirm=confirm;
    return RunQuery(query);
}
std::string QtHammerProbeAction(const std::string& action,const std::string& title,bool confirm) {
    // Experimental fixed commands only. No arbitrary QAction/object addresses.
    if (action!="File/Save" && action!="Edit/Select All" && action!="Edit/Delete Selected" &&
        action!="Edit/Undo" && action!="Edit/Redo")
        return JsonMakeObject({{"error",JsonMakeString("unsupported probe action")}});
    if (title.size()>256 || title.rfind("Hammer - [",0)!=0)
        return JsonMakeObject({{"error",JsonMakeString("exact Hammer document title required")}});
    auto query=std::make_shared<Query>();query->menu_window="CQBaseEditorWnd";
    query->probe_action=action;query->expected_title=title;query->confirm=confirm;
    return RunQuery(query);
}

std::string QtFileDialogMap(const std::string& path,bool confirm) {
    if (path.size()<6 || path.size()>1024 || path.find('\0')!=std::string::npos ||
        _stricmp(path.c_str()+path.size()-5,".vmap")!=0)
        return JsonMakeObject({{"error",JsonMakeString("existing .vmap path required")}});
    int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path.data(),static_cast<int>(path.size()),nullptr,0);
    if (!count) return JsonMakeObject({{"error",JsonMakeString("invalid UTF8 path")}});
    std::wstring wide(count,L'\0');MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path.data(),static_cast<int>(path.size()),wide.data(),count);
    DWORD attributes=GetFileAttributesW(wide.c_str());
    if (attributes==INVALID_FILE_ATTRIBUTES || (attributes&FILE_ATTRIBUTE_DIRECTORY))
        return JsonMakeObject({{"error",JsonMakeString("map file is missing or is a directory")}});
    auto query=std::make_shared<Query>();query->map_path=path;query->confirm=confirm;
    return RunQuery(query);
}

std::string QtHammerOutliner() {
    auto query=std::make_shared<Query>();query->outliner=true;return RunQuery(query);
}
std::string QtHammerOutlinerSelect(const std::vector<int>& path,const std::string& root,
    const std::string& label,const std::string& key,bool confirm) {
    if(path.empty() || path.size()>8 || root.empty() || root.size()>1024 || label.empty() || label.size()>1024 || key.empty() || key.size()>112 ||
       std::any_of(path.begin(),path.end(),[](int row){return row<0 || row>=100000;}))
        return JsonMakeObject({{"error",JsonMakeString("bounded row path, root, label and observed row key required")}});
    auto query=std::make_shared<Query>();query->outliner=true;query->select_outliner=true;
    query->row_path=path;query->expected_root=root;query->expected_label=label;query->expected_row_key=key;query->confirm=confirm;
    return RunQuery(query);
}
std::string QtHammerTargetnameProbe(const std::string& root,const std::string& selected_key,
    const std::string& before,const std::string& value,bool confirm) {
    if(!ProbeMap(root) || selected_key.empty() || selected_key.size()>112 || !ProbeName(before) || !ProbeName(value))
        return JsonMakeObject({{"error",JsonMakeString("UUID-scoped test map, observed selection and probe-only names required")}});
    auto query=std::make_shared<Query>();query->outliner=true;query->targetname_probe=true;
    query->expected_root=root;query->expected_row_key=selected_key;query->expected_before=before;query->probe_value=value;query->confirm=confirm;
    return RunQuery(query);
}

}
