"""从 IDA 反编译结果（JSON 文本）里提取关键片段。"""
import re
import sys

p = sys.argv[1]
kw = sys.argv[2] if len(sys.argv) > 2 else "DmeConnectionData"
span = int(sys.argv[3]) if len(sys.argv) > 3 else 1500

txt = open(p, encoding="utf-8").read()
# 把 JSON 里的转义还原，便于阅读
txt = txt.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")

for m in re.finditer(re.escape(kw), txt):
    k = m.start()
    print("=" * 30, kw, "@", k, "=" * 30)
    print(txt[max(0, k - span):k + span])
    print()

# 顺带把所有字符串常量列出来
strs = sorted(set(re.findall(r'"(a[A-Za-z0-9_]{3,})"', txt)))
print("字符串常量:", strs)
