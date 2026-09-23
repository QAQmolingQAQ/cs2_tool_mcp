import subprocess, sys
result = subprocess.run(
    [sys.executable, r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector\test_detailed.py"],
    capture_output=True, text=True, timeout=15
)
print("=== STDOUT ===")
print(result.stdout)
print("=== STDERR ===")
print(result.stderr)
print(f"Exit code: {result.returncode}")
