// Independent host: exercises the actual Windows hook dispatcher, no CS2 required.
#include "../hammer_bridge.cpp"
#include "../qt_snapshot.cpp"
#include <atomic>
#include <thread>
#include <iostream>

std::atomic<int> entered{0}, finished{0}, released{0};
HANDLE entered_event;
uint64_t SlowTarget() {
    ++entered;
    SetEvent(entered_event);
    Sleep(300);
    ++finished;
    return 42;
}
uint64_t FastTarget() { ++entered; return 43; }
int destroyed_strings = 0, disposed_lists = 0;
alignas(8) unsigned char string_data[64]{};
void* FakeStringGetter(void*, void* result) {
    *static_cast<void**>(result) = string_data;
    return result;
}
void FakeStringDestructor(void*) { ++destroyed_strings; }
void FakeListDispose(void*) { ++disposed_lists; }
int CheckQtCleanup() {
    auto* size = reinterpret_cast<int*>(string_data + 4);
    *size = 2;
    *reinterpret_cast<intptr_t*>(string_data + 16) = 24;
    auto* text = reinterpret_cast<wchar_t*>(string_data + 24);
    text[0] = L'A'; text[1] = 0x4e2d;
    cs2tool::Api api{}; api.destroy_string = FakeStringDestructor;
    if (cs2tool::Text(nullptr, FakeStringGetter, api) != "A\xe4\xb8\xad" || destroyed_strings != 1) return 30;
    *size = -1;
    try { cs2tool::Text(nullptr, FakeStringGetter, api); return 31; }
    catch (const std::runtime_error&) {}
    if (destroyed_strings != 2) return 32;
    LONG refs = -1;
    { cs2tool::ListResult value{&refs, FakeListDispose}; }
    if (refs != -1 || disposed_lists) return 33;
    refs = 2;
    { cs2tool::ListResult value{&refs, FakeListDispose}; }
    if (refs != 1 || disposed_lists) return 34;
    { cs2tool::ListResult value{&refs, FakeListDispose}; }
    if (refs != 0 || disposed_lists != 1) return 35;
    if (cs2tool::QtWidgetsSnapshot(-1, 128).find("error") == std::string::npos) return 36;
    if (cs2tool::QtOpenEditor("arbitrary", true).find("unsupported") == std::string::npos) return 37;
    alignas(8) unsigned char string_list[32]{};
    *reinterpret_cast<LONG*>(string_list)=1;
    *reinterpret_cast<int*>(string_list+4)=2;
    *reinterpret_cast<int*>(string_list+12)=2;
    auto** string_items=reinterpret_cast<void**>(string_list+16);
    string_items[0]=string_data;string_items[1]=string_data;
    api.dispose=FakeListDispose;
    { cs2tool::StringListResult strings{string_list,&api}; }
    if (destroyed_strings!=4 || disposed_lists!=2) return 41;
    if (cs2tool::QtFileDialogMap("not-a-map.txt",true).find("error")==std::string::npos) return 42;
    if (cs2tool::QtHammerProbeAction("File/Exit","Hammer - [test.vmap]",true).find("unsupported")==std::string::npos) return 43;
    if (cs2tool::QtHammerProbeAction("File/Save","Hammer",true).find("title required")==std::string::npos) return 44;
    if (cs2tool::MenuLabel("&Open...") != "Open" || cs2tool::MenuLabel("&File") != "File" || cs2tool::MenuLabel("&Open\tCtrl+O") != "Open") return 38;
    if (cs2tool::QtMenuActions("").find("error") == std::string::npos) return 39;
    alignas(8) unsigned char list_data[24]{};
    *reinterpret_cast<int*>(list_data+4)=1;
    *reinterpret_cast<int*>(list_data+12)=2;
    try { cs2tool::ListItems(list_data); return 40; } catch (const std::runtime_error&) {}
    return 0;
}
int CheckNativeFilename(HWND owner) {
    HWND dialog=CreateWindowExW(0,L"#32770",L"Open",WS_POPUP|WS_VISIBLE,
        -32000,-32000,1,1,owner,nullptr,GetModuleHandleW(nullptr),nullptr);
    if (!dialog) return 50;
    HWND holder=CreateWindowW(L"Static",L"",WS_CHILD|WS_VISIBLE,
        0,0,1,1,dialog,reinterpret_cast<HMENU>(1148),GetModuleHandleW(nullptr),nullptr);
    HWND combo=CreateWindowW(L"ComboBox",L"",WS_CHILD|WS_VISIBLE|CBS_DROPDOWN,
        0,0,1,1,holder,nullptr,GetModuleHandleW(nullptr),nullptr);
    CreateWindowW(L"ComboBox",L"",WS_CHILD|WS_VISIBLE,0,0,1,1,dialog,
        reinterpret_cast<HMENU>(1136),GetModuleHandleW(nullptr),nullptr);
    CreateWindowW(L"Button",L"Open",WS_CHILD|WS_VISIBLE,0,0,1,1,dialog,
        reinterpret_cast<HMENU>(IDOK),GetModuleHandleW(nullptr),nullptr);
    CreateWindowW(L"Button",L"Cancel",WS_CHILD|WS_VISIBLE,0,0,1,1,dialog,
        reinterpret_cast<HMENU>(IDCANCEL),GetModuleHandleW(nullptr),nullptr);
    int result=0;
    if (cs2tool::NativeFileDialog()!=dialog) result=51;
    const std::string path="C:/isolated/map.vmap";
    if (!result && cs2tool::SetNativeMapFilename(dialog,path,false)!="C:\\isolated\\map.vmap") result=52;
    wchar_t actual[256]{};GetWindowTextW(FindWindowExW(combo,nullptr,L"Edit",nullptr),actual,256);
    if (!result && wcscmp(actual,L"C:\\isolated\\map.vmap")) result=53;
    HWND extra=CreateWindowW(L"Edit",L"",WS_CHILD|WS_VISIBLE,0,0,1,1,holder,
        nullptr,GetModuleHandleW(nullptr),nullptr);
    try { cs2tool::SetNativeMapFilename(dialog,path,true);result=55; }
    catch (const std::runtime_error&) {}
    DestroyWindow(extra);
    EnableWindow(GetDlgItem(dialog,IDOK),FALSE);
    try { cs2tool::SetNativeMapFilename(dialog,path,true);result=54; }
    catch (const std::runtime_error&) {}
    DestroyWindow(dialog);
    return result;
}
int main() {
    const int cleanup = CheckQtCleanup();
    if (cleanup) return cleanup;
    const wchar_t* cls = L"Qt5152QWindowIcon";
    WNDCLASSW wc{}; wc.lpfnWndProc = DefWindowProcW;
    wc.hInstance = GetModuleHandleW(nullptr); wc.lpszClassName = cls;
    RegisterClassW(&wc);
    HWND window = CreateWindowW(cls, cls, WS_VISIBLE | WS_POPUP,
        -32000, -32000, 1, 1, nullptr, nullptr, wc.hInstance, nullptr);
    if (!window) return 10;
    const int native=CheckNativeFilename(window);
    if (native) return native;
    if (cs2tool::HammerBridge::GetMainThreadId() != GetCurrentThreadId()) return 20;
    if (!cs2tool::IsQtWindowClass(L"Qt5QWindowIcon") ||
        !cs2tool::IsQtWindowClass(L"Qt5152QWindowPopupDropShadowSaveBits") ||
        cs2tool::IsQtWindowClass(L"QtQWindow") ||
        cs2tool::IsQtWindowClass(L"SDL_app")) return 21;
    HANDLE ready = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE stop = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    std::thread other([&] {
        HWND second = CreateWindowW(cls, cls, WS_POPUP, 0, 0, 1, 1,
            nullptr, nullptr, wc.hInstance, nullptr);
        SetEvent(ready);
        WaitForSingleObject(stop, 2000);
        DestroyWindow(second);
    });
    WaitForSingleObject(ready, 2000);
    const bool rejected = cs2tool::HammerBridge::GetMainThreadId() == 0;
    SetEvent(stop); other.join(); CloseHandle(stop); CloseHandle(ready);
    if (!rejected) return 22;
    if (cs2tool::HammerBridge::GetMainThreadId() != GetCurrentThreadId()) return 23;
    entered_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    auto& bridge = cs2tool::HammerBridge::Instance();
    std::atomic<bool> done{false};
    std::atomic<int> failure{0};
    // Do not pump: a queued request must cancel, and never execute later.
    std::thread queued([&] {
        bridge.CallFunctionOnMainThread((uintptr_t)&FastTarget, {}, 5);
        if (bridge.LastMainThreadStatus() != 1) failure = 11;
    });
    queued.join();
    MSG msg;
    while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
    if (entered != 0) return 12;
    std::thread running([&] {
        auto owner = std::shared_ptr<void>(new int(1), [](void* p) {
            delete static_cast<int*>(p); ++released;
        });
        bridge.CallFunctionOnMainThread((uintptr_t)&SlowTarget, {}, 100, owner);
        const int status = bridge.LastMainThreadStatus();
        owner.reset();
        if (status != 6 || released != 0 || finished != 0) failure = 13;
        bridge.CallFunctionOnMainThread((uintptr_t)&FastTarget, {}, 10);
        if (bridge.LastMainThreadStatus() != 5) failure = 14;
        while (!finished.load()) Sleep(1);
        // Callback may still be releasing its final reference.
        for (int i=0; i<1000 && released != 1; ++i) Sleep(1);
        if (released != 1 || entered != 1) failure = 15;
        if (bridge.SelfTestOnMainThread(1000) != 0x43533254434F4445ULL ||
            bridge.LastMainThreadStatus() != 0) failure = 16;
        done = true;
    });
    while (!done) {
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
        Sleep(1);
    }
    running.join();
    CloseHandle(entered_event);
    DestroyWindow(window);
    std::cout << "dispatch test failure=" << failure << " entered=" << entered
              << " finished=" << finished << " released=" << released << '\n';
    return failure;
}
