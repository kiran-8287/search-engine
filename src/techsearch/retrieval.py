"""Rankers use postings directly and share deterministic tie handling."""
from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict
from typing import NamedTuple

from .config import FIELDS
from .indexing import tfidf_idf


class QueryPosting(NamedTuple):
    """One query term and its decoded posting list."""

    term: str
    field: int | None
    weight: float
    document_frequency: int
    collection_frequency: int
    documents: dict


def query_order(item):
    # Identical ordering keeps term contributions reproducible in both traversals.
    (term, field), _weight = item
    return term, -1 if field is None else field


def ranking_order(hit):
    document_id, score, _explanation = hit
    return -score, document_id


def scored_document(document_id, contributions):
    return document_id, sum(score for _, score in contributions), contributions


def bm25_contribution(frequencies, lengths, averages, weights, idf, query_weight, k1, b):
    """Score one term across matching fields using field lengths and TF saturation."""
    field_scores = []
    for field, tf in frequencies:
        # k1 controls how quickly repeats saturate. b controls the field length penalty.
        scaled_length = b * lengths[field] / max(1e-12, averages[field])
        length_factor = 1 - b + scaled_length
        field_scores.append(weights[field] * (k1 + 1) * tf / (tf + k1 * length_factor))
    return query_weight * idf * sum(field_scores)


def tfidf_contribution(frequencies, weights, idf, query_weight, query_norm, document_norm):
    """Return this term's contribution to cosine similarity between TF-IDF vectors."""
    weighted_tf = sum(weights[field] * tf for field, tf in frequencies)
    return query_weight * idf * idf * weighted_tf / max(1e-12, query_norm * document_norm)


def term_at_a_time(postings, contribution, trace):
    """Accumulate scores by visiting each term's complete posting list in turn."""
    scores = defaultdict(list)
    for posting in postings:
        for document_id, fields in posting.documents.items():
            score = contribution(document_id, fields, posting)
            if score:
                scores[document_id].append((posting.term, score))
    trace["peak_accumulators"] = len(scores)
    return (scored_document(document_id, parts) for document_id, parts in scores.items())


def document_at_a_time(postings, contribution, trace):
    """Merge sorted posting lists, scoring all occurrences of one document together."""
    iterators = [iter(posting.documents.items()) for posting in postings]
    queue = []
    for term_index, iterator in enumerate(iterators):
        document_id, fields = next(iterator)
        heapq.heappush(queue, (document_id, term_index, fields))
    trace["peak_accumulators"] = len(queue)
    while queue:
        document_id = queue[0][0]
        parts = []
        while queue:
            trace["comparisons"] += 1
            if queue[0][0] != document_id:
                break
            _, term_index, fields = heapq.heappop(queue)
            posting = postings[term_index]
            score = contribution(document_id, fields, posting)
            if score:
                parts.append((posting.term, score))
            following = next(iterators[term_index], None)
            if following:
                next_document, next_fields = following
                heapq.heappush(queue, (next_document, term_index, next_fields))
        if parts:
            yield scored_document(document_id, parts)


def lexical(index, query, eligible, config, *, ranker="bm25", strategy="taat", depth=100):
    """Rank eligible documents and return the top hits and traversal counters."""
    trace = {"postings_visited": 0, "comparisons": 0, "score_work": 0, "peak_accumulators": 0}
    postings = []
    for (term, field), weight in sorted(query.items(), key=query_order):
        df, cf, documents = index.posting(term)
        if df and eligible:
            postings.append(QueryPosting(term, field, weight, df, cf, documents))
    if ranker == "likelihood":
        return likelihood(index, postings, eligible, config, index.info["occurrences"], depth, trace)

    document_count = index.info["parents"]
    averages = index.info["avg_lengths"]
    weights = [config["field_weights"][field] for field in FIELDS]
    k1, b = config["k1"], config["b"]
    length_cache = {}
    idfs = {}
    query_vector = Counter()
    for posting in postings:
        # df is the number of parents containing the term, across all fields.
        df = posting.document_frequency
        if ranker == "tfidf":
            idfs[posting.term] = tfidf_idf(document_count, df)
            query_vector[posting.term] += posting.weight * idfs[posting.term]
        else:
            idfs[posting.term] = math.log1p((document_count - df + 0.5) / (df + 0.5))
    query_norm = math.sqrt(sum(weight * weight for weight in query_vector.values()))

    def contribution(document_id, fields, posting):
        trace["postings_visited"] += 1
        requested = posting.field
        if document_id not in eligible or (requested is not None and requested not in fields):
            return 0.0
        if document_id not in length_cache:
            length_cache[document_id] = index.length_stats(document_id)
        lengths, document_norm = length_cache[document_id]
        # Each stored position is one occurrence, so list length gives term frequency.
        frequencies = [(field, len(positions)) for field, positions in fields.items()
                       if requested is None or field == requested]
        trace["score_work"] += len(frequencies)
        idf = idfs[posting.term]
        if ranker == "tfidf":
            return tfidf_contribution(frequencies, weights, idf, posting.weight, query_norm, document_norm)
        return bm25_contribution(frequencies, lengths, averages, weights, idf, posting.weight, k1, b)

    if strategy == "taat":
        scored = term_at_a_time(postings, contribution, trace)
    else:
        scored = document_at_a_time(postings, contribution, trace)
    return heapq.nsmallest(depth, scored, key=ranking_order), trace


def likelihood(index, rows, eligible, config, total, depth, traces):
    """Score eligible parents with Dirichlet smoothing over known query terms."""
    query_weight = sum(row.weight for row in rows)
    if not query_weight:
        return [], traces
    mu = config["mu"]
    base = sum(row.weight * math.log(mu * row.collection_frequency / total) for row in rows)
    matches = defaultdict(list)
    for posting in rows:
        background = mu * posting.collection_frequency / total
        for document_id, fields in posting.documents.items():
            traces["postings_visited"] += 1
            if document_id not in eligible:
                continue
            tf = sum(len(positions) for field, positions in fields.items()
                     if posting.field is None or posting.field == field)
            if tf:
                adjustment = posting.weight * math.log1p(tf / background)
                matches[document_id].append((posting.term, adjustment))
    traces["peak_accumulators"] = len(matches)

    def scored():
        for document_id in sorted(eligible):
            # Missing terms still contribute their collection probability.
            prior = base - query_weight * math.log(index.indexed_length(document_id) + mu)
            parts = [("collection prior", prior), *matches.get(document_id, [])]
            traces["score_work"] += len(parts)
            yield scored_document(document_id, parts)

    return heapq.nsmallest(depth, scored(), key=ranking_order), traces


def fuse(branches, k, eligible):
    """Add reciprocal ranks from each branch and keep the branch contributions."""
    contributions = defaultdict(list)
    for branch, results in branches.items():
        for rank, (document_id, _score, _details) in enumerate(results, start=1):
            if document_id in eligible:
                contributions[document_id].append((branch, rank, 1 / (k + rank)))
    hits = []
    for document_id, parts in contributions.items():
        hits.append((document_id, sum(score for _, _, score in parts), parts))
    return sorted(hits, key=ranking_order)
