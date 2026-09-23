// protocol.h - IPC protocol definitions (no BOM)
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace cs2tool {

// Pipe name
constexpr const wchar_t* kPipeName = L"\\\\.\\pipe\\CS2ToolMCP";

// Max message size
constexpr size_t kMaxMsgSize = 1024 * 1024;

// Request/response header
#pragma pack(push, 1)
struct MsgHeader {
    uint32_t magic;
    uint32_t version;
    uint32_t length;
    uint32_t reserved;
};
#pragma pack(pop)

constexpr uint32_t kMsgMagic = 0x43533254; // "CS2T"
constexpr uint32_t kMsgVersion = 1;

std::string JsonEscape(const std::string& s);
std::string JsonUnescape(const std::string& s);

struct JsonValue {
    enum class Type { Null, Bool, Number, String, Object, Array };
    Type type = Type::Null;
    bool bval = false;
    double nval = 0;
    std::string sval;
    std::vector<std::pair<std::string, JsonValue>> obj;
    std::vector<JsonValue> arr;

    bool Has(const std::string& key) const;
    const JsonValue* Get(const std::string& key) const;
    std::string GetString(const std::string& key, const std::string& def = "") const;
    int64_t GetInt(const std::string& key, int64_t def = 0) const;
    bool GetBool(const std::string& key, bool def = false) const;
};

class JsonParser {
public:
    static bool Parse(const std::string& input, JsonValue& out);
private:
    const char* p_ = nullptr;
    void SkipWs();
    bool ParseValue(JsonValue& out);
    bool ParseString(std::string& out);
    bool ParseNumber(double& out);
    bool ParseObject(JsonValue& out);
    bool ParseArray(JsonValue& out);
};

std::string JsonMakeObject(const std::vector<std::pair<std::string, std::string>>& fields);
std::string JsonMakeString(const std::string& s);
std::string JsonMakeInt(int64_t v);
std::string JsonMakeBool(bool v);
std::string JsonMakeNull();
std::string JsonMakeArray(const std::vector<std::string>& items_json);

} // namespace cs2tool
