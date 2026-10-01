#!/usr/bin/env python3
"""静态核对 stg.js 里用到的 API 名字是否都在 point_script.d.ts 里声明过。

只查名字（不查签名），用来防止拼错方法名 / 用了 d.ts 之外的东西。
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive"
    r"\content\csgo_addons\ze_surf_nannoimi\maps\scripts")

JS_BUILTINS = {
    # Object / Array / Math / String 常见方法（非 CS2 API）
    "push", "pop", "splice", "slice", "includes", "indexOf", "join", "map", "filter",
    "forEach", "find", "concat", "split", "replace", "toFixed", "toString", "keys",
    "values", "entries", "sort", "reverse", "shift", "unshift", "at", "trim",
    "sin", "cos", "tan", "atan2", "sqrt", "abs", "min", "max", "floor", "ceil",
    "round", "random", "pow", "log", "isValid",
}


def main() -> int:
    js = (SCRIPTS / "stg.js").read_text(encoding="utf-8")
    dts = (SCRIPTS / "point_script.d.ts").read_text(encoding="utf-8")

    declared = set(re.findall(r"^\s*([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\(", dts, re.M))
    declared |= set(re.findall(r"^\s*([A-Za-z_]\w*)\s*:", dts, re.M))          # 枚举/属性
    declared |= set(re.findall(r"export (?:class|enum|const|type|interface) (\w+)", dts))
    declared |= {"x", "y", "z", "pitch", "yaw", "roll", "r", "g", "b", "a"}

    used = {}
    for m in re.finditer(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(", js):
        used.setdefault(m.group(2), set()).add(m.group(1))

    unknown = {k: v for k, v in used.items() if k not in declared and k not in JS_BUILTINS}
    print(f"d.ts 声明名 {len(declared)} 个；stg.js 用到 {len(used)} 个方法名")
    if unknown:
        print("\n⚠ 未在 d.ts 中找到的方法名：")
        for k, v in sorted(unknown.items()):
            print(f"    .{k}()   <- 调用者 {sorted(v)}")
    else:
        print("\n✅ stg.js 用到的所有 .方法() 都能在 point_script.d.ts 里找到（或属于 JS 内置）")

    # 再核对导入的东西
    print("\nimport 检查：", re.findall(r'import \{([^}]*)\} from "([^"]+)"', js))
    for name in re.findall(r'import \{([^}]*)\}', js)[0].split(","):
        n = name.strip()
        print(f"   {n}: {'✔ 已导出' if f'export const {n}' in dts or f'export enum {n}' in dts or f'export class {n}' in dts else '✘ 未导出'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
