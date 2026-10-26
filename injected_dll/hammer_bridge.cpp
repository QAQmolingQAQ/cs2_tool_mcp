// hammer_bridge.cpp - Hammer.dll interface bridge implementation
#include "hammer_bridge.h"
#include <psapi.h>
#include <tlhelp32.h>
#include <algorithm>
#include <cstring>
#include <mutex>
#include <memory>

#pragma comment(lib, "psapi.lib")

namespace cs2tool {

// ---------------------------------------------------------------------------
// memory-range helpers
// ---------------------------------------------------------------------------
namespace {

bool IsRangeReadable(uintptr_t addr, size_t size) {
    if (!addr || size == 0) return false;
    uintptr_t cur = addr;
    const uintptr_t end = addr + size;
    while (cur < end) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (VirtualQuery((LPCVOID)cur, &mbi, sizeof(mbi)) == 0) return false;
        if (mbi.State != MEM_COMMIT) return false;
        const DWORD prot = mbi.Protect & 0xFF;
        const bool readable =
            prot == PAGE_READONLY || prot == PAGE_READWRITE ||
            prot == PAGE_EXECUTE_READ || prot == PAGE_EXECUTE_READWRITE ||
            prot == PAGE_WRITECOPY || prot == PAGE_EXECUTE_WRITECOPY;
        if (!readable) return false;
        const uintptr_t region_end = (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
        if (region_end <= cur) return false;
        cur = region_end;
    }
    return true;
}

bool IsRangeWritable(uintptr_t addr, size_t size) {
    if (!addr || size == 0) return false;
    MEMORY_BASIC_INFORMATION mbi{};
    if (VirtualQuery((LPCVOID)addr, &mbi, sizeof(mbi)) == 0) return false;
    if (mbi.State != MEM_COMMIT) return false;
    const DWORD prot = mbi.Protect & 0xFF;
    if (mbi.Protect & PAGE_GUARD) return false;
    return prot == PAGE_READWRITE || prot == PAGE_EXECUTE_READWRITE ||
           prot == PAGE_WRITECOPY || prot == PAGE_EXECUTE_WRITECOPY;
}

std::string ToLower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return (char)std::tolower(c); });
    return s;
}

std::string Trim(const std::string& s) {
    size_t b = s.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) return "";
    size_t e = s.find_last_not_of(" \t\r\n");
    return s.substr(b, e - b + 1);
}

bool ParseUint(const std::string& s, uint64_t& out) {
    std::string t = Trim(s);
    if (t.empty()) return false;
    int base = 10;
    size_t start = 0;
    if (t.size() > 2 && t[0] == '0' && (t[1] == 'x' || t[1] == 'X')) {
        base = 16;
        start = 2;
    } else if (t.size() > 1 && t.back() == 'h') {
        base = 16;
        t.pop_back();
    }
    try {
        out = std::stoull(t.substr(start), nullptr, base);
    } catch (...) {
        return false;
    }
    return true;
}

} // namespace

bool ParseValueType(const std::string& s, ValueType& out) {
    const std::string t = ToLower(Trim(s));
    if (t == "u8" || t == "byte") out = ValueType::U8;
    else if (t == "u16" || t == "word") out = ValueType::U16;
    else if (t == "u32" || t == "dword") out = ValueType::U32;
    else if (t == "u64" || t == "qword") out = ValueType::U64;
    else if (t == "i8") out = ValueType::I8;
    else if (t == "i16") out = ValueType::I16;
    else if (t == "i32" || t == "int") out = ValueType::I32;
    else if (t == "i64") out = ValueType::I64;
    else if (t == "f32" || t == "float") out = ValueType::F32;
    else if (t == "f64" || t == "double") out = ValueType::F64;
    else if (t == "ptr" || t == "pointer") out = ValueType::Ptr;
    else return false;
    return true;
}

namespace HammerAddr {
    constexpr uintptr_t kCreateInterfaceRva = 0x1401130;
    constexpr uintptr_t kInterfaceListHeadRva = 0x2738770;
    constexpr uintptr_t kToolSystemFactoryRva = 0x1152B0;
    constexpr uintptr_t kToolSystemNameRva = 0x1CB4898;

    // 2026-09 新版 hammer.dll（见 REVERSE_NOTES.md §3）：
    // 旧全局文档表 (0x2355020/0x2355028) 已失效，改为运行时对象链枚举：
    //   CHammerApp+0x58 / +0x60 = CHammerEditorSession* 的 CUtlVector
    //   session+0x138                = 当前活动 CMapDocSession*
    //   CMapDoc 内嵌在 session 包装里：doc = wrapper + 0x10
    constexpr uintptr_t kAppSessionVecCount = 0x58;
    constexpr uintptr_t kAppSessionVecMem   = 0x60;
    constexpr uintptr_t kSessionActiveWrap  = 0x138;
    constexpr uintptr_t kWrapperDocEmbed    = 0x10;
    constexpr uintptr_t kCMapDocVtableRva   = 0x1766188;
}

HammerBridge& HammerBridge::Instance() {
    static HammerBridge inst;
    return inst;
}

static uintptr_t GetModuleImageBase(HMODULE hMod) {
    uintptr_t base = (uintptr_t)hMod;
    auto* dos = (IMAGE_DOS_HEADER*)base;
    if (dos->e_magic == IMAGE_DOS_SIGNATURE) {
        auto* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
        if (nt->Signature == IMAGE_NT_SIGNATURE) {
            return nt->OptionalHeader.ImageBase;
        }
    }
    return 0;
}

