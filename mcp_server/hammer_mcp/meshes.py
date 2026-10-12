"""Hammer meshes operations."""
from __future__ import annotations
from .results import EditResult
import math
import struct
from typing import Literal
from .datamodel import (
    _dm_array_handles,
    _dm_array_numbers,
    _dm_array_strings,
    _dm_attr_element,
    _dm_attr_value,
    _dm_find_attr,
    _dm_handle_map,
    _dm_table,
    _resolve_handle,
)
from .geometry import (
    _mesh_geometry_runtime,
    _mesh_world_box,
    _mesh_live_vertices,
    _parse_vec3_arg,
    _poly_handle_slot,
    _poly_materials,
    _poly_position_channel,
    _poly_ready,
    _poly_u32,
)
from .history import (
    _find_map_histories,
    _hist_notify,
    _hist_push_step,
    _hist_record_node,
    _hist_record_object,
    _hist_state,
)
from .offsets import (
    CMAPDOC_WORLD_OFFSET,
    ENTITY_CREATE_FLAGS,
    ENTITY_OFF_ORIGIN,
    FACE_OFF_FIRST_HE,
    HEC_OFF_NEXT,
    HEC_OFF_ORIGIN_VERTEX,
    MESH_ATTR_DATA,
    MESH_ATTR_EDGE_NEXT_INDICES,
    MESH_ATTR_EDGE_VERTEX_DATA_INDICES,
    MESH_ATTR_FACE_DATA,
    MESH_ATTR_FACE_EDGE_INDICES,
    MESH_ATTR_FACE_VERTEX_DATA,
    MESH_ATTR_MATERIALS,
    MESH_ATTR_STREAMS,
    MESH_ATTR_VERTEX_DATA,
    MESH_OFF_AABB,
    MESH_OFF_POLYMESH_BACKPTR,
    MESH_STREAM_ATTR_DATA,
    MESH_STREAM_ATTR_SEMANTIC,
    MESH_STREAM_COMPONENTS,
    NODE_IFACE_OFFSET,
    NODE_OFF_CHILD_COUNT,
    POLY_HANDLE_MASK,
    POLY_OFF_FPOOL_CNT,
    POLY_OFF_FPOOL_PTR,
    POLY_OFF_HEMAP_CNT,
    POLY_OFF_HEMAP_PTR,
    POLY_OFF_HEPOOL_PTR,
    POLY_OFF_HE_DENSE,
    POLY_OFF_HE_NORMAL,
    POLY_OFF_HE_TEXCOORD,
    POLY_OFF_VMAP_CNT,
    POLY_OFF_VMAP_PTR,
    POLY_OFF_VPOOL_PTR,
    RVA_CDATAMODEL_GLOBAL,
    RVA_CHAMMERPOLYMESH_VTABLE,
    RVA_CMAPMESH_VTABLE,
    RVA_DATAMODEL_CREATE_ELEMENT,
    RVA_MESH_BUILD_FACE,
    RVA_NODE_ADD_CHILD,
    RVA_NODE_GET_PARENT,
    RVA_NODE_POST_CLASS,
    RVA_POLY_MERGE_VERTICES,
    RVA_POLY_REMOVE_ISOLATED,
    RVA_POLY_SET_VERTEX_POSITIONS,
    TEX_DEFAULT_SCALE,
    TEX_DEFAULT_SIZE,
    VREC_OFF_POS_INDEX,
)
from .runtime import (
    _alloc_mem,
    _call_fn,
    _free_mem,
    _hammer_base,
    _parse_addr,
    _invoke_main,
    _read_bytes,
    _read_int,
    _read_vec3,
    _write_mem_chunked,
)
from .scene import (
    _doc_of_element,
    _map_doc,
    _walk_elements,
)


