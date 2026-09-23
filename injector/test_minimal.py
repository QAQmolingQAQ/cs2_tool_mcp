"""Minimal end-to-end test after all fixes."""
import ctypes, struct, json, time, sys
from ctypes import wintypes

pipe_name = "\\\\.\\pipe\\CS2ToolMCP"
dll_path = r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injected_dll\build_msvc\Release\cs2_tool.dll"

MSG_MAGIC = 0x43533254

print(f"[1] Loading DLL: {dll_path}")
dll = ctypes.WinDLL(dll_path)
dll.Cs2Tool_Init.restype = ctypes.c_int
dll.Cs2Tool_Init()
time.sleep(0.3)

k = ctypes.WinDLL("kernel32", use_last_error=True)

print(f"[2] WaitNamedPipe({repr(pipe_name)})")
ok = k.WaitNamedPipeW(pipe_name, 5000)
print(f"    ok={ok}, err={ctypes.get_last_error()}")
if not ok: sys.exit(1)

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
h = k.CreateFileW(pipe_name, 0xC0000000, 0, None, 3, 0, None)
print(f"[3] CreateFileW: h={h}, err={ctypes.get_last_error()}")
if h == INVALID_HANDLE_VALUE: sys.exit(1)

# Build frame
req = json.dumps({"id":1,"method":"ping"}).encode()
frame = struct.pack("<IIII", MSG_MAGIC, 1, len(req), 0) + req

# Write with ubyte array (no null truncation)
buf_type = ctypes.c_ubyte * len(frame)
buf = buf_type.from_buffer_copy(frame)
w = wintypes.DWORD()
ok = k.WriteFile(h, buf, len(frame), ctypes.byref(w), None)
err = ctypes.get_last_error()
print(f"[4] WriteFile: ok={ok}, written={w.value}, err={err}")

rhdr = ctypes.create_string_buffer(16)
ok = k.ReadFile(h, rhdr, 16, ctypes.byref(w), None)
print(f"[5] ReadFile hdr: ok={ok}, got={w.value}, err={ctypes.get_last_error()}")
magic, ver, length, _ = struct.unpack("<IIII", bytes(rhdr.raw))
print(f"    magic=0x{magic:x} ver={ver} len={length}")

if length > 0:
    resp = ctypes.create_string_buffer(length)
    ok = k.ReadFile(h, resp, length, ctypes.byref(w), None)
    print(f"[6] Response: {bytes(resp.raw)}")

k.CloseHandle(h)
dll.Cs2Tool_Shutdown()
print("DONE")
