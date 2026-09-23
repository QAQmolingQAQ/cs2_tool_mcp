#!/usr/bin/env python3
"""
Standalone test: Load cs2_tool.dll into this python process (simulating injection)
then exercise the named-pipe IPC by calling Cs2Tool_Init export.

This avoids needing hammer.exe running first - we just verify the pipe server
and basic protocol work end-to-end.

Usage:
    python test_dll_standalone.py
"""

from __future__ import annotations

import ctypes
import struct
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Protocol constants (must match injected_dll/protocol.h)
# ---------------------------------------------------------------------------
MSG_MAGIC = 0x43533254  # "CS2T"
MSG_VERSION = 1
HEADER_SIZE = 16  # 4 uint32 fields

DEFAULT_PIPE = "\\\\.\\pipe\\CS2ToolMCP"
DLL_PATH = Path(__file__).parent.parent / "injected_dll" / "build_msvc" / "Release" / "cs2_tool.dll"


# ---------------------------------------------------------------------------
# Named pipe client
# ---------------------------------------------------------------------------
class PipeClient:
    def __init__(self, pipe_name: str = DEFAULT_PIPE, timeout_ms: int = 5000):
        self.pipe_name = pipe_name
        self.timeout_ms = timeout_ms
        self._handle = None

    def _open(self) -> None:
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3

        ok = kernel32.WaitNamedPipeW(self.pipe_name, self.timeout_ms)
        if not ok:
            err = ctypes.get_last_error()
            raise ConnectionError(f"WaitNamedPipe failed (err={err}). Is DLL loaded?")

        handle = kernel32.CreateFileW(
            self.pipe_name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None,
        )
        if handle == INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            raise ConnectionError(f"CreateFileW failed (err={err})")

        self._handle = handle

    def _close(self) -> None:
        if self._handle is not None:
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.CloseHandle(self._handle)
            self._handle = None

    def _write_all(self, data: bytes) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        buf_type = ctypes.c_ubyte * len(data)
        buf = buf_type.from_buffer_copy(data)
        total = 0
        while total < len(data):
            written = ctypes.wintypes.DWORD()
            ok = kernel32.WriteFile(
                self._handle, ctypes.byref(buf, total), len(data) - total,
                ctypes.byref(written), None,
            )
            if not ok or written.value == 0:
                err = ctypes.get_last_error()
                raise IOError(f"WriteFile failed: err={err}, total={total}, remaining={len(data)-total}")
            total += written.value

    def _read_exact(self, n: int) -> bytes:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        buf = ctypes.create_string_buffer(n)
        total = 0
        while total < n:
            got = ctypes.wintypes.DWORD()
            ok = kernel32.ReadFile(
                self._handle, ctypes.byref(buf, total), n - total,
                ctypes.byref(got), None,
            )
            if not ok or got.value == 0:
                raise IOError("ReadFile failed / pipe closed")
            total += got.value
        return bytes(buf.raw)

    def call(self, method: str, params: dict | None = None) -> dict:
        import json
        request_obj = {"id": int(time.time() * 1000) & 0x7FFFFFFF, "method": method}
        if params is not None:
            request_obj["params"] = params
        payload = json.dumps(request_obj).encode("utf-8")

        header = struct.pack("<IIII", MSG_MAGIC, MSG_VERSION, len(payload), 0)
        frame = header + payload

        self._open()
        try:
            self._write_all(frame)
            resp_header = self._read_exact(HEADER_SIZE)
            magic, version, length, reserved = struct.unpack("<IIII", resp_header)
            if magic != MSG_MAGIC:
                raise IOError(f"Bad response magic: 0x{magic:x}")
            resp_payload = self._read_exact(length) if length > 0 else b""
        finally:
            self._close()

        return json.loads(resp_payload.decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Load cs2_tool.dll (simulate injection)
# ---------------------------------------------------------------------------
def load_dll() -> ctypes.WinDLL:
    if not DLL_PATH.exists():
        print(f"ERROR: DLL not found at {DLL_PATH}")
        print("Build it first: cmake --build injected_dll/build_msvc --config Release")
        sys.exit(1)

    print(f"[+] Loading: {DLL_PATH}")
    dll = ctypes.WinDLL(str(DLL_PATH))

    # Call exports
    dll.Cs2Tool_Version.restype = ctypes.c_char_p
    ver = dll.Cs2Tool_Version()
    print(f"[+] Cs2Tool_Version -> {ver.decode()}")

    dll.Cs2Tool_Init.restype = ctypes.c_int
    rc = dll.Cs2Tool_Init()
    print(f"[+] Cs2Tool_Init -> {rc}  (1=started, 0=already running)")

    return dll


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------
def run_tests() -> None:
    time.sleep(0.5)  # let pipe server spin up

    client = PipeClient(timeout_ms=5000)

    tests = [
        ("ping", None),
        ("list_tools", None),
        ("get_status", None),
        ("list_interfaces", None),  # will probably be empty in python.exe (no hammer.dll)
        ("get_hammer_app", None),
    ]

    all_ok = True
    for method, params in tests:
        try:
            resp = client.call(method, params)
            ok = "error" not in resp
            status = "OK" if ok else "INJECTED_ERROR"
            print(f"\n[{status}] {method}:")
            import json
            print("   ", json.dumps(resp, indent=2, ensure_ascii=False)[:300])
            if not ok:
                all_ok = False
        except Exception as e:
            print(f"\n[FAIL] {method}: {type(e).__name__}: {e}")
            all_ok = False

    print(f"\n{'='*50}")
    print(f"RESULT: {'ALL OK' if all_ok else 'SOME FAILED'}")
    print("=" * 50)


def main() -> None:
    print(f"[cs2_tool_test] DLL={DLL_PATH}")
    print("[cs2_tool_test] Loading cs2_tool.dll into this process...")
    dll = load_dll()

    try:
        run_tests()
    finally:
        print("\n[+] Calling Cs2Tool_Shutdown...")
        dll.Cs2Tool_Shutdown.restype = ctypes.c_int
        dll.Cs2Tool_Shutdown()
        print("[+] Done.")


if __name__ == "__main__":
    main()
