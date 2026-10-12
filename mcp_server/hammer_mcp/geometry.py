"""Hammer geometry operations."""
from __future__ import annotations
import struct
from typing import Any
from .offsets import (
    ENTITY_OFF_ORIGIN,
    FACE_OFF_FIRST_HE,
    HEC_OFF_NEXT,
    HEC_OFF_ORIGIN_VERTEX,
    MESH_OFF_AABB,
    MESH_OFF_POLYMESH,
    MESH_OFF_POLYMESH_BACKPTR,
    POLY_CH_STRIDE,
    POLY_CUTLSTRING_SIZE,
    POLY_HANDLE_INVALID,
    POLY_HANDLE_MASK,
    POLY_HANDLE_SERIAL_MASK,
    POLY_OFF_CH0,
    POLY_OFF_CH_CTL,
    POLY_OFF_CH_FLAGS,
    POLY_OFF_FACE_AXIS_U,
    POLY_OFF_FACE_AXIS_V,
    POLY_OFF_FACE_MATINDEX,
    POLY_OFF_FACE_SCALE,
    POLY_OFF_FPOOL_CNT,
    POLY_OFF_FPOOL_PTR,
    POLY_OFF_HEMAP_CNT,
    POLY_OFF_HEMAP_PTR,
    POLY_OFF_HEPOOL_PTR,
    POLY_OFF_HE_DENSE,
    POLY_OFF_HE_NORMAL,
    POLY_OFF_HE_TEXCOORD,
    POLY_OFF_MATERIALS,
    POLY_OFF_VMAP_CNT,
    POLY_OFF_VMAP_PTR,
    POLY_OFF_VPOOL_CAP,
    POLY_OFF_VPOOL_CNT,
    POLY_OFF_VPOOL_PTR,
    RVA_CHAMMERPOLYMESH_VTABLE,
    VREC_OFF_POS_INDEX,
)
from .runtime import (
    _hammer_base,
    _read_bytes,
    _read_int,
    _read_string,
    _read_vec3,
)


def _poly_u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _poly_u64(buf: bytes, off: int) -> int:
    return struct.unpack_from("<Q", buf, off)[0]


def _poly_handle_slot(map_ptr: int, map_cnt: int, handle: int) -> int | None:
    """handle(低22位索引+高位序列号) -> 记录池槽位；校验不过返回 None。

    与 hammer.dll sub_180CC2830 的校验等价：索引范围内 + 表项里存的句柄索引一致 + 序列号一致。
    """
    idx = handle & POLY_HANDLE_MASK
    if not map_ptr or idx == POLY_HANDLE_INVALID or idx >= map_cnt:
        return None
    rec = _read_bytes(map_ptr + 24 * idx, 24)
    stored = _poly_u32(rec, 8)
    if (stored & POLY_HANDLE_MASK) != idx:
        return None
    if (handle ^ stored) & POLY_HANDLE_SERIAL_MASK:
        return None
    return _poly_u32(rec, 0)


def _poly_position_channel(poly: int) -> tuple[int, int, int]:
    """取位置通道 -> (数据个数, 数据指针, 通道号)；无位置通道返回 (0, 0, -1)。"""
    ctl = _read_int(poly + POLY_OFF_CH_CTL, "u32")
    ch = (ctl >> 8) & 0xFF
    if (ctl & 0xFF) != 2 or ch > 5:
        return 0, 0, -1
    if _read_bytes(poly + POLY_OFF_CH_FLAGS + ch, 1)[0] == 0:
        return 0, 0, -1
    desc = poly + POLY_OFF_CH0 + POLY_CH_STRIDE * ch
    cnt = _read_int(desc, "u32")
    ptr = _read_int(desc + 8, "u64")
    return cnt, ptr, ch


def _poly_ready(el: int) -> int:
    """校验并返回该元素的运行时 CHammerPolyMesh 地址；不是 mesh / 未就绪返回 0。"""
    base = _hammer_base()
    want = base + RVA_CHAMMERPOLYMESH_VTABLE
    try:
        poly = _read_int(el + MESH_OFF_POLYMESH_BACKPTR, "u64")
        if poly and _read_int(poly, "u64") == want:
            return poly
        poly = el + MESH_OFF_POLYMESH
        if _read_int(poly, "u64") == want:
            return poly
    except Exception:  # noqa: BLE001
        pass
    return 0


