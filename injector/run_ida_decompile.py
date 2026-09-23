import subprocess, sys, os

logfile = r"C:\Users\a5767\AppData\Local\Temp\ida_decompile_output.txt"
if os.path.exists(logfile): os.remove(logfile)

proc = subprocess.Popen(
    [sys.executable, "-u", r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector\ida_decompile.py"],
    stdout=open(logfile, 'wb'), stderr=subprocess.STDOUT,
    cwd=r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp"
)
try:
    proc.wait(timeout=120)
    print(f"Exit code: {proc.returncode}")
except subprocess.TimeoutExpired:
    proc.kill()
    print("TIMED OUT after 120s")

if os.path.exists(logfile):
    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    # Print only first 5000 chars
    print(content[:8000])
    if len(content) > 8000:
        print(f"\n... ({len(content) - 8000} more chars, full log at {logfile})")