// ---------------------------------------------------------------------------
// 工具模块表：四个 CS2 编辑器 DLL 各自的工具系统接口名。
//   · hammer.dll / met.dll / pet.dll  -> "ToolSystem2_001"
//   · modeldoc_editor.dll             -> "ToolSystem2_ModelDoc"
// 四者导出表完全一致（各 6 个导出，都含 CreateInterface），故优先 GetProcAddress；
// RVA 只在取不到导出时兜底（值取自各 DLL 的导出表）。
// ---------------------------------------------------------------------------
namespace {
struct ToolModuleSpec {
    const char* name;
    const char* label;
    const char* iface;
    uintptr_t   rva_create_iface;
    uintptr_t   rva_iface_head;   // s_pInterfaceRegs 链头（序言解析失败时兜底）
    uintptr_t   rva_bind_head;    // CBaseBindTargetDescriptor 链头（REVERSE_NOTES §23.2 IDA 实测）
};
const ToolModuleSpec kToolModuleSpecs[] = {
    // rva_iface_head 也可从 CreateInterface 序言 `REX 8B /r [rip+d]` 动态解析，
    // 表里的值是 2026-10-10 版实测，仅作兜底；rva_bind_head 是数据全局，无法推导，只能硬编码。
    { "hammer.dll",          "hammer",   "ToolSystem2_001",      0x1401130, 0x2738770,  0x2731E98 },
    { "met.dll",             "met",      "ToolSystem2_001",      0x1D89A0,  0x4A1740,   0x4A0AD0  },
    { "modeldoc_editor.dll", "modeldoc", "ToolSystem2_ModelDoc", 0xAF2AB0,  0x1AAB588,  0x1AA9620 },
    { "pet.dll",             "pet",      "ToolSystem2_001",      0x3A2AE0,  0x93A1D0,   0x938408 },
};

// 从 CreateInterface 序言解析 s_pInterfaceRegs 链头地址。
// Source 系统一序言：4C 8B 0D d32（mov r9,[rip+d]）/ 48 8B 05/0D（mov rax/rcx,[rip+d]）。
// 返回 0 = 不是这个模式（调用方改用 RVA 兜底）。
uintptr_t ParseInterfaceListHead(void* fn) {
    if (!fn) return 0;
    auto* p = reinterpret_cast<uint8_t*>(fn);
    __try {
        uint8_t rex = p[0], op = p[1], modrm = p[2];
        if ((rex == 0x48 || rex == 0x4C) && op == 0x8B && (modrm & 0xC7) == 0x05) {
            int32_t disp = *reinterpret_cast<int32_t*>(p + 3);
            return reinterpret_cast<uintptr_t>(p) + 7 + disp;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return 0;
    }
    return 0;
}

std::string LowerAscii(const std::string& s) {
    std::string r = s;
    for (auto& c : r) {
        if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
    }
    return r;
}
}  // namespace

void HammerBridge::RefreshToolModules() {
    tool_modules_.clear();
    for (const auto& spec : kToolModuleSpecs) {
        ToolModule tm;
        tm.name = spec.name;
        tm.label = spec.label;
        tm.iface_name = spec.iface;
        tm.rva_create_iface = spec.rva_create_iface;
        tm.rva_iface_head = spec.rva_iface_head;
        tm.rva_bind_head = spec.rva_bind_head;

        HMODULE h = GetModuleHandleA(spec.name);
        if (!h) {  // 大小写/名称不匹配时退回全量枚举
            HMODULE mods[1024];
            DWORD need = 0;
            if (EnumProcessModules(GetCurrentProcess(), mods, sizeof(mods), &need)) {
                for (DWORD i = 0; i < need / sizeof(HMODULE); i++) {
                    char nm[MAX_PATH] = {};
                    if (GetModuleBaseNameA(GetCurrentProcess(), mods[i], nm, sizeof(nm)) &&
                        _stricmp(nm, spec.name) == 0) {
                        h = mods[i];
                        break;
                    }
                }
            }
        }

        if (h) {
            tm.module = h;
            tm.base = GetModuleImageBase(h);
            tm.loaded = true;
            tm.create_interface = (void*)GetProcAddress(h, "CreateInterface");
            if (!tm.create_interface && tm.base) {
                tm.create_interface = (void*)(tm.base + tm.rva_create_iface);
            }
            // s_pInterfaceRegs 链头：优先从 CreateInterface 序言动态解析，失败用 RVA 兜底
            tm.iface_list_head = ParseInterfaceListHead(tm.create_interface);
            if (!tm.iface_list_head && tm.base) {
                tm.iface_list_head = tm.base + tm.rva_iface_head;
            }
            if (tm.create_interface) {
                int rc = -1;
                auto fn = (CreateInterfaceFn)tm.create_interface;
                tm.tool_system = fn(tm.iface_name.c_str(), &rc);
                if (tm.tool_system && tm.base) {
                    tm.tool_system_class = ResolveVtableClassName((uintptr_t)tm.tool_system, tm.base);
                }
            }
        }
        tool_modules_.push_back(tm);
    }
}

const std::vector<ToolModule>& HammerBridge::ToolModules(bool force_refresh) {
    if (force_refresh || tool_modules_.empty()) RefreshToolModules();
    return tool_modules_;
}

bool HammerBridge::GetToolModule(const std::string& module, ToolModule& out) {
    const std::string want = LowerAscii(module);
    auto find_module = [&](const std::vector<ToolModule>& list, bool require_loaded) -> const ToolModule* {
        for (const auto& m : list) {
            if (want == LowerAscii(m.name) || want == LowerAscii(m.label)) {
                if (require_loaded && !m.loaded) return nullptr;
                return &m;
            }
        }
        return nullptr;
    };

    // 第一次查缓存（可能是注入后的旧快照）
    if (const auto* m = find_module(tool_modules_, false)) {
        if (m->loaded) { out = *m; return true; }
    }
    // 没查到 / 查到但尚未加载 -> 重新枚举进程模块再查一次
    // （pet.dll 等按需加载的编辑器可能在注入之后才被打开）
    if (const auto* m = find_module(ToolModules(true), false)) {
        out = *m;
        return true;
    }
    return false;
}

bool HammerBridge::GetInterfaceModule(const std::string& module, ToolModule& out) {
    if (GetToolModule(module, out)) return true;

    // Resolve by the process module list, never by a caller-supplied path.
    // This supports runtime DLLs such as scenesystem/tier0/particles without
    // pretending that they own an editor ToolSystem or bind-target chain.
    ModuleDesc desc;
    if (!GetModule(module, desc)) return false;
    HMODULE handle = reinterpret_cast<HMODULE>(desc.base);
    void* create = reinterpret_cast<void*>(GetProcAddress(handle, "CreateInterface"));
    if (!create) return false;

    out = ToolModule{};
    out.name = desc.name;
    out.label = LowerAscii(desc.name);
    if (out.label.size() > 4 && out.label.substr(out.label.size() - 4) == ".dll") {
        out.label.resize(out.label.size() - 4);
    }
    out.module = handle;
    out.base = desc.base;
    out.loaded = true;
    out.create_interface = create;
    const uintptr_t head = ParseInterfaceListHead(create);
    if (head >= desc.base && head - desc.base < desc.size &&
        IsRangeReadable(head, sizeof(uintptr_t))) {
        out.iface_list_head = head;
    }
    return true;
}

bool HammerBridge::GetToolSystemFor(const std::string& module, void*& out) {
    ToolModule m;
    if (!GetToolModule(module, m) || !m.tool_system) return false;
    out = m.tool_system;
    return true;
}

std::vector<ModuleInterface> HammerBridge::ListModuleInterfaces(const ToolModule& m) {
    std::vector<ModuleInterface> out;
    if (!m.loaded || !m.iface_list_head) return out;
    // InterfaceNode { void* factory; const char* name; InterfaceNode* next; }（24 字节）
    uintptr_t node = ReadQword(m.iface_list_head);
    constexpr int kMaxNodes = 256;
    for (int i = 0; node && i < kMaxNodes; ++i) {
        ModuleInterface mi;
        mi.factory = ReadQword(node + 0x00);
        uintptr_t name_ptr = ReadQword(node + 0x08);
        if (name_ptr) ReadCString(name_ptr, 128, mi.name);
        out.push_back(std::move(mi));
        node = ReadQword(node + 0x10);
    }
    return out;
}

void* HammerBridge::GetModuleInterface(const ToolModule& m, const std::string& name, int* rc) {
    if (!m.loaded || !m.create_interface || name.empty()) return nullptr;
    int local_rc = -1;
    void* result = ((CreateInterfaceFn)m.create_interface)(name.c_str(), &local_rc);
    if (rc) *rc = local_rc;
    return result;
}

std::string HammerBridge::ResolveVtableClassName(uintptr_t obj, uintptr_t module_base) {
    // MSVC x64 RTTI：对象 +0x00 = 主虚表；虚表 -8 = CompleteObjectLocator(COL)；
    // COL +0x0C = pTypeDescriptor 的 32 位 RVA（相对模块基址）；TD +0x10 = 名字内联字符数组。
    if (!obj || !module_base) return "";
    uintptr_t vtable = ReadQword(obj + 0x00);
    if (!vtable) return "";
    uintptr_t col = ReadQword(vtable - 8);
    if (!col) return "";
    uint32_t td_rva = ReadDword(col + 0x0C);
    if (!td_rva) return "";
    std::string name;
    ReadCString(module_base + td_rva + 0x10, 128, name);
    if (name.rfind(".?AV", 0) == 0) name.erase(0, 4);  // 去掉 MSVC 修饰前缀
    while (!name.empty() && name.back() == '@') name.pop_back();  // 去掉尾部修饰
    return name;
}

std::vector<ModuleBindTarget> HammerBridge::ListModuleBindTargets(const ToolModule& m,
                                                                  bool include_commands) {
    // 节点布局与 hammer 完全一致（同一套 tier2 框架静态链进各编辑器 DLL），
    // 字段偏移见 REVERSE_NOTES §17.6；四个模块的链表头 RVA 见 §23.2。
    constexpr uintptr_t kOffName      = 0x10;  // 目标名 char*
    constexpr uintptr_t kOffClass     = 0x18;  // 实现类名 char*
    constexpr uintptr_t kOffFile      = 0x20;  // 注册源文件 char*
    constexpr uintptr_t kOffLine      = 0x28;  // 行号 u32
    constexpr uintptr_t kOffNext      = 0x38;  // next
    constexpr uintptr_t kOffCmdCount  = 0x40;  // 命令数 i32
    constexpr uintptr_t kOffCmdArray  = 0x48;  // 命令对象指针数组
    constexpr uintptr_t kCmdOffName   = 0x08;  // 命令名 char*
    constexpr int kMaxNodes = 4096;
    constexpr int kMaxCmds  = 512;

    std::vector<ModuleBindTarget> out;
    if (!m.loaded || !m.base || !m.rva_bind_head) return out;
    uintptr_t node = ReadQword(m.base + m.rva_bind_head);
    uintptr_t prev = 0;
    for (int i = 0; node && i < kMaxNodes; ++i) {
        if (node == prev) break;  // 自指保护
        prev = node;
        ModuleBindTarget t;
        uintptr_t p;
        if ((p = ReadQword(node + kOffName)))  ReadCString(p, 128, t.name);
        if ((p = ReadQword(node + kOffClass))) ReadCString(p, 128, t.cls);
        if ((p = ReadQword(node + kOffFile)))  ReadCString(p, 260, t.source_file);
        t.line = (int)ReadDword(node + kOffLine);
        if (include_commands) {
            int cnt = (int)ReadDword(node + kOffCmdCount);
            uintptr_t arr = ReadQword(node + kOffCmdArray);
            if (cnt > 0 && cnt <= kMaxCmds && arr) {
                for (int k = 0; k < cnt; ++k) {
                    uintptr_t cmd = ReadQword(arr + (uintptr_t)k * 8);
                    if (!cmd) continue;
                    uintptr_t cname = ReadQword(cmd + kCmdOffName);
                    std::string s;
                    if (cname) ReadCString(cname, 160, s);
                    if (!s.empty()) t.commands.push_back(std::move(s));
                }
            }
        }
        out.push_back(std::move(t));
        node = ReadQword(node + kOffNext);
    }
    return out;
}

bool HammerBridge::Initialize() {
    if (initialized_) return true;

    // Enumerate modules in current process
    HMODULE hMods[1024];
    DWORD needed = 0;
    if (EnumProcessModules(GetCurrentProcess(), hMods, sizeof(hMods), &needed)) {
        for (DWORD i = 0; i < needed / sizeof(HMODULE); i++) {
            char name[MAX_PATH] = {};
            if (GetModuleBaseNameA(GetCurrentProcess(), hMods[i], name, sizeof(name))) {
                if (_stricmp(name, "hammer.dll") == 0) {
                    hammer_module_ = hMods[i];
                    hammer_base_ = GetModuleImageBase(hammer_module_);
                    break;
                }
            }
        }
    }

    // Fallback: main module of current process (if injected into hammer.exe)
    if (!hammer_module_) {
        hammer_module_ = GetModuleHandleA(nullptr);
        if (hammer_module_) {
            char name[MAX_PATH] = {};
            GetModuleBaseNameA(GetCurrentProcess(), hammer_module_, name, sizeof(name));
            if (_stricmp(name, "hammer.exe") != 0 && _stricmp(name, "hammer.dll") != 0) {
                hammer_module_ = nullptr;
                hammer_base_ = 0;
            } else {
                hammer_base_ = GetModuleImageBase(hammer_module_);
            }
        }
    }

    // hammer 专属路径：解析 CreateInterface 并拿 CHammerApp（ToolSystem2_001）
    if (hammer_module_ && hammer_base_) {
        create_interface_ = (CreateInterfaceFn)GetProcAddress(hammer_module_, "CreateInterface");
        if (!create_interface_) {
            create_interface_ = (CreateInterfaceFn)(hammer_base_ + HammerAddr::kCreateInterfaceRva);
        }
        list_head_rva_ = HammerAddr::kInterfaceListHeadRva;
        if (create_interface_) {
            int rc = -1;
            hammer_app_instance_ = GetInterface("ToolSystem2_001", &rc);
        }
    }

    // 探测全部编辑器模块（hammer / met / modeldoc_editor / pet）
    RefreshToolModules();
    for (const auto& m : tool_modules_) {
        if (m.label == "hammer" && m.tool_system) hammer_app_instance_ = m.tool_system;
    }

    // 只要有一个模块的工具系统可用就算初始化成功 —— 编辑器进程可能只加载了
    // modeldoc_editor / pet，并没有 hammer.dll
    for (const auto& m : tool_modules_) {
        if (m.loaded && m.tool_system) { initialized_ = true; break; }
    }
    return initialized_;
}

void HammerBridge::Shutdown() {
    hammer_app_instance_ = nullptr;
    create_interface_ = nullptr;
    tool_modules_.clear();
    initialized_ = false;
}

std::string HammerBridge::GetStatus() const {
    std::vector<std::pair<std::string, std::string>> fields;
    fields.push_back({"initialized", JsonMakeBool(initialized_)});
    fields.push_back({"hammer_base", JsonMakeInt((int64_t)hammer_base_)});
    fields.push_back({"create_interface", JsonMakeInt((int64_t)(void*)create_interface_)});
    fields.push_back({"tool_system", JsonMakeInt((int64_t)hammer_app_instance_)});

    std::vector<std::string> iface_items;
    if (hammer_base_) {
        uintptr_t list_head = hammer_base_ + list_head_rva_;
        auto* node = *(InterfaceNode**)list_head;
        int count = 0;
        while (node && count < 30) {
            if (node->name) {
                iface_items.push_back(JsonMakeString(node->name));
            }
            node = node->next;
            count++;
        }
    }
    fields.push_back({"interfaces", JsonMakeArray(iface_items)});

    return JsonMakeObject(fields);
}

void* HammerBridge::GetInterface(const std::string& name, int* rc) {
    if (!create_interface_) return nullptr;
    int local_rc = -1;
    void* result = create_interface_(name.c_str(), &local_rc);
    if (rc) *rc = local_rc;
    return result;
}

std::vector<std::string> HammerBridge::ListInterfaces() {
    std::vector<std::string> result;
    if (!hammer_base_) return result;

    uintptr_t list_head = hammer_base_ + list_head_rva_;
    auto* node = *(InterfaceNode**)list_head;
    while (node) {
        if (node->name) {
            result.push_back(node->name);
        }
        node = node->next;
    }
    return result;
}

void* HammerBridge::GetHammerApp() {
    return hammer_app_instance_;
}

void* HammerBridge::GetToolSystem() {
    return hammer_app_instance_;
}

bool HammerBridge::ReadMem(uintptr_t addr, void* buf, size_t size) {
    if (!IsRangeReadable(addr, size)) return false;
    memcpy(buf, (void*)addr, size);
    return true;
}

bool HammerBridge::WriteMem(uintptr_t addr, const void* buf, size_t size) {
    if (!IsRangeWritable(addr, size)) return false;
    // temporarily lift write protection if the page is read-only but committed
    DWORD old = 0;
    bool unprotected = VirtualProtect((LPVOID)addr, size, PAGE_EXECUTE_READWRITE, &old) != 0;
    memcpy((void*)addr, buf, size);
    if (unprotected) {
        DWORD tmp = 0;
        VirtualProtect((LPVOID)addr, size, old, &tmp);
    }
    return true;
}

uint8_t HammerBridge::ReadByte(uintptr_t addr) {
    uint8_t v = 0;
    ReadMem(addr, &v, 1);
    return v;
}

uint32_t HammerBridge::ReadDword(uintptr_t addr) {
    uint32_t v = 0;
    ReadMem(addr, &v, 4);
    return v;
}

uint64_t HammerBridge::ReadQword(uintptr_t addr) {
    uint64_t v = 0;
    ReadMem(addr, &v, 8);
    return v;
}

// ---------------------------------------------------------------------------
// module primitives
// ---------------------------------------------------------------------------
const std::vector<ModuleDesc>& HammerBridge::ListModules() {
    // 每次都重新枚举：hammer.dll 是**打开地图后**才被加载的，若做永久缓存，
    // 在地图打开前调用过一次就再也看不到 hammer.dll（实测踩过这个坑）。
    modules_.clear();

    HMODULE mods[1024];
    DWORD needed = 0;
    if (!EnumProcessModules(GetCurrentProcess(), mods, sizeof(mods), &needed)) {
        return modules_;
    }
    const DWORD count = needed / sizeof(HMODULE);
    for (DWORD i = 0; i < count; i++) {
        ModuleDesc d;
        char name[MAX_PATH] = {};
        if (!GetModuleBaseNameA(GetCurrentProcess(), mods[i], name, sizeof(name))) continue;
        d.name = name;
        d.base = (uintptr_t)mods[i];
        d.image_base = GetModuleImageBase(mods[i]);
        MODULEINFO mi{};
        if (GetModuleInformation(GetCurrentProcess(), mods[i], &mi, sizeof(mi))) {
            d.size = mi.SizeOfImage;
        }
        modules_.push_back(d);
    }
    return modules_;
}

bool HammerBridge::GetModule(const std::string& name, ModuleDesc& out) {
    std::string want = ToLower(Trim(name));
    if (want.find('.') == std::string::npos) want += ".dll";
    for (const auto& m : ListModules()) {
        if (ToLower(m.name) == want) {
            out = m;
            return true;
        }
    }
    return false;
}

bool HammerBridge::ResolveAddress(const std::string& expr, uintptr_t& out) {
    const std::string s = Trim(expr);
    if (s.empty()) return false;

    const size_t plus = s.find('+');
    if (plus != std::string::npos) {
        const std::string mod = s.substr(0, plus);
        const std::string off = s.substr(plus + 1);
        ModuleDesc m;
        if (!GetModule(mod, m)) return false;
        uint64_t delta = 0;
        if (!ParseUint(off, delta)) return false;
        out = m.base + (uintptr_t)delta;
        return true;
    }

    uint64_t v = 0;
    if (!ParseUint(s, v)) return false;
    out = (uintptr_t)v;
    return true;
}

// ---------------------------------------------------------------------------
// typed memory
// ---------------------------------------------------------------------------
bool HammerBridge::ReadTyped(uintptr_t addr, ValueType type, uint64_t& out_bits) {
    size_t size = 0;
    switch (type) {
    case ValueType::U8: case ValueType::I8: size = 1; break;
    case ValueType::U16: case ValueType::I16: size = 2; break;
    case ValueType::U32: case ValueType::I32: case ValueType::F32: size = 4; break;
    default: size = 8; break;
    }
    if (!IsRangeReadable(addr, size)) return false;

    switch (type) {
    case ValueType::U8:  { uint8_t v;  memcpy(&v, (void*)addr, 1); out_bits = (uint64_t)v; break; }
    case ValueType::I8:  { int8_t v;   memcpy(&v, (void*)addr, 1); out_bits = (uint64_t)(int64_t)v; break; }
    case ValueType::U16: { uint16_t v; memcpy(&v, (void*)addr, 2); out_bits = (uint64_t)v; break; }
    case ValueType::I16: { int16_t v;  memcpy(&v, (void*)addr, 2); out_bits = (uint64_t)(int64_t)v; break; }
    case ValueType::U32: { uint32_t v; memcpy(&v, (void*)addr, 4); out_bits = (uint64_t)v; break; }
    case ValueType::I32: { int32_t v;  memcpy(&v, (void*)addr, 4); out_bits = (uint64_t)(int64_t)v; break; }
    case ValueType::F32: { float f;    memcpy(&f, (void*)addr, 4); uint32_t v; memcpy(&v, &f, 4); out_bits = (uint64_t)v; break; }
    case ValueType::F64: { double d;   memcpy(&d, (void*)addr, 8); memcpy(&out_bits, &d, 8); break; }
    default:             { uint64_t v; memcpy(&v, (void*)addr, 8); out_bits = v; break; }
    }
    return true;
}

bool HammerBridge::WriteTyped(uintptr_t addr, ValueType type, uint64_t bits) {
    size_t size = 0;
    switch (type) {
    case ValueType::U8: case ValueType::I8: size = 1; break;
    case ValueType::U16: case ValueType::I16: size = 2; break;
    case ValueType::U32: case ValueType::I32: case ValueType::F32: size = 4; break;
    default: size = 8; break;
    }
    return WriteMem(addr, &bits, size);
}

bool HammerBridge::ReadCString(uintptr_t addr, size_t max_len, std::string& out) {
    out.clear();
    if (!max_len) max_len = 256;
    if (max_len > 4096) max_len = 4096;
    if (!IsRangeReadable(addr, 1)) return false;

    // read page-by-page so a string crossing into an unmapped page stops cleanly
    std::string result;
    uintptr_t cur = addr;
    while (result.size() < max_len) {
        if (!IsRangeReadable(cur, 1)) break;
        char c = *(const char*)cur;
        if (c == '\0') { out = result; return true; }
        result.push_back(c);
        cur++;
    }
    out = result;
    return true;
}

bool HammerBridge::ReadPointerChain(uintptr_t base, const std::vector<int64_t>& offsets,
                                    uintptr_t& out) {
    uintptr_t cur = base;
    for (size_t i = 0; i < offsets.size(); i++) {
        if (i > 0) {
            if (!IsRangeReadable(cur, 8)) return false;
            cur = *(uintptr_t*)cur;
        }
        cur = (uintptr_t)((int64_t)cur + offsets[i]);
    }
    out = cur;
    return IsRangeReadable(cur, 1);
}

// ---------------------------------------------------------------------------
// pattern scan
// ---------------------------------------------------------------------------
namespace {
struct PatternByte { uint8_t value; bool wildcard; };

bool ParsePattern(const std::string& pattern, std::vector<PatternByte>& out) {
    out.clear();
    size_t i = 0;
    while (i < pattern.size()) {
        unsigned char c = (unsigned char)pattern[i];
        if (c == ' ' || c == '\t') { i++; continue; }
        if (c == '?') {
            out.push_back({0, true});
            while (i < pattern.size() && pattern[i] == '?') i++;
            continue;
        }
        auto hexval = [](unsigned char h) -> int {
            if (h >= '0' && h <= '9') return h - '0';
            if (h >= 'a' && h <= 'f') return h - 'a' + 10;
            if (h >= 'A' && h <= 'F') return h - 'A' + 10;
            return -1;
        };
        int hi = hexval(c);
        if (hi < 0) return false;
        if (i + 1 >= pattern.size()) return false;
        int lo = hexval((unsigned char)pattern[i + 1]);
        if (lo < 0) return false;
        out.push_back({(uint8_t)((hi << 4) | lo), false});
        i += 2;
    }
    return !out.empty();
}
} // namespace

bool HammerBridge::FindPattern(const std::string& module, const std::string& pattern,
                               size_t limit, std::vector<uintptr_t>& out) {
    out.clear();
    if (!limit) limit = 20;

    std::vector<PatternByte> pat;
    if (!ParsePattern(pattern, pat)) return false;

    ModuleDesc mod;
    if (!module.empty()) {
        if (!GetModule(module, mod)) return false;
    } else {
        if (!hammer_base_) return false;
        mod.base = hammer_base_;
        HMODULE h = GetModuleHandleA("hammer.dll");
        if (!h) h = hammer_module_;
        MODULEINFO mi{};
        if (!h || !GetModuleInformation(GetCurrentProcess(), h, &mi, sizeof(mi))) return false;
        mod.size = mi.SizeOfImage;
    }

    const uintptr_t start = mod.base;
    const uintptr_t end = mod.base + mod.size;
    const size_t n = pat.size();

    uintptr_t cur = start;
    while (cur < end && out.size() < limit) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (VirtualQuery((LPCVOID)cur, &mbi, sizeof(mbi)) == 0) break;
        const uintptr_t region_end = (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
        uintptr_t scan_end = region_end < end ? region_end : end;

        if (mbi.State == MEM_COMMIT && IsRangeReadable(cur, 1)) {
            const DWORD prot = mbi.Protect & 0xFF;
            const bool readable =
                prot == PAGE_READONLY || prot == PAGE_READWRITE ||
                prot == PAGE_EXECUTE_READ || prot == PAGE_EXECUTE_READWRITE ||
                prot == PAGE_WRITECOPY || prot == PAGE_EXECUTE_WRITECOPY;
            if (readable && scan_end > cur + n) {
                const uint8_t* data = (const uint8_t*)cur;
                const size_t span = (size_t)(scan_end - cur);
                for (size_t i = 0; i + n <= span; i++) {
                    bool hit = true;
                    for (size_t j = 0; j < n; j++) {
                        if (!pat[j].wildcard && data[i + j] != pat[j].value) { hit = false; break; }
                    }
                    if (hit) {
                        out.push_back(cur + i);
                        if (out.size() >= limit) break;
                    }
                }
            }
        }
        if (region_end <= cur) break;
        cur = region_end;
    }
    return true;
}

namespace {
// SEH-protected scan of one contiguous chunk. POD-only locals so __try is legal.
// The target process is running; heap pages can be decommitted concurrently, so a
// read may fault mid-scan. We catch it and keep whatever matches we found.
int ScanChunkSEH(const uint8_t* base, size_t span, const PatternByte* pat,
                 size_t n, size_t limit, uintptr_t* out) {
    size_t count = 0;
    __try {
        for (size_t i = 0; i + n <= span && count < limit; i += 8) {
            bool hit = true;
            for (size_t j = 0; j < n; j++) {
                if (!pat[j].wildcard && base[i + j] != pat[j].value) { hit = false; break; }
            }
            if (hit) out[count++] = (uintptr_t)(base + i);
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        // keep partial results
    }
    return (int)count;
}
} // namespace

bool HammerBridge::ScanHeap(const std::string& pattern, size_t limit,
                            uintptr_t lo, uintptr_t hi,
                            std::vector<uintptr_t>& out) {
    out.clear();
    if (!limit) limit = 64;

    std::vector<PatternByte> pat;
    if (!ParsePattern(pattern, pat)) return false;
    const size_t n = pat.size();

    SYSTEM_INFO si{};
    GetSystemInfo(&si);
    uintptr_t cur = (uintptr_t)si.lpMinimumApplicationAddress;
    const uintptr_t maxaddr = (uintptr_t)si.lpMaximumApplicationAddress;
    const size_t kChunk = 256 * 1024;   // scan in 256 KB chunks so one fault loses little
    const size_t kMaxScan = (size_t)2 * 1024 * 1024 * 1024;  // hard cap on bytes scanned
    size_t scanned = 0;

    while (cur < maxaddr && out.size() < limit && scanned < kMaxScan) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (VirtualQuery((LPCVOID)cur, &mbi, sizeof(mbi)) == 0) break;
        const uintptr_t region = (uintptr_t)mbi.BaseAddress;
        const uintptr_t region_end = region + mbi.RegionSize;

        bool scan_ok = false;
        if (mbi.State == MEM_COMMIT &&
            (mbi.Type == MEM_PRIVATE || mbi.Type == MEM_MAPPED)) {
            const DWORD prot = mbi.Protect & 0xFF;
            if (prot == PAGE_READWRITE || prot == PAGE_WRITECOPY)
                scan_ok = true;
        }
        if (scan_ok) {
            uintptr_t s = region;
            uintptr_t e = region_end;
            if (lo && s < lo) s = lo;
            if (hi && e > hi) e = hi;
            s = (s + 7u) & ~(uintptr_t)7;
            while (s + n <= e && out.size() < limit) {
                size_t span = (size_t)(e - s);
                if (span > kChunk) span = kChunk;
                if (span >= n && IsRangeReadable(s, n)) {
                    std::vector<uintptr_t> tmp(limit - out.size());
                    const int got = ScanChunkSEH((const uint8_t*)s, span, pat.data(), n,
                                                 tmp.size(), tmp.data());
                    for (int k = 0; k < got; k++) out.push_back(tmp[k]);
                }
                s += span;
                scanned += span;
            }
        }
        if (region_end <= cur) break;
        cur = region_end;
    }
    return true;
}

// ---------------------------------------------------------------------------
// generic invocation
// ---------------------------------------------------------------------------
namespace {

// 动态生成 x64 fastcall 调用桩：最多 6 个参数
//   前 4 槽：kind=0 -> RCX/RDX/R8/R9；kind=1/2 -> xmm0..xmm3（movss/movsd 语义，
//   这里直接把 IEEE 位模式经 eax/rax 中转送进 xmm，等价于 movd/movq）
//   第 5/6 槽：一律按 8 字节位模式压栈（Win64 每个栈参数占一个 8 字节槽，float 高位补 0）
uint64_t InvokeStub(uintptr_t fn, const std::vector<FnArg>& args) {
    if (!fn || !IsRangeReadable(fn, 1)) return 0;

    FnArg a[6];
    for (size_t i = 0; i < args.size() && i < 6; i++) a[i] = args[i];

    std::vector<uint8_t> code;
    code.reserve(160);
    auto imm64 = [&](uint64_t v) {
        for (int i = 0; i < 8; i++) code.push_back((uint8_t)(v >> (8 * i)));
    };
    auto imm32 = [&](uint32_t v) {
        for (int i = 0; i < 4; i++) code.push_back((uint8_t)(v >> (8 * i)));
    };

    // 前 4 槽里的整数/指针参数
    code.push_back(0x48); code.push_back(0xB9); imm64(a[0].bits);         // mov rcx, a0
    code.push_back(0x48); code.push_back(0xBA); imm64(a[1].bits);         // mov rdx, a1
    code.push_back(0x49); code.push_back(0xB8); imm64(a[2].bits);         // mov r8,  a2
    code.push_back(0x49); code.push_back(0xB9); imm64(a[3].bits);         // mov r9,  a3
    code.push_back(0x48); code.push_back(0x83); code.push_back(0xEC); code.push_back(0x38); // sub rsp, 38h
    code.push_back(0x48); code.push_back(0xB8); imm64(a[4].bits);         // mov rax, a4
    code.push_back(0x48); code.push_back(0x89); code.push_back(0x44); code.push_back(0x24); code.push_back(0x20); // mov [rsp+20h], rax
    code.push_back(0x48); code.push_back(0xB8); imm64(a[5].bits);         // mov rax, a5
    code.push_back(0x48); code.push_back(0x89); code.push_back(0x44); code.push_back(0x24); code.push_back(0x28); // mov [rsp+28h], rax

    // 前 4 槽里的浮点参数：统一经 eax/rax 中转，避免触碰整数寄存器。
    //   float : mov eax, imm32            B8 id
    //           movd xmmN, eax            66 0F 6E (C0 + N*8)
    //   double: mov rax, imm64            48 B8 id
    //           movq xmmN, rax            66 48 0F 6E (C0 + N*8)
    for (int i = 0; i < 4; i++) {
        if (a[i].kind == 1) {
            code.push_back(0xB8); imm32((uint32_t)a[i].bits);
            code.push_back(0x66); code.push_back(0x0F); code.push_back(0x6E);
            code.push_back((uint8_t)(0xC0 + i * 8));
        } else if (a[i].kind == 2) {
            code.push_back(0x48); code.push_back(0xB8); imm64(a[i].bits);
            code.push_back(0x66); code.push_back(0x48); code.push_back(0x0F); code.push_back(0x6E);
            code.push_back((uint8_t)(0xC0 + i * 8));
        }
    }

    code.push_back(0x48); code.push_back(0xB8); imm64(fn);                // mov rax, fn
    code.push_back(0xFF); code.push_back(0xD0);                          // call rax
    code.push_back(0x48); code.push_back(0x83); code.push_back(0xC4); code.push_back(0x38); // add rsp, 38h
    code.push_back(0xC3);                                                // ret

    void* mem = VirtualAlloc(nullptr, code.size(), MEM_COMMIT | MEM_RESERVE,
                             PAGE_EXECUTE_READWRITE);
    if (!mem) return 0;
    memcpy(mem, code.data(), code.size());
    FlushInstructionCache(GetCurrentProcess(), mem, code.size());

    using StubFn = uint64_t (*)();
    StubFn stub = reinterpret_cast<StubFn>(mem);
    uint64_t result = stub();

    VirtualFree(mem, 0, MEM_RELEASE);
    return result;
}

// --- 主线程派发 -----------------------------------------------------------

// 自检目标：只做无害计算，用于验证派发链路（绝不触碰 Hammer 代码）
uint64_t SelfTestTarget() {
    return 0x43533254434F4445ULL;  // "CS2TCODE"
}

struct MainThreadCall {
    uintptr_t fn = 0;
    std::vector<FnArg> args;
    uint64_t result = 0;
    HANDLE done = nullptr;
    bool faulted = false;
    std::shared_ptr<void> argument_owner;
    bool running = false; // guarded by g_pending_mutex
    ~MainThreadCall() { if (done) CloseHandle(done); }
};

std::mutex g_pending_mutex;
std::shared_ptr<MainThreadCall> g_pending_call;
HMODULE g_bridge_module = nullptr;
thread_local int g_last_dispatch_status = 0;

// Keep SEH separate from the shared_ptr-owning frame (MSVC C2712).
void ExecutePendingCall(MainThreadCall* call) {
    __try {
        call->result = InvokeStub(call->fn, call->args);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        call->faulted = true;
        call->result = 0;
    }
}

LRESULT CALLBACK MainThreadHookProc(int nCode, WPARAM wParam, LPARAM lParam) {
    std::shared_ptr<MainThreadCall> call;
    if (nCode == HC_ACTION) {
        std::lock_guard<std::mutex> lock(g_pending_mutex);
        if (g_pending_call && !g_pending_call->running) {
            call = g_pending_call;
            call->running = true;
        }
    }
    if (call) {
        ExecutePendingCall(call.get());
        // Publish completion and remove the in-flight slot atomically to observers.
        std::lock_guard<std::mutex> lock(g_pending_mutex);
        SetEvent(call->done);
        if (g_pending_call == call) g_pending_call.reset();
    }
    return CallNextHookEx(nullptr, nCode, wParam, lParam);
}

struct FindMainWindowCtx {
    DWORD pid = 0;
    DWORD qt_thread = 0;
    DWORD visible_thread = 0;
    bool qt_ambiguous = false;
    bool visible_ambiguous = false;
};

bool IsQtWindowClass(const wchar_t* name) {
    if (wcsncmp(name, L"Qt", 2) != 0) return false;
    const wchar_t* p = name + 2;
    if (*p < L'0' || *p > L'9') return false;
    while (*p >= L'0' && *p <= L'9') ++p;
    return wcsncmp(p, L"QWindow", 7) == 0;
}

void AddThreadCandidate(DWORD tid, DWORD& candidate, bool& ambiguous) {
    if (candidate && candidate != tid) ambiguous = true;
    else candidate = tid;
}

BOOL CALLBACK FindMainWindowProc(HWND hwnd, LPARAM lp) {
    auto* ctx = reinterpret_cast<FindMainWindowCtx*>(lp);
    DWORD pid = 0;
    const DWORD tid = GetWindowThreadProcessId(hwnd, &pid);
    if (pid != ctx->pid || !tid) return TRUE;
    wchar_t name[256]{};
    if (GetClassNameW(hwnd, name, 256) && IsQtWindowClass(name)) {
        // Hidden/popup Qt windows are useful too; do not depend on z-order.
        AddThreadCandidate(tid, ctx->qt_thread, ctx->qt_ambiguous);
    }
    if (IsWindowVisible(hwnd) && GetWindow(hwnd, GW_OWNER) == nullptr) {
        AddThreadCandidate(tid, ctx->visible_thread, ctx->visible_ambiguous);
    }
    return TRUE;
}

} // namespace

void SetBridgeModuleHandle(HMODULE mod) { g_bridge_module = mod; }

DWORD HammerBridge::GetMainThreadId() {
    FindMainWindowCtx ctx{};
    ctx.pid = GetCurrentProcessId();
    if (!EnumWindows(FindMainWindowProc, reinterpret_cast<LPARAM>(&ctx))) return 0;
    if (ctx.qt_ambiguous) return 0;
    if (ctx.qt_thread) return ctx.qt_thread;
    // Qt present but no supported native Qt window: do not guess another thread.
    if (GetModuleHandleW(L"Qt5Widgets.dll")) return 0;
    // Non-Qt hosts (including the independent test) must have one visible thread.
    return ctx.visible_ambiguous ? 0 : ctx.visible_thread;
}

uint64_t HammerBridge::CallFunction(uintptr_t fn, const std::vector<FnArg>& args) {
    return InvokeStub(fn, args);
}

uint64_t HammerBridge::CallFunctionOnMainThread(uintptr_t fn, const std::vector<FnArg>& args,
                                                DWORD timeout_ms, std::shared_ptr<void> argument_owner) {
    if (!fn || !IsRangeReadable(fn, 1)) return 0;

    const DWORD tid = GetMainThreadId();
    if (!tid) { g_last_dispatch_status = 2; return 0; }
    if (tid == GetCurrentThreadId()) { g_last_dispatch_status = 0; return InvokeStub(fn, args); }

    static std::mutex s_dispatch_mutex;   // 串行化，避免并发派发互相覆盖
    std::lock_guard<std::mutex> guard(s_dispatch_mutex);

    auto call = std::make_shared<MainThreadCall>();
    call->fn = fn;
    call->args = args;
    call->argument_owner = std::move(argument_owner);
    call->done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!call->done) { g_last_dispatch_status = 3; return 0; }

