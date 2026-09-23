import subprocess, sys, os, time

# Kill stray
subprocess.run("taskkill /f /im python.exe /fi \"WINDOWTITLE eq *cs2*\" 2>nul", shell=True, capture_output=True)

os.chdir(r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp")

proc = subprocess.Popen(
    [sys.executable, r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector\test_dll_standalone.py"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    cwd=r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp"
)
try:
    stdout, stderr = proc.communicate(timeout=20)
    print(stdout)
    if stderr: print("STDERR:", stderr)
except subprocess.TimeoutExpired:
    proc.kill()
    stdout, stderr = proc.communicate()
    print("TIMED OUT!")
    print(stdout)
    print(stderr)
