import subprocess, sys, os
from pathlib import Path
import tempfile

logfile = str(Path(tempfile.gettempdir()) / 'ida_decompile_output.txt')
if os.path.exists(logfile): os.remove(logfile)

proc = subprocess.Popen(
    [sys.executable, "-u", str(Path(__file__).resolve().parent / 'ida_decompile.py')],
    stdout=open(logfile, 'wb'), stderr=subprocess.STDOUT,
    cwd=str(Path(__file__).resolve().parents[1])
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