    {
        std::lock_guard<std::mutex> lock(g_pending_mutex);
        // A timed-out callback may still be executing. Never overwrite it.
        if (g_pending_call) { g_last_dispatch_status = 5; return 0; }
        g_pending_call = call;
    }
    HHOOK hook = SetWindowsHookExW(WH_GETMESSAGE, MainThreadHookProc, g_bridge_module, tid);
    if (!hook) {
        std::lock_guard<std::mutex> lock(g_pending_mutex);
        if (g_pending_call == call) g_pending_call.reset();
        g_last_dispatch_status = 3;
        return 0;
    }

    PostThreadMessageW(tid, WM_NULL, 0, 0);
    const DWORD wr = WaitForSingleObject(call->done, timeout_ms);
    int status;
    {
        std::lock_guard<std::mutex> lock(g_pending_mutex);
        // Recheck under the same lock as completion: timeout can race SetEvent.
        if (WaitForSingleObject(call->done, 0) == WAIT_OBJECT_0) {
            status = call->faulted ? 4 : 0;
        } else if (call->running) {
            status = 6; // outcome unknown; callback owns request until completion
        } else {
            if (g_pending_call == call) g_pending_call.reset();
            status = wr == WAIT_TIMEOUT ? 1 : 7; // cancelled before execution
        }
    }
    UnhookWindowsHookEx(hook);
    g_last_dispatch_status = status;
    return status == 0 ? call->result : 0;
}

