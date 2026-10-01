"""实体 IO 探测：复用 cs2_mcp_server 的命名管道客户端直接调用其工具函数。

用法：
    python probe_io.py save              # 触发 Hammer Ctrl+S
    python probe_io.py io <entity_hex>   # 读实体 IO
    python probe_io.py attrs <elem_hex>  # 列出元素属性链（名/类型/值）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp_server"))
import cs2_mcp_server as S  # noqa: E402


def dump_attrs(elem: int) -> None:
    a = S._read_int(elem + S.ELEMENT_OFF_ATTR_HEAD, "u64")
    for _ in range(48):
        if not a or a < 0x10000:
            break
        t = S._read_int(a + S.ATTR_OFF_TYPE, "byte") & 0x3F
        np = S._read_int(a + S.ATTR_OFF_NAME, "u64")
        vp = S._read_int(a + S.ATTR_OFF_VALUE, "u64")
        name = S._read_string(np, 64) if np else "?"
        if t == S.DM_ATTR_TYPE_STRING and vp:
            val = S._read_string(S._read_int(vp, "u64"), 96)
        elif t == 2 and vp:
            val = S._read_int(vp, "i32")
        elif t == 33 and vp:
            size = S._read_int(vp, "u32")
            data = S._read_int(vp + 8, "u64")
            cap = S._read_int(vp + 0x10, "u32")
            first = S._read_int(data, "u32") if data else -1
            val = f"AT33 size={size} cap={cap} data={data:#x} first={first}"
        else:
            val = f"<t{t}>"
        print(f"  {name:<24} t={t:<2} attr={a:#x} {val}")
        a = S._read_int(a + S.ATTR_OFF_NEXT, "u64")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "io"
    if cmd == "save":
        print(S.cs2_map_save())
    elif cmd == "io":
        print(S.cs2_entity_get_io(sys.argv[2] if len(sys.argv) > 2 else "0x26426690c00"))
    elif cmd == "setattr":
        print(S.cs2_entity_set_attr(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif cmd == "addio":
        # python probe_io.py addio <entity> <output> <input> [target] [param] [delay] [times]
        ent, out, inp = sys.argv[2], sys.argv[3], sys.argv[4]
        target = sys.argv[5] if len(sys.argv) > 5 else "!self"
        param = sys.argv[6] if len(sys.argv) > 6 else ""
        delay = float(sys.argv[7]) if len(sys.argv) > 7 else 0.0
        times = int(sys.argv[8]) if len(sys.argv) > 8 else -1
        print(S.cs2_entity_add_io(ent, out, inp, target, param, delay, times))
    elif cmd == "rmio":
        print(S.cs2_entity_remove_io(sys.argv[2], int(sys.argv[3])))
    elif cmd == "attrs":
        elem = int(sys.argv[2], 16)
        print(f"element {elem:#x}")
        dump_attrs(elem)
    elif cmd == "props":
        ent = int(sys.argv[2], 16)
        ep = S._dm_attr_element(ent, S.ENTITY_PROPS_ATTR_NAME)
        print(f"entity {ent:#x} entity_properties -> {ep:#x}")
        dump_attrs(ep)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
