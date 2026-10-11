def _main():
    import ida_hexrays, idautils, idc, ida_funcs

    ea = 0x18080DAA0
    f = ida_funcs.get_func(ea)
    print("sub_18080DAA0 size", f.end_ea - f.start_ea)
    print(str(ida_hexrays.decompile(ea))[:3000])
    print("--- callers ---")
    for r in idautils.XrefsTo(ea):
        g = ida_funcs.get_func(r.frm)
        print("  ", hex(r.frm), idc.get_func_name(r.frm) or "-",
              "size", (g.end_ea - g.start_ea) if g else "?")


_main()
