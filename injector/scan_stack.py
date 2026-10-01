# -*- coding: utf-8 -*-
"""扫描 GUI 主线程栈，打印落在可执行内存且形如「call 返回地址」的帧。

用法：
    python scan_stack.py <pid> [窗口标题关键字]

x64 StackWalk64 依赖 .pdata 展开，实测在本环境里第一帧就失败，
所以这里改用「Raw RSP 扫描 + call-site 校验」的笨办法：
  1) Susp/GetThreadContext 取 RIP/RSP/RBP
  2) 逐页读栈（跨页/未提交页会失败，逐页读可最大化拿到已提交部分）
  3) 找形如 E8 rel32 / FF 15 disp32 / FF D0-D7 的 call 指令之后的地址
"""
import ctypes
import ctypes.wintypes as w
import struct
import sys

w.ULONGLONG = ctypes.c_uint64
k32 = ctypes.windll.kernel32
u32 = ctypes.windll.user32
k32.OpenProcess.restype = w.HANDLE
k32.OpenThread.restype = w.HANDLE
k32.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = w.BOOL
k32.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.CreateToolhelp32Snapshot.restype = w.HANDLE

TH32CS_SNAPMODULE = 0x8


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("th32ModuleID", w.DWORD),
                ("th32ProcessID", w.DWORD), ("GlblcntUsage", w.DWORD),
                ("ProccntUsage", w.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
                ("modBaseSize", w.DWORD), ("hModule", w.HMODULE),
                ("szModule", ctypes.c_wchar * 256),
                ("szExePath", ctypes.c_wchar * 260)]


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", w.DWORD), ("_pad1", w.DWORD),
                ("RegionSize", ctypes.c_size_t), ("State", w.DWORD),
                ("Protect", w.DWORD), ("Type", w.DWORD)]


EXEC_PROTECTS = {0x10, 0x20, 0x40, 0x80}
PID = int(sys.argv[1])
_ARG2 = sys.argv[2] if len(sys.argv) > 2 else "Hammer"
ALL = _ARG2 == "all" or (len(sys.argv) > 3 and sys.argv[3] == "all")
TITLE_KEY = "" if _ARG2 == "all" else _ARG2
SCAN = 0x40000

hp = k32.OpenProcess(0x1F0FFF, False, PID)
if not hp:
    print("OpenProcess failed", ctypes.get_last_error())
    sys.exit(1)


def modules():
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, PID)
    me = MODULEENTRY32W()
    me.dwSize = ctypes.sizeof(MODULEENTRY32W)
    out = []
    if k32.Module32FirstW(snap, ctypes.byref(me)):
        while True:
            out.append((me.szModule.lower(),
                        ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value or 0,
                        me.modBaseSize))
            if not k32.Module32NextW(snap, ctypes.byref(me)):
                break
    k32.CloseHandle(snap)
    return out


MODS = modules()
RANGES = [(n, b, b + s) for n, b, s in MODS]


def which_mod(addr):
    for n, lo, hi in RANGES:
        if lo <= addr < hi:
            return n, addr - lo
    return None, 0


def gui_tid():
    """找标题含关键字的可见窗口所属线程。"""
    res = []

    def cb(h, l):
        p = w.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == PID and u32.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(h, t, 256)
            c = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(h, c, 256)
            if TITLE_KEY.lower() in t.value.lower() and c.value.startswith("Qt"):
                res.append((h, u32.GetWindowThreadProcessId(h, None), t.value))
        return True

    u32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    u32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    u32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)(cb), 0)
    return res


def is_exec(addr):
    m = MBI()
    n = k32.VirtualQueryEx(hp, ctypes.c_void_p(addr), ctypes.byref(m), ctypes.sizeof(m))
    return bool(n) and m.State == 0x1000 and m.Protect in EXEC_PROTECTS


def code_at(addr, n):
    tb = (ctypes.c_ubyte * n)()
    g = ctypes.c_size_t()
    ok = k32.ReadProcessMemory(hp, ctypes.c_void_p(addr), tb, n, ctypes.byref(g))
    return bytes(tb[:g.value]) if ok else b""


def is_call_return(addr):
    b = code_at(addr - 7, 7)
    if len(b) < 7:
        return False
    if b[2] == 0xE8:                                     # call rel32
        return True
    if b[0] in (0x48, 0x4C, 0x40, 0x41) and b[1] == 0xFF and b[2] == 0x15:
        return True                                      # [REX] call [rip+disp]
    if b[1] == 0xFF and b[2] == 0x15:
        return True
    if b[4] in (0x48, 0x4C) and b[5] == 0xFF and 0xD0 <= b[6] <= 0xD7:
        return True                                      # call r8-r15
    if b[5] == 0xFF and 0xD0 <= b[6] <= 0xD7:
        return True
    return False


def scan_thread(tid, tag, only_if_our_dll=False):
    ht = k32.OpenThread(0x40 | 0x8 | 0x2, False, tid)
    if not ht:
        return
    ctx = (ctypes.c_byte * 1232)()
    ctypes.cast(ctypes.byref(ctx), ctypes.POINTER(ctypes.c_uint32))[0x30 // 4] = 0x100007
    k32.SuspendThread(ht)
    try:
        got = k32.GetThreadContext(ht, ctypes.byref(ctx))
    finally:
        k32.ResumeThread(ht)
    if not got:
        k32.CloseHandle(ht)
        return
    q = ctypes.cast(ctypes.byref(ctx), ctypes.POINTER(ctypes.c_uint64))
    rip, rsp, rbp = q[0xF8 // 8], q[0x98 // 8], q[0xA0 // 8]
    rn, ro = which_mod(rip)

    raw = b""
    PAGE = 0x1000
    for i in range(0, SCAN, PAGE):
        tb = (ctypes.c_ubyte * PAGE)()
        g = ctypes.c_size_t()
        if not k32.ReadProcessMemory(hp, ctypes.c_void_p(rsp + i), tb, PAGE, ctypes.byref(g)) \
                or g.value == 0:
            break
        raw += bytes(tb[:g.value])
    frames = []
    for off in range(0, max(0, len(raw) - 8), 8):
        v = struct.unpack_from("<Q", raw, off)[0]
        if not is_exec(v) or not is_call_return(v):
            continue
        n, o = which_mod(v)
        if n:
            frames.append((off, n, o))
    k32.CloseHandle(ht)

    our = [f for f in frames if f[1] == "cs2_tool.dll"]
    if only_if_our_dll and not our:
        return
    print(f"--- tid {tid} {tag} rip={rip:#x} ({rn}+{ro:#x}) frames={len(frames)}")
    for off, n, o in frames[:40]:
        print(f"    rsp+{off:#07x}  {n}+{o:#x}")


wins = gui_tid()
print("Hammer 窗口:", [(hex(h), t) for h, _, t in wins])
if not wins:
    print("找不到窗口")
    sys.exit(1)

if ALL:
    import subprocess as _sp
    out = _sp.run(["powershell", "-NoProfile", "-Command",
                   f"(Get-Process -Id {PID}).Threads | ForEach-Object {{ $_.Id }}"],
                  capture_output=True, text=True).stdout
    for line in out.split():
        try:
            t = int(line)
        except ValueError:
            continue
        scan_thread(t, "<<< GUI MAIN" if t == wins[0][1] else "",
                    only_if_our_dll=(t != wins[0][1]))
else:
    scan_thread(wins[0][1], "<<< GUI MAIN")
