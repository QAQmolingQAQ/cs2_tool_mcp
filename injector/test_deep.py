#!/usr/bin/env python3
"""Deep test: read real addresses from hammer.exe."""
import ctypes, struct, json, time, sys
from ctypes import wintypes

MSG_MAGIC = 0x43533254
pipe_name = "\\\\.\\pipe\\CS2ToolMCP"

k = ctypes.WinDLL("kernel32", use_last_error=True)
ok = k.WaitNamedPipeW(pipe_name, 3000)
if not ok: print("Pipe not available"); sys.exit(1)

h = k.CreateFileW(pipe_name, 0xC0000000, 0, None, 3, 0, None)
if h == wintypes.HANDLE(-1).value: print("CreateFileW failed"); sys.exit(1)

def call(method, params=None):
    req_obj = {"id": int(time.time()*1000)&0x7FFFFFFF, "method": method}
    if params is not None:
        req_obj["params"] = params
    payload = json.dumps(req_obj).encode()
    frame = struct.pack("<IIII", MSG_MAGIC, 1, len(payload), 0) + payload
    buf = (ctypes.c_ubyte * len(frame)).from_buffer_copy(frame)
    w = wintypes.DWORD()
    k.WriteFile(h, buf, len(frame), ctypes.byref(w), None)
    rhdr = ctypes.create_string_buffer(16)
    k.ReadFile(h, rhdr, 16, ctypes.byref(w), None)
    _, _, length, _ = struct.unpack("<IIII", bytes(rhdr.raw))
    if length > 0:
        resp = ctypes.create_string_buffer(length)
        k.ReadFile(h, resp, length, ctypes.byref(w), None)
        return json.loads(bytes(resp.raw[:length]))
    return {}

# Get status
s = call("get_status")["result"]
hammer_base = s["hammer_base"]
ci = s["create_interface"]
app = s["tool_system"]

print(f"=== Real Hammer.exe Addresses ===")
print(f"hammer_base      = 0x{hammer_base:x}")
print(f"CreateInterface  = 0x{ci:x}  (offset: 0x{ci - hammer_base:x})")
print(f"CHammerApp*      = 0x{app:x}")
print()

# Calculate expected CreateInterface RVA from IDA: 0x12E1B50
ida_rva = 0x12E1B50
expected = hammer_base + ida_rva
print(f"IDA CreateInterface RVA = 0x{ida_rva:x}")
print(f"Expected CI address    = 0x{expected:x}")
print(f"Actual CI address      = 0x{ci:x}")
print(f"Match: {expected == ci}")
print()

# Check interfaces more deeply
print("=== Interface Chain ===")
ifaces = call("list_interfaces")["result"]
for i, name in enumerate(ifaces):
    print(f"  [{i}] {name}")

# Try to get ToolSystem2_001 interface pointer
print("\n=== Get ToolSystem2_001 ===")
r = call("get_interface", {"name": "ToolSystem2_001"})
if "result" in r:
    res = r["result"]
    print(f"  name      = {res['name']}")
    print(f"  rc        = {res['return_code']}")
    print(f"  pointer   = 0x{res['pointer']:x}")
else:
    print(f"  error: {r.get('error')}")

# Read vtable from CHammerApp
print(f"\n=== CHammerApp VTable ===")
if app and app != 0:
    r = call("read_qword", {"address": app})
    vftable = r["result"]["value"] if "result" in r else 0
    print(f"  CHammerApp ptr       = 0x{app:x}")
    print(f"  *CHammerApp (vtable) = 0x{vftable:x}")
    if vftable:
        # Read first 16 vtable entries
        print(f"\n  First 16 vtable entries:")
        for i in range(16):
            entry_addr = vftable + i * 8
            r = call("read_qword", {"address": entry_addr})
            v = r["result"]["value"] if "result" in r else 0
            print(f"    [{i:2d}] 0x{v:x}  (RVA: 0x{(v - hammer_base):x}" if v > hammer_base else f"    [{i:2d}] 0x{v:x}", end="")
            if v > 0 and v < 0x1000000:
                print(f"  < 1MB (likely invalid)>")
            elif v > hammer_base:
                print("  <- in hammer module>")
            else:
                print()

# Read DOS header + e_lfanew
print(f"\n=== PE Header Check ===")
if hammer_base:
    r = call("read_qword", {"address": hammer_base})
    print(f"  DOS header first 8 bytes: 0x{r['result']['hex']}")
    # e_lfanew is at offset 0x3C
    r = call("read_memory", {"address": hammer_base + 0x3C, "size": 4})
    import struct as st
    e_lfanew = int(r['result']['hex'], 16)
    print(f"  e_lfanew = 0x{e_lfanew:x}")
    nt_addr = hammer_base + e_lfanew
    r = call("read_dword", {"address": nt_addr}) if False else None
    # Read NT signature
    r = call("read_memory", {"address": nt_addr, "size": 4})
    print(f"  NT signature: 0x{r['result']['hex']}")
    # ImageBase from OptionalHeader (offset 0x10 from NT header + 0x10 from signature+machine+sections+timedatestamp+ptr+nsyms)
    # Actually NT headers: Signature(4) + FileHeader(20) + OptionalHeader(variable)
    # OptionalHeader starts at e_lfanew + 24, ImageBase is at offset 24 in OptionalHeader
    opt_hdr = nt_addr + 24
    # For PE32+, ImageBase at +24 is 8 bytes
    r = call("read_qword", {"address": opt_hdr + 24})
    print(f"  PE OptionalHeader.ImageBase = 0x{r['result']['hex']}")
    print(f"  ASLR slide: 0x{(hammer_base - int(r['result']['hex'], 16)):x}")

k.CloseHandle(h)
