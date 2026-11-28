import json
from types import SimpleNamespace

import pytest

from techsearch import evaluation, human_review
from techsearch.io import digest, write_json


@pytest.fixture
def study(settings, monkeypatch):
    def group(key, docs):
        return {"id": key, "class": "natural-language", "query": key,
                "methods": {method: {"status": "ok", "ids": list(reversed(docs)) if method == "pagerank" else docs}
                            for method in evaluation.LAB_DESIGNS}}

    rows = [group("first query", ["shared", "other"]),
            group("second query", ["shared"]), group("third query", ["last"])]
    release = SimpleNamespace(id="example")
    monkeypatch.setattr(evaluation, "groq_study", lambda *_: ({"protocol": "rankings"}, rows))
    monkeypatch.setattr(human_review.judging, "interpretations", lambda *_: {"case": "test"})
    _, _, _, manifest = human_review.study_batch(settings, release.id)
    return release, manifest


def export_for(manifest, entries):
    return {**{key: manifest[key] for key in ("schema", "batch_id", "judging_protocol")}, "grades": entries}


def test_deduplication_and_complete_six_run_metrics(settings, study):
    release, manifest = study
    assert manifest["pool_pairs"] == 4
    assert len({row["pair_id"] for row in manifest["pairs"] if row["document"] == "shared"}) == 2
    grades = {("first query", "shared"): 3, ("first query", "other"): 1,
              ("second query", "shared"): 1, ("third query", "last"): 0}
    rows = [{"pair_id": row["pair_id"], "grade": grades[row["group"], row["document"]], "comment": ""}
            for row in manifest["pairs"]]
    file = settings.root / "review.json"
    report_file = settings.path("artifacts") / "reports" / release.id / f"{human_review.REPORT_NAME}.json"

    write_json(file, export_for(manifest, [{**rows[0], "grade": None}, *rows[1:]]))
    partial = human_review.compare(settings, release, file)
    assert partial["pending"] == partial["unresolved"] == 1 and "aggregates" not in partial
    assert not report_file.exists()

    write_json(file, export_for(manifest, rows))
    report = human_review.compare(settings, release, file)["report"]
    assert report_file.is_file()
    assert report["status"] == "complete" and report["label_type"] == "human"
    assert set(report["aggregates"]) == set(evaluation.LAB_DESIGNS)
    assert set(report["sample_counts"].values()) == {3}
    assert report["aggregates"]["bm25"] == {"nDCG@10": 2 / 3, "P@10": .1 / 3, "MRR@10": 1 / 3}
    assert report["aggregates"]["pagerank"]["MRR@10"] == .5 / 3
    assert report["queries_without_relevant_results"] == ["second query", "third query"]
    assert report["per_group"]["third query"]["bm25"]["nDCG@10"] == 0
    assert report["per_group"]["second query"]["bm25"]["nDCG@10"] == 1


def test_pilot_compatibility_and_duplicate_rejection(settings, study):
    release, manifest = study
    selected = manifest["pairs"][:2]
    pilot = {**{key: manifest[key] for key in ("release_id", "study_protocol", "judging_protocol")},
             "schema": 1, "pairs": selected}
    pilot["batch_id"] = digest(pilot)
    write_json(evaluation.home(settings) / human_review.PILOT_REVIEW, pilot)
    compatible = human_review.compatible_pilot(settings, manifest)
    assert compatible == pilot
    entry = {"grade": 2, "comment": "Partial"}
    picked, outside = selected[0]["pair_id"], manifest["pairs"][-1]["pair_id"]
    assert human_review.study_grades(export_for(pilot, {picked: entry}), manifest, pilot) == {picked: entry}
    with pytest.raises(ValueError, match="pair IDs"):
        human_review.study_grades(export_for(pilot, {outside: entry}), manifest, pilot)
    row = {"pair_id": picked, **entry}
    with pytest.raises(ValueError, match="duplicate"):
        human_review.study_grades(export_for(manifest, [row, row]), manifest, pilot)
    file = settings.root / "duplicate.json"
    file.write_text('{"schema":2,' + json.dumps(export_for(manifest, [row]))[1:], encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON"):
        human_review.compare(settings, release, file)
