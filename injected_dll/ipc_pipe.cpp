// ipc_pipe.cpp - Named pipe IPC server implementation
#include "ipc_pipe.h"
#include "hammer_bridge.h"
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

    HammerBridge::Instance().Initialize();

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
    if (json_response.size() > 0) {
        if (!WriteFile(hPipe, json_response.data(), (DWORD)json_response.size(), &bytes_written, nullptr)) {
            return false;
        }
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

    auto& bridge = HammerBridge::Instance();

    if (method == "ping") {
        return success(JsonMakeObject({
            {"status", JsonMakeString("ok")},
            {"initialized", JsonMakeBool(bridge.IsInitialized())}
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
        if (size <= 0 || size > 1024) return error("invalid size");
        std::vector<uint8_t> buf(size);
        if (!bridge.ReadMem(addr, buf.data(), size)) return error("read failed");
        std::string hex;
        hex.reserve(size * 2 + 2);
        hex += "0x";
        for (auto b : buf) {
            char tb[4];
            snprintf(tb, sizeof(tb), "%02x", b);
            hex += tb;
        }
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
    if (method == "call_function") {
        if (!params) return error("missing params");
        uintptr_t fn = 0;
        if (!GetAddressParam(params, bridge, fn)) return error("invalid 'address'");
        std::vector<uint64_t> args;
        std::vector<void*> str_allocs;   // "str:" 参数的本进程分配，调用后释放
        const JsonValue* arr = params->Get("args");
        if (arr && arr->type == JsonValue::Type::Array) {
            for (auto& v : arr->arr) {
                if (v.type == JsonValue::Type::Number) {
                    args.push_back((uint64_t)v.nval);
                } else if (v.type == JsonValue::Type::String) {
                    const std::string& s = v.sval;
                    if (s.rfind("str:", 0) == 0) {
                        // "str:文本"：在本进程分配一份 UTF-8 C 字符串并传其指针。
                        // 仅在**调用期间**有效（调用返回后释放），适合只读取参数名的 API。
                        const std::string text = s.substr(4);
                        void* mem = VirtualAlloc(nullptr, text.size() + 1,
                                                 MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
                        if (!mem) continue;
                        memcpy(mem, text.c_str(), text.size() + 1);
                        str_allocs.push_back(mem);
                        args.push_back((uint64_t)mem);
                    } else {
                        uintptr_t a = 0;
                        if (bridge.ResolveAddress(s, a)) args.push_back((uint64_t)a);
                    }
                }
            }
        }
        auto free_str_allocs = [&str_allocs]() {
            for (void* p : str_allocs) VirtualFree(p, 0, MEM_RELEASE);
        };
        // on_main_thread=true 时在目标进程主线程执行（文档/UI 相关操作必需，
        // 否则函数可能永不返回并让历史留在 busy 状态）
        const bool on_main = params->GetBool("on_main_thread", false);
        const DWORD timeout_ms = (DWORD)params->GetInt("timeout_ms", 5000);
        const uint64_t ret = on_main
            ? bridge.CallFunctionOnMainThread(fn, args, timeout_ms)
            : bridge.CallFunction(fn, args);
        free_str_allocs();
        return success(JsonMakeObject({
            {"address", JsonMakeString(Hex(fn))},
            {"on_main_thread", JsonMakeBool(on_main)},
            // 0=成功 1=超时 2=无主线程 3=钩子失败 4=调用中异常（仅 on_main_thread 时有意义）
            {"main_thread_status", JsonMakeInt(bridge.LastMainThreadStatus())},
            {"ret", JsonMakeInt((int64_t)ret)},
            {"ret_hex", JsonMakeString(Hex(ret))}
        }));
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
        std::vector<uint64_t> args;
        const JsonValue* arr = params->Get("args");
        if (arr && arr->type == JsonValue::Type::Array) {
            for (auto& v : arr->arr) {
                if (v.type == JsonValue::Type::Number) args.push_back((uint64_t)v.nval);
                else if (v.type == JsonValue::Type::String) {
                    uintptr_t a = 0;
                    if (bridge.ResolveAddress(v.sval, a)) args.push_back((uint64_t)a);
                }
            }
        }
        // 与 call_function 一致：文档/UI 相关的虚函数必须走主线程
        const bool on_main = params->GetBool("on_main_thread", false);
        const DWORD timeout_ms = (DWORD)params->GetInt("timeout_ms", 5000);
        uint64_t ret = bridge.CallVirtual(this_ptr, vtable_offset, args, on_main, timeout_ms);
        return success(JsonMakeObject({
            {"this", JsonMakeString(Hex(this_ptr))},
            {"vtable_offset", JsonMakeInt((int64_t)vtable_offset)},
            {"on_main_thread", JsonMakeBool(on_main)},
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
            JsonMakeString("read_value"),
            JsonMakeString("write_value"),
            JsonMakeString("write_memory"),
            JsonMakeString("alloc_memory"),
            JsonMakeString("free_memory"),
            JsonMakeString("read_string"),
            JsonMakeString("read_ptr_chain"),
            JsonMakeString("find_pattern"),
            JsonMakeString("call_function"),
            JsonMakeString("call_virtual"),
            JsonMakeString("main_thread_selftest"),
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
