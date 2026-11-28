import json
from types import SimpleNamespace

import pytest

from techsearch import evaluation
from techsearch.io import read_json, write_json


@pytest.fixture
def mock_judge(service, monkeypatch):
    settings = service.settings
    config = settings.evaluation["annotation"]
    config.update(model="test-judge", audit_fraction=1)
    monkeypatch.setenv("TECHSEARCH_ANNOTATION_API_KEY", "fixture-key")
    monkeypatch.setattr(evaluation.time, "sleep", lambda _: None)
    group = {"id": "sample", "class": "exact-api", "query": "Promise.all"}
    document = next(iter(service.stable_to_doc))
    run = {"split": "dev", "protocol": "fixture", "runs": [
        {**group, "methods": {"bm25": {"status": "ok", "ids": [document]}}}
    ]}
    write_json(settings.path("artifacts") / "runs" / service.release.id / "benchmark-dev.json", run)
    calls = []

    def respond(grade, pair_id=None):
        def post(*_args, **options):
            content = json.loads(options["json"]["messages"][1]["content"])
            assert {"pair_id", "query", "query_type", "title", "source_type", "topic", "tags", "excerpts"} == set(content)
            calls.append(options["json"]["messages"][0]["content"])
            payload = {"model": "test-judge", "choices": [{"message": {"content": json.dumps({
                "pair_id": content["pair_id"] if pair_id is None else pair_id,
                "grade": grade, "rationale": "The excerpt shows the API and explains the behavior.",
            })}}]}
            return SimpleNamespace(status_code=200, ok=True, is_redirect=False, json=lambda: payload)

        monkeypatch.setattr(evaluation.requests, "post", post)

    return group, document, calls, respond


def test_request_budget_counts_invalid_responses_and_retries(service, mock_judge):
    group, document, calls, respond = mock_judge
    respond(3, pair_id="a different pair")
    provider = evaluation.AnnotationProvider(service.settings.evaluation["annotation"], max_requests=2)
    with pytest.raises(evaluation.AnnotationBudgetExhausted):
        provider.label(evaluation.evidence_for(service, group, document), "primary")
    assert len(calls) == 2
    assert provider.usage() == {"max_requests": 2, "total": 2, "primary": 2, "audit": 0,
                                "adjudicate": 0, "retries": 1, "invalid_responses": 2}


def test_budget_stop_resumes_audit_and_adjudication_without_repeating_calls(service, mock_judge):
    group, document, calls, respond = mock_judge
    settings = service.settings

    def evaluate():
        return evaluation.evaluate(settings, service, "dev", annotate=True, limit=50, max_requests=1)

    respond(3)
    first = evaluate()
    assert first["status"] == "partial" and first["pending"] == 1 and first["labeled"] == 0
    assert first["provider_requests"]["primary"] == 1
    key = evaluation.annotation_key(service.release.id, "fixture", settings.evaluation["annotation"], group, document)
    path = evaluation.home(settings) / "annotations" / key[:2] / (key + ".json")
    assert [attempt["grade"] for attempt in read_json(path)["attempts"]] == [3]

    respond(1)
    second = evaluate()
    assert second["provider_requests"]["audit"] == 1
    assert second["provider_requests"]["primary"] == 0 and second["pending"] == 1
    assert [attempt["grade"] for attempt in read_json(path)["attempts"]] == [3, 1]

    respond(2)
    result = evaluate()["report"]
    assert result["provider_requests"]["adjudicate"] == 1
    assert result["provider_requests"]["total"] == 1 and result["pending"] == 0
    assert result["fully_judged_queries"] == 1 and result["reported_models"] == ["test-judge"]
    assert result["aggregates"]["bm25"]["P@10"] == .1
    assert read_json(path)["grade"] == 2

    result = evaluation.evaluate(settings, service, "dev")["report"]
    assert result["provider_requests"]["total"] == 0 and sum(result["sample_counts"].values()) == 1
    assert len(calls) == 3


def test_insufficient_evidence_stays_pending_without_spending_again(service, mock_judge):
    _, _, calls, respond = mock_judge
    respond(None)
    for _ in range(2):
        result = evaluation.evaluate(service.settings, service, "dev", annotate=True, max_requests=3)
        assert result["labeled"] == 0 and result["pending"] == result["unresolved"] == 1
        assert "aggregates" not in result
    assert result["provider_requests"]["total"] == 0 and len(calls) == 1
