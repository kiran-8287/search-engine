"""Binary forward records and independently seekable compressed posting lists."""
from __future__ import annotations

import bisect
import heapq
import json
import math
import struct
import tempfile
import zlib
from collections import Counter, defaultdict
from contextlib import ExitStack
from functools import cached_property
from itertools import groupby
from pathlib import Path
from time import perf_counter

from .compression import CODECS, pack_postings, unpack_postings
from .config import FIELDS
from .io import WorkloadError, atomic_file, dumps, read_json, read_jsonl, write_json
from .preprocessing import analyze
from .repository import ByteRecords, Documents, write_records

FIELD_ID = {field: index for index, field in enumerate(FIELDS)}
STATS = struct.Struct("<" + "I" * (len(FIELDS) + 1) + "d")
FORWARD_FILES = {"forward.bin", "forward.offsets", "forward-stats.bin", "index.json"}
INDEX_FILES = FORWARD_FILES | {f"{prefix}-{codec}.{ext}" for codec in CODECS
                              for prefix, ext in (("postings", "bin"), ("lexicon", "jsonl"))}


def tfidf_idf(count, frequency):
    return math.log((count + 1) / (frequency + 1)) + 1


def analyze_parent(document):
    """Yield token and position records with the legacy phrase-safety flag."""
    for segment in document["segments"]:
        field = FIELD_ID[segment["field"]]
        ordinal = segment["ordinal"]
        for position, token in enumerate(analyze(segment["text"])):
            yield field, ordinal, position, token, segment["type"] != "legacy_flat"


def shard_rows(path, rows):
    rows.sort()
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(dumps(row) + "\n")
    rows.clear()


def merge(paths):
    return heapq.merge(*(read_jsonl(path) for path in paths))


def reduce_shards(paths, directory, fan_in=24):
    generation = 0
    while len(paths) > fan_in:
        reduced = []
        for offset in range(0, len(paths), fan_in):
            group = paths[offset:offset + fan_in]
            output = directory / f"merge-{generation}-{offset}.jsonl"
            with output.open("w", encoding="utf-8", newline="\n") as stream:
                for row in merge(group):
                    stream.write(dumps(row) + "\n")
            for path in group:
                path.unlink()
            reduced.append(output)
        paths = reduced
        generation += 1
    return paths


def write_postings(directory, documents, shard_limit):
    """Sort token occurrences in bounded runs and write one term at a time."""
    payload_sizes = Counter()
    encode_times = Counter()
    frequencies = {}
    posting_count = occurrences = 0
    with tempfile.TemporaryDirectory(prefix="techsearch-sort-", dir=directory) as temporary:
        temporary = Path(temporary)
        rows, paths = [], []
        for document in documents:
            for field, ordinal, position, token, phrase_safe in analyze_parent(document):
                location = [document["doc"], field, ordinal, position, token.start, token.end]
                rows.append([token.term, *location, int(phrase_safe)])
                for alias in token.aliases:
                    rows.append([alias, *location, 0])
                if len(rows) >= shard_limit:
                    paths.append(temporary / f"shard-{len(paths)}.jsonl")
                    shard_rows(paths[-1], rows)
        if rows:
            paths.append(temporary / f"shard-{len(paths)}.jsonl")
            shard_rows(paths[-1], rows)
        paths = reduce_shards(paths, temporary)
        with ExitStack() as stack:
            streams = {codec: (
                stack.enter_context(atomic_file(directory / f"postings-{codec}.bin")),
                stack.enter_context(atomic_file(directory / f"lexicon-{codec}.jsonl")),
            ) for codec in CODECS}
            for term, group in groupby(merge(paths), key=lambda row: row[0]):
                postings = {}
                cf = 0
                for _, document_id, field, segment, position, start, end, original in group:
                    fields = postings.setdefault(document_id, {})
                    positions = fields.setdefault(field, [])
                    positions.append((segment, position, start, end, original))
                    cf += 1
                df = len(postings)
                frequencies[term] = df
                posting_count += df
                occurrences += cf
                for codec, (payload, lexicon) in streams.items():
                    started = perf_counter()
                    blob, bits = pack_postings(postings, codec)
                    encode_times[codec] += perf_counter() - started
                    metadata = [term, df, cf, payload.tell(), len(blob), bits]
                    payload.write(blob)
                    lexicon.write((dumps(metadata) + "\n").encode("utf-8"))
                    payload_sizes[codec] += len(blob)
    compression = {}
    for codec in CODECS:
        metadata_bytes = (directory / f"lexicon-{codec}.jsonl").stat().st_size
        payload_bytes = (directory / f"postings-{codec}.bin").stat().st_size
        compression[codec] = {"payload_bytes": payload_bytes, "metadata_bytes": metadata_bytes,
                              "artifact_bytes": payload_bytes + metadata_bytes, "encode_seconds": encode_times[codec],
                              "payload_ratio": payload_bytes / max(1, payload_sizes["uint32"])}
    return frequencies, posting_count, occurrences, compression


def forward_records(documents, stats, idfs, weights, totals):
    """Write per-document scoring stats and yield compressed term counts."""
    for document in documents:
        lengths = [0] * len(FIELDS)
        term_frequencies = defaultdict(Counter)
        expanded_length = 0
        for field, _, _, token, _phrase_safe in analyze_parent(document):
            lengths[field] += 1
            for term in (token.term, *token.aliases):
                term_frequencies[term][field] += 1
                expanded_length += 1
        squared_weights = []
        for term, fields in term_frequencies.items():
            weighted_tf = sum(weights[field] * tf for field, tf in fields.items())
            squared_weights.append((idfs[term] * weighted_tf) ** 2)
        norm = math.sqrt(sum(squared_weights))
        stats.write(STATS.pack(*lengths, expanded_length, norm))
        for field, length in enumerate(lengths):
            totals[field] += length
        yield zlib.compress(dumps(term_frequencies).encode("utf-8"), level=3)


