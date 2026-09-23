// test_pipe_client.cpp - Minimal pipe client that loads cs2_tool.dll and tests IPC
#include <windows.h>
#include <cstdio>
#include <cstring>
#include <string>

#pragma pack(push, 1)
struct MsgHeader { uint32_t magic; uint32_t version; uint32_t length; uint32_t reserved; };
#pragma pack(pop)

constexpr uint32_t kMsgMagic = 0x43533254;
const wchar_t kPipeName[] = L"\\\\.\\pipe\\CS2ToolMCP";

static void P(const char* fmt, ...) {
    char buf[512];
    va_list ap; va_start(ap, fmt);
    _vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    DWORD w = 0;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), buf, (DWORD)strlen(buf), &w, nullptr);
}

static bool WriteAll(HANDLE h, const void* data, size_t size) {
    const char* p = (const char*)data;
    DWORD total = 0;
    while (total < (DWORD)size) {
        DWORD written = 0;
        if (!WriteFile(h, p + total, (DWORD)(size - total), &written, nullptr)) return false;
        if (written == 0) return false;
        total += written;
    }
    return true;
}

static bool ReadExact(HANDLE h, void* buf, size_t size) {
    char* p = (char*)buf;
    DWORD total = 0;
    while (total < (DWORD)size) {
        DWORD got = 0;
        if (!ReadFile(h, p + total, (DWORD)(size - total), &got, nullptr)) return false;
        if (got == 0) return false;
        total += got;
    }
    return true;
}

static std::string DoCall(const std::string& method) {
    // Connect with retries
    for (int attempt = 0; attempt < 10; ++attempt) {
        if (WaitNamedPipeW(kPipeName, 500)) break;
        if (GetLastError() != ERROR_SEM_TIMEOUT && GetLastError() != ERROR_ACCESS_DENIED) {
            P("WaitNamedPipe err=%lu\n", GetLastError());
            return "ERROR WaitNamedPipe";
        }
        P("  waiting... (%d)\n", attempt + 1);
    }

    HANDLE h = CreateFileW(kPipeName, GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) { P("CreateFileW err=%lu\n", GetLastError()); return "ERROR CreateFileW"; }

    std::string req = "{\"id\":1,\"method\":\"" + method + "\"}";
    MsgHeader hdr = { kMsgMagic, 1, (uint32_t)req.size(), 0 };

    if (!WriteAll(h, &hdr, sizeof(hdr)) || !WriteAll(h, req.data(), req.size())) {
        P("WriteFile err=%lu\n", GetLastError()); CloseHandle(h); return "ERROR WriteFile";
    }

    MsgHeader rhdr;
    if (!ReadExact(h, &rhdr, sizeof(rhdr))) { P("ReadFile hdr err=%lu\n", GetLastError()); CloseHandle(h); return "ERROR ReadFile hdr"; }
    if (rhdr.magic != kMsgMagic) { CloseHandle(h); return "ERROR bad magic"; }

    std::string resp(rhdr.length, '\0');
    if (rhdr.length > 0 && !ReadExact(h, resp.data(), rhdr.length)) { P("ReadFile payload err=%lu\n", GetLastError()); CloseHandle(h); return "ERROR ReadFile payload"; }

    CloseHandle(h);
    return resp;
}

int main() {
    P("=== cs2_tool pipe client test ===\n");

    HMODULE hDll = nullptr;
    const char* dllpath = "d:\\ai\\agent\\tool\\mcp\\cs2\\cs2_tool_mcp\\injected_dll\\build_msvc\\Release\\cs2_tool.dll";
    P("[1] Loading: %s\n", dllpath);
    hDll = LoadLibraryA(dllpath);
    if (!hDll) {
        P("FATAL LoadLibrary err=%lu\n", GetLastError());
        return 1;
    }
    P("  OK\n");

    auto fnInit = (int (__cdecl*)())GetProcAddress(hDll, "Cs2Tool_Init");
    auto fnVer = (const char* (__cdecl*)())GetProcAddress(hDll, "Cs2Tool_Version");
    auto fnShut = (int (__cdecl*)())GetProcAddress(hDll, "Cs2Tool_Shutdown");
    P("[2] Version: %s\n", fnVer ? fnVer() : "null");
    int rc = fnInit ? fnInit() : -1;
    P("[3] Cs2Tool_Init -> %d\n", rc);

    P("[4] Sleeping 500ms...\n");
    Sleep(500);

    P("[5] Waiting for pipe...\n");
    int ok = 0, fail = 0;
    for (auto* name : {"ping", "list_tools", "get_status", "list_interfaces", "get_hammer_app"}) {
        P("\n--- %s ---\n", name);
        std::string resp = DoCall(name);
        if (resp.substr(0, 5) == "ERROR") { P("  FAIL: %s\n", resp.c_str()); fail++; }
        else { P("  OK (len=%zu): %.150s\n", resp.size(), resp.c_str()); ok++; }
    }

    P("\n=== %d OK / %d FAIL ===\n", ok, fail);
    if (fnShut) fnShut();
    FreeLibrary(hDll);
    return fail == 0 ? 0 : 1;
}