def _poly_materials(poly: int) -> list[str]:
    """材料名表 CUtlVector<CUtlString> @ poly+0x3448（16B/条，条首 qword = 名字指针）。"""
    cnt = _read_int(poly + POLY_OFF_MATERIALS, "u32")
    ptr = _read_int(poly + POLY_OFF_MATERIALS + 8, "u64")
    if not (0 < cnt < 4096) or not (0x10000000000 < ptr < 0x800000000000):
        return []
    rec = _read_bytes(ptr, POLY_CUTLSTRING_SIZE * cnt)
    names = []
    for i in range(cnt):
        sp = _poly_u64(rec, POLY_CUTLSTRING_SIZE * i)
        try:
            names.append(_read_string(sp, 260) if 0x10000 < sp < 0x7FFFFFFFFFFF else "")
        except Exception:  # noqa: BLE001
            names.append("")
    return names


def _poly_vertex_box(poly: int, origin: tuple[float, float, float],
                     max_verts: int = 4096):
    """用顶点池 + 位置通道算世界包围盒（(xmin,ymin,zmin,xmax,ymax,zmax)）；顶点太多返回 None。

    只用于元素缓存 AABB 失效（例如单面 mesh 某轴被压成 0 宽）时的兜底。
    """
    try:
        vcnt = _read_int(poly + POLY_OFF_VPOOL_CNT, "u32")
        vptr = _read_int(poly + POLY_OFF_VPOOL_PTR, "u64")
        pos_cnt, pos_ptr, _ = _poly_position_channel(poly)
        if not (0 < vcnt <= max_verts) or not vptr or not pos_ptr:
            return None
        recs = _read_bytes(vptr, 32 * vcnt)
    except Exception:  # noqa: BLE001
        return None
    mn = [float("inf")] * 3
    mx = [float("-inf")] * 3
    seen = 0
    for i in range(vcnt):
        pidx = _poly_u32(recs, 32 * i + VREC_OFF_POS_INDEX)
        if pidx >= pos_cnt:
            continue
        try:
            p = struct.unpack("<3f", _read_bytes(pos_ptr + 12 * pidx, 12))
        except Exception:  # noqa: BLE001
            continue
        for k in range(3):
            w = p[k] + origin[k]
            mn[k] = min(mn[k], w)
            mx[k] = max(mx[k], w)
        seen += 1
    if not seen:
        return None
    return (mn[0], mn[1], mn[2], mx[0], mx[1], mx[2])


def _mesh_world_box(el: int, poly: int):
    """mesh 的世界包围盒 + 来源说明。

    优先用元素缓存 AABB（`el+0x118`，布局 `{u32, xmin, ymin, zmin, xmax, ymax, zmax}`；
    实测手绘 mesh 与顶点算出来的一致）；缓存某个轴被压成 0 宽（单面 mesh 常见）或非法时，
    用小顶点数兜底重算。注意：地图自带的部分 tile mesh 缓存与顶点不在同一参照系（§13.6），
    两者都只当「大致范围」用。
    """
    box = None
    try:
        f = struct.unpack("<7f", _read_bytes(el + MESH_OFF_AABB, 28))
        xmin, ymin, zmin, xmax, ymax, zmax = f[1:7]
        if (xmin <= xmax and ymin <= ymax and zmin <= zmax
                and abs(xmin) < 1e9 and abs(xmax) < 1e9):
            box = (xmin, ymin, zmin, xmax, ymax, zmax)
    except Exception:  # noqa: BLE001
        box = None

    if box and all(box[i + 3] - box[i] > 0.01 for i in range(3)):
        return box, "AABB缓存"

    try:
        origin = _read_vec3(el + ENTITY_OFF_ORIGIN)
    except Exception:  # noqa: BLE001
        origin = (0.0, 0.0, 0.0)
    vbox = _poly_vertex_box(poly, origin)
    if box is None:
        return vbox, "顶点重算(无缓存)"
    if vbox is None:
        return box, "AABB缓存(某轴0宽)"
    # 缓存某轴被压成 0 宽时（单面 mesh / 带旋转的 mesh，两个来源的退化轴可能互补），
    # 取并集 —— 宁可范围外扩，也不要把对象漏掉。
    union = tuple([min(box[i], vbox[i]) for i in range(3)]
                  + [max(box[i + 3], vbox[i + 3]) for i in range(3)])
    return union, "并集(AABB缓存+顶点)"


