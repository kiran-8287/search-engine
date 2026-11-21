from __future__ import annotations

import hashlib
import csv
import io
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2
INDEX_VERSION = 2
ANALYZER_VERSION = "web-identifiers-v2"
CHUNK_VERSION = "section-token-spans-v1"
ROUTER_VERSION = "rules-v1"


class WorkloadError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def file_hash(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def peak_process_memory():
    """Report process-lifetime peak resident bytes on the supported laptop OSs."""
    if sys.platform.startswith("linux"):
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("page_faults", wintypes.DWORD),
                        ("peak_working_set", ctypes.c_size_t), ("working_set", ctypes.c_size_t),
                        ("peak_paged_pool", ctypes.c_size_t), ("paged_pool", ctypes.c_size_t),
                        ("peak_nonpaged_pool", ctypes.c_size_t), ("nonpaged_pool", ctypes.c_size_t),
                        ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t)]

        get_process = ctypes.windll.kernel32.GetCurrentProcess
        get_process.restype = wintypes.HANDLE
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = (wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD)
        get_memory.restype = wintypes.BOOL
        counters = MemoryCounters()
        counters.size = ctypes.sizeof(counters)
        if get_memory(get_process(), ctypes.byref(counters), counters.size):
            return counters.peak_working_set
    return None


def read_json(path):
    with path.open(encoding="utf-8-sig") as file:
        return json.load(file)


def write_json(path, value):
    with atomic_file(path) as file:
        file.write((dumps(value) + "\n").encode("utf-8"))


def write_jsonl(path, rows):
    with atomic_file(path) as file:
        for row in rows:
            file.write((dumps(row) + "\n").encode("utf-8"))


def read_jsonl(path):
    with path.open(encoding="utf-8") as file:
        for line in file:
            yield json.loads(line)


def csv_cell(value):
    if isinstance(value, str) and (value[:1] in {"\t", "\r", "\n"} or value.lstrip()[:1] in {"=", "+", "-", "@"}):
        return "'" + value
    return value


def write_csv(path, headings, rows):
    with atomic_file(path) as stream:
        line = io.StringIO(newline="")
        writer = csv.writer(line)
        writer.writerow(headings)
        stream.write(line.getvalue().encode("utf-8"))
        for row in rows:
            line.seek(0)
            line.truncate()
            writer.writerow(map(csv_cell, row))
            stream.write(line.getvalue().encode("utf-8"))


def filesystem_path(path):
    if os.name != "nt":
        return path
    absolute = str(path.absolute())
    if absolute.startswith("\\\\?\\"):
        return path
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


@contextmanager
def atomic_file(path):
    path = filesystem_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".techsearch-", delete=False) as file:
            temporary = Path(file.name)
            yield file
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
