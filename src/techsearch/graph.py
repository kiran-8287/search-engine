"""PageRank on the induced MDN graph and a bounded source-slot reranker."""
from __future__ import annotations

import math
from collections import deque

from .io import write_json
from .repository import Documents


def pagerank(adjacency, damping, tolerance, iterations):
    """Spread page weight over outgoing links until rank changes are small."""
    nodes = sorted(adjacency)
    if not nodes:
        return {}, 0, 0.0
    ranks = dict.fromkeys(nodes, 1 / len(nodes))
    for iteration in range(1, iterations + 1):
        dangling_weight = sum(ranks[node] for node in nodes if not adjacency[node])
        # A page without outgoing links shares its weight across all nodes.
        base = (1 - damping + damping * dangling_weight) / len(nodes)
        following = dict.fromkeys(nodes, base)
        for node in nodes:
            targets = adjacency[node]
            if not targets:
                continue
            share = damping * ranks[node] / len(targets)
            for target in targets:
                following[target] += share
        residual = sum(abs(following[node] - ranks[node]) for node in nodes)
        ranks = following
        if residual <= tolerance:
            break
    return ranks, iteration, residual


def component_sizes(neighbors):
    """Count connected groups when link direction is ignored."""
    remaining = set(neighbors)
    sizes = []
    while remaining:
        seed = remaining.pop()
        queue = deque([seed])
        size = 0
        while queue:
            node = queue.popleft()
            size += 1
            for target in neighbors[node] & remaining:
                remaining.remove(target)
                queue.append(target)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def build_graph(directory, config, output=None):
    """Build PageRank and graph statistics for links between MDN parents."""
    documents = Documents(directory)
    nodes = {document_id: row["stable"] for document_id, row in documents.parents.items() if row["source"] == "mdn"}
    adjacency = {node: [] for node in nodes}
    neighbors = {node: set() for node in nodes}
    edge_count = 0
    for edge in documents.edges():
        source, target = edge["source"], edge["destination"]
        if source not in nodes or target not in nodes:
            continue
        adjacency[source].append(target)
        neighbors[source].add(target)
        neighbors[target].add(source)
        edge_count += 1
    ranks, iterations, residual = pagerank(adjacency, config["damping"], config["tolerance"], config["iterations"])
    top = sorted(ranks, key=lambda node: (-ranks[node], node))[:20]
    report = {"parents": len(nodes), "retained_edges": edge_count, "isolates": sum(not values for values in neighbors.values()),
              "dangling": sum(not targets for targets in adjacency.values()), "weak_component_sizes": component_sizes(neighbors),
              "damping": config["damping"], "tolerance": config["tolerance"], "iterations": iterations, "residual": residual,
              "top_pages": [{"id": nodes[node], "score": ranks[node]} for node in top]}
    write_json(output or (directory / "graph.json"), {"ranks": ranks, "report": report})
    return report


def rerank_slots(rows, parents, ranks, window, weight):
    """Promote pages by authority within the existing MDN result slots."""
    rows = list(rows)
    slots = []
    candidates = []
    for slot, hit in enumerate(rows[:window]):
        document_id = hit[0]
        if parents[document_id]["source"] != "mdn":
            continue
        slots.append(slot)
        authority = math.log1p(len(ranks) * ranks.get(str(document_id), 0))
        adjusted_position = slot - weight * window * authority
        candidates.append((adjusted_position, slot, hit, authority))
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
    for slot, (_, previous_slot, (document_id, score, parts), authority) in zip(slots, candidates):
        rows[slot] = document_id, score, [*parts, ("mdn-authority", authority, previous_slot + 1)]
    return rows
