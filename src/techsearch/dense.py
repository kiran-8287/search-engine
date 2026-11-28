"""Offline passage encoding and exact, eligible-parent similarity."""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from contextlib import ExitStack
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
    except ModuleNotFoundError as error:
        if error.name == "sentence_transformers":
            raise DenseUnavailable("Install TechSearch with the dense extra.") from error
        raise DenseUnavailable("A dense dependency is missing. See the server log for the cause.") from error
    except ImportError as error:
        raise DenseUnavailable("A dense dependency could not be imported. See the server log for the cause.") from error
    model = SentenceTransformer(str(target), device="cpu", local_files_only=True, trust_remote_code=False,
                                model_kwargs={"use_safetensors": True})
    special = model.tokenizer.num_special_tokens_to_add()
    if not model.tokenizer.is_fast or settings.dense["chunk_tokens"] + special > model.max_seq_length:
        raise DenseUnavailable("Configured chunks exceed the local encoder's token budget.")
    return model


def passage_segments(documents):
    """Yield searchable segments in document order, skipping tag labels."""
    for document in documents:
        for segment in document["segments"]:
            if segment["field"] != "tag":
                yield document["doc"], segment


def section_key(row):
    document_id, segment = row
    headings = tuple(segment.get("heading_path", []))
    # Give titles and code their own group even when the heading path agrees.
    boundary = segment["ordinal"] if segment["field"] in {"code", "title"} else -1
    return document_id, segment.get("answer_id"), headings, boundary


