# -*- coding: utf-8 -*-
"""一键恢复开发环境：拉起 cs2 → 注入新 DLL → 点 Hammer 图标 → 打开指定 .vmap。

用法：
    python bringup.py                      # 不开地图
    python bringup.py <vmap 全路径>        # 打开地图

流程依据 VM_DEV.md §3 / PROGRESS.md §8.1：
  Asset Browser 起来后注入 DLL（此时 hammer.dll 还没加载，DLL 内的
  CreateInterface 解析不了 ToolSystem2_001），点 Hammer 图标后再调一次
  `initialize` 才能拿到 CHammerApp —— 所以注入时机在 AB 阶段即可，
  但注入的必须是**最新构建**（build_vs18）。
"""
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inject_dll as INJ  # noqa: E402


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def cs2_pids():
    """只返回**活着的** cs2（僵尸进程照样能被 tasklist 列出，但杀不掉也用不了）。"""
    return [p for p in INJ.list_candidate_pids() if not INJ._is_zombie(p)]


def _get_cpu(pid):
    """进程累计 CPU 秒数（取不到返回 None）。"""
    import subprocess as _sp
    out = _sp.run(["powershell", "-NoProfile", "-Command",
                   f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).CPU"],
                  capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return None


def cs2_title(pid):
    import ctypes
    from ctypes import wintypes as w
    u = ctypes.windll.user32
    u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    res = []

    P = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

    def cb(h, l):
        p = w.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(h, t, 256)
            res.append(t.value)
        return True

    u.EnumWindows(P(cb), 0)
    return res


def main():
    map_path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ""

    # 1) 杀掉旧 cs2（否则旧 DLL 仍占着同名管道）
    old = cs2_pids()
    if old:
        print("杀掉旧 cs2:", old)
        for p in old:
            run(["taskkill", "/f", "/pid", str(p)])
        for _ in range(30):
            time.sleep(1)
            if not cs2_pids():
                break
    if cs2_pids():
        print("旧 cs2 未退出")
        return 1

    # 2) 拉起 Hammer（必须投递到 Session 1）
    print("启动 Hammer ...")
    run(["schtasks", "/run", "/tn", "HammerLaunch"])

    pid = 0
    for _ in range(40):
        time.sleep(3)
        pids = cs2_pids()
        if not pids:
            continue
        pid = pids[0]
        titles = cs2_title(pid)
        if any("Asset Browser" in t for t in titles):
            print(f"Asset Browser 就绪 pid={pid}")
            break
    if not pid:
        print("cs2 未起来")
        return 1

    # 2.5) 等 AB 从启动/加载的高负载里退出来（实测刚起来时主线程在狂跑渲染 +
    #      资源加载，此时做 Qt 主线程调用容易撞上正在销毁的 widget）
    import ctypes as _ct
    for _ in range(20):
        p1 = _get_cpu(pid)
        time.sleep(3)
        p2 = _get_cpu(pid)
        if p1 is not None and p2 is not None and (p2 - p1) < 2.0:
            print(f"AB 已空闲 (3s CPU delta={p2 - p1:.1f}s)")
            break
    else:
        print("AB 一直很忙，继续")

    # 3) 注入最新 DLL
    r = run([PY, os.path.join(REPO, "injector", "inject_dll.py"), str(pid)])
    if "INJECTION SUCCESS" not in r.stdout:
        print(r.stdout[-800:], r.stderr[-400:])
        return 1
    print("DLL 注入成功")

    # 4) 点 Hammer 图标（用安全版 qt_button.py：按 vtable 缓存类名，
    #    绝不像 vm_pipe qt-buttons 那样对每个 widget 调一次 inherits）
    r = run([PY, os.path.join(REPO, "injector", "qt_button.py"), "find", "hammer"])
    addr = 0
    for line in r.stdout.split("\n"):
        if "tip=" in line and "Hammer" in line and "0x" in line:
            addr = int(line.split("0x")[1].split()[0], 16)
            break
    if not addr:
        print("找不到 Hammer 按钮：", r.stdout[-400:])
        return 1
    r = run([PY, os.path.join(REPO, "injector", "qt_button.py"), "click", hex(addr)])
    print(f"已点击 Hammer 图标 ({addr:#x}) -> {r.stdout.strip()}")

    # 5) 等 hammer.dll 加载
    for _ in range(30):
        time.sleep(3)
        r = run([PY, os.path.join(REPO, "injector", "vm_pipe.py"), "module", "hammer.dll"])
        if "hammer.dll" in r.stdout and "base=" in r.stdout:
            print(r.stdout.strip())
            break
    else:
        print("hammer.dll 未加载")
        return 1

    # 6) 重新 initialize（此时才能解析 ToolSystem2_001）
    r = run([PY, "-c",
             "import sys; sys.path.insert(0, r'%s\\mcp_server');"
             "import cs2_mcp_server as S;"
             "print(S._get_pipe().call('initialize', {}).get('result'))" % REPO])
    print("initialize:", r.stdout.strip() or r.stderr.strip())

    if not map_path:
        return 0

    # 7) 打开地图
    print("打开地图:", map_path)
    r = run([PY, os.path.join(REPO, "injector", "open_map.py"), map_path])
    print(r.stdout.strip()[-600:])
    for _ in range(20):
        time.sleep(3)
        r = run([PY, os.path.join(REPO, "injector", "vm_pipe.py"), "map-info"])
        if "CMapDoc" in r.stdout:
            print(r.stdout.strip())
            return 0
    print("地图未打开：", r.stdout.strip())
    return 1


if __name__ == "__main__":
    sys.exit(main())