uint64_t HammerBridge::SelfTestOnMainThread(DWORD timeout_ms) {
    return CallFunctionOnMainThread(reinterpret_cast<uintptr_t>(&SelfTestTarget), {}, timeout_ms);
}

int HammerBridge::LastMainThreadStatus() const { return g_last_dispatch_status; }

uint64_t HammerBridge::CallVirtual(uintptr_t this_ptr, size_t vtable_offset,
                                   const std::vector<FnArg>& args,
                                   bool on_main_thread, DWORD timeout_ms, std::shared_ptr<void> argument_owner) {
    if (!IsRangeReadable(this_ptr, 8)) return 0;
    const uintptr_t vtable = *(uintptr_t*)this_ptr;
    if (!IsRangeReadable(vtable + vtable_offset, 8)) return 0;
    const uintptr_t fn = *(uintptr_t*)(vtable + vtable_offset);

    std::vector<FnArg> full;
    full.reserve(args.size() + 1);
    full.push_back(FnArg(this_ptr));
    for (const auto& v : args) full.push_back(v);
    // 与 call_function 同理：会改文档/UI 的虚函数必须走主线程
    if (on_main_thread) return CallFunctionOnMainThread(fn, full, timeout_ms, std::move(argument_owner));
    return CallFunction(fn, full);
}

