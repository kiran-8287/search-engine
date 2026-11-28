import json
from collections import Counter
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from techsearch import evaluation as ev
from techsearch.api import create_app
from techsearch.experiments import save_report
from techsearch.io import ROUTER_VERSION, digest, write_json


def test_frozen_study_selection_and_compatible_lab_report(settings, release):
    classes = settings.evaluation["classes"]
    groups = [{"id": f"{split}-{kind}-{i}", "split": split, "class": kind, "query": f"{kind} {i}"}
              for split in ("dev", "test") for kind in classes for i in range(5)]
    frozen = {"group_fingerprint": digest(groups), "groups": groups}
    write_json(ev.home(settings) / "frozen.json", frozen)
    selected = ev.stratified_groups(groups, classes)
    assert selected == ev.stratified_groups(groups, reversed(classes))
    assert len(selected) == 50 and all(g["split"] == "dev" for g in selected)
    assert sorted(Counter(g["class"] for g in selected).values()) == [4] * 10 + [5, 5]
    parent = {"release_id": release.id, "split": "dev", "router": ROUTER_VERSION,
              "lab_protocol": ev.LAB_PROTOCOL, "lab_settings": ev.lab_settings(settings),
              "methods": ev.LAB_DESIGNS, "protocol": frozen["group_fingerprint"]}
    rankings = [{"d%d" % i: None for i in range(offset, offset+15)} for offset in range(6)]
    parent["runs"] = [{**g, "methods": {m: {"status": "ok", "degraded": False, "ids": list(rankings[i])}
                                        for i, m in enumerate(ev.LAB_DESIGNS)}} for g in groups if g["split"] == "dev"]
    path = settings.path("artifacts") / "runs" / release.id / "lab-dev.json"
    write_json(path, parent)
    profile, rows = ev.groq_study(settings, release.id, save=True)
    assert len(ev.pool_for({**parent, "runs": rows}, settings, depth=10)) == 50 * 15
    original = {k: v for k, v in parent.items() if k != "runs"}
    save_report(settings, release, "lab-dev", {**original, "run_id": profile["source_run_id"], "query_count": 60, "paired_queries": 60})
    timing = {**original, "profile": ev.GROQ_PROFILE, "protocol": profile["protocol"],
              "source_run_id": profile["source_run_id"], "run_id": "mini-fixture", "query_count": 50, "paired_queries": 50}
    save_report(settings, release, ev.GROQ_RUN, timing)
    quality = {"profile": ev.GROQ_PROFILE, "protocol": profile["protocol"], "prompt_version": ev.GROQ_PROMPT,
               "measurement_run_id": "mini-fixture", "status": "partial", "labeled": 1, "pending": 749}
    save_report(settings, release, "evaluation-" + ev.GROQ_RUN, quality)
    with TestClient(create_app(settings)) as client:
        value = client.get("/api/v1/lab").json()
        assert value["measurement"]["query_count"] == 50 and value["full_development_timing"]
        assert value["quality"] == quality
        save_report(settings, release, "evaluation-" + ev.GROQ_RUN, {**quality, "protocol": parent["protocol"]})
        assert client.get("/api/v1/lab").json()["quality"] is None
        assert client.get("/api/v1/exports/reports/lab-dev").json()["report"]["query_count"] == 60

        service = SimpleNamespace(release=release, parents=[{"source": "mdn"}],
                                  stable_to_doc={f"d{i}": 0 for i in range(15)})
        review_path = ev.home(settings) / "annotations" / f"{release.id}-{ev.GROQ_PROFILE}-review.json"
        write_json(review_path, {"outcome": "rejected", "protocol": profile["protocol"],
                                 "prompt_version": ev.GROQ_PROMPT, "reviewed_by": "AI"})
        with pytest.raises(ValueError, match="pilot failed AI review"):
            ev.evaluate(settings, service, "dev", lab=True, profile=ev.GROQ_PROFILE, annotate=True, max_requests=1)
        ev.evaluate(settings, service, "dev", lab=True, profile=ev.GROQ_PROFILE)
        assert client.get("/api/v1/lab").json()["quality"]["pilot_review_status"] == "rejected"


