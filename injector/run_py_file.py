import subprocess, sys, os
from pathlib import Path
import tempfile

logfile = str(Path(tempfile.gettempdir()) / 'py_test_output.txt')
if os.path.exists(logfile): os.remove(logfile)

proc = subprocess.Popen(
    [sys.executable, "-u", str(Path(__file__).resolve().parent / 'test_dll_standalone.py')],
    stdout=open(logfile, 'wb'), stderr=subprocess.STDOUT,
    cwd=str(Path(__file__).resolve().parents[1])
)
try:
    proc.wait(timeout=15)
    print(f"Exit code: {proc.returncode}")
except subprocess.TimeoutExpired:
    proc.kill()
    print("TIMED OUT - killed after 15s")

# Print output
if os.path.exists(logfile):
    with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
        print(f.read())
