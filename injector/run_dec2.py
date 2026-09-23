import subprocess, sys, os

logfile = r"C:\Users\a5767\AppData\Local\Temp\ida_dec2_output.txt"
if os.path.exists(logfile): os.remove(logfile)

proc = subprocess.Popen(
    [sys.executable, "-u", r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector\ida_decompile2.py"],
    stdout=open(logfile, 'wb'), stderr=subprocess.STDOUT,
    cwd=r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp"
)
try:
    proc.wait(timeout=180)
    print(f"Exit code: {proc.returncode}")
except subprocess.TimeoutExpired:
    proc.kill()
    print("TIMED OUT after 180s")

if os.path.exists(logfile):
    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    print(content[:10000])
    if len(content) > 10000:
        print(f"\n... ({len(content) - 10000} more in {logfile})")
