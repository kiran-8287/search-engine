import json
from types import SimpleNamespace

import pytest

from techsearch import evaluation as ev, judging
from techsearch.io import read_json, write_json


def intent_rows(settings, *queries):
    path = settings.root / "config/groq-dev50-intents.json"
    notes = read_json(path)
    write_json(path, {query: notes[query] for query in queries})
    return judging.interpretations(settings, [{"id": str(i), "query": q} for i, q in enumerate(queries)])


def segment(ordinal, text, *, kind="paragraph", answer=None):
    return {"ordinal": ordinal, "segment_id": f"source-{ordinal}", "heading_path": [],
            "answer_id": answer, "type": kind, "field": "code" if kind == "code" else
            ("answer" if answer else "question"), "text": text}


def page(title, rows):
    return {"title": title, "source": "stackoverflow", "topic": "javascript",
            "tags": ["javascript"], "segments": rows}


def test_diagnostic_flatmap_answer_keeps_code_and_explanation(settings):
    intent = intent_rows(settings, "Array.prototype.flatMap")["0"]
    # Relevant sections from Stack Overflow 24806772, answer 55260552.
    document = page("How to skip over an element in .map()?", [
        segment(1, "How can I skip an array element in .map?"),
        segment(2, "An unrelated answer. " * 600, answer=2),
        segment(17, "Since 2019, Array.prototype.flatMap is a good option.", answer=55260552),
        segment(18, "images.flatMap(({src}) => src.endsWith('.json') ? [] : src);\n", kind="code", answer=55260552),
        segment(19, "From MDN:", answer=55260552),
        segment(20, "flatMap can be used as a way to add and remove items (modify the number of items) during a map.",
                answer=55260552),
    ])
    original = ev.evidence_for(SimpleNamespace(document=lambda _: document),
                               {"query": intent["original_query"], "class": "exact-api", "id": "q"}, "d")
    # The production case has other overlapping sections that displaced the code.
    assert original["query"] == intent["original_query"]
    base, expanded = judging.contextual_evidence(document, intent, "pair")
    sections = {row["id"]: row for row in base["sections"]}
    assert sections["s18"]["text"].startswith("images.flatMap")
    assert "add and remove items" in sections["s20"]["text"]
    assert {sections[s]["answer_id"] for s in ("s17", "s18", "s19", "s20")} == {55260552}
    assert sections["s1"]["section"] == "question" and sections["s18"]["section"] == "answer"
    assert base["query"]["original_query"] == "Array.prototype.flatMap"
    assert base["document"]["title"] == document["title"]
    assert {row["id"] for row in base["sections"]} <= {row["id"] for row in expanded["sections"]}


def test_v2_preserves_constraints_without_benchmark_classes(settings):
    queries = ('html AND (dialog OR popover)', 'css AND grid AND NOT flex', '"storage event"',
               "title:Promise.all", "tag:javascript arrays", "code:=== equality", "source:mdn SVG use href",
               "vulnexo spacer div", "ordering of geological rock layers", "void zero result")
    notes = intent_rows(settings, *queries)
    assert notes["0"]["constraints"]["name"] == "AND"
    assert notes["0"]["constraints"]["right"]["name"] == "OR"
    assert notes["1"]["constraints"]["right"] == {"name": "NOT", "left": {
        "kind": "word", "value": "flex", "field": None}, "right": None}
    assert notes["2"]["constraints"] == {"kind": "phrase", "value": "storage event", "field": None}
    for i, kind, value, field in ((3, "word", "Promise.all", "title"), (4, "meta", "javascript", "tag"),
                                  (5, "word", "===", "code"), (6, "meta", "mdn", "source")):
        assert notes[str(i)]["constraints"] == {"kind": kind, "value": value, "field": field}
    assert "unclear" in notes["7"]["information_need"]
    assert notes["9"]["target"] == "void 0"
    document = page("Which HTML elements can't contain child nodes?", [
        segment(1, "Which elements cannot contain children?"),
        segment(2, "The HTML spec lists void elements that cannot have child content.", answer=4898444),
    ])
    for i in ("7", "8", "9"):
        base, extra = judging.contextual_evidence(document, notes[i], "opaque")
        assert base == extra and base["omitted_segments"] == 0
        assert base["query"]["original_query"] != base["document"]["title"]
        message = judging.user_message(base)
        assert not any(marker in message for marker in ("out-of-domain", "no-match", "query_type", "expected_grade"))


