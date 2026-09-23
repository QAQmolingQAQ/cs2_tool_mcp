import ctypes, struct, json, time, sys
from ctypes import wintypes

MSG_MAGIC = 0x43533254
pipe_name = "\\\\.\\pipe\\CS2ToolMCP"
dll_path = r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injected_dll\build_msvc\Release\cs2_tool.dll"

print(f"[1] Loading DLL...", flush=True)
dll = ctypes.WinDLL(dll_path)
dll.Cs2Tool_Init.restype = ctypes.c_int
dll.Cs2Tool_Version.restype = ctypes.c_char_p
rc = dll.Cs2Tool_Init()
print(f"    Init -> {rc}, Ver -> {dll.Cs2Tool_Version()}", flush=True)

k = ctypes.WinDLL("kernel32", use_last_error=True)

time.sleep(0.5)

print(f"[2] WaitNamedPipe...", flush=True)
ok = k.WaitNamedPipeW(pipe_name, 3000)
err = ctypes.get_last_error()
print(f"    ok={ok}, err={err}", flush=True)
if not ok:
    print("FATAL", flush=True); sys.exit(1)

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
h = k.CreateFileW(pipe_name, 0xC0000000, 0, None, 3, 0, None)
err = ctypes.get_last_error()
print(f"[3] CreateFileW: h=0x{h:x}, err={err}", flush=True)
if h == INVALID_HANDLE_VALUE:
    print("FATAL", flush=True); sys.exit(1)

req = json.dumps({"id":1,"method":"ping"}).encode()
frame = struct.pack("<IIII", MSG_MAGIC, 1, len(req), 0) + req
print(f"[4] Writing {len(frame)} bytes... frame hex[:20]={[hex(b) for b in frame[:20]]}", flush=True)

buf_type = ctypes.c_ubyte * len(frame)
buf = buf_type.from_buffer_copy(frame)

w = wintypes.DWORD()
ok = k.WriteFile(h, buf, len(frame), ctypes.byref(w), None)
err = ctypes.get_last_error()
print(f"    WriteFile: ok={ok}, written={w.value}, err={err}", flush=True)
if not ok:
    print("FATAL WriteFile", flush=True); sys.exit(1)

print(f"[5] Reading response header...", flush=True)
rhdr = ctypes.create_string_buffer(16)
ok = k.ReadFile(h, rhdr, 16, ctypes.byref(w), None)
err = ctypes.get_last_error()
print(f"    ReadFile hdr: ok={ok}, got={w.value}, err={err}", flush=True)
magic, ver, length, _ = struct.unpack("<IIII", bytes(rhdr.raw))
print(f"    magic=0x{magic:x} ver={ver} len={length}", flush=True)

if length > 0:
    resp = ctypes.create_string_buffer(length)
    ok = k.ReadFile(h, resp, length, ctypes.byref(w), None)
    err = ctypes.get_last_error()
    print(f"[6] Response: {bytes(resp.raw[:length])}", flush=True)

k.CloseHandle(h)
dll.Cs2Tool_Shutdown()
print("DONE", flush=True)
