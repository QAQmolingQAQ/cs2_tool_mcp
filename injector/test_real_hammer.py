#!/usr/bin/env python3
"""End-to-end test: pipe IPC against injected DLL in real hammer.exe."""
import ctypes, struct, json, time, sys
from ctypes import wintypes

MSG_MAGIC = 0x43533254
pipe_name = "\\\\.\\pipe\\CS2ToolMCP"

k = ctypes.WinDLL("kernel32", use_last_error=True)

# Wait for pipe
print("[1] Waiting for pipe...")
for i in range(10):
    ok = k.WaitNamedPipeW(pipe_name, 1000)
    err = ctypes.get_last_error()
    if ok:
        print(f"  Pipe available after {i+1}s!")
        break
    if err != 161:
        print(f"  WaitNamedPipe err={err}")
else:
    print("FATAL: Pipe not available")
    sys.exit(1)

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
h = k.CreateFileW(pipe_name, 0xC0000000, 0, None, 3, 0, None)
if h == INVALID_HANDLE_VALUE:
    print(f"CreateFileW err={ctypes.get_last_error()}")
    sys.exit(1)
print(f"[2] Connected handle=0x{h:x}")

def call(method, params=None):
    import json
    req_obj = {"id": int(time.time()*1000)&0x7FFFFFFF, "method": method}
    if params is not None:
        req_obj["params"] = params
    payload = json.dumps(req_obj).encode()
    frame = struct.pack("<IIII", MSG_MAGIC, 1, len(payload), 0) + payload

    # Write
    buf_type = ctypes.c_ubyte * len(frame)
    buf = buf_type.from_buffer_copy(frame)
    w = wintypes.DWORD()
    ok = k.WriteFile(h, buf, len(frame), ctypes.byref(w), None)
    if not ok:
        print(f"  WriteFile err={ctypes.get_last_error()}")
        return None

    # Read header
    rhdr = ctypes.create_string_buffer(16)
    ok = k.ReadFile(h, rhdr, 16, ctypes.byref(w), None)
    magic, ver, length, _ = struct.unpack("<IIII", bytes(rhdr.raw))

    # Read payload
    if length > 0:
        resp = ctypes.create_string_buffer(length)
        k.ReadFile(h, resp, length, ctypes.byref(w), None)
        return json.loads(bytes(resp.raw[:length]))
    return {}

# Run tests
tests = [
    ("ping", None),
    ("get_status", None),
    ("list_interfaces", None),
    ("get_hammer_app", None),
    ("initialize", None),
    ("list_tools", None),
]

ok_count = 0
for method, params in tests:
    print(f"\n--- {method} ---")
    resp = call(method, params)
    if resp is None:
        print(f"  FAIL (pipe error)")
        continue
    if "error" in resp:
        print(f"  ERROR: {resp['error']}")
    else:
        result = resp.get("result", {})
        print(f"  OK: {json.dumps(result, ensure_ascii=False)[:500]}")
        ok_count += 1

print(f"\n{'='*50}")
print(f"RESULT: {ok_count}/{len(tests)} OK")

# Also test read_memory if hammer_base was found
resp = call("get_status")
if resp and "result" in resp:
    hammer_base = resp["result"].get("hammer_base", 0)
    if hammer_base and hammer_base != 0:
        print(f"\n[bonus] hammer_base=0x{hammer_base:x}, testing read_memory...")
        # Read first 16 bytes of hammer module (should be DOS header MZ)
        r2 = call("read_memory", {"address": hammer_base, "size": 16})
        if r2 and "result" in r2:
            print(f"  MZ header: {r2['result'].get('hex', '?')}")
        r3 = call("read_qword", {"address": hammer_base})
        if r3 and "result" in r3:
            print(f"  First qword: {r3['result'].get('hex', '?')}")
    else:
        print(f"\n[note] hammer_base=0 — HammerBridge didn't find hammer.dll in this context")

k.CloseHandle(h)
print("\nDONE")
