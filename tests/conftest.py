from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from techsearch.config import load_settings
from techsearch.pipeline import build, open_release, preprocess
from techsearch.service import SearchService

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    parser.addoption("--browser-executable", help="Use an installed browser compatible with the host OS")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, pytestconfig):
    executable = pytestconfig.getoption("--browser-executable")
    return {**browser_type_launch_args, **({"executable_path": executable} if executable else {})}


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    for name in ("config",):
        shutil.copytree(ROOT / name, tmp_path / name)
    (tmp_path / "frontend" / "assets").mkdir(parents=True)
    shutil.copy2(ROOT / "frontend/index.html", tmp_path / "frontend/index.html")
    shutil.copy2(ROOT / "frontend/lab.html", tmp_path / "frontend/lab.html")
    for directory in ("css", "js"):
        shutil.copytree(ROOT / "frontend/assets" / directory, tmp_path / "frontend/assets" / directory)
    for file in (ROOT / "tests/fixtures").glob("*.json"):
        shutil.copy2(file, tmp_path / file.name)
    monkeypatch.delenv("STACKEXCHANGE_API_KEY", raising=False)
    monkeypatch.delenv("TECHSEARCH_ANNOTATION_API_KEY", raising=False)
    for key in os.environ.copy():
        if key.startswith("TECHSEARCH_CFG__"):
            monkeypatch.delenv(key, raising=False)
    config = load_settings(tmp_path)
    config.default["resources"]["postings_shard_rows"] = 75
    return config


@pytest.fixture()
def release(settings):
    preprocess(settings)
    build(settings, lexical_only=True)
    return open_release(settings, verify=True)


@pytest.fixture()
def service(settings, release):
    return SearchService(settings, release, persistent=True)
