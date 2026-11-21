"""Offline comparisons and explicit MMR reranking."""
from __future__ import annotations

import math
import random
import statistics
import tracemalloc
from collections import Counter
from contextlib import ExitStack
from time import perf_counter

from .compression import CODECS
from .indexing import Index, tfidf_idf
from .io import digest, now, write_json
from .preprocessing import analyze


def mmr(rows, index, coefficient=0.7, window=35):
    rows = list(rows)
    pool = rows[:window]
    if len(pool) < 2:
        return rows
    weights = {row[0]: 1 - rank / (len(pool) - 1) for rank, row in enumerate(pool)}
    terms = {doc: set(index.terms(doc)) for doc, *_ in pool}
    chosen = []
    similarity = dict.fromkeys(terms, 0.0)
    while pool:
        def score(row):
            doc = row[0]
            return coefficient * weights[doc] - (1 - coefficient) * similarity[doc]
        winner = max(pool, key=lambda row: (score(row), -row[0]))
        doc, relevance, details = winner
        chosen.append((doc, relevance, [*details, ("mmr", score(winner), similarity[doc])]))
        pool.remove(winner)
        for other, *_ in pool:
            union = terms[doc] | terms[other]
            overlap = len(terms[doc] & terms[other]) / len(union) if union else 0
            similarity[other] = max(similarity[other], overlap)
    return chosen + rows[window:]


def percentile(numbers, p):
    values = sorted(numbers)
    return values[max(0, math.ceil(len(values) * p) - 1)] if values else None


def execution_report(service, queries, repeats):
    rows = []
    for query in queries:
        signatures = set()
        for condition in ("fresh-index-reader", "reused-index-reader"):
            for strategy in ("taat", "daat"):
                times, peaks = [], []
                with ExitStack() as stack:
                    shared = Index(service.release.path, stack, files=service.index_files) if condition == "reused-index-reader" else None
                    for _ in range(repeats):
                        tracemalloc.start()
                        try:
                            started = perf_counter()
                            result = service.search(query, mode="keyword", strategy=strategy, index=shared)
                            times.append((perf_counter() - started) * 1000)
                            peaks.append(tracemalloc.get_traced_memory()[1])
                        finally:
                            tracemalloc.stop()
                        signatures.add(tuple((hit["id"], hit["score"]) for hit in result["results"]))
                    traces = result["trace"]["branches"].get("lexical", {})
                    rows.append({"query": query, "condition": condition, "strategy": strategy,
                                 "p50_ms": statistics.median(times), "p95_ms": percentile(times, .95),
                                 "traced_python_peak_bytes": max(peaks), "work": traces})
        if len(signatures) != 1:
            raise ValueError(f"TAAT and DAAT diverged for {query!r}")
    return rows


def compression_report(release, queries, repeats):
    terms = sorted({token.term for query in queries for token in analyze(query)})
    reference = None
    reports = {}
    for codec in CODECS:
        times = []
        for _ in range(repeats):
            with ExitStack() as stack:
                i = Index(release.path, stack, codec)
                t = perf_counter()
                postings = [i.posting(term) for term in terms]
                times.append((perf_counter() - t) * 1000)
            if reference is not None and postings != reference:
                raise ValueError(f"Posting encodings differ in {codec}")
            reference = postings
        reports[codec] = {**release.info["lexical"]["compression"][codec],
                          "lookup_decode_ms": times, "median_lookup_decode_ms": statistics.median(times)}
    return {"terms": terms, "codecs": reports, "repeats": repeats}


