# -*- coding: utf-8 -*-
"""对目标进程所有线程做一次原生 StackWalk64，输出各线程的返回地址(RVA)。"""
import ctypes
import ctypes.wintypes as w
import sys

w.ULONGLONG = ctypes.c_uint64

PID = int(sys.argv[1]) if len(sys.argv) > 1 else 3824
TARGET_MODS = ("hammer.dll", "cs2_tool.dll", "Qt5Core.dll", "Qt5Widgets.dll")

k32 = ctypes.windll.kernel32
dbg = ctypes.windll.dbghelp

k32.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = w.BOOL
for _fn in ("OpenProcess", "OpenThread", "CreateToolhelp32Snapshot"):
    getattr(k32, _fn).restype = w.HANDLE

TH32CS_SNAPTHREAD = 0x4
THREAD_QUERY = 0x0040
THREAD_GET_CONTEXT = 0x0008
THREAD_SUSPEND_RESUME = 0x0002
CONTEXT_FULL = 0x100007
CONTEXT_AMD64 = 0x100000


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD),
                ("th32ThreadID", w.DWORD), ("th32OwnerProcessID", w.DWORD),
                ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", w.DWORD)]


class M128(ctypes.Structure):
    _fields_ = [("Low", w.ULONGLONG), ("High", w.ULONGLONG)]


class CONTEXT64(ctypes.Structure):
    _align_ = 16
    _fields_ = [
        ("P1Home", w.ULONGLONG), ("P2Home", w.ULONGLONG),
        ("P3Home", w.ULONGLONG), ("P4Home", w.ULONGLONG),
        ("P5Home", w.ULONGLONG), ("P6Home", w.ULONGLONG),
        ("ContextFlags", w.DWORD), ("MxCsr", w.DWORD),
        ("SegCs", w.WORD), ("SegDs", w.WORD), ("SegEs", w.WORD),
        ("SegFs", w.WORD), ("SegGs", w.WORD), ("SegSs", w.WORD),
        ("EFlags", w.DWORD),
        ("Rax", w.ULONGLONG), ("Rcx", w.ULONGLONG),
        ("Rdx", w.ULONGLONG), ("Rbx", w.ULONGLONG),
        ("Rsp", w.ULONGLONG), ("Rbp", w.ULONGLONG),
        ("Rsi", w.ULONGLONG), ("Rdi", w.ULONGLONG),
        ("R8", w.ULONGLONG), ("R9", w.ULONGLONG),
        ("R10", w.ULONGLONG), ("R11", w.ULONGLONG),
        ("R12", w.ULONGLONG), ("R13", w.ULONGLONG),
        ("R14", w.ULONGLONG), ("R15", w.ULONGLONG),
        ("Rip", w.ULONGLONG),
        ("FltSave", ctypes.c_byte * 512),
        ("VectorRegister", M128 * 26),
        ("VectorControl", w.ULONGLONG),
        ("DebugControl", w.ULONGLONG), ("LastBranchToRip", w.ULONGLONG),
        ("LastBranchFromRip", w.ULONGLONG), ("LastExceptionToRip", w.ULONGLONG),
        ("LastExceptionFromRip", w.ULONGLONG),
    ]


class STACKFRAME64(ctypes.Structure):
    _fields_ = [
        ("AddrPC", w.ULONGLONG * 2),  # {offset,module} use AddrPC.Offset
        ("_pad_addr_mode1", w.DWORD),
        ("AddrReturn", w.ULONGLONG * 2),
        ("_pad2", w.DWORD),
        ("AddrFrame", w.ULONGLONG * 2),
        ("_pad3", w.DWORD),
        ("AddrStack", w.ULONGLONG * 2),
        ("_pad4", w.DWORD),
        ("AddrBStore", w.ULONGLONG * 2),
        ("_pad5", w.DWORD),
        ("FuncTableEntry", w.LPVOID),
        ("Params", w.ULONGLONG * 4),
        ("Far", ctypes.c_bool),
        ("Virtual", ctypes.c_bool),
        ("_pad6", w.BYTE * 6),
        ("KdHELP", w.LPVOID),
        ("StackBase", w.ULONGLONG), ("StackSize", w.ULONGLONG),
        ("_dummy", w.ULONGLONG * 12),
    ]


