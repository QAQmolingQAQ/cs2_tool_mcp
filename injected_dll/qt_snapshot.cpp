// Fixed, read-only Qt 5 x64 ABI adapter. No caller-supplied function/object addresses.
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
    std::string result, error;
};
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
        const int total = end - begin;
        for (int i = q->offset; i < total && i < q->offset + q->limit; ++i) {
            void* widget = items[begin + i];
            if (!Readable(widget, sizeof(void*))) throw std::runtime_error("invalid QWidget");
            const bool button = a.inherits(widget, "QAbstractButton");
            char address[32]; snprintf(address, sizeof(address), "0x%llx", (unsigned long long)widget);
            rows.push_back(JsonMakeObject({
                {"address", JsonMakeString(address)},
                {"kind", JsonMakeString(button ? "QAbstractButton" : "QWidget")},
                {"object_name", JsonMakeString(Text(widget, a.object_name, a))},
                {"button_text", JsonMakeString(button ? Text(widget, a.button_text, a) : "")}
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

}
