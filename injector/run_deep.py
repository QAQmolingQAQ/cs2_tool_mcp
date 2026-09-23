import subprocess, sys, os

logfile = r"C:\Users\a5767\AppData\Local\Temp\deep_test_output.txt"
if os.path.exists(logfile): os.remove(logfile)

proc = subprocess.Popen(
    [sys.executable, "-u", r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector\test_deep.py"],
    stdout=open(logfile, 'wb'), stderr=subprocess.STDOUT,
    cwd=r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp"
)
try:
    proc.wait(timeout=15)
except subprocess.TimeoutExpired:
    proc.kill()

if os.path.exists(logfile):
    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        print(f.read())
