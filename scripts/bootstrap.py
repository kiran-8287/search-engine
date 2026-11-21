#!/usr/bin/env python3
"""Set up an OS-local Python environment when explicitly run."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexical-only", action="store_true", help="Skip PyTorch and the dense encoder dependencies")
    parser.add_argument("--no-tests", action="store_true", help="Skip pytest and Playwright's Python plugin")
    parser.add_argument("--browsers", action="store_true", help="Explicitly install Playwright Chromium")
    parser.add_argument("--wheelhouse", type=Path, help="Install without a package index from an OS-specific wheel directory")
    args = parser.parse_args()
    if sys.version_info[:2] not in ((3, 11), (3, 12)):
        parser.error("Use Python 3.11 or 3.12.")
    if args.browsers and (args.no_tests or args.wheelhouse):
        parser.error("Install Chromium separately when using an offline wheelhouse or no test dependencies.")
    home = ROOT / ".venv"
    executable = home / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        venv.EnvBuilder(with_pip=True).create(home)
    extras = ["research"]
    if not args.lexical_only:
        extras.append("dense")
    if not args.no_tests:
        extras.append("test")
    pip = [str(executable), "-m", "pip", "install"]
    if args.wheelhouse:
        pip.extend(("--no-index", "--find-links", str(args.wheelhouse.resolve())))
    subprocess.run([*pip, "-e", f".[{','.join(extras)}]"], cwd=ROOT, check=True)
    subprocess.run([str(executable), "-m", "pip", "check"], cwd=ROOT, check=True)
    if args.browsers:
        subprocess.run([str(executable), "-m", "playwright", "install", "chromium"], cwd=ROOT, check=True)
    example = ROOT / ".env.example"
    try:
        with (ROOT / ".env").open("xb") as output, example.open("rb") as source:
            shutil.copyfileobj(source, output)
    except FileExistsError:
        pass
    prefix = r".\.venv\Scripts\python.exe" if os.name == "nt" else "./.venv/bin/python"
    print(f"{prefix} -m techsearch doctor")
    print(f"{prefix} -m techsearch inspect-data")
    model = "" if args.lexical_only else f"{prefix} -m techsearch download-model"
    if model:
        print(model)
    flags = " --lexical-only" if args.lexical_only else ""
    print(f"{prefix} -m techsearch pipeline --resume{flags}")
    print(f"{prefix} -m techsearch validate-release")
    print(f"{prefix} -m techsearch serve --host 127.0.0.1 --port 8000")


if __name__ == "__main__":
    main()