def _parse_vec3_arg(value: Any, name: str) -> tuple[float, float, float]:
    """把 "x y z" / "x,y,z" / [x, y, z] 解析成 3 个 float。"""
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    parts = str(value).replace("[", " ").replace("]", " ").replace(",", " ").split()
    if len(parts) != 3:
        raise ValueError(f'{name} 需要 3 个数字，例如 "0 0 0"（收到 {value!r}）')
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError as e:
        raise ValueError(f'{name} 不是 3 个数字：{value!r}') from e


def _box_hits(box: tuple[float, ...], qmin: tuple[float, float, float],
              qmax: tuple[float, float, float]) -> bool:
    """AABB 相交（闭区间）。"""
    return all(box[i + 3] >= qmin[i] and box[i] <= qmax[i] for i in range(3))


def _point_hits(p: tuple[float, float, float], qmin: tuple[float, float, float],
                qmax: tuple[float, float, float]) -> bool:
    return all(qmin[i] <= p[i] <= qmax[i] for i in range(3))


def _mesh_geometry_runtime(mesh_el: int, max_faces: int) -> str:
    """读运行时 CHammerPolyMesh 的半边缘几何（顶点/面环/世界包围盒）。"""
    poly = _poly_ready(mesh_el)
    if not poly:
        return (f"{mesh_el:#x} 没找到运行时的 CHammerPolyMesh"
                f"（+{MESH_OFF_POLYMESH_BACKPTR:#x} 指针 与 +{MESH_OFF_POLYMESH:#x} 内嵌均校验失败）")

    hdr = _read_bytes(poly, POLY_OFF_CH0 + POLY_CH_STRIDE * 6)
    vpool_cnt = _poly_u32(hdr, POLY_OFF_VPOOL_CNT)
    vpool_ptr = _poly_u64(hdr, POLY_OFF_VPOOL_PTR)
    vmap_cnt = _poly_u32(hdr, POLY_OFF_VMAP_CNT)
    vmap_ptr = _poly_u64(hdr, POLY_OFF_VMAP_PTR)
    hepool_ptr = _poly_u64(hdr, POLY_OFF_HEPOOL_PTR)
    hemap_cnt = _poly_u32(hdr, POLY_OFF_HEMAP_CNT)
    hemap_ptr = _poly_u64(hdr, POLY_OFF_HEMAP_PTR)
    fpool_cnt = _poly_u32(hdr, POLY_OFF_FPOOL_CNT)
    fpool_ptr = _poly_u64(hdr, POLY_OFF_FPOOL_PTR)
    if max(vpool_cnt, vmap_cnt, hemap_cnt, fpool_cnt) > 2_000_000:
        return f"{mesh_el:#x} 的 CHammerPolyMesh 头异常（count 过大），可能不是 mesh 元素"

    pos_cnt, pos_ptr, pos_ch = _poly_position_channel(poly)
    origin = _read_vec3(mesh_el + ENTITY_OFF_ORIGIN)

    def vec_desc(off: int) -> tuple[int, int]:
        """读一个 CUtlVector 描述符 -> (元素数, 数据指针)。"""
        return _read_int(poly + off, "u32"), _read_int(poly + off + 8, "u64")

    # 半边「密集序 -> handle 索引」映射：逐半边属性数组按密集序排列
    dense_cnt, dense_ptr = vec_desc(POLY_OFF_HE_DENSE)
    handle_to_dense: dict[int, int] = {}
    if 0 < dense_cnt < 1_000_000 and 0x10000000000 < dense_ptr < 0x800000000000:
        raw = _read_bytes(dense_ptr, 16 * dense_cnt)
        for i in range(dense_cnt):
            handle_to_dense[_poly_u32(raw, 16 * i) & POLY_HANDLE_MASK] = i

    tc_cnt, tc_ptr = vec_desc(POLY_OFF_HE_TEXCOORD)
    nrm_cnt, nrm_ptr = vec_desc(POLY_OFF_HE_NORMAL)
    fscale_cnt, fscale_ptr = vec_desc(POLY_OFF_FACE_SCALE)
    fau_cnt, fau_ptr = vec_desc(POLY_OFF_FACE_AXIS_U)
    fav_cnt, fav_ptr = vec_desc(POLY_OFF_FACE_AXIS_V)
    fmi_cnt, fmi_ptr = vec_desc(POLY_OFF_FACE_MATINDEX)
    materials = _poly_materials(poly)

    def he_uv(handle: int):
        d = handle_to_dense.get(handle & POLY_HANDLE_MASK)
        if d is None or not tc_ptr or d >= tc_cnt:
            return None
        return struct.unpack("<2f", _read_bytes(tc_ptr + 8 * d, 8))

    def he_normal(handle: int):
        d = handle_to_dense.get(handle & POLY_HANDLE_MASK)
        if d is None or not nrm_ptr or d >= nrm_cnt:
            return None
        return struct.unpack("<3f", _read_bytes(nrm_ptr + 12 * d, 12))

    def face_material(fslot: int) -> str:
        if not fmi_ptr or fslot >= fmi_cnt:
            return "<无 materialindex>"
        idx = _read_int(fmi_ptr + 4 * fslot, "i32")
        if 0 <= idx < len(materials):
            return materials[idx]
        return f"<越界 index={idx}，材料名表 {len(materials)} 项>"

    def face_tex_params(fslot: int) -> str:
        parts = []
        if fscale_ptr and fslot < fscale_cnt:
            s = struct.unpack("<2f", _read_bytes(fscale_ptr + 8 * fslot, 8))
            parts.append("scale=(%.4f,%.4f)" % s)
        if fau_ptr and fslot < fau_cnt:
            u = struct.unpack("<4f", _read_bytes(fau_ptr + 16 * fslot, 16))
            parts.append("U=(%.3f,%.3f,%.3f,w=%.3f)" % u)
        if fav_ptr and fslot < fav_cnt:
            v = struct.unpack("<4f", _read_bytes(fav_ptr + 16 * fslot, 16))
            parts.append("V=(%.3f,%.3f,%.3f,w=%.3f)" % v)
        return "  ".join(parts) if parts else "<无贴图参数>"

    pos_cache: dict[int, tuple[float, float, float]] = {}

    def vertex_local(vslot: int):
        """顶点池槽位 -> 本地坐标（位置通道 12B/顶点）。"""
        if vslot in pos_cache:
            return pos_cache[vslot]
        vrec = _read_bytes(vpool_ptr + 32 * vslot, 32)
        pidx = _poly_u32(vrec, VREC_OFF_POS_INDEX)
        pt = None
        if pos_ptr and pidx < pos_cnt:
            pt = struct.unpack("<3f", _read_bytes(pos_ptr + 12 * pidx, 12))
        pos_cache[vslot] = pt
        return pt

    lines = [
        f"CMapMesh {mesh_el:#x} 运行时 CHammerPolyMesh={poly:#x}",
        f"  顶点池 {vpool_cnt}（handle 表 {vmap_cnt}）  半边池 {hemap_cnt}（handle 表）  "
        f"面池 {fpool_cnt}  位置通道 #{pos_ch} 数据 {pos_cnt}  元素 origin={origin}",
        f"  材料名表 {len(materials)} 项 {materials[:8]}",
    ]

    verts: dict[int, tuple[float, float, float] | None] = {}
    for slot in range(min(vpool_cnt, max(max_faces * 8, 64))):
        verts[slot] = vertex_local(slot)

    wpts = []
    for slot, p in verts.items():
        if p:
            w = (origin[0] + p[0], origin[1] + p[1], origin[2] + p[2])
            wpts.append(w)
            lines.append(f"  v{slot:<3} 本地=({p[0]:9.3f},{p[1]:9.3f},{p[2]:9.3f})  "
                         f"世界=({w[0]:9.3f},{w[1]:9.3f},{w[2]:9.3f})")
    if wpts:
        mn = [min(p[i] for p in wpts) for i in range(3)]
        mx = [max(p[i] for p in wpts) for i in range(3)]
        lines.append("  世界包围盒 = (%.3f, %.3f, %.3f) ~ (%.3f, %.3f, %.3f)"
                     % (*mn, *mx))

    shown = 0
    for fslot in range(fpool_cnt):
        if shown >= max_faces:
            lines.append(f"  … 其余 {fpool_cnt - shown} 个面省略（max_faces={max_faces}）")
            break
        frec = _read_bytes(fpool_ptr + 32 * fslot, 32)
        first = _poly_u32(frec, FACE_OFF_FIRST_HE)
        loop: list[int | None] = []
        he_list: list[int] = []
        he = first
        for _ in range(4096):
            hslot = _poly_handle_slot(hemap_ptr, hemap_cnt, he)
            if hslot is None:
                loop.append(None)
                break
            hrec = _read_bytes(hepool_ptr + 80 * hslot, 80)
            he_list.append(he)
            loop.append(_poly_handle_slot(vmap_ptr, vmap_cnt,
                                          _poly_u32(hrec, HEC_OFF_ORIGIN_VERTEX)))
            he = _poly_u32(hrec, HEC_OFF_NEXT)
            if (he & POLY_HANDLE_MASK) == (first & POLY_HANDLE_MASK):
                break
        lines.append(f"  face[{fslot}] 首半边#{first & POLY_HANDLE_MASK} 顶点数 {len(loop)}  "
                     f"材质={face_material(fslot)}")
        lines.append(f"      贴图 {face_tex_params(fslot)}")
        for vs, he_h in zip(loop, he_list):
            p = verts.get(vs) if vs is not None else None
            if not p:
                continue
            uv = he_uv(he_h)
            n = he_normal(he_h)
            extra = ""
            if uv:
                extra += "  uv=(%.4f, %.4f)" % uv
            if n:
                extra += "  n=(%.3f, %.3f, %.3f)" % n
            lines.append("      v%-3d 世界=(%.3f, %.3f, %.3f)%s"
                         % (vs, origin[0] + p[0], origin[1] + p[1], origin[2] + p[2], extra))
        shown += 1
    return "\n".join(lines)


