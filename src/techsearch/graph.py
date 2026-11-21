"""PageRank on the induced MDN graph and a bounded source-slot reranker."""
from __future__ import annotations

from collections import deque

from .io import write_json
from .repository import Documents


def pagerank(adjacency, damping, tolerance, iterations):
    nodes = sorted(adjacency)
    if not nodes:
        return {}, 0, 0.0
    ranks = dict.fromkeys(nodes, 1 / len(nodes))
    for iteration in range(1, iterations + 1):
        dangling = sum(ranks[node] for node in nodes if not adjacency[node])
        base = (1 - damping + damping * dangling) / len(nodes)
        following = dict.fromkeys(nodes, base)
        for node in nodes:
            if adjacency[node]:
                share = damping * ranks[node] / len(adjacency[node])
                for target in adjacency[node]:
                    following[target] += share
        residual = sum(abs(following[node] - ranks[node]) for node in nodes)
        ranks = following
        if residual <= tolerance:
            break
    return ranks, iteration, residual


def build_graph(directory, config, output=None):
    documents = Documents(directory)
    nodes = {doc: row["stable"] for doc, row in documents.parents.items() if row["source"] == "mdn"}
    edges = [(row["source"], row["destination"]) for row in documents.edges()
             if row["source"] in nodes and row["destination"] in nodes]
    adjacency = {node: [] for node in nodes}
    weak = {node: set() for node in nodes}
    for source, target in edges:
        adjacency[source].append(target)
        weak[source].add(target)
        weak[target].add(source)
    remaining = set(nodes)
    sizes = []
    while remaining:
        seed = remaining.pop()
        queue = deque([seed])
        size = 0
        while queue:
            size += 1
            for target in weak[queue.popleft()] & remaining:
                remaining.remove(target)
                queue.append(target)
        sizes.append(size)
    ranks, iterations, residual = pagerank(adjacency, config["damping"], config["tolerance"], config["iterations"])
    top = sorted(ranks, key=lambda node: (-ranks[node], node))[:20]
    report = {"parents": len(nodes), "retained_edges": len(edges), "isolates": sum(not values for values in weak.values()),
              "dangling": sum(not targets for targets in adjacency.values()), "weak_component_sizes": sorted(sizes, reverse=True),
              "damping": config["damping"], "tolerance": config["tolerance"], "iterations": iterations, "residual": residual,
              "top_pages": [{"id": nodes[node], "score": ranks[node]} for node in top]}
    write_json(output or (directory / "graph.json"), {"ranks": ranks, "report": report})
    return report


def rerank_slots(rows, parents, ranks, window, weight):
    import math

    rows = list(rows)
    slots = [slot for slot, hit in enumerate(rows[:window]) if parents[hit[0]]["source"] == "mdn"]
    boost = [(slot, rows[slot], math.log1p(len(ranks) * ranks.get(str(rows[slot][0]), 0))) for slot in slots]
    ordered = sorted(boost, key=lambda item: (item[0] - weight * window * item[2], item[0]))
    for slot, (old, (doc, score, parts), authority) in zip(slots, ordered):
        rows[slot] = doc, score, [*parts, ("mdn-authority", authority, old + 1)]
    return rows
