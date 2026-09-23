import subprocess, sys, os, time

# Kill any stray processes
subprocess.run("taskkill /f /im test_pipe_client.exe 2>nul", shell=True, capture_output=True)
subprocess.run("taskkill /f /im cs2_tool.exe 2>nul", shell=True, capture_output=True)

env = os.environ.copy()
env["INCLUDE"] = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC\14.44.35207\include;"
    r"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um;"
    r"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared;"
    r"C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt"
)
env["LIB"] = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC\14.44.35207\lib\x64;"
    r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64;"
    r"C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64"
)
env["PATH"] = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64;"
    r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64;" + env["PATH"]
)

cpp_file = r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector\test_pipe_client.cpp"
exe_file = r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector\test_pipe_client.exe"

print("=== Compiling ===")
cl_path = r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"
compile_proc = subprocess.run(
    [cl_path, "/EHsc", "/std:c++20", "/O2", cpp_file, f"/Fe:{exe_file}", "/link", "kernel32.lib"],
    capture_output=True, text=True, env=env, cwd=r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector"
)
print(compile_proc.stdout[-500:] if compile_proc.stdout else "")
if compile_proc.returncode != 0:
    print("COMPILE FAILED!")
    print(compile_proc.stderr)
    sys.exit(1)
print("Compile OK!")

print("\n=== Running ===")
proc = subprocess.Popen([exe_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, cwd=r"d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector")
try:
    stdout, stderr = proc.communicate(timeout=15)
    print(f"Exit code: {proc.returncode}")
    print("--- STDOUT ---")
    print(stdout)
    if stderr:
        print("--- STDERR ---")
        print(stderr)
except subprocess.TimeoutExpired:
    proc.kill()
    stdout, stderr = proc.communicate()
    print("TIMED OUT after 15s!")
    print(f"STDOUT so far:\n{stdout}")
    print(f"STDERR:\n{stderr}")
