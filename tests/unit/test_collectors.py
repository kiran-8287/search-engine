from __future__ import annotations

import json
import zipfile

import pytest
import requests

import collect_mdn as mdn
import collect_stackoverflow as so


def test_mdn_scoped_extraction_supports_long_paths(tmp_path):
    archive = tmp_path / "fixture.zip"
    long_path = "content-archive/files/en-us/web/api/" + "/".join(["long-" + "x" * 45] * 6) + "/index.md"
    outside_scope = "content-archive/files/en-us/games/fixture/index.md"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(long_path, "in scope")
        output.writestr(outside_scope, "outside scope")
        output.writestr("content-archive/files/en-us/_redirects.txt", "/source /target\n")
    destination = tmp_path / "content"
    mdn.safe_extract_zip(archive, destination, scoped=True)
    destination = mdn.archive_filesystem_path(destination)
    assert (destination / long_path).read_text() == "in scope"
    assert not (destination / outside_scope).exists()
    assert (destination / "content-archive/files/en-us/_redirects.txt").is_file()


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


def test_so_api_throttle_error_retries_with_server_delay(api_state, monkeypatch):
    class Throttled(Reply):
        ok = False
        status_code = 400
        headers = {"Retry-After": "12"}

    replies = iter([Throttled(error_id=502, error_message="paused"), Reply(items=[], quota_remaining=500)])
    waits = []
    monkeypatch.setattr(so.session, "get", lambda *_args, **_options: next(replies))
    monkeypatch.setattr(so.time, "sleep", waits.append)
    assert so.api_get("questions").success
    assert waits == [12]


def test_so_supplement_batches_collect_each_questions_top_votes(api_state, monkeypatch):
    documents = {"1": {"question_id": 1, "answer_count": 4}, "2": {"question_id": 2, "answer_count": 2}}
    assert list(so.supplement_batches(documents, ["1", "2"])) == [["1", "2"]]
    pages = [
        [{"question_id": 1, "answer_id": 11, "score": 9}, {"question_id": 1, "answer_id": 12, "score": 8},
         {"question_id": 2, "answer_id": 21, "score": 7}],
        [{"question_id": 1, "answer_id": 13, "score": 6}, {"question_id": 1, "answer_id": 14, "score": 5},
         {"question_id": 2, "answer_id": 22, "score": 4}],
    ]
    calls = []

    def fetch(endpoint, params, *, page):
        calls.append((endpoint, page))
        assert params["sort"] == "votes" and params["order"] == "desc"
        return so.ApiResult(True, pages[page - 1], page, params["pagesize"], page == 1)

    monkeypatch.setattr(so, "api_get", fetch)
    monkeypatch.setattr(so.time, "sleep", lambda _seconds: None)
    completed, count, error = so.lookup_supplement_batch(documents, ["1", "2"])
    assert (completed, count, error) == ({"1", "2"}, 5, None)
    assert calls == [("questions/1;2/answers", 1), ("questions/1;2/answers", 2)]
    assert [answer["answer_id"] for answer in documents["1"]["answers"]] == [11, 12, 13]
    assert [answer["answer_id"] for answer in documents["2"]["answers"]] == [21, 22]


def test_so_question_scope_uses_extracted_text(settings, monkeypatch):
    monkeypatch.setattr(so, "SCOPE", settings.scope)
    raw = {"question_id": 55, "title": "Service migration", "tags": ["http"],
           "body": '<p>See <a href="https://example.invalid/browser">the migration</a>.</p>'}
    assert so.eligible_question(raw)
    assert so.scoped_question_document(raw, "http") is None
    raw["body"] = "<p>The browser sends a preflight request.</p>"
    assert so.scoped_question_document(raw, "http")["question_id"] == 55


def test_so_supplement_keeps_completed_questions_when_quota_stops_batch(api_state, monkeypatch, tmp_path):
    monkeypatch.setattr(so, "CHECKPOINT_FILE", tmp_path / "checkpoint.json")
    state = so.load_checkpoint()
    state["documents"] = {"1": {"question_id": 1, "answer_count": 4}, "2": {"question_id": 2, "answer_count": 2}}

    def fetch(_endpoint, params, *, page):
        monkeypatch.setattr(so, "STOP_COLLECTION", True)
        items = [{"question_id": 1, "answer_id": aid} for aid in (11, 12, 13)]
        items.append({"question_id": 2, "answer_id": 21})
        return so.ApiResult(True, items, page, params["pagesize"], True, quota_remaining=2)

    monkeypatch.setattr(so, "api_get", fetch)
    so.collect_additional_answers(state)
    saved = so.load_checkpoint()
    assert saved["supplement_question_ids_done"] == ["1"]
    assert saved["documents"]["2"]["answer_collection"]["additional_answers_status"] == "pending"
    assert saved["documents"]["2"]["answers"][0]["answer_id"] == 21


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
