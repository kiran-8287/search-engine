import os
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from techsearch.api import create_app
from techsearch.corpus import alias_key, url
from techsearch.feedback import Runtime, SnapshotMissing, search_id
from techsearch.io import atomic_file, read_jsonl
from techsearch.pipeline import ReleaseUnavailable, open_release, preprocess
from techsearch.repository import Documents

PROMISE = "mdn:web/javascript/fixture-promise/index.md"
SELECTOR = "mdn:web/api/fixture-selector/index.md"


def ids(result):
    return [hit["id"] for hit in result["results"]]


def test_release_lookup_links_and_schema(settings, release):
    assert preprocess(settings)["id"] == release.info["corpus"]["id"]
    coverage = release.info["corpus"]["coverage"]
    assert coverage["quarantined"] == 2
    assert coverage["unresolved_macros"] == {"FixtureMacro": 1}
    repo = Documents(release.path)
    with repo.reader() as get:
        record = get(repo.stable_to_doc[PROMISE])
    assert record["segments"][-1]["text"].startswith("  const result")
    assert record["references"][0]["url"].endswith("#examples")
    aliases = {alias["key"]: alias["doc"] for alias in read_jsonl(release.path / "aliases.jsonl")}
    assert aliases[alias_key("https://stackoverflow.com/a/99002#ignored")] == repo.stable_to_doc["so:99001"]
    assert aliases[alias_key("https://developer.mozilla.org/en-US/docs/Web/JavaScript/OldFixture")] == repo.stable_to_doc[PROMISE]
    assert url("http://example.com/Is/Case/?a=x#Help") == "http://example.com/Is/Case/?a=x#Help"
    assert open_release(settings, deep=True).id == release.id


def test_release_rejects_same_size_payload_tamper(settings, release):
    path = release.path / "postings-vb.bin"
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    with pytest.raises(ReleaseUnavailable):
        open_release(settings, verify=True)


def test_atomic_failure_keeps_existing_file(tmp_path):
    path = tmp_path / "committed.bin"
    path.write_bytes(b"intact")
    with pytest.raises(RuntimeError), atomic_file(path) as out:
        out.write(b"incomplete")
        raise RuntimeError("intentional")
    assert path.read_bytes() == b"intact"
    assert sorted(tmp_path.iterdir()) == [path]


def test_search_modes_and_constraints(service):
    assert ids(service.search("source:mdn AND title:Promise.all", mode="boolean")) == [PROMISE]
    assert ids(service.search('"query selector"', mode="phrase", source="mdn")) == [SELECTOR]
    assert not ids(service.search('"cross boundary"', mode="phrase"))
    assert not ids(service.search('"fixture legacy"', mode="phrase"))
    assert PROMISE in ids(service.search("querySel*", mode="prefix"))
    assert ids(service.search("promsie.all", mode="fuzzy"))[0] == PROMISE
    assert ids(service.search("code:===", mode="field")) == [PROMISE]
    assert ids(service.search("answer:persistent", mode="field")) == ["so:99001"]
    assert ids(service.search("source:mdn", mode="field")) == sorted(ids(service.search("source:mdn", mode="field")))
    assert not ids(service.search("zqqpzkx", mode="keyword"))
    lexical = service.search("concurrent tasks")
    assert lexical["warnings"] and lexical["trace"]["fallback"]


def test_session_feedback_and_expiry(service):
    a, b = search_id(), search_id()
    query = "concurrent"
    result = service.search(query, source="mdn", session=a)
    assert PROMISE in ids(result)
    with pytest.raises(SnapshotMissing):
        service.runtime.get(b, result["search_id"])
    with pytest.raises(ValueError):
        service.runtime.judge(a, result["search_id"], "so:99001", 1)
    service.runtime.judge(a, result["search_id"], PROMISE, 1)
    result2 = service.search(query, source="mdn", apply_feedback=True, session=a)
    assert result2["trace"]["reranking"][0]["judgments"] == 1
    assert result2["results"][0]["source"] == "mdn"
    assert [hit["score"] for hit in result2["results"]] != [hit["score"] for hit in result["results"]]
    persisted = Runtime(service.settings.path("runtime"))
    assert persisted.get(a, result["search_id"])["results"] == result["results"]
    snapshot = persisted.session_path(a) / f'{result["search_id"]}.json'
    os.utime(snapshot, (0, 0))
    with pytest.raises(SnapshotMissing):
        persisted.get(a, result["search_id"])


def test_api_pagination_validation_and_export(settings, release):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/readiness").json()["release_id"] == release.id
        assert client.post("/api/v1/search", json={"query": "x", "bogus": True}).status_code == 422
        assert client.post("/api/v1/search", json={"query": "word", "mode": "semantic"}).status_code == 503
        found = client.post("/api/v1/search", json={"query": "fixturefolio", "mode": "keyword", "page_size": 4}).json()
        pages = client.get(f'/api/v1/search/{found["search_id"]}', params={"page": 2, "size": 4}).json()
        assert pages["search_id"] == found["search_id"] and found["total"] == pages["total"] == 12
        assert not (set(ids(found)) & set(ids(pages)))
        doc = client.get("/api/v1/documents/" + quote(PROMISE, safe="")).json()
        assert "<img src=x onerror=" in doc["segments"][-1]["text"]
        payload = {"search_id": found["search_id"], "document": found["results"][0]["id"], "value": 1}
        assert client.post("/api/v1/feedback", json=payload).status_code == 204
        assert client.get("/api/v1/exports/search/" + found["search_id"]).headers["content-disposition"].startswith("attachment")
        assert client.get("/api/v1/reports/taat-daat").json()["status"] == "not-run"
    with TestClient(create_app(settings)) as private_client:
        assert private_client.get("/api/v1/search/" + found["search_id"]).status_code == 404