# use the real struct definition properly
class ADDRESS64(ctypes.Structure):
    _fields_ = [("Offset", w.ULONGLONG), ("Mode", ctypes.c_ushort)]


class STACKFRAME64B(ctypes.Structure):
    _fields_ = [
        ("AddrPC", ADDRESS64),        # 0x00
        ("AddrReturn", ADDRESS64),    # 0x10
        ("AddrFrame", ADDRESS64),     # 0x20
        ("AddrStack", ADDRESS64),     # 0x30
        ("AddrBStore", ADDRESS64),    # 0x40
        ("FuncTableEntry", w.LPVOID), # 0x50
        ("Params", w.ULONGLONG * 4),  # 0x58
        ("Far", w.BOOL),              # 0x78
        ("Virtual", w.BOOL),          # 0x7C
        ("_pad", w.DWORD),            # 0x80 align
        ("KdHELP", w.LPVOID),         # 0x80... -> actual at 0x80? below
        ("StackBase", w.ULONGLONG),
        ("StackSize", w.ULONGLONG),
        ("_dummy", w.ULONGLONG * 12),
    ]


# ---- module list ----
class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("th32ModuleID", w.DWORD),
                ("th32ProcessID", w.DWORD), ("GlblcntUsage", w.DWORD),
                ("ProccntUsage", w.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
                ("modBaseSize", w.DWORD), ("hModule", w.HMODULE),
                ("szModule", ctypes.c_wchar * 256),
                ("szExePath", ctypes.c_wchar * 260)]


def module_list(hp):
    snap = k32.CreateToolhelp32Snapshot(0x8, PID)
    me = MODULEENTRY32W(); me.dwSize = ctypes.sizeof(MODULEENTRY32W)
    mods = []
    if k32.Module32FirstW(snap, ctypes.byref(me)):
        while True:
            mods.append((me.szModule.lower(), ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value or 0,
                         me.modBaseSize, me.szExePath))
            if not k32.Module32NextW(snap, ctypes.byref(me)):
                break
    k32.CloseHandle(snap)
    return mods


def which_mod(addr, mods):
    for nm, base, size, path in mods:
        if base <= addr < base + size:
            return nm, base
    return None, 0


READPROCMEM = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HANDLE, ctypes.c_uint64, w.LPVOID, w.DWORD,
                                 ctypes.POINTER(ctypes.c_size_t))
FINDFUNCTABLE = ctypes.WINFUNCTYPE(w.LPVOID, w.HANDLE, ctypes.c_uint64)
GETMODBASE = ctypes.WINFUNCTYPE(ctypes.c_uint64, w.HANDLE, ctypes.c_uint64)


