"""Immutable builds and atomic activation of complete, content-addressed releases."""
from __future__ import annotations

import os
import errno
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from . import corpus, dense, graph, indexing
from .compression import CODECS
from .io import ANALYZER_VERSION, CHUNK_VERSION, INDEX_VERSION, SCHEMA_VERSION, digest, file_hash, now, peak_process_memory, read_json, write_json
from .repository import CORPUS_FILES, PASSAGE_FILES, Documents, Passages

RELEASE_ID = re.compile(r"[a-f0-9]{24}\Z")


class ReleaseUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    path: Path
    info: dict

    @property
    def id(self):
        return self.info["release_id"]


@contextmanager
def staging(home):
    home.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix=".techsearch-build-", dir=home)
    try:
        folder = Path(temporary.name) / "files"
        folder.mkdir()
        yield folder
    finally:
        # NFS can briefly retain an unlinked open file while an interrupted
        # writer closes. Retry that transient cleanup failure without masking
        # the interruption or changing any completed release/checkpoint.
        for attempt in range(5):
            try:
                temporary.cleanup()
                break
            except OSError as error:
                if error.errno not in {errno.ENOTEMPTY, errno.EBUSY} or attempt == 4:
                    raise
                time.sleep(.1 * 2 ** attempt)


@contextmanager
def writer_lock(home):
    home.mkdir(parents=True, exist_ok=True)
    path = home / ".writer.lock"
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"Build or collection lock exists at {path}. If a previous process crashed, verify it has stopped before removing the lock.") from error
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def preprocess(settings):
    data = settings.path("data")
    inputs = corpus.raw_inputs(settings)
    if not any(corpus.raw_path(settings, name).is_file() for name in corpus.RAW_FILES):
        raise ValueError("Raw collector exports are missing. Run inspect-data.")
    key = digest([SCHEMA_VERSION, settings.scope, inputs])[:24]
    home = data / "processed"
    target = home / key
    if target.is_dir() and (target / "manifest.json").is_file():
        existing = read_json(target / "manifest.json")
        verify_files(target, existing["files"], CORPUS_FILES, hashes=True)
        write_json(home / "current.json", existing)
        return existing
    with staging(home) as folder:
        start = perf_counter()
        stats = corpus.build_corpus(folder, settings)
        if corpus.raw_inputs(settings) != inputs:
            raise ValueError("Raw files changed during preprocessing. Retry after collection finishes.")
        if stats["quarantine"]:
            write_json(data / "quarantine" / f"{key}.json", stats["quarantine"])
        stats["quarantined"] = len(stats.pop("quarantine"))
        files = artifact_info(folder, CORPUS_FILES)
        manifest = {"id": key, "schema_version": SCHEMA_VERSION, "raw": inputs, "scope": digest(settings.scope),
                    "provenance": corpus.source_attestations(settings, inputs),
                    "corpus_sha256": digest(files), "files": files, "seconds": perf_counter() - start,
                    "created_at": now(), "coverage": stats}
        write_json(folder / "manifest.json", manifest)
        folder.rename(target)
    write_json(home / "current.json", manifest)
    return manifest


