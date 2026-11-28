from contextlib import ExitStack

import numpy as np
import pytest

from techsearch.compression import CODECS, decode, encode, gaps, pack_postings, unpack_postings
from techsearch.dense import exact_parent_hits
from techsearch.evaluation import scores
from techsearch.experiments import cluster_label_terms, compression_report
from techsearch.graph import pagerank
from techsearch.indexing import Index
from techsearch.preprocessing import analyze
from techsearch.query import FIELD_ID, Matcher, Operator, QueryError, edit_distance, lex, parse
from techsearch.retrieval import fuse
from techsearch.service import auto_mode


def test_code_aware_analysis_and_offsets():
    text = "Promise.all querySelector --main-color === => ??. C++ <a>"
    tokens = list(analyze(text))
    assert {token.term for token in tokens} >= {"promise.all", "queryselector", "--main-color", "===", "=>", "??", "c++", "<a>"}
    assert tokens[0].aliases == ("all", "promise")
    assert tokens[1].aliases == ("query", "selector")
    assert text[tokens[-1].start:tokens[-1].end] == "<a>"


@pytest.mark.parametrize(("query", "mode"), [
    ("wait for several JavaScript promises to finish", "hybrid"),
    ("how do TypeScript promises settle", "hybrid"),
    ("Promise.all", "keyword"),
    ("document.querySelector examples", "keyword"),
    ("querySelectorAll()", "keyword"),
    ("x === y", "keyword"),
    ('"event bubbling"', "phrase"),
    ("source:mdn title:Promise.all", "field"),
    ("promise AND (resolve OR reject) AND NOT xhr", "boolean"),
])
def test_auto_distinguishes_prose_from_exact_syntax(query, mode, settings):
    assert auto_mode(query, settings.search)[0] == mode


def test_cluster_labels_keep_informative_terms_in_weight_order():
    terms = ["the", "=", "123", "and", "fetch", "c++", "css-grid", "dom", "unused"]
    weights = [12, 11, 10, 9, 5, 7, 5, 3, -2]
    assert cluster_label_terms(terms, weights) == ["c++", "fetch", "css-grid", "dom"]
    assert cluster_label_terms(terms, weights, limit=2) == ["c++", "fetch"]


def test_compression_warms_each_codec_and_rotates_the_same_lookup_batch(monkeypatch):
    from types import SimpleNamespace

    opened = []
    batches = []

    class Reader:
        def __init__(self, path, stack, codec):
            opened.append(codec)
            self.batch = []
            batches.append(self.batch)

        def posting(self, term):
            self.batch.append(term)
            return (term, {})

    monkeypatch.setattr("techsearch.experiments.Index", Reader)
    formats = {codec: {"artifact_bytes": 10} for codec in CODECS}
    release = SimpleNamespace(path=None, info={"lexical": {"compression": formats}})
    result = compression_report(release, ["css grid", "grid template"], repeats=3)
    assert result["terms"] == ["css", "grid", "template"] and result["warmups"] == 1
    order = list(CODECS)
    assert opened == order + order + order[1:] + order[:1] + order[2:] + order[:2]
    assert all(batch == result["terms"] for batch in batches)
    assert all(len(codec["lookup_decode_ms"]) == 3 for codec in result["codecs"].values())


def test_prefix_budget_applies_to_terms_in_the_requested_field():
    title, body = (FIELD_ID[field] for field in ("title", "body"))
    matches = {
        "abort": {0: {body: []}},
        "abortcontroller": {0: {title: []}},
        "abortsignal": {1: {title: []}},
    }

    class Vocabulary:
        def prefix(self, prefix, limit):
            return [term for term in matches if term.startswith(prefix)][:limit]

        def posting(self, term):
            return 1, 1, matches[term]

    matcher = Matcher(Vocabulary(), {}, {0}, {"expansion": 1, "vocabulary_scan": 3})
    assert matcher.prefix("Abort", "title") == [("abortcontroller", 1.0)]
    assert matcher.prefix("Abort", "body") == [("abort", 1.0)]
    with pytest.raises(QueryError, match="matches more than 1"):
        matcher.prefix("Abort")
    matcher = Matcher(Vocabulary(), {}, {0, 1}, {"expansion": 1, "vocabulary_scan": 3})
    with pytest.raises(QueryError, match="matches more than 1"):
        matcher.prefix("Abort", "title")


