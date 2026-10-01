#!/usr/bin/env python3
"""定向探针：把地图里的实体（名字/类名/坐标）快速列出来，供 STG 任务核对。

比 `cs2_entity_list` 快的原因：
  * 用 `_walk_elements`（只走场景树，顺带拿到 vtable），不做全元素表扫描；
  * 属性链**每项只读一次 0x28 字节块**，属性名走「驻留串指针 -> 名字」缓存
    （驻留串在整个进程里唯一，指针可复用），把每属性 2~3 次管道往返压到 ~1 次；
  * origin/angles/scales 三个原生成员一次块读。

用法：
  python injector/_stg_probe.py            # 只打印名字里含关键字的实体
  python injector/_stg_probe.py --all      # 打印全部实体（慢一些，输出多）
  python injector/_stg_probe.py --doc 1 --all   # 指定地图文档（cs2_map_list_docs 的 index）
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vm_pipe import _load_server  # noqa: E402

KEYWORDS = ("stg", "hitbox", "danmu", "boss", "move_", "game_ui", "laser", "zd",
            "bullet", "ui", "count", "bg", "background")
WANT = {"classname", "targetname", "model", "origin", "angles", "scales",
        "spawnflags", "speed", "movedir", "movedistance", "target", "parentname",
        "rendercolor", "vscripts", "cs_script"}


def main() -> int:
    s = _load_server()
    base = s._hammer_base()
    ent_vt = base + s.RVA_CMAPENTITY_VTABLE
    doc_sel = sys.argv[sys.argv.index("--doc") + 1] if "--doc" in sys.argv else ""
    world = s._read_int(s._map_doc(doc_sel) + s.CMAPDOC_WORLD_OFFSET, "u64")
    print(f"doc={doc_sel or '0'}  world={world:#x}  CMapEntity vtable={ent_vt:#x}")

    ents = [(el, vt) for el, vt in s._walk_elements(world) if vt == ent_vt]
    print(f"场景内实体数 = {len(ents)}\n")

    name_cache: dict[int, str] = {}
    rows = []
    for el, _vt in ents:
        try:
            raw = s._read_bytes(el + 0xA0, 0x24)          # origin/angles/scales 一次读完
            origin = struct.unpack("<3f", raw[0:12])
            angles = struct.unpack("<3f", raw[12:24])
            scales = struct.unpack("<3f", raw[24:36])
            props = s._entity_class_props(el)
            kv: dict = {}
            for container in (props, el):
                if not container:
                    continue
                attr = s._read_int(container + s.ELEMENT_OFF_ATTR_HEAD, "u64")
                guard = 0
                while attr and guard < 512:
                    buf = s._read_bytes(attr, 0x28)
                    nxt = int.from_bytes(buf[0:8], "little")
                    val = int.from_bytes(buf[8:16], "little")
                    tcode = buf[0x1C] & 0x3F
                    nptr = int.from_bytes(buf[0x20:0x28], "little")
                    nm = name_cache.get(nptr)
                    if nm is None:
                        nm = s._read_string(nptr, 96) if nptr else ""
                        name_cache[nptr] = nm
                    if nm in WANT and nm not in kv:
                        if tcode == 5 and val:
                            cp = s._read_int(val, "u64")
                            kv[nm] = s._read_string(cp, 512) if cp else ""
                        elif tcode in (1, 2, 3, 4, 7, 8):
                            kv[nm] = s._read_int(val, "u32")
                    attr = nxt
                    guard += 1
        except Exception as e:  # noqa: BLE001
            rows.append((el, {}, (0, 0, 0), (0, 0, 0), (1, 1, 1), f"<err {e}>"))
            continue
        rows.append((el, kv, origin, angles, scales, ""))

    show_all = "--all" in sys.argv
    class_filter = None
    if "--class" in sys.argv:
        class_filter = {c.strip().lower() for c in sys.argv[sys.argv.index("--class") + 1].split(",")}
    print(f"{'element':>13} {'classname':<24} {'targetname':<26} origin")
    hit = 0
    for el, kv, origin, angles, scales, err in rows:
        tn = str(kv.get("targetname", ""))
        cn = str(kv.get("classname", ""))
        blob = (tn + "|" + cn).lower()
        if class_filter is not None:
            if cn.lower() not in class_filter:
                continue
        elif not show_all and not any(k in blob for k in KEYWORDS):
            continue
        hit += 1
        print(f"{el:#13x} {cn[:24]:<24} {tn[:26]:<26} "
              f"({origin[0]:.0f}, {origin[1]:.0f}, {origin[2]:.0f})")
        extra = {k: v for k, v in kv.items() if k not in ("classname", "targetname")}
        if extra:
            print(f"{'':13}   {extra}")
        if any(abs(a - b) > 1e-3 for a, b in zip(scales, (1, 1, 1))) or any(angles):
            print(f"{'':13}   angles=({angles[0]:.1f}, {angles[1]:.1f}, {angles[2]:.1f}) "
                  f"scales=({scales[0]:.2f}, {scales[1]:.2f}, {scales[2]:.2f})")
    print(f"\n命中关键字实体 {hit} / 共 {len(rows)}    (--all 可看全部)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