def test_groq_top_ten_metrics_distinguish_missing_and_empty():
    run = {"runs": [{"id": "empty", "class": "no-match", "methods": {"bm25": {"status": "ok", "ids": []}}},
                    {"id": "known", "class": "phrase", "methods": {"bm25": {"status": "ok", "ids": ["a"]}}}]}
    with pytest.raises(ValueError, match="unjudged"):
        ev.metrics(run, {}, None)
    measured = ev.metrics(run, {"known": {"a": 2}}, None)
    assert measured["sample_counts"]["bm25"] == 2
    assert measured["aggregates"]["bm25"] == {"P@10": .05, "MRR@10": .5, "nDCG@10": .5}
    assert measured["per_group"]["empty"]["bm25"] == {"P@10": 0, "MRR@10": 0, "nDCG@10": 0}


def test_groq_quota_stop_and_persistent_ceiling(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "fake-fixture")
    monkeypatch.setenv("TECHSEARCH_GROQ_FREE", "1")
    monkeypatch.setattr(ev, "check_groq_model", lambda key: {"accessible": True})
    monkeypatch.setattr(ev.time, "sleep", lambda seconds: None)
    path = tmp_path / "budget.json"
    calls = []

    def post(url, **kwargs):
        assert url == ev.GROQ_ENDPOINT and not kwargs["allow_redirects"]
        body = kwargs["json"]
        assert body["model"] == ev.GROQ_MODEL and body["include_reasoning"] is False
        assert body["response_format"]["json_schema"]["strict"] and body["max_completion_tokens"] == 512
        calls.append(body)
        if len(calls) == 2:
            return SimpleNamespace(status_code=429, headers={"x-ratelimit-remaining-requests": "0", "Retry-After": "3600"})
        payload = {"model": ev.GROQ_MODEL, "usage": {"prompt_tokens": 200, "completion_tokens": 80},
                   "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                       "pair_id": "pair", "grade": 2, "rationale": "The excerpt describes the requested method."})}}]}
        return SimpleNamespace(status_code=200, headers={}, ok=True, is_redirect=False, json=lambda: payload)

    monkeypatch.setattr(ev.requests, "post", post)
    config = {"endpoint": ev.GROQ_ENDPOINT, "model": ev.GROQ_MODEL, "prompt_version": ev.GROQ_PROMPT}
    budget = ev.GroqBudget(path, pilot=True)
    provider = ev.AnnotationProvider(config, 75, budget=budget)
    assert provider.label({"pair_id": "pair"}, "primary")["grade"] == 2
    with pytest.raises(RuntimeError, match="quota stop"):
        provider.label({"pair_id": "pair"}, "audit")
    resumed = ev.GroqBudget(path, pilot=True)
    assert resumed.record["pilot_attempts"] == 2 and resumed.record["prompt_tokens"] == 200
    resumed.record.update(total=74, pilot_attempts=74)
    resumed.reserve("adjudicate", False)
    with pytest.raises(ev.AnnotationBudgetExhausted):
        ev.GroqBudget(path, pilot=True).reserve("primary", True)
    resumed.record["total"] = 3999
    resumed.pilot = False
    resumed.reserve("primary", True)
    with pytest.raises(ev.AnnotationBudgetExhausted):
        ev.GroqBudget(path).reserve("primary", False)
    assert len(calls) == 2


def test_groq_legacy_key_requires_exact_provider_and_model(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    legacy = "gsk_" + "fixture" * 4
    monkeypatch.setenv("TECHSEARCH_ANNOTATION_API_KEY", legacy)
    annotation = {"endpoint": ev.GROQ_ENDPOINT, "model": ev.GROQ_MODEL}
    assert ev.groq_key(annotation) == legacy
    assert ev.groq_key({**annotation, "model": "unrelated"}) is None
    assert ev.groq_key({**annotation, "endpoint": "https://example.invalid/"}) is None
    monkeypatch.setenv("GROQ_API_KEY", "explicit-fixture")
    assert ev.groq_key(annotation) == "explicit-fixture"


def test_groq_waits_for_token_headroom_and_stops_at_zero_requests(monkeypatch, tmp_path):
    clock = [100.0]
    monkeypatch.setattr(ev.time, "monotonic", lambda: clock[0])
    budget = ev.GroqBudget(tmp_path / "budget.json", pilot=True)
    messages = [{"role": "user", "content": "example"}]
    budget.observe({"x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "100"})
    assert budget.quota_delay(messages) > 3
    clock[0] += 5
    assert budget.quota_delay(messages) == 0
    budget.observe({"x-ratelimit-remaining-requests": "0"})
    with pytest.raises(ev.AnnotationBudgetExhausted, match="quota stop"):
        budget.quota_delay(messages)
    assert budget.record["total"] == 0
