"""Prepare the blind study review and score complete human exports locally."""
import json
from collections import defaultdict
from urllib.parse import urlsplit

from . import evaluation, judging, judging_v3
from .experiments import save_report
from .io import atomic_file, digest, dumps, read_json, write_json
from .preprocessing import analyze


STUDY_REVIEW = "groq-dev50-study-review.json"
PILOT_REVIEW = "groq-dev50-v3-human-review.json"
REPORT_NAME = "evaluation-lab-groq-dev50-human"
METHOD_NAMES = {"tfidf": "TF-IDF", "bm25": "BM25", "likelihood": "Query likelihood",
                "dense": "Semantic", "hybrid": "Hybrid", "pagerank": "BM25 + PageRank"}


def study_batch(settings, release_id):
    study, rows = evaluation.groq_study(settings, release_id)
    intents = judging.interpretations(settings, rows)
    pool = evaluation.pool_for({"runs": rows, "split": "dev"}, settings, depth=10)
    protocol = judging_v3.identity(study["protocol"], intents)
    identities = [{"pair_id": digest([g["id"], doc]), "group": g["id"], "document": doc}
                  for g, doc in sorted(pool, key=lambda pair: (pair[0]["id"], pair[1]))]
    manifest = {"schema": 2, "release_id": release_id, "study_protocol": study["protocol"],
                "judging_protocol": protocol, "pool_pairs": len(pool), "pairs": identities}
    manifest["batch_id"] = digest(manifest)
    return study, rows, intents, manifest


def compatible_pilot(settings, manifest):
    path = evaluation.home(settings) / PILOT_REVIEW
    if not path.is_file():
        return None
    pilot = read_json(path)
    pairs = {item["pair_id"]: (item["group"], item["document"]) for item in manifest["pairs"]}
    bound = ("release_id", "study_protocol", "judging_protocol")
    if (pilot.get("schema") != 1 or any(pilot.get(k) != manifest[k] for k in bound)
            or pilot.get("batch_id") != digest({k: v for k, v in pilot.items() if k != "batch_id"})):
        return None
    ids = set()
    for item in pilot["pairs"]:
        pair = item["pair_id"]
        if pair in ids or pairs.get(pair) != (item["group"], item["document"]):
            return None
        ids.add(pair)
    return pilot


def source_view(page):
    url = urlsplit(page["url"])
    source_url = page["url"] if url.scheme == "https" and url.hostname in {
        "developer.mozilla.org", "stackoverflow.com"} and not url.username and not url.password else None
    metadata = page["metadata"]
    sections = [{"kind": s["type"], "text": s["text"], "answer_id": s.get("answer_id"),
                 "heading_path": s.get("heading_path", []), "segment_id": s.get("segment_id"),
                 "ordinal": s["ordinal"]} for s in page["segments"] if s["field"] not in {"title", "tag"}]
    answers = [{"id": answer["answer_id"], "author": answer.get("author"),
                "license": answer.get("content_license"), "accepted": answer.get("is_accepted", False)}
               for answer in page["answers"]]
    return {"title": page["title"], "source": page["source"], "url": source_url, "tags": page["tags"],
            "author": metadata.get("author"), "license": metadata.get("content_license"),
            "path": metadata.get("source_path"), "sections": sections, "answers": answers}


def excerpt(sections, terms):
    prose = [s for s in sections if s["kind"] in {"paragraph", "list_item", "blockquote"} and len(s["text"]) > 28]
    if not prose:
        prose = sections
    if not prose:
        return ""
    def priority(section):
        overlap = len(terms & {token.term for token in analyze(section["text"])})
        return overlap, section["answer_id"] is not None
    text = " ".join(max(prose, key=priority)["text"].split())
    if len(text) <= 250:
        return text
    return (text[:250].rsplit(" ", 1)[0] or text[:250]) + "…"


def prepare(settings, service, output):
    _, rows, intents, manifest = study_batch(settings, service.release.id)
    path = evaluation.home(settings) / STUDY_REVIEW
    if path.is_file() and read_json(path) != manifest:
        raise ValueError("Review inputs differ from the frozen study batch.")
    pilot = compatible_pilot(settings, manifest)
    documents = {}
    pairs = defaultdict(list)
    for item in manifest["pairs"]:
        stable, group = item["document"], item["group"]
        if stable not in documents:
            documents[stable] = source_view(service.documents.document(stable))
        pairs[group].append(item)
    queries = []
    for row in rows:
        group = row["id"]
        intent = intents[group]
        terms = {token.term for token in analyze(intent["original_query"])}
        ordered = sorted(pairs[group], key=lambda item: (
            documents[item["document"]]["title"].casefold(), item["document"]))
        queries.append({"query": intent, "pairs": [{"pair_id": item["pair_id"], "document": item["document"],
                        "excerpt": excerpt(documents[item["document"]]["sections"], terms)} for item in ordered]})
    legacy = {"batch_id": pilot["batch_id"], "pairs": [row["pair_id"] for row in pilot["pairs"]]} if pilot else None
    data = dumps({"schema": manifest["schema"], "batch_id": manifest["batch_id"],
                  "judging_protocol": manifest["judging_protocol"], "queries": queries,
                  "documents": documents, "legacy": legacy}).replace("<", "\\u003c")
    template = (settings.root / "frontend/review.html").read_text(encoding="utf-8")
    if template.count("__REVIEW_DATA__") != 1:
        raise ValueError("The review page must have one data placeholder.")
    output = output or settings.path("artifacts") / "techsearch-study-review.html"
    if output.resolve() == (settings.path("artifacts") / "techsearch-human-review.html").resolve() or output.suffix.lower() != ".html":
        raise ValueError("Use a separate HTML path for the study page.")
    with atomic_file(output) as file:
        file.write(template.replace("__REVIEW_DATA__", data).encode("utf-8"))
    if not path.exists():
        write_json(path, manifest)
    return {"review_page": str(output.resolve()), "batch": str(path.resolve()), "queries": len(queries),
            "pool_pairs": manifest["pool_pairs"], "unique_documents": len(documents),
            "judging_protocol": manifest["judging_protocol"], "compatible_pilot_export": bool(pilot)}