def _mesh_live_vertices(el: int, poly: int):
    """枚举活跃顶点 -> [(vertexHandle, poolSlot, posIndex, world(x,y,z))]。

    走顶点 handle 映射表（`poly+0x30`，24B/条：{池槽位@0, ?@4, 句柄@8}），
    句柄低 22 位 == 下标即为活跃项；顶点记录 `+0x10` 是位置通道下标，世界坐标 = 位置 + 元素 origin。
    """
    vmap_cnt = _read_int(poly + POLY_OFF_VMAP_CNT, "u32")
    vmap_ptr = _read_int(poly + POLY_OFF_VMAP_PTR, "u64")
    vpool_cap = _read_int(poly + POLY_OFF_VPOOL_CAP, "u32")
    vpool_ptr = _read_int(poly + POLY_OFF_VPOOL_PTR, "u64")
    pos_cnt, pos_ptr, _ = _poly_position_channel(poly)
    if not (0 < vmap_cnt < 1_000_000 and 0 < vpool_cap < 1_000_000) or not vmap_ptr or not vpool_ptr:
        return []
    origin = _read_vec3(el + ENTITY_OFF_ORIGIN)
    raw_map = _read_bytes(vmap_ptr, 24 * vmap_cnt)
    raw_pool = _read_bytes(vpool_ptr, 32 * vpool_cap)
    raw_pos = _read_bytes(pos_ptr, 12 * pos_cnt) if pos_ptr and pos_cnt else b""
    out = []
    for i in range(vmap_cnt):
        handle = _poly_u32(raw_map, 24 * i + 8)
        if (handle & POLY_HANDLE_MASK) != i:      # 空闲槽
            continue
        slot = _poly_u32(raw_map, 24 * i)
        if slot >= vpool_cap:
            continue
        pidx = _poly_u32(raw_pool, 32 * slot + VREC_OFF_POS_INDEX)
        if pidx >= pos_cnt or len(raw_pos) < 12 * (pidx + 1):
            continue
        p = struct.unpack_from("<3f", raw_pos, 12 * pidx)
        out.append((handle, slot, pidx,
                    (p[0] + origin[0], p[1] + origin[1], p[2] + origin[2])))
    return out
