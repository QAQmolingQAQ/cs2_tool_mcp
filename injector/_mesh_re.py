def main():
    import ida_hexrays
    import ida_nalt

    ida_hexrays.init_hexrays_plugin()
    base = ida_nalt.get_imagebase()
    for rva in (0xC4CF60, 0xC4BB60, 0xC4BB20, 0xC4E310, 0xC4DB20, 0x925010):
        try:
            cf = ida_hexrays.decompile(base + rva)
            s = str(cf)
            print("=" * 20, "%#x LEN=%d" % (rva, len(s)), "=" * 20)
            print(s[:2600])
        except Exception as e:
            print(rva, "fail", e)
        print()


main()
