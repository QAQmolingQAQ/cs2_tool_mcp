// hammer_bridge.h - Hammer.dll interface bridge
#pragma once
#include "protocol.h"
#include <windows.h>
#include <string>
#include <vector>
#include <cstdint>
#include <cstring>

namespace cs2tool {

using CreateInterfaceFn = void* (*)(const char* name, int* returnCode);

// 通用调用参数：默认是整数/指针；kind=1/2 时按 float/double 走 xmm0..xmm3（Win64 ABI）。
// 栈参数（第 5/6 个）无论何种类型都只占一个 8 字节槽，位模式直接入栈，故只需标注前 4 槽。
struct FnArg {
    uint64_t bits = 0;
    uint8_t  kind = 0;   // 0=整数/指针, 1=float32, 2=float64
    FnArg() = default;
    FnArg(uint64_t v) : bits(v), kind(0) {}          // 允许从整数字面量隐式构造
    FnArg(int v) : bits((uint64_t)(int64_t)v), kind(0) {}
    static FnArg Float(float f) {
        FnArg a; uint32_t b; memcpy(&b, &f, 4); a.bits = b; a.kind = 1; return a;
    }
    static FnArg Double(double d) {
        FnArg a; memcpy(&a.bits, &d, 8); a.kind = 2; return a;
    }
};

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

// 工具模块：CS2 每个编辑器 DLL（hammer / met / modeldoc_editor / pet）都**自带**一份
// CreateInterface 和一套 ToolSystem2 工具系统，各自的接口注册表相互独立。
struct ToolModule {
    std::string name;                  // 模块文件名，如 "hammer.dll"
    std::string label;                 // 短名，如 "hammer"
    std::string iface_name;            // 工具系统接口名，如 "ToolSystem2_001"
    uintptr_t   rva_create_iface = 0;  // CreateInterface 的 RVA（GetProcAddress 失败时兜底）
    uintptr_t   rva_iface_head = 0;    // s_pInterfaceRegs 链表头的 RVA（序言解析失败时兜底）
    uintptr_t   rva_bind_head = 0;     // CBaseBindTargetDescriptor 描述符全局链表头 RVA（见 REVERSE_NOTES §17/§23）
    HMODULE     module = nullptr;
    uintptr_t   base = 0;              // 加载基址（= 内存里的 OptionalHeader.ImageBase）
    void*       create_interface = nullptr;
    uintptr_t   iface_list_head = 0;   // s_pInterfaceRegs 的运行时地址（从 CreateInterface 序言解析）
    void*       tool_system = nullptr; // CreateInterface(iface_name) 的结果
    std::string tool_system_class;     // tool_system 的 RTTI 实现类名（如 CMaterialEditorTool / CPetApp）
    bool        loaded = false;        // 该模块当前是否已加载进进程
};

// 模块内 CreateInterface 注册表里的一项
struct ModuleInterface {
    std::string name;                  // 接口名，如 "ToolSystem2_001"
    uintptr_t   factory = 0;           // 工厂函数地址
};

// 模块内可绑定目标描述符（CBindableTargetDescriptorInstance<T>，布局见 REVERSE_NOTES §17.6）
struct ModuleBindTarget {
    std::string name;                  // 目标名（vfn0 / 节点 +0x10）
    std::string cls;                   // 实现类名（节点 +0x18）
    std::string source_file;           // 注册处源文件（节点 +0x20）
    int         line = 0;              // 注册处行号（节点 +0x28）
    std::vector<std::string> commands; // 命令名（命令对象 +0x08）
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

    // --- 工具模块（hammer / met / modeldoc_editor / pet）------------------
    // 每个编辑器 DLL 各自一套 CreateInterface + ToolSystem2；未加载的模块 loaded==false。
    // force_refresh=true 时重新枚举进程模块（pet.dll 这类按需加载的编辑器
    // 可能在注入之后才加载，不能只信 Initialize() 时的一次性快照）
    const std::vector<ToolModule>& ToolModules(bool force_refresh = false);
    // 目标模块未加载时会自动重探一次，再判定
    bool GetToolModule(const std::string& module, ToolModule& out);
    bool GetToolSystemFor(const std::string& module, void*& out);

    // --- 按模块枚举（hammer / met / modeldoc / pet 通用）-------------------
    // 该模块 CreateInterface 注册表里登记的全部接口（名字 + 工厂地址）
    std::vector<ModuleInterface> ListModuleInterfaces(const ToolModule& m);
    // 直接向该模块的 CreateInterface 取任意命名接口
    void* GetModuleInterface(const ToolModule& m, const std::string& name, int* rc = nullptr);
    // 该模块的可绑定目标描述符链（Key Bindings / 工具热键体系，见 REVERSE_NOTES §17/§23）。
    // include_commands=false 时只列目标名/类名，不展开命令（大模块如 modeldoc 可省大量读取）。
    std::vector<ModuleBindTarget> ListModuleBindTargets(const ToolModule& m, bool include_commands);

    // 解析某个对象主虚表的 RTTI 实现类名（MSVC BCD64：vtable-8 → COL → TypeDescriptor）。
    // module_base 用于把 COL 里的 32 位 RVA 还原成绝对地址。失败返回空串。
    std::string ResolveVtableClassName(uintptr_t obj, uintptr_t module_base);

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
    // Calls fn with up to 6 args (x64 fastcall). 参数可用 FnArg::Float/Double 标注浮点，
    // 浮点按 Win64 ABI 走 xmm0..xmm3；前 4 槽为 rcx/rdx/r8/r9 或 xmm0..3，第 5/6 槽在栈上。
    uint64_t CallFunction(uintptr_t fn, const std::vector<FnArg>& args);
    // on_main_thread=true 时在目标进程主线程上执行（会改文档/UI 的虚函数必需）
    uint64_t CallVirtual(uintptr_t this_ptr, size_t index, const std::vector<FnArg>& args,
                         bool on_main_thread = false, DWORD timeout_ms = 5000);

    // 在目标进程的**主线程**上调用 fn（多线程亲和的操作必须走这里）。
    // 实现：向主线程挂一个临时 WH_GETMESSAGE 钩子，钩子过程里执行 fn 并唤醒调用方。
    // 返回 fn 的返回值；超时或失败返回 0。
    uint64_t CallFunctionOnMainThread(uintptr_t fn, const std::vector<FnArg>& args,
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

    // 探测 hammer / met / modeldoc_editor / pet，填充 tool_modules_
    void RefreshToolModules();
    std::vector<ToolModule> tool_modules_;
};

// 记录本 DLL 的模块句柄（WH_GETMESSAGE 钩子需要它），由 DllMain 调用
void SetBridgeModuleHandle(HMODULE mod);

} // namespace cs2tool
