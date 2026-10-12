#!/usr/bin/env python3
"""Legacy script/import entry point. Implementation lives in hammer_mcp."""
from pathlib import Path
import sys

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from hammer_mcp import compat as _compat


def __getattr__(name):
    return getattr(_compat, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_compat)))


def main():
    from hammer_mcp.app import main as run
    run()


if __name__ == "__main__":
    main()
