import ctypes, struct, json, time, sys
from ctypes import wintypes

pipe_name = "\\\\.\\pipe\\CS2ToolMCP"
print(f"pipe_name repr: {repr(pipe_name)}")

dll = ctypes.WinDLL(r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injected_dll\build_msvc\Release\cs2_tool.dll")
dll.Cs2Tool_Init.restype = ctypes.c_int
rc = dll.Cs2Tool_Init()
print(f"Cs2Tool_Init = {rc}")
time.sleep(0.5)

k = ctypes.WinDLL("kernel32", use_last_error=True)
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

ok = k.WaitNamedPipeW(pipe_name, 5000)
print(f"WaitNamedPipe: ok={ok}, err={ctypes.get_last_error()}")

h = k.CreateFileW(pipe_name, GENERIC_READ|GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
err = ctypes.get_last_error()
print(f"CreateFileW: h={h}, err={err}")

if h != INVALID_HANDLE_VALUE:
    req = json.dumps({"id":1,"method":"ping"}).encode()
    hdr = struct.pack("<IIII", 0x43533254, 1, len(req), 0)
    w = wintypes.DWORD()
    ok = k.WriteFile(h, hdr + req, 16 + len(req), ctypes.byref(w), None)
    print(f"WriteFile: ok={ok}, written={w.value}, err={ctypes.get_last_error()}")

    rhdr = ctypes.create_string_buffer(16)
    ok = k.ReadFile(h, rhdr, 16, ctypes.byref(w), None)
    print(f"ReadFile hdr: ok={ok}, got={w.value}, err={ctypes.get_last_error()}")
    magic, ver, length, _ = struct.unpack("<IIII", bytes(rhdr.raw))
    print(f"magic=0x{magic:x} ver={ver} len={length}")

    if length > 0:
        buf = ctypes.create_string_buffer(length)
        ok = k.ReadFile(h, buf, length, ctypes.byref(w), None)
        print(f"RESPONSE: {bytes(buf.raw)}")

    k.CloseHandle(h)
else:
    print("FAILED to open pipe")

dll.Cs2Tool_Shutdown()
print("DONE")
