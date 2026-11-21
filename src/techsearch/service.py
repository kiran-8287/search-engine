"""Single ranking entry point for Search, Lab, CLI and evaluation."""
from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import ExitStack
from time import perf_counter
from urllib.parse import quote

from . import graph
from .dense import Dense, DenseUnavailable
from .experiments import mmr
from .feedback import Runtime, rocchio, search_id
from .indexing import Index, IndexFiles
from .io import ROUTER_VERSION, digest, read_json
from .preprocessing import analyze
from .query import MODES, IDENTIFIER, Matcher, QueryError, lex, parse
from .repository import Documents
from .retrieval import fuse, lexical


def auto_mode(text, search):
    tokens = lex(text, search["query_tokens"])
    if any(token.kind in {"OR", "AND", "NOT"} for token in tokens):
        return "boolean", "explicit Boolean operators"
    if any(token.field for token in tokens):
        return "field", "explicit field constraint"
    if any(token.kind == "phrase" for token in tokens):
        return "phrase", "quoted original tokens"
    if any(token.kind == "prefix" for token in tokens):
        return "prefix", "bounded prefix"
    terms = list(analyze(text))
    if any(IDENTIFIER.search(token.value) for token in tokens) or any(not term.term[0].isalnum() for term in terms):
        return "keyword", "API identifier or operator"
    return "hybrid", "conceptual or ambiguous words"


def page_of(result, page, size):
    start = (page - 1) * size
    return {**result, "results": result["results"][start:start + size], "page": page,
            "page_size": size, "total": len(result["results"])}


def highlight(text, left, right, spans):
    cursor = left
    pieces = []
    for start, end in sorted(spans):
        start, end = max(cursor, start), min(right, end)
        if start >= end:
            continue
        if start > cursor:
            pieces.append({"text": text[cursor:start], "match": False})
        pieces.append({"text": text[start:end], "match": True})
        cursor = end
    if cursor < right:
        pieces.append({"text": text[cursor:right], "match": False})
    return pieces


