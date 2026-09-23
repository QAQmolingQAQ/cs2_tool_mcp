"""解析 PE 导出表，按关键字查找导出函数（用于定位 Qt5 的 C++ 符号 RVA）。

用法:
    python qt_exports.py <dll 路径> [关键字 ...]

说明:
    Qt5 的 DLL 以 mangled 名导出全部 public 符号，所以可以直接用导出表拿到
    QApplication::allWidgets / QAbstractButton::click 这类函数的 RVA。
    注意要跳过 forward export（其 RVA 落在导出目录内部，指向的是 "DLL.func" 字符串）。
"""
import struct
import sys


def parse_exports(path):
    """返回 [(rva, name)]，已剔除 forward export。"""
    data = open(path, "rb").read()
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe_off:pe_off + 4] == b"PE\0\0", "不是有效的 PE 文件"

    coff = pe_off + 4
    nsec = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    is64 = struct.unpack_from("<H", data, opt)[0] == 0x20B

    dd = opt + (112 if is64 else 96)
    exp_rva, exp_size = struct.unpack_from("<II", data, dd)

    secs = []
    sec_off = opt + opt_size
    for i in range(nsec):
        o = sec_off + i * 40
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, o + 8)
        secs.append((vaddr, max(vsize, rsize), raddr))

    def rva2off(rva):
        for vaddr, vsize, raddr in secs:
            if vaddr <= rva < vaddr + vsize:
                return raddr + (rva - vaddr)
        return None

    eo = rva2off(exp_rva)
    nname = struct.unpack_from("<I", data, eo + 24)[0]
    afun, aname, aord = struct.unpack_from("<III", data, eo + 28)
    fo, no, oo = rva2off(afun), rva2off(aname), rva2off(aord)

    out = []
    for i in range(nname):
        off = rva2off(struct.unpack_from("<I", data, no + i * 4)[0])
        nm = data[off:data.index(b"\0", off)].decode("latin1")
        ordi = struct.unpack_from("<H", data, oo + i * 2)[0]
        frva = struct.unpack_from("<I", data, fo + ordi * 4)[0]
        if exp_rva <= frva < exp_rva + exp_size:
            continue  # forward export，跳过
        out.append((frva, nm))
    return out


if __name__ == "__main__":
    path, keys = sys.argv[1], sys.argv[2:]
    exps = parse_exports(path)
    print(f"{path}\n  非转发导出 {len(exps)} 个")
    hits = [(r, n) for r, n in exps if not keys or any(k in n for k in keys)]
    for rva, nm in hits:
        print(f"  0x{rva:X}  {nm}")
    print(f"  命中 {len(hits)} 个")