def test_context_expansion_stays_within_budget_and_preserves_whole_code_lines(settings):
    intent = intent_rows(settings, "document.querySelector")["0"]
    code = "const unrelated = 'text';\n" * 130
    code += "const target = document.querySelector('main');\n" + "console.log(target);\n" * 130
    document = page("A long answer", [segment(1, "Source question."),
                    segment(2, code, kind="code", answer=5),
                    segment(3, "The document.querySelector call selects the first matching element.", answer=5)])
    base, extra = judging.contextual_evidence(document, intent, "opaque")
    code_excerpt = next(x for x in base["sections"] if x["id"] == "s2")
    point = code_excerpt["clipping"]
    assert point["before"] and point["after"]
    assert code[point["start"] - 1] == "\n" and code[point["end"] - 1] == "\n"
    assert code[point["start"]:point["end"]] == code_excerpt["text"] and "document.querySelector" in code_excerpt["text"]
    for level, evidence in (("base", base), ("expanded", extra)):
        assert judging.input_bound(judging.PROMPTS["adjudicate"], judging.user_message(evidence)) <= judging.POLICY[
            f"{level}_input_tokens"]


def test_copying_answer_keeps_context_separate_from_offline_query(settings):
    query = "Ship a site that can function without a connection"
    intent = intent_rows(settings, query)["0"]
    # Diagnostic Stack Overflow post 541140 and the three parts of answer 541164.
    document = page("Entire website hijacked! How to prevent from being hijacked?", [
        segment(1, "Technically, how do you prevent your website from being mirrored on another domain?"),
        segment(2, "Any website can be duplicated. The browser downloads the content, and it could be pulled from browser cache.",
                answer=541164),
        segment(3, "The best course of action is to approach the ISP hosting the copy.", answer=541164),
        segment(4, "In terms of Google ranking the page higher, that's down to their algorithms.", answer=541164),
    ])
    evidence, expanded = judging.contextual_evidence(document, intent, "opaque")
    assert evidence == expanded and evidence["omitted_segments"] == 0
    assert evidence["query"]["original_query"] == query
    assert evidence["document"]["title"] == document["title"]
    assert [row["section"] for row in evidence["sections"]] == ["question", "answer", "answer", "answer"]
    assert all(row["answer_id"] == 541164 for row in evidence["sections"][1:])
    assert "ISP hosting the copy" in evidence["sections"][2]["text"]


