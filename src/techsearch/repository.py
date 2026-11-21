"""Shared file repositories for canonical documents, passages and byte records."""
from __future__ import annotations

import json
import struct
from contextlib import contextmanager

from .io import atomic_file, dumps, read_jsonl, write_jsonl

OFFSET = struct.Struct("<Q")
CORPUS_FILES = {"documents.jsonl", "documents.offsets", "catalog.jsonl", "aliases.jsonl", "edges.jsonl"}
PASSAGE_FILES = {"passages.jsonl", "passages.offsets", "passage-parents.npy", "vectors.npy"}


class ByteRecords:
    """Dense record ID to exact byte range. Readers own independent file cursors."""

    def __init__(self, path, offsets):
        raw = offsets.read_bytes()
        if not raw or len(raw) % OFFSET.size:
            raise ValueError(f"Invalid offset table {offsets.name}.")
        positions = tuple(value for (value,) in OFFSET.iter_unpack(raw))
        if positions[0] != 0 or positions[-1] != path.stat().st_size or any(
            first >= second for first, second in zip(positions, positions[1:])
        ):
            raise ValueError(f"Inconsistent offset table {offsets.name}.")
        self.positions = positions
        self.path = path

    def __len__(self):
        return len(self.positions) - 1

    @contextmanager
    def reader(self):
        with self.path.open("rb") as stream:
            def read(index):
                if not 0 <= index < len(self):
                    raise LookupError(f"Record {index} is outside the {self.path.name} table.")
                left, right = self.positions[index:index + 2]
                stream.seek(left)
                data = stream.read(right - left)
                if len(data) != right - left:
                    raise ValueError(f"Truncated record in {self.path.name}.")
                return data
            yield read


def write_records(path, offsets, records):
    """Write a pair inside an unpublished staging directory."""
    with atomic_file(path) as stream, atomic_file(offsets) as index:
        for record in records:
            if not record:
                raise ValueError(f"Empty record in {path.name}.")
            index.write(OFFSET.pack(stream.tell()))
            stream.write(record)
        index.write(OFFSET.pack(stream.tell()))


def write_indexed_jsonl(path, offsets, records):
    write_records(path, offsets, ((dumps(record) + "\n").encode("utf-8") for record in records))


class Documents:
    def __init__(self, path):
        self.path = path
        self.records = ByteRecords(path / "documents.jsonl", path / "documents.offsets")
        self.parents = {}
        self.stable_to_doc = {}
        for expected, row in enumerate(read_jsonl(path / "catalog.jsonl")):
            if row["doc"] != expected or row["stable"] in self.stable_to_doc:
                raise ValueError("Catalog has duplicate keys or invalid dense IDs.")
            self.parents[expected] = row
            self.stable_to_doc[row["stable"]] = expected
        if len(self.parents) != len(self.records):
            raise ValueError("Document and catalog record counts disagree.")

    @contextmanager
    def reader(self):
        with self.records.reader() as read:
            yield lambda index: json.loads(read(index))

    def document(self, stable):
        doc = self.stable_to_doc.get(stable)
        if doc is None:
            raise LookupError("Document is unavailable in this release.")
        with self.reader() as by_id:
            return by_id(doc)

    def __iter__(self):
        return read_jsonl(self.path / "documents.jsonl")

    def edges(self):
        yield from read_jsonl(self.path / "edges.jsonl")

    def validate(self):
        with self.reader() as read:
            for doc, metadata in self.parents.items():
                entry = read(doc)
                if entry["id"] != metadata["stable"] or entry["doc"] != doc or any(
                    entry[key] != metadata[key] for key in ("title", "url", "source", "topic", "tags")
                ):
                    raise ValueError(f"Indexed document {doc} disagrees with its catalog.")
                if [segment["ordinal"] for segment in entry["segments"]] != list(range(len(entry["segments"]))):
                    raise ValueError(f"Indexed document {doc} has unordered segments.")
                answers = {answer["answer_id"] for answer in entry["answers"]}
                if any(segment["answer_id"] is not None and segment["answer_id"] not in answers for segment in entry["segments"]):
                    raise ValueError(f"Indexed document {doc} has an unreachable answer segment.")
        for row in read_jsonl(self.path / "aliases.jsonl"):
            if row["doc"] not in self.parents:
                raise ValueError("Alias points outside the corpus.")
        for row in self.edges():
            if (row["source"] not in self.parents or row["destination"] not in self.parents
                    or row["source"] == row["destination"]):
                raise ValueError("Edge does not connect two distinct canonical parents.")


class Passages:
    def __init__(self, path):
        import numpy as np

        self.records = ByteRecords(path / "passages.jsonl", path / "passages.offsets")
        self.parents = np.load(path / "passage-parents.npy", mmap_mode="r", allow_pickle=False)
        self.vectors = np.load(path / "vectors.npy", mmap_mode="r", allow_pickle=False)
        if self.vectors.ndim != 2 or self.vectors.dtype != np.dtype("<f4") or self.parents.dtype != np.dtype("<u4"):
            raise ValueError("Dense vector or passage map format is invalid.")
        if self.parents.shape != (len(self.records),) or self.vectors.shape[0] != len(self.records):
            raise ValueError("Dense indexes and passage metadata disagree.")

    @contextmanager
    def reader(self):
        with self.records.reader() as read:
            yield lambda index: json.loads(read(index))

    def validate(self, documents):
        import numpy as np

        for start in range(0, len(self.records), 4096):
            chunk = self.vectors[start:start + 4096]
            if not np.isfinite(chunk).all() or not np.allclose(np.linalg.norm(chunk, axis=1), 1, atol=1e-5):
                raise ValueError("Dense passage vectors are invalid or unnormalized.")
        previous = None
        with self.reader() as read, documents.reader() as document_at:
            for row, parent in enumerate(self.parents):
                passage = read(row)
                if passage["row"] != row or passage["parent"] != parent:
                    raise ValueError("Passage record and row mapping disagree.")
                if previous != parent:
                    document = document_at(int(parent))
                    previous = parent
                for segment, start, end in passage["spans"]:
                    if not 0 <= segment < len(document["segments"]):
                        raise ValueError("Passage points to an invalid segment.")
                    source = document["segments"][segment]
                    if source["answer_id"] != passage["answer_id"] or not 0 <= start < end <= len(source["text"]):
                        raise ValueError("Passage points outside its source evidence.")
