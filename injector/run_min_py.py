import subprocess, sys, os

proc = subprocess.Popen(
    [sys.executable, r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector\test_min_py.py"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True
)
try:
    for line in proc.stdout:
        print(line, end='', flush=True)
    proc.wait(timeout=10)
    print(f"\nExit code: {proc.returncode}")
except subprocess.TimeoutExpired:
    proc.kill()
    print("\nTIMED OUT")
