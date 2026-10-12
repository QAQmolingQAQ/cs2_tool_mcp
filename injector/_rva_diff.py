r"""hammer.dll 换版体检 + RVA 自动重定位。

背景：Steam 每次更新 `hammer.dll` 都可能把代码整体挪位，`cs2_mcp_server.py` 里
60 条硬编码 `RVA_*` 就全废。本项目 `ida_db\` 里留着**上一版的 dll 副本**，于是可以
离线干两件事：

  1) 同 RVA 字节比对 —— 只能说明「没动」，对含绝对指针的数据段（虚表/全局）没意义；
  2) **拿旧版某 RVA 处的字节片段去新版里搜** —— 这是真正的判据：
     · 唯一命中 => 函数没被改过、只是挪了位置，直接算出新 RVA（自动重定位）；
     · 搜不到   => 函数本体被改过（或者那段含指针），必须重新逆向。

用法：
  python injector/_rva_diff.py                 # 按默认路径跑
  python injector/_rva_diff.py <旧.dll> <新.dll> [片段长度]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# ⚠ RVA_SERVER 必须指向**与参考 DLL 同一版本**的 RVA 表：换版时先在 git 里把旧表
#   另存一份再指过来，否则会在错误偏移上取字节（工具不会报错，只会全错）。
SERVER = Path(os.environ.get("RVA_SERVER") or (REPO / "mcp_server" / "hammer_mcp" / "offsets.py"))
GAME_DLL = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive"
                r"\game\bin\win64\tools\hammer.dll")
OLD_DLL = REPO / "ida_db" / "hammer_new.dll"


def md5(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


class Pe:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = path.read_bytes()
        d = self.data
        e_lfanew = struct.unpack_from("<I", d, 0x3C)[0]
        if d[e_lfanew:e_lfanew + 4] != b"PE\0\0":
            raise ValueError("不是 PE 文件")
        coff = e_lfanew + 4
        nsec = struct.unpack_from("<H", d, coff + 2)[0]
        size_opt = struct.unpack_from("<H", d, coff + 16)[0]
        opt = coff + 20
        self.image_base = struct.unpack_from("<Q", d, opt + 24)[0]
        self.sections: list[tuple[str, int, int, int, int]] = []
        sh = opt + size_opt
        for i in range(nsec):
            b = sh + i * 40
            name = d[b:b + 8].rstrip(b"\0").decode("latin1")
            vsize, va, rawsize, rawptr = struct.unpack_from("<4I", d, b + 8)
            # 存 (名字, VA, 虚拟大小, 文件里真实有的字节数, 文件偏移)
            self.sections.append((name, va, vsize, rawsize, rawptr))

    def off(self, rva: int) -> int | None:
        """RVA -> 文件偏移。只映射**文件里真的有数据**的那一段：
        .data 的虚拟大小远大于文件大小（尾部是载入时清零的），映射到那儿读出来全是垃圾。"""
        for _n, va, _vsize, rawsize, ptr in self.sections:
            if va <= rva < va + rawsize:
                return rva - va + ptr
        return None

    def at(self, rva: int, n: int) -> bytes | None:
        o = self.off(rva)
        if o is None or o + n > len(self.data):
            return None
        return self.data[o:o + n]

    def rva_of_off(self, off: int) -> int | None:
        for _n, va, _vsize, rawsize, ptr in self.sections:
            if ptr and ptr <= off < ptr + rawsize:
                return off - ptr + va
        return None

    def text(self) -> tuple[int, int, int]:
        """(.text 的 VA, 大小, 文件偏移)。"""
        for n, va, _vs, rawsize, ptr in self.sections:
            if n == ".text":
                return va, rawsize, ptr
        raise ValueError("没有 .text")

    def find_all(self, needle: bytes, limit: int = 8) -> list[int]:
        out, start = [], 0
        while len(out) < limit:
            i = self.data.find(needle, start)
            if i < 0:
                break
            out.append(i)
            start = i + 1
        return out


def parse_rvas() -> list[tuple[str, int]]:
    """两侧硬编码的 RVA：server 的 `RVA_*` + DLL 里 hammer_bridge.cpp 的 `kXxxRva`。"""
    out: list[tuple[str, int]] = []
    txt = SERVER.read_text(encoding="utf-8", errors="replace")
    # ⚠ RVA_QT_* 存的是 **Qt5Widgets.dll / Qt5Core.dll** 的偏移（server 里每条都有
    #   `@ Qt5Widgets` / `@ Qt5Core` 注释），跟 hammer.dll 无关，绝不能拿 hammer.dll
    #   的字节去差分它们。踩过一次：靠巧合把 QMainWindow::menuBar() 从 0x135220
    #   "迁"到 0x135260，Hammer 一开图就在 Qt5Widgets+0x135262 闪退。
    raw = [(m.group(1), int(m.group(2), 16))
           for m in re.finditer(r"^(RVA_[A-Z0-9_]+)\s*=\s*(0x[0-9A-Fa-f]+)\b", txt, re.M)]
    out += [(n, v) for n, v in raw if not n.startswith("RVA_QT_")]
    bridge = Path(os.environ.get("RVA_BRIDGE") or (REPO / "injected_dll" / "hammer_bridge.cpp"))
    if bridge.exists():
        bt = bridge.read_text(encoding="utf-8", errors="replace")
        out += [(m.group(1), int(m.group(2), 16))
                for m in re.finditer(r"^\s*constexpr\s+\w+\s+(k[A-Za-z0-9_]*Rva)\s*=\s*(0x[0-9A-Fa-f]+)",
                                     bt, re.M)]
    return out


def entry_check(pe: Pe, rva: int, look: int = 16) -> tuple[int, int]:
    """函数入口的两个旁证：16 字节对齐情况 + 入口前有多少 0xCC/0x90 填充。"""
    align = rva % 16
    o = pe.off(rva)
    if o is None:
        return align, -1
    pad = 0
    for i in range(1, look + 1):
        if o - i < 0 or pe.data[o - i] not in (0xCC, 0x90):
            break
        pad += 1
    return align, pad


# --------------------------------------------------------------------------- #
# 数据全局：文件里根本没有可比的字节（在 .data 尾部载入时清零，或者存的就是
# 运行时才填的指针），所以「字节片段」和「滑窗」都救不了。唯一办法是
# **看谁在引用它**：在旧版 .text 里找出 RIP 相对引用该地址的指令，把那条指令
# 附近的字节（承载着「引用」这件事）拿到新版里唯一定位，再解出新版里的目标。
# --------------------------------------------------------------------------- #
GLOBALS = [
    ("RVA_CDATAMODEL_GLOBAL",     0x24B7C80),
    ("RVA_CDATAMODEL_PTR_GLOBAL", 0x21B2B68),
    ("RVA_MAP_HISTORY_GATE",      0x221A418),
    ("RVA_BIND_TARGET_LIST",      0x272D898),
    ("RVA_CHAMMERAPP",            0x677AE50),
    ("RVA_CMAPENTITY_FACTORY",    0x21DB400),
]

# `[REX?][opcode][modrm]`，modrm 的 mod=00 rm=101 就是 RIP 相对（reg 字段任意）
# => modrm ∈ {05,0D,15,1D,25,2D,35,3D}；后面跟 4 字节 disp32。
# ⚠ REX 前缀**可选** —— 像 `80 3D <disp32> <imm8>`（cmp byte ptr [rip+d], imm）这种
#   比较指令根本没有 REX，只认 0x48/0x4C 会整片漏掉（全局开关就是被这么漏掉的）。
XREF_RE = re.compile(
    rb"([\x40-\x4f]?)"
    rb"([\x8b\x8d\x89\x3b\x39\x01\x03\x0b\x0c\x85\x2b\x29\x31\x33"
    rb"\xc6\xc7\x88\x8a\x38\x3a\x84\x86\xf6\xf7\xa2\xa3\xd0\xd1\xd3\x18\x08\x80\x83])"
    rb"([\x05\x0d\x15\x1d\x25\x2d\x35\x3d])([\s\S]{4})", re.S)

# 已经确认的代码位移（`_rva_diff.py` 的 ② 段统计出来的）。
# 引用指令自身所在函数若变了，全局搜不到，就按这些 Δ 平移过去再比对。
CAND_DELTAS = (0x0, 0x340, 0x610, 0x380, 0x3A0, 0x360, 0xE0, 0xF0, -0x210, -0x1C0, 0x60, 0x140)

# 两字节 opcode 的第二遍：`0F B6/B7/BE/BF ...`（movzx/movsx 从内存取窄整数）
XREF_0F_RE = re.compile(
    rb"([\x40-\x4f]?)\x0f([\xb6\xb7\xbe\xbf\xb1\xb0\x10\x11\x6f\x7f\x28\x29\x94\x95\x4f\x4e])"
    rb"([\x05\x0d\x15\x1d\x25\x2d\x35\x3d])([\s\S]{4})", re.S)


def xref_sites(pe: Pe, target_rva: int) -> list[tuple[int, int, int]]:
    """列出 .text 里所有「RIP 相对指向 target_rva」的指令。

    返回 [(指令 RVA, 指令内 disp 的偏移, 指令总长)]。跑两遍：
      · 单字节 opcode（8B/8D/89/C6/C7/80/83 ...）
      · 两字节 opcode（0F B6/B7/BE/BF：movzx/movsx 读一个字节/字 —— 读「开关」最常见）
    """
    va, size, ptr = pe.text()
    out = []
    for rx, extra in ((XREF_RE, 0), (XREF_0F_RE, 1)):
        for m in rx.finditer(pe.data, ptr, ptr + size):
            i = m.start()
            pre = len(m.group(1))
            disp_off_in_insn = pre + 2 + extra
            insn_len = pre + 2 + extra + 4
            insn_rva = va + (i - ptr)
            disp = struct.unpack_from("<i", pe.data, i + disp_off_in_insn)[0]
            if insn_rva + insn_len + disp == target_rva:
                out.append((insn_rva, disp_off_in_insn, insn_len))
    return out


def find_wildcard(pe: Pe, snip: bytes, skip_off: int, skip_len: int = 4,
                  limit: int = 8) -> list[int]:
    """在整份文件里找 `snip`，但把 [skip_off, skip_off+skip_len) 这段当通配符。

    为什么要挖掉这 4 字节：引用全局的那条指令里嵌的正是 RIP 相对 disp —— 目标一挪，
    disp 就跟着变，整段字节就再也匹配不上了。挖掉它，指令的其余部分仍是唯一指纹。
    """
    pat = (re.escape(snip[:skip_off]) + rb"[\s\S]{%d}" % skip_len
           + re.escape(snip[skip_off + skip_len:]))
    rx = re.compile(pat, re.S)
    out = []
    for m in rx.finditer(pe.data):
        out.append(m.start())
        if len(out) >= limit:
            break
    return out


def relocate_via_xref(pe_old: Pe, pe_new: Pe, target_rva: int, wins=(48, 64, 32)):
    """返回 (新地址, 参考指令旧 RVA, 参考指令新 RVA, 诊断)；失败时新地址为 None。"""
    diag: list[str] = []
    sites = xref_sites(pe_old, target_rva)
    for site, doff, ilen in sites:
        for w in wins:
            snip = pe_old.at(site, w)
            if not snip:
                continue
            # ① 引用指令没动过：挖掉它内嵌的 disp 后全局唯一命中
            hits = find_wildcard(pe_new, snip, doff, 4, 16)
            rvas = [r for r in (pe_new.rva_of_off(h) for h in hits) if r is not None]
            if len(rvas) == 1:
                o = pe_new.off(rvas[0])
                disp = struct.unpack_from("<i", pe_new.data, o + doff)[0]
                return rvas[0] + ilen + disp, site, rvas[0], diag
            # ② 引用指令所在函数也挪了：按已知 Δ 平移过去，再掩掉 disp 比对
            for d in CAND_DELTAS:
                if d == 0:
                    continue
                b = pe_new.at(site + d, len(snip))
                if not b or b[:doff] != snip[:doff] or b[doff + 4:] != snip[doff + 4:]:
                    continue
                o = pe_new.off(site + d)
                if o is None:
                    continue
                disp = struct.unpack_from("<i", pe_new.data, o + doff)[0]
                return site + d + ilen + disp, site, site + d, diag
            diag.append(f"{site:#x}/w{w}:{len(rvas)}")
    return None, 0, 0, diag or [f"没有引用指令(sites={len(sites)})"]


def relocate_by_windows(pe_old: Pe, pe_new: Pe, rva: int,
                        offs=(0, 16, 32, 48, 64, 96, 128, 192), win: int = 32):
    """入口片段搜不到时，改从函数内部若干偏移取窗口再搜（函数头部小改也能救回来）。

    返回 (窗口偏移, 新 RVA, Δ)，找不到返回 None。
    """
    for o in offs:
        snip = pe_old.at(rva + o, win)
        if not snip:
            continue
        hits = pe_new.find_all(snip, 8)
        rvas = [r for r in (pe_new.rva_of_off(h) for h in hits) if r is not None]
        if len(rvas) == 1:
            return o, rvas[0], rvas[0] - rva
    return None


def vtable_probe(pe: Pe, rva: int, count: int = 8):
    """看某 RVA 处的 qword 数组是不是「一堆指向本模块的指针」（虚表的特征）。"""
    b = pe.at(rva, 8 * count)
    if not b:
        return None, []
    vals = struct.unpack_from("<%dQ" % count, b)
    text_va, text_size = next((s[1], s[2]) for s in pe.sections if s[0] == ".text")
    good = sum(1 for v in vals if text_va <= (v - pe.image_base) < text_va + text_size)
    return good, vals


def main() -> int:
    argv = list(sys.argv[1:])
    json_out: Path | None = None
    if "--json" in argv:                      # --json 是带值的选项，先摘出去，别混进位置参数
        i = argv.index("--json")
        json_out = Path(argv[i + 1])
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    old_p = Path(args[0]) if len(args) > 0 else OLD_DLL
    new_p = Path(args[1]) if len(args) > 1 else GAME_DLL
    win = int(args[2]) if len(args) > 2 else 48

    for label, p in (("旧版", old_p), ("新版", new_p)):
        if not p.exists():
            print(f"❌ {label} {p} 不存在")
            return 1
        print(f"{label}: {p.name}  {p.stat().st_size} 字节  MD5={md5(p)}")

    pe_old, pe_new = Pe(old_p), Pe(new_p)
    print(f"imagebase: 旧={pe_old.image_base:#x} 新={pe_new.image_base:#x}   片段长度 {win}")
    print("\n节表变化:")
    for tag, pe in (("旧", pe_old), ("新", pe_new)):
        for name, va, vsize, rawsize, ptr in pe.sections:
            if name in (".text", ".rdata", ".data", ".pdata"):
                print(f"   {tag} {name:<7} VA={va:#010x} vsize={vsize:#09x} "
                      f"raw={rawsize:#09x} rawptr={ptr:#010x}")

    rvas = parse_rvas()
    print(f"\n从 {SERVER.name} 抽到 {len(rvas)} 条 RVA\n")

    intact: list[tuple[str, int]] = []
    moved: list[tuple[str, int, int, int, int]] = []   # 名,旧,新,命中数,窗口偏移
    lost: list[tuple[str, int, bytes]] = []

    for name, rva in rvas:
        snippet = pe_old.at(rva, win)
        if snippet is None:
            lost.append((name, rva, b""))
            continue
        hits = pe_new.find_all(snippet)
        rvas_hit = [r for r in (pe_new.rva_of_off(h) for h in hits) if r is not None]
        if rva in rvas_hit:
            intact.append((name, rva))
        elif rvas_hit:
            moved.append((name, rva, rvas_hit[0], len(rvas_hit), 0))
        else:
            deeper = relocate_by_windows(pe_old, pe_new, rva)
            if deeper:
                o, found, _d = deeper
                moved.append((name, rva, found - o, 1, o))   # ★ 减掉窗口偏移才是函数入口
            else:
                lost.append((name, rva, snippet))

    print("=" * 78)
    print(f"① 原位未动：{len(intact)} 条")
    for name, rva in intact:
        print(f"   ✔ {rva:#010x}  {name}")

    print("\n" + "=" * 78)
    print(f"② 挪位（可用字节片段直接算出新 RVA）：{len(moved)} 条")
    for name, rva, nrva, nhit, o in moved:
        align, pad = entry_check(pe_new, nrva)
        conf = ("对齐✓" if align == 0 else f"⚠对齐{align}")
        conf += " 前置填充✓" if pad > 0 else " 前置无填充"
        note = f"命中{nhit}处" if nhit > 1 else (f"滑窗+{o}" if o else "入口片段")
        print(f"   → {rva:#010x} → {nrva:#010x}  Δ{nrva - rva:+#x}  {name:<36} [{note} {conf}]")

    print("\n" + "=" * 78)
    print(f"③ 片段搜不到：{len(lost)} 条 —— 再分两类看")
    real_lost: list[tuple[str, int]] = []
    for name, rva, snip in lost:
        if "_VTABLE" in name:
            good, vals = vtable_probe(pe_new, rva)
            tag = "虚表位置不变（该处仍是本模块指针数组）" if good else "该处已不是虚表"
            print(f"   ⓥ {rva:#010x}  {name:<34} {tag}  前4项={[hex(v) for v in vals[:4]]}")
        elif "GLOBAL" in name or name in ("RVA_MAP_HISTORY_GATE", "RVA_CHAMMERAPP",
                                          "RVA_BIND_TARGET_LIST", "RVA_CMAPENTITY_FACTORY"):
            print(f"   ⓓ {rva:#010x}  {name:<34} 数据/全局：位置待用「谁引用它」反查")
            real_lost.append((name, rva))
        else:
            print(f"   ✘ {rva:#010x}  {name:<34} 旧片段 {snip[:8].hex(' ')}  → 函数本体被改，需重逆")
            real_lost.append((name, rva))

    globals_map: dict[str, int] = {}
    if "--globals" in sys.argv:
        print("\n" + "=" * 78)
        print("④ 数据全局：靠 .text 里的 RIP 相对引用反查")
        for name, rva in GLOBALS:
            new, site_old, site_new, diag = relocate_via_xref(pe_old, pe_new, rva)
            if new:
                globals_map[name] = new
                print(f"   → {rva:#010x} → {new:#010x}  Δ{new - rva:+#x}  {name:<28}"
                      f" (引用指令 {site_old:#x}→{site_new:#x})")
            else:
                print(f"   ✘ {rva:#010x}  {name:<28} 反查失败: {', '.join(diag[:6])}")

    if json_out is not None:
        mp = {name: nrva for name, _rva, nrva, _h, _o in moved}
        mp.update(globals_map)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(mp, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n已写出 {len(mp)} 条新 RVA -> {json_out}")

    print("\n" + "=" * 78)
    deltas: dict[int, int] = {}
    for _n, rva, nrva, h, _o in moved:
        if h == 1:
            deltas[nrva - rva] = deltas.get(nrva - rva, 0) + 1
    print(f"小结：未动 {len(intact)} / 可重定位 {len(moved)} / 待人工处理 {len(lost)}   共 {len(rvas)}")
    print("唯一命中项的 Δ 分布：" + ", ".join(f"{hex(d)}×{c}" for d, c in sorted(deltas.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
