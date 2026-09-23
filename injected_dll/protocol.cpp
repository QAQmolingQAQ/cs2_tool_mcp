// protocol.cpp - Simple JSON implementation
#include "protocol.h"
#include <cctype>
#include <cmath>
#include <sstream>
#include <algorithm>

namespace cs2tool
{

    std::string JsonEscape(const std::string &s)
    {
        std::string out;
        out.reserve(s.size() + 2);
        for (char c : s)
        {
            switch (c)
            {
            case '"':
                out += "\\\"";
                break;
            case '\\':
                out += "\\\\";
                break;
            case '\n':
                out += "\\n";
                break;
            case '\r':
                out += "\\r";
                break;
            case '\t':
                out += "\\t";
                break;
            case '\b':
                out += "\\b";
                break;
            case '\f':
                out += "\\f";
                break;
            default:
                if ((unsigned char)c < 0x20)
                {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", (unsigned char)c);
                    out += buf;
                }
                else
                {
                    out += c;
                }
            }
        }
        return out;
    }

    std::string JsonUnescape(const std::string &s)
    {
        std::string out;
        out.reserve(s.size());
        for (size_t i = 0; i < s.size(); i++)
        {
            if (s[i] == '\\' && i + 1 < s.size())
            {
                char n = s[i + 1];
                switch (n)
                {
                case '"':
                    out += '"';
                    i++;
                    break;
                case '\\':
                    out += '\\';
                    i++;
                    break;
                case '/':
                    out += '/';
                    i++;
                    break;
                case 'n':
                    out += '\n';
                    i++;
                    break;
                case 'r':
                    out += '\r';
                    i++;
                    break;
                case 't':
                    out += '\t';
                    i++;
                    break;
                case 'b':
                    out += '\b';
                    i++;
                    break;
                case 'f':
                    out += '\f';
                    i++;
                    break;
                case 'u':
                {
                    i += 4;
                    break;
                }
                default:
                    out += s[i];
                    break;
                }
            }
            else
            {
                out += s[i];
            }
        }
        return out;
    }

    // ---- JsonValue helpers ----
    bool JsonValue::Has(const std::string &key) const
    {
        for (auto &[k, v] : obj)
            if (k == key)
                return true;
        return false;
    }

    const JsonValue *JsonValue::Get(const std::string &key) const
    {
        for (auto &[k, v] : obj)
            if (k == key)
                return &v;
        return nullptr;
    }

    std::string JsonValue::GetString(const std::string &key, const std::string &def) const
    {
        auto *v = Get(key);
        if (v && v->type == Type::String)
            return v->sval;
        return def;
    }

    int64_t JsonValue::GetInt(const std::string &key, int64_t def) const
    {
        auto *v = Get(key);
        if (v && v->type == Type::Number)
            return (int64_t)v->nval;
        return def;
    }

    bool JsonValue::GetBool(const std::string &key, bool def) const
    {
        auto *v = Get(key);
        if (v && v->type == Type::Bool)
            return v->bval;
        return def;
    }

    // ---- JsonParser ----
    void JsonParser::SkipWs()
    {
        while (*p_ && std::isspace((unsigned char)*p_))
            p_++;
    }

    bool JsonParser::ParseString(std::string &out)
    {
        if (*p_ != '"')
            return false;
        p_++;
        out.clear();
        while (*p_ && *p_ != '"')
        {
            if (*p_ == '\\' && p_[1])
            {
                char n = p_[1];
                switch (n)
                {
                case '"':
                    out += '"';
                    p_ += 2;
                    break;
                case '\\':
                    out += '\\';
                    p_ += 2;
                    break;
                case '/':
                    out += '/';
                    p_ += 2;
                    break;
                case 'n':
                    out += '\n';
                    p_ += 2;
                    break;
                case 'r':
                    out += '\r';
                    p_ += 2;
                    break;
                case 't':
                    out += '\t';
                    p_ += 2;
                    break;
                case 'b':
                    out += '\b';
                    p_ += 2;
                    break;
                case 'f':
                    out += '\f';
                    p_ += 2;
                    break;
                case 'u':
                {
                    p_ += 6;
                    out += '?';
                    break;
                }
                default:
                    out += p_[1];
                    p_ += 2;
                    break;
                }
            }
            else
            {
                out += *p_++;
            }
        }
        if (*p_ == '"')
        {
            p_++;
            return true;
        }
        return false;
    }

