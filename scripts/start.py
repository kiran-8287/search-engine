#!/usr/bin/env python3
"""Start the existing TechSearch release with the project-local environment."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    executable = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        print("Project environment missing. Run python scripts/bootstrap.py first.", file=sys.stderr)
        return 2
    try:
        return subprocess.call([str(executable), "-m", "techsearch", "--root", str(ROOT), "serve", *sys.argv[1:]], cwd=ROOT)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