def validate_review(export, manifest, *, complete=False):
    if not isinstance(export, dict) or type(export.get("schema")) is not int or any(export.get(key) != manifest[key]
                                           for key in ("schema", "batch_id", "judging_protocol")):
        raise ValueError("The review file belongs to another batch or protocol.")
    expected = {row["pair_id"] for row in manifest["pairs"]}
    grades = export.get("grades")
    if not isinstance(grades, dict) or not set(grades) <= expected or (complete and set(grades) != expected):
        raise ValueError("Review pair IDs are invalid or the file is incomplete.")
    for row in grades.values():
        if not isinstance(row, dict) or set(row) != {"grade", "comment"}:
            raise ValueError("Invalid review entry.")
        grade, comment = row["grade"], row["comment"]
        if grade is not None and (type(grade) is not int or not 0 <= grade <= 3):
            raise ValueError("A grade must be 0–3 or an abstention.")
        if not isinstance(comment, str) or len(comment) > 2000:
            raise ValueError("Comments must be text of at most 2,000 characters.")
    return {"submitted": len(grades), "numeric_grades": sum(row["grade"] is not None for row in grades.values()),
            "abstentions": sum(row["grade"] is None for row in grades.values()), "pending": len(expected) - len(grades)}


def study_grades(export, manifest, pilot=None):
    if not isinstance(export, dict):
        raise ValueError("A review export must be a JSON object.")
    if export.get("schema") == 1 and pilot is not None:
        validate_review(export, pilot)
        return export["grades"]
    items = export.get("grades")
    if not isinstance(items, list):
        raise ValueError("Use an export from the study or its compatible pilot.")
    grades = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"pair_id", "grade", "comment"}:
            raise ValueError("Invalid study review entry.")
        pair = item["pair_id"]
        if not isinstance(pair, str) or pair in grades:
            raise ValueError("Invalid or duplicate query–document pair.")
        grades[pair] = {"grade": item["grade"], "comment": item["comment"]}
    validate_review({**export, "grades": grades}, manifest)
    return grades


def compare(settings, release, path):
    def unique_object(items):
        result = dict(items)
        if len(result) != len(items):
            raise ValueError("Duplicate JSON object key in review export.")
        return result

    with path.open(encoding="utf-8-sig") as stream:
        export = json.load(stream, object_pairs_hook=unique_object)
    study, rows, _, manifest = study_batch(settings, release.id)
    grades = study_grades(export, manifest, compatible_pilot(settings, manifest))
    qrels = defaultdict(dict)
    for pair in manifest["pairs"]:
        grade = grades.get(pair["pair_id"], {}).get("grade")
        if grade is not None:
            qrels[pair["group"]][pair["document"]] = grade
    judged = sum(map(len, qrels.values()))
    report = {"split": "dev", "profile": evaluation.GROQ_PROFILE, "label_type": "human",
              "protocol": study["protocol"], "judging_protocol": manifest["judging_protocol"],
              "review_batch_id": manifest["batch_id"], "query_count": len(rows), "total_pairs": manifest["pool_pairs"],
              "labeled": judged, "unresolved": sum(row["grade"] is None for row in grades.values()),
              "pending": manifest["pool_pairs"] - judged}
    if report["pending"]:
        return {**report, "status": "partial", "reason": "All pooled pairs need numeric grades before comparison."}
    report.update(evaluation.metrics({"runs": rows}, qrels, None))
    report.update(status="complete", review_fingerprint=digest(grades), relevant_grade_minimum=2,
                  ndcg_gain="2^grade - 1", excluded_queries=[],
                  comparison=[{"method": name, **report["aggregates"][key]} for key, name in METHOD_NAMES.items()],
                  queries_without_relevant_results=[row["id"] for row in rows
                                                     if not any(grade >= 2 for grade in qrels[row["id"]].values())],
                  zero_relevance_policy="With no grades 2–3, Precision and MRR are zero. nDCG is zero for an ideal gain of zero. Grade 1 still contributes graded gain.")
    return save_report(settings, release, REPORT_NAME, report)