def build(settings, lexical_only=False):
    data = settings.path("data") / "processed"
    if not (data / "current.json").is_file():
        raise ValueError("Canonical snapshot missing. Run preprocess first.")
    canonical = read_json(data / "current.json")
    if canonical["raw"] != corpus.raw_inputs(settings) or canonical["scope"] != digest(settings.scope):
        raise ValueError("Canonical snapshot is stale. Run preprocess first.")
    if canonical.get("schema_version") != SCHEMA_VERSION or not RELEASE_ID.fullmatch(canonical.get("id", "")):
        raise ValueError("Canonical snapshot needs rebuilding for this storage version.")
    origin = data / canonical["id"]
    verify_files(origin, canonical["files"], CORPUS_FILES, hashes=True)
    if digest(canonical["files"]) != canonical["corpus_sha256"]:
        raise ValueError("Canonical snapshot manifest checksum mismatch.")
    model = None if lexical_only else dense.model_manifest(settings)
    weights = settings.search["field_weights"]
    graph_config = settings.default["graph"]
    components = {
        "lexical": digest([canonical["corpus_sha256"], INDEX_VERSION, ANALYZER_VERSION, weights]),
        "dense": digest([canonical["corpus_sha256"], model, ANALYZER_VERSION, CHUNK_VERSION, settings.dense]) if model else None,
        "graph": digest([canonical["corpus_sha256"], graph_config]),
    }
    key = digest([canonical["id"], components])[:24]
    home = settings.path("artifacts") / "releases"
    target = home / key
    if not target.is_dir():
        previous = None
        if (home / "active.json").is_file():
            existing = read_json(home / "active.json").get("release_id")
            if isinstance(existing, str) and RELEASE_ID.fullmatch(existing):
                previous_path = home / existing
                if (previous_path / "manifest.json").is_file():
                    previous = Release(previous_path, read_json(previous_path / "manifest.json"))
        with staging(home) as folder:
            started = perf_counter()
            for filename in sorted(CORPUS_FILES):
                shutil.copyfile(origin / filename, folder / filename)
            lexical_stats = reuse_component(previous, components, "lexical", folder, indexing.INDEX_FILES)
            if lexical_stats is None:
                lexical_stats = indexing.build_indexes(folder, weights, settings.default["resources"]["postings_shard_rows"])
            dense_stats = None
            if model:
                dense_stats = reuse_component(previous, components, "dense", folder, PASSAGE_FILES)
                if dense_stats is None:
                    verified_previous = None
                    if previous and previous.info.get("dense"):
                        try:
                            verified_previous = open_release(settings, previous.id, verify=True)
                        except ReleaseUnavailable:
                            pass
                    dense_stats = dense.build_dense(folder, settings, model, previous=verified_previous)
            graph_stats = reuse_component(previous, components, "graph", folder, {"graph.json"})
            if graph_stats is None:
                graph_stats = graph.build_graph(folder, graph_config)
            expected = CORPUS_FILES | indexing.INDEX_FILES | {"graph.json"} | (PASSAGE_FILES if dense_stats else set())
            files = artifact_info(folder, expected)
            if sum(entry["bytes"] for entry in files.values()) > settings.default["resources"]["max_artifact_bytes"]:
                raise ValueError("Release exceeds the configured artifact byte budget.")
            info = {"release_id": key, "created_at": now(), "index_version": INDEX_VERSION,
                    "schema_version": SCHEMA_VERSION, "analyzer": ANALYZER_VERSION, "chunker": CHUNK_VERSION,
                    "config_fingerprint": settings.fingerprint, "weights": weights, "graph_config": graph_config,
                    "components": components,
                    "corpus": canonical, "files": files, "lexical": lexical_stats, "dense": dense_stats,
                    "graph": graph_stats, "seconds": perf_counter() - started, "peak_process_rss_bytes": peak_process_memory()}
            write_json(folder / "manifest.json", info)
            folder.rename(target)
    release = open_release(settings, key, verify=True)
    write_json(home / "active.json", {"release_id": release.id})
    return release.info


def artifact_info(directory, expected):
    return {name: {"sha256": file_hash(directory / name), "bytes": (directory / name).stat().st_size}
            for name in sorted(expected)}


def reuse_component(previous, components, name, destination, expected):
    if previous is None or previous.info.get("components", {}).get(name) != components[name]:
        return None
    artifacts = {key: previous.info["files"][key] for key in expected}
    try:
        verify_files(previous.path, artifacts, expected, hashes=True)
    except ReleaseUnavailable:
        return None
    for filename in sorted(expected):
        shutil.copyfile(previous.path / filename, destination / filename)
    return previous.info[name]


def verify_files(directory, manifest, expected, *, hashes):
    if set(manifest) != expected:
        raise ReleaseUnavailable("Manifest contains inconsistent artifact names.")
    for name, info in manifest.items():
        file = directory / name
        if not file.is_file() or file.stat().st_size != info["bytes"] or (hashes and file_hash(file) != info["sha256"]):
            raise ReleaseUnavailable(f"Release artifact missing or inconsistent: {name}.")


def open_release(settings, release_id=None, *, verify=False, deep=False):
    home = settings.path("artifacts") / "releases"
    pointer = home / "active.json"
    if release_id is None:
        if not pointer.is_file():
            raise ReleaseUnavailable("No active release. Run preprocess and build-indexes.")
        release_id = read_json(pointer).get("release_id")
    if not isinstance(release_id, str) or not RELEASE_ID.fullmatch(release_id):
        raise ReleaseUnavailable("Invalid release identifier.")
    directory = home / release_id
    if not (directory / "manifest.json").is_file():
        raise ReleaseUnavailable(f"Release {release_id} has no manifest.")
    manifest = read_json(directory / "manifest.json")
    if (manifest.get("release_id") != release_id or manifest.get("index_version") != INDEX_VERSION
            or manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("analyzer") != ANALYZER_VERSION
            or manifest.get("chunker") != CHUNK_VERSION or manifest.get("weights") != settings.search["field_weights"]):
        raise ReleaseUnavailable("Release is incompatible with this code or field weights. Build indexes explicitly.")
    if (digest([manifest["corpus"]["id"], manifest["components"]])[:24] != release_id
            or digest(manifest["corpus"]["files"]) != manifest["corpus"]["corpus_sha256"]):
        raise ReleaseUnavailable("Release ID does not match the recorded component or corpus fingerprints.")
    expected = CORPUS_FILES | indexing.INDEX_FILES | {"graph.json"}
    if manifest.get("dense"):
        expected |= PASSAGE_FILES
    verify_files(directory, manifest["files"], expected, hashes=verify or deep)
    if any(manifest["files"][name] != manifest["corpus"]["files"][name] for name in CORPUS_FILES):
        raise ReleaseUnavailable("Release and corpus artifact fingerprints disagree.")
    if verify or deep:
        documents = Documents(directory)
        if len(documents.parents) != manifest["lexical"]["parents"]:
            raise ReleaseUnavailable("Corpus and lexical document counts disagree.")
        if read_json(directory / "index.json") != manifest["lexical"]:
            raise ReleaseUnavailable("Lexical metadata and release manifest disagree.")
        if deep:
            documents.validate()
            validate_postings(directory)
        info = manifest.get("dense")
        if info:
            passages = Passages(directory)
            if (passages.vectors.shape != (info["passages"], info["dimension"])
                    or (info["passages"] and passages.parents.max() >= len(documents.parents))):
                raise ReleaseUnavailable("Dense vector offsets or dimensions are inconsistent.")
            if deep:
                passages.validate(documents)
    return Release(directory, manifest)


