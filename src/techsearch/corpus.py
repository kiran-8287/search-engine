"""Schema adapters for structured collector output and pre-existing flat JSON."""
from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from .io import digest, dumps, file_hash, read_json, write_jsonl
from .repository import write_indexed_jsonl

RAW_FILES = {"mdn": "mdn_documents.json", "stackoverflow": "stackoverflow_documents.json"}
MDN = "developer.mozilla.org"
SO = "stackoverflow.com"
SO_URL = re.compile(r"^/(q|questions|a|answers)/([1-9]\d*)(?:/|$)")
BROWSER_EVIDENCE = re.compile(
    r"\b(?:browser|javascript|html|css|dom|fetch\(|cors|same-origin|web page|http header|frontend|front.end|"
    r"screen reader|rendering|paint|navigator\.|window\.|document\.)", re.I
)


def url(value, base=""):
    try:
        parts = urlsplit(urljoin(base, value))
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        host = parts.hostname.lower()
        netloc = f"[{host}]" if ":" in host else host
        if parts.port:
            netloc += f":{parts.port}"
        path = parts.path or "/"
        if host == MDN and (path.startswith("/docs/") or path.lower().startswith("/en-us/docs/")):
            path = "/en-US/docs/" + path[(6 if path.startswith("/docs/") else 12):].rstrip("/")
        scheme = "https" if host in {MDN, SO, "www.stackoverflow.com"} else parts.scheme
        return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))
    except (AttributeError, TypeError, ValueError):
        return None


def alias_key(value):
    parts = urlsplit(value)
    host = parts.hostname
    if host == MDN:
        return f"mdn:{unquote(parts.path).casefold().rstrip('/')}"
    if host in {SO, "www.stackoverflow.com"}:
        match = SO_URL.match(parts.path)
        if match:
            kind = "answer" if match[1] in {"a", "answers"} else "question"
            return f"so:{kind}:{match[2]}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def raw_path(settings, source):
    preferred = settings.path("data") / "raw" / RAW_FILES[source]
    legacy = settings.root / RAW_FILES[source]
    return preferred if preferred.is_file() or not legacy.exists() else legacy


def raw_inputs(settings):
    data = settings.path("data")
    paths = {}
    for source, filename in RAW_FILES.items():
        path = raw_path(settings, source)
        kind = "raw" if path == data / "raw" / filename else "legacy"
        paths[f"{kind}/{filename}"] = path
    for name in ("mdn_source_path_to_url.json", "mdn_collection_report.json", "browser_compat.json"):
        paths[f"raw/{name}"] = data / "raw" / name
    fingerprints = {name: file_hash(path) for name, path in paths.items() if path.is_file()}
    for source in RAW_FILES:
        name = f"manifests/collection-{source}.json"
        path = data / name
        if path.is_file():
            collection = read_json(path)
            if collection.get("raw_hashes"):
                fields = ("source_revision", "archive_sha256", "collector_sha256", "raw_hashes")
                fingerprints[name] = digest({field: collection.get(field) for field in fields})
    return fingerprints


def source_attestations(settings, fingerprints):
    attestations = {}
    directory = settings.path("data") / "manifests"
    for source, filename in RAW_FILES.items():
        artifact = f"raw/{filename}" if f"raw/{filename}" in fingerprints else f"legacy/{filename}"
        if artifact not in fingerprints:
            continue
        checksum = fingerprints[artifact]
        provenance = {"artifact": artifact, "sha256": checksum, "status": "unattested",
                      "source_revision": None, "collector_sha256": None}
        path = directory / f"collection-{source}.json"
        if artifact.startswith("raw/") and path.is_file():
            record = read_json(path)
            if not record.get("raw_hashes") and isinstance(record.get("previous"), dict):
                record = record["previous"]
            if record.get("raw_hashes", {}).get(filename) == checksum:
                provenance.update({key: record.get(key) for key in (
                    "source_revision", "archive_sha256", "collector_sha256", "finished_at", "status", "target"
                )})
        attestations[source] = provenance
    return attestations


def positive_id(value):
    text = str(value)
    if not re.fullmatch(r"[1-9]\d{0,18}", text):
        raise ValueError("Expected a positive source ID")
    number = int(text)
    if number > 2**63 - 1:
        raise ValueError("Source ID outside supported integer range")
    return number


