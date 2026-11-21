#!/usr/bin/env python3
"""Invoke the package-demo command using the project's installed package."""
import sys

from techsearch.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["package-demo", *sys.argv[1:]]))
