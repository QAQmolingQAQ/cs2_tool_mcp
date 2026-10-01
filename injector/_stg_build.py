#!/usr/bin/env python3
"""把 STG 需要的实体批量建进 ze_surf_nannoimi 地图（走 cs2_entity_create 的底层链路）。

设计成可重复执行：
  * 先一次性扫描场景树建「名字 -> 元素」索引（比 cs2_entity_list 快得多）；
  * 已存在的名字不重复建（如 boss 那个未命名 func_physbox 就复用，只补 targetname）。

用法： python injector/_stg_build.py [--dry]
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))

import cs2_mcp_server as srv  # noqa: E402

# 实测几何（见 stg.js 顶部注释）；2026-09-29 作者把整组 mover 沿 -Y 挪了 191，
# 这里跟着更新——注意 stg.js 本身不依赖这些数值（它开波时从 hitbox_show 实时标定），
# 这几个常量只决定模板/粒子实体在 Hammer 里摆在哪儿。
HITBOX_START = (-3874.0, -14021.0, 10667.0)      # hitbox_show 起始（玩区左下角）
PLAY_W, PLAY_H = 1950.0, 2954.0                  # Y(横) x Z(竖)
PLANE_DEPTH_X = -3874.0
FUMO = "models/qaqmolingqaq/fumo_kijinseija/fumo_kijinseija.vmdl"


def plane_to_world(u: float, v: float) -> tuple[float, float, float]:
    """平面坐标（以屏幕中心为原点，见 stg.js 的 planeCenter）-> 世界坐标"""
    return (PLANE_DEPTH_X,
            HITBOX_START[1] + PLAY_W / 2 + u,
            HITBOX_START[2] + PLAY_H / 2 + v)


# 平面坐标下的关键位置
BOSS_UV = (0.0, 1150.0)          # 与 stg.js 的 bossOrigin 一致

# 粒子：必须是**基础游戏自带**的路径，否则地图单独挂载时解析不到。
# 这两条都能在 game/csgo/pak01_dir.vpk 的目录表里查到（particles/explosions_fx、
# particles/weapons/cs_weapon_fx），也和 ze_surf_easy 里地图实际引用的同类路径一致。
FX_HIT = "particles/explosions_fx/explosion_hegrenade_interior.vpcf"          # 命中爆点
FX_MUZZLE = "particles/weapons/cs_weapon_fx/weapon_muzzle_flash_huntingrifle_main_fallback.vpcf"  # 发射火花

# 待建清单： (targetname, classname, {(键值): 值}, 平面坐标 u/v 或 None)
PLAN = [
    ("stg_script", "point_script",
     {"cs_script": "maps/scripts/stg.vjs"}, (-700.0, -1500.0)),
    ("danmu_bullet", "prop_dynamic",
     {"model": FUMO, "solid": "0"}, BOSS_UV),
    ("danmu_template", "point_template",
     {"Template01": "danmu_bullet", "spawnflags": "0"}, BOSS_UV),
    ("danmu_hit_fx", "info_particle_system",
     {"effect_name": FX_HIT, "start_active": "0"}, (-300.0, 1100.0)),
    ("danmu_hit_fx_template", "point_template",
     {"Template01": "danmu_hit_fx", "spawnflags": "0"}, (-300.0, 1100.0)),
    ("danmu_muzzle_fx", "info_particle_system",
     {"effect_name": FX_MUZZLE, "start_active": "0"}, (300.0, 1100.0)),
    ("danmu_muzzle_fx_template", "point_template",
     {"Template01": "danmu_muzzle_fx", "spawnflags": "0"}, (300.0, 1100.0)),
]
# prop_dynamic 的 scale：fumo 模型原生高 ~28 单位（物理球半径 8），1.0 就是天然大小，
# 换算到 2954 高的玩区大约占屏高 1%，刚好是弹幕该有的尺寸。
SCALE_BULLET = "1 1 1"


def build_name_index() -> dict[str, tuple[int, str]]:
    """扫描场景树 -> {targetname: (element, classname)}（只读，约 20s）"""
    base = srv._hammer_base()
    ent_vt = base + srv.RVA_CMAPENTITY_VTABLE
    world = srv._read_int(srv._map_doc() + srv.CMAPDOC_WORLD_OFFSET, "u64")
    cache: dict[int, str] = {}
    idx: dict[str, tuple[int, str]] = {}
    for el, vt in srv._walk_elements(world):
        if vt != ent_vt:
            continue
        try:
            props = srv._entity_class_props(el)
            if not props:
                continue
            attr = srv._read_int(props + srv.ELEMENT_OFF_ATTR_HEAD, "u64")
            kv: dict[str, str] = {}
            guard = 0
            while attr and guard < 512 and len(kv) < 2:
                buf = srv._read_bytes(attr, 0x28)
                nxt = int.from_bytes(buf[0:8], "little")
                val = int.from_bytes(buf[8:16], "little")
                nptr = int.from_bytes(buf[0x20:0x28], "little")
                nm = cache.get(nptr)
                if nm is None:
                    nm = srv._read_string(nptr, 96) if nptr else ""
                    cache[nptr] = nm
                if nm in ("targetname", "classname") and nm not in kv and val:
                    cp = srv._read_int(val, "u64")
                    kv[nm] = srv._read_string(cp, 256) if cp else ""
                attr = nxt
                guard += 1
            tn = kv.get("targetname", "")
            if tn:
                idx[tn] = (el, kv.get("classname", ""))
        except Exception:  # noqa: BLE001
            continue
    return idx


def parse_element(out: str) -> int:
    m = re.search(r"element = (0x[0-9a-fA-F]+)", out)
    return int(m.group(1), 16) if m else 0


def main() -> int:
    dry = "--dry" in sys.argv
    print("扫描场景树建名字索引 …")
    idx = build_name_index()
    print(f"  索引 {len(idx)} 个有名字的实体")
    for n in [n for n, _, _, _ in PLAN]:
        print(f"    {n:<26} {'已存在 -> ' + idx[n][1] if n in idx else '缺失，需要新建'}")

    # boss = 玩区顶部那个未命名 func_physbox
    if "boss" not in idx:
        base = srv._hammer_base()
        ent_vt = base + srv.RVA_CMAPENTITY_VTABLE
        world = srv._read_int(srv._map_doc() + srv.CMAPDOC_WORLD_OFFSET, "u64")
        for el, vt in srv._walk_elements(world):
            if vt != ent_vt:
                continue
            try:
                props = srv._entity_class_props(el)
                cls = srv._dm_attr_value(srv._dm_find_attr(props, "classname")) if props else None
                if cls != "func_physbox":
                    continue
                tn = srv._dm_attr_value(srv._dm_find_attr(props, "targetname"))
                org = struct.unpack("<3f", srv._read_bytes(el + 0xA0, 12))
                if tn or not (-13900 < org[1] < -11800 and 10600 < org[2] < 13700):
                    continue
                print(f"\n把未命名 func_physbox {el:#x} @({org[0]:.0f},{org[1]:.0f},{org[2]:.0f}) 命名为 boss")
                if not dry:
                    print("   " + srv.cs2_entity_set_attr(hex(el), "targetname", "boss").splitlines()[0])
            except Exception:  # noqa: BLE001
                continue

    if dry:
        print("\n--dry：未做任何写操作")
        return 0

    print("\n建实体 …")
    for name, cls, kvs, uv in PLAN:
        if name in idx:
            el, realcls = idx[name]
            print(f"\n[{name}] 已存在 ({realcls}) {el:#x} -> 只补键值")
        else:
            out = srv.cs2_entity_create(cls, name)
            el = parse_element(out)
            ok = "已挂进世界 ✅" in out
            print(f"\n[{name}] 新建 {cls} -> {el:#x}  挂世界={ok}")
            if not el:
                print("   ❌ 建失败:\n" + out)
                continue
            if not ok:
                print("   ⚠ 未挂进世界:\n" + out)
            real_cls = srv.cs2_entity_get_attr(hex(el), "classname")
            print("   类名读回: " + real_cls.strip())
            try:
                srv._get_pipe().call("call_function", {  # 让新建实体立即置脏（只自身，不碰 world）
                    "address": srv._hammer_addr(srv.RVA_ELEMENT_MARK_DIRTY),
                    "args": [el, 3], "on_main_thread": True, "timeout_ms": 15000})
            except Exception as e:  # noqa: BLE001
                print(f"   (置脏失败 {e})")

        # targetname + 类特有键值
        for k, v in {"targetname": name, **kvs}.items():
            r = srv.cs2_entity_set_attr(hex(el), k, v)
            first = r.splitlines()[0]
            print(f"   set {k} = {v!r:<34} {first[:70]}")

        # 位置 / 缩放
        org = plane_to_world(*uv)
        scale = SCALE_BULLET if name == "danmu_bullet" else ""
        r = srv.cs2_entity_set_transform(hex(el), origin="%.1f %.1f %.1f" % org, scales=scale)
        print("   transform: " + r.splitlines()[1].strip() if len(r.splitlines()) > 1 else "   " + r)

    print("\n完成。用 `python injector/_stg_probe.py` 复核。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