def segments(record, kind, answer=None):
    structured = record.get("segments")
    legacy = structured is None
    if legacy:
        if not isinstance(record.get("content"), str):
            raise ValueError("Missing text and structured segments")
        structured = [{"text": record["content"], "type": "legacy_flat"}]
    if not isinstance(structured, list):
        raise ValueError("Segments must be an array")
    for item in structured:
        if not isinstance(item, dict):
            raise ValueError("Invalid segment")
        type_ = item.get("type", "paragraph")
        content = item.get("code", item.get("text")) if type_ == "code" else item.get("text")
        if not isinstance(content, str) or not isinstance(type_, str):
            raise ValueError("Invalid segment text or type")
        headings = item.get("heading_path", [])
        if not isinstance(headings, list) or any(not isinstance(value, str) for value in headings):
            raise ValueError("Invalid segment heading path")
        field = {"code": "code", "heading": "heading"}.get(type_, kind)
        if content.strip():
            yield {**item, "text": content, "type": type_, "field": field, "answer_id": answer,
                   "source_ordinal": item.get("ordinal")}


def topic_for_so(record, scope):
    tags = record.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("Invalid tags")
    tags = {tag.casefold() for tag in tags}
    if tags.intersection(scope["so_exclusions"]):
        raise ValueError("Framework or server tag")
    text = f"{record.get('title', '')} {record.get('content', '')[:3500]}" if isinstance(record.get("content", ""), str) else ""
    evidence = bool(BROWSER_EVIDENCE.search(text))
    matches = [topic for topic, group in scope["browser_tags"].items() if tags.intersection(group)]
    preferred = {"web_apis": "dom", "general_web": "general-web"}.get(record.get("category"), record.get("category"))
    if preferred in matches and (preferred not in {"http", "security"} or evidence):
        return preferred
    for topic in ("accessibility", "css", "html", "dom", "security", "http", "performance", "javascript"):
        if topic in matches and (topic not in {"http", "security"} or evidence):
            return topic
    if evidence and tags.intersection({"json", "rest", "web", "frontend"}):
        return "general-web"
    raise ValueError("Insufficient browser-domain evidence")


def normalize(record, source, scope):
    if not isinstance(record, dict):
        raise ValueError("Parent must be an object")
    title = record.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Missing title")
    if str(record.get("language", "en")).casefold() not in {"en", "en-us"}:
        raise ValueError("Parent is outside the English corpus")
    page_url = url(record.get("url"))
    host = urlsplit(page_url).hostname if page_url else None
    if host not in ({MDN} if source == "mdn" else {SO, "www.stackoverflow.com"}):
        raise ValueError("Invalid source URL")
    answers = {}
    aliases = []
    metadata = dict(record)
    for key in ("content", "segments", "answers", "code_blocks", "incoming_links", "incoming_link_references"):
        metadata.pop(key, None)
    if source == "mdn":
        path = record.get("source_path") or record.get("id")
        if not isinstance(path, str) or not path.endswith("/index.md") or ".." in PurePosixPath(path).parts or path.startswith("/"):
            raise ValueError("Invalid MDN source path")
        root = next((root for root in scope["mdn_roots"] if path.casefold().startswith(root + "/")), None)
        if root is None or any(part in "/" + path.casefold() for part in scope["mdn_exclusions"]):
            raise ValueError("MDN page outside set scope")
        stable = "mdn:" + path
        topic = scope["mdn_roots"][root]
        body = list(segments(record, "body"))
        aliases += [url(value, page_url) for value in record.get("redirects", []) if isinstance(value, str)]
        metadata.update(author="MDN contributors", author_url=page_url, content_license="CC BY-SA 2.5 (MDN documentation; see source for exceptions)")
        flags = {str(value).casefold() for value in record.get("status", [])} if isinstance(record.get("status"), list) else set()
        metadata.update(deprecated=bool("deprecated" in flags or record.get("deprecated") is True),
                        experimental=bool("experimental" in flags or record.get("experimental") is True))
    else:
        question_id = positive_id(record.get("question_id", record.get("id")))
        match = SO_URL.match(urlsplit(page_url).path)
        if not match or match[1] not in {"q", "questions"} or int(match[2]) != question_id:
            raise ValueError("Question ID and URL disagree")
        stable = f"so:{question_id}"
        title = html.unescape(title)
        topic = topic_for_so(record, scope)
        body = list(segments(record, "question"))
        metadata["author"] = record.get("question_author")
        owner_id = record.get("question_owner_id")
        metadata["author_url"] = f"https://stackoverflow.com/users/{owner_id}" if type(owner_id) is int and owner_id > 0 else None
        accepted = record.get("accepted_answer_id")
        if accepted is not None:
            aliases.append(f"https://stackoverflow.com/a/{positive_id(accepted)}")
        raw_answers = record.get("answers", [])
        if not isinstance(raw_answers, list):
            raise ValueError("Answers must be an array")
        for item in raw_answers:
            if not isinstance(item, dict):
                raise ValueError("Invalid answer")
            aid = positive_id(item.get("answer_id"))
            if aid in answers:
                raise ValueError("Duplicate answer ID")
            body.extend(segments(item, "answer", aid))
            answer = {key: value for key, value in item.items() if key not in ("content", "segments", "code_blocks")}
            answer["url"] = f"https://stackoverflow.com/a/{aid}"
            owner = item.get("owner_id")
            answer["author_url"] = f"https://stackoverflow.com/users/{owner}" if type(owner) is int and owner > 0 else None
            answers[aid] = answer
            aliases.append(answer["url"])
    if not any(segment["answer_id"] is None for segment in body):
        raise ValueError("Missing parent content")
    tags = sorted({tag.casefold() for tag in record.get("tags", []) if isinstance(tag, str)}) if source == "stackoverflow" else []
    title_segment = {"text": title, "type": "title", "field": "title", "answer_id": None}
    tag_segments = [{"text": tag, "type": "tag", "field": "tag", "answer_id": None} for tag in tags]
    return {"id": stable, "source": source, "url": page_url, "title": title, "topic": topic,
            "tags": tags, "segments": [title_segment, *body, *tag_segments], "metadata": metadata,
            "answers": answers, "aliases": [item for item in aliases if item]}


