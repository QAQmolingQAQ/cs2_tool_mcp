// hammer_bridge.cpp - Hammer.dll interface bridge implementation
#include "hammer_bridge.h"
#include <psapi.h>
#include <tlhelp32.h>
#include <algorithm>
#include <cstring>
#include <mutex>

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
    constexpr uintptr_t kCreateInterfaceRva = 0x13FFCB0;
    constexpr uintptr_t kInterfaceListHeadRva = 0x2733FB0;
    constexpr uintptr_t kToolSystemFactoryRva = 0x115270;
    constexpr uintptr_t kToolSystemNameRva = 0x1CB1C48;

    // 2026-09 新版 hammer.dll（见 REVERSE_NOTES.md §3）：
    // 旧全局文档表 (0x2355020/0x2355028) 已失效，改为运行时对象链枚举：
    //   CHammerApp+0x58 / +0x60 = CHammerEditorSession* 的 CUtlVector
    //   session+0x138                = 当前活动 CMapDocSession*
    //   CMapDoc 内嵌在 session 包装里：doc = wrapper + 0x10
    constexpr uintptr_t kAppSessionVecCount = 0x58;
    constexpr uintptr_t kAppSessionVecMem   = 0x60;
    constexpr uintptr_t kSessionActiveWrap  = 0x138;
    constexpr uintptr_t kWrapperDocEmbed    = 0x10;
    constexpr uintptr_t kCMapDocVtableRva   = 0x1764188;
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

    if (!hammer_module_ || !hammer_base_) {
        return false;
    }

    // Find CreateInterface export
    create_interface_ = (CreateInterfaceFn)GetProcAddress(hammer_module_, "CreateInterface");
    if (!create_interface_) {
        create_interface_ = (CreateInterfaceFn)(hammer_base_ + HammerAddr::kCreateInterfaceRva);
    }
    if (!create_interface_) {
        return false;
    }

    list_head_rva_ = HammerAddr::kInterfaceListHeadRva;

    // Try get ToolSystem2_001
    int rc = -1;
    hammer_app_instance_ = GetInterface("ToolSystem2_001", &rc);

    initialized_ = true;
    return true;
}

void HammerBridge::Shutdown() {
    hammer_app_instance_ = nullptr;
    create_interface_ = nullptr;
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
};

MainThreadCall* g_pending_call = nullptr;   // 同一时刻只允许一个在途
HHOOK g_main_thread_hook = nullptr;
HMODULE g_bridge_module = nullptr;
int g_last_dispatch_status = 0;            // 见 LastMainThreadStatus 注释

// 该过程会在**目标主线程**上下文中被调用（GetMessage/PeekMessage 取得消息后）
LRESULT CALLBACK MainThreadHookProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode == HC_ACTION && g_pending_call) {
        MainThreadCall* call = g_pending_call;
        g_pending_call = nullptr;           // 只执行一次
        // 用 SEH 兜住目标函数可能触发的异常，避免把宿主进程一起带走
        __try {
            call->result = InvokeStub(call->fn, call->args);
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            call->faulted = true;
            call->result = 0;
        }
        if (call->done) SetEvent(call->done);
    }
    return CallNextHookEx(g_main_thread_hook, nCode, wParam, lParam);
}

struct FindMainWindowCtx {
    DWORD pid = 0;
    DWORD thread_id = 0;
};

BOOL CALLBACK FindMainWindowProc(HWND hwnd, LPARAM lp) {
    auto* ctx = reinterpret_cast<FindMainWindowCtx*>(lp);
    DWORD pid = 0;
    const DWORD tid = GetWindowThreadProcessId(hwnd, &pid);
    if (pid == ctx->pid && IsWindowVisible(hwnd) && GetWindow(hwnd, GW_OWNER) == nullptr) {
        ctx->thread_id = tid;
        return FALSE;
    }
    return TRUE;
}

} // namespace

