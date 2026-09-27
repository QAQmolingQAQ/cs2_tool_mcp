// hammer_bridge.h - Hammer.dll interface bridge
#pragma once
#include "protocol.h"
#include <windows.h>
#include <string>
#include <vector>
#include <cstdint>

namespace cs2tool {

using CreateInterfaceFn = void* (*)(const char* name, int* returnCode);

// Interface linked list node (from IDA analysis of sub_18004A730)
// qword[0] = factory_func, qword[1] = interface_name_str, qword[2] = next_node
struct InterfaceNode {
    void* factory;
    const char* name;
    InterfaceNode* next;
};

// Module descriptor for list_modules / get_module
struct ModuleDesc {
    std::string name;
    uintptr_t base = 0;        // HMODULE (load address)
    uintptr_t image_base = 0;  // PE OptionalHeader.ImageBase
    size_t size = 0;           // SizeOfImage
};

// Typed value kinds for read_value / write_value
enum class ValueType {
    U8, U16, U32, U64,
    I8, I16, I32, I64,
    F32, F64, Ptr,
};

bool ParseValueType(const std::string& s, ValueType& out);

class HammerBridge {
public:
    static HammerBridge& Instance();

    bool Initialize();
    void Shutdown();

    bool IsInitialized() const { return initialized_; }
    std::string GetStatus() const;

    void* GetInterface(const std::string& name, int* rc = nullptr);
    std::vector<std::string> ListInterfaces();

    void* GetHammerApp();
    void* GetToolSystem();

    bool ReadMem(uintptr_t addr, void* buf, size_t size);
    bool WriteMem(uintptr_t addr, const void* buf, size_t size);
    uint8_t ReadByte(uintptr_t addr);
    uint32_t ReadDword(uintptr_t addr);
    uint64_t ReadQword(uintptr_t addr);

    uintptr_t GetHammerBase() const { return hammer_base_; }
    uintptr_t Rva(uintptr_t rva) const { return hammer_base_ + rva; }

    // --- process / module primitives -----------------------------------
    const std::vector<ModuleDesc>& ListModules();
    bool GetModule(const std::string& name, ModuleDesc& out);
    // Translate "hammer.dll+0x1234" or a bare address into an absolute address.
    bool ResolveAddress(const std::string& expr, uintptr_t& out);

    // --- typed memory --------------------------------------------------
    bool ReadTyped(uintptr_t addr, ValueType type, uint64_t& out_bits);
    bool WriteTyped(uintptr_t addr, ValueType type, uint64_t bits);
    bool ReadCString(uintptr_t addr, size_t max_len, std::string& out);
    bool ReadPointerChain(uintptr_t base, const std::vector<int64_t>& offsets, uintptr_t& out);

    // --- pattern scan --------------------------------------------------
    bool FindPattern(const std::string& module, const std::string& pattern,
                     size_t limit, std::vector<uintptr_t>& out);
    // Scan committed private/RW heap regions across the whole process.
    // Only qword-aligned matches are reported. Optional [lo,hi) bounds.
    bool ScanHeap(const std::string& pattern, size_t limit,
                  uintptr_t lo, uintptr_t hi, std::vector<uintptr_t>& out);

    // --- generic invocation --------------------------------------------
    // Calls fn with up to 6 integer/pointer args (x64 fastcall).
    // args[0] is RCX, args[1] RDX, args[2] R8, args[3] R9, args[4..5] on stack.
    uint64_t CallFunction(uintptr_t fn, const std::vector<uint64_t>& args);
    // on_main_thread=true 时在目标进程主线程上执行（会改文档/UI 的虚函数必需）
    uint64_t CallVirtual(uintptr_t this_ptr, size_t index, const std::vector<uint64_t>& args,
                         bool on_main_thread = false, DWORD timeout_ms = 5000);

    // 在目标进程的**主线程**上调用 fn（多线程亲和的操作必须走这里）。
    // 实现：向主线程挂一个临时 WH_GETMESSAGE 钩子，钩子过程里执行 fn 并唤醒调用方。
    // 返回 fn 的返回值；超时或失败返回 0。
    uint64_t CallFunctionOnMainThread(uintptr_t fn, const std::vector<uint64_t>& args,
                                      DWORD timeout_ms = 5000);

    // 取目标进程主线程 ID（0 表示未找到）
    static DWORD GetMainThreadId();

    // 主线程派发的自检：对 **DLL 内部**的无害函数做一次主线程调用。
    // 不触碰 Hammer 任何代码，用于安全验证 WH_GETMESSAGE 派发链路是否可用。
    uint64_t SelfTestOnMainThread(DWORD timeout_ms = 3000);

    // 最近一次主线程派发的状态：
    //   0=成功 1=等待超时 2=未找到主线程 3=SetWindowsHookEx 失败 4=调用中触发异常
    int LastMainThreadStatus() const;

    // --- hammer map docs ------------------------------------------------
    std::vector<uintptr_t> ListMapDocs();

private:
    HammerBridge() = default;
    ~HammerBridge() = default;
    HammerBridge(const HammerBridge&) = delete;
    HammerBridge& operator=(const HammerBridge&) = delete;

    bool initialized_ = false;
    HMODULE hammer_module_ = nullptr;
    CreateInterfaceFn create_interface_ = nullptr;
    uintptr_t hammer_base_ = 0;
    uintptr_t list_head_rva_ = 0;

    void* hammer_app_instance_ = nullptr;

    std::vector<ModuleDesc> modules_;  // cached by ListModules()
};

// 记录本 DLL 的模块句柄（WH_GETMESSAGE 钩子需要它），由 DllMain 调用
void SetBridgeModuleHandle(HMODULE mod);

} // namespace cs2tool
