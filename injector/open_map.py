# -*- coding: utf-8 -*-
"""触发 Hammer 的 File->&Open 并用 Win32 驱动原生文件对话框打开 .vmap。

用法：
    python open_map.py list                 # 只列出当前 cs2 的顶层窗口
    python open_map.py <vmap 全路径>        # 打开地图（自动填文件名并点“打开”）

背景：QAction::trigger() 在钩子上下文里遇到模态对话框会永不返回（嵌套消息循环），
所以 trigger 走后台进程（只要 10s 超时），我们再从外部用 Win32 把对话框填完。
"""
import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import time

u = ctypes.windll.user32
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
u.SendMessageW.restype = ctypes.c_void_p
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
u.GetDlgItem.restype = w.HWND
u.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
u.GetWindowLongW.restype = ctypes.c_long
u.IsWindow.argtypes = [w.HWND]
u.IsWindow.restype = w.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

REPO = r"c:\cs2_tool_mcp"

sys.path.insert(0, os.path.join(REPO, "mcp_server"))
import cs2_mcp_server as S  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inject_dll as INJ  # noqa: E402


def find_open_action():
    """动态查 File 菜单里的 &Open QAction（每次重启地址都会变，不能硬编码）。"""
    return S._qt_find_menu_action("&Open", menu="File", exclude="Recent")


def cs2_pid():
    """取**活着的** cs2（僵尸进程照样被 tasklist 列出，会让窗口枚举扑空）。"""
    for p in INJ.list_candidate_pids():
        if not INJ._is_zombie(p):
            return p
    return 0


def cs2_hwnd(pid):
    """cs2 主窗口（Hammer）。"""
    found = []

    def cb(h, l):
        p = w.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(h, t, 256)
            c = ctypes.create_unicode_buffer(256)
            u.GetClassNameW(h, c, 256)
            found.append((h, c.value, t.value))
        return True

    u.EnumWindows(WNDENUMPROC(cb), 0)
    for h, c, t in found:
        if c.startswith("Qt") and "Hammer" in t:
            return h
    return 0


def enum_windows(pid):
    res = []

    def cb(h, l):
        p = w.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(h, t, 512)
            c = ctypes.create_unicode_buffer(256)
            u.GetClassNameW(h, c, 256)
            res.append((h, c.value, t.value))
        return True

    u.EnumWindows(WNDENUMPROC(cb), 0)
    return res


def enum_children(h):
    res = []

    def cb(ch, l):
        c = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(ch, c, 256)
        t = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(ch, t, 512)
        cid = u.GetWindowLongW(ch, -12)
        res.append((ch, c.value, cid, t.value))
        return True

    u.EnumChildWindows(h, WNDENUMPROC(cb), 0)
    return res


def find_open_btn(h):
    """在对话框里找 IDOK(1) 且文本含“打开/Open”的按钮。"""
    for ch, cls, cid, txt in enum_children(h):
        if cls != "Button":
            continue
        if cid == 1 or txt.lower().startswith(("open", "打开")):
            return ch
    return 0


def set_filename(h, path):
    """把文件名写进原生文件对话框的“文件名”编辑框（id=1148）。"""
    target = 0
    fallback = 0
    for ch, cls, cid, txt in enum_children(h):
        if cls != "Edit":
            continue
        if cid == 1148:
            target = ch
        elif fallback == 0:
            fallback = ch
    if target == 0:
        target = fallback
    if not target:
        return False
    u.SendMessageW(target, 0x000C, 0, ctypes.c_wchar_p(path))  # WM_SETTEXT
    return True


def submit(dlg, btn):
    """点“打开”：对对话框发 WM_COMMAND(IDOK) 是最可靠的方式。"""
    WM_COMMAND = 0x0111
    u.SendMessageW(dlg, WM_COMMAND, 1, btn)        # wParam=IDOK(1)
    time.sleep(0.3)
    if u.IsWindow(dlg):
        u.SendMessageW(btn, 0x00F5, 0, 0)          # BM_CLICK 兜底


def main():
    pid = cs2_pid()
    if not pid:
        print("cs2 未运行")
        return 1
    print("cs2 pid =", pid)

    if sys.argv[1] == "list":
        for h, c, t in enum_windows(pid):
            print(f"  {h:#014x}  {c:<28} {t!r}")
        return 0

    path = os.path.abspath(sys.argv[1])

    if sys.argv[1] == "fill":
        path = os.path.abspath(sys.argv[2])
        for h, c, t in enum_windows(pid):
            if c == "#32770":
                print("reuse dialog", hex(h), repr(t))
                print("set filename:", set_filename(h, path))
                submit(h, find_open_btn(h))
                return 0
        print("没有已打开的对话框")
        return 1

    # 0) 特殊模式：在子进程里做「会阻塞」的 trigger
    if sys.argv[1] == "trigger":
        act = int(sys.argv[2], 16)
        wb, cb = S._qt_bases()
        # 安全校验：地址必须真的是 QAction（旧进程的地址在新进程里是垃圾，
        # 拿垃圾当 this 调 trigger() 会把主线程卡死在 Qt 内部）
        if not S._qt_call(cb + S.RVA_QT_INHERITS, [act, "str:QAction"], 10000):
            print(f"不是 QAction，拒绝 trigger: {act:#x}")
            return 2
        ret = S._qt_call(wb + S.RVA_QT_ACTION_TRIGGER, [act], 15000)
        print("trigger ret =", ret)
        return 0

    print("target =", path)

    # 1) 动态找 &Open 并后台触发（trigger 遇到模态对话框会一直不返回）
    act = find_open_action()
    if not act:
        print("找不到 File->&Open")
        return 1
    print(f"&Open action = {act:#x}")
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "trigger", hex(act)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2) 等 #32770 对话框
    dlg = 0
    for _ in range(40):
        time.sleep(0.5)
        for h, c, t in enum_windows(pid):
            if c == "#32770":
                dlg = h
                print(f"dialog {h:#x} class={c} title={t!r}")
                break
        if dlg:
            break
    if not dlg:
        print("未出现 #32770 对话框，现有窗口：")
        for h, c, t in enum_windows(pid):
            print(f"  {h:#014x}  {c:<28} {t!r}")
        proc.kill()
        return 1

    time.sleep(1.0)
    print("--- children ---")
    for ch, cls, cid, txt in enum_children(dlg):
        print(f"  {ch:#014x} id={cid:<5} {cls:<24} {txt!r}")

    ok = set_filename(dlg, path)
    print("set filename:", ok)
    time.sleep(0.5)
    btn = find_open_btn(dlg)
    print("open button:", hex(btn) if btn else "NOT FOUND")
    if btn:
        submit(dlg, btn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
