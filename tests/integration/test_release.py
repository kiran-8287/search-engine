import os
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from techsearch.api import create_app
from techsearch.corpus import alias_key, url
from techsearch.feedback import Runtime, SnapshotMissing, search_id
from techsearch.io import atomic_file, read_jsonl
from techsearch.pipeline import ReleaseUnavailable, open_release, preprocess, validate_postings
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


def test_interrupted_staging_handles_transient_nfs_cleanup(tmp_path, monkeypatch):
    import errno
    import tempfile

    from techsearch.pipeline import staging

    original = tempfile.TemporaryDirectory.cleanup
    attempts = []

    def busy_once(directory):
        attempts.append(directory.name)
        if len(attempts) == 1:
            raise OSError(errno.ENOTEMPTY, "transient NFS deletion")
        return original(directory)

    monkeypatch.setattr(tempfile.TemporaryDirectory, "cleanup", busy_once)
    with pytest.raises(KeyboardInterrupt), staging(tmp_path) as folder:
        (folder / "incomplete.bin").write_bytes(b"partial")
        raise KeyboardInterrupt
    assert len(attempts) == 2 and not list(tmp_path.iterdir())


def test_missing_release_keeps_ui_alive_and_returns_actionable_error(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/lab").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
        readiness = client.get("/api/v1/readiness")
        assert readiness.status_code == 503 and "No active release" in readiness.json()["detail"]
        assert client.post("/api/v1/search", json={"query": "CSS"}).status_code == 503


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


def test_deep_validation_checks_forward_against_source(release):
    from techsearch.indexing import STATS

    path = release.path / "forward-stats.bin"
    data = bytearray(path.read_bytes())
    row = list(STATS.unpack_from(data))
    row[0] += 1
    STATS.pack_into(data, 0, *row)
    path.write_bytes(data)
    with pytest.raises(ReleaseUnavailable, match="Forward statistics"):
        validate_postings(release.path)


def test_deep_validation_checks_postings_against_source(release):
    from techsearch.repository import write_indexed_jsonl

    docs = list(Documents(release.path))
    docs[0]["segments"][-1]["text"] += " uniquevalidationtoken"
    write_indexed_jsonl(release.path / "documents.jsonl", release.path / "documents.offsets", docs)
    with pytest.raises(ReleaseUnavailable, match="Forward terms"):
        validate_postings(release.path)


def test_deep_validation_rejects_identical_bad_offsets_in_all_codecs(release):
    from contextlib import ExitStack

    from techsearch.compression import CODECS, pack_postings
    from techsearch.indexing import Index
    from techsearch.io import dumps

    for codec in CODECS:
        with ExitStack() as stack:
            index = Index(release.path, stack, codec)
            rows = [(term, *index.posting(term)) for term in index.files.sorted_terms]
        term, _df, _cf, postings = rows[0]
        positions = next(iter(next(iter(postings.values())).values()))
        segment, position, start, end, original = positions[0]
        positions[0] = (segment, position, start + 1, end + 1, original)
        with (release.path / f"postings-{codec}.bin").open("wb") as payload, (
                release.path / f"lexicon-{codec}.jsonl").open("w", encoding="utf-8") as lexicon:
            for term, df, cf, postings in rows:
                blob, bits = pack_postings(postings, codec)
                lexicon.write(dumps([term, df, cf, payload.tell(), len(blob), bits]) + "\n")
                payload.write(blob)
    with pytest.raises(ReleaseUnavailable, match="Postings disagree with canonical positions"):
        validate_postings(release.path)


def test_retrieval_experiment_keeps_qrels_separate(service):
    import math

    from techsearch.experiments import retrieval_report

    report = retrieval_report(service, ["concurrent tasks"])
    methods = report["rows"][0]["methods"]
    assert methods["rocchio_probe"]["probe_document"] == methods["bm25"]["hits"][0]["id"]
    assert methods["rocchio_probe"]["expansion"]
    assert all(math.isfinite(hit["score"]) for method in methods.values() for hit in method["hits"])
    assert not (service.settings.path("data") / "evaluation").exists()


def test_unjudged_evaluation_is_saved_and_shown_as_blocked(service):
    from techsearch.evaluation import evaluate
    from techsearch.io import write_json

    run = {"split": "dev", "protocol": "fixture-protocol", "runs": [
        {"id": "fixture-group", "query": "Promise.all", "class": "exact-api", "methods": {
            "bm25": {"status": "ok", "ids": [PROMISE]}}}]}
    path = service.settings.path("artifacts") / "runs" / service.release.id / "benchmark-dev.json"
    write_json(path, run)
    result = evaluate(service.settings, service, "dev")
    assert result["status"] == "blocked" and result["pending"] == 1 and result["labeled"] == 0
    with TestClient(create_app(service.settings)) as client:
        report = client.get("/api/v1/reports/evaluation-dev").json()
        assert report["status"] == "blocked"
        assert "aggregates" not in report["report"]


def test_ablation_export_preserves_actual_baseline_observations(service):
    from techsearch.evaluation import benchmark
    from techsearch.io import read_json, write_json

    write_json(service.settings.path("data") / "evaluation/frozen.json", {
        "group_fingerprint": "fixture-protocol", "groups": [
            {"split": "dev", "id": "fixture-group", "query": "concurrent tasks", "class": "natural-language"}]})
    benchmark(service.settings, service, "dev", ablations=True)
    directory = service.settings.path("artifacts") / "runs" / service.release.id
    full, baseline = [read_json(directory / name) for name in ("ablations-dev.json", "benchmark-dev.json")]
    assert len(full["methods"]) == 8 and len(baseline["methods"]) == 4
    assert baseline["measurement_source_run_id"]
    for method in baseline["methods"]:
        assert baseline["runs"][0]["methods"][method] == full["runs"][0]["methods"][method]
        assert baseline["timing_ms"].get(method) == full["timing_ms"].get(method)


def test_demo_bundle_keeps_saved_reports_and_portable_paths(settings, release, tmp_path):
    import shutil
    from pathlib import Path
    from zipfile import ZipFile

    import yaml

    from techsearch.experiments import save_report
    from techsearch.packaging import package_demo

    root = Path(__file__).resolve().parents[2]
    for filename in (".env.example", ".gitignore", "README.md", "pyproject.toml", "collect_mdn.py", "collect_stackoverflow.py"):
        shutil.copy2(root / filename, settings.root / filename)
    save_report(settings, release, "retrieval", {"rows": []})
    bundle = package_demo(settings, release, tmp_path / "demo.zip")
    with ZipFile(bundle["bundle"]) as archive:
        assert f"artifacts/reports/{release.id}/retrieval.json" in archive.namelist()
        assert ".env" not in archive.namelist()
        paths = yaml.safe_load(archive.read("config/default.yaml"))["paths"]
        assert paths == {"data": "data", "artifacts": "artifacts", "runtime": "data/runtime", "frontend": "frontend"}
