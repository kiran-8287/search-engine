"""Session-scoped search snapshots and explicit feedback in separate files."""
from __future__ import annotations

import math
import os
import re
import time
import uuid
from collections import Counter
from contextlib import contextmanager

from .indexing import tfidf_idf
from .io import now, read_json, read_jsonl, write_json, write_jsonl

IDENTIFIER = re.compile("[a-f0-9]{32}")
EXPIRATION = 7 * 86400
SNAPSHOT_LIMIT = 100
EVENT_LIMIT = 1000


class SnapshotMissing(LookupError):
    pass


@contextmanager
def session_lock(path):
    path.mkdir(parents=True, exist_ok=True)
    with (path / ".lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class Runtime:
    def __init__(self, path):
        path.mkdir(parents=True, exist_ok=True)
        self.path = path

    def session_path(self, session):
        if not isinstance(session, str) or not IDENTIFIER.fullmatch(session):
            raise SnapshotMissing("Session is unavailable.")
        return self.path / session[:2] / session

    def snapshot(self, directory, key):
        if not isinstance(key, str) or not IDENTIFIER.fullmatch(key):
            raise SnapshotMissing("Search snapshot expired or is unavailable in this session.")
        path = directory / (key + ".json")
        if not path.is_file() or path.stat().st_mtime < time.time() - EXPIRATION:
            raise SnapshotMissing("Search snapshot expired or is unavailable in this session.")
        return read_json(path)

    def store(self, session, release, scope, result):
        directory = self.session_path(session)
        with session_lock(directory):
            key = result["search_id"]
            if not IDENTIFIER.fullmatch(key) or (directory / (key + ".json")).exists():
                raise ValueError("Duplicate or invalid search identifier.")
            write_json(directory / (key + ".json"), {"release": release, "scope": scope, "created": now(), "result": result})
            cutoff = time.time() - EXPIRATION
            snapshots = sorted(((file.stat().st_mtime, file) for file in directory.glob("*.json")), reverse=True)
            for index, (modified, file) in enumerate(snapshots):
                if index >= SNAPSHOT_LIMIT or modified < cutoff:
                    file.unlink(missing_ok=True)
        return result

    def get(self, session, key):
        directory = self.session_path(session)
        if not directory.is_dir():
            raise SnapshotMissing("Search snapshot expired or is unavailable in this session.")
        with session_lock(directory):
            return self.snapshot(directory, key)["result"]

    def judge(self, session, key, document, value):
        if value not in (-1, 1):
            raise ValueError("Feedback must be -1 or 1.")
        directory = self.session_path(session)
        if not directory.is_dir():
            raise SnapshotMissing("Search snapshot expired or is unavailable in this session.")
        with session_lock(directory):
            snapshot = self.snapshot(directory, key)
            if not any(hit["id"] == document for hit in snapshot["result"]["results"]):
                raise ValueError("Feedback must refer to a result in the snapshot.")
            path = directory / "feedback.jsonl"
            events = list(read_jsonl(path)) if path.is_file() else []
            events = [event for event in events if (event["snapshot"], event["document"]) != (key, document)]
            events.append({"snapshot": key, "document": document, "value": value, "release": snapshot["release"],
                           "scope": snapshot["scope"], "created": now()})
            write_jsonl(path, events[-EVENT_LIMIT:])

    def judgments(self, session, release, scope):
        if not session:
            return {}
        directory = self.session_path(session)
        path = directory / "feedback.jsonl"
        if not path.is_file():
            return {}
        with session_lock(directory):
            result = {}
            active = set()
            cutoff = time.time() - EXPIRATION
            for file in directory.glob("*.json"):
                if file.stat().st_mtime >= cutoff:
                    active.add(file.stem)
            for event in reversed(list(read_jsonl(path))):
                if event["release"] == release and event["scope"] == scope and event["snapshot"] in active:
                    result.setdefault(event["document"], event["value"])
                if len(result) == 100:
                    break
            return result


def rocchio(index, query, judgments, stable_to_doc, eligible, *, beta=0.75, gamma=0.25, expansion=6):
    """Use normalized vectors of judged parents to adjust and expand a lexical query."""
    accepted = []
    for stable_id, value in judgments.items():
        document_id = stable_to_doc.get(stable_id)
        if document_id is not None and document_id in eligible:
            accepted.append((document_id, value))
    adjusted_query = dict(query)
    if not accepted or not query:
        return adjusted_query, []
    count = index.info["parents"]
    signs = Counter(value for _, value in accepted)
    centroid = Counter()
    for document_id, sign in accepted:
        weighted_terms = {}
        for term, field_counts in index.terms(document_id).items():
            df = index.df(term)
            if term.isalpha() and 4 <= len(term) <= 30 and 1 < df <= max(2, count * 0.3):
                weighted_terms[term] = sum(field_counts.values()) * tfidf_idf(count, df)
        norm = math.sqrt(sum(weight * weight for weight in weighted_terms.values())) or 1
        # Divide by the number of judgments of this sign to get its mean vector.
        factor = (beta if sign == 1 else -gamma) / signs[sign]
        for term, value in weighted_terms.items():
            centroid[term] += factor * value / norm
    base = {term for term, _ in query}
    for (term, field), weight in query.items():
        adjusted_query[term, field] = max(weight * 0.15, weight + centroid[term])
    ranked_terms = sorted(centroid.items(), key=lambda item: (-item[1], item[0]))
    expansion_terms = [term for term, value in ranked_terms if value > 0 and term not in base][:expansion]
    for term in expansion_terms:
        adjusted_query[term, None] = centroid[term]
    return adjusted_query, expansion_terms


def search_id():
    return uuid.uuid4().hex
