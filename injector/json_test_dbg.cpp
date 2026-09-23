#include <windows.h>
#include <string>
#include <iostream>
#include <vector>
#include <utility>
#include <cctype>
#include <cstring>
#include <fstream>
#include <iomanip>

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
        std::cerr << "DEBUG Parse: input=" << input << std::endl;
        std::cerr << "DEBUG Parse: p_=" << (void*)self.p_ << " first_char='" << *self.p_ << "' (0x" << std::hex << (int)(unsigned char)*self.p_ << ")" << std::dec << std::endl;
        return self.ParseValue(out);
    }
private:
    const char* p_ = nullptr;
    void SkipWs() { while (*p_ && (std::isspace((unsigned char)*p_) || *p_==',')) p_++; }
    bool ParseValue(JsonValue& out) {
        std::cerr << "  ParseValue: *p_='" << (*p_ ? *p_ : '?') << "'" << std::endl;
        SkipWs();
        if (!*p_) { std::cerr << "  ParseValue: EOF after SkipWs" << std::endl; return false; }
        std::cerr << "  ParseValue after SkipWs: *p_='" << (*p_ ? *p_ : '?') << "'" << std::endl;
        if (*p_=='"') { std::string s; if(!ParseString(s)) return false; out.type=JsonValue::Type::String; out.sval=std::move(s); return true; }
        if (*p_=='{') return ParseObject(out);
        if (*p_=='[') return ParseArray(out);
        if (strncmp(p_,"true",4)==0) { out.type=JsonValue::Type::Bool; out.bval=true; p_+=4; return true; }
        if (strncmp(p_,"false",5)==0) { out.type=JsonValue::Type::Bool; out.bval=false; p_+=5; return true; }
        if (strncmp(p_,"null",4)==0) { out.type=JsonValue::Type::Null; p_+=4; return true; }
        if (*p_=='-' || std::isdigit((unsigned char)*p_)) { double n; if(!ParseNumber(n)) return false; out.type=JsonValue::Type::Number; out.nval=n; return true; }
        std::cerr << "  ParseValue: unknown char '" << *p_ << "'" << std::endl;
        return false;
    }
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
    std::cerr << "  ParseObject: *p_='" << (*p_?*p_:'?') << "'" << std::endl;
    if (*p_!='{') return false;
    p_++;
    out.type = JsonValue::Type::Object;
    out.obj.clear();
    SkipWs();
    if (*p_=='}') { p_++; return true; }
    while (*p_) {
        SkipWs();
        std::string key;
        if (!ParseString(key)) { std::cerr << "  ParseObject: ParseString(key) failed at *p_='" << (*p_?*p_:'?') << "'" << std::endl; return false; }
        std::cerr << "  ParseObject: key='" << key << "'" << std::endl;
        SkipWs();
        if (*p_!=':') { std::cerr << "  ParseObject: expected ':' at *p_='" << (*p_?*p_:'?') << "'" << std::endl; return false; }
        p_++;
        SkipWs();
        JsonValue val;
        if (!ParseValue(val)) { std::cerr << "  ParseObject: ParseValue failed after key '" << key << "'" << std::endl; return false; }
        out.obj.push_back({key, val});
        SkipWs();
        if (*p_==',') { p_++; continue; }
        if (*p_=='}') { p_++; return true; }
        std::cerr << "  ParseObject: expected ',' or '}' at *p_='" << (*p_?*p_:'?') << "'" << std::endl;
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

int main(int argc, char** argv) {
    std::string test;
    if (argc > 1) {
        test = argv[1];
    } else {
        std::ifstream f("request.json");
        if (f) {
            test.assign((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
        } else {
            test = "{\"id\":1,\"method\":\"ping\"}";
        }
    }
    std::cerr << "=== JSON Parser Debug ===" << std::endl;
    std::cerr << "Input hex:";
    for (char c : test) std::cerr << " " << std::hex << (int)(unsigned char)c;
    std::cerr << std::dec << std::endl;
    std::cerr << "Input: " << test << std::endl;

    JsonValue root;
    bool ok = JsonParser::Parse(test, root);
    std::cerr << "Parse result: " << (ok ? "true" : "false") << std::endl;
    std::cerr << "Has id: " << root.Has("id") << std::endl;
    std::cerr << "Has method: " << root.Has("method") << std::endl;
    if (ok && root.Has("method")) {
        std::cerr << "method = " << root.GetString("method") << std::endl;
    }
    return ok ? 0 : 1;
}