def test_v2_attempt_accounting_retries_citations_and_abstentions(monkeypatch, tmp_path):
    path = tmp_path / "budget.json"
    write_json(path, {"total": 69, "pilot_attempts": 69, "primary": 60, "audit": 8,
                      "adjudicate": 1, "retries": 11})
    budget = ev.GroqBudget(path, pilot=True, judge_version="v2")
    with pytest.raises(ValueError, match="authorization"):
        budget.authorize_v2_pilot("sealed")
    with pytest.raises(ev.AnnotationBudgetExhausted):
        budget.reserve("primary", False)
    assert read_json(path)["total"] == 69
    budget.authorize_v2_pilot("sealed", 75)

    monkeypatch.setenv("GROQ_API_KEY", "fixture-only")
    monkeypatch.setenv("TECHSEARCH_GROQ_FREE", "1")
    monkeypatch.setattr(ev, "check_groq_model", lambda _: {"accessible": True})
    monkeypatch.setattr(ev.time, "sleep", lambda _: None)
    responses = iter([(2, ["absent"]), (None, []), (2, ["s2"]), (1, ["s2"]), (None, [])])
    calls = []

    def post(url, **options):
        assert url == ev.GROQ_ENDPOINT and not options["allow_redirects"]
        body = options["json"]
        assert body["model"] == ev.GROQ_MODEL and body["response_format"] == judging.RESPONSE_FORMAT
        assert body["max_completion_tokens"] == 512 and body["reasoning_effort"] == "low"
        evidence = json.loads(body["messages"][1]["content"])
        assert "attempts" not in evidence and "previous grade" not in body["messages"][1]["content"]
        calls.append((body["messages"][0]["content"], len(evidence["sections"])))
        grade, refs = next(responses)
        content = json.dumps({"pair_id": evidence["pair_id"], "grade": grade,
                              "rationale": "Mocked rationale.", "segment_ids": refs})
        payload = {"model": ev.GROQ_MODEL, "choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        return SimpleNamespace(status_code=200, headers={}, ok=True, is_redirect=False, json=lambda: payload)

    monkeypatch.setattr(ev.requests, "post", post)
    provider = ev.AnnotationProvider({"endpoint": ev.GROQ_ENDPOINT, "model": ev.GROQ_MODEL,
                                      "prompt_version": judging.VERSION}, 4, budget=budget)
    base = {"pair_id": "opaque", "sections": [{"id": "s1"}]}
    large = {"pair_id": "opaque", "sections": [{"id": "s1"}, {"id": "s2"}]}
    record = {"evidence": {"base": base, "expanded": large}, "attempts": []}
    cache = tmp_path / "pair.json"
    with pytest.raises(ev.AnnotationBudgetExhausted):
        ev.judge_pair_v2(provider, record, cache, audited=True)
    assert [a["variant"] for a in read_json(cache)["attempts"]] == ["primary", "expand", "audit"]

    resume = ev.GroqBudget(path, True, judge_version="v2")
    resume.authorize_v2_pilot("sealed")
    provider = ev.AnnotationProvider({"endpoint": ev.GROQ_ENDPOINT, "model": ev.GROQ_MODEL,
                                      "prompt_version": judging.VERSION}, 1, budget=resume)
    record = read_json(cache)
    ev.judge_pair_v2(provider, record, cache, audited=True)
    ev.judge_pair_v2(provider, record, cache, audited=True)
    assert record["unresolved"] and "grade" not in record
    assert calls == [(judging.PROMPTS["primary"], 1)] * 2 + [
        (judging.PROMPTS[stage], 2) for stage in ("expand", "audit", "adjudicate")]
    assert resume.record["v2_pilot_attempts"] == 5 and resume.record["pilot_attempts"] == 69
    assert resume.record["total"] == 74 and resume.record["retries"] == 12
    assert resume.record["expand"] == 1 and resume.record["adjudicate"] == 2


def test_cache_identity_and_v2_allowance_are_versioned(tmp_path):
    group = {"id": "q"}
    config = {"endpoint": ev.GROQ_ENDPOINT, "model": ev.GROQ_MODEL, "audit_fraction": .15}
    initial = {"q": {"information_need": "An interpretation."}}
    protocol = judging.identity("source", initial)
    assert protocol != judging.identity("source", {"q": {"information_need": "Changed."}})
    assert ev.annotation_key("r", "source", {**config, "prompt_version": ev.GROQ_PROMPT}, group, "d") != (
        ev.annotation_key("r", protocol, {**config, "prompt_version": judging.VERSION}, group, "d"))
    path = tmp_path / "budget.json"
    budget = ev.GroqBudget(path, True, judge_version="v2")
    budget.authorize_v2_pilot(protocol, 75)
    budget.record.update(total=143, pilot_attempts=69, v2_pilot_attempts=74)
    budget.reserve("audit", False)
    with pytest.raises(ev.AnnotationBudgetExhausted):
        budget.reserve("adjudicate", False)
    with pytest.raises(ValueError, match="authorization"):
        budget.authorize_v2_pilot("other", 75)
    assert read_json(path)["total"] == 144 and read_json(path)["pilot_attempts"] == 69
    budget.record["total"] = 4000
    with pytest.raises(ev.AnnotationBudgetExhausted):
        budget.reserve("primary", False)
