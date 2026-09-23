#!/usr/bin/env python3
"""
Simple DLL injector using CreateRemoteThread + LoadLibraryW.
Injects cs2_tool.dll into hammer.exe by PID.

Usage:
    python inject_dll.py [pid]
    python inject_dll.py         # auto-find hammer.exe
"""
from __future__ import annotations

import ctypes
import sys
import os
from ctypes import wintypes

# Constants
PROCESS_ALL_ACCESS = 0x001F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
MEM_RELEASE = 0x8000
WAIT_OBJECT_0 = 0x00000000

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# API declarations
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

kernel32.VirtualAllocEx.restype = wintypes.LPVOID
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]

kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

kernel32.GetProcAddress.restype = wintypes.LPVOID
kernel32.GetProcAddress.argtypes = [wintypes.HMODULE, wintypes.LPCSTR]

kernel32.CreateRemoteThread.restype = wintypes.HANDLE
kernel32.CreateRemoteThread.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID]

kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def _is_zombie(pid: int) -> bool:
    """僵尸进程判据：能 OpenProcess 但枚举不到任何模块。

    CS2 崩溃后进程会残留成僵尸（HandleCount=0、模块读不到），
    既不能注入也不能调管道 —— 必须跳过，否则会误选到它。
    """
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return True  # 打不开也算不可用
    try:
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        # 必须声明 argtypes：否则 64 位 HANDLE 会被当 int 截断，调用直接失败
        psapi.EnumProcessModules.restype = wintypes.BOOL
        psapi.EnumProcessModules.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.HMODULE),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        buf = (wintypes.HMODULE * 1024)()
        needed = wintypes.DWORD(0)
        ok = psapi.EnumProcessModules(h, buf, ctypes.sizeof(buf), ctypes.byref(needed))
        if not ok:
            return True
        return needed.value == 0
    finally:
        kernel32.CloseHandle(h)


def list_candidate_pids() -> list[int]:
    """列出所有 cs2 进程 PID（可能含僵尸）。"""
    import subprocess
    result = subprocess.run(
        ["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True
    )
    pids = []
    for line in result.stdout.strip().split("\n"):
        parts = line.strip('"').split('","')
        if len(parts) >= 2 and parts[0].lower() in ("hammer.exe", "hammer", "cs2.exe", "cs2"):
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def find_hammer_pid() -> int | None:
    """自动挑选可用的 cs2/hammer 进程，跳过僵尸。"""
    pids = list_candidate_pids()
    alive = []
    for pid in pids:
        if _is_zombie(pid):
            print(f"  [跳过] PID {pid} 是僵尸进程（枚举不到模块）")
        else:
            alive.append(pid)
    if not alive:
        return None
    if len(alive) > 1:
        print(f"  [注意] 有多个可用进程 {alive}，取第一个")
    return alive[0]


def inject_dll(pid: int, dll_path: str) -> bool:
    """Inject dll_path into process pid."""
    dll_path = os.path.abspath(dll_path)
    if not os.path.exists(dll_path):
        print(f"  ERROR: DLL not found: {dll_path}")
        return False

    dll_path_w = dll_path.encode("utf-16-le") + b"\x00\x00"
    path_size = len(dll_path_w)

    print(f"  PID: {pid}")
    print(f"  DLL: {dll_path}")

    # 1. Open process
    hProc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not hProc:
        print(f"  ERROR: OpenProcess failed (err={ctypes.get_last_error()})")
        return False
    print(f"  [+] OpenProcess -> 0x{hProc:x}")

    try:
        # 2. Get LoadLibraryW address
        hKernel32 = kernel32.GetModuleHandleW("kernel32.dll")
        if not hKernel32:
            print(f"  ERROR: GetModuleHandleW kernel32 (err={ctypes.get_last_error()})")
            return False
        pLoadLibraryW = kernel32.GetProcAddress(hKernel32, b"LoadLibraryW")
        if not pLoadLibraryW:
            print(f"  ERROR: GetProcAddress LoadLibraryW (err={ctypes.get_last_error()})")
            return False
        print(f"  [+] LoadLibraryW @ 0x{pLoadLibraryW:x}")

        # 3. Allocate memory in target process
        remote_addr = kernel32.VirtualAllocEx(
            hProc, None, path_size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not remote_addr:
            print(f"  ERROR: VirtualAllocEx failed (err={ctypes.get_last_error()})")
            return False
        print(f"  [+] VirtualAllocEx -> 0x{remote_addr:x}")

        # 4. Write DLL path into remote memory
        written = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(
            hProc, remote_addr, dll_path_w, path_size, ctypes.byref(written)
        ) or written.value != path_size:
            print(f"  ERROR: WriteProcessMemory failed (err={ctypes.get_last_error()})")
            return False
        print(f"  [+] Wrote {written.value} bytes to remote")

        # 5. Create remote thread calling LoadLibraryW(dll_path)
        hThread = kernel32.CreateRemoteThread(
            hProc, None, 0, pLoadLibraryW, remote_addr, 0, None
        )
        if not hThread:
            print(f"  ERROR: CreateRemoteThread failed (err={ctypes.get_last_error()})")
            return False
        print(f"  [+] CreateRemoteThread -> 0x{hThread:x}")

        # 6. Wait for thread to finish (LoadLibraryW is quick)
        rc = kernel32.WaitForSingleObject(hThread, 5000)
        if rc == WAIT_OBJECT_0:
            print(f"  [+] Thread completed successfully!")
        else:
            print(f"  [!] Wait returned {rc} (non-fatal, continuing)")

        kernel32.CloseHandle(hThread)
        return True

    finally:
        kernel32.CloseHandle(hProc)


def main():
    # Get DLL path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dll_path = os.path.join(
        script_dir, "..", "injected_dll", "build_msvc", "Release", "cs2_tool.dll"
    )

    # Get PID
    if len(sys.argv) > 1:
        pid = int(sys.argv[1])
    else:
        pid = find_hammer_pid()
        if not pid:
            print("ERROR: Cannot find hammer.exe (or cs2.exe). Start Hammer first!")
            sys.exit(1)

    print(f"=== cs2_tool.dll Injector ===")
    print(f"  Target PID: {pid}")

    if inject_dll(pid, dll_path):
        print(f"\n  [+] INJECTION SUCCESS!")
        print(f"  [+] Pipe should be available: \\\\.\\pipe\\CS2ToolMCP")
        print(f"\n  Now run: python mcp_server\\cs2_mcp_server.py")
    else:
        print(f"\n  [-] INJECTION FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
