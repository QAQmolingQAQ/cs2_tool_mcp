"""Serialize complete bridge operations across module MCP processes on Windows."""
from contextlib import contextmanager
import ctypes
import hashlib
import os
import threading

_fallback = threading.RLock()

@contextmanager
def operation_lock(pipe_name: str):
    if os.name != "nt":
        with _fallback:
            yield
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    name = "Local\\CS2McpOperation_" + hashlib.sha256(pipe_name.casefold().encode()).hexdigest()[:24]
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise OSError(ctypes.get_last_error(), "Cannot create shared bridge operation mutex")
    acquired = False
    try:
        status = kernel.WaitForSingleObject(handle, 120000)
        acquired = status in (0, 0x80)
        if status == 0x80:
            raise RuntimeError("Previous MCP process exited during an operation; inspect editor before retrying")
        if status != 0:
            raise TimeoutError(f"Cannot acquire bridge operation mutex (status={status:#x})")
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)
