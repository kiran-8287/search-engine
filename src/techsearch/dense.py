"""Offline passage encoding and exact, eligible-parent similarity."""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from itertools import groupby
from time import perf_counter

import numpy as np

from .io import ANALYZER_VERSION, CHUNK_VERSION, WorkloadError, atomic_file, digest, file_hash, filesystem_path, read_json, write_json
from .repository import Documents, Passages, write_indexed_jsonl


class DenseUnavailable(RuntimeError):
    pass


def model_path(settings):
    return settings.path("artifacts") / "models" / "encoder"


def download_model(settings):
    from huggingface_hub import HfApi, snapshot_download

    home = model_path(settings)
    repo = settings.dense["model"]
    revision = HfApi().model_info(repo, revision=settings.dense["revision"]).sha
    if not revision or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Model repository did not return a pinned revision.")
    target = home / revision
    snapshot_download(repo_id=repo, revision=revision, local_dir=target, allow_patterns=[
        "*.txt", "*.json", "*.safetensors", "README.md", "LICENSE*", "1_Pooling/*"
    ])
    files = {file.relative_to(target).as_posix(): file_hash(file)
             for file in sorted(target.rglob("*")) if file.is_file() and ".cache" not in file.relative_to(target).parts}
    if not files or not (target / "modules.json").is_file() or not (target / "model.safetensors").is_file():
        raise ValueError("Missing encoder model or configuration in downloaded snapshot.")
    manifest = {"repo": repo, "revision": revision, "files": files}
    write_json(home / "active.json", manifest)
    return manifest


def model_manifest(settings):
    path = model_path(settings) / "active.json"
    if not path.is_file():
        return None
    manifest = read_json(path)
    revision = manifest.get("revision")
    if (not isinstance(revision, str) or not re.fullmatch("[a-f0-9]{40}", revision)
            or manifest.get("repo") != settings.dense["model"]
            or settings.dense["revision"] not in (None, revision)):
        raise DenseUnavailable("Cached model does not match configuration. Run download-model explicitly.")
    return manifest


def load_encoder(settings, manifest, verify=False):
    if not manifest:
        raise DenseUnavailable("Install the dense dependencies and run download-model explicitly.")
    target = model_path(settings) / manifest["revision"]
    for relative, expected in manifest["files"].items():
        file = target / relative
        if not file.resolve().is_relative_to(target.resolve()) or not file.is_file() or (verify and file_hash(file) != expected):
            raise DenseUnavailable(f"Cached model file missing or changed: {relative}")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise DenseUnavailable("Install TechSearch with the dense extra.") from error
    model = SentenceTransformer(str(target), device="cpu", local_files_only=True, trust_remote_code=False,
                                model_kwargs={"use_safetensors": True})
    special = model.tokenizer.num_special_tokens_to_add()
    if not model.tokenizer.is_fast or settings.dense["chunk_tokens"] + special > model.max_seq_length:
        raise DenseUnavailable("Configured chunks exceed the local encoder's token budget.")
    return model


