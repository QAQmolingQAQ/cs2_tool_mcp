"""Run inside IDA to persist this database's fixed MCP endpoint."""
from pathlib import Path
import json
import ida_netnode
import idc
root = Path(__file__).resolve().parents[1]
modules = json.loads((root / "config/ida_modules.json").read_text(encoding="utf-8"))
database = Path(idc.get_idb_path()).name
matches = [(name, row) for name, row in modules.items() if row["database"] == database]
if len(matches) != 1:
    raise RuntimeError(f"Unknown IDA database: {database}")
name, row = matches[0]
node = ida_netnode.netnode("$ ida_mcp.config", 0, True)
node.altset(0, row["port"])
node.altset(1, 2)
node.supset(0, row["host"])
ida_netnode.netnode("$ ida_mcp.autostart", 0, True).altset(0, 2)
print(f"MCP endpoint persisted: {name} {row['host']}:{row['port']}")
idc.qexit(0)
