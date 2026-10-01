import sys

sys.path.insert(0, r"C:\cs2_tool_mcp\injector")
from ce_call import ce_call  # noqa: E402

HOST = "127.0.0.1"
PORT = 17171

CANDIDATES = [
    ("ping", {}),
    ("get_process_list", {}),
    ("get_process_info", {}),
    ("get_module_list", {}),
    ("list_modules", {}),
    ("get_thread_list", {}),
    ("get_symbol_address", {"module": "hammer.dll", "symbol": "??_7CParticleHelper@@6B@"}),
    ("get_address", {"expression": "hammer.dll+0x24B7C80"}),
    ("read_memory", {"address": "0x0", "size": 8}),
    ("aob_scan", {"pattern": "DE AD BE EF"}),
    ("set_breakpoint", {"address": "0x0"}),
    ("list_breakpoints", {}),
    ("get_breakpoint_hits", {}),
    ("execute_lua", {"code": "return 1+1"}),
    ("lua", {"code": "return 1+1"}),
    ("run_lua", {"script": "return 1+1"}),
    ("eval_lua", {"code": "return 1+1"}),
    ("execute_code", {"code": "return 1"}),
    ("get_register", {"name": "RAX"}),
    ("disassemble", {"address": "hammer.dll+0x0", "count": 2}),
]

for name, params in CANDIDATES:
    try:
        r = ce_call(name, params, HOST, PORT, timeout=20)
    except Exception as e:  # noqa: BLE001
        print(f"{name:22} EXC {type(e).__name__}: {e}")
        continue
    s = str(r)
    print(f"{name:22} {s[:220]}")
