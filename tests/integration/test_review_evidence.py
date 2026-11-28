from dataclasses import asdict

import pytest

from techsearch import evaluation, judging, judging_v3
from techsearch.human_review import validate_review
from techsearch.query import parse


def row(ordinal, text, field="question", answer=None, kind="paragraph"):
    return {"ordinal": ordinal, "segment_id": f"fixture-{ordinal}", "text": text, "field": field,
            "answer_id": answer, "type": kind, "heading_path": []}


def page(title, sections, *, source="stackoverflow", tags=None):
    tags = tags if tags is not None else ["javascript"]
    return {"title": title, "source": source, "topic": "javascript", "tags": tags, "segments": [
        row(0, title, "title"), *sections]}


def intent(settings, query, target=None, mode="keyword"):
    constraint = parse(query, mode, settings.search, set()).constraint
    return {"original_query": query, "information_need": query, "target": target,
            "constraints": asdict(constraint) if constraint is not None else None}


def test_answers_stay_with_code_and_question_context(settings):
    # The source question supplies inputs and expected output. The solution is answer 1584377.
    document = page("How to merge two arrays in JavaScript and de-duplicate items", [
        row(1, "How do I combine these arrays and keep only unique items?"),
        *[row(i, "How do I combine JavaScript arrays with unique values? " * 20) for i in range(2, 8)],
        row(8, "Use a Set to keep each value once.", "answer", 1584377),
        row(9, "const unique = [...new Set([...array1, ...array2])];", "code", 1584377, "code"),
        row(10, "Its spread output turns the Set back into an array.", "answer", 1584377),
    ])
    query = intent(settings, "tag:javascript arrays")
    base, expanded = judging_v3.contextual_evidence(document, query, "pair", settings.search)
    for packet in (base, expanded):
        sections = {item["id"]: item for item in packet["sections"]}
        assert packet["answer_evidence"] == "available"
        assert sections["s1"]["section"] == "question"
        assert all(sections[key]["answer_id"] == 1584377 for key in ("s8", "s9", "s10"))
        assert packet["matching_facts"]["checks"][0]["full"]
    assert "expected output" in judging_v3.RUBRIC
    unanswered = page(document["title"], [row(1, "Array input and expected output only.")])
    base, _ = judging_v3.contextual_evidence(unanswered, query, "pair", settings.search)
    assert base["answer_evidence"] == "no_saved_answer"


def test_missing_safe_answer_excerpt_is_explicit(settings):
    document = page("A long single-line example", [
        row(1, "The answer contains a long generated source line."),
        row(2, "a" * 7000, "code", 11, "code"),
    ])
    snapshots = judging_v3.contextual_evidence(document, intent(settings, "generated code"), "pair", settings.search)
    assert all(packet["answer_evidence"] == "insufficient" and packet["omitted_segments"] == 1 for packet in snapshots)
    assert all(packet["sections"][0]["section"] == "question" for packet in snapshots)


def test_distinct_apis_and_working_division_assignment(settings):
    alternative = page("Removing HTMLCollection elements", [
        row(1, "var paragraphs = document.querySelectorAll('p');", "code", 23989142, "code")])
    query = intent(settings, "document.querySelector", "document.querySelector")
    base, _ = judging_v3.contextual_evidence(alternative, query, "pair", settings.search)
    assert base["matching_facts"]["exact_target"] == {"full": False, "visible": False, "visible_spans": []}
    assert "document.querySelectorAll" in base["sections"][0]["text"]

    code = "do {\n  fileSizeInBytes /= 1024;\n} while (fileSizeInBytes > 1024);"
    division = page("Converting file size in bytes", [
        row(1, "This converts bytes to a readable size."),
        row(2, code, "question", kind="code"),
        row(3, "These units use powers of 1024.", "answer", 10420413),
    ])
    query = intent(settings, "/= assignment division", "/=")
    base, _ = judging_v3.contextual_evidence(division, query, "pair", settings.search)
    assert base["answer_evidence"] == "available"
    location = base["matching_facts"]["exact_target"]["visible_spans"]
    assert location == [["s2", code.index("/="), code.index("/=") + 2]]
    assert "fileSizeInBytes /= 1024" in next(s["text"] for s in base["sections"] if s["id"] == "s2")


def test_phrase_original_positions_code_fields_and_boolean_constraints(settings):
    query = intent(settings, 'source:mdn AND code:"form data" AND NOT legacy', mode="boolean")
    code = "// Get the form data from the event object\nlet data = e.formData;"
    sections = [row(1, code, "code", kind="code"), row(2, "form data in prose", "body")]
    document = page("FormDataEvent: formData property", sections, source="mdn", tags=[])
    base, _ = judging_v3.contextual_evidence(document, query, "pair", settings.search)
    assert base["matching_facts"]["constraints"] == {"full": True, "visible": True}
    phrase = next(item for item in base["matching_facts"]["checks"] if item["kind"] == "phrase")
    assert phrase["visible_spans"] == [["s1", code.index("form data"), code.index("form data") + 9]]
    for invalid in (
        [row(1, "form", "code"), row(2, "data", "code")],
        [row(1, "const code = e.formData;", "code", kind="code")],
        [row(1, "form data", "code", kind="legacy_flat")],
        [row(1, code, "code"), row(2, "Legacy", "body")],
    ):
        doc = page("FormDataEvent", invalid, source="mdn", tags=[])
        packet, _ = judging_v3.contextual_evidence(doc, query, "pair", settings.search)
        assert not packet["matching_facts"]["constraints"]["full"]


def test_v3_evidence_identity_and_human_export_are_separate(settings):
    interpretation = {"q": intent(settings, '"form data"')}
    v3 = judging_v3.identity("same-study", interpretation)
    assert v3 != judging.identity("same-study", interpretation)
    config = {"prompt_version": judging_v3.VERSION, "model": evaluation.GROQ_MODEL,
              "endpoint": evaluation.GROQ_ENDPOINT, "audit_fraction": .15}
    first = evaluation.annotation_key("release", v3, config, {"id": "q"}, "d", evidence_identity="base")
    assert first != evaluation.annotation_key("release", v3, config, {"id": "q"}, "d", evidence_identity="expanded")
    manifest = {"schema": 1, "batch_id": "frozen", "judging_protocol": v3, "pairs": [{"pair_id": "one"}, {"pair_id": "two"}]}
    export = {"schema": 1, "batch_id": "frozen", "judging_protocol": v3,
              "grades": {"one": {"grade": 0, "comment": "Different task."}}}
    assert validate_review(export, manifest)["pending"] == 1
    with pytest.raises(ValueError, match="incomplete"):
        validate_review(export, manifest, complete=True)
    export["grades"]["two"] = {"grade": None, "comment": "Missing explanation"}
    assert validate_review(export, manifest, complete=True) == {
        "submitted": 2, "numeric_grades": 1, "abstentions": 1, "pending": 0}
    with pytest.raises(ValueError, match="another batch"):
        validate_review({**export, "batch_id": "old"}, manifest)