def validate_postings(directory):
    import hashlib
    import math
    import struct
    from collections import Counter, defaultdict
    from contextlib import ExitStack

    with ExitStack() as stack:
        indexes = [indexing.Index(directory, stack, codec) for codec in CODECS]
        terms = indexes[0].files.sorted_terms
        if any(idx.files.sorted_terms != terms for idx in indexes):
            raise ReleaseUnavailable("Postings vocabulary differs by codec.")

        # Compare both index directions with the canonical source, as three
        # codecs can agree while sharing the same bad offsets or frequencies.
        # A commutative digest keeps validation bounded by vocabulary size.
        expected = defaultdict(lambda: [0, 0])
        frequencies = Counter()
        position_row = struct.Struct("<7I")

        def fingerprint(doc, field, position):
            return int.from_bytes(hashlib.sha256(position_row.pack(doc, field, *position)).digest(), "little")

        baseline = indexes[0]
        manifest = read_json(directory / "manifest.json")
        weights = [manifest["weights"][field] for field in indexing.FIELDS]
        totals = [0] * len(indexing.FIELDS)
        occurrences = 0
        for document in Documents(directory):
            doc = document["doc"]
            forward = defaultdict(Counter)
            lengths = [0] * len(totals)
            for field, segment, position, token, phrase_safe in indexing.analyze_parent(document):
                lengths[field] += 1
                for term, original in [(token.term, int(phrase_safe)), *((alias, 0) for alias in token.aliases)]:
                    forward[term][str(field)] += 1
                    expected[term][0] += 1
                    expected[term][1] += fingerprint(doc, field, (segment, position, token.start, token.end, original))
            if dict(forward) != baseline.terms(doc):
                raise ReleaseUnavailable(f"Forward terms disagree with canonical document {doc}.")
            frequencies.update(forward.keys())
            indexed_length = sum(sum(fields.values()) for fields in forward.values())
            occurrences += indexed_length
            norm = math.sqrt(sum((indexing.tfidf_idf(baseline.info["parents"], baseline.df(term)) *
                                  sum(weights[int(field)] * tf for field, tf in fields.items())) ** 2
                                 for term, fields in forward.items()))
            stored_lengths, stored_norm = baseline.length_stats(doc)
            if (tuple(lengths) != stored_lengths or indexed_length != baseline.indexed_length(doc)
                    or not math.isclose(norm, stored_norm, rel_tol=1e-12, abs_tol=1e-12)):
                raise ReleaseUnavailable(f"Forward statistics disagree with canonical document {doc}.")
            totals = [total + length for total, length in zip(totals, lengths)]
        if (set(expected) != set(terms) or occurrences != baseline.info["occurrences"]
                or sum(totals) != baseline.info["original_tokens"]
                or sum(frequencies.values()) != baseline.info["postings"]):
            raise ReleaseUnavailable("Lexical vocabulary or token totals disagree with canonical documents.")
        if any(not math.isclose(total / baseline.info["parents"], average, rel_tol=1e-12, abs_tol=1e-12)
               for total, average in zip(totals, baseline.info["avg_lengths"])):
            raise ReleaseUnavailable("Lexical average lengths disagree with canonical documents.")
        for term in terms:
            reference = baseline.posting(term)
            if any(idx.posting(term) != reference for idx in indexes[1:]):
                raise ReleaseUnavailable(f"Posting contents differ for {term!r}.")
            df, cf, postings = reference
            count, signature = 0, 0
            for doc, fields in postings.items():
                for field, positions in fields.items():
                    for position in positions:
                        count += 1
                        signature += fingerprint(doc, field, position)
            if (df != len(postings) or df != frequencies[term] or cf != count or [count, signature] != expected[term]):
                raise ReleaseUnavailable(f"Postings disagree with canonical positions for {term!r}.")
            for idx in indexes:
                idx.cache.clear()


def status(settings):
    data = settings.path("data")
    home = settings.path("artifacts")
    stages = {}
    paths = {"canonical": data / "processed/current.json", "release": home / "releases/active.json",
             "mdn_collection": data / "manifests/collection-mdn.json",
             "stackoverflow_collection": data / "manifests/collection-stackoverflow.json",
             "model": home / "models/encoder/active.json"}
    for stage, path in paths.items():
        stages[stage] = read_json(path) if path.is_file() else {"status": "pending"}
    stages["raw"] = {source: corpus.raw_path(settings, source).is_file() for source in corpus.RAW_FILES}
    return stages
