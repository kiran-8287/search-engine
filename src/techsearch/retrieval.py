"""Rankers use postings directly and share deterministic tie handling."""
from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict

from .config import FIELDS
from .indexing import tfidf_idf


def lexical(index, query, eligible, config, *, ranker="bm25", strategy="taat", depth=100):
    count = index.info["parents"]
    averages = index.info["avg_lengths"]
    weights = [config["field_weights"][field] for field in FIELDS]
    traces = {"postings_visited": 0, "comparisons": 0, "score_work": 0, "peak_accumulators": 0}
    rows = []
    length_cache = {}
    corpus_size = index.info["occurrences"]
    for (term, field), weight in sorted(query.items(), key=lambda item: (item[0][0], -1 if item[0][1] is None else item[0][1])):
        df, cf, postings = index.posting(term)
        if df and eligible:
            rows.append((term, field, weight, df, cf, postings))

    if ranker == "likelihood":
        return likelihood(index, rows, eligible, config, corpus_size, depth, traces)
    qnorm = 1.0
    if ranker == "tfidf":
        query_vector = Counter()
        for term, _field, weight, df, _cf, _posting in rows:
            query_vector[term] += weight * tfidf_idf(count, df)
        qnorm = math.sqrt(sum(weight * weight for weight in query_vector.values()))

    def contribution(doc, fields, row):
        term, requested, weight, df, _cf, _postings = row
        traces["postings_visited"] += 1
        if doc not in eligible or (requested is not None and requested not in fields):
            return 0.0
        if doc not in length_cache:
            length_cache[doc] = index.length_stats(doc)
        lengths, norm = length_cache[doc]
        actual = [(field, len(positions)) for field, positions in fields.items() if requested is None or field == requested]
        traces["score_work"] += len(actual)
        if ranker == "tfidf":
            idf = tfidf_idf(count, df)
            return weight * idf * idf * sum(weights[field] * tf for field, tf in actual) / max(1e-12, qnorm * norm)
        k1, b = config["k1"], config["b"]
        idf = math.log1p((count - df + 0.5) / (df + 0.5))
        return weight * idf * sum(
            weights[field] * (k1 + 1) * tf / (tf + k1 * (1 - b + b * lengths[field] / max(1e-12, averages[field])))
            for field, tf in actual
        )

    def result(doc, parts):
        return doc, sum(value for _, value in parts), parts

    if strategy == "taat":
        scores = defaultdict(list)
        for row in rows:
            for doc, fields in row[5].items():
                score = contribution(doc, fields, row)
                if score:
                    scores[doc].append((row[0], score))
        traces["peak_accumulators"] = len(scores)
        ordered = heapq.nsmallest(depth, (result(doc, parts) for doc, parts in scores.items()), key=lambda item: (-item[1], item[0]))
        return ordered, traces

    def merged():
        iterators = [iter(row[5].items()) for row in rows]
        queue = []
        for i, iterator in enumerate(iterators):
            doc, fields = next(iterator)
            heapq.heappush(queue, (doc, i, fields))
        traces["peak_accumulators"] = len(queue)
        while queue:
            doc = queue[0][0]
            parts = []
            while queue:
                traces["comparisons"] += 1
                if queue[0][0] != doc:
                    break
                _, i, fields = heapq.heappop(queue)
                score = contribution(doc, fields, rows[i])
                if score:
                    parts.append((rows[i][0], score))
                following = next(iterators[i], None)
                if following:
                    heapq.heappush(queue, (following[0], i, following[1]))
            if parts:
                yield result(doc, parts)
    return heapq.nsmallest(depth, merged(), key=lambda item: (-item[1], item[0])), traces


def likelihood(index, rows, eligible, config, total, depth, traces):
    all_weight = sum(row[2] for row in rows)
    if not all_weight:
        return [], traces
    mu = config["mu"]
    base = sum(weight * math.log(mu * cf / total) for _, _, weight, _, cf, _ in rows)
    matches = defaultdict(list)
    for term, field, weight, _, cf, posting in rows:
        background = mu * cf / total
        for doc, fields in posting.items():
            traces["postings_visited"] += 1
            if doc in eligible:
                tf = sum(len(values) for key, values in fields.items() if field is None or field == key)
                if tf:
                    matches[doc].append((term, weight * math.log1p(tf / background)))
    traces["peak_accumulators"] = len(matches)
    def scored():
        for doc in sorted(eligible):
            parts = [("collection prior", base - all_weight * math.log(index.indexed_length(doc) + mu)), *matches.get(doc, [])]
            traces["score_work"] += len(parts)
            yield doc, sum(value for _, value in parts), parts
    return heapq.nsmallest(depth, scored(), key=lambda item: (-item[1], item[0])), traces


def fuse(branches, k, eligible):
    scores = defaultdict(list)
    for name, results in branches.items():
        for rank, (doc, _score, _details) in enumerate(results, start=1):
            if doc in eligible:
                scores[doc].append((name, rank, 1 / (k + rank)))
    return sorted(((doc, sum(part[2] for part in parts), parts) for doc, parts in scores.items()),
                  key=lambda item: (-item[1], item[0]))