def cs2_mesh_scale(mesh: str, scale: str = "1 1 1", pivot: str = "") -> str:
    """缩放 mesh 几何（改顶点坐标），走 Hammer 自己的顶点写入算子。

    链路（2026-09-27 逆向，见 REVERSE_NOTES §13.10）：

        sub_180CDC6E0(poly, CUtlVector<顶点handle>*, 3x4矩阵*, CUtlVector<Vector>*)
          = CPolygonMesh 官方算子 **"SetVertexPositions"**：开事务 → 写位置通道 →
            更新缓存 → 发脏通知（Hammer 自己的 vfn+160 变换也走它）

    这里给它传**单位矩阵** + 网格本地坐标 —— 于是写进去的就是想要的值，不依赖
    「local→world 只差一个平移」的假设（地图自带 tile mesh 不满足该假设，见 §13.6）。
    顶点位置是 mesh 唯一的几何真相，缩放它就是缩放 mesh；UV 不动，所以贴图会跟着拉伸
    （等价 Hammer 里「关掉纹理锁定」缩放）。

    Args:
        mesh: CMapMesh 元素地址（cs2_mesh_list / cs2_area_query 给出）。
        scale: 各轴缩放系数 "sx sy sz"（也接受 "s,s,s"；单个数字 = 等比）。
        pivot: 缩放中心（世界坐标 "x y z"，内部换算到网格本地）；留空 = 用元素 origin。
    """
    base = _hammer_base()
    try:
        el = _parse_addr(mesh)
        poly = _poly_ready(el)
        if not poly:
            return f"{el:#x} 不是可编辑的 CMapMesh（没找到运行时 CHammerPolyMesh）"
        if "," in str(scale) or " " in str(scale).strip():
            sc = _parse_vec3_arg(scale, "scale")
        else:
            s = float(str(scale).strip())
            sc = (s, s, s)
        if sc[0] == 0 or sc[1] == 0 or sc[2] == 0:
            return "ERROR scale 不能含 0（会把 mesh 压成平面）"

        verts = _mesh_live_vertices(el, poly)
        if not verts:
            return f"{el:#x} 没有活跃顶点（可能只是空 mesh 元素）"
        origin = _read_vec3(el + ENTITY_OFF_ORIGIN)

        # 世界 pivot -> 本地 pivot（本地就是位置通道里存的坐标）
        if str(pivot).strip():
            pw = _parse_vec3_arg(pivot, "pivot")
        else:
            pw = origin
        pv = (pw[0] - origin[0], pw[1] - origin[1], pw[2] - origin[2])

        n = len(verts)
        size = 48 + 24 + 16 * n + 24 + 12 * n
        mem = _alloc_mem(size)
        mtx = mem
        hdr_h, data_h = mem + 48, mem + 48 + 24
        hdr_p, data_p = data_h + 16 * n + 24, data_h + 16 * n + 24 + 24
        try:
            hbuf = bytearray(16 * n)
            pbuf = bytearray(12 * n)
            for i, (handle, _slot, _pidx, w) in enumerate(verts):
                struct.pack_into("<I", hbuf, 16 * i, handle)
                # w 是「本地 + origin」，先还原成本地
                lx, ly, lz = w[0] - origin[0], w[1] - origin[1], w[2] - origin[2]
                struct.pack_into("<3f", pbuf, 12 * i,
                                 pv[0] + (lx - pv[0]) * sc[0],
                                 pv[1] + (ly - pv[1]) * sc[1],
                                 pv[2] + (lz - pv[2]) * sc[2])
            _write_mem_chunked(mtx, struct.pack("<12f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0))
            _write_mem_chunked(hdr_h, struct.pack("<IIQII", n, 0, data_h, n, 0))
            _write_mem_chunked(data_h, bytes(hbuf))
            _write_mem_chunked(hdr_p, struct.pack("<IIQII", n, 0, data_p, n, 0))
            _write_mem_chunked(data_p, bytes(pbuf))
            _invoke_main(base + RVA_POLY_SET_VERTEX_POSITIONS, [poly, hdr_h, mtx, hdr_p],
                     timeout=20000)
        finally:
            _free_mem(mem)

        after = _mesh_live_vertices(el, poly)
        if not after:
            return "⚠ 调用已发出，但顶点读不回来了（mesh 状态异常）"
        mn = [min(v[3][k] for v in after) for k in range(3)]
        mx = [max(v[3][k] for v in after) for k in range(3)]
        try:
            box = struct.unpack("<7f", _read_bytes(el + MESH_OFF_AABB, 28))[1:7]
        except Exception:  # noqa: BLE001
            box = (0.0,) * 6
        body = (
            "已缩放 mesh 顶点  scale=(%.3f, %.3f, %.3f)  pivot(世界)=(%.1f, %.1f, %.1f)  顶点 %d 个\n"
            "  顶点世界包围盒 = (%.3f, %.3f, %.3f) ~ (%.3f, %.3f, %.3f)\n"
            "  元素缓存 AABB  = (%.3f, %.3f, %.3f) ~ (%.3f, %.3f, %.3f)"
            % (*sc, *pw, len(after), *mn, *mx, *box)
        )
        return body + "（缓存由 Hammer 异步刷新，可能延迟一拍）"
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


def _poly_set_flat_normals(poly: int) -> int:
    """把每角法线重写成**所属面的面法线**（Hammer 原生笔刷那种平直着色）。返回写入的半边数。

    为什么需要：官方焊接算子 `MergeVerticesWithinDistance` 会把每角法线**重算成顶点平均
    法线** —— 方块的角点变成 `(±1,±1,±1)/√3`，等于把方块渲染成"圆角/球面感"，实测
    未焊接时 CreateFace 给的是正确面法线，一焊就坏；而 Hammer 自己的笔刷（同样共享顶点、
    8 顶点 6 面）存的是**面法线**。所以焊接后必须按面重写一遍。

    写的是 `poly+POLY_OFF_HE_NORMAL` 那张**逐半边密集序**数组（12B/条，索引走
    `poly+POLY_OFF_HE_DENSE` 的「密集序 -> handle」映射），与 cs2_mesh_get_geometry 的读法同源。
    """
    try:
        vpool_ptr = _read_int(poly + POLY_OFF_VPOOL_PTR, "u64")
        vmap_cnt = _read_int(poly + POLY_OFF_VMAP_CNT, "u32")
        vmap_ptr = _read_int(poly + POLY_OFF_VMAP_PTR, "u64")
        hepool_ptr = _read_int(poly + POLY_OFF_HEPOOL_PTR, "u64")
        hemap_cnt = _read_int(poly + POLY_OFF_HEMAP_CNT, "u32")
        hemap_ptr = _read_int(poly + POLY_OFF_HEMAP_PTR, "u64")
        fpool_cnt = _read_int(poly + POLY_OFF_FPOOL_CNT, "u32")
        fpool_ptr = _read_int(poly + POLY_OFF_FPOOL_PTR, "u64")
        dense_cnt = _read_int(poly + POLY_OFF_HE_DENSE, "u32")
        dense_ptr = _read_int(poly + POLY_OFF_HE_DENSE + 8, "u64")
        nrm_cnt = _read_int(poly + POLY_OFF_HE_NORMAL, "u32")
        nrm_ptr = _read_int(poly + POLY_OFF_HE_NORMAL + 8, "u64")
        pos_cnt, pos_ptr, _ = _poly_position_channel(poly)
        if not (vpool_ptr and vmap_ptr and hepool_ptr and hemap_ptr and fpool_ptr
                and dense_ptr and nrm_ptr and pos_ptr):
            return 0
        if not (0 < dense_cnt < 1_000_000 and 0 < nrm_cnt < 1_000_000):
            return 0

        handle_to_dense: dict[int, int] = {}
        raw = _read_bytes(dense_ptr, 16 * dense_cnt)
        for i in range(dense_cnt):
            handle_to_dense[_poly_u32(raw, 16 * i) & POLY_HANDLE_MASK] = i

        pos_of_slot: dict[int, tuple[float, float, float]] = {}

        def slot_pos(vslot: int):
            if vslot in pos_of_slot:
                return pos_of_slot[vslot]
            p = None
            try:
                vrec = _read_bytes(vpool_ptr + 32 * vslot, 32)
                pidx = _poly_u32(vrec, VREC_OFF_POS_INDEX)
                if pidx < pos_cnt:
                    p = struct.unpack("<3f", _read_bytes(pos_ptr + 12 * pidx, 12))
            except Exception:  # noqa: BLE001
                p = None
            pos_of_slot[vslot] = p
            return p

        normals = bytearray(_read_bytes(nrm_ptr, 12 * nrm_cnt))
        written = 0
        for fslot in range(fpool_cnt):
            first = _poly_u32(_read_bytes(fpool_ptr + 32 * fslot, 32), FACE_OFF_FIRST_HE)
            he = first
            hes: list[int] = []
            pts: list[tuple[float, float, float]] = []
            for _ in range(4096):
                hslot = _poly_handle_slot(hemap_ptr, hemap_cnt, he)
                if hslot is None:
                    break
                hrec = _read_bytes(hepool_ptr + 80 * hslot, 80)
                hes.append(he & POLY_HANDLE_MASK)
                vs = _poly_handle_slot(vmap_ptr, vmap_cnt,
                                       _poly_u32(hrec, HEC_OFF_ORIGIN_VERTEX))
                p = slot_pos(vs) if vs is not None else None
                if p:
                    pts.append(p)
                he = _poly_u32(hrec, HEC_OFF_NEXT)
                if (he & POLY_HANDLE_MASK) == (first & POLY_HANDLE_MASK):
                    break
            if len(pts) < 3:
                continue
            nx, ny, nz = _face_normal_newell(pts)
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            if ln < 1e-12:
                continue
            packed = struct.pack("<3f", nx / ln, ny / ln, nz / ln)
            for h in hes:
                d = handle_to_dense.get(h)
                if d is None or d >= nrm_cnt:
                    continue
                normals[12 * d:12 * d + 12] = packed
                written += 1
        if written:
            _write_mem_chunked(nrm_ptr, bytes(normals))
        return written
    except Exception:  # noqa: BLE001
        return 0


def _poly_restore_face_uvs(poly: int, local_faces, uv_faces) -> int:
    """Restore per-corner UVs after Hammer's vertex merge rewrites them.

    Match each surviving half-edge to its original face corner by local position.
    This preserves UV seams when several faces share one welded vertex.
    """
    dense_count = _read_int(poly + POLY_OFF_HE_DENSE, "u32")
    dense_ptr = _read_int(poly + POLY_OFF_HE_DENSE + 8, "u64")
    uv_count = _read_int(poly + POLY_OFF_HE_TEXCOORD, "u32")
    uv_ptr = _read_int(poly + POLY_OFF_HE_TEXCOORD + 8, "u64")
    face_count = _read_int(poly + POLY_OFF_FPOOL_CNT, "u32")
    face_ptr = _read_int(poly + POLY_OFF_FPOOL_PTR, "u64")
    he_count = _read_int(poly + POLY_OFF_HEMAP_CNT, "u32")
    he_ptr = _read_int(poly + POLY_OFF_HEMAP_PTR, "u64")
    vertex_count = _read_int(poly + POLY_OFF_VMAP_CNT, "u32")
    vertex_ptr = _read_int(poly + POLY_OFF_VMAP_PTR, "u64")
    vertex_pool = _read_int(poly + POLY_OFF_VPOOL_PTR, "u64")
    edge_pool = _read_int(poly + POLY_OFF_HEPOOL_PTR, "u64")
    position_count, position_ptr, _ = _poly_position_channel(poly)
    if not all((dense_ptr, uv_ptr, face_ptr, he_ptr, vertex_ptr,
                vertex_pool, edge_pool, position_ptr)):
        raise RuntimeError("UV 通道或拓扑数据不可读")
    if face_count != len(local_faces) or len(uv_faces) != face_count:
        raise RuntimeError("焊接后面数不一致，无法恢复 UV")
    dense_raw = _read_bytes(dense_ptr, dense_count * 16)
    dense = {_poly_u32(dense_raw, i * 16) & POLY_HANDLE_MASK: i
             for i in range(dense_count)}
    restored = bytearray(_read_bytes(uv_ptr, uv_count * 8))
    written = 0
    for face_index, (points, mapped) in enumerate(zip(local_faces, uv_faces)):
        if len(points) != len(mapped):
            raise RuntimeError("UV 与面顶点数量不一致")
        first = _poly_u32(_read_bytes(face_ptr + 32 * face_index, 32),
                          FACE_OFF_FIRST_HE)
        edge = first
        seen = set()
        for _ in range(len(points)):
            edge_key = edge & POLY_HANDLE_MASK
            if edge_key in seen:
                break
            seen.add(edge_key)
            edge_slot = _poly_handle_slot(he_ptr, he_count, edge)
            if edge_slot is None:
                raise RuntimeError("焊接后半边不可读")
            edge_record = _read_bytes(edge_pool + 80 * edge_slot, 80)
            vertex_slot = _poly_handle_slot(
                vertex_ptr, vertex_count,
                _poly_u32(edge_record, HEC_OFF_ORIGIN_VERTEX))
            if vertex_slot is None:
                raise RuntimeError("焊接后顶点不可读")
            vertex_record = _read_bytes(vertex_pool + 32 * vertex_slot, 32)
            position_index = _poly_u32(vertex_record, VREC_OFF_POS_INDEX)
            if position_index >= position_count:
                raise RuntimeError("焊接后位置索引越界")
            point = struct.unpack("<3f", _read_bytes(
                position_ptr + 12 * position_index, 12))
            closest = min(range(len(points)),
                          key=lambda i: sum((point[k] - points[i][k]) ** 2
                                            for k in range(3)))
            if sum((point[k] - points[closest][k]) ** 2 for k in range(3)) > 1e-4:
                raise RuntimeError("焊接后角点位置与原始面不匹配")
            dense_index = dense.get(edge_key)
            if dense_index is None or dense_index >= uv_count:
                raise RuntimeError("焊接后 UV 索引不可读")
            struct.pack_into("<2f", restored, dense_index * 8, *mapped[closest])
            written += 1
            edge = _poly_u32(edge_record, HEC_OFF_NEXT)
        if len(seen) != len(points) or (edge & POLY_HANDLE_MASK) != (first & POLY_HANDLE_MASK):
            raise RuntimeError("焊接后面角点数不一致")
    _write_mem_chunked(uv_ptr, bytes(restored))
    return written


def _mesh_weld_native(el: int, poly: int, distance: float = 0.01) -> tuple[int, int, int, str]:
    """原生焊接两步（不含历史）：MergeVerticesWithinDistance + RemoveIsolatedVertices。

    返回 (焊接前活跃顶点数, 焊接后活跃顶点数, 算子报告的合并数, 错误串)。
    """
    verts = _mesh_live_vertices(el, poly)
    n_before = len(verts)
    if n_before < 2:
        return n_before, n_before, 0, ""
    mem = _alloc_mem(20 + 16 * n_before)
    data = mem + 20
    try:
        hbuf = bytearray(16 * n_before)
        for i, (handle, _slot, _pidx, _w) in enumerate(verts):
            struct.pack_into("<I", hbuf, 16 * i, handle)
        _write_mem_chunked(mem, struct.pack("<IIQII", n_before, 0, data, n_before, 0))
        _write_mem_chunked(data, bytes(hbuf))
        # float 阈值走 "f:" 前缀 → xmm2（Win64 第 3 参数槽）
        ret, err = _call_fn(RVA_POLY_MERGE_VERTICES,
                            [poly, mem, f"f:{distance}", 1, 1, 0], timeout=30000)
        if err:
            return n_before, n_before, 0, f"MergeVerticesWithinDistance: {err}"
        merged = int(ret, 16) if ret else 0
        _r2, e2 = _call_fn(RVA_POLY_REMOVE_ISOLATED, [poly], timeout=30000)
        if e2:
            return n_before, n_before, merged, f"RemoveIsolatedVertices: {e2}"
    finally:
        _free_mem(mem)
    # 焊接会把每角法线变成平均法线（方块角 → (±1,±1,±1)/√3）→ 按面重写回面法线
    _poly_set_flat_normals(poly)
    return n_before, len(_mesh_live_vertices(el, poly)), merged, ""


def cs2_mesh_weld_vertices(mesh: str, distance: float = 0.01,
                           history: bool = True) -> str:
    """焊接 mesh 中距离很近的重复顶点（Hammer 官方 MergeVerticesWithinDistance 算子）。

    用途：`cs2_mesh_create_box` 每个面各带 4 个顶点 → 24 顶点/6 面；本工具把同一位置的
    顶点焊成一个 → 8 顶点，等价原生 Block 工具的产物。

    链路（2026-09-29 逆向，见 REVERSE_NOTES §16.10）：

        sub_180CD21E0(poly, 全部顶点 handle 向量, float 阈值, 1, 1, 0)
          = CPolygonMesh 算子 "MergeVerticesWithinDistance"
            第 4 参数=1：焊接时同步重接半边；第 5 参数=1：新顶点取两端中点
            （与 Hammer 顶点工具的「Weld Vertices」命令完全同款参数）
        sub_180CD83C0(poly)
          = "RemoveIsolatedVertices"：合并后旧顶点变成孤立点，必须再调一次清掉

    阈值是**距离**（单位：世界单位的网格本地尺度，算子内部平方比较）。官方 UI 固定 0.01。

    Args:
        mesh: CMapMesh 元素地址（cs2_mesh_list / cs2_area_query 给出）。
        distance: 焊接距离阈值，<= 该距离的顶点合并（默认 0.01，官方 UI 同款）。
        history: 是否记入 Hammer 的 Ctrl+Z 历史（默认 True）。
    """
    base = _hammer_base()
    try:
        if distance < 0:
            return "ERROR distance 不能为负"
        el = _parse_addr(mesh)
        poly = _poly_ready(el)
        if not poly:
            return f"{el:#x} 不是可编辑的 CMapMesh（没找到运行时 CHammerPolyMesh）"

        hist_note = ""
        if history:
            try:
                doc = _doc_of_element(el)   # 多文档：按 mesh 反查所属文档，别写错历史栈
                undo_h, _rd = _find_map_histories(doc)
                hist_before = _hist_state(undo_h)
                _hist_push_step(undo_h, "cs2: weld vertices")
                # 记录的是**改动前**节点状态，必须在真正焊接之前登记
                _hist_record_node(undo_h, el)
                _hist_notify(undo_h)
            except Exception as e:  # noqa: BLE001
                hist_note = f"  ⚠ 未记入 Ctrl+Z 历史（{type(e).__name__}: {e}）"

        n_before, n_after, merged, werr = _mesh_weld_native(el, poly, distance)
        if n_before < 2:
            return f"{el:#x} 活跃顶点不足 2 个（{n_before}），无需焊接"
        if werr:
            return f"ERROR {werr}"

        if history and not hist_note:
            try:
                hist_note = f"  Ctrl+Z 历史: {hist_before} -> {_hist_state(undo_h)}"
            except Exception:  # noqa: BLE001
                pass

        after = _mesh_live_vertices(el, poly)
        if n_after:
            mn = [min(v[3][k] for v in after) for k in range(3)]
            mx = [max(v[3][k] for v in after) for k in range(3)]
            box_s = (f"  顶点世界包围盒 = ({mn[0]:.3f}, {mn[1]:.3f}, {mn[2]:.3f})"
                     f" ~ ({mx[0]:.3f}, {mx[1]:.3f}, {mx[2]:.3f})")
        else:
            box_s = "  ⚠ 焊接后读不回顶点（mesh 状态异常）"
        return (
            f"已焊接 mesh 顶点 元素={el:#x}  阈值={distance:g}\n"
            f"  顶点 {n_before} -> {n_after}（算子报告合并 {merged} 个）\n"
            f"{box_s}\n{hist_note}".rstrip()
        )
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


_BOX_CORNERS = ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))