@pytest.mark.parametrize("codec", CODECS)
def test_codecs_roundtrip_and_offsets(codec):
    integers = [0, 1, 7, 127, 128, 32000, 2**32 - 1]
    payload, bits = encode(integers, codec)
    assert list(decode(payload, bits, codec)) == integers
    docs = {0: {1: [(4, 0, 0, 2, 1), (4, 4, 11, 14, 0)]}, 9: {0: [(0, 0, 0, 3, 1)]}}
    assert list(gaps(docs)) == [1, 9]
    payload, bits = pack_postings(docs, codec)
    assert unpack_postings(payload, bits, codec) == docs
    with pytest.raises(ValueError):
        unpack_postings(payload[:-1], bits, codec)
    with pytest.raises(ValueError):
        list(gaps([0, 0]))


def test_ast_precedence_field_values_and_escape(settings):
    query = parse("alpha OR beta AND NOT gamma", "boolean", settings.search, ["css"])
    assert query.constraint.name == "OR"
    assert isinstance(query.constraint.right, Operator)
    assert query.constraint.right.name == "AND"
    assert query.constraint.right.right.name == "NOT"
    assert [token.kind for token in lex(r"\NOT \* querySel*", 8)] == ["word", "word", "prefix"]
    assert parse("unknown:word", "keyword", settings.search, []).scoring[0].value == "unknown:word"
    for text in ("source:pennylane", "topic:bad", "title:", 'title:"unfinished'):
        with pytest.raises(QueryError):
            parse(text, "keyword", settings.search, [])
    with pytest.raises(QueryError):
        parse("alpha OR (beta AND)", "boolean", settings.search, [])
    assert edit_distance("selector", "seletcor", 2) == 2


def test_dense_exact_respects_eligibility_and_best_passage():
    vectors = np.array([[1, 0], [.6, .8], [0, 1], [.6, .8], [-1, 0]], dtype=np.float32)
    parents = np.array([1, 0, 0, 3, 3], dtype=np.uint32)
    q = np.array([1, 0], dtype=np.float32)
    matches, visited = exact_parent_hits(vectors, parents, q, {0, 3}, .5, 2)
    assert [row[0] for row in matches] == [0, 3]
    assert matches[0][2][0][1] == 1
    assert matches[0][1] == pytest.approx(.6)
    assert visited == 4


def test_rrf_uses_eligible_one_based_ranks():
    rows = fuse({"a": [(0, 100, []), (1, 10, [])], "b": [(1, .5, []), (2, .4, [])]}, 60, {1, 2})
    assert rows[0][0] == 1
    assert rows[0][1] == pytest.approx(1 / 62 + 1 / 61)


def test_graph_dangling_mass_and_symmetry():
    rank, _, residual = pagerank({0: [1], 1: [0], 2: []}, .85, 1e-10, 100)
    assert sum(rank.values()) == pytest.approx(1)
    assert rank[0] == pytest.approx(rank[1])
    assert rank[0] > rank[2] and residual <= 1e-10


def test_pooled_metrics():
    metrics = scores(["a", "b"], {"a": 0, "b": 3, "c": 2}, 10)
    assert metrics["P@5"] == pytest.approx(.2)
    assert metrics["MRR@10"] == pytest.approx(.5)
    assert metrics["pooled Recall@10"] == pytest.approx(.5)


def test_taat_and_daat_ties_have_identical_order(service):
    for ranker in ("bm25", "tfidf"):
        first = service.search("fixturefolio CSS", mode="keyword", ranker=ranker)
        other = service.search("fixturefolio CSS", mode="keyword", ranker=ranker, strategy="daat")
        assert [(item["id"], item["score"]) for item in first["results"]] == [(item["id"], item["score"]) for item in other["results"]]
    with ExitStack() as stack:
        readers = [Index(service.release.path, stack, codec) for codec in CODECS]
        assert all(reader.posting("promise.all") == readers[0].posting("promise.all") for reader in readers)