def chunk_rows(documents, tokenizer, limit, overlap):
    """Group adjacent prose within a section and keep code and answers separate."""
    ordered = ((document["doc"], segment) for document in documents for segment in document["segments"] if segment["field"] != "tag")
    def section(row):
        parent, segment = row
        return (parent, segment.get("answer_id"), tuple(segment.get("heading_path", [])),
                segment["ordinal"] if segment["field"] in {"code", "title"} else -1)
    for (parent, answer, _headings, _boundary), rows in groupby(ordered, key=section):
        items = [segment for _, segment in rows]
        text = "\n\n".join(row["text"] for row in items)
        spans = []
        offset = 0
        for row in items:
            end = offset + len(row["text"])
            spans.append((offset, end, row["ordinal"]))
            offset = end + 2
        offsets = tokenizer(text, add_special_tokens=False, truncation=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
        start = 0
        span_index = 0
        while start < len(offsets):
            stop = min(start + limit, len(offsets))
            left = offsets[start][0]
            right = offsets[stop - 1][1]
            while stop > start + 1 and len(tokenizer(text[left:right], add_special_tokens=False, verbose=False)["input_ids"]) > limit:
                stop -= 1
                right = offsets[stop - 1][1]
            while span_index + 1 < len(spans) and spans[span_index][1] <= left:
                span_index += 1
            relevant = []
            for span_left, span_right, ordinal in spans[span_index:]:
                if span_left >= right:
                    break
                relevant.append([ordinal, max(0, left - span_left), min(right, span_right) - span_left])
            yield parent, answer, relevant, text[left:right]
            if stop == len(offsets):
                break
            start = max(start + 1, stop - overlap)


def build_dense(directory, settings, manifest):
    started = perf_counter()
    model = load_encoder(settings, manifest, verify=True)
    dimension_method = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    dimension = dimension_method()
    limits = settings.default["resources"]
    revision = digest([manifest, settings.dense, CHUNK_VERSION, ANALYZER_VERSION])
    cache_home = model_path(settings) / "embeddings" / revision
    batch_size = settings.dense["batch_size"]
    parents = []
    documents = Documents(directory)
    count = 0
    with tempfile.TemporaryFile(dir=directory) as vector_file:
        batch = []

        def cache_path(key):
            return filesystem_path(cache_home / key[:2] / f"{key}.npy")

        def valid(vector):
            return vector.shape == (dimension,) and np.isfinite(vector).all() and np.isclose(np.linalg.norm(vector), 1)

        def flush():
            nonlocal count
            unique = {key: text for _, _, _, text, key in batch}
            vectors = {}
            for key in unique:
                try:
                    hit = np.asarray(np.load(cache_path(key), allow_pickle=False), dtype="<f4")
                    if valid(hit):
                        vectors[key] = hit
                except (OSError, ValueError, EOFError):
                    continue
            missing = [key for key in unique if key not in vectors]
            if missing:
                encoded = model.encode([unique[key] for key in missing], convert_to_numpy=True,
                                       batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
                for key, vector in zip(missing, encoded, strict=True):
                    vector = np.asarray(vector, dtype="<f4")
                    if not valid(vector):
                        raise ValueError("Encoder emitted an invalid normalized vector.")
                    vectors[key] = vector
                    with atomic_file(cache_path(key)) as cache:
                        np.save(cache, vector, allow_pickle=False)
            for parent, answer, spans, _, key in batch:
                index = count + 1
                if index * dimension * 4 > limits["max_dense_bytes"] or index > limits["max_dense_passages"]:
                    raise ValueError("Dense build exceeds configured passage or byte budget.")
                vector_file.write(vectors[key].tobytes())
                parents.append(parent)
                yield {"row": count, "parent": parent, "answer_id": answer, "spans": spans}
                count = index
            batch.clear()
            if count and count % (batch_size * 32) == 0:
                print(f"Dense build: {count:,} passages written; resumable vectors cached.", file=sys.stderr, flush=True)
        def passages():
            rows = chunk_rows(documents, model.tokenizer, settings.dense["chunk_tokens"], settings.dense["overlap_tokens"])
            for parent, answer, spans, text in rows:
                batch.append((parent, answer, spans, text, digest(text)))
                if len(batch) >= batch_size:
                    yield from flush()
            yield from flush()
        write_indexed_jsonl(directory / "passages.jsonl", directory / "passages.offsets", passages())
        vector_file.seek(0)
        with atomic_file(directory / "vectors.npy") as output:
            np.lib.format.write_array_header_1_0(output, {"descr": "<f4", "fortran_order": False, "shape": (count, dimension)})
            shutil.copyfileobj(vector_file, output)
        with atomic_file(directory / "passage-parents.npy") as output:
            np.save(output, np.asarray(parents, dtype="<u4"), allow_pickle=False)
    return {"passages": count, "dimension": dimension, "model": manifest, "fingerprint": revision,
            "bytes": (directory / "vectors.npy").stat().st_size,
            "vector_payload_bytes": count * dimension * 4, "seconds": perf_counter() - started}


class Dense:
    def __init__(self, release, settings):
        info = release.info.get("dense")
        if not info or not info["passages"]:
            raise DenseUnavailable("This release has no dense passages. Download a model and build indexes explicitly.")
        self.model = load_encoder(settings, info["model"], verify=True)
        self.passages = Passages(release.path)
        self.vectors, self.parents = self.passages.vectors, self.passages.parents

    def rank(self, text, eligible, cutoff, depth):
        started = perf_counter()
        if not eligible:
            return [], {"passages_scored": 0, "seconds": perf_counter() - started}
        tokens = self.model.tokenizer(text, add_special_tokens=True, truncation=False, verbose=False)["input_ids"]
        if len(tokens) > self.model.max_seq_length:
            raise WorkloadError("The query exceeds the local encoder token budget. Use fewer terms.")
        q = np.asarray(self.model.encode(text, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)
        rows, visited = exact_parent_hits(self.vectors, self.parents, q, eligible, cutoff, depth)
        return rows, {"passages_scored": visited, "cutoff": cutoff, "seconds": perf_counter() - started}


def exact_parent_hits(vectors, parents, query, eligible, cutoff, depth):
    mask = np.isin(parents, np.asarray(sorted(eligible), dtype=np.uint32))
    best = {}
    visited = 0
    for start in range(0, len(mask), 4096):
        indices = np.flatnonzero(mask[start:start + 4096]) + start
        if indices.size == 0:
            continue
        similarity = vectors[indices] @ query
        visited += len(indices)
        matches = similarity >= cutoff
        for index, score in zip(indices[matches], similarity[matches]):
            parent = int(parents[index])
            score = float(score)
            if parent not in best or score > best[parent][0]:
                best[parent] = (score, int(index))
    ordered = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))[:depth]
    return [(doc, score, [("passage", row, score)]) for doc, (score, row) in ordered], visited
