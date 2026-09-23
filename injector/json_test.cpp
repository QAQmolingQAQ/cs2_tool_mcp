#include <windows.h>
#include <string>
#include <iostream>
#include <vector>
#include <utility>
#include <sstream>
#include <cctype>
#include <cstring>

struct JsonValue {
    enum class Type { Null, Bool, Number, String, Object, Array };
    Type type = Type::Null;
    bool bval = false;
    double nval = 0;
    std::string sval;
    std::vector<std::pair<std::string, JsonValue>> obj;
    std::vector<JsonValue> arr;
    bool Has(const std::string& k) const { for (auto& [kk,v]:obj) if (kk==k) return true; return false; }
    const JsonValue* Get(const std::string& k) const { for (auto& [kk,v]:obj) if (kk==k) return &v; return nullptr; }
    std::string GetString(const std::string& k, const std::string& d="") const { auto* v=Get(k); return v&&v->type==Type::String ? v->sval : d; }
    int64_t GetInt(const std::string& k, int64_t d=0) const { auto* v=Get(k); return v&&v->type==Type::Number ? (int64_t)v->nval : d; }
};

class JsonParser {
public:
    static bool Parse(const std::string& input, JsonValue& out) {
        JsonParser self;
        self.p_ = input.c_str();
        return self.ParseValue(out);
    }
private:
    const char* p_ = nullptr;
    void SkipWs() { while (*p_ && (std::isspace((unsigned char)*p_) || *p_==',')) p_++; }
    bool ParseValue(JsonValue& out);
    bool ParseString(std::string& out);
    bool ParseNumber(double& out) { char* e=nullptr; out=strtod(p_,&e); if(e==p_) return false; p_=e; return true; }
    bool ParseObject(JsonValue& out);
    bool ParseArray(JsonValue& out);
};

bool JsonParser::ParseString(std::string& out) {
    if (*p_ != '"') return false;
    p_++; out.clear();
    while (*p_ && *p_ != '"') {
        if (*p_=='\\' && p_[1]) {
            char n=p_[1];
            switch(n) {
                case '"': out+='"'; p_+=2; break;
                case '\\': out+='\\'; p_+=2; break;
                case 'n': out+='\n'; p_+=2; break;
                case 'r': out+='\r'; p_+=2; break;
                case 't': out+='\t'; p_+=2; break;
                default: out+=p_[1]; p_+=2; break;
            }
        } else { out+=*p_++; }
    }
    if (*p_=='"') { p_++; return true; }
    return false;
}

bool JsonParser::ParseObject(JsonValue& out) {
    if (*p_!='{') return false;
    p_++;
    out.type = JsonValue::Type::Object;
    out.obj.clear();
    SkipWs();
    if (*p_=='}') { p_++; return true; }
    while (*p_) {
        SkipWs();
        std::string key;
        if (!ParseString(key)) return false;
        SkipWs();
        if (*p_!=':') return false;
        p_++;
        SkipWs();
        JsonValue val;
        if (!ParseValue(val)) return false;
        out.obj.push_back({key, val});
        SkipWs();
        if (*p_==',') { p_++; continue; }
        if (*p_=='}') { p_++; return true; }
        return false;
    }
    return false;
}

bool JsonParser::ParseArray(JsonValue& out) {
    if (*p_!='[') return false;
    p_++;
    out.type = JsonValue::Type::Array;
    out.arr.clear();
    SkipWs();
    if (*p_==']') { p_++; return true; }
    while (*p_) {
        SkipWs();
        JsonValue val;
        if (!ParseValue(val)) return false;
        out.arr.push_back(std::move(val));
        SkipWs();
        if (*p_==',') { p_++; continue; }
        if (*p_==']') { p_++; return true; }
        return false;
    }
    return false;
}

bool JsonParser::ParseValue(JsonValue& out) {
    SkipWs();
    if (!*p_) return false;
    if (*p_=='"') { std::string s; if(!ParseString(s)) return false; out.type=JsonValue::Type::String; out.sval=std::move(s); return true; }
    if (*p_=='{') return ParseObject(out);
    if (*p_=='[') return ParseArray(out);
    if (strncmp(p_,"true",4)==0) { out.type=JsonValue::Type::Bool; out.bval=true; p_+=4; return true; }
    if (strncmp(p_,"false",5)==0) { out.type=JsonValue::Type::Bool; out.bval=false; p_+=5; return true; }
    if (strncmp(p_,"null",4)==0) { out.type=JsonValue::Type::Null; p_+=4; return true; }
    if (*p_=='-' || std::isdigit((unsigned char)*p_)) { double n; if(!ParseNumber(n)) return false; out.type=JsonValue::Type::Number; out.nval=n; return true; }
    return false;
}

int main(int argc, char** argv) {
    std::string test = argc > 1 ? argv[1] : "{\"id\":1,\"method\":\"ping\"}";
    std::cout << "Input: " << test << std::endl;
    JsonValue root;
    bool ok = JsonParser::Parse(test, root);
    std::cout << "Parse result: " << (ok ? "true" : "false") << std::endl;
    std::cout << "Has id: " << root.Has("id") << std::endl;
    std::cout << "Has method: " << root.Has("method") << std::endl;
    if (ok && root.Has("method")) {
        std::cout << "method = " << root.GetString("method") << std::endl;
    }
    return 0;
}
