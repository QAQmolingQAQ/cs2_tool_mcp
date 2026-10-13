"""Configure, start, or inspect a local IDA database on its fixed MCP port."""
import argparse
import json
from pathlib import Path
import subprocess
import socket
import urllib.request
ROOT = Path(__file__).resolve().parents[1]
MODULES = json.loads((ROOT / "config/ida_modules.json").read_text(encoding="utf-8"))

def status(module):
    row = MODULES[module]
    request = urllib.request.Request(
        f"http://{row['host']}:{row['port']}/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.load(response)
        if "error" in data:
            return {"module": module, "online": False, "error": data["error"]}
        identity = urllib.request.Request(f"http://{row['host']}:{row['port']}/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "py_eval", "arguments": {"code": "import idc;print(idc.get_idb_path())"}}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(identity, timeout=10) as response:
            payload = json.load(response)["result"]
        if payload.get("isError"):
            raise RuntimeError("IDA database identity query failed")
        output = payload.get("structuredContent") or json.loads(payload["content"][0]["text"])
        database = Path(output["stdout"].strip()).name
        if database != row["database"]:
            raise RuntimeError(f"Unexpected database on port {row['port']}: {database}")
        return {"module": module, "online": True, "tools": len(data["result"]["tools"]),
                "port": row["port"], "database": database, "identity_verified": True}
    except Exception as error:
        return {"module": module, "online": False, "error": str(error), "port": row["port"]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "start", "status"))
    parser.add_argument("module", choices=tuple(MODULES) + ("all",))
    parser.add_argument("--db-root", type=Path, default=Path(r"C:\cs2_tool_mcp\ida_db"))
    parser.add_argument("--ida-root", type=Path, default=Path(r"C:\deprogram\IDA Professional 9.1"))
    args = parser.parse_args()
    names = list(MODULES) if args.module == "all" else [args.module]
    if args.action == "start" and args.module == "all":
        parser.error("start one module at a time to limit memory use")
    for module in names:
        row = MODULES[module]
        database = args.db_root / row["database"]
        if args.action == "status":
            print(json.dumps(status(module)), flush=True)
            continue
        if not database.is_file():
            raise FileNotFoundError(database)
        if args.action == "configure":
            if database.with_suffix(".id0").exists() or status(module)["online"]:
                raise RuntimeError("Database appears open; do not configure it through a second IDA process")
            subprocess.run([str(args.ida_root / "idat.exe"), "-A",
                            "-L" + str(args.db_root / (module + "_mcp_port.log")),
                            "-S" + str(ROOT / "scripts/ida_set_module_port.py"), str(database)], check=True)
            print("configured " + module + ":" + str(row["port"]), flush=True)
        else:
            if status(module)["online"]:
                print(json.dumps(status(module)))
                continue
            with socket.socket() as probe:
                try:
                    probe.bind((row["host"], row["port"]))
                except OSError as error:
                    raise RuntimeError("Fixed IDA port is occupied by an unverified service") from error
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            child = subprocess.Popen([str(args.ida_root / "ida.exe"), str(database)],
                                     startupinfo=startup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(json.dumps({"module": module, "started_pid": child.pid, "port": row["port"]}))
if __name__ == "__main__":
    main()
