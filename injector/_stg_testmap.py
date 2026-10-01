#!/usr/bin/env python3
"""在空地图里搭一个**专门测弹幕**的沙盒（默认 doc 1 = untitled_1.vmap）。

搭出来的东西：
  * 一间封闭房间（6 个 CMapMesh 盒子：地/顶/四壁）—— 封闭是必需的，否则编译报 leak；
  * 光照：light_environment + 3 个 light_omni2（键值从真图 ze_surf_nannoimi 里
    **逐字段抄**过来，保证是「能点亮」的那套值，只放大 range / 亮度）；
  * 玩区平面（竖直墙，法线沿 X）：与真图同尺寸 1950(Y) × 2954(Z)，
    左下角 = hitbox_show 起点，所以 stg.js 的 CFG(planeCenter / bounds / bossOrigin)
    **一个字都不用改**；
  * 弹幕全套实体：stg_script / hitbox_show / boss / danmu_bullet / 两个点模板 /
    命中·发射粒子 / danmu_hit_count，外加一个 point_worldtext 实时显示命中数。

用法：
  python injector/_stg_testmap.py --doc 1            # 搭
  python injector/_stg_testmap.py --doc 1 --dry      # 只看要建什么
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))

import cs2_mcp_server as srv  # noqa: E402

DOC = "1"                      # 空图的文档选择器（cs2_map_list_docs 的 index）
FUMO = "models/qaqmolingqaq/fumo_kijinseija/fumo_kijinseija.vmdl"
FLOOR_MAT = "materials/dev/reflectivity_30.vmat"
FX_HIT = "particles/explosions_fx/explosion_hegrenade_interior.vpcf"
FX_MUZZLE = "particles/weapons/cs_weapon_fx/weapon_muzzle_flash_huntingrifle_main_fallback.vpcf"

# ---- 玩区几何（和真图同尺寸，只是把世界原点挪到方便看的位置）----
PLAY_X = 0.0                   # 玩区平面的深度轴（法线沿 X）
PLAY_W, PLAY_H = 1950.0, 2954.0
HITBOX_POS = (PLAY_X, -PLAY_W / 2, 128.0)          # 玩区左下角 = hitbox_show 起点
PLANE_CZ = 128.0 + PLAY_H / 2                       # 玩区中心的 z
BOSS_UV = (0.0, 1150.0)                             # 与 stg.js 的 bossOrigin 一致
BOSS_POS = (PLAY_X, -PLAY_W / 2 + PLAY_W / 2 + BOSS_UV[0], 128.0 + PLAY_H / 2 + BOSS_UV[1])

# ---- 房间（外壳 x[-3200,768] y[-2176,2176] z[-128,4208]，壁厚 128）----
ROOM = [
    ("stgtest_floor", (-1216.0, 0.0, -64.0), (3968.0, 4352.0, 128.0)),
    ("stgtest_ceil", (-1216.0, 0.0, 4144.0), (3968.0, 4352.0, 128.0)),
    ("stgtest_wall_xn", (-3136.0, 0.0, 2040.0), (128.0, 4352.0, 4352.0)),
    ("stgtest_wall_xp", (704.0, 0.0, 2040.0), (128.0, 4352.0, 4352.0)),
    ("stgtest_wall_yn", (-1216.0, -2112.0, 2040.0), (3968.0, 128.0, 4352.0)),
    ("stgtest_wall_yp", (-1216.0, 2112.0, 2040.0), (3968.0, 128.0, 4352.0)),
]

SPAWN_POS = (-3000.0, 0.0, 8.0)          # 离玩区 3000 单位，垂直 FOV 才装得下 2954 高的玩区
LIGHT_ENV_POS = (-1500.0, 0.0, 3900.0)
OMNI_POS = [(200.0, 0.0, 2900.0), (-800.0, 0.0, 3700.0), (-2500.0, 0.0, 3700.0)]

BULLET_POS = (PLAY_X, 0.0, PLANE_CZ)     # 模板从哪儿生成不影响，脚本用 ForceSpawn(origin) 定位


def fmt(v: tuple[float, float, float]) -> str:
    return "%.1f %.1f %.1f" % v


# --------------------------------------------------------------------------- #
# 读真图的键值（用于把能工作的光源配置整套抄过来）
# --------------------------------------------------------------------------- #
def _walk_entities(doc: int):
    """产出 doc 里所有 CMapEntity 元素的地址。"""
    ent_vt = srv._hammer_base() + srv.RVA_CMAPENTITY_VTABLE
    world = srv._read_int(doc + srv.CMAPDOC_WORLD_OFFSET, "u64")
    for el, vt in srv._walk_elements(world):
        if vt == ent_vt:
            yield el


def dump_kvs(props: int, cache: dict[int, str] | None = None) -> dict[str, str]:
    """把 CEditGameClassProps 链上的 keyvalue 全读出来（全是 AT_STRING）。"""
    cache = {} if cache is None else cache
    out: dict[str, str] = {}
    attr = srv._read_int(props + srv.ELEMENT_OFF_ATTR_HEAD, "u64")
    guard = 0
    while attr and guard < 1024:
        buf = srv._read_bytes(attr, 0x28)
        nxt = int.from_bytes(buf[0:8], "little")
        val = int.from_bytes(buf[8:16], "little")
        nptr = int.from_bytes(buf[0x20:0x28], "little")
        nm = cache.get(nptr)
        if nm is None:
            nm = srv._read_string(nptr, 96) if nptr else ""
            cache[nptr] = nm
        if nm and val:
            cp = srv._read_int(val, "u64")
            out[nm] = srv._read_string(cp, 512) if cp else ""
        attr = nxt
        guard += 1
    return out


def find_class_kvs(doc: int, classname: str) -> dict[str, str]:
    """在 doc 里找第一个指定类名的实体，返回它的全部 keyvalue。"""
    cache: dict[int, str] = {}
    for el in _walk_entities(doc):
        props = srv._entity_class_props(el)
        if not props:
            continue
        kvs = dump_kvs(props, cache)
        if kvs.get("classname") == classname:
            return kvs
    return {}


def build_name_index(doc: int) -> dict[str, tuple[int, str]]:
    """doc 里 {targetname: (element, classname)}。"""
    cache: dict[int, str] = {}
    idx: dict[str, tuple[int, str]] = {}
    for el in _walk_entities(doc):
        props = srv._entity_class_props(el)
        if not props:
            continue
        kvs = dump_kvs(props, cache)
        tn = kvs.get("targetname", "")
        if tn:
            idx[tn] = (el, kvs.get("classname", ""))
    return idx


# --------------------------------------------------------------------------- #
def parse_element(out: str) -> int:
    m = re.search(r"element = (0x[0-9a-fA-F]+)", out)
    return int(m.group(1), 16) if m else 0


def create_entity(cls: str, name: str) -> int:
    out = srv.cs2_entity_create(cls, name, DOC)
    el = parse_element(out)
    if not el or "已挂进世界" not in out:
        print("   ❌ 建失败:\n" + out)
        return 0
    return el


def set_kvs(el: int, kvs: dict[str, str]) -> None:
    for k, v in kvs.items():
        r = srv.cs2_entity_set_attr(hex(el), k, v, history=False)
        print(f"     {k} = {v!r:<46} {r.splitlines()[0][:56]}")


def place(el: int, pos=None, angles=None, scales=None) -> None:
    r = srv.cs2_entity_set_transform(
        hex(el), origin=fmt(pos) if pos else "",
        angles=fmt(angles) if angles else "",
        scales=fmt(scales) if scales else "")
    line = [x for x in r.splitlines() if "已生效" in x]
    print("     transform: " + (line[0].strip()[:96] if line else r[:96]))


def main() -> int:
    global DOC
    if "--doc" in sys.argv:
        DOC = sys.argv[sys.argv.index("--doc") + 1]
    dry = "--dry" in sys.argv

    doc0 = srv._map_doc("0")
    doc1 = srv._map_doc(DOC)
    print(f"源图(抄光源键值) doc? = {doc0:#x}   目标图 = {doc1:#x}  (选择器 {DOC!r})")

    print("读真图的光源键值 …")
    kv_env = find_class_kvs(doc0, "light_environment")
    kv_omni = find_class_kvs(doc0, "light_omni2")
    print(f"  light_environment: {len(kv_env)} 项  light_omni2: {len(kv_omni)} 项")
    if not kv_env or not kv_omni:
        print("  ❌ 抄不到光源配置，先确认 doc 0 还是那张真图")
        return 1
    # 抄来的 range/亮度只够照亮一间小屋子，这里放大
    kv_env = dict(kv_env)
    kv_omni = dict(kv_omni)
    kv_omni.update({"range": "3200.0", "brightness_lumens": "40000",
                    "brightness_nits": "40000", "brightness_candelas": "400"})

    idx = build_name_index(doc1)
    print(f"目标图现有 {len(idx)} 个有名字的实体")

    print("\n=== 1) 房间 ===")
    for name, ctr, size in ROOM:
        if dry:
            print(f"  [dry] mesh {name}  center={fmt(ctr)} size={fmt(size)}")
            continue
        r = srv.cs2_mesh_create_box(center=fmt(ctr), size=fmt(size),
                                    material=FLOOR_MAT, name=name, doc=DOC)
        print(f"  {name:<18} {r.splitlines()[0][:90]}")

    PLAN = [
        ("stgtest_spawn_ct", "info_player_counterterrorist", {}, SPAWN_POS, (15.0, 0.0, 0.0), None),
        ("stgtest_spawn_t", "info_player_terrorist", {}, (-2900.0, 256.0, 8.0), (15.0, 0.0, 0.0), None),
        ("stgtest_light_env", "light_environment", kv_env, LIGHT_ENV_POS, (50.0, 315.0, 0.0), None),
        ("stgtest_light_0", "light_omni2", kv_omni, OMNI_POS[0], None, None),
        ("stgtest_light_1", "light_omni2", kv_omni, OMNI_POS[1], None, None),
        ("stgtest_light_2", "light_omni2", kv_omni, OMNI_POS[2], None, None),
        ("stg_script", "point_script", {"cs_script": "maps/scripts/stg.vjs"},
         (-2400.0, 0.0, 16.0), None, None),
        # 玩区两侧的视觉参照：hitbox 与 boss（都是 fumo，靠 scale 区分大小）
        ("hitbox_show", "prop_dynamic", {"model": FUMO, "solid": "0"},
         HITBOX_POS, None, (3.0, 3.0, 3.0)),
        ("boss", "prop_dynamic", {"model": FUMO, "solid": "0"},
         BOSS_POS, None, (20.38, 20.38, 20.38)),
        ("danmu_bullet", "prop_dynamic", {"model": FUMO, "solid": "0"},
         BULLET_POS, None, (3.0, 3.0, 3.0)),
        ("danmu_template", "point_template",
         {"Template01": "danmu_bullet", "spawnflags": "0"}, BULLET_POS, None, None),
        ("danmu_hit_fx", "info_particle_system",
         {"effect_name": FX_HIT, "start_active": "0"}, (PLAY_X, -900.0, PLANE_CZ), None, None),
        ("danmu_hit_fx_template", "point_template",
         {"Template01": "danmu_hit_fx", "spawnflags": "0"}, (PLAY_X, -900.0, PLANE_CZ), None, None),
        ("danmu_muzzle_fx", "info_particle_system",
         {"effect_name": FX_MUZZLE, "start_active": "0"}, (PLAY_X, 900.0, PLANE_CZ), None, None),
        ("danmu_muzzle_fx_template", "point_template",
         {"Template01": "danmu_muzzle_fx", "spawnflags": "0"}, (PLAY_X, 900.0, PLANE_CZ), None, None),
        ("danmu_hit_count", "math_counter", {}, (200.0, -975.0, PLANE_CZ), None, None),
        ("stg_hits_text", "point_worldtext", {"message": "0"},
         (-1000.0, -1700.0, PLANE_CZ), None, None),
    ]

    print("\n=== 2) 实体 ===")
    made: dict[str, int] = {}
    for name, cls, kvs, pos, ang, scl in PLAN:
        if name in idx:
            el, real = idx[name]
            print(f"\n[{name}] 已存在 ({real}) {el:#x} -> 只补键值")
        else:
            if dry:
                print(f"\n[dry] {name:<24} {cls:<24} @{fmt(pos)}")
                continue
            print(f"\n[{name}] 新建 {cls}")
            el = create_entity(cls, name)
            if not el:
                continue
        made[name] = el
        if not dry:
            set_kvs(el, {"targetname": name, **kvs})
            place(el, pos, ang, scl)

    # 命中数显示：math_counter 的 OutValue -> point_worldtext.SetMessage
    if not dry and "danmu_hit_count" in made and "stg_hits_text" in made:
        print("\n=== 3) 命中数显示 IO ===")
        r = srv.cs2_entity_add_io(hex(made["danmu_hit_count"]), "OutValue",
                                  "SetMessage", target="stg_hits_text")
        print("  " + r.splitlines()[0][:100])

    if dry:
        print("\n--dry：未做任何写操作")
        return 0

    print("\n=== 4) 保存 ===")
    print("  " + srv.cs2_map_save(DOC).splitlines()[0][:110])
    print("\n完成。用 `python injector/_stg_probe.py --doc %s --all` 复核。" % DOC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