def main():
    hp = k32.OpenProcess(0x1F0FFF, False, PID)  # PROCESS_ALL_ACCESS
    if not hp:
        print("OpenProcess failed", ctypes.get_last_error()); return
    mods = module_list(hp)
    tmods = {n: b for n, b, s, p in mods if n in TARGET_MODS}
    print("modules:", {n: hex(b) for n, b in tmods.items()}, flush=True)

    sym_opts = dbg.SymSetOptions(0)
    dbg.SymSetOptions(sym_opts | 0x800 | 0x8)  # SYMOPT_DEFERRED_LOADS|UNDNAME
    dbg.SymInitializeW.argtypes = [w.HANDLE, w.LPCWSTR, w.BOOL]
    dbg.SymInitializeW.restype = w.BOOL
    dbg.SymInitializeW(hp, None, False)
    dbg.SymLoadModuleExW.argtypes = [w.HANDLE, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR,
                                     ctypes.c_uint64, w.DWORD, ctypes.c_void_p, w.DWORD]
    dbg.SymLoadModuleExW.restype = ctypes.c_uint64
    for nm, base, size, path in mods:
        dbg.SymLoadModuleExW(hp, path, None, None, base, size, None, 0)

    dbg.SymFunctionTableAccess64.argtypes = [w.HANDLE, ctypes.c_uint64]
    dbg.SymFunctionTableAccess64.restype = ctypes.c_void_p
    dbg.SymGetModuleBase64.argtypes = [w.HANDLE, ctypes.c_uint64]
    dbg.SymGetModuleBase64.restype = ctypes.c_uint64
    dbg.StackWalk64.argtypes = [w.DWORD, w.HANDLE, w.HANDLE,
                                ctypes.POINTER(STACKFRAME64B), ctypes.POINTER(CONTEXT64),
                                READPROCMEM, FINDFUNCTABLE, GETMODBASE, ctypes.c_void_p]
    dbg.StackWalk64.restype = w.BOOL

    @READPROCMEM
    def rpm(h, a, buf, n, got):
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(a), buf, n, got)
        return ok != 0

    @FINDFUNCTABLE
    def ftab(h, a):
        return dbg.SymFunctionTableAccess64(h, a)

    @GETMODBASE
    def gmb(h, a):
        return dbg.SymGetModuleBase64(h, a)

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    hwnd_main = ctypes.windll.user32.FindWindowW(None, "Hammer - [untitled_2.vmap]")
    gui_tid = ctypes.windll.user32.GetWindowThreadProcessId(hwnd_main, None)
    print("GUI main tid:", gui_tid, flush=True)
    te = THREADENTRY32(); te.dwSize = ctypes.sizeof(THREADENTRY32)
    ok = k32.Thread32First(snap, ctypes.byref(te))
    threads = []
    while ok:
        if te.th32OwnerProcessID == PID:
            threads.append(te.th32ThreadID)
        ok = k32.Thread32Next(snap, ctypes.byref(te))
    k32.CloseHandle(snap)
    print("threads:", len(threads), flush=True)

    for tid in threads:
        ht = k32.OpenThread(THREAD_QUERY | THREAD_GET_CONTEXT | THREAD_SUSPEND_RESUME, False, tid)
        if not ht:
            if tid == gui_tid:
                print("GUI thread OpenThread failed", ctypes.get_last_error(), flush=True)
            continue
        ctx_buf = (ctypes.c_byte * 1232)()
        ctypes.cast(ctypes.byref(ctx_buf), ctypes.POINTER(ctypes.c_uint32))[0x30 // 4] = CONTEXT_AMD64 | CONTEXT_FULL
        k32.SuspendThread(ht)
        got = k32.GetThreadContext(ht, ctypes.byref(ctx_buf))
        k32.ResumeThread(ht)
        if not got:
            if tid == gui_tid:
                print("GUI thread GetThreadContext failed", ctypes.get_last_error(), flush=True)
            k32.CloseHandle(ht); continue
        cq = ctypes.cast(ctypes.byref(ctx_buf), ctypes.POINTER(ctypes.c_uint64))
        rip = cq[0xF8 // 8]
        rsp = cq[0x98 // 8]
        rbp = cq[0xA0 // 8]
        sf = STACKFRAME64B()
        sf.AddrPC.Offset = rip; sf.AddrPC.Mode = 3  # AddrModeFlat
        sf.AddrFrame.Offset = rbp; sf.AddrFrame.Mode = 3
        sf.AddrStack.Offset = rsp; sf.AddrStack.Mode = 3
        chain = []
        sw_dbg = None
        for _ in range(64):
            r = dbg.StackWalk64(0x8664, hp, ht, ctypes.byref(sf), None,
                                rpm, ftab, gmb, None)
            if not r:
                if tid == gui_tid:
                    sw_dbg = (sf.AddrPC.Offset, sf.AddrStack.Offset,
                              sf.FuncTableEntry or 0, ctypes.get_last_error())
                break
            a = sf.AddrPC.Offset
            nm, base = which_mod(a, mods)
            if nm:
                chain.append(f"{nm}+{a-base:#x}")
            elif a:
                chain.append(f"{a:#x}")
        k32.CloseHandle(ht)
        if chain or tid == gui_tid:
            gnm, gbase = which_mod(rip, mods)
            print(f"--- tid {tid}{'  <<< GUI MAIN' if tid == gui_tid else ''} "
                  f"rip={rip:#x} mod={gnm}+{rip-gbase:#x} frames={len(chain)} ---")
            for c in chain[:40]:
                print("   ", c)
            if sw_dbg:
                print("    swfail pc=%#x stack=%#x fte=%#x lasterr=%d" % sw_dbg)
    k32.CloseHandle(hp)


if __name__ == "__main__":
    main()
