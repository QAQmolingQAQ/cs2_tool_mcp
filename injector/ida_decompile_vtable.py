# IDAPython script: Decompile CHammerApp vtable functions
# Run this in IDA's File -> Script file... or Python console

import ida_idaapi
import idc
import idaapi
import ida_hexrays
import ida_funcs

# From our live memory test:
# hammer_base (IDA imagebase) = 0x180000000
# ASLR slide in this session: runtime_base - imagebase
# We need to calculate runtime addresses from RVAs

# vtable entries RVAs we found:
vtable_rvas = {
    0: 0x117940,
    1: 0x118670,
    2: 0x1364c20,
    3: 0x1364be0,
    4: 0x1363dc0,
    5: 0x753a0,
    6: 0x1156a0,
    7: 0xe7e50,
    8: 0x11f450,
    9: 0xa12e0,
    10: 0xa3f10,
    11: 0x1360690,
    12: 0x11f400,
    13: 0x1363e60,
    14: 0x135f940,
    15: 0x753a0,  # duplicate of [5]
}

imagebase = ida_idaapi.get_imagebase()
print(f"IDA ImageBase: 0x{imagebase:x}")

# Decompile each
for idx, rva in vtable_rvas.items():
    addr = imagebase + rva
    func = ida_funcs.get_func(addr)
    if not func:
        print(f"\n=== vtable[{idx}] 0x{addr:x} (RVA 0x{rva:x}) - NO FUNCTION ===")
        continue

    fname = idc.get_func_name(addr)
    print(f"\n{'='*60}")
    print(f"vtable[{idx}] 0x{addr:x} (RVA 0x{rva:x})")
    print(f"Function: {fname}")

    # Try decompile
    cfunc = ida_hexrays.decompile(addr)
    if cfunc:
        print(f"{'='*60}")
        print(str(cfunc)[:1500])  # first 1500 chars
    else:
        print(f"  Decompilation failed at 0x{addr:x}")

print("\n\n=== DONE ===")
