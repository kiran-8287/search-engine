"""Explicit network acquisition, provenance and resumable stage reporting."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

import requests

from . import corpus
from .io import digest, dumps, file_hash, now, read_json, write_json
from .pipeline import writer_lock

SHA = re.compile(r"[a-f0-9]{40}\Z")


def github_revision(repo, revision):
    if revision:
        if not SHA.fullmatch(revision):
            raise ValueError("Use a full lowercase Git commit SHA.")
        return revision
    try:
        response = requests.get(f"https://api.github.com/repos/{repo}/commits/main", timeout=(10, 30))
        response.raise_for_status()
        pinned = response.json()["sha"]
    except (requests.RequestException, ValueError, KeyError) as error:
        raise RuntimeError(f"Could not resolve a GitHub commit for {repo}: {type(error).__name__}") from error
    if not isinstance(pinned, str) or not SHA.fullmatch(pinned):
        raise ValueError("Unexpected GitHub commit ID.")
    return pinned


def backup_raw(data, relative_paths):
    for relative in relative_paths:
        file = data / "raw" / relative
        if file.is_file():
            target = data / "raw" / "history" / file_hash(file) / file.name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(".tmp")
                shutil.copyfile(file, temporary)
                if file_hash(temporary) != target.parent.name:
                    temporary.unlink(missing_ok=True)
                    raise RuntimeError(f"Raw file changed while preserving {file.name}")
                temporary.replace(target)


def stackoverflow_coverage(state, scope, target):
    """Summarize eligible questions and outstanding answer IDs from a checkpoint."""
    records = state.get("documents", {})
    if isinstance(records, list):
        # Older checkpoints store records in a list instead of an ID-keyed map.
        records = {str(record["question_id"]): record for record in records
                   if isinstance(record, dict) and "question_id" in record}
    eligible_ids = set()
    topics = Counter()
    completed_accepted = set(map(str, state.get("accepted_answer_ids_done", [])))
    pending_accepted = set()
    for question_id, record in records.items():
        try:
            topic = corpus.topic_for_so(record, scope)
        except (ValueError, TypeError, AttributeError):
            continue
        eligible_ids.add(question_id)
        topics[topic] += 1
        accepted_id = record.get("accepted_answer_id")
        if accepted_id and str(accepted_id) not in completed_accepted:
            pending_accepted.add(str(accepted_id))

    completed_supplement = set(map(str, state.get("supplement_question_ids_done", [])))
    return {
        "eligible_questions": len(eligible_ids),
        "raw_checkpoint_questions": len(records),
        "eligible_by_topic": dict(topics),
        "shortfall": max(0, target - len(eligible_ids)),
        "pending_supplement_ids": sorted(eligible_ids - completed_supplement),
        "pending_accepted_ids": sorted(pending_accepted),
        "missing_accepted_ids": state.get("accepted_answers_missing", []),
        "known_answer_failures": len(state.get("answer_request_errors", {})),
        "partition_shortfalls": state.get("question_shortfalls", []),
    }


def collect(settings, source, *, revision=None, target=5000):
    """Run a root collector and record its observed provenance and completion."""
    data = settings.path("data")
    manifest_file = data / "manifests" / f"collection-{source}.json"
    raw_file = data / "raw" / corpus.RAW_FILES[source]
    scope_hash = digest(settings.scope)
    old = read_json(manifest_file) if manifest_file.is_file() else {}
    if source == "stackoverflow" and target not in settings.scope["so_targets"]:
        raise ValueError("Target must be a configured acquisition milestone.")
    with writer_lock(settings.root):
        if source == "mdn":
            pinned = github_revision("mdn/content", revision or old.get("requested_revision"))
            script = settings.root / "collect_mdn.py"
            names = [raw_file.name, "mdn_source_path_to_url.json", "mdn_collection_report.json"]
        else:
            if not os.getenv("STACKEXCHANGE_API_KEY"):
                manifest = {"source": source, "status": "blocked", "reason": "STACKEXCHANGE_API_KEY is missing",
                            "target": target, "recorded_at": now()}
                if old:
                    manifest["previous"] = {k: v for k, v in old.items() if k != "previous"}
                write_json(manifest_file, manifest)
                return manifest
            pinned = None
            script = settings.root / "collect_stackoverflow.py"
            names = [raw_file.name]
        backup_raw(data, names)
        version = file_hash(script)
        manifest = {"source": source, "started_at": now(), "status": "running", "collector_sha256": version,
                    "requested_revision": pinned, "target": target if source == "stackoverflow" else None,
                    "run_fingerprint": digest([source, version, pinned, target, scope_hash])}
        write_json(manifest_file, manifest)
        env = {**os.environ, "TECHSEARCH_PROJECT_DIR": str(settings.root), "TECHSEARCH_DATA_DIR": str(data),
               "TECHSEARCH_SO_TARGET": str(target)}
        if pinned:
            env["TECHSEARCH_MDN_REVISION"] = pinned
            env["TECHSEARCH_MDN_TOPIC_PATHS"] = dumps(list(settings.scope["mdn_roots"]))
        try:
            code = subprocess.run([sys.executable, "-u", str(script)], cwd=settings.root, env=env, check=False).returncode
        except KeyboardInterrupt:
            code = 130
        manifest.update(exit_code=code, finished_at=now(),
                        raw_hashes={name: file_hash(data / "raw" / name) for name in names if (data / "raw" / name).is_file()})
        if source == "mdn":
            archive = data / "downloads/mdn" / pinned / "mdn_content.zip"
            report_path = data / "raw/mdn_collection_report.json"
            details = read_json(report_path) if not code and report_path.is_file() else {}
            manifest.update(archive_sha256=file_hash(archive) if archive.is_file() else None,
                            source_revision=pinned if not code and archive.is_file() and raw_file.is_file() else None,
                            discovered=details.get("files_discovered"), saved=details.get("documents_saved"),
                            parse_failures=details.get("parse_errors", []), topics=details.get("topics", {}))
            complete = bool(manifest["source_revision"] and manifest["saved"] and not manifest["parse_failures"]
                            and len(manifest["topics"]) == len(settings.scope["mdn_roots"])
                            and all(topic["path_available"] for topic in manifest["topics"].values()))
        else:
            checkpoint = settings.root / "stackoverflow_checkpoint.json"
            state = read_json(checkpoint) if checkpoint.is_file() else {}
            manifest.update(stackoverflow_coverage(state, settings.scope, target))
            complete = bool(not code and raw_file.is_file() and not manifest["shortfall"]
                            and not manifest["pending_supplement_ids"] and not manifest["pending_accepted_ids"])
        manifest["status"] = "complete" if complete else "partial" if manifest["raw_hashes"] else "blocked"
        if not complete:
            manifest["reason"] = "Collector interrupted or failed" if code else "Incomplete scope, quota, source or answer coverage; inspect stage details"
        write_json(manifest_file, manifest)
        return manifest


def collect_compat(settings, revision=None):
    data = settings.path("data")
    target = data / "raw/browser_compat.json"
    old = read_json(target) if target.is_file() else {}
    sha = github_revision("mdn/browser-compat-data", revision or old.get("revision"))
    cache = data / "downloads/bcd" / f"{sha}.tar.gz"
    entries = {}
    with writer_lock(settings.root):
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.is_file():
            try:
                with (
                    requests.get(f"https://codeload.github.com/mdn/browser-compat-data/tar.gz/{sha}",
                                 timeout=(10, 60), stream=True) as response,
                    tempfile.NamedTemporaryFile(dir=cache.parent, delete=False) as out,
                ):
                    temporary = Path(out.name)
                    try:
                        response.raise_for_status()
                        downloaded = 0
                        for chunk in response.iter_content(1024 * 1024):
                            downloaded += len(chunk)
                            if downloaded > 256 * 1024 * 1024:
                                raise ValueError("BCD download exceeds its archive budget.")
                            out.write(chunk)
                        out.close()
                        temporary.replace(cache)
                    finally:
                        if not out.closed:
                            out.close()
                        temporary.unlink(missing_ok=True)
            except requests.RequestException as error:
                raise RuntimeError(f"BCD download failed: {type(error).__name__}") from error
        import json

        def traverse(value, path):
            if not isinstance(value, dict):
                return
            compatibility = value.get("__compat")
            if isinstance(compatibility, dict):
                link = corpus.url(compatibility.get("mdn_url"))
                if link and link.startswith("https://developer.mozilla.org/"):
                    entries.setdefault(corpus.alias_key(link), []).append(
                        {"feature": ".".join(path), "status": compatibility.get("status"),
                         "support": compatibility.get("support"), "mdn_url": link}
                    )
            for key, child in value.items():
                if key != "__compat":
                    traverse(child, [*path, key])
        with tarfile.open(cache, "r:gz") as archive:
            for member in archive:
                parts = Path(member.name).parts
                if (member.isfile() and member.name.endswith(".json") and member.size <= 16 * 1024 * 1024
                        and len(parts) > 2 and parts[1] in {"api", "css", "html", "javascript", "http", "svg", "webassembly"}):
                    with archive.extractfile(member) as stream:
                        traverse(json.load(stream), [])
        if not entries:
            raise ValueError("No BCD MDN mappings found in the pinned archive.")
        backup_raw(data, [target.name])
        write_json(target, {"revision": sha, "archive_sha256": file_hash(cache), "license": "CC0-1.0", "entries": entries})
    return {"revision": sha, "url_keys": len(entries), "archive_sha256": file_hash(cache)}