def latent_report(service, window, components, clusters, seed, queries):
    started = perf_counter()
    import numpy as np
    from scipy.sparse import csr_matrix
    from sklearn.cluster import KMeans
    from sklearn.decomposition import TruncatedSVD
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import normalize

    ids = sorted(service.parents)
    if len(ids) < 4:
        raise ValueError("LSI and K-means need at least four canonical parents.")
    rng = random.Random(seed)
    ids = sorted(rng.sample(ids, min(window, len(ids))))
    with ExitStack() as stack:
        index = Index(service.release.path, stack, files=service.index_files)
        vocabulary = dict(index.frequent_terms(2, 30000))
        if len(vocabulary) < 3 or len(ids) < 4:
            raise ValueError("The sample has too few documents or repeated terms.")
        columns = {term: col for col, term in enumerate(vocabulary)}
        values, ri, ci = [], [], []
        for row, doc in enumerate(ids):
            for term, fields in index.terms(doc).items():
                if term in vocabulary:
                    ri.append(row)
                    ci.append(columns[term])
                    values.append(sum(fields.values()) * tfidf_idf(index.info["parents"], vocabulary[term]))
    matrix = normalize(csr_matrix((values, (ri, ci)), shape=(len(ids), len(vocabulary))))
    svd = TruncatedSVD(n_components=min(components, len(ids) - 1, len(vocabulary) - 1), random_state=seed)
    latent = normalize(svd.fit_transform(matrix))
    count = min(clusters, len(ids) - 1)
    model = KMeans(n_clusters=count, random_state=seed, n_init=10)
    labels = model.fit_predict(latent)
    n = len(set(labels))
    diagnostics = {"clusters": count, "effective_clusters": n, "inertia": float(model.inertia_),
                   "sizes": dict(Counter(map(int, labels))),
                   "silhouette": float(silhouette_score(latent, labels, sample_size=min(1000, len(ids)), random_state=seed))
                   if 1 < n < len(ids) else None}
    anchor = latent[0]
    cosine = latent @ anchor
    nearest = sorted(range(1, len(ids)), key=lambda row: (-float(cosine[row]), ids[row]))[:10]
    query_runs = []
    for query in queries:
        frequencies = Counter(token.term for token in analyze(query) if token.term in columns)
        if not frequencies:
            query_runs.append({"query": query, "hits": []})
            continue
        vector = csr_matrix(([tf * tfidf_idf(service.index_files.info["parents"], vocabulary[term])
                              for term, tf in frequencies.items()],
                             ([0] * len(frequencies), [columns[term] for term in frequencies])),
                            shape=(1, len(columns)))
        similarities = latent @ normalize(svd.transform(normalize(vector)))[0]
        order = sorted(range(len(ids)), key=lambda row: (-float(similarities[row]), ids[row]))[:10]
        query_runs.append({"query": query, "hits": [{"id": service.parents[ids[row]]["stable"], "cosine": float(similarities[row])}
                                                   for row in order]})
    return {"sample_ids": [service.parents[doc]["stable"] for doc in ids], "vocabulary": len(vocabulary),
            "configuration": {"seed": seed, "window": window, "requested_components": components, "requested_clusters": clusters},
            "lsi": {"dimensions": latent.shape[1], "explained_variance_ratio": float(np.sum(svd.explained_variance_ratio_)),
                    "anchor": service.parents[ids[0]]["stable"],
                    "nearest": [{"id": service.parents[ids[row]]["stable"], "cosine": float(cosine[row])} for row in nearest],
                    "query_runs": query_runs},
            "kmeans": {**diagnostics, "assignments": list(map(int, labels))},
            "seconds": perf_counter() - started}


def retrieval_report(service, queries):
    """Measured algorithm interventions, without creating relevance labels."""
    from .feedback import rocchio
    from .query import Matcher, parse
    from .retrieval import lexical

    rows = []
    for query in queries:
        methods = {}
        for name, options in (("bm25", {}), ("likelihood", {"ranker": "likelihood"}),
                              ("pagerank", {"authority": True}), ("mmr", {"diversify": True})):
            result = service.search(query, mode="keyword", **options)
            methods[name] = {"options": {"mode": "keyword", **options}, "timing_ms": result["timing_ms"],
                             "trace": result["trace"],
                             "hits": [{"id": hit["id"], "score": hit["score"]} for hit in result["results"]]}
        started = perf_counter()
        with ExitStack() as stack:
            index = Index(service.release.path, stack, files=service.index_files)
            parsed = parse(query, "keyword", service.settings.search, service.topics)
            matcher = Matcher(index, service.metadata, service.all_docs, service.settings.search)
            eligible = matcher.match(parsed.constraint)
            original = matcher.scoring(parsed.scoring)
            # Select the first BM25 hit as a declared vector probe. This is a
            # controlled transformation, never a qrel or a user judgment.
            probe = methods["bm25"]["hits"][:1]
            interventions = {hit["id"]: 1 for hit in probe}
            expanded, terms = rocchio(index, original, interventions, service.stable_to_doc, eligible)
            ranked, work = lexical(index, expanded, eligible, service.settings.search,
                                   depth=service.settings.search["max_results"])
            methods["rocchio_probe"] = {
                "probe_document": probe[0]["id"] if probe else None,
                "beta": .75, "gamma": .25, "expansion_limit": 6,
                "expansion": terms, "timing_ms": (perf_counter() - started) * 1000,
                "work": work, "hits": [{"id": service.parents[doc]["stable"], "score": score}
                                       for doc, score, _ in ranked]}
        rows.append({"query": query, "methods": methods})
    return {"queries": list(queries), "rows": rows,
            "label_policy": "No relevance labels or quality metrics. Rocchio uses an explicitly selected BM25 vector probe; it is not an annotation."}


def save_report(settings, release, name, report):
    value = {"release_id": release.id, "created_at": now(), "name": name,
             "config_fingerprint": settings.fingerprint, "configuration": settings.default, "report": report}
    home = settings.path("artifacts") / "reports" / release.id
    write_json(home / f"{name}-{digest(value)[:16]}.json", value)
    write_json(home / f"{name}.json", value)
    return value
