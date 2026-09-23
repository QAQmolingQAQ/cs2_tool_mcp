// dllmain.cpp - DLL entry point
#include <windows.h>
#include <thread>
#include "ipc_pipe.h"
#include "hammer_bridge.h"
#include <atomic>

namespace {
std::atomic<bool> g_initialized{false};
}

static DWORD WINAPI InitThread(LPVOID) {
    if (!cs2tool::HammerBridge::Instance().IsInitialized()) {
        cs2tool::HammerBridge::Instance().Initialize();
    }
    cs2tool::IpcPipeServer::Instance().Start();
    g_initialized.store(true);
    return 0;
}

extern "C" BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpReserved) {
    (void)lpReserved;

    switch (fdwReason) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hinstDLL);
        cs2tool::SetBridgeModuleHandle(hinstDLL);   // 主线程钩子需要本模块句柄
        CreateThread(nullptr, 0, InitThread, nullptr, 0, nullptr);
        break;
    case DLL_PROCESS_DETACH:
        cs2tool::IpcPipeServer::Instance().Stop();
        cs2tool::HammerBridge::Instance().Shutdown();
        g_initialized.store(false);
        break;
    default:
        break;
    }

    return TRUE;
}

extern "C" __declspec(dllexport) int Cs2Tool_Init() {
    if (!cs2tool::IpcPipeServer::Instance().IsRunning()) {
        cs2tool::HammerBridge::Instance().Initialize();
        cs2tool::IpcPipeServer::Instance().Start();
        return 1;
    }
    return 0;
}

extern "C" __declspec(dllexport) int Cs2Tool_Shutdown() {
    cs2tool::IpcPipeServer::Instance().Stop();
    cs2tool::HammerBridge::Instance().Shutdown();
    return 1;
}

extern "C" __declspec(dllexport) const char* Cs2Tool_Version() {
    return "cs2_tool_injector v0.1.0";
}
