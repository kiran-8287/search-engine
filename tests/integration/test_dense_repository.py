import re
import shutil

import numpy as np
import pytest

from techsearch import dense
from techsearch.pipeline import Release
from techsearch.repository import CORPUS_FILES, Documents, Passages, write_indexed_jsonl
from techsearch.io import read_jsonl, write_jsonl
from techsearch import service as search_module


class FixtureTokenizer:
    def __call__(self, text, **kwargs):
        offsets = [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]
        return {"offset_mapping": offsets, "input_ids": list(range(len(offsets)))}


class FixtureEncoder:
    tokenizer = FixtureTokenizer()

    def get_sentence_embedding_dimension(self):
        return 3

    def encode(self, texts, **_options):
        return np.tile(np.array([0, 0, 1], dtype=np.float32), (len(texts), 1))


def test_missing_cached_model_is_explicit(settings):
    manifest = {"repo": settings.dense["model"], "revision": "0" * 40, "files": {"config.json": "missing"}}
    with pytest.raises(dense.DenseUnavailable, match="Cached model file missing"):
        dense.load_encoder(settings, manifest, verify=True)


def test_dense_initialization_retries_after_temporary_failure(service, monkeypatch, caplog):
    encoder = object()
    calls = []
    monkeypatch.setitem(service.release.info, "dense", {"passages": 1})

    def initialize(*_args):
        calls.append(True)
        if len(calls) == 1:
            raise ImportError("temporary import failure")
        return encoder

    now = 100.0
    monkeypatch.setattr(search_module, "Dense", initialize)
    monkeypatch.setattr(search_module, "monotonic", lambda: now)
    with pytest.raises(dense.DenseUnavailable, match="Dense encoder could not be opened"):
        service.require_dense()
    assert "temporary import failure" in caplog.text

    now += search_module.DENSE_RETRY_SECONDS / 2
    with pytest.raises(dense.DenseUnavailable):
        service.require_dense()
    assert len(calls) == 1

    now += search_module.DENSE_RETRY_SECONDS
    assert service.require_dense() is encoder
    assert service.dense_error is None
    assert service.require_dense() is encoder
    assert len(calls) == 2


def test_dense_storage_alignment_and_cache(tmp_path, settings, release, monkeypatch):
    stage = tmp_path / "dense-fixture"
    stage.mkdir()
    for filename in CORPUS_FILES:
        shutil.copyfile(release.path / filename, stage / filename)
    monkeypatch.setattr(dense, "load_encoder", lambda *_args, **_options: FixtureEncoder())
    settings.dense.update(chunk_tokens=9, overlap_tokens=2)
    info = dense.build_dense(stage, settings, {"repo": "fixture", "revision": "0" * 40, "files": {}})
    assert info["passages"] > len(Documents(stage).parents)
    assert info["bytes"] == (stage / "vectors.npy").stat().st_size
    assert info["bytes"] > info["vector_payload_bytes"]
    repo = Passages(stage)
    repo.validate(Documents(stage))
    assert tuple(repo.vectors[0]) == (0, 0, 1)
    with repo.reader() as read:
        assert read(0)["parent"] == int(repo.parents[0])
    assert len(list(dense.model_path(settings).glob("embeddings/*/*/*.npy"))) > 0


def test_verified_dense_reuse_rewrites_rows_and_parent_ids(tmp_path, settings, release, monkeypatch):
    old = tmp_path / "dense-old"
    old.mkdir()
    for name in CORPUS_FILES:
        shutil.copyfile(release.path / name, old / name)
    monkeypatch.setattr(dense, "load_encoder", lambda *_args, **_options: FixtureEncoder())
    manifest = {"repo": "fixture", "revision": "0" * 40, "files": {}}
    previous = Release(old, {"dense": dense.build_dense(old, settings, manifest)})
    old_docs = list(Documents(old))
    old_catalog = list(read_jsonl(old / "catalog.jsonl"))
    updated = tmp_path / "dense-updated"
    updated.mkdir()
    parents = old_docs[1:3]
    parents[-1]["segments"][0]["text"] += " changed"
    for number, parent in enumerate(parents):
        parent["doc"] = number
    write_indexed_jsonl(updated / "documents.jsonl", updated / "documents.offsets", parents)
    write_jsonl(updated / "catalog.jsonl",
                ({**row, "doc": i} for i, row in enumerate(old_catalog[1:3])))
    built = dense.build_dense(updated, settings, manifest, previous=previous)
    old_passages, new_passages = Passages(old), Passages(updated)
    count = int(np.count_nonzero(old_passages.parents == 1))
    assert built["passages_reused"] == count and 0 < count < built["passages"]
    assert new_passages.parents[:count].tolist() == [0] * count
    assert np.array_equal(new_passages.vectors[:count], old_passages.vectors[old_passages.parents == 1])
    new_passages.validate(Documents(updated))
    del new_passages

    settings.dense["overlap_tokens"] -= 1
    assert dense.build_dense(updated, settings, manifest, previous=previous)["passages_reused"] == 0