void SetBridgeModuleHandle(HMODULE mod) { g_bridge_module = mod; }

DWORD HammerBridge::GetMainThreadId() {
    FindMainWindowCtx ctx{GetCurrentProcessId(), 0};
    EnumWindows(FindMainWindowProc, reinterpret_cast<LPARAM>(&ctx));
    if (ctx.thread_id) return ctx.thread_id;

    // 退化方案：取进程内最早创建的线程
    const HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    THREADENTRY32 te{};
    te.dwSize = sizeof(te);
    DWORD first = 0;
    if (Thread32First(snap, &te)) {
        do {
            if (te.th32OwnerProcessID == GetCurrentProcessId()) {
                first = te.th32ThreadID;
                break;
            }
        } while (Thread32Next(snap, &te));
    }
    CloseHandle(snap);
    return first;
}

uint64_t HammerBridge::CallFunction(uintptr_t fn, const std::vector<FnArg>& args) {
    return InvokeStub(fn, args);
}

uint64_t HammerBridge::CallFunctionOnMainThread(uintptr_t fn, const std::vector<FnArg>& args,
                                                DWORD timeout_ms) {
    if (!fn || !IsRangeReadable(fn, 1)) return 0;

    const DWORD tid = GetMainThreadId();
    if (!tid) { g_last_dispatch_status = 2; return 0; }
    if (tid == GetCurrentThreadId()) { g_last_dispatch_status = 0; return InvokeStub(fn, args); }

    static std::mutex s_dispatch_mutex;   // 串行化，避免并发派发互相覆盖
    std::lock_guard<std::mutex> guard(s_dispatch_mutex);

    MainThreadCall call;
    call.fn = fn;
    call.args = args;
    call.done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!call.done) { g_last_dispatch_status = 3; return 0; }

    g_pending_call = &call;
    g_main_thread_hook = SetWindowsHookExW(WH_GETMESSAGE, MainThreadHookProc, g_bridge_module, tid);
    if (!g_main_thread_hook) {
        g_pending_call = nullptr;
        CloseHandle(call.done);
        g_last_dispatch_status = 3;
        return 0;
    }

    PostThreadMessageW(tid, WM_NULL, 0, 0);   // 踢一下目标线程的消息循环

    const DWORD wr = WaitForSingleObject(call.done, timeout_ms);

    g_pending_call = nullptr;
    UnhookWindowsHookEx(g_main_thread_hook);
    g_main_thread_hook = nullptr;
    CloseHandle(call.done);

    if (wr != WAIT_OBJECT_0) { g_last_dispatch_status = 1; return 0; }
    g_last_dispatch_status = call.faulted ? 4 : 0;
    return call.result;
}

uint64_t HammerBridge::SelfTestOnMainThread(DWORD timeout_ms) {
    return CallFunctionOnMainThread(reinterpret_cast<uintptr_t>(&SelfTestTarget), {}, timeout_ms);
}

int HammerBridge::LastMainThreadStatus() const { return g_last_dispatch_status; }

uint64_t HammerBridge::CallVirtual(uintptr_t this_ptr, size_t vtable_offset,
                                   const std::vector<FnArg>& args,
                                   bool on_main_thread, DWORD timeout_ms) {
    if (!IsRangeReadable(this_ptr, 8)) return 0;
    const uintptr_t vtable = *(uintptr_t*)this_ptr;
    if (!IsRangeReadable(vtable + vtable_offset, 8)) return 0;
    const uintptr_t fn = *(uintptr_t*)(vtable + vtable_offset);

    std::vector<FnArg> full;
    full.reserve(args.size() + 1);
    full.push_back(FnArg(this_ptr));
    for (const auto& v : args) full.push_back(v);
    // 与 call_function 同理：会改文档/UI 的虚函数必须走主线程
    if (on_main_thread) return CallFunctionOnMainThread(fn, full, timeout_ms);
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