def chunk_rows(documents, tokenizer, limit, overlap):
    """Yield overlapping token windows with their parent IDs and source spans."""
    for (parent, answer, _headings, _boundary), rows in groupby(passage_segments(documents), key=section_key):
        segments = [segment for _, segment in rows]
        text = "\n\n".join(segment["text"] for segment in segments)
        spans = []
        offset = 0
        for segment in segments:
            end = offset + len(segment["text"])
            spans.append((offset, end, segment["ordinal"]))
            offset = end + 2
        offsets = tokenizer(text, add_special_tokens=False, truncation=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
        first_token = 0
        span_index = 0
        while first_token < len(offsets):
            past_last_token = min(first_token + limit, len(offsets))
            left = offsets[first_token][0]
            right = offsets[past_last_token - 1][1]
            # A sliced word can tokenize differently without its original context.
            while past_last_token > first_token + 1:
                window_tokens = tokenizer(text[left:right], add_special_tokens=False, verbose=False)["input_ids"]
                if len(window_tokens) <= limit:
                    break
                past_last_token -= 1
                right = offsets[past_last_token - 1][1]
            while span_index + 1 < len(spans) and spans[span_index][1] <= left:
                span_index += 1
            relevant = []
            for span_left, span_right, ordinal in spans[span_index:]:
                if span_left >= right:
                    break
                relevant.append([ordinal, max(0, left - span_left), min(right, span_right) - span_left])
            yield parent, answer, relevant, text[left:right]
            if past_last_token == len(offsets):
                break
            first_token = max(first_token + 1, past_last_token - overlap)


def passage_inputs(document):
    """Return the inputs that determine how one parent is split and encoded."""
    return [(section_key(row)[1:], row[1]["ordinal"], row[1]["text"]) for row in passage_segments((document,))]


def build_dense(directory, settings, manifest, previous=None):
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
    reused = 0
    with ExitStack() as stack:
        vector_file = stack.enter_context(tempfile.TemporaryFile(dir=directory))
        batch = []
        prior = None
        if previous is not None and (previous.info.get("dense") or {}).get("fingerprint") == revision:
            old_documents = Documents(previous.path)
            old_passages = Passages(previous.path)
            if (old_passages.vectors.shape[1] == dimension
                    and np.all(old_passages.parents[:-1] <= old_passages.parents[1:])):
                prior = (old_documents.stable_to_doc, stack.enter_context(old_documents.reader()),
                         old_passages, stack.enter_context(old_passages.reader()))

        def check_budget(total):
            if total * dimension * 4 > limits["max_dense_bytes"] or total > limits["max_dense_passages"]:
                raise ValueError("Dense build exceeds configured passage or byte budget.")

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
                check_budget(index)
                vector_file.write(vectors[key].tobytes())
                parents.append(parent)
                yield {"row": count, "parent": parent, "answer_id": answer, "spans": spans}
                count = index
            batch.clear()
            if count and count % (batch_size * 32) == 0:
                print(f"Dense build: {count:,} passages written; resumable vectors cached.", file=sys.stderr, flush=True)
        def reusable_range(document):
            if prior is None:
                return None
            stable_to_doc, old_document, old_passages, _ = prior
            old_id = stable_to_doc.get(document["id"])
            if old_id is None or passage_inputs(document) != passage_inputs(old_document(old_id)):
                return None
            return (int(old_passages.parents.searchsorted(old_id, side="left")),
                    int(old_passages.parents.searchsorted(old_id, side="right")))

        def passages():
            nonlocal count, reused
            for document in documents:
                indexes = reusable_range(document)
                if indexes is not None:
                    yield from flush()
                    start, end = indexes
                    _, _, old_passages, read_passage = prior
                    check_budget(count + end - start)
                    vector_file.write(old_passages.vectors[start:end].tobytes())
                    parents.extend([document["doc"]] * (end - start))
                    for row in range(start, end):
                        passage = read_passage(row)
                        yield {**passage, "row": count, "parent": document["doc"]}
                        count += 1
                        reused += 1
                    continue
                rows = chunk_rows((document,), model.tokenizer, settings.dense["chunk_tokens"],
                                  settings.dense["overlap_tokens"])
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
    return {"passages": count, "passages_reused": reused, "dimension": dimension, "model": manifest, "fingerprint": revision,
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
        """Encode the query locally and return the highest-scoring eligible parents."""
        started = perf_counter()
        if not eligible:
            return [], {"passages_scored": 0, "seconds": perf_counter() - started}
        tokens = self.model.tokenizer(text, add_special_tokens=True, truncation=False, verbose=False)["input_ids"]
        if len(tokens) > self.model.max_seq_length:
            raise WorkloadError("The query exceeds the local encoder token budget. Use fewer terms.")
        query_vector = self.model.encode(text, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
        query_vector = np.asarray(query_vector, dtype=np.float32)
        rows, visited = exact_parent_hits(self.vectors, self.parents, query_vector, eligible, cutoff, depth)
        return rows, {"passages_scored": visited, "cutoff": cutoff, "seconds": perf_counter() - started}


def exact_parent_hits(vectors, parents, query, eligible, cutoff, depth):
    """Score eligible passages in blocks and keep one best passage per parent."""
    mask = np.isin(parents, np.asarray(sorted(eligible), dtype=np.uint32))
    best_by_parent = {}
    visited = 0
    block_size = 4096
    for start in range(0, len(mask), block_size):
        passage_ids = np.flatnonzero(mask[start:start + block_size]) + start
        if passage_ids.size == 0:
            continue
        similarity = vectors[passage_ids] @ query
        visited += len(passage_ids)
        matches = similarity >= cutoff
        for passage_id, score in zip(passage_ids[matches], similarity[matches]):
            parent_id = int(parents[passage_id])
            score = float(score)
            previous = best_by_parent.get(parent_id)
            # Keep the first passage when two passages of a parent tie.
            if previous is None or score > previous[0]:
                best_by_parent[parent_id] = (score, int(passage_id))
    ordered = sorted(best_by_parent.items(), key=lambda item: (-item[1][0], item[0]))[:depth]
    hits = [(parent_id, score, [("passage", passage_id, score)])
            for parent_id, (score, passage_id) in ordered]
    return hits, visited
