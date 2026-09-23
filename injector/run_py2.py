import subprocess, sys, os

# Run test_dll_standalone.py and show output line by line
proc = subprocess.Popen(
    [sys.executable, "-u",  # unbuffered!
     r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector\test_dll_standalone.py"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    cwd=r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp"
)
try:
    output = b""
    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            print(line.decode(), end='', flush=True)
            output += line
    proc.wait(timeout=15)
    print(f"\n=== Exit: {proc.returncode} ===")
except subprocess.TimeoutExpired:
    proc.kill()
    print("\nTIMED OUT after 15s, killed.")