// ---------------------------------------------------------------------------
// hammer map docs
// ---------------------------------------------------------------------------
std::vector<uintptr_t> HammerBridge::ListMapDocs() {
    // 新版 hammer.dll（2026-09 更新后）：经 ToolSystem(CHammerApp) 运行时对象链枚举。
    //   app+0x58/+0x60 = CHammerEditorSession* CUtlVector
    //   session+0x138  = 活动 CMapDocSession 包装；CMapDoc 内嵌于 wrapper+0x10
    std::vector<uintptr_t> out;
    if (!hammer_base_ || !hammer_app_instance_) return out;

    const uintptr_t app = (uintptr_t)hammer_app_instance_;
    if (!IsRangeReadable(app + HammerAddr::kAppSessionVecCount, 4)) return out;

    int32_t count = *(int32_t*)(app + HammerAddr::kAppSessionVecCount);
    uintptr_t arr = *(uintptr_t*)(app + HammerAddr::kAppSessionVecMem);
    if (count <= 0 || count > 64 || !arr) return out;
    if (!IsRangeReadable(arr, (size_t)count * 8)) return out;

    const uintptr_t want_vtable = hammer_base_ + HammerAddr::kCMapDocVtableRva;
    for (int32_t i = 0; i < count; i++) {
        uintptr_t session = ((uintptr_t*)arr)[i];
        if (!session || !IsRangeReadable(session + HammerAddr::kSessionActiveWrap, 8)) continue;
        uintptr_t wrapper = *(uintptr_t*)(session + HammerAddr::kSessionActiveWrap);
        if (!wrapper || !IsRangeReadable(wrapper + HammerAddr::kWrapperDocEmbed, 8)) continue;
        uintptr_t doc = wrapper + HammerAddr::kWrapperDocEmbed;
        // vptr 校验，确保确实是 CMapDoc
        if (IsRangeReadable(doc, 8) && *(uintptr_t*)doc == want_vtable) {
            out.push_back(doc);
        }
    }
    return out;
}

} // namespace cs2tool
