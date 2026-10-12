import subprocess, sys, os
from pathlib import Path
import tempfile

logfile = str(Path(tempfile.gettempdir()) / 'ida_dec2_output.txt')
if os.path.exists(logfile): os.remove(logfile)

proc = subprocess.Popen(
    [sys.executable, "-u", str(Path(__file__).resolve().parent / 'ida_decompile2.py')],
    stdout=open(logfile, 'wb'), stderr=subprocess.STDOUT,
    cwd=str(Path(__file__).resolve().parents[1])
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
