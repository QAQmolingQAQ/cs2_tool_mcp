"""Windows named-pipe transport. No Hammer addresses or MCP dependencies."""
from __future__ import annotations
import ctypes
import itertools
import threading
from typing import Any, Callable
from .settings import DEFAULT_PIPE, DEFAULT_PIPE_TIMEOUT
from .protocol import HEADER_SIZE, encode_request, response_length, decode_response

KERNEL32 = None

def _kernel32():
    """kernel32 绑定（**进程内缓存**）。

    原先每次 Win32 调用都重建一遍 `ctypes.WinDLL(...)` 并重设 argtypes ——
    那点构造开销比读写本身还大；缓存后单次 IPC 往返明显变快。
    """
    global KERNEL32
    if KERNEL32 is None:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        k32.WaitNamedPipeW.restype = ctypes.c_int
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CreateFileW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ]
        k32.WriteFile.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
        ]
        k32.ReadFile.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
        ]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        KERNEL32 = k32
    return KERNEL32


class Cs2Pipe:
    """与注入 DLL 中 IpcPipeServer 对应的命名管道客户端。"""

    def __init__(self, pipe_name: str = DEFAULT_PIPE, timeout_ms: int = DEFAULT_PIPE_TIMEOUT, on_reset: Callable[[], None] | None = None):
        self.pipe_name = pipe_name
        self.timeout_ms = timeout_ms
        self._handle: int | None = None
        self._on_reset = on_reset or (lambda: None)
        self._lock = threading.RLock()
        self._ids = itertools.count(1)

    # -- Win32 原语 ----------------------------------------------------

    def _open(self) -> None:
        k32 = _kernel32()
        if not k32.WaitNamedPipeW(self.pipe_name, self.timeout_ms):
            raise ConnectionError(
                f"WaitNamedPipe failed for {self.pipe_name} (err={ctypes.get_last_error()}). "
                "cs2_tool.dll 是否已注入 hammer.exe？"
            )
        handle = k32.CreateFileW(
            self.pipe_name, 0x80000000 | 0x40000000, 0, None, 3, 0, None
        )
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise ConnectionError(
                f"CreateFileW failed for {self.pipe_name} (err={ctypes.get_last_error()})"
            )
        self._handle = handle
        self._on_reset()   # 新连接：对端可能换过进程，基址缓存作废

    def _close(self) -> None:
        if self._handle is not None:
            _kernel32().CloseHandle(self._handle)
            self._handle = None
        self._on_reset()

    def _write_all(self, data: bytes) -> None:
        k32 = _kernel32()
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        total = 0
        while total < len(data):
            written = ctypes.c_uint32(0)
            ok = k32.WriteFile(
                self._handle, ctypes.byref(buf, total),
                len(data) - total, ctypes.byref(written), None,
            )
            if not ok or written.value == 0:
                raise IOError("WriteFile failed")
            total += written.value

    def _read_exact(self, n: int) -> bytes:
        k32 = _kernel32()
        buf = ctypes.create_string_buffer(n)
        total = 0
        while total < n:
            got = ctypes.c_uint32(0)
            ok = k32.ReadFile(
                self._handle, ctypes.byref(buf, total),
                n - total, ctypes.byref(got), None,
            )
            if not ok or got.value == 0:
                raise IOError("ReadFile failed / pipe closed")
            total += got.value
        return buf.raw[:n]

    # -- 协议 API ------------------------------------------------------

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Serialize one round trip. Never replay an ambiguously completed request."""
        with self._lock:
            request_id = next(self._ids) & 0x7FFFFFFF
            frame = encode_request(request_id, method, params)
            if self._handle is None:
                self._open()
            try:
                self._write_all(frame)
                length = response_length(self._read_exact(HEADER_SIZE))
                return decode_response(self._read_exact(length), request_id)
            except (OSError, ValueError) as exc:
                self._close()
                raise OSError(
                    f"Bridge call {method!r} failed; outcome may be unknown. "
                    "Request was not replayed. Inspect Hammer before retrying."
                ) from exc

    def close(self) -> None:
        with self._lock:
            self._close()
