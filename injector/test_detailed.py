import ctypes, struct, json, time, sys
from ctypes import wintypes

pipe_name = "\\\\.\\pipe\\CS2ToolMCP"
dll_path = r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injected_dll\build_msvc\Release\cs2_tool.dll"

MSG_MAGIC = 0x43533254

print(f"[1] Loading DLL")
dll = ctypes.WinDLL(dll_path)
dll.Cs2Tool_Init.restype = ctypes.c_int
rc = dll.Cs2Tool_Init()
print(f"    Cs2Tool_Init -> {rc}")
time.sleep(0.5)

k = ctypes.WinDLL("kernel32", use_last_error=True)

print(f"[2] WaitNamedPipe('{pipe_name}')")
ok = k.WaitNamedPipeW(pipe_name, 5000)
err1 = ctypes.get_last_error()
print(f"    result={ok}, err={err1}")
if not ok:
    print("FATAL: pipe not available")
    sys.exit(1)

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
h = k.CreateFileW(pipe_name, 0xC0000000, 0, None, 3, 0, None)
err2 = ctypes.get_last_error()
print(f"[3] CreateFileW: handle={h} (0x{h:x}), err={err2}")
if h == INVALID_HANDLE_VALUE:
    print("FATAL: CreateFileW failed")
    sys.exit(1)

# Build frame
req = json.dumps({"id":1,"method":"ping"}).encode()
print(f"[4] request JSON bytes: {req}")
frame = struct.pack("<IIII", MSG_MAGIC, 1, len(req), 0) + req
print(f"    frame len: {len(frame)}")
print(f"    frame hex[:24]: {[hex(b) for b in frame[:24]]}")

buf_type = ctypes.c_ubyte * len(frame)
buf = buf_type.from_buffer_copy(frame)

GENERIC_READ_WRITE = 0xC0000000  # just for reference

w = wintypes.DWORD()
ok = k.WriteFile(h, buf, len(frame), ctypes.byref(w), None)
err3 = ctypes.get_last_error()
print(f"[5] WriteFile: ok={ok}, written={w.value}, err={err3}")
if not ok:
    print("FATAL: WriteFile failed")
    k.CloseHandle(h)
    sys.exit(1)

# Read response
print("[6] Reading response header...")
rhdr = ctypes.create_string_buffer(16)
ok = k.ReadFile(h, rhdr, 16, ctypes.byref(w), None)
err4 = ctypes.get_last_error()
print(f"    ReadFile hdr: ok={ok}, got={w.value}, err={err4}")
if not ok or w.value == 0:
    print("FATAL: ReadFile header failed")
    k.CloseHandle(h)
    sys.exit(1)

magic, ver, length, reserved = struct.unpack("<IIII", bytes(rhdr.raw))
print(f"    response magic=0x{magic:x} ver={ver} len={length}")

if length > 0:
    resp = ctypes.create_string_buffer(length)
    ok = k.ReadFile(h, resp, length, ctypes.byref(w), None)
    err5 = ctypes.get_last_error()
    print(f"[7] ReadFile payload: ok={ok}, got={w.value}, err={err5}")
    if ok and w.value > 0:
        print(f"    RESPONSE: {bytes(resp.raw)[:w.value]}")

k.CloseHandle(h)
dll.Cs2Tool_Shutdown()
print("\n=== TEST COMPLETE ===")
