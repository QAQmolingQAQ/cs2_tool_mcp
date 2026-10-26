// ipc_pipe.cpp - Named pipe IPC server implementation
#include "ipc_pipe.h"
#include "hammer_bridge.h"
#include "bridge_version.h"
#include "qt_snapshot.h"
#include <shellapi.h>
#include <vector>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace cs2tool {

namespace {

std::string Hex(uint64_t v) {
    char buf[32];
    snprintf(buf, sizeof(buf), "0x%llx", (unsigned long long)v);
    return buf;
}

std::string FormatFloat(ValueType type, uint64_t bits) {
    char buf[64];
    if (type == ValueType::F32) {
        float f;
        uint32_t u = (uint32_t)bits;
        memcpy(&f, &u, 4);
        snprintf(buf, sizeof(buf), "%.9g", f);
    } else if (type == ValueType::F64) {
        double d;
        memcpy(&d, &bits, 8);
        snprintf(buf, sizeof(buf), "%.17g", d);
    } else {
        return "";
    }
    return buf;
}

// Accepts a numeric address or a string expression like "hammer.dll+0x12E1B50".
bool GetAddressParam(const JsonValue* params, HammerBridge& bridge, uintptr_t& out) {
    if (!params) return false;
    const JsonValue* v = params->Get("address");
    if (!v) v = params->Get("base");
    if (!v) v = params->Get("this");
    if (!v) return false;

    std::string s;
    if (v->type == JsonValue::Type::String) {
        s = v->sval;
    } else if (v->type == JsonValue::Type::Number) {
        char buf[32];
        snprintf(buf, sizeof(buf), "%lld", (long long)v->nval);
        s = buf;
    } else {
        return false;
    }
    return bridge.ResolveAddress(s, out);
}

// 单次 read_memory 上限。响应里是十六进制字符串，实际载荷 = 2 × size + JSON 开销。
constexpr int kMaxReadSize = 8192;

// 十六进制编码：查表代替逐字节 snprintf（read_memory 用，快一个数量级）。
struct HexTable {
    char t[512];
    HexTable() {
        const char* d = "0123456789abcdef";
        for (int i = 0; i < 256; ++i) {
            t[i * 2] = d[i >> 4];
            t[i * 2 + 1] = d[i & 15];
        }
    }
};

std::string ToHex(const uint8_t* data, size_t n) {
    static const HexTable tbl;   // C++11 保证函数内静态初始化线程安全
    std::string out;
    out.resize(n * 2);
    for (size_t i = 0; i < n; ++i) {
        const char* p = tbl.t + (size_t)data[i] * 2;
        out[i * 2] = p[0];
        out[i * 2 + 1] = p[1];
    }
    return out;
}

// 解析 args 数组 -> 原始参数值（call_function / call_virtual 共用）：
//   Number      -> 值本身（整数/指针）
//   "str:文本"  -> 在本进程分配一份 UTF-8 C 字符串并传其指针
//                  （地址记进 str_allocs，调用返回后由 FreeCallArgs 释放）
//   "f:0.01"    -> float32（IEEE 位模式进 xmmN，Win64 ABI）
//   "d:1.5"     -> float64（同上）
//   其它字符串  -> 当「模块地址表达式」解析（"hammer.dll+0x1234" / "0x1234"）
//   ⚠ 每个元素**必须压一个参数**：解析失败压 0。旧版 call_virtual 遇到字符串
//     解析失败会**跳过不压**，导致参数整体左移、被调函数收到错位参数
//     （vfn2144 拿到空类名直接 return，被长期误判成「该虚函数无效」）。
void ParseCallArgs(const JsonValue* arr, HammerBridge& bridge,
                   std::vector<FnArg>& out, std::vector<void*>& str_allocs) {
    if (!arr || arr->type != JsonValue::Type::Array) return;
    for (auto& v : arr->arr) {
        if (v.type == JsonValue::Type::Number) {
            out.push_back(FnArg((uint64_t)v.nval));
        } else if (v.type == JsonValue::Type::String) {
            const std::string& s = v.sval;
            if (s.rfind("str:", 0) == 0) {
                const std::string text = s.substr(4);
                void* mem = VirtualAlloc(nullptr, text.size() + 1,
                                         MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
                if (mem) {
                    memcpy(mem, text.c_str(), text.size() + 1);
                    str_allocs.push_back(mem);
                }
                out.push_back(FnArg((uint64_t)mem));
            } else if (s.rfind("f:", 0) == 0) {
                out.push_back(FnArg::Float(strtof(s.substr(2).c_str(), nullptr)));
            } else if (s.rfind("d:", 0) == 0) {
                out.push_back(FnArg::Double(strtod(s.substr(2).c_str(), nullptr)));
            } else {
                uintptr_t a = 0;
                bridge.ResolveAddress(s, a);   // 失败时 a 保持 0
                out.push_back(FnArg((uint64_t)a));
            }
        } else {
            out.push_back(FnArg());   // bool / null / 数组 / 对象：占位，保持参数个数
        }
    }
}

void FreeCallArgs(std::vector<void*>& str_allocs) {
    for (void* p : str_allocs) VirtualFree(p, 0, MEM_RELEASE);
}

} // namespace

IpcPipeServer& IpcPipeServer::Instance() {
    static IpcPipeServer inst;
    return inst;
}

bool IpcPipeServer::Start() {
    if (running_.load()) return true;
    running_.store(true);
    server_thread_ = std::thread(&IpcPipeServer::ServerThread, this);
    return true;
}

void IpcPipeServer::Stop() {
    running_.store(false);
    if (server_thread_handle_) {
        CancelSynchronousIo(server_thread_handle_);
    }
    // Detach the thread - DllMain can't safely join (loader lock deadlock risk)
    if (server_thread_.joinable()) {
        server_thread_.detach();
    }
}

void IpcPipeServer::ServerThread() {
    // Save thread handle for CancelSynchronousIo during shutdown
    server_thread_handle_ = OpenThread(SYNCHRONIZE | THREAD_QUERY_INFORMATION, FALSE, GetCurrentThreadId());

    // Diagnostic startup must never invoke editor factories or offset-based initialization.
    // initialize is handled only as an explicitly attested native request.
    while (running_.load()) {
        HANDLE hPipe = CreateNamedPipeW(
            kPipeName,
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES,
            0, 0, 0, nullptr
        );

        if (hPipe == INVALID_HANDLE_VALUE) {
            Sleep(1000);
            continue;
        }

        while (running_.load()) {
            if (!ConnectNamedPipe(hPipe, nullptr)) {
                DWORD err = GetLastError();
                if (err == ERROR_PIPE_CONNECTED) {
                    // connected immediately
                } else if (err == ERROR_NO_DATA) {
                    DisconnectNamedPipe(hPipe);
                    continue;
                } else if (err == ERROR_OPERATION_ABORTED) {
                    // CancelSynchronousIo woke us up during shutdown
                    CloseHandle(hPipe);
                    hPipe = INVALID_HANDLE_VALUE;
                    break;
                } else {
                    // Real error - abandon this pipe
                    CloseHandle(hPipe);
                    hPipe = INVALID_HANDLE_VALUE;
                    break;
                }
            }

            if (!running_.load()) {
                DisconnectNamedPipe(hPipe);
                CloseHandle(hPipe);
                hPipe = INVALID_HANDLE_VALUE;
                break;
            }

            // Spawn client thread. The client thread owns this pipe handle
            // and will CloseHandle() when done. We do NOT close it here.
            std::thread client_thread(&IpcPipeServer::ClientThread, this, hPipe);
            client_thread.detach();
            hPipe = INVALID_HANDLE_VALUE;  // so we don't double-close
            break;  // exit inner loop, outer loop creates new pipe instance
        }
    }

    if (server_thread_handle_) {
        CloseHandle(server_thread_handle_);
        server_thread_handle_ = nullptr;
    }
}

void IpcPipeServer::ClientThread(HANDLE hPipe) {
    while (running_.load()) {
        std::string request_json;
        if (!ReadRequest(hPipe, request_json)) {
            break;
        }
        if (request_json.empty()) continue;

        std::string response = HandleRequest(request_json);
        if (!SendResponse(hPipe, response)) {
            break;
        }
    }
    DisconnectNamedPipe(hPipe);
    CloseHandle(hPipe);
}

bool IpcPipeServer::ReadRequest(HANDLE hPipe, std::string& out_json) {
    out_json.clear();

    MsgHeader header;
    DWORD bytes_read = 0;
    if (!ReadFile(hPipe, &header, sizeof(header), &bytes_read, nullptr)) {
        return false;
    }
    if (bytes_read != sizeof(header)) return false;
    if (header.magic != kMsgMagic || header.length > kMaxMsgSize) {
        return false;
    }

    if (header.length > 0) {
        out_json.resize(header.length);
        bytes_read = 0;
        DWORD total = header.length;
        char* dst = out_json.data();
        while (total > 0) {
            if (!ReadFile(hPipe, dst, total, &bytes_read, nullptr)) {
                return false;
            }
            if (bytes_read == 0) return false;
            dst += bytes_read;
            total -= bytes_read;
        }
    }

    return true;
}

bool IpcPipeServer::SendResponse(HANDLE hPipe, const std::string& json_response) {
    MsgHeader header;
    header.magic = kMsgMagic;
    header.version = kMsgVersion;
    header.length = (uint32_t)json_response.size();
    header.reserved = 0;

    DWORD bytes_written = 0;
    if (!WriteFile(hPipe, &header, sizeof(header), &bytes_written, nullptr)) {
        return false;
    }
    if (bytes_written != sizeof(header)) return false;
    // 循环写：(read_memory 之类的) 大响应可能超过管道缓冲区，单次 WriteFile
    // 只写进去一部分 —— 那样响应流会错位，客户端读到的就是垃圾。
    size_t total = 0;
    while (total < json_response.size()) {
        DWORD written = 0;
        if (!WriteFile(hPipe, json_response.data() + total,
                       (DWORD)(json_response.size() - total), &written, nullptr)) {
            return false;
        }
        if (written == 0) return false;
        total += written;
    }
    FlushFileBuffers(hPipe);
    return true;
}

std::string IpcPipeServer::HandleRequest(const std::string& json_request) {
    JsonValue root;
    JsonParser parser;
    if (!parser.Parse(json_request, root)) {
        return JsonMakeObject({
            {"id", root.Has("id") ? JsonMakeInt(root.GetInt("id")) : JsonMakeInt(-1)},
            {"error", JsonMakeString("Invalid JSON")}
        });
    }

    int64_t id = root.GetInt("id", -1);
    std::string method = root.GetString("method");
    const JsonValue* params = root.Get("params");

    std::vector<std::pair<std::string, std::string>> fields;
    fields.push_back({"id", JsonMakeInt(id)});

    auto error = [&](const std::string& msg) {
        fields.push_back({"error", JsonMakeString(msg)});
        return JsonMakeObject(fields);
    };

    auto success = [&](const std::string& result_json) {
        fields.push_back({"result", result_json});
        return JsonMakeObject(fields);
    };

    // Old, already-running MCP clients have no Python version gate. Require
    // per-request attestation from a current client before native operations.
    // This is a compatibility handshake, not a security/authentication boundary.
    const char* diagnostic_methods[] = {
        "ping", "list_tools", "get_status", "list_modules", "get_module",
        "read_memory", "read_qword", "read_value", "read_string", "read_ptr_chain",
        "find_pattern", "scan_heap", "list_interfaces", "module_interfaces", "main_thread_selftest", "qt_widgets_snapshot", "qt_menu_actions", "qt_hammer_outliner"
    };
    bool diagnostic = false;
    for (auto name : diagnostic_methods) if (method == name) diagnostic = true;
    const bool stable_ui = (method == "qt_open_editor" || method == "qt_hammer_open_dialog" || method == "qt_file_dialog_map" || method == "qt_hammer_probe_action" || method == "qt_hammer_outliner_select" || method == "qt_hammer_targetname_probe"); // fixed Qt ABI adapter, no editor RVAs
    if (!diagnostic && !stable_ui) {
        const auto* attestation = params ? params->Get("native_attestation") : nullptr;
        if (!attestation || attestation->GetString("profile").empty() ||
            attestation->GetInt("pid", 0) != GetCurrentProcessId() ||
            attestation->GetInt("bridge_api_version", 0) != kBridgeApiVersion ||
            attestation->GetString("implementation_sha256").size() != 64) {
            return error("native request blocked: current client version attestation required; run cs2_session_selfcheck");
        }
    }

    auto& bridge = HammerBridge::Instance();

    if (method == "ping") {
        std::string addon, launch_map;
        int argc = 0;
        auto argv = CommandLineToArgvW(GetCommandLineW(), &argc);
        if (argv) {
            auto utf8 = [](const wchar_t* value) {
                int size = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
                std::string text(size, '\0');
                if (size > 0) {
                    WideCharToMultiByte(CP_UTF8, 0, value, -1, text.data(), size, nullptr, nullptr);
                    text.pop_back();
                }
                return text;
            };
            for (int i = 1; i + 1 < argc; ++i) {
                if (!_wcsicmp(argv[i], L"-addon")) addon = utf8(argv[i + 1]);
                if (!_wcsicmp(argv[i], L"+map")) launch_map = utf8(argv[i + 1]);
            }
            LocalFree(argv);
        }
        return success(JsonMakeObject({
            {"status", JsonMakeString("ok")},
            {"initialized", JsonMakeBool(bridge.IsInitialized())},
            {"bridge_version", JsonMakeString(kBridgeVersion)},
            {"bridge_api_version", JsonMakeInt(kBridgeApiVersion)},
            {"native_attestation_required", JsonMakeBool(true)},
            {"protocol_version", JsonMakeInt(kMsgVersion)},
            {"pid", JsonMakeInt(GetCurrentProcessId())},
            {"addon", JsonMakeString(addon)},
            {"launch_map", JsonMakeString(launch_map)}
        }));
    }
    if (method == "get_status") {
        return success(bridge.GetStatus());
    }
    if (method == "list_interfaces") {
        auto ifaces = bridge.ListInterfaces();
        std::vector<std::string> items;
        for (auto& n : ifaces) items.push_back(JsonMakeString(n));
        return success(JsonMakeArray(items));
    }
    if (method == "get_interface") {
        if (!params) return error("missing params");
        std::string name = params->GetString("name");
        if (name.empty()) return error("missing 'name'");
        int rc = -1;
        void* iface = bridge.GetInterface(name, &rc);
        return success(JsonMakeObject({
            {"name", JsonMakeString(name)},
            {"return_code", JsonMakeInt(rc)},
            {"pointer", JsonMakeInt((int64_t)iface)}
        }));
    }
    if (method == "read_memory") {
        if (!params) return error("missing params");
        uintptr_t addr = 0;
        if (!GetAddressParam(params, bridge, addr)) return error("invalid 'address'");
        int size = (int)params->GetInt("size", 8);
        if (size <= 0 || size > kMaxReadSize) return error("invalid size");
        std::vector<uint8_t> buf(size);
        if (!bridge.ReadMem(addr, buf.data(), size)) return error("read failed");
        std::string hex = "0x";
        hex += ToHex(buf.data(), buf.size());
        return success(JsonMakeObject({
            {"address", JsonMakeInt((int64_t)addr)},
            {"size", JsonMakeInt(size)},
            {"hex", JsonMakeString(hex)}
        }));
    }
    if (method == "read_qword") {
        if (!params) return error("missing params");
        uintptr_t addr = 0;
        if (!GetAddressParam(params, bridge, addr)) return error("invalid 'address'");
        auto v = bridge.ReadQword(addr);
        char hexbuf[20];
        snprintf(hexbuf, sizeof(hexbuf), "0x%llx", (unsigned long long)v);
        return success(JsonMakeObject({
            {"address", JsonMakeInt((int64_t)addr)},
            {"value", JsonMakeInt((int64_t)v)},
            {"hex", JsonMakeString(hexbuf)}
        }));
    }
    if (method == "list_modules") {
        std::vector<std::string> items;
        for (auto& m : bridge.ListModules()) {
            items.push_back(JsonMakeObject({
                {"name", JsonMakeString(m.name)},
                {"base", JsonMakeInt((int64_t)m.base)},
                {"base_hex", JsonMakeString(Hex(m.base))},
                {"image_base", JsonMakeInt((int64_t)m.image_base)},
                {"size", JsonMakeInt((int64_t)m.size)}
            }));
        }
        return success(JsonMakeArray(items));
    }
    if (method == "get_module") {
        if (!params) return error("missing params");
        std::string name = params->GetString("name");
        if (name.empty()) return error("missing 'name'");
        ModuleDesc m;
        if (!bridge.GetModule(name, m)) return error("module not found: " + name);
        return success(JsonMakeObject({
            {"name", JsonMakeString(m.name)},
            {"base", JsonMakeInt((int64_t)m.base)},
            {"base_hex", JsonMakeString(Hex(m.base))},
            {"image_base", JsonMakeInt((int64_t)m.image_base)},
            {"size", JsonMakeInt((int64_t)m.size)}
        }));
    }
    if (method == "tool_modules") {
        // 四个编辑器模块（hammer / met / modeldoc_editor / pet）各自的 CreateInterface + 工具系统
        std::vector<std::string> items;
        for (const auto& m : bridge.ToolModules(true)) {  // 实时重探（pet.dll 可能注入后才加载）
            items.push_back(JsonMakeObject({
                {"name", JsonMakeString(m.name)},
                {"label", JsonMakeString(m.label)},
                {"iface", JsonMakeString(m.iface_name)},
                {"loaded", JsonMakeBool(m.loaded)},
                {"base", JsonMakeInt((int64_t)m.base)},
                {"base_hex", JsonMakeString(Hex(m.base))},
                {"create_interface", JsonMakeInt((int64_t)(void*)m.create_interface)},
                {"create_interface_hex", JsonMakeString(Hex((uint64_t)(void*)m.create_interface))},
                {"iface_list_head", JsonMakeInt((int64_t)m.iface_list_head)},
                {"iface_list_head_hex", JsonMakeString(Hex(m.iface_list_head))},
                {"bind_head", JsonMakeInt((int64_t)(m.base ? m.base + m.rva_bind_head : 0))},
                {"bind_head_hex", JsonMakeString(Hex(m.base ? m.base + m.rva_bind_head : 0))},
                {"tool_system", JsonMakeInt((int64_t)m.tool_system)},
                {"tool_system_hex", JsonMakeString(Hex((uint64_t)m.tool_system))},
                {"tool_system_class", JsonMakeString(m.tool_system_class)}
            }));
        }
        return success(JsonMakeArray(items));
    }
    if (method == "get_tool_system") {
        if (!params) return error("missing params");
        std::string module = params->GetString("module");
        if (module.empty()) return error("missing 'module'");
        ToolModule m;
        if (!bridge.GetToolModule(module, m)) return error("unknown tool module: " + module);
        return success(JsonMakeObject({
            {"name", JsonMakeString(m.name)},
            {"label", JsonMakeString(m.label)},
            {"iface", JsonMakeString(m.iface_name)},
            {"loaded", JsonMakeBool(m.loaded)},
            {"base", JsonMakeInt((int64_t)m.base)},
            {"base_hex", JsonMakeString(Hex(m.base))},
            {"iface_list_head", JsonMakeInt((int64_t)m.iface_list_head)},
            {"iface_list_head_hex", JsonMakeString(Hex(m.iface_list_head))},
            {"bind_head", JsonMakeInt((int64_t)(m.base ? m.base + m.rva_bind_head : 0))},
            {"bind_head_hex", JsonMakeString(Hex(m.base ? m.base + m.rva_bind_head : 0))},
            {"tool_system", JsonMakeInt((int64_t)m.tool_system)},
            {"tool_system_hex", JsonMakeString(Hex((uint64_t)m.tool_system))},
            {"tool_system_class", JsonMakeString(m.tool_system_class)}
        }));
    }
    if (method == "module_interfaces") {
        // 枚举某模块 CreateInterface 注册表里的全部接口（不调用工厂，纯读链表）
        if (!params) return error("missing params");
        std::string module = params->GetString("module");
        if (module.empty()) return error("missing 'module'");
        ToolModule m;
        if (!bridge.GetInterfaceModule(module, m)) return error("module not loaded or CreateInterface unavailable: " + module);
        if (!m.loaded) return error("module not loaded: " + module);
        std::vector<std::string> items;
        for (const auto& mi : bridge.ListModuleInterfaces(m)) {
            items.push_back(JsonMakeObject({
                {"name", JsonMakeString(mi.name)},
                {"factory", JsonMakeInt((int64_t)mi.factory)},
                {"factory_hex", JsonMakeString(Hex(mi.factory))}
            }));
        }
        return success(JsonMakeArray(items));
    }
    if (method == "module_get_interface") {
        // 向某模块的 CreateInterface 取任意命名接口
        if (!params) return error("missing params");
        std::string module = params->GetString("module");
        std::string name = params->GetString("name");
        if (module.empty()) return error("missing 'module'");
        if (name.empty()) return error("missing 'name'");
        ToolModule m;
        if (!bridge.GetInterfaceModule(module, m)) return error("module not loaded or CreateInterface unavailable: " + module);
        if (!m.loaded) return error("module not loaded: " + module);
        int rc = -1;
        void* ptr = bridge.GetModuleInterface(m, name, &rc);
        return success(JsonMakeObject({
            {"name", JsonMakeString(name)},
            {"return_code", JsonMakeInt(rc)},
            {"pointer", JsonMakeInt((int64_t)ptr)},
            {"pointer_hex", JsonMakeString(Hex((uint64_t)ptr))}
        }));
    }
    if (method == "module_bind_targets") {
        // 枚举某模块的可绑定目标（Key Bindings / 工具热键体系，REVERSE_NOTES §17/§23）
        if (!params) return error("missing params");
        std::string module = params->GetString("module");
        if (module.empty()) return error("missing 'module'");
        bool with_cmds = params->GetBool("include_commands", true);
        ToolModule m;
        if (!bridge.GetToolModule(module, m)) return error("unknown tool module: " + module);
        if (!m.loaded) return error("module not loaded: " + module);
        auto targets = bridge.ListModuleBindTargets(m, with_cmds);
        std::vector<std::string> items;
        int cmd_total = 0;
        for (const auto& t : targets) {
            cmd_total += (int)t.commands.size();
            std::vector<std::string> cmds;
            for (const auto& c : t.commands) cmds.push_back(JsonMakeString(c));
            std::vector<std::pair<std::string, std::string>> fields = {
                {"name", JsonMakeString(t.name)},
                {"class", JsonMakeString(t.cls)},
                {"source_file", JsonMakeString(t.source_file)},
                {"line", JsonMakeInt(t.line)},
                {"command_count", JsonMakeInt((int)t.commands.size())}
            };
            if (with_cmds) fields.push_back({"commands", JsonMakeArray(cmds)});
            items.push_back(JsonMakeObject(fields));
        }
        return success(JsonMakeObject({
            {"module", JsonMakeString(m.label)},
            {"target_count", JsonMakeInt((int)targets.size())},
            {"command_total", JsonMakeInt(cmd_total)},
            {"targets", JsonMakeArray(items)}
        }));
    }
    if (method == "read_value") {
        if (!params) return error("missing params");
        uintptr_t addr = 0;
        if (!GetAddressParam(params, bridge, addr)) return error("invalid 'address'");
        ValueType type = ValueType::U64;
        std::string type_name = params->GetString("type", "u64");
        if (!ParseValueType(type_name, type)) return error("invalid type: " + type_name);
        uint64_t bits = 0;
        if (!bridge.ReadTyped(addr, type, bits)) return error("read failed");
        return success(JsonMakeObject({
            {"address", JsonMakeString(Hex(addr))},
            {"type", JsonMakeString(type_name)},
            {"value", JsonMakeInt((int64_t)bits)},
            {"value_hex", JsonMakeString(Hex(bits))},
            {"value_float", JsonMakeString(FormatFloat(type, bits))}
        }));
    }
    if (method == "write_value") {
        if (!params) return error("missing params");
        uintptr_t addr = 0;
        if (!GetAddressParam(params, bridge, addr)) return error("invalid 'address'");
        ValueType type = ValueType::U64;
        std::string type_name = params->GetString("type", "u64");
        if (!ParseValueType(type_name, type)) return error("invalid type: " + type_name);
        uint64_t bits = (uint64_t)params->GetInt("value");
        if (!bridge.WriteTyped(addr, type, bits)) return error("write failed");
        return success(JsonMakeObject({
            {"address", JsonMakeString(Hex(addr))},
            {"type", JsonMakeString(type_name)},
            {"written", JsonMakeInt((int64_t)bits)}
        }));
    }
    if (method == "alloc_memory") {
        // 在目标进程里分配一块可读写的暂存区（构造传给引擎 API 的临时容器用）
        if (!params) return error("missing params");
        int64_t size = params->GetInt("size", 0);
        if (size <= 0 || size > (1 << 24)) return error("invalid size");
        void* mem = VirtualAlloc(nullptr, (SIZE_T)size,
                                 MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!mem) return error("VirtualAlloc failed");
        return success(JsonMakeObject({
            {"address", JsonMakeString(Hex((uint64_t)mem))},
            {"size", JsonMakeInt(size)}
        }));
    }
    if (method == "free_memory") {
        if (!params) return error("missing params");
        uintptr_t addr = 0;
        if (!GetAddressParam(params, bridge, addr)) return error("invalid 'address'");
        if (addr) VirtualFree((void*)addr, 0, MEM_RELEASE);
        return success(JsonMakeObject({{"freed", JsonMakeString(Hex(addr))}}));
    }
    if (method == "write_memory") {
        // hex 字符串（允许空格与 "0x" 前缀）写入目标地址
        if (!params) return error("missing params");
        uintptr_t addr = 0;
        if (!GetAddressParam(params, bridge, addr)) return error("invalid 'address'");
        const std::string hex = params->GetString("hex");
        std::string clean;
        for (char c : hex) {
            if (isxdigit((unsigned char)c)) clean += c;
        }
        if (clean.empty() || (clean.size() % 2) != 0) return error("invalid 'hex'");
        std::vector<uint8_t> buf;
        buf.reserve(clean.size() / 2);
        for (size_t i = 0; i < clean.size(); i += 2) {
            buf.push_back((uint8_t)strtoul(clean.substr(i, 2).c_str(), nullptr, 16));
        }
        if (!bridge.WriteMem(addr, buf.data(), buf.size())) return error("write failed");
        return success(JsonMakeObject({
            {"address", JsonMakeString(Hex(addr))},
            {"size", JsonMakeInt((int64_t)buf.size())}
        }));
    }
    if (method == "read_string") {
        if (!params) return error("missing params");
        uintptr_t addr = 0;
        if (!GetAddressParam(params, bridge, addr)) return error("invalid 'address'");
        size_t max_len = (size_t)params->GetInt("max_len", 256);
        std::string s;
        if (!bridge.ReadCString(addr, max_len, s)) return error("read failed");
        return success(JsonMakeObject({
            {"address", JsonMakeString(Hex(addr))},
            {"value", JsonMakeString(s)}
        }));
    }
    if (method == "read_ptr_chain") {
        if (!params) return error("missing params");
        uintptr_t addr = 0;
        if (!GetAddressParam(params, bridge, addr)) return error("invalid 'base'");
        std::vector<int64_t> offsets;
        const JsonValue* arr = params->Get("offsets");
        if (arr && arr->type == JsonValue::Type::Array) {
            for (auto& v : arr->arr) {
                if (v.type == JsonValue::Type::Number) offsets.push_back((int64_t)v.nval);
            }
        }
        uintptr_t result = 0;
        if (!bridge.ReadPointerChain(addr, offsets, result)) return error("pointer chain failed");
        std::string value_str;
        bridge.ReadCString(result, 128, value_str);
        return success(JsonMakeObject({
            {"base", JsonMakeString(Hex(addr))},
            {"result", JsonMakeString(Hex(result))},
            {"string_at_result", JsonMakeString(value_str)}
        }));
    }
    if (method == "find_pattern") {
        if (!params) return error("missing params");
        std::string pattern = params->GetString("pattern");
        if (pattern.empty()) return error("missing 'pattern'");
        std::string module = params->GetString("module");
        size_t limit = (size_t)params->GetInt("limit", 20);
        std::vector<uintptr_t> hits;
        if (!bridge.FindPattern(module, pattern, limit, hits)) return error("pattern scan failed");
        std::vector<std::string> items;
        for (auto h : hits) items.push_back(JsonMakeString(Hex(h)));
        return success(JsonMakeObject({
            {"pattern", JsonMakeString(pattern)},
            {"count", JsonMakeInt((int64_t)hits.size())},
            {"matches", JsonMakeArray(items)}
        }));
    }
    if (method == "scan_heap") {
        if (!params) return error("missing params");
        std::string pattern = params->GetString("pattern");
        if (pattern.empty()) return error("missing 'pattern'");
        size_t limit = (size_t)params->GetInt("limit", 64);
        uintptr_t lo = 0, hi = 0;
        const JsonValue* plo = params->Get("start");
        if (plo && plo->type == JsonValue::Type::String) bridge.ResolveAddress(plo->sval, lo);
        const JsonValue* phi = params->Get("end");
        if (phi && phi->type == JsonValue::Type::String) bridge.ResolveAddress(phi->sval, hi);
        std::vector<uintptr_t> hits;
        if (!bridge.ScanHeap(pattern, limit, lo, hi, hits)) return error("heap scan failed");
        std::vector<std::string> items;
        for (auto h : hits) items.push_back(JsonMakeString(Hex(h)));
        return success(JsonMakeObject({
            {"pattern", JsonMakeString(pattern)},
            {"count", JsonMakeInt((int64_t)hits.size())},
            {"matches", JsonMakeArray(items)}
        }));
    }
    if (method == "call_function") {
        if (!params) return error("missing params");
        uintptr_t fn = 0;
        if (!GetAddressParam(params, bridge, fn)) return error("invalid 'address'");
        std::vector<FnArg> args;
        std::vector<void*> str_allocs;   // "str:" 参数的本进程分配，调用后释放
        ParseCallArgs(params->Get("args"), bridge, args, str_allocs);
        auto argument_owner = std::shared_ptr<void>(
            new std::vector<void*>(std::move(str_allocs)), [](void* p) {
                auto* allocations = static_cast<std::vector<void*>*>(p);
                FreeCallArgs(*allocations);
                delete allocations;
            });
        // on_main_thread=true 时在目标进程主线程执行（文档/UI 相关操作必需，
        // 否则函数可能永不返回并让历史留在 busy 状态）
        const bool on_main = params->GetBool("on_main_thread", false);
        const DWORD timeout_ms = (DWORD)params->GetInt("timeout_ms", 5000);
        const uint64_t ret = on_main
            ? bridge.CallFunctionOnMainThread(fn, args, timeout_ms, argument_owner)
            : bridge.CallFunction(fn, args);

        return success(JsonMakeObject({
            {"address", JsonMakeString(Hex(fn))},
            {"on_main_thread", JsonMakeBool(on_main)},
            // 0=成功 1=超时 2=无主线程 3=钩子失败 4=调用中异常（仅 on_main_thread 时有意义）
            {"main_thread_status", JsonMakeInt(bridge.LastMainThreadStatus())},
            {"ret", JsonMakeInt((int64_t)ret)},
            {"ret_hex", JsonMakeString(Hex(ret))}
        }));
    }
    if (method == "qt_file_dialog_map") {
        if (!params) return error("missing params");
        return success(QtFileDialogMap(params->GetString("path"),params->GetBool("confirm",false)));
    }
    if (method == "qt_hammer_outliner") return success(QtHammerOutliner());
    if (method == "qt_hammer_targetname_probe") {
        if(!params)return error("missing params");
        return success(QtHammerTargetnameProbe(params->GetString("expected_root"),params->GetString("selected_row_key"),
            params->GetString("expected_before"),params->GetString("value"),params->GetBool("confirm",false)));
    }
    if (method == "qt_hammer_outliner_select") {
        const auto* path=params?params->Get("row_path"):nullptr;
        if(!path || path->type!=JsonValue::Type::Array || path->arr.empty() || path->arr.size()>8)return error("bounded row_path array required");
        std::vector<int> rows;
        for(const auto& part:path->arr) {
            if(part.type!=JsonValue::Type::Number || part.nval<0 || part.nval>=100000 || part.nval!=static_cast<int>(part.nval))return error("invalid row path index");
            rows.push_back(static_cast<int>(part.nval));
        }
        return success(QtHammerOutlinerSelect(rows,params->GetString("expected_root"),params->GetString("expected_label"),
            params->GetString("expected_row_key"),params->GetBool("confirm",false)));
    }
    if (method == "qt_hammer_probe_action") {
        if (!params) return error("missing params");
        return success(QtHammerProbeAction(params->GetString("action"),params->GetString("expected_title"),params->GetBool("confirm",false)));
    }
    if (method == "qt_menu_actions") {
        if (!params) return error("missing params");
        return success(QtMenuActions(params->GetString("window_object_name")));
    }
    if (method == "qt_hammer_open_dialog" || method == "qt_file_dialog_map") {
        return success(QtHammerOpenDialog(params ? params->GetBool("confirm",false) : false));
    }
    if (method == "qt_open_editor") {
        if (!params) return error("missing params");
        return success(QtOpenEditor(params->GetString("editor"), params->GetBool("confirm", false)));
    }
    if (method == "qt_widgets_snapshot") {
        const int64_t offset = params ? params->GetInt("offset", 0) : 0;
        const int64_t limit = params ? params->GetInt("limit", 128) : 128;
        if (offset < 0 || offset > 20000 || limit < 1 || limit > 128) return error("invalid Qt snapshot bounds");
        return success(QtWidgetsSnapshot(static_cast<int>(offset), static_cast<int>(limit)));
    }
    if (method == "main_thread_selftest") {
        // 不触碰 Hammer 代码：只对 DLL 内部函数做一次主线程调用，验证派发链路
        const DWORD main_tid = HammerBridge::GetMainThreadId();
        const DWORD pipe_tid = GetCurrentThreadId();
        const uint64_t ret = bridge.SelfTestOnMainThread(3000);
        return success(JsonMakeObject({
            {"main_thread_id", JsonMakeInt((int64_t)main_tid)},
            {"pipe_thread_id", JsonMakeInt((int64_t)pipe_tid)},
            {"different_threads", JsonMakeBool(main_tid != 0 && main_tid != pipe_tid)},
            {"main_thread_status", JsonMakeInt(bridge.LastMainThreadStatus())},
            {"ret", JsonMakeInt((int64_t)ret)},
            {"ret_hex", JsonMakeString(Hex(ret))},
            {"expected_ret_hex", JsonMakeString("0x43533254434f4445")}
        }));
    }
    if (method == "call_virtual") {
        if (!params) return error("missing params");
        uintptr_t this_ptr = 0;
        if (!GetAddressParam(params, bridge, this_ptr)) return error("invalid 'this'");
        size_t vtable_offset = (size_t)params->GetInt("vtable_offset", 0);
        // ★ 与 call_function 共用同一套参数解析：支持 "str:文本"（本进程分配后传指针），
        //   且解析失败的字符串压 0 而不是跳过 —— 跳过会让参数错位（见 ParseCallArgs 注释）。
        std::vector<FnArg> args;
        std::vector<void*> str_allocs;
        ParseCallArgs(params->Get("args"), bridge, args, str_allocs);
        auto argument_owner = std::shared_ptr<void>(
            new std::vector<void*>(std::move(str_allocs)), [](void* p) {
                auto* allocations = static_cast<std::vector<void*>*>(p);
                FreeCallArgs(*allocations);
                delete allocations;
            });
        // 与 call_function 一致：文档/UI 相关的虚函数必须走主线程
        const bool on_main = params->GetBool("on_main_thread", false);
        const DWORD timeout_ms = (DWORD)params->GetInt("timeout_ms", 5000);
        uint64_t ret = bridge.CallVirtual(this_ptr, vtable_offset, args, on_main, timeout_ms, argument_owner);

        return success(JsonMakeObject({
            {"this", JsonMakeString(Hex(this_ptr))},
            {"vtable_offset", JsonMakeInt((int64_t)vtable_offset)},
            {"on_main_thread", JsonMakeBool(on_main)},
            {"arg_count", JsonMakeInt((int64_t)args.size())},
            // 0=成功 1=超时 2=无主线程 3=钩子失败 4=调用中异常（仅 on_main_thread 时有意义）
            {"main_thread_status", JsonMakeInt(bridge.LastMainThreadStatus())},
            {"ret", JsonMakeInt((int64_t)ret)},
            {"ret_hex", JsonMakeString(Hex(ret))}
        }));
    }
    if (method == "map_list_docs") {
        auto docs = bridge.ListMapDocs();
        std::vector<std::string> items;
        int index = 0;
        for (auto doc : docs) {
            // CMapDoc + 0x6A0 是地图全路径（CUtlString，+0 即 char*）。
            // 旧代码用 +2640，实测那里是 0（见 REVERSE_NOTES §2.13）。
            std::string name;
            uintptr_t str_ptr = 0;
            if (bridge.ReadTyped(doc + 0x6A0, ValueType::U64, str_ptr) && str_ptr) {
                bridge.ReadCString(str_ptr, 260, name);
            }
            items.push_back(JsonMakeObject({
                {"index", JsonMakeInt(index++)},
                {"address", JsonMakeString(Hex(doc))},
                {"name", JsonMakeString(name)}
            }));
        }
        return success(JsonMakeObject({
            {"count", JsonMakeInt((int64_t)docs.size())},
            {"docs", JsonMakeArray(items)}
        }));
    }
    if (method == "get_hammer_app") {
        return success(JsonMakeObject({
            {"pointer", JsonMakeInt((int64_t)bridge.GetHammerApp())},
            {"tool_system", JsonMakeInt((int64_t)bridge.GetToolSystem())}
        }));
    }
    if (method == "initialize") {
        bool ok = bridge.Initialize();
        return success(JsonMakeObject({
            {"success", JsonMakeBool(ok)},
            {"status", JsonMakeString(ok ? "initialized" : "failed")}
        }));
    }
    if (method == "list_tools") {
        std::vector<std::string> tools = {
            JsonMakeString("ping"),
            JsonMakeString("get_status"),
            JsonMakeString("list_interfaces"),
            JsonMakeString("get_interface"),
            JsonMakeString("read_memory"),
            JsonMakeString("read_qword"),
            JsonMakeString("list_modules"),
            JsonMakeString("get_module"),
            JsonMakeString("tool_modules"),
            JsonMakeString("get_tool_system"),
            JsonMakeString("module_interfaces"),
            JsonMakeString("module_get_interface"),
            JsonMakeString("module_bind_targets"),
            JsonMakeString("read_value"),
            JsonMakeString("write_value"),
            JsonMakeString("write_memory"),
            JsonMakeString("alloc_memory"),
            JsonMakeString("free_memory"),
            JsonMakeString("read_string"),
            JsonMakeString("read_ptr_chain"),
            JsonMakeString("find_pattern"),
            JsonMakeString("scan_heap"),
            JsonMakeString("call_function"),
            JsonMakeString("call_virtual"),
            JsonMakeString("main_thread_selftest"),
            JsonMakeString("qt_widgets_snapshot"),
            JsonMakeString("qt_open_editor"),
            JsonMakeString("qt_menu_actions"),
            JsonMakeString("qt_hammer_open_dialog"),
            JsonMakeString("qt_file_dialog_map"),
            JsonMakeString("map_list_docs"),
            JsonMakeString("get_hammer_app"),
            JsonMakeString("initialize"),
            JsonMakeString("list_tools")
        };
        return success(JsonMakeArray(tools));
    }

    return error("unknown method: " + method);
}

} // namespace cs2tool