def refs(record):
    references = record.get("link_references")
    if isinstance(references, list) and references:
        return references
    urls = record.get("outgoing_links")
    return [{"url": value} for value in urls if isinstance(value, str)] if isinstance(urls, list) else []


def build_corpus(path, settings):
    rejected, parents = [], []
    observed, macros, availability, legacy_counts = Counter(), Counter(), Counter(), Counter()
    macro_affected = Counter()
    seen = {"id": set(), "url": set(), "text": set(), "answers": set()}
    data = settings.path("data")
    for source in RAW_FILES:
        source_file = raw_path(settings, source)
        if not source_file.is_file():
            continue
        raw = read_json(source_file)
        if not isinstance(raw, list):
            raise ValueError(f"{source_file.name} must contain an array")
        for offset, record in enumerate(raw):
            try:
                parent = normalize(record, source, settings.scope)
                dumps(parent)
                identities = {"id": parent["id"], "url": alias_key(parent["url"]),
                              "text": digest([source, [(s["field"], s["text"]) for s in parent["segments"]
                                                       if s["field"] not in {"title", "tag"}]])}
                if any(identity in seen[key] for key, identity in identities.items()) or seen["answers"].intersection(parent["answers"]):
                    raise ValueError("Duplicate ID, canonical URL, exact content, or answer")
                for key, identity in identities.items():
                    seen[key].add(identity)
                seen["answers"].update(parent["answers"])
                parents.append(parent)
                observed[(source, parent["topic"])] += 1
                metadata = parent["metadata"]
                metadata["raw_array_offset"] = offset
                metadata["raw_storage"] = "raw" if source_file.parent == data / "raw" else "legacy"
                if any(item["type"] == "legacy_flat" for item in parent["segments"]):
                    legacy_counts[source] += 1
                items = metadata.get("unresolved_macros")
                if isinstance(items, list):
                    names = [str(macro.get("macro_name") or macro.get("macro") or macro.get("name") or "unknown")
                             for macro in items if isinstance(macro, dict)]
                    macros.update(names)
                    macro_affected.update(set(names))
                if source == "stackoverflow":
                    status = metadata.get("answer_collection") or {}
                    value = status.get("accepted_answer_status", "legacy-unknown") if isinstance(status, dict) else "legacy-unknown"
                    availability[str(value)] += 1
            except (TypeError, ValueError, AttributeError) as error:
                rejected.append({"source": source, "array_offset": offset, "reason": str(error)})
    if not parents:
        raise ValueError("No eligible documents. Inspect collector files and scope.")
    groups = defaultdict(list)
    for parent in parents:
        key = re.sub(r"\W+", "", parent["title"].casefold())
        groups[key].append(parent["id"])
    near = [sorted(ids) for ids in groups.values() if len(ids) > 1]
    mapping_path = data / "raw/mdn_source_path_to_url.json"
    mapping = read_json(mapping_path) if mapping_path.is_file() else {}
    compat_path = data / "raw/browser_compat.json"
    compat = read_json(compat_path) if compat_path.is_file() else {}
    compat_urls = compat.get("entries", {})
    mdn_report_path = data / "raw/mdn_collection_report.json"
    inventory = read_json(mdn_report_path) if mdn_report_path.is_file() else {}
    compat_matches = set()
    parents.sort(key=lambda item: item["id"])
    aliases = {alias_key(parent["url"]): index for index, parent in enumerate(parents)}
    ambiguous = set()
    for index, parent in enumerate(parents):
        variants = list(parent["aliases"])
        if parent["source"] == "mdn":
            source_path = parent["id"].removeprefix("mdn:")
            variants.append(f"https://{MDN}/en-US/docs/" + quote(source_path.removesuffix("/index.md"), safe="/"))
            if source_path in mapping:
                variants.append(mapping[source_path])
        for variant in variants:
            normalized = url(variant, parent["url"])
            if normalized:
                key = alias_key(normalized)
                if aliases.setdefault(key, index) != index:
                    ambiguous.add(key)
    for source_path, target in mapping.items():
        normalized = url(target)
        destination = aliases.get(alias_key(normalized)) if normalized else None
        if destination is not None and isinstance(source_path, str):
            key = f"mdn:/en-us/docs/{source_path.removesuffix('/index.md').casefold()}"
            if aliases.setdefault(key, destination) != destination:
                ambiguous.add(key)
    canonical_keys = {alias_key(parent["url"]) for parent in parents}
    for key in ambiguous - canonical_keys:
        del aliases[key]

    edges = set()
    unresolved = 0
    catalog = []

    def records():
        nonlocal unresolved
        for index, parent in enumerate(parents):
            metadata = parent["metadata"]
            key = alias_key(parent["url"])
            if key in compat_urls:
                compatibility = compat_urls[key]
                metadata["browser_compat"] = compatibility
                metadata["browser_compat_revision"] = compat.get("revision")
                compat_matches.add(key)
                for flag in ("deprecated", "experimental"):
                    metadata[flag] = metadata.get(flag, False) or any(
                        (feature.get("status") or {}).get(flag) is True for feature in compatibility
                    )
            record = {key: parent[key] for key in ("id", "source", "topic", "title", "url", "tags", "metadata")}
            record["doc"] = index
            record["segments"] = [{**segment, "ordinal": ordinal} for ordinal, segment in enumerate(parent["segments"])]
            record["answers"] = [{"answer_id": answer_id, **answer} for answer_id, answer in sorted(parent["answers"].items())]
            record["references"] = []
            for answer_id, entity in [(None, metadata), *parent["answers"].items()]:
                for reference in refs(entity):
                    if not isinstance(reference, dict):
                        continue
                    target = url(reference.get("url"), entity.get("url") or parent["url"])
                    if target:
                        destination = aliases.get(alias_key(target))
                        record["references"].append({**reference, "url": target, "answer_id": answer_id, "target_doc": destination})
                        if destination is None:
                            unresolved += 1
                        elif destination != index:
                            edges.add((index, destination))
            catalog.append({"doc": index, "stable": parent["id"], **{
                key: parent[key] for key in ("source", "topic", "title", "url", "tags")
            }})
            yield record

    write_indexed_jsonl(path / "documents.jsonl", path / "documents.offsets", records())
    write_jsonl(path / "catalog.jsonl", catalog)
    write_jsonl(path / "aliases.jsonl", ({"key": key, "doc": doc} for key, doc in sorted(aliases.items())))
    write_jsonl(path / "edges.jsonl", ({"source": src, "destination": dst} for src, dst in sorted(edges)))
    observed_paths = {parent["id"].removeprefix("mdn:") for parent in parents if parent["source"] == "mdn"}
    return {"parents": len(parents), "observed": [{"source": s, "topic": t, "parents": n} for (s, t), n in sorted(observed.items())],
            "quarantine": rejected, "near_duplicate_title_groups": near, "unresolved_macros": dict(macros),
            "parents_affected_by_macro": dict(macro_affected), "legacy_flat_parents": dict(legacy_counts),
            "mdn_inventory": inventory.get("topics", {}),
            "mdn_inventory_paths_outside_release": sorted(set(mapping) - observed_paths),
            "accepted_answer_availability": dict(availability), "unresolved_reference_occurrences": unresolved,
            "alias_conflicts": len(ambiguous), "compat_matched": len(compat_matches),
            "compat_unmatched_targets": sorted(set(compat_urls) - compat_matches)}


def inspect(settings):
    report = {}
    for source in RAW_FILES:
        path = raw_path(settings, source)
        if not path.is_file():
            report[source] = {"status": "missing", "path": str(path)}
            continue
        records = read_json(path)
        if not isinstance(records, list):
            raise ValueError(f"{path.name} must contain an array")
        topics, rejected = Counter(), Counter()
        for record in records:
            try:
                topics[normalize(record, source, settings.scope)["topic"]] += 1
            except (ValueError, TypeError, AttributeError) as error:
                rejected[str(error)] += 1
        report[source] = {"path": str(path), "bytes": path.stat().st_size, "sha256": file_hash(path),
                          "raw_parents": len(records), "eligible_before_dedup": dict(topics), "reasons": dict(rejected),
                          "structured": sum(isinstance(record, dict) and "segments" in record for record in records)}
    return report
