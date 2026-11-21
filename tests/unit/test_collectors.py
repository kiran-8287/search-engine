from __future__ import annotations

import json

import pytest
import requests

import collect_mdn as mdn
import collect_stackoverflow as so


def test_mdn_macro_and_code_preservation(tmp_path):
    path = tmp_path / "web/js/index.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\ntitle: Promise fixture\nslug: Web/JavaScript/PromiseFixture\nstatus: [experimental]\n---\n"
        'Use {{jsxref("Promise.all", "combine promises")}} and {{Unlisted("fixture label")}}.\n'
        "\n" + "\x60" * 3 + "js\n  const node = '<div>';\n" + "\x60" * 3 + "\n",
        encoding="utf-8",
    )
    result = mdn.parse_document(path, tmp_path)
    assert result["url"].endswith("/Web/JavaScript/PromiseFixture")
    assert "combine promises" in result["content"]
    assert "fixture label" in result["content"]
    assert result["code_blocks"][0]["code"] == "  const node = '<div>';\n"
    assert any("Promise/all" in item["url"] for item in result["link_references"])
    assert result["unresolved_macros"][0]["macro_name"] == "Unlisted"


def test_so_checkpoint_keeps_previous_data_on_failed_replace(monkeypatch, tmp_path):
    path = tmp_path / "stackoverflow_checkpoint.json"
    monkeypatch.setattr(so, "CHECKPOINT_FILE", path)
    state = so.load_checkpoint()
    state["documents"] = {"25": {"question_id": 25}}
    state["supplement_question_ids_done"] = ["25"]
    so.save_checkpoint(state)
    assert so.load_checkpoint()["supplement_question_ids_done"] == ["25"]
    previous = path.read_bytes()
    old_replace = type(path).replace

    def blocked(file, target):
        if target == path:
            raise OSError("fixture disk fault")
        return old_replace(file, target)

    monkeypatch.setattr(type(path), "replace", blocked)
    state["tag_pages"]["javascript"] = 5
    with pytest.raises(OSError):
        so.save_checkpoint(state)
    assert path.read_bytes() == previous
    assert "javascript" not in so.load_checkpoint()["tag_pages"]


@pytest.fixture
def api_state(monkeypatch):
    monkeypatch.setattr(so, "STOP_COLLECTION", False)
    monkeypatch.setattr(so, "REMAINING_QUOTA", None)
    monkeypatch.setattr(so, "API_REQUESTS", 0)
    monkeypatch.setattr(so, "ENDPOINT_BACKOFF", {})
    monkeypatch.setattr(so, "API_KEY", None)


class Reply:
    ok = True
    status_code = 200
    headers = {}

    def __init__(self, **values):
        self.values = values

    def json(self):
        return self.values


def test_so_low_quota_preserves_successful_page(api_state, monkeypatch):
    monkeypatch.setattr(so.session, "get", lambda *_args, **_options: Reply(items=[{"question_id": 25}],
                                                                         quota_remaining=3, has_more=True))
    answer = so.api_get("questions", {"tagged": "javascript"})
    assert answer.success and answer.has_more and answer.items == [{"question_id": 25}]
    assert not so.api_get("questions", {"tagged": "css"}).success
    assert so.API_REQUESTS == 1


def test_so_backoff_applies_to_answer_family(api_state, monkeypatch):
    waits = []
    replies = iter([Reply(items=[], backoff=4, quota_remaining=99), Reply(items=[], quota_remaining=98)])
    monkeypatch.setattr(so.session, "get", lambda *_args, **_options: next(replies))
    monkeypatch.setattr(so.time, "monotonic", lambda: 50)
    monkeypatch.setattr(so.time, "sleep", waits.append)
    assert so.api_get("questions/1/answers").success
    assert waits == []
    assert so.api_get("questions/2/answers").success
    assert waits == [4]


def test_so_timeout_pauses_after_finite_retries(api_state, monkeypatch):
    def fail(*_args, **_kwargs):
        raise requests.Timeout("dummy credential must stay out of diagnostics")

    monkeypatch.setattr(so.session, "get", fail)
    monkeypatch.setattr(so.time, "sleep", lambda _seconds: None)
    value = so.api_get("questions")
    assert not value.success and so.STOP_COLLECTION
    assert so.API_REQUESTS == so.MAX_REQUEST_RETRIES + 1
    assert "dummy credential" not in value.error


def test_stackoverflow_code_and_legacy_answer_provenance():
    question = so.build_question_document({"question_id": 25, "title": "Fixture",
                                          "body": '<p>Some prose</p><pre><code>  &lt;img&gt; \n</code></pre>',
                                          "owner": {"user_id": 42}, "tags": ["html"], "content_license": "CC BY-SA 4.0"}, "html")
    assert question["segments"][1]["text"] == "  <img> \n"
    assert question["question_owner_id"] == 42
    assert question["content_license"] == "CC BY-SA 4.0"