    bool JsonParser::ParseNumber(double &out)
    {
        char *end = nullptr;
        out = strtod(p_, &end);
        if (end == p_)
            return false;
        p_ = end;
        return true;
    }

    bool JsonParser::ParseObject(JsonValue &out)
    {
        if (*p_ != '{')
            return false;
        p_++;
        out.type = JsonValue::Type::Object;
        out.obj.clear();
        SkipWs();
        if (*p_ == '}')
        {
            p_++;
            return true;
        }
        while (*p_)
        {
            SkipWs();
            std::string key;
            if (!ParseString(key))
                return false;
            SkipWs();
            if (*p_ != ':')
                return false;
            p_++;
            SkipWs();
            JsonValue val;
            if (!ParseValue(val))
                return false;
            out.obj.push_back({key, val});
            SkipWs();
            if (*p_ == ',')
            {
                p_++;
                continue;
            }
            if (*p_ == '}')
            {
                p_++;
                return true;
            }
            return false;
        }
        return false;
    }

    bool JsonParser::ParseArray(JsonValue &out)
    {
        if (*p_ != '[')
            return false;
        p_++;
        out.type = JsonValue::Type::Array;
        out.arr.clear();
        SkipWs();
        if (*p_ == ']')
        {
            p_++;
            return true;
        }
        while (*p_)
        {
            SkipWs();
            JsonValue val;
            if (!ParseValue(val))
                return false;
            out.arr.push_back(std::move(val));
            SkipWs();
            if (*p_ == ',')
            {
                p_++;
                continue;
            }
            if (*p_ == ']')
            {
                p_++;
                return true;
            }
            return false;
        }
        return false;
    }

    bool JsonParser::ParseValue(JsonValue &out)
    {
        SkipWs();
        if (!*p_)
            return false;
        if (*p_ == '"')
        {
            std::string s;
            if (!ParseString(s))
                return false;
            out.type = JsonValue::Type::String;
            out.sval = std::move(s);
            return true;
        }
        if (*p_ == '{')
            return ParseObject(out);
        if (*p_ == '[')
            return ParseArray(out);
        if (strncmp(p_, "true", 4) == 0)
        {
            out.type = JsonValue::Type::Bool;
            out.bval = true;
            p_ += 4;
            return true;
        }
        if (strncmp(p_, "false", 5) == 0)
        {
            out.type = JsonValue::Type::Bool;
            out.bval = false;
            p_ += 5;
            return true;
        }
        if (strncmp(p_, "null", 4) == 0)
        {
            out.type = JsonValue::Type::Null;
            p_ += 4;
            return true;
        }
        if (*p_ == '-' || std::isdigit((unsigned char)*p_))
        {
            double n;
            if (!ParseNumber(n))
                return false;
            out.type = JsonValue::Type::Number;
            out.nval = n;
            return true;
        }
        return false;
    }

    bool JsonParser::Parse(const std::string &input, JsonValue &out)
    {
        JsonParser self;
        self.p_ = input.c_str();
        return self.ParseValue(out);
    }

    // ---- Json generators ----
    std::string JsonMakeString(const std::string &s)
    {
        return "\"" + JsonEscape(s) + "\"";
    }

    std::string JsonMakeInt(int64_t v)
    {
        char buf[32];
        snprintf(buf, sizeof(buf), "%lld", (long long)v);
        return buf;
    }

    std::string JsonMakeBool(bool v)
    {
        return v ? "true" : "false";
    }

    std::string JsonMakeNull() { return "null"; }

    std::string JsonMakeObject(const std::vector<std::pair<std::string, std::string>> &fields)
    {
        std::string out = "{";
        bool first = true;
        for (auto &[k, v] : fields)
        {
            if (!first)
                out += ",";
            first = false;
            out += "\"" + JsonEscape(k) + "\":" + v;
        }
        out += "}";
        return out;
    }

    std::string JsonMakeArray(const std::vector<std::string> &items_json)
    {
        std::string out = "[";
        bool first = true;
        for (auto &item : items_json)
        {
            if (!first)
                out += ",";
            first = false;
            out += item;
        }
        out += "]";
        return out;
    }

} // namespace cs2tool