def build_indexes(directory, field_weights, shard_limit):
    """Build the posting lists first, then use their frequencies for the forward index."""
    started = perf_counter()
    documents = Documents(directory)
    frequencies, posting_count, occurrences, compression = write_postings(directory, documents, shard_limit)
    count = len(documents.parents)
    idfs = {term: tfidf_idf(count, df) for term, df in frequencies.items()}
    weights = [field_weights[field] for field in FIELDS]
    totals = [0] * len(FIELDS)

    with atomic_file(directory / "forward-stats.bin") as stats:
        records = forward_records(documents, stats, idfs, weights, totals)
        write_records(directory / "forward.bin", directory / "forward.offsets", records)
    info = {"parents": count, "vocabulary": len(frequencies), "postings": posting_count, "occurrences": occurrences,
            "avg_lengths": [total / max(1, count) for total in totals], "original_tokens": sum(totals),
            "compression": compression, "seconds": perf_counter() - started}
    write_json(directory / "index.json", info)
    return info


class IndexFiles:
    """Load compact structural metadata once. Request readers own file cursors."""
    def __init__(self, directory, codec="vb"):
        if codec not in CODECS:
            raise ValueError(f"Unsupported postings codec {codec}")
        self.directory, self.codec = directory, codec
        self.info = read_json(directory / "index.json")
        self.forward = ByteRecords(directory / "forward.bin", directory / "forward.offsets")
        self.stats = (directory / "forward-stats.bin").read_bytes()
        self.lexicon = {}
        self.payload = directory / f"postings-{codec}.bin"
        offset = 0
        previous = None
        for term, df, cf, start, size, bits in read_jsonl(directory / f"lexicon-{codec}.jsonl"):
            if ((previous is not None and previous >= term) or start != offset or size < 1
                    or not 0 < df <= self.info["parents"] or df > cf or not 0 < bits <= 8 * size
                    or (bits + 7) // 8 != size):
                raise ValueError("Invalid lexicon ordering, counts, or byte boundaries.")
            self.lexicon[term] = (df, cf, start, size, bits)
            previous, offset = term, offset + size
        if (len(self.forward) != self.info["parents"] or len(self.stats) != len(self.forward) * STATS.size
                or len(self.lexicon) != self.info["vocabulary"] or self.payload.stat().st_size != offset):
            raise ValueError("Inconsistent lexical index counts or size.")
        self.sorted_terms = list(self.lexicon)

    @cached_property
    def terms_by_length(self):
        bins = defaultdict(list)
        for term, (df, *_rest) in self.lexicon.items():
            if term.replace(".", "").isalpha():
                bins[len(term)].append((term, df))
        for values in bins.values():
            values.sort(key=lambda item: (-item[1], item[0]))
        return dict(bins)


class Index:
    def __init__(self, directory, stack, codec="vb", *, files=None):
        self.files = files if files is not None else IndexFiles(directory, codec)
        self.info = self.files.info
        self.codec = self.files.codec
        self.read_forward = stack.enter_context(self.files.forward.reader())
        self.read_payload = stack.enter_context(self.files.payload.open("rb"))
        self.cache = {}
        self.begin_query(None)

    def begin_query(self, budget):
        self.budget = budget
        self.visited_terms = set()
        self.posting_occurrences = 0

    def posting(self, term):
        row = self.files.lexicon.get(term)
        if row and term not in self.visited_terms:
            self.visited_terms.add(term)
            self.posting_occurrences += row[1]
            if self.budget is not None and self.posting_occurrences > self.budget:
                raise WorkloadError("This query requires too many posting occurrences. Use fewer or more specific terms.")
        if term not in self.cache:
            if row is None:
                self.cache[term] = (0, 0, {})
            else:
                df, cf, offset, size, bits = row
                self.read_payload.seek(offset)
                self.cache[term] = (df, cf, unpack_postings(self.read_payload.read(size), bits, self.codec))
        return self.cache[term]

    def df(self, term):
        return self.files.lexicon.get(term, (0,))[0]

    def length_stats(self, doc):
        record = STATS.unpack_from(self.files.stats, doc * STATS.size)
        return record[:-2], record[-1]

    def indexed_length(self, doc):
        return STATS.unpack_from(self.files.stats, doc * STATS.size)[-2]

    def terms(self, doc):
        return json.loads(zlib.decompress(self.read_forward(doc)))

    def prefix(self, prefix, limit):
        keys = self.files.sorted_terms
        start = bisect.bisect_left(keys, prefix)
        found = []
        for term in keys[start:start + limit]:
            if not term.startswith(prefix):
                break
            found.append(term)
        return found

    def vocabulary(self, low, high, limit):
        from itertools import islice

        bins = self.files.terms_by_length
        merged = heapq.merge(*(bins.get(length, ()) for length in range(low, high + 1)),
                             key=lambda item: (-item[1], item[0]))
        return islice(merged, limit)

    def frequent_terms(self, min_df, limit):
        candidates = ((term, values[0]) for term, values in self.files.lexicon.items() if values[0] >= min_df)
        return heapq.nsmallest(limit, candidates, key=lambda item: (-item[1], item[0]))