class SearchService:
    def __init__(self, settings, release, *, persistent=False):
        self.settings = settings
        self.release = release
        self.runtime = Runtime(settings.path("runtime")) if persistent else None
        self.dense = None
        self.dense_error = None
        self.dense_lock = threading.RLock()
        self.topics = sorted(set(settings.scope["mdn_roots"].values()) | set(settings.scope["browser_tags"]))
        self.documents = Documents(release.path)
        self.index_files = IndexFiles(release.path)
        self.parents = self.documents.parents
        self.stable_to_doc = self.documents.stable_to_doc
        self.metadata = {field: defaultdict(set) for field in ("source", "topic", "tag")}
        for doc, parent in self.parents.items():
            for field in ("source", "topic"):
                self.metadata[field][parent[field]].add(doc)
            for tag in parent["tags"]:
                self.metadata["tag"][tag].add(doc)
        self.all_docs = set(self.parents)
        self.authority = read_json(release.path / "graph.json")["ranks"]

    def require_dense(self):
        with self.dense_lock:
            if self.dense_error:
                raise DenseUnavailable(self.dense_error)
            if self.dense is None:
                try:
                    self.dense = Dense(self.release, self.settings)
                except (ImportError, RuntimeError, OSError, ValueError) as error:
                    self.dense_error = str(error) if isinstance(error, DenseUnavailable) else "Dense encoder could not be opened. Check the local model and dense dependencies."
                    raise DenseUnavailable(self.dense_error) from error
            return self.dense

    def search(self, query, *, mode="auto", source=None, topic=None, ranker="bm25", strategy="taat",
               k1=None, b=None, rrf_k=None, cutoff=None, depth=None, authority=False,
               diversify=False, apply_feedback=False, session=None, index=None, boolean_constraints=False, **extra):
        if extra:
            raise QueryError("Unsupported search setting.")
        started = perf_counter()
        config = dict(self.settings.search)
        if len(query) > config["query_length"]:
            raise QueryError(f"Use at most {config['query_length']} characters.")
        if mode not in ("auto", *MODES) or ranker not in {"bm25", "tfidf", "likelihood"} or strategy not in {"taat", "daat"}:
            raise QueryError("Unknown mode, ranker, or execution strategy.")
        if source not in {None, "mdn", "stackoverflow"} or topic not in {None, *self.topics}:
            raise QueryError("Unknown source or topic filter.")
        if ((k1 is not None and not 0 < k1 <= 5) or (b is not None and not 0 <= b <= 1)
                or (rrf_k is not None and not 1 <= rrf_k <= 500) or (cutoff is not None and not 0 < cutoff < 1)
                or (depth is not None and not 1 <= depth <= config["candidate_depth"])):
            raise QueryError("Ranking option exceeds the configured range.")
        if strategy == "daat" and ranker == "likelihood":
            raise QueryError("Dirichlet likelihood does not provide DAAT execution.")
        if apply_feedback and (mode == "semantic" or not session or self.runtime is None):
            raise QueryError("Feedback refinement requires a session and a lexical branch.")
        config.update({key: value for key, value in {"k1": k1, "b": b, "rrf_k": rrf_k, "dense_min_similarity": cutoff}.items() if value is not None})
        if not query.strip() and (source or topic):
            query = " ".join(part for part in (f"source:{source}" if source else "", f"topic:{topic}" if topic else "") if part)
        manual = mode != "auto"
        selected, rule = (mode, "manual") if manual else auto_mode(query, config)
        syntax = "boolean" if boolean_constraints else selected
        parsed = parse(query, syntax, config, self.topics)
        if not parsed.scoring and selected in {"semantic", "hybrid"} and manual and not boolean_constraints:
            raise QueryError("Provide scoring text with the filters for this mode.")
        trace = {"router_version": ROUTER_VERSION, "rule": rule, "selected_mode": selected, "ranker": ranker,
                 "strategy": strategy, "branches": {}, "fallback": None, "reranking": [],
                 "parameters": {"k1": config["k1"], "b": config["b"], "rrf_k": config["rrf_k"],
                                "cutoff": config["dense_min_similarity"], "candidate_depth": depth or config["candidate_depth"]}}
        trace["constraint"] = repr(parsed.constraint) if parsed.constraint else None
        effective_depth = depth or config["candidate_depth"]
        scope = digest([query, source, topic])
        warnings = []
        allowed = self.metadata["source"].get(source, set()) if source else self.all_docs
        if topic:
            allowed = allowed & self.metadata["topic"].get(topic, set())
        with ExitStack() as stack:
            index = index if index is not None else Index(self.release.path, stack, files=self.index_files)
            index.begin_query(config["max_query_posting_occurrences"])
            corpus = stack.enter_context(self.documents.reader())
            matcher = Matcher(index, self.metadata, allowed, config)
            eligible = matcher.match(parsed.constraint)
            trace["eligible"] = len(eligible)
            q = matcher.scoring(parsed.scoring, fuzzy=selected == "fuzzy")
            if apply_feedback:
                judgments = self.runtime.judgments(session, self.release.id, scope)
                q, expansion = rocchio(index, q, judgments, self.stable_to_doc, eligible)
                trace["reranking"].append({"method": "rocchio", "judgments": len(judgments), "expansion": expansion})
            branches = {}
            if not parsed.scoring:
                rows = [(doc, 0.0, []) for doc in sorted(eligible)[:effective_depth]]
            else:
                if selected != "semantic":
                    t = perf_counter()
                    branches["lexical"], stats = lexical(index, q, eligible, config, ranker=ranker, strategy=strategy, depth=effective_depth)
                    trace["branches"]["lexical"] = {**stats, "seconds": perf_counter() - t}
                if selected in {"semantic", "hybrid"}:
                    try:
                        dense = self.require_dense()
                        minimum = config["dense_min_similarity"]
                        if not manual and not branches.get("lexical"):
                            minimum = max(minimum, config["dense_unanchored_min_similarity"])
                            trace["adequacy"] = "higher dense cutoff without a lexical candidate"
                        with self.dense_lock:
                            branches["dense"], trace["branches"]["dense"] = dense.rank(
                                parsed.semantic_text, eligible, minimum, effective_depth)
                    except DenseUnavailable as error:
                        if manual:
                            raise
                        trace["fallback"] = str(error)
                        warnings.append("Dense search is unavailable. These results use lexical ranking.")
                if selected == "hybrid":
                    rows = fuse(branches, config["rrf_k"], eligible) if "dense" in branches else branches["lexical"]
                else:
                    rows = next(iter(branches.values()), [])
                if selected == "boolean" or (boolean_constraints and selected == "keyword"):
                    seen = {hit[0] for hit in rows}
                    rows.extend((doc, 0.0, []) for doc in sorted(eligible - seen)[:max(0, effective_depth - len(rows))])
            rows = [row for row in rows if row[0] in eligible]
            if authority:
                graph_settings = self.settings.default["graph"]
                rows = graph.rerank_slots(rows, self.parents, self.authority, graph_settings["window"], graph_settings["weight"])
                trace["reranking"].append({"method": "mdn-authority", "window": graph_settings["window"]})
            if diversify:
                rows = mmr(rows, index)
                trace["reranking"].append({"method": "mmr", "coefficient": .7, "window": 35})
            trace["expansions"] = [{"kind": kind, "from": term, "terms": values} for (kind, term), values in matcher.expansions.items()]
            dense_passages = {doc: details[0][1] for doc, _, details in branches.get("dense", []) if details}
            read_passage = stack.enter_context(self.dense.passages.reader()) if dense_passages else None
            snippets = [self.hit(row, rank, q, index, corpus, dense_passages.get(row[0]), read_passage)
                        for rank, row in enumerate(rows[:config["max_results"]], 1)]
            suggestions = []
            if not snippets and selected in {"keyword", "hybrid", "fuzzy"} and not parsed.constraint:
                for token in list(analyze(query))[:5]:
                    suggestions.extend(candidate for candidate, _ in matcher.fuzzy(token.term) if candidate != token.term)
        result = {"search_id": search_id(), "release_id": self.release.id, "query": query, "mode": selected,
                  "results": snippets, "warnings": warnings, "suggestions": list(dict.fromkeys(suggestions))[:5],
                  "timing_ms": (perf_counter() - started) * 1000, "trace": trace}
        if session and self.runtime:
            self.runtime.store(session, self.release.id, scope, result)
        return result

    def hit(self, scored, rank, query, index, corpus, passage, read_passage):
        doc, score, details = scored
        parent = corpus(doc)
        info = parent["metadata"]
        lexical_evidence = {}
        for (term, requested), weight in query.items():
            fields = index.posting(term)[2].get(doc, {})
            for field, positions in fields.items():
                if requested is not None and requested != field:
                    continue
                for seg, _pos, start, end, original in positions:
                    entry = lexical_evidence.setdefault(seg, {"score": 0, "spans": set(), "terms": set()})
                    if term not in entry["terms"]:
                        entry["score"] += weight * (1 if original else .5)
                        entry["terms"].add(term)
                    if len(entry["spans"]) < 24:
                        entry["spans"].add((start, end))
        chosen = None
        dense_evidence = read_passage(passage)["spans"] if passage is not None else None
        non_title = {seg: e for seg, e in lexical_evidence.items() if seg != 0}
        if non_title:
            chosen = min(non_title, key=lambda seg: (-non_title[seg]["score"], seg))
        elif dense_evidence:
            chosen = dense_evidence[0][0]
        if chosen is not None:
            row = parent["segments"][chosen]
        else:
            row = next((segment for segment in parent["segments"] if segment["field"] not in {"title", "tag"}), None)
        text, evidence, parts = "", None, []
        if row:
            text = row["text"]
            detail = row
            found = lexical_evidence.get(row["ordinal"], {"spans": set(), "terms": set()})
            offset = min((start for start, _ in found["spans"]), default=0)
            if not found["spans"] and dense_evidence:
                offset = next((start for seg, start, _ in dense_evidence if seg == row["ordinal"]), 0)
            left = max(0, offset - 75)
            right = min(len(text), left + 255)
            parts = highlight(text, left, right, found["spans"])
            if left:
                parts.insert(0, {"text": "…", "match": False})
            if right < len(text):
                parts.append({"text": "…", "match": False})
            answer = detail.get("answer_id")
            anchor = detail.get("source_anchor")
            link = f"https://stackoverflow.com/a/{answer}" if answer else parent["url"]
            if anchor and isinstance(anchor, str):
                link = link.split("#")[0] + "#" + quote(anchor, safe="-_")
            evidence = {"section": detail.get("heading_path", []), "ordinal": row["ordinal"], "url": link,
                        "field": row["field"], "answer_id": answer, "matched_terms": sorted(found["terms"]),
                        "dense_passage": passage}
        return {"id": parent["id"], "release_id": self.release.id, "rank": rank, "title": parent["title"], "source": parent["source"], "topic": parent["topic"],
                "url": parent["url"], "tags": parent["tags"], "author": info.get("author"), "author_url": info.get("author_url"),
                "license": info.get("content_license"), "score": score, "explanation": details, "snippet": parts, "evidence": evidence}

    def document(self, stable):
        return document_detail(self.documents, self.release.id, stable)

    def suggestions(self, prefix):
        tokens = list(analyze(prefix))
        if len(tokens) != 1 or len(tokens[0].term) < 2:
            return []
        with ExitStack() as stack:
            index = Index(self.release.path, stack, files=self.index_files)
            return index.prefix(tokens[0].term, 8)


def document_detail(repository, release_id, stable):
    parent = repository.document(stable)
    segments = [segment for segment in parent["segments"] if segment["field"] not in {"title", "tag"}]
    return {**parent, "release_id": release_id, "segments": segments}
