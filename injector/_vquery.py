#!/usr/bin/env python3
"""探针7：VirtualQueryEx 查顶点数组区域保护状态，再尝试读。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import struct
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

PID = int(sys.argv[1]) if len(sys.argv) > 1 else 1812
ADDR = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x5bb53230000

h = k32.OpenProcess(0x0410, False, PID)
print("handle", hex(h) if h else None)


class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", w.DWORD),
        ("__part1", w.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", w.DWORD),
        ("Protect", w.DWORD),
        ("Type", w.DWORD),
    ]


mbi = MBI()
ok = k32.VirtualQueryEx(h, ctypes.c_void_p(ADDR), ctypes.byref(mbi), ctypes.sizeof(mbi))
print("VirtualQuery ok=%s err=%d" % (ok, ctypes.get_last_error()))
print("Base=%#x AllocBase=%#x AllocProt=0x%x Size=%#x State=0x%x Prot=0x%x Type=0x%x"
      % (mbi.BaseAddress or 0, mbi.AllocationBase or 0, mbi.AllocationProtect,
         mbi.RegionSize, mbi.State, mbi.Protect, mbi.Type))

buf = ctypes.create_string_buffer(256)
got = ctypes.c_size_t()
ok = k32.ReadProcessMemory(h, ctypes.c_void_p(ADDR), buf, 256, ctypes.byref(got))
print("ReadProcessMemory ok=%s got=%d err=%d" % (ok, got.value, ctypes.get_last_error()))
if ok:
    d = buf.raw[:got.value]
    for i in range(0, min(got.value, 128), 4):
        iv = struct.unpack_from("<i", d, i)[0]
        fv = struct.unpack_from("<f", d, i)[0]
        print("+%3d i=%-12d f=%g" % (i, iv, fv))