_BOX_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 4, 7, 3), (1, 2, 6, 5))


_TEX_AXES_BY_MAJOR = {
    0: ((0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),   # 主轴 X
    1: ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),   # 主轴 Y
    2: ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),   # 主轴 Z
}


def _face_normal_newell(pts):
    """多边形面法线（Newell 法，凹多边形也成立；大小为两倍面积）。"""
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0, z0 = pts[i]
        x1, y1, z1 = pts[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return nx, ny, nz


def _tex_axes_for_face(pts):
    """按面法线主轴选世界对齐贴图轴（主轴取绝对值最大者；并列时取靠后者，同 Hammer）。"""
    nx, ny, nz = _face_normal_newell(pts)
    absn = (abs(nx), abs(ny), abs(nz))
    best, major = -1.0, 0
    for i in range(3):
        if absn[i] >= best:
            best, major = absn[i], i
    return _TEX_AXES_BY_MAJOR[major]


def _dot_axis_range(ax, lo, hi):
    """`dot(ax, ·)` 在 AABB [lo, hi] 上的 (最小值, 最大值)。

    `ax` 只含 ±1 / 0（世界轴），所以逐分量取值即可，不需要枚举顶点。
    """
    d_lo = d_hi = 0.0
    for k in range(3):
        if ax[k] > 0.0:
            d_lo += ax[k] * lo[k]
            d_hi += ax[k] * hi[k]
        elif ax[k] < 0.0:
            d_lo += ax[k] * hi[k]
            d_hi += ax[k] * lo[k]
    return d_lo, d_hi


def _face_uv_bytes(pts, lo, hi, tex_size=TEX_DEFAULT_SIZE, tex_scale=TEX_DEFAULT_SCALE):
    """给一个面算 Hammer 风格的 UV（每点 8 字节 Vec2），返回字节串。

    ⚠ 必须传**世界坐标**（元素 origin + 本地坐标）与整网格的 AABB `[lo, hi]`。

    相位规则（实测 Hammer Block 工具产物）：轴是**世界轴**（按面法线主轴选），
    但 UV **从网格自己的角点起算** ——

        u = (dot(U轴, 世界坐标) − u_min) / (scale × textureSize)      # 锚在网格 U 向最小端
        v = (dot(V轴, 世界坐标) − v_max) / (scale × textureSize)      # 锚在网格 V 向最大端

    以 `materials/dev/reflectivity_30.vmat`（512 → 64 单位/贴图）为例，Hammer 新建的
    64×96×64 块：顶面 `u=(x−xmin)/64 → 0…1`、`v=−(y−ymin)/64 → 0…−1.5`；
    若改成世界相位（`u=x/64`）就会得到 `−13…−12`，和 Hammer 建出来的块对不上（差半个
    非整数相位，视觉上"效果不太一样"）。
    """
    (ux, uy, uz), (vx, vy, vz) = _tex_axes_for_face(pts)
    u_ax, v_ax = (ux, uy, uz), (vx, vy, vz)
    u_org, _ = _dot_axis_range(u_ax, lo, hi)
    _, v_org = _dot_axis_range(v_ax, lo, hi)
    k = (tex_scale or TEX_DEFAULT_SCALE) * (tex_size or TEX_DEFAULT_SIZE)
    out = bytearray()
    for x, y, z in pts:
        out += struct.pack("<2f",
                           (u_ax[0] * x + u_ax[1] * y + u_ax[2] * z - u_org) / k,
                           (v_ax[0] * x + v_ax[1] * y + v_ax[2] * z - v_org) / k)
    return bytes(out)


def _write_mesh_faces(el: int, base: int, local_faces: list[list[tuple[float, float, float]]],
                      center: tuple[float, float, float], material: str,
                      tex_size: float, uv_faces=None):
    """Create face loops and return UV values for post-weld restoration."""
    world_faces = [[tuple(center[k] + point[k] for k in range(3)) for point in face]
                   for face in local_faces]
    lo = tuple(min(point[k] for face in world_faces for point in face) for k in range(3))
    hi = tuple(max(point[k] for face in world_faces for point in face) for k in range(3))
    if uv_faces is None:
        uv_faces = [[struct.unpack_from('<2f', _face_uv_bytes(face, lo, hi, tex_size),
                                        8 * i) for i in range(len(face))]
                    for face in world_faces]
    if len(uv_faces) != len(local_faces) or any(
            len(uv) != len(face) for uv, face in zip(uv_faces, local_faces)):
        raise ValueError('UV 与面顶点数量不一致')
    n_points = sum(len(face) for face in local_faces)
    material_bytes = material.encode('utf-8') + b'\x00'
    memory = _alloc_mem(20 * n_points + len(material_bytes) + 8)
    points, uvs, material_ptr = memory, memory + 12 * n_points, memory + 20 * n_points
    try:
        vertices = b''.join(struct.pack('<3f', *point)
                            for face in local_faces for point in face)
        texture = b''.join(struct.pack('<2f', *uv) for face in uv_faces for uv in face)
        _write_mem_chunked(points, vertices)
        _write_mem_chunked(uvs, texture)
        _write_mem_chunked(material_ptr, material_bytes)
        point_offset = uv_offset = 0
        for face in local_faces:
            _invoke_main(base + RVA_MESH_BUILD_FACE,
                         [el, points + point_offset, uvs + uv_offset,
                          len(face), material_ptr], timeout=20000)
            point_offset += 12 * len(face)
            uv_offset += 8 * len(face)
    finally:
        _free_mem(memory)
    return uv_faces


def cs2_mesh_create_box(center: str = "", size: str = "32 32 32",
                        material: str = "materials/tools/toolsnodraw.vmat",
                        name: str = "cs2_box", weld: bool = True,
                        tex_size: float = TEX_DEFAULT_SIZE,
                        doc: str = "") -> str:
    """从零建一个**盒形笔刷**（CMapMesh + 6 个面），挂进世界并记进 Hammer 的 Ctrl+Z 历史。

    链路（2026-09-27 逆向，见 REVERSE_NOTES §16）：

        CreateElement("CMapMesh")       → 元素自带一个**空的** CHammerPolyMesh（el+0x498）
        每个面: sub_180901F40(el, 4 个点(12B/点), 4 个 UV(8B/点), 4, 材质名)
        PostClass sub_180866D70(el, 0)  → AddChild sub_180879170(doc, el, 0)
        weld=True: MergeVerticesWithinDistance + RemoveIsolatedVertices（见 §16.10）

    ⚠ 用 `sub_180901F40` 而**不是**官方的 `sub_180901DF0(el, 宽, 高, 材质)`：后者第 2/3 个
    参数是 float（走 xmm 寄存器），现在 DLL 调用桥已支持浮点（"f:" 前缀）。

    每面各带 4 个顶点（共 24 个）；`weld=True`（默认）会用官方算子把同一位置的顶点焊成
    一个 → **8 顶点 / 6 面**，与 Hammer Block 工具产物一致。焊接归入同一个 Ctrl+Z 步，
    一次 Undo 即删除整个盒子。

    贴图：每面按 Hammer Block 工具的规则写 UV —— 轴取**世界轴**（按面法线主轴选），
    但相位**锚在本网格自己的角点**（`u=(U向坐标−最小值)/k`、`v=(V向坐标−最大值)/k`，
    `k = 0.125×tex_size`，见 `_face_uv_bytes`）—— 建出来的块与 Hammer 手建的块外观一致。

    Args:
        center: 盒心世界坐标 "x y z"（留空 = 世界原点）。
        size: 三个方向的边长 "sx sy sz"（单个数字 = 正方体）。
        material: 材质路径（写进网格的材质表）。
        name: 元素名（显示在 Hammer 里）。
        weld: 是否把 24 个面顶点焊接为 8 个共享顶点（默认 True）。
        tex_size: 贴图像素尺寸（默认 512）。一张贴图平铺 `tex_size×0.125` 世界单位，
             512 → 64 单位；材质贴图不是 512 时改这里（纯色/nodraw 材质无所谓）。
        doc: 目标地图文档：留空 = 清单第一个；数字 = 索引；其余 = 路径子串
             （多文档时**务必指定**，见 `cs2_map_list_docs`）。
    """
    return create_box(center=center, size=size, material=material, name=name, weld=weld, tex_size=tex_size, doc=doc).report


def create_box(center: str = "", size: str = "32 32 32",
                        material: str = "materials/tools/toolsnodraw.vmat",
                        name: str = "cs2_box", weld: bool = True,
                        tex_size: float = TEX_DEFAULT_SIZE,
                        doc: str = "", *, document: int | None = None) -> EditResult:
    """Internal editing operation; returns typed status and any allocated address."""
    el: int | None = None
    try:
        base = _hammer_base()
        ctr = _parse_vec3_arg(center, "center") if str(center).strip() else (0.0, 0.0, 0.0)
        # 单个数字 = 正方体（和 cs2_mesh_scale 一个口径）
        if "," in str(size) or " " in str(size).strip():
            sz = _parse_vec3_arg(size, "size")
        else:
            s = float(str(size).strip())
            sz = (s, s, s)
        if min(sz) <= 0:
            return EditResult(ok=False, report=("ERROR size 必须为正数"), element=el)
        doc = document if document is not None else _map_doc(doc)   # 参数是文档选择器，这里换成 CMapDoc 地址
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")

        ret, err = _call_fn(RVA_DATAMODEL_CREATE_ELEMENT, [
            base + RVA_CDATAMODEL_GLOBAL, "str:CMapMesh", f"str:{name}",
            ENTITY_CREATE_FLAGS, 0], timeout=20000)
        if err:
            return EditResult(ok=False, report=(f"ERROR 建 CMapMesh 元素失败: {err}"), element=el)
        el = _resolve_handle(int(ret, 16) & 0xFFFFFFFF)
        poly = _poly_ready(el)
        if not poly:
            return EditResult(ok=False, report=(f"ERROR 新建的 {el:#x} 没有运行时 CHammerPolyMesh"), element=el)
        _write_mem_chunked(el + ENTITY_OFF_ORIGIN, struct.pack("<3f", *ctr))

        hx, hy, hz = sz[0] * 0.5, sz[1] * 0.5, sz[2] * 0.5
        corners = [(hx * c[0], hy * c[1], hz * c[2]) for c in _BOX_CORNERS]
        local_faces = [[corners[i] for i in face] for face in _BOX_FACES]
        face_uvs = _write_mesh_faces(el, base, local_faces, ctr, material, tex_size)

        _invoke_main(base + RVA_NODE_POST_CLASS, [el, 0], timeout=20000)
        before = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")
        add_ret, add_err = _call_fn(RVA_NODE_ADD_CHILD, [doc, el, 0], timeout=30000)
        after = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")

        weld_note = ""
        if weld:
            # 归入下面同一个 create box 撤销步：记录的是「新增元素」最终态，一次 Undo 整盒删除
            n_b, n_a, merged, werr = _mesh_weld_native(el, poly, 0.01)
            weld_note = (f"  焊接 {n_b} -> {n_a} 顶点（合并 {merged}）\n"
                         if not werr else f"  ⚠ 焊接失败: {werr}\n")

        if weld and not werr:
            _poly_restore_face_uvs(poly, local_faces, face_uvs)

        hist_note = ""
        try:
            undo_hist, _rd = _find_map_histories(doc)
            hist_before = _hist_state(undo_hist)
            _hist_push_step(undo_hist, f"cs2: create box {sz[0]:g}x{sz[1]:g}x{sz[2]:g}")
            _hist_record_object(undo_hist, el, added=True)
            _hist_notify(undo_hist)
            hist_note = (f"  Ctrl+Z 历史: {hist_before} -> {_hist_state(undo_hist)}"
                         f"  记录 node={el + NODE_IFACE_OFFSET:#x}")
        except Exception as e:  # noqa: BLE001
            hist_note = f"  ⚠ 未记入 Ctrl+Z 历史（{type(e).__name__}: {e}）"

        verts = _mesh_live_vertices(el, poly) or []
        try:
            box = struct.unpack("<7f", _read_bytes(el + MESH_OFF_AABB, 28))[1:7]
        except Exception:  # noqa: BLE001
            box = (0.0,) * 6
        parent_hex, _pe = _call_fn(RVA_NODE_GET_PARENT, [el])
        return (
            EditResult(ok=bool(not add_err and not _pe and parent_hex and int(parent_hex, 16) == world and verts), report=(f"已建盒形笔刷 元素={el:#x}  顶点={len(verts)}（{'8 共享顶点' if weld else '每面 4 个，未焊接'}）\n"
            f"  center=({ctr[0]:g}, {ctr[1]:g}, {ctr[2]:g})  size=({sz[0]:g}, {sz[1]:g}, {sz[2]:g})"
            f"  材质={material!r}\n"
            f"  元素缓存 AABB = ({box[0]:.3f}, {box[1]:.3f}, {box[2]:.3f})"
            f" ~ ({box[3]:.3f}, {box[4]:.3f}, {box[5]:.3f})\n"
            f"  材质表 = {_poly_materials(poly)}\n"
            f"{weld_note}"
            f"  AddChild ret={add_ret} err={add_err!r}  world 子节点 {before} -> {after}\n"
            f"  GetParent = {parent_hex}\n"
            + hist_note), element=el)
        )
    except ConnectionError as e:
        return EditResult(ok=False, report=(f"ERROR 管道未连接: {e}"), element=el)
    except Exception as e:  # noqa: BLE001
        return EditResult(ok=False, report=(f"ERROR {type(e).__name__}: {e}"), element=el)


def _prism_faces(dimensions: tuple[float, float, float], sides: int,
                 rotation: float) -> list[list[tuple[float, float, float]]]:
    """Local face loops: outward caps and side quads around a CCW XY ring."""
    half_x, half_y, half_z = (n * 0.5 for n in dimensions)
    phase = math.radians(rotation)
    ring = [(half_x * math.cos(phase + 2 * math.pi * i / sides),
             half_y * math.sin(phase + 2 * math.pi * i / sides))
            for i in range(sides)]
    lower = [(x, y, -half_z) for x, y in ring]
    upper = [(x, y, half_z) for x, y in ring]
    faces = [list(reversed(lower)), upper]
    for i in range(sides):
        following = (i + 1) % sides
        faces.append([lower[i], lower[following], upper[following], upper[i]])
    return faces


def cs2_mesh_create_prism(center: str = "", size: str = "64 64 64",
                          sides: int = 16, rotation: float = 0.0,
                          material: str = "materials/tools/toolsnodraw.vmat",
                          name: str = "cs2_prism", weld: bool = True,
                          tex_size: float = TEX_DEFAULT_SIZE, doc: str = "") -> str:
    """创建竖直棱柱笔刷并挂入地图。3 边为三角棱柱，边数较多时近似圆柱。

    size 指 X/Y 直径和 Z 高度；center 为世界中心，rotation 是绕 Z 轴的角度。
    sides 限 3–64；weld 将端盖和侧面的重复顶点焊成共享顶点。
    会记录一个原生 Ctrl+Z 步。多地图时通过 doc 指定目标文档。
    """
    return create_prism(center=center, size=size, sides=sides, rotation=rotation,
                        material=material, name=name, weld=weld,
                        tex_size=tex_size, doc=doc).report


def create_prism(center: str = "", size: str = "64 64 64",
                 sides: int = 16, rotation: float = 0.0,
                 material: str = "materials/tools/toolsnodraw.vmat",
                 name: str = "cs2_prism", weld: bool = True,
                 tex_size: float = TEX_DEFAULT_SIZE, doc: str = "",
                 *, document: int | None = None) -> EditResult:
    """Return a typed result so a later entity workflow can compose this operation."""
    element: int | None = None
    try:
        ctr = _parse_vec3_arg(center, "center") if str(center).strip() else (0.0, 0.0, 0.0)
        dimensions = (size.strip() + ' ') * 3 if len(size.split()) == 1 else size
        dimensions = _parse_vec3_arg(dimensions, "size")
        if not all(math.isfinite(x) for x in (*ctr, *dimensions, rotation, tex_size)):
            raise ValueError('center、size、rotation 和 tex_size 必须是有限数值')
        if min(dimensions) <= 0 or tex_size <= 0:
            raise ValueError('size 和 tex_size 必须大于 0')
        if isinstance(sides, bool) or not isinstance(sides, int) or not 3 <= sides <= 64:
            raise ValueError('sides 必须是 3 到 64 的整数')
        if not material.strip() or any('\x00' in value for value in (name, material)):
            raise ValueError('材质不能为空，名称和材质不能包含 NUL')
        faces = _prism_faces(dimensions, sides, rotation)

        base = _hammer_base()
        target = document if document is not None else _map_doc(doc)
        world = _read_int(target + CMAPDOC_WORLD_OFFSET, 'u64')
        reply, error = _call_fn(RVA_DATAMODEL_CREATE_ELEMENT, [
            base + RVA_CDATAMODEL_GLOBAL, 'str:CMapMesh', f'str:{name}',
            ENTITY_CREATE_FLAGS, 0], timeout=20000)
        if error:
            raise RuntimeError('建 CMapMesh 失败: ' + error)
        element = _resolve_handle(int(reply, 16) & 0xFFFFFFFF)
        poly = _poly_ready(element)
        if not poly:
            raise RuntimeError('新元素没有运行时 CHammerPolyMesh')
        _write_mem_chunked(element + ENTITY_OFF_ORIGIN, struct.pack('<3f', *ctr))
        face_uvs = _primitive_uvs(faces, dimensions, 'cylinder', sides, 2, tex_size)
        _write_mesh_faces(element, base, faces, ctr, material, tex_size, face_uvs)
        face_count = _read_int(poly + POLY_OFF_FPOOL_CNT, 'u32')
        if face_count != sides + 2:
            raise RuntimeError(f'面数读回 {face_count}，预期 {sides + 2}')
        _invoke_main(base + RVA_NODE_POST_CLASS, [element, 0], timeout=20000)
        add_reply, add_error = _call_fn(RVA_NODE_ADD_CHILD, [target, element, 0], timeout=30000)
        if add_error:
            raise RuntimeError('挂入地图失败: ' + add_error)
        parent_reply, parent_error = _call_fn(RVA_NODE_GET_PARENT, [element])
        if parent_error or not parent_reply or int(parent_reply, 16) != world:
            raise RuntimeError('挂入后父节点读回不一致')

        note = ''
        if weld:
            before, after, merged, weld_error = _mesh_weld_native(element, poly, 0.01)
            if weld_error:
                raise RuntimeError('顶点焊接失败: ' + weld_error)
            _poly_restore_face_uvs(poly, faces, face_uvs)
            note = f'；焊接 {before}→{after}（合并 {merged}）'
        vertices = _mesh_live_vertices(element, poly) or []
        expected_vertices = sides * (2 if weld else 6)
        if len(vertices) != expected_vertices:
            raise RuntimeError(f'顶点读回 {len(vertices)}，预期 {expected_vertices}')
        bounds, _ = _mesh_world_box(element, poly)
        if bounds is None:
            raise RuntimeError('世界包围盒不可读')
        history, _ = _find_map_histories(target)
        _hist_push_step(history, f'cs2: create prism {sides} sides')
        _hist_record_object(history, element, added=True)
        _hist_notify(history)
        return EditResult(True, f'已建棱柱 mesh={element:#x}，{sides} 边、{face_count} 面、'
                         f'{len(vertices)} 顶点{note}；world AABB={bounds}；'
                         f'材质={material}；已记录 Ctrl+Z', element)
    except Exception as exc:
        return EditResult(False, f'ERROR {type(exc).__name__}: {exc}'
                          + (f'；已创建元素={element:#x}，请检查场景和撤销历史' if element else ''),
                          element)



PrimitiveShape = Literal['block', 'quad', 'cylinder', 'spike', 'sphere']


def _primitive_faces(dimensions, shape: PrimitiveShape, segments: int, rings: int,
                     rotation: float):
    """Local face loops for the five shapes shown by Hammer's Block Tool."""
    hx, hy, hz = (v * 0.5 for v in dimensions)
    phase = math.radians(rotation)
    angles = [phase + 2.0 * math.pi * i / segments for i in range(segments)]
    xy = [(hx * math.cos(a), hy * math.sin(a)) for a in angles]
    if shape == 'quad':
        return [[(-hx, -hy, 0.0), (hx, -hy, 0.0),
                 (hx, hy, 0.0), (-hx, hy, 0.0)]]
    if shape == 'cylinder':
        return _prism_faces(dimensions, segments, rotation)
    if shape == 'spike':
        lower = [(x, y, -hz) for x, y in xy]
        tip = (0.0, 0.0, hz)
        return [list(reversed(lower))] + [
            [lower[i], lower[(i + 1) % segments], tip]
            for i in range(segments)]
    if shape == 'sphere':
        top, bottom = (0.0, 0.0, hz), (0.0, 0.0, -hz)
        latitude = []
        for lat in range(1, rings):
            polar = math.pi * lat / rings
            latitude.append([(hx * math.sin(polar) * math.cos(a),
                              hy * math.sin(polar) * math.sin(a),
                              hz * math.cos(polar)) for a in angles])
        faces = [[top, latitude[0][i], latitude[0][(i + 1) % segments]]
                 for i in range(segments)]
        for upper, lower in zip(latitude, latitude[1:]):
            faces.extend([[upper[i], lower[i], lower[(i + 1) % segments],
                           upper[(i + 1) % segments]]
                          for i in range(segments)])
        faces.extend([[latitude[-1][i], bottom,
                       latitude[-1][(i + 1) % segments]]
                      for i in range(segments)])
        return faces
    raise ValueError('shape 必须是 block、quad、cylinder、spike 或 sphere')


def _primitive_uvs(faces, dimensions, shape: PrimitiveShape,
                   segments: int, rings: int, tex_size: float):
    """Planar caps plus continuous circumference/latitude UVs for curved shapes."""
    lo = tuple(min(p[k] for f in faces for p in f) for k in range(3))
    hi = tuple(max(p[k] for f in faces for p in f) for k in range(3))
    mapped = [[struct.unpack_from('<2f', _face_uv_bytes(face, lo, hi, tex_size),
                                  8 * i) for i in range(len(face))]
              for face in faces]
    k = TEX_DEFAULT_SCALE * tex_size
    if shape in ('cylinder', 'spike'):
        side_start = 2 if shape == 'cylinder' else 1
        ring = [faces[side_start + i][0] for i in range(segments)]
        distances = [0.0]
        for i in range(segments):
            a, b = ring[i], ring[(i + 1) % segments]
            distances.append(distances[-1] + math.dist(a[:2], b[:2]))
        for i in range(segments):
            u0, u1 = distances[i] / k, distances[i + 1] / k
            if shape == 'cylinder':
                mapped[side_start + i] = [(u0, dimensions[2] / k),
                                          (u1, dimensions[2] / k),
                                          (u1, 0.0), (u0, 0.0)]
            else:
                edge = faces[side_start + i]
                mid = ((edge[0][0] + edge[1][0]) * 0.5,
                       (edge[0][1] + edge[1][1]) * 0.5)
                slant = math.hypot(math.hypot(*mid), dimensions[2]) / k
                mapped[side_start + i] = [(u0, slant), (u1, slant),
                                          ((u0 + u1) * 0.5, 0.0)]
    elif shape == 'sphere':
        circumference = 2.0 * math.pi * max(dimensions[0], dimensions[1]) * 0.5 / k
        meridian = math.pi * max(dimensions) * 0.5 / k
        for lat in range(rings):
            for i in range(segments):
                index = lat * segments + i
                u0, u1 = circumference * i / segments, circumference * (i + 1) / segments
                v0, v1 = meridian * lat / rings, meridian * (lat + 1) / rings
                if lat == 0:
                    mapped[index] = [((u0 + u1) * 0.5, v0),
                                     (u0, v1), (u1, v1)]
                elif lat == rings - 1:
                    mapped[index] = [(u0, v0), ((u0 + u1) * 0.5, v1),
                                     (u1, v0)]
                else:
                    mapped[index] = [(u0, v0), (u0, v1),
                                     (u1, v1), (u1, v0)]
    return mapped


def cs2_mesh_create_primitive(shape: PrimitiveShape = 'block',
                              center: str = '', size: str = '64 64 64',
                              segments: int = 16, rings: int = 8,
                              rotation: float = 0.0,
                              material: str = 'materials/tools/toolsnodraw.vmat',
                              name: str = 'cs2_primitive', weld: bool = True,
                              tex_size: float = TEX_DEFAULT_SIZE,
                              doc: str = '') -> str:
    """创建 Hammer Block Tool 的 block / quad / cylinder / spike / sphere 形状。

    quad 是 XY 单面；其他形状是闭合网格。size 为 X/Y/Z 尺寸，
    segments 控制圆周分段（3–64），rings 控制球体纬向分段（2–32）。
    侧面 UV 按周长连续展开，sphere 使用经纬展开；焊接后恢复每角 UV。
    单次 Ctrl+Z 删除整个新网格。
    """
    return create_primitive(shape=shape, center=center, size=size,
                            segments=segments, rings=rings, rotation=rotation,
                            material=material, name=name, weld=weld,
                            tex_size=tex_size, doc=doc).report


def create_primitive(shape: PrimitiveShape = 'block',
                     center: str = '', size: str = '64 64 64',
                     segments: int = 16, rings: int = 8, rotation: float = 0.0,
                     material: str = 'materials/tools/toolsnodraw.vmat',
                     name: str = 'cs2_primitive', weld: bool = True,
                     tex_size: float = TEX_DEFAULT_SIZE, doc: str = '',
                     *, document: int | None = None) -> EditResult:
    if shape == 'block':
        return create_box(center=center, size=size, material=material, name=name,
                          weld=weld, tex_size=tex_size, doc=doc, document=document)
    element: int | None = None
    try:
        if shape not in ('quad', 'cylinder', 'spike', 'sphere'):
            raise ValueError('shape 必须是 block、quad、cylinder、spike 或 sphere')
        ctr = _parse_vec3_arg(center, 'center') if str(center).strip() else (0.0, 0.0, 0.0)
        raw = str(size).strip().replace(',', ' ').split()
        if len(raw) == 1:
            raw *= 3
        dimensions = _parse_vec3_arg(' '.join(raw), 'size')
        if not all(math.isfinite(v) for v in (*ctr, *dimensions, rotation, tex_size)):
            raise ValueError('center、size、rotation 和 tex_size 必须是有限数值')
        if min(dimensions) <= 0 or tex_size <= 0:
            raise ValueError('size 和 tex_size 必须大于 0')
        if isinstance(segments, bool) or not isinstance(segments, int) or not 3 <= segments <= 64:
            raise ValueError('segments 必须是 3 到 64 的整数')
        if isinstance(rings, bool) or not isinstance(rings, int) or not 2 <= rings <= 32:
            raise ValueError('rings 必须是 2 到 32 的整数')
        if not material.strip() or any('\x00' in value for value in (name, material)):
            raise ValueError('材质不能为空，名称和材质不能包含 NUL')
        faces = _primitive_faces(dimensions, shape, segments, rings, rotation)
        face_uvs = _primitive_uvs(faces, dimensions, shape, segments, rings, tex_size)
        base = _hammer_base()
        target = document if document is not None else _map_doc(doc)
        world = _read_int(target + CMAPDOC_WORLD_OFFSET, 'u64')
        reply, error = _call_fn(RVA_DATAMODEL_CREATE_ELEMENT, [
            base + RVA_CDATAMODEL_GLOBAL, 'str:CMapMesh', f'str:{name}',
            ENTITY_CREATE_FLAGS, 0], timeout=20000)
        if error:
            raise RuntimeError('建 CMapMesh 失败: ' + error)
        element = _resolve_handle(int(reply, 16) & 0xFFFFFFFF)
        poly = _poly_ready(element)
        if not poly:
            raise RuntimeError('新元素没有运行时 CHammerPolyMesh')
        _write_mem_chunked(element + ENTITY_OFF_ORIGIN, struct.pack('<3f', *ctr))
        _write_mesh_faces(element, base, faces, ctr, material, tex_size, face_uvs)
        count = _read_int(poly + POLY_OFF_FPOOL_CNT, 'u32')
        if count != len(faces):
            raise RuntimeError(f'面数读回 {count}，预期 {len(faces)}')
        _invoke_main(base + RVA_NODE_POST_CLASS, [element, 0], timeout=20000)
        _, add_error = _call_fn(RVA_NODE_ADD_CHILD, [target, element, 0], timeout=30000)
        if add_error:
            raise RuntimeError('挂入地图失败: ' + add_error)
        parent_reply, parent_error = _call_fn(RVA_NODE_GET_PARENT, [element])
        if parent_error or not parent_reply or int(parent_reply, 16) != world:
            raise RuntimeError('挂入后父节点读回不一致')
        if weld:
            _, _, _, weld_error = _mesh_weld_native(element, poly, 0.01)
            if weld_error:
                raise RuntimeError('顶点焊接失败: ' + weld_error)
            _poly_restore_face_uvs(poly, faces, face_uvs)
        vertices = _mesh_live_vertices(element, poly) or []
        expected = len(set(point for face in faces for point in face)) if weld else sum(map(len, faces))
        if len(vertices) != expected:
            raise RuntimeError(f'顶点读回 {len(vertices)}，预期 {expected}')
        history, _ = _find_map_histories(target)
        _hist_push_step(history, f'cs2: create {shape}')
        _hist_record_object(history, element, added=True)
        _hist_notify(history)
        return EditResult(True, f'已建 {shape} mesh={element:#x}，{count} 面、'
                          f'{len(vertices)} 顶点；材质={material}；已记录 Ctrl+Z', element)
    except Exception as exc:
        return EditResult(False, f'ERROR {type(exc).__name__}: {exc}'
                          + (f'；已创建元素={element:#x}，请检查场景和撤销历史' if element else ''),
                          element)

def _arch_outline(width: float, height: float, opening: float,
                  opening_height: float, segments: int) -> list[tuple[float, float]]:
    """拱门在 XZ 截面（x=宽向, z=竖直）上的**简单凹多边形**轮廓（CCW），门洞从地面切入。

    外轮廓 = width×height 矩形；门洞宽 opening（半圆半径 r=opening/2），直墙高
    opening_height-r，拱顶半圆由 segments 段折线近似。

    ⚠ `opening_height` 必须**严格小于** height：否则拱顶顶点与该矩形顶边相切，多边形退化成
    非简单多边形（三角化会出现零面积片、Hammer 拒收）。
    """
    half_out, r = width * 0.5, opening * 0.5
    side_h = opening_height - r
    pts: list[tuple[float, float]] = [
        (-half_out, 0.0),       # 外墙左下角
        (-r, 0.0),              # 门洞左内边（地面）
        (-r, side_h),           # 左墙顶 = 半圆起点(θ=π)
    ]
    for k in range(1, segments + 1):        # 半圆 θ: π → 0，末点 = (r, side_h)
        t = math.pi * (1.0 - k / segments)
        pts.append((r * math.cos(t), side_h + r * math.sin(t)))
    pts += [
        (r, 0.0),               # 门洞右内边落地
        (half_out, 0.0),        # 外墙右下角
        (half_out, height),     # 右上
        (-half_out, height),    # 左上（闭合回外墙左下）
    ]
    return pts


def cs2_mesh_create_arch(center: str = "", width: float = 160.0, height: float = 160.0,
                         thickness: float = 16.0, opening: float = 96.0,
                         opening_height: float = 0.0, segments: int = 12,
                         material: str = "materials/tools/toolsnodraw.vmat",
                         name: str = "cs2_arch", weld: bool = True,
                         tex_size: float = TEX_DEFAULT_SIZE,
                         doc: str = "") -> str:
    """建一个**拱门笔刷**（凹多边形截面沿厚度拉伸：矩形墙 + 半圆拱顶门洞），挂进世界并记历史。

    构造方式：XZ 截面上画一个 U 形凹多边形（`_arch_outline`），沿 y 向拉伸 thickness ——
    前/后端面各一个 n 点**凹多边形面**（建面算子 `CreateFaceLocalFromPoints` 点数直接透传、
    凹面同样接受），每条截面边（含拱顶半圆的 segments 段折线）生成一个连接前后的四边形
    条带 → 共 n+2 个面、2n 个顶点；最后走官方焊接算子合并共享顶点 → 收敛到 n 个顶点。

    ⚠ `opening_height` 必须**严格小于** height：否则拱顶顶点与矩形顶边相切，截面退化成
    非简单多边形（建面会静默失败 / 焊接无法收敛）。

    几何参数（全部世界单位）：

        外墙：宽 width、总高 height、进深 thickness（y 向）
        门洞：宽 opening（半圆直径 = opening），地面到拱顶高 opening_height
              （默认 0 = 自动取 height×0.9，顶部留出拱冠厚度）

    Args:
        center: 拱门底平面中心 "x y z"（截面 z=0 落在此高度；留空 = 世界原点）。
        width: 外墙总宽（默认 160）。
        height: 外墙总高（默认 160）。
        thickness: 墙厚/进深（默认 16）。
        opening: 门洞宽（半圆直径，默认 96；须 < width）。
        opening_height: 门洞地面到拱顶高（默认 0 = height×0.9；须 ≥ opening/2 且 < height）。
        segments: 拱顶半圆分段数（默认 12，越大越圆滑、面越多）。
        material: 材质路径。
        name: 元素名。
        weld: 是否焊接共享顶点（默认 True）。
        tex_size: 贴图像素尺寸（默认 512）；每面按世界对齐投影写 UV，见 `cs2_mesh_create_box`。
        doc: 目标地图文档：留空 = 清单第一个；数字 = 索引；其余 = 路径子串
             （多文档时**务必指定**，见 `cs2_map_list_docs`）。
    """
    base = _hammer_base()
    try:
        if opening >= width:
            return "ERROR opening 必须 < width（门洞要比外墙窄）"
        r = opening * 0.5
        oh = float(opening_height) if opening_height else height * 0.9
        if r > oh:
            return f"ERROR opening/2 ({r:g}) 不能大于 opening_height ({oh:g})（半圆放不下）"
        if oh >= height:
            return (f"ERROR opening_height ({oh:g}) 必须 < height ({height:g})"
                    f"（否则拱顶与墙顶相切，截面退化为非简单多边形）")
        if segments < 3:
            return "ERROR segments 至少 3"
        ctr = _parse_vec3_arg(center, "center") if str(center).strip() else (0.0, 0.0, 0.0)
        cx, cy, cz = ctr
        # ⚠ 顶点写**本地坐标**，元素 origin 设成 ctr（渲染时相加）—— 和 cs2_mesh_create_box 一致。
        #   早期版本把 ctr 加进了顶点、又设了 origin，导致位置被叠加两次（拱门跑偏一倍）。
        yf, yb = -thickness * 0.5, thickness * 0.5
        outline = _arch_outline(width, height, opening, oh, segments)
        n = len(outline)

        # 面表：前/后端面各一个 n 点凹多边形（建面算子点数直接透传，**凹面同样接受**，
        # 实测 19 点 U 形面可正常建立），每条轮廓边一个四边形条带 → 共 n+2 个面。
        # 绕序：outline 为 (x,z) 平面 CCW → 外法线 -y（前端面 yf 朝外）；后端面反向 → +y。
        faces: list[list[tuple[float, float, float]]] = [
            [(x, yf, z) for x, z in outline],
            [(x, yb, z) for x, z in reversed(outline)],
        ]
        for i in range(n):
            xi, zi = outline[i]
            xj, zj = outline[(i + 1) % n]
            fi = (xi, yf, zi)
            bi = (xi, yb, zi)
            bj = (xj, yb, zj)
            fj = (xj, yf, zj)
            faces.append([fi, bi, bj, fj])    # 条带绕序 → 法线统一朝截面外侧

        doc = _map_doc(doc)   # 参数是文档选择器，这里换成 CMapDoc 地址
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
        ret, err = _call_fn(RVA_DATAMODEL_CREATE_ELEMENT, [
            base + RVA_CDATAMODEL_GLOBAL, "str:CMapMesh", f"str:{name}",
            ENTITY_CREATE_FLAGS, 0], timeout=20000)
        if err:
            return f"ERROR 建 CMapMesh 元素失败: {err}"
        el = _resolve_handle(int(ret, 16) & 0xFFFFFFFF)
        poly = _poly_ready(el)
        if not poly:
            return f"ERROR 新建的 {el:#x} 没有运行时 CHammerPolyMesh"
        _write_mem_chunked(el + ENTITY_OFF_ORIGIN, struct.pack("<3f", *ctr))

        face_uvs = _write_mesh_faces(el, base, faces, ctr, material, tex_size)

        _invoke_main(base + RVA_NODE_POST_CLASS, [el, 0], timeout=20000)
        before = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")
        add_ret, add_err = _call_fn(RVA_NODE_ADD_CHILD, [doc, el, 0], timeout=30000)
        after = _read_int(world + NODE_OFF_CHILD_COUNT, "u32")

        weld_note = ""
        if weld:
            n_b, n_a, merged, werr = _mesh_weld_native(el, poly, 0.01)
            if not werr:
                _poly_restore_face_uvs(poly, faces, face_uvs)
            weld_note = (f"  焊接 {n_b} -> {n_a} 顶点（合并 {merged}）\n"
                         if not werr else f"  ⚠ 焊接失败: {werr}\n")

        hist_note = ""
        try:
            undo_hist, _rd = _find_map_histories(doc)
            hist_before = _hist_state(undo_hist)
            _hist_push_step(undo_hist, f"cs2: create arch {width:g}x{height:g}")
            _hist_record_object(undo_hist, el, added=True)
            _hist_notify(undo_hist)
            hist_note = f"  Ctrl+Z 历史: {hist_before} -> {_hist_state(undo_hist)}"
        except Exception as e:  # noqa: BLE001
            hist_note = f"  ⚠ 未记入 Ctrl+Z 历史（{type(e).__name__}: {e}）"

        verts = _mesh_live_vertices(el, poly) or []
        return (
            f"已建拱门笔刷 元素={el:#x}  面={len(faces)}（{segments} 段拱顶）  顶点={len(verts)}\n"
            f"  外墙 {width:g} 宽 × {height:g} 高 × {thickness:g} 厚；门洞宽 {opening:g}"
            f" 高 {oh:g}（直墙高 {oh - r:g}）\n"
            f"  center=({cx:g}, {cy:g}, {cz:g})\n"
            f"  材质表 = {_poly_materials(poly)}\n"
            f"{weld_note}"
            f"  AddChild ret={add_ret} err={add_err!r}  world 子节点 {before} -> {after}\n"
            + hist_note
        )
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"


def cs2_mesh_list(limit: int = 100, doc: str = "") -> str:
    """列出地图里的 CMapMesh（Hammer 手绘网格 / 贴花 overlay）。

    走**世界树**（`_walk_elements`）按主虚表筛 `CMapMesh`（RVA 0x176B8E0）。
    旧版走 `_enum_elements`（元素表），会被它的 8192 截断坑到 —— ze_surf_easy
    实测只报 338 个，实际有 4124 个。走树只访问场景内元素且 vtable 顺带就有。
    坐标同样读 `+0xA0`（CMapMesh 也派生自 MapNode）。

    Args:
        limit: 最多返回多少条。
        doc: 目标地图文档（多文档**务必指定**）：留空 = 清单第一个；数字 = 索引；
             其余 = 路径子串。见 `cs2_map_list_docs`。
    """
    try:
        base = _hammer_base()
        vt_mesh = base + RVA_CMAPMESH_VTABLE
        doc = _map_doc(doc)
        world = _read_int(doc + CMAPDOC_WORLD_OFFSET, "u64")
        if not world:
            return "ERROR CMapDoc 里没有 CMapWorld（地图可能还没加载完）"
        table, cap = _dm_table()
        handle_of = _dm_handle_map(table, cap)
        rows = [(handle_of.get(el, -1), el)
                for el, vt in _walk_elements(world, table, cap) if vt == vt_mesh]
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"

    if not rows:
        return "地图里没有 CMapMesh（该图没有手绘网格 / 贴花）"
    lines = [f"CMapMesh 数: {len(rows)}"]
    for h, el in rows[:limit]:
        try:
            origin = _read_vec3(el + ENTITY_OFF_ORIGIN)
            origin_s = "(%.1f, %.1f, %.1f)" % origin
        except Exception:  # noqa: BLE001
            origin_s = "<读取失败>"
        # 运行时几何容器：CMapMesh+0x498 是内嵌 CHammerPolyMesh 的 vptr，
        # +0x560 才是指向该对象的实体指针
        poly_s = "-"
        try:
            p = _read_int(el + MESH_OFF_POLYMESH_BACKPTR, "u64")
            if p and _read_int(p, "u64") == base + RVA_CHAMMERPOLYMESH_VTABLE:
                poly_s = f"{p:#x}"
        except Exception:  # noqa: BLE001
            pass
        # 存档用 DMX 引用（编辑期通常无效）
        dmx = _dm_attr_element(el, MESH_ATTR_DATA)
        dmx_s = f"{dmx:#x}" if dmx else "INVALID(编辑期未生成)"
        lines.append(f"  handle={h:<5} mesh={el:#x}  origin={origin_s}")
        lines.append(f"        runtimePolyMesh(CHammerPolyMesh)={poly_s}   meshData(DMX)={dmx_s}")
    return "\n".join(lines)


def cs2_mesh_get_geometry(mesh: str, max_faces: int = 16) -> str:
    """读 CMapMesh 的几何：顶点坐标 / 面顶点环 / 世界包围盒。

    编辑期 Hammer **不用** CDmePolygonMesh 存几何，真正在内存里的是
    `CMapMesh+0x498` 内嵌的 CHammerPolyMesh（半边缘 DCEL）。本工具优先直接读它
    （布局 2026-09-27 实证，见 REVERSE_NOTES.md §13）：
        poly+0x18 顶点池(32B/条)   {count@+0, ptr@+8}
        poly+0x50 半边池(80B/条)：+0=起点顶点 handle，+0x20=下一条半边 handle
        poly+0x88 面池(32B/条)：+0=首条半边 handle（低 22 位为索引）
        poly+0x30/0x68/0xA0 三张 handle->槽位 映射表（24B/条，句柄在 +8）
        poly+0x8D8 数据通道数组（24B/通道，ch0 通常是 position，12B/顶点）
        顶点记录 +0x10 = 位置通道数据下标；世界坐标 = 位置 + CMapMesh+0xA0(origin)
    面/半边属性同样读运行时结构（见 REVERSE_NOTES §13.8）：
        poly+0x1110 「密集序 -> 半边 handle」映射；texcoord/normal/tangent 按密集序排列
        poly+0x3118/0x3300/0x3318 每面 textureScale / textureAxisU / textureAxisV
        poly+0x33B8 每面 materialindex，索引 poly+0x3448 的 CUtlVector<CUtlString> 材料名表
    meshData 有效时（载入/导出场景）仍走 CDmePolygonMesh 分支。

    Args:
        mesh: CMapMesh 元素地址（cs2_mesh_list 给出）。
        max_faces: 最多输出多少个面的顶点环。
    """
    def _stream(da: int, semantic: str) -> tuple[int, int]:
        """在 DataArray 里找 semanticName==semantic 的流 -> (流元素, 分量数)。"""
        if not da:
            return 0, 0
        for h in _dm_array_handles(da, MESH_ATTR_STREAMS):
            st = _resolve_handle(h)
            if not st:
                continue
            a = _dm_find_attr(st, MESH_STREAM_ATTR_SEMANTIC)
            if a and _dm_attr_value(a) == semantic:
                return st, MESH_STREAM_COMPONENTS.get(semantic, 0)
        return 0, 0

    try:
        mesh_el = _parse_addr(mesh)
        poly = _dm_attr_element(mesh_el, MESH_ATTR_DATA)
        if not poly:
            return _mesh_geometry_runtime(mesh_el, max_faces)

        materials = _dm_array_strings(poly, MESH_ATTR_MATERIALS)
        vda = _dm_attr_element(poly, MESH_ATTR_VERTEX_DATA)
        fvda = _dm_attr_element(poly, MESH_ATTR_FACE_VERTEX_DATA)
        fda = _dm_attr_element(poly, MESH_ATTR_FACE_DATA)

        pos_st, pos_c = _stream(vda, "position")
        uv_st, uv_c = _stream(fvda, "texcoord")
        nrm_st, _ = _stream(fvda, "normal")
        mat_st, _ = _stream(fda, "materialindex")

        positions = _dm_array_numbers(pos_st, MESH_STREAM_ATTR_DATA, pos_c) if pos_st else []
        uvs = _dm_array_numbers(uv_st, MESH_STREAM_ATTR_DATA, uv_c) if uv_st else []
        normals = _dm_array_numbers(nrm_st, MESH_STREAM_ATTR_DATA, 3) if nrm_st else []
        mat_idx = _dm_array_numbers(mat_st, MESH_STREAM_ATTR_DATA, 1) if mat_st else []

        face_edge = _dm_array_numbers(poly, MESH_ATTR_FACE_EDGE_INDICES, 1)
        edge_next = _dm_array_numbers(poly, MESH_ATTR_EDGE_NEXT_INDICES, 1)
        edge_vert = _dm_array_numbers(poly, "edgeVertexIndices", 1)
        edge_vdata = _dm_array_numbers(poly, MESH_ATTR_EDGE_VERTEX_DATA_INDICES, 1)
        vert_data_idx = _dm_array_numbers(poly, "vertexDataIndices", 1)

        def v_pos(vertex_index: int):
            si = vert_data_idx[vertex_index] if vertex_index < len(vert_data_idx) else vertex_index
            o = si * pos_c
            if o + pos_c > len(positions):
                return None
            return tuple(positions[o:o + pos_c])

        def v_uv(half_edge: int):
            si = edge_vdata[half_edge] if half_edge < len(edge_vdata) else half_edge
            o = si * uv_c
            if not uv_c or o + uv_c > len(uvs):
                return None
            return tuple(uvs[o:o + uv_c])

        lines = [
            f"CMapMesh {mesh_el:#x}  meshData(CDmePolygonMesh)={poly:#x}",
            f"  顶点(position) {len(positions) // pos_c if pos_c else 0}   "
            f"半边 {len(edge_vert)}   face {len(face_edge)}   材质 {len(materials)}",
            f"  materials = {materials[:12]}",
            f"  materialindex = {mat_idx[:16]}",
        ]

        for f in range(min(len(face_edge), max_faces)):
            start = face_edge[f]
            loop: list[int] = []
            e = start
            for _ in range(256):
                loop.append(e)
                e = edge_next[e] if e < len(edge_next) else start
                if e == start or len(loop) > 255:
                    break
            verts = [edge_vert[e] if e < len(edge_vert) else -1 for e in loop]
            pts = [v_pos(v) for v in verts]
            uv = [v_uv(e) for e in loop]
            mat = materials[mat_idx[f]] if f < len(mat_idx) and 0 <= mat_idx[f] < len(materials) else "?"
            lines.append(f"  face[{f}] mat={mat!r} verts={verts}")
            for i in range(1, max(len(pts) - 1, 1)):
                tri = [pts[0], pts[i], pts[i + 1]] if len(pts) > i + 1 else []
                if tri and all(t is not None for t in tri):
                    lines.append("      tri " + "  ".join(
                        "(%.3f, %.3f, %.3f)" % t for t in tri))
            if uv and uv[0] is not None:
                lines.append("      uv " + "  ".join(
                    ("(%.4f, %.4f)" % t) if t else "<->" for t in uv))
    except ConnectionError as e:
        return f"ERROR 管道未连接: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR {type(e).__name__}: {e}"
    return "\n".join(lines)
