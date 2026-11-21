#!/usr/bin/env python3
"""Collect Stack Overflow questions and selected answers for TechSearch.

The collector keeps source structure (paragraphs, headings, lists, tables and
code blocks), records link references independently from unique graph edges,
and uses ID-based checkpoints so collection can safely resume when the
question set changes.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is convenient, but environment variables still work.
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False


# ============================================================================
# 1. PROJECT CONFIGURATION
# ============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = Path(
    os.getenv("TECHSEARCH_PROJECT_DIR", str(SCRIPT_DIR))
).resolve()
DATA_DIR = Path(os.getenv("TECHSEARCH_DATA_DIR", str(PROJECT_DIR / "data"))) / "raw"

OUTPUT_FILE = DATA_DIR / "stackoverflow_documents.json"
CHECKPOINT_FILE = PROJECT_DIR / "stackoverflow_checkpoint.json"

load_dotenv(PROJECT_DIR / ".env")
API_KEY = os.getenv("STACKEXCHANGE_API_KEY")

API_URL = "https://api.stackexchange.com/2.3"
SITE = "stackoverflow"
PAGE_SIZE = 100
MAX_API_PAGE = 25
MAX_ANSWERS_PER_QUESTION = 3
MINIMUM_QUOTA = 5
MAX_REQUEST_RETRIES = 3
REQUEST_TIMEOUT = (10, 30)  # Separate connect/read limits, in seconds.
REQUEST_DELAY_SECONDS = 0.2

# This is the current pilot acquisition target. The project plan treats it as
# an acquisition checkpoint, not as evidence that domain coverage is complete.
TARGET_QUESTIONS = 5000
SCOPE = None

TOPIC_CONFIG: dict[str, dict[str, Any]] = {
    "javascript": {
        "target": 1200,
        "tags": ["javascript", "jquery", "json"],
    },
    "html": {
        "target": 800,
        "tags": ["html"],
    },
    "css": {
        "target": 800,
        "tags": ["css"],
    },
    "web_apis": {
        "target": 1000,
        "tags": [
            "dom",
            "fetch-api",
            "xmlhttprequest",
            "websocket",
            "service-worker",
            "webassembly",
        ],
    },
    "http": {
        "target": 500,
        "tags": ["http", "https", "http-headers", "rest", "cors"],
    },
    "general_web": {
        "target": 700,
        "tags": ["web", "browser", "frontend"],
    },
}

session = requests.Session()
session.headers.update({"User-Agent": "TechSearch-Research-Collector/1.0"})

API_REQUESTS = 0
REMAINING_QUOTA: int | None = None
STOP_COLLECTION = False
ENDPOINT_BACKOFF: dict[str, float] = {}


def endpoint_family(endpoint: str) -> str:
    return re.sub(r"(?<=/)\d+(?:;\d+)*(?=/|$)", "{ids}", endpoint)


# ============================================================================
# 2. STACK EXCHANGE API
# ============================================================================

@dataclass
class ApiResult:
    """An API response with explicit status and pagination information."""

    success: bool
    items: list[dict[str, Any]]
    page: int
    page_size: int
    has_more: bool
    quota_remaining: int | None = None
    backoff: int | None = None
    error: str | None = None
    http_status: int | None = None


def api_get(
    endpoint: str,
    params: dict[str, Any] | None = None,
    *,
    page: int = 1,
) -> ApiResult:
    """Fetch one API page.

    Empty successful results and failed requests are intentionally distinct:
    callers may checkpoint an empty successful response, but must not
    checkpoint a failed response as completed work.
    """

    global API_REQUESTS, REMAINING_QUOTA, STOP_COLLECTION

    request_params: dict[str, Any] = {
        "site": SITE,
        "pagesize": PAGE_SIZE,
        "page": page,
        "filter": "withbody",
    }
    if params:
        request_params.update(params)
    if API_KEY:
        request_params["key"] = API_KEY

    effective_page = int(request_params.get("page", page))
    effective_page_size = int(request_params.get("pagesize", PAGE_SIZE))

    if STOP_COLLECTION:
        return ApiResult(
            success=False,
            items=[],
            page=effective_page,
            page_size=effective_page_size,
            has_more=False,
            quota_remaining=REMAINING_QUOTA,
            error="Collection stopped because the API quota is low.",
        )

    family = endpoint_family(endpoint)
    url = f"{API_URL}/{endpoint.lstrip('/')}"
    last_error: str | None = None
    last_status: int | None = None

    for attempt in range(MAX_REQUEST_RETRIES + 1):
        remaining_delay = ENDPOINT_BACKOFF.get(family, 0) - time.monotonic()
        if remaining_delay > 0:
            print(f"API backoff: waiting {remaining_delay:.1f} seconds.")
            time.sleep(remaining_delay)
        try:
            API_REQUESTS += 1
            response = session.get(
                url,
                params=request_params,
                timeout=REQUEST_TIMEOUT,
            )
            last_status = response.status_code

            # Parse an API error payload before deciding whether the HTTP
            # status alone explains the failure.
            try:
                payload = response.json()
            except ValueError:
                payload = None
            backoff_seconds = None
            if isinstance(payload, dict):
                value = payload.get("backoff")
                if type(value) is int and value > 0:
                    backoff_seconds = value
                    ENDPOINT_BACKOFF[family] = time.monotonic() + value

            if not response.ok:
                if isinstance(payload, dict) and payload.get("error_message"):
                    last_error = f"Stack Exchange API error {payload.get('error_id')} (HTTP {response.status_code})"
                else:
                    last_error = f"HTTP {response.status_code}"

                retryable = response.status_code in (429, 500, 502, 503, 504)
                if retryable and attempt < MAX_REQUEST_RETRIES:
                    retry_after = response.headers.get("Retry-After")
                    wait_seconds = (
                        int(retry_after)
                        if retry_after and retry_after.isdigit()
                        else min(2 ** attempt, 20)
                    )
                    print(f"Temporary API response ({response.status_code}); retrying in {wait_seconds}s.")
                    time.sleep(wait_seconds)
                    continue

                STOP_COLLECTION = True
                return ApiResult(
                    success=False,
                    items=[],
                    page=effective_page,
                    page_size=effective_page_size,
                    has_more=False,
                    quota_remaining=REMAINING_QUOTA,
                    error=last_error,
                    http_status=last_status,
                )

            if not isinstance(payload, dict):
                STOP_COLLECTION = True
                return ApiResult(
                    success=False,
                    items=[],
                    page=effective_page,
                    page_size=effective_page_size,
                    has_more=False,
                    quota_remaining=REMAINING_QUOTA,
                    error="The API response was not a JSON object.",
                    http_status=last_status,
                )

            if "error_id" in payload:
                last_error = f"Stack Exchange API error {payload.get('error_id')}"
                STOP_COLLECTION = True
                return ApiResult(
                    success=False,
                    items=[],
                    page=effective_page,
                    page_size=effective_page_size,
                    has_more=False,
                    quota_remaining=payload.get("quota_remaining", REMAINING_QUOTA),
                    backoff=payload.get("backoff"),
                    error=last_error,
                    http_status=last_status,
                )

            if "items" not in payload or not isinstance(payload["items"], list):
                STOP_COLLECTION = True
                return ApiResult(
                    success=False,
                    items=[],
                    page=effective_page,
                    page_size=effective_page_size,
                    has_more=False,
                    quota_remaining=payload.get("quota_remaining", REMAINING_QUOTA),
                    error="The API response did not contain a valid 'items' list.",
                    http_status=last_status,
                )

            quota_value = payload.get("quota_remaining", REMAINING_QUOTA)
            if quota_value is not None:
                try:
                    REMAINING_QUOTA = int(quota_value)
                except (TypeError, ValueError):
                    pass

            result = ApiResult(
                success=True,
                items=payload["items"],
                page=effective_page,
                page_size=effective_page_size,
                has_more=bool(payload.get("has_more", False)),
                quota_remaining=REMAINING_QUOTA,
                backoff=backoff_seconds,
                http_status=last_status,
            )

            # Do not discard this successful page. Stop only subsequent calls;
            # the caller still processes and checkpoints this returned page.
            if REMAINING_QUOTA is not None and REMAINING_QUOTA <= MINIMUM_QUOTA:
                print(f"\nAPI quota is low ({REMAINING_QUOTA}); no further requests will be started in this run.")
                STOP_COLLECTION = True

            return result

        except requests.RequestException as error:
            last_error = f"Request failed: {type(error).__name__}"
            if attempt < MAX_REQUEST_RETRIES:
                wait_seconds = min(2 ** attempt, 20)
                print(f"{last_error}; retrying in {wait_seconds}s.")
                time.sleep(wait_seconds)
                continue
            break

    STOP_COLLECTION = True
    print("Connection retry budget exhausted; pausing this run. Rerun to resume.")
    return ApiResult(
        success=False,
        items=[],
        page=effective_page,
        page_size=effective_page_size,
        has_more=False,
        quota_remaining=REMAINING_QUOTA,
        error=last_error or "Unknown request failure.",
        http_status=last_status,
    )


def chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


# ============================================================================
# 3. CHECKPOINTS
# ============================================================================

EMPTY_STATE: dict[str, Any] = {
    "documents": {},
    "tag_pages": {},
    "tag_complete": {},
    "tag_page_limit_reached": {},
    "accepted_answer_ids_done": [],
    "accepted_answers_missing": [],
    "supplement_question_ids_done": [],
    "answer_request_errors": {},
    "question_windows": {},
    "question_shortfalls": [],
}


def load_checkpoint() -> dict[str, Any]:
    if not CHECKPOINT_FILE.exists():
        return {key: value.copy() if isinstance(value, (dict, list)) else value
                for key, value in EMPTY_STATE.items()}

    try:
        with CHECKPOINT_FILE.open("r", encoding="utf-8") as file:
            saved = json.load(file)

        raw_documents = saved.get("documents", {})
        documents: dict[str, dict[str, Any]] = {}
        if isinstance(raw_documents, dict):
            for key, value in raw_documents.items():
                if isinstance(value, dict):
                    question_id = value.get("question_id", key)
                    documents[str(question_id)] = value
        elif isinstance(raw_documents, list):
            for value in raw_documents:
                if isinstance(value, dict) and value.get("question_id") is not None:
                    documents[str(value["question_id"])] = value
        else:
            raise ValueError("Unknown checkpoint document format.")

        state = {
            "documents": documents,
            "tag_pages": saved.get("tag_pages", {}),
            "tag_complete": saved.get("tag_complete", {}),
            "tag_page_limit_reached": saved.get("tag_page_limit_reached", {}),
            "accepted_answer_ids_done": [
                str(value) for value in saved.get("accepted_answer_ids_done", [])
            ],
            "accepted_answers_missing": [
                str(value) for value in saved.get("accepted_answers_missing", [])
            ],
            "supplement_question_ids_done": [
                str(value) for value in saved.get("supplement_question_ids_done", [])
            ],
            "answer_request_errors": saved.get("answer_request_errors", {}),
            "question_windows": saved.get("question_windows", {}),
            "question_shortfalls": saved.get("question_shortfalls", []),
        }

        # Old checkpoints stored accepted/supplement work as batch numbers.
        # Those numbers do not identify the question/answer membership and
        # therefore are deliberately not migrated as completed work.
        if saved.get("accepted_batches_done") or saved.get("supplement_batches_done"):
            print("Legacy batch checkpoints detected; old batch numbers will be revalidated by ID.")

        print("\nCheckpoint loaded successfully.")
        print(f"Previously collected questions: {len(documents)}")
        return state

    except Exception as error:
        raise RuntimeError(
            f"Checkpoint could not be loaded: {error}. The original file was not deleted."
        ) from error


def save_checkpoint(state: dict[str, Any]) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = CHECKPOINT_FILE.with_suffix(CHECKPOINT_FILE.suffix + ".tmp")

    payload = {
        "documents": state["documents"],
        "tag_pages": state["tag_pages"],
        "tag_complete": state["tag_complete"],
        "tag_page_limit_reached": state["tag_page_limit_reached"],
        "accepted_answer_ids_done": state["accepted_answer_ids_done"],
        "accepted_answers_missing": state["accepted_answers_missing"],
        "supplement_question_ids_done": state["supplement_question_ids_done"],
        "answer_request_errors": state["answer_request_errors"],
        "question_windows": state.get("question_windows", {}),
        "question_shortfalls": state.get("question_shortfalls", []),
    }

    # Serialize once: json.dump otherwise performs millions of small writes.
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with temporary_file.open("w", encoding="utf-8") as file:
        file.write(encoded)
        file.flush()
        os.fsync(file.fileno())
    temporary_file.replace(CHECKPOINT_FILE)


# ============================================================================
# 4. STRUCTURED HTML EXTRACTION
# ============================================================================

BLOCK_CONTAINER_TAGS = {
    "article", "body", "div", "dl", "fieldset", "footer", "form",
    "main", "ol", "section", "table", "tbody", "thead", "tfoot",
    "ul",
}
HEADING_TAGS = {f"h{level}" for level in range(1, 7)}
SKIP_TAGS = {"script", "style", "noscript", "template"}


def normalize_url(url: str | None, base_url: str | None = None) -> str | None:
    if not url:
        return None
    try:
        candidate = url.strip()
        if base_url:
            candidate = urljoin(base_url, candidate)
        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            return None

        hostname = parsed.hostname.lower()
        if hostname in {"stackoverflow.com", "www.stackoverflow.com"}:
            hostname = "stackoverflow.com"
        if parsed.port:
            netloc = f"{hostname}:{parsed.port}"
        else:
            netloc = hostname
        path = re.sub(r"/+", "/", parsed.path or "/")
        if path != "/":
            path = path.rstrip("/")
        scheme = "https" if hostname == "stackoverflow.com" else parsed.scheme
        return urlunparse((scheme, netloc, path if scheme == "https" and hostname == "stackoverflow.com" else parsed.path, "",
                           parsed.query, parsed.fragment))
    except (TypeError, ValueError):
        return None


def clean_prose_text(value: str) -> str:
    """Normalize prose whitespace without flattening embedded line breaks."""
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [re.sub(r"[\t\xa0 ]+", " ", line).strip() for line in value.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def extract_node_text(
    node: Any,
    *,
    base_url: str,
    link_references: list[dict[str, Any]],
    skip_descendants: set[str] | None = None,
) -> str:
    """Extract inline text from a DOM node, retaining <br> boundaries."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag) or node.name in SKIP_TAGS:
        return ""
    if skip_descendants and node.name in skip_descendants:
        return ""

    if node.name == "br":
        return "\n"
    if node.name == "img":
        return str(node.get("alt", ""))

    if node.name == "a" and node.get("href"):
        target = normalize_url(str(node.get("href")), base_url)
        if target:
            anchor_text = clean_prose_text(node.get_text("", strip=False))
            link_references.append({
                "url": target,
                "anchor_text": anchor_text,
                "rel": list(node.get("rel", [])),
            })

    parts: list[str] = []
    block_children = {"blockquote", "div", "li", "ol", "p", "pre", "ul"}
    for child in node.children:
        child_text = extract_node_text(
            child,
            base_url=base_url,
            link_references=link_references,
            skip_descendants=skip_descendants,
        )
        if not child_text:
            continue
        if isinstance(child, Tag) and child.name in block_children and parts:
            if not parts[-1].endswith("\n"):
                parts.append("\n")
        parts.append(child_text)
        if isinstance(child, Tag) and child.name in block_children:
            if not child_text.endswith("\n"):
                parts.append("\n")
    return "".join(parts)


def extract_code_language(pre: Tag) -> str | None:
    candidates: list[str] = []
    candidates.extend(str(value) for value in pre.get("class", []))
    code = pre.find("code")
    if code:
        candidates.extend(str(value) for value in code.get("class", []))
    for candidate in candidates:
        match = re.search(r"(?:language|lang)-([A-Za-z0-9_+#.-]+)", candidate)
        if match:
            return match.group(1)
    return None


def extract_structured_segments(
    soup: BeautifulSoup,
    *,
    segment_prefix: str,
    base_url: str,
    link_references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Walk parsed HTML in document order and emit stable ordered segments."""
    segments: list[dict[str, Any]] = []
    heading_path: list[str] = []

    def add_segment(
        segment_type: str,
        text: str,
        *,
        language: str | None = None,
        source_anchor: str | None = None,
    ) -> None:
        if segment_type == "code":
            cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
            if not cleaned.strip():
                return
        else:
            cleaned = clean_prose_text(text)
            if not cleaned:
                return

        ordinal = len(segments)
        segment: dict[str, Any] = {
            "segment_id": f"{segment_prefix}:segment:{ordinal:04d}",
            "ordinal": ordinal,
            "type": segment_type,
            "text": cleaned,
            "heading_path": heading_path.copy(),
        }
        if language:
            segment["language"] = language
        if segment_type == "code":
            segment["code"] = cleaned
        if source_anchor:
            segment["source_anchor"] = source_anchor
        segments.append(segment)

    def walk(node: Any) -> None:
        if isinstance(node, NavigableString):
            text_value = str(node)
            if text_value.strip():
                add_segment("paragraph", text_value)
            return
        if not isinstance(node, Tag) or node.name in SKIP_TAGS:
            return

        name = node.name.lower()
        if name == "pre":
            code_node = node.find("code")
            source = code_node if code_node else node
            code_text = source.get_text("", strip=False)
            add_segment("code", code_text, language=extract_code_language(node))
            return

        if name in HEADING_TAGS:
            heading_text = extract_node_text(
                node,
                base_url=base_url,
                link_references=link_references,
            )
            level = int(name[1])
            heading_path[:] = heading_path[:level - 1]
            heading_path.append(clean_prose_text(heading_text))
            add_segment(
                "heading",
                heading_text,
                source_anchor=str(node.get("id")) if node.get("id") else None,
            )
            return

        if name == "p":
            text_value = extract_node_text(
                node,
                base_url=base_url,
                link_references=link_references,
            )
            add_segment("paragraph", text_value)
            return

        if name == "li":
            text_value = extract_node_text(
                node,
                base_url=base_url,
                link_references=link_references,
                skip_descendants={"ul", "ol", "pre"},
            )
            add_segment("list_item", text_value)
            for child in node.find_all(["ul", "ol", "pre"], recursive=False):
                walk(child)
            return

        if name in {"dt", "dd"}:
            text_value = extract_node_text(
                node,
                base_url=base_url,
                link_references=link_references,
            )
            add_segment("definition_term" if name == "dt" else "definition_description", text_value)
            return

        if name == "tr":
            cells: list[str] = []
            for cell in node.find_all(["th", "td"], recursive=False):
                cells.append(clean_prose_text(extract_node_text(
                    cell,
                    base_url=base_url,
                    link_references=link_references,
                )))
            add_segment("table_row", " | ".join(cell for cell in cells if cell))
            return

        if name == "blockquote":
            text_value = extract_node_text(
                node,
                base_url=base_url,
                link_references=link_references,
                skip_descendants={"pre"},
            )
            add_segment("blockquote", text_value)
            for pre in node.find_all("pre", recursive=True):
                walk(pre)
            return

        if name == "hr":
            return

        if name in BLOCK_CONTAINER_TAGS:
            for child in node.children:
                walk(child)
            return

        # Inline wrappers at the top level are treated as one readable block.
        text_value = extract_node_text(
            node,
            base_url=base_url,
            link_references=link_references,
        )
        add_segment("paragraph", text_value)

    for child in soup.contents:
        walk(child)

    return segments


def segments_to_content(segments: list[dict[str, Any]]) -> str:
    return "\n\n".join(segment["text"] for segment in segments).strip()


def unique_urls(references: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for reference in references:
        url = reference.get("url")
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


def split_links(urls: list[str]) -> tuple[list[str], list[str]]:
    internal: list[str] = []
    external: list[str] = []
    for link in urls:
        hostname = (urlparse(link).hostname or "").lower()
        if hostname == "stackoverflow.com" or hostname.endswith(".stackoverflow.com"):
            internal.append(link)
        else:
            external.append(link)
    return internal, external


def extract_content_and_links(
    body: str,
    *,
    segment_prefix: str = "source",
    base_url: str = "https://stackoverflow.com",
) -> tuple[
    str,
    list[dict[str, Any]],
    list[str],
    list[str],
    list[dict[str, Any]],
]:
    """Return content, reference occurrences, unique internal/external URLs and segments."""
    if not body:
        return "", [], [], [], []

    soup = BeautifulSoup(body, "html.parser")
    link_references: list[dict[str, Any]] = []
    segments = extract_structured_segments(
        soup,
        segment_prefix=segment_prefix,
        base_url=base_url,
        link_references=link_references,
    )

    # Some Stack Overflow bodies consist of inline text without a wrapping p.
    if not segments:
        text_value = clean_prose_text(extract_node_text(
            soup,
            base_url=base_url,
            link_references=link_references,
        ))
        if text_value:
            segments = [{
                "segment_id": f"{segment_prefix}:segment:0000",
                "ordinal": 0,
                "type": "paragraph",
                "text": text_value,
                "heading_path": [],
            }]

    outgoing = unique_urls(link_references)
    internal, external = split_links(outgoing)
    return segments_to_content(segments), link_references, internal, external, segments


# ============================================================================
# 5. QUESTION COLLECTION
# ============================================================================


def category_counts(documents: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for document in documents.values():
        if not eligible_question(document):
            continue
        category = document.get("category", "unknown")
        counts[category] = counts.get(category, 0) + 1
    return counts


def eligible_question(record: dict[str, Any]) -> bool:
    if SCOPE is None:
        return True
    from techsearch.corpus import topic_for_so

    try:
        topic_for_so({**record, "content": record.get("content", record.get("body", ""))}, SCOPE)
        return True
    except ValueError:
        return False


def build_question_document(question: dict[str, Any], category: str) -> dict[str, Any]:
    question_id = str(question["question_id"])
    question_url = question.get("link") or f"https://stackoverflow.com/questions/{question_id}"
    content, link_refs, internal, external, segments = extract_content_and_links(
        question.get("body", ""),
        segment_prefix=f"so:question:{question_id}",
        base_url=question_url,
    )
    owner = question.get("owner") or {}

    return {
        "id": f"so:question:{question_id}",
        "question_id": int(question_id),
        "title": question.get("title", ""),
        "content": content,
        "segments": segments,
        "url": question_url,
        "outgoing_links": unique_urls(link_refs),
        "link_references": link_refs,
        "internal_links": internal,
        "external_links": external,
        "incoming_links": [],
        "incoming_link_references": [],
        "tags": question.get("tags", []),
        "score": question.get("score", 0),
        "view_count": question.get("view_count", 0),
        "answer_count": question.get("answer_count", 0),
        "accepted_answer_id": question.get("accepted_answer_id"),
        "question_author": owner.get("display_name"),
        "question_owner_id": owner.get("user_id"),
        "creation_date": question.get("creation_date"),
        "last_edit_date": question.get("last_edit_date"),
        "last_activity_date": question.get("last_activity_date"),
        "content_license": question.get("content_license"),
        "source": "Stack Overflow",
        "category": category,
        "answers": [],
        "answer_collection": {
            "accepted_answer_status": "pending" if question.get("accepted_answer_id") else "not_available",
            "additional_answers_status": "pending",
        },
    }


def creation_windows() -> list[dict[str, int]]:
    today = int(time.time())
    starts = [1217462400]
    starts.extend(int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
                  for year in range(2010, datetime.now(timezone.utc).year + 1, 2))
    return [{"fromdate": first, "todate": last - 1, "page": 1}
            for first, last in zip(starts, [*starts[1:], today + 1]) if first < last]


def collect_partitioned_questions(state: dict[str, Any], category: str, config: dict[str, Any]) -> None:
    """Fill a short category with disjoint creation-date windows.

    Existing broad-tag checkpoints remain valid. Each window has its own
    page cursor. A capped window is split in half, rather than silently
    treating the category as complete. Replayed pages are deduplicated by ID.
    """
    target = int(config["target"])
    documents = state["documents"]
    count = category_counts(documents).get(category, 0)
    windows = state.setdefault("question_windows", {})
    prefix = "balanced" if TARGET_QUESTIONS > 5000 else "pilot"
    tagged = [(tag, windows.setdefault(f"{prefix}:{category}:{tag}",
               windows.get(f"{category}:{tag}", creation_windows()) if prefix == "pilot" else creation_windows()))
              for tag in config["tags"]]
    while any(queue for _, queue in tagged) and not STOP_COLLECTION and count < target:
        for tag, queue in tagged:
            if not queue or STOP_COLLECTION or count >= target:
                continue
            window = queue[0]
            print(f"  Partition {tag}: page {window['page']} | {count}/{target}")
            result = api_get("questions", {
                "tagged": tag, "sort": "creation" if prefix == "balanced" else "votes", "order": "desc",
                "pagesize": PAGE_SIZE, **window,
            })
            if not result.success:
                print(f"  Partition left pending: {result.error}")
                save_checkpoint(state)
                return
            for question in result.items:
                qid = str(question.get("question_id", ""))
                if qid and qid not in documents and eligible_question(question):
                    if count >= target:
                        # Keep this page pending so a later increased target
                        # does not skip items from the rest of the page.
                        save_checkpoint(state)
                        return
                    documents[qid] = build_question_document(question, category)
                    count += 1
            if count >= target:
                save_checkpoint(state)
                return
            if not result.has_more:
                queue.pop(0)
            elif window["page"] < MAX_API_PAGE:
                queue.append({**queue.pop(0), "page": window["page"] + 1})
            elif window["fromdate"] < window["todate"]:
                midpoint = (window["fromdate"] + window["todate"]) // 2
                queue[:1] = [
                    {"fromdate": midpoint + 1, "todate": window["todate"], "page": 1},
                    {"fromdate": window["fromdate"], "todate": midpoint, "page": 1},
                ]
            else:
                state.setdefault("question_shortfalls", []).append({"tag": tag, "window": queue.pop(0), "reason": "pagination cap in indivisible window"})
            save_checkpoint(state)
            time.sleep(REQUEST_DELAY_SECONDS)


def collect_questions(state: dict[str, Any]) -> None:
    documents = state["documents"]
    print("\n========== QUESTION COLLECTION ==========")

    for category, config in TOPIC_CONFIG.items():
        if STOP_COLLECTION:
            break

        target = int(config["target"])
        current_count = category_counts(documents).get(category, 0)
        print(f"\nCategory: {category} ({current_count}/{target})")
        if current_count >= target:
            print("Target already reached. Skipping.")
            continue

        for tag in config["tags"] if TARGET_QUESTIONS == 5000 else ():
            if STOP_COLLECTION or current_count >= target:
                break
            if state["tag_complete"].get(tag):
                continue
            if state["tag_page_limit_reached"].get(tag):
                print(f"Tag {tag} reached the API's 25-page limit; use a narrower time/topic partition to extend it.")
                continue

            page = int(state["tag_pages"].get(tag, 0)) + 1
            print(f"\nSearching tag: {tag} (resume at page {page})")
            if page > MAX_API_PAGE:
                state["tag_page_limit_reached"][tag] = True
                save_checkpoint(state)
                continue

            while page <= MAX_API_PAGE and not STOP_COLLECTION:
                if current_count >= target:
                    break

                print(f"  Page {page} | {current_count}/{target}")
                result = api_get(
                    "questions",
                    {
                        "tagged": tag,
                        "page": page,
                        "pagesize": PAGE_SIZE,
                        "order": "desc",
                        "sort": "votes",
                    },
                )

                if not result.success:
                    print(f"  Question request failed; page not checkpointed: {result.error}")
                    save_checkpoint(state)
                    return

                added = 0
                for question in result.items:
                    question_id = str(question.get("question_id", ""))
                    if not question_id or question_id in documents or not eligible_question(question):
                        continue
                    if current_count >= target:
                        break
                    documents[question_id] = build_question_document(question, category)
                    added += 1
                    current_count += 1

                print(f"  New questions added: {added}")
                if current_count < target:
                    state["tag_pages"][tag] = page
                save_checkpoint(state)
                if current_count >= target:
                    break

                if not result.has_more:
                    state["tag_complete"][tag] = True
                    save_checkpoint(state)
                    break

                if page >= MAX_API_PAGE:
                    state["tag_page_limit_reached"][tag] = True
                    save_checkpoint(state)
                    print(f"  Reached Stack Exchange's maximum page number ({MAX_API_PAGE}) for tag {tag}.")
                    break

                page += 1
                time.sleep(REQUEST_DELAY_SECONDS)

        if current_count < target and not STOP_COLLECTION:
            collect_partitioned_questions(state, category, config)
        current_count = category_counts(documents).get(category, 0)
        print(f"Completed {category}: {current_count}/{target}")
        save_checkpoint(state)

    print("\nQuestion collection stage finished.")
    save_checkpoint(state)


# ============================================================================
# 6. ANSWER COLLECTION
# ============================================================================


def add_answers_to_documents(
    documents: dict[str, dict[str, Any]],
    answers: list[dict[str, Any]],
) -> int:
    added = 0
    for answer in answers:
        question_id = str(answer.get("question_id", ""))
        if question_id not in documents:
            continue

        document = documents[question_id]
        answer_id = answer.get("answer_id")
        if answer_id is None:
            continue

        answer_id = int(answer_id)
        existing_ids = {
            int(item["answer_id"])
            for item in document.setdefault("answers", [])
            if item.get("answer_id") is not None
        }
        if answer_id in existing_ids:
            continue

        answer_url = f"https://stackoverflow.com/a/{answer_id}"
        content, link_refs, internal, external, segments = extract_content_and_links(
            answer.get("body", ""),
            segment_prefix=f"so:answer:{answer_id}",
            base_url=answer_url,
        )
        owner = answer.get("owner") or {}
        answer_document = {
            "answer_id": answer_id,
            "content": content,
            "segments": segments,
            "url": answer_url,
            "outgoing_links": unique_urls(link_refs),
            "link_references": link_refs,
            "internal_links": internal,
            "external_links": external,
            "score": answer.get("score", 0),
            "is_accepted": bool(answer.get("is_accepted", False)),
            "author": owner.get("display_name"),
            "owner_id": owner.get("user_id"),
            "creation_date": answer.get("creation_date"),
            "last_edit_date": answer.get("last_edit_date"),
            "last_activity_date": answer.get("last_activity_date"),
            "content_license": answer.get("content_license"),
        }
        document["answers"].append(answer_document)
        added += 1

    return added


def mark_answer_error(state: dict[str, Any], key: str, error: str) -> None:
    state["answer_request_errors"][key] = {
        "error": error,
        "last_attempt_unix": int(time.time()),
    }


def clear_answer_error(state: dict[str, Any], key: str) -> None:
    state["answer_request_errors"].pop(key, None)


def collect_accepted_answers(state: dict[str, Any]) -> None:
    documents = state["documents"]
    accepted_ids = sorted({
        str(document["accepted_answer_id"])
        for document in documents.values()
        if document.get("accepted_answer_id") is not None
    }, key=lambda value: int(value))

    completed = set(state["accepted_answer_ids_done"])
    missing = set(state["accepted_answers_missing"])
    pending = [answer_id for answer_id in accepted_ids if answer_id not in completed]

    print(f"\nAccepted answer IDs: {len(accepted_ids)} ({len(pending)} still to verify)")

    for batch in chunks(pending, 100):
        if STOP_COLLECTION:
            break

        requested_ids = [str(value) for value in batch]
        endpoint_ids = ";".join(requested_ids)
        page = 1
        batch_answers: list[dict[str, Any]] = []
        batch_complete = False
        error_key = "accepted:" + ",".join(requested_ids)

        while not STOP_COLLECTION:
            result = api_get(
                f"answers/{endpoint_ids}",
                {
                    "page": page,
                    "pagesize": 100,
                    "order": "desc",
                    "sort": "votes",
                },
            )
            if not result.success:
                mark_answer_error(state, error_key, result.error or "Unknown API error")
                print(f"Accepted answer request failed; IDs remain pending: {result.error}")
                save_checkpoint(state)
                break

            batch_answers.extend(result.items)
            if not result.has_more:
                batch_complete = True
                break
            page += 1
            time.sleep(REQUEST_DELAY_SECONDS)

        if batch_answers:
            added = add_answers_to_documents(documents, batch_answers)
            print(f"Accepted lookup: {added} answers added from {len(requested_ids)} requested IDs.")

        if batch_complete:
            returned_ids = {
                str(answer.get("answer_id"))
                for answer in batch_answers
                if answer.get("answer_id") is not None
            }
            completed.update(requested_ids)
            missing.update(answer_id for answer_id in requested_ids if answer_id not in returned_ids)
            state["accepted_answer_ids_done"] = sorted(completed, key=lambda value: int(value))
            state["accepted_answers_missing"] = sorted(missing, key=lambda value: int(value))
            clear_answer_error(state, error_key)
            save_checkpoint(state)
        else:
            # A successful page with has_more=True is still an incomplete
            # lookup if quota stopped the next page. Leave IDs pending.
            save_checkpoint(state)

        if STOP_COLLECTION:
            break
        time.sleep(REQUEST_DELAY_SECONDS)


def collect_additional_answers(state: dict[str, Any]) -> None:
    documents = state["documents"]
    completed_questions = set(state["supplement_question_ids_done"])
    question_ids = sorted(documents.keys(), key=lambda value: int(value))
    pending_ids = [question_id for question_id in question_ids if question_id not in completed_questions]

    print(f"\nCollecting additional answers per question: {len(pending_ids)} questions pending.")

    for index, question_id in enumerate(pending_ids, start=1):
        if STOP_COLLECTION:
            break

        document = documents[question_id]
        request_key = f"supplement:{question_id}"
        result = api_get(
            f"questions/{question_id}/answers",
            {
                "page": 1,
                "pagesize": MAX_ANSWERS_PER_QUESTION,
                "order": "desc",
                "sort": "votes",
            },
        )

        if not result.success:
            mark_answer_error(state, request_key, result.error or "Unknown API error")
            document.setdefault("answer_collection", {})["additional_answers_status"] = "pending"
            print(f"  [{index}/{len(pending_ids)}] Question {question_id}: failed; left pending ({result.error}).")
            save_checkpoint(state)
            # api_get has already exhausted its retry budget. Avoid issuing
            # thousands of identical failing requests during an outage.
            print("  Answer collection paused after request failure; rerun to resume.")
            break

        added = add_answers_to_documents(documents, result.items)
        # The endpoint sorts this question's own answers. We intentionally
        # request only the top N candidates needed by the selection policy.
        completed_questions.add(question_id)
        state["supplement_question_ids_done"] = sorted(
            completed_questions,
            key=lambda value: int(value),
        )
        document.setdefault("answer_collection", {})["additional_answers_status"] = "complete"
        document["answer_collection"]["additional_answers_page_has_more"] = result.has_more
        clear_answer_error(state, request_key)
        if index % 25 == 0 or index == len(pending_ids) or STOP_COLLECTION:
            save_checkpoint(state)

        if index % 25 == 0 or index == len(pending_ids):
            print(f"  [{index}/{len(pending_ids)}] Latest question {question_id}: {added} answers added.")
        time.sleep(REQUEST_DELAY_SECONDS)


def select_answers(
    documents: dict[str, dict[str, Any]],
    missing_accepted_ids: set[str] | None = None,
) -> None:
    """Keep accepted answer plus the highest-scoring distinct alternatives."""
    missing_accepted_ids = missing_accepted_ids or set()
    for question_id, document in documents.items():
        answers = document.get("answers", [])
        answers.sort(
            key=lambda item: (
                bool(item.get("is_accepted")),
                int(item.get("score", 0) or 0),
                int(item.get("answer_id", 0) or 0),
            ),
            reverse=True,
        )
        document["answers"] = answers[:MAX_ANSWERS_PER_QUESTION]

        accepted_id = document.get("accepted_answer_id")
        answer_ids = {str(answer.get("answer_id")) for answer in document["answers"]}
        status = document.setdefault("answer_collection", {})
        if accepted_id is None:
            status["accepted_answer_status"] = "not_available"
        elif str(accepted_id) in answer_ids:
            status["accepted_answer_status"] = "collected"
        elif str(accepted_id) in missing_accepted_ids:
            status["accepted_answer_status"] = "not_returned_by_api"
        else:
            status["accepted_answer_status"] = "pending"


def collect_answers(state: dict[str, Any]) -> None:
    print("\n========== ANSWER COLLECTION ==========")
    collect_accepted_answers(state)
    if not STOP_COLLECTION:
        collect_additional_answers(state)

    select_answers(
        state["documents"],
        missing_accepted_ids=set(state["accepted_answers_missing"]),
    )
    save_checkpoint(state)
    print("\nAnswer collection stage finished.")


# ============================================================================
# 7. INCOMING LINK REFERENCES AND PARENT-LEVEL GRAPH
# ============================================================================


def resolve_link_target(
    normalized_url: str,
    question_url_map: dict[str, str],
    answer_url_map: dict[str, str],
    documents: dict[str, dict[str, Any]],
) -> str | None:
    if normalized_url in question_url_map:
        return question_url_map[normalized_url]
    if normalized_url in answer_url_map:
        return answer_url_map[normalized_url]

    parsed = urlparse(normalized_url)
    path = parsed.path
    patterns = (
        r"/questions/(\d+)(?:/|$)",
        r"/q/(\d+)(?:/|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, path)
        if match and match.group(1) in documents:
            return match.group(1)

    answer_match = re.search(r"/a/(\d+)(?:/|$)", path)
    if answer_match:
        answer_id = answer_match.group(1)
        return answer_url_map.get(
            normalize_url(f"https://stackoverflow.com/a/{answer_id}") or ""
        )
    return None


def derive_incoming_links(documents: dict[str, dict[str, Any]]) -> int:
    """Build unique parent edges while retaining every source reference."""
    print("\n========== INCOMING LINK DERIVATION ==========")

    question_url_map: dict[str, str] = {}
    answer_url_map: dict[str, str] = {}

    for question_id, document in documents.items():
        question_url = normalize_url(document.get("url", ""))
        if question_url:
            question_url_map[question_url] = question_id

        # Accepted answers are mapped even if the API did not return their
        # body, allowing /a/{id} references to resolve to the parent thread.
        accepted_id = document.get("accepted_answer_id")
        if accepted_id is not None:
            accepted_url = normalize_url(f"https://stackoverflow.com/a/{accepted_id}")
            if accepted_url:
                answer_url_map[accepted_url] = question_id

        for answer in document.get("answers", []):
            answer_id = answer.get("answer_id")
            if answer_id is not None:
                answer_url = normalize_url(f"https://stackoverflow.com/a/{answer_id}")
                if answer_url:
                    answer_url_map[answer_url] = question_id

    for document in documents.values():
        document["incoming_links"] = []
        document["incoming_link_references"] = []

    edge_count = 0
    reference_count = 0

    for source_question_id, source_document in documents.items():
        source_entities: list[tuple[str, int | None, list[dict[str, Any]]]] = [
            ("question", None, source_document.get("link_references", [])),
        ]
        for answer in source_document.get("answers", []):
            source_entities.append((
                "answer",
                answer.get("answer_id"),
                answer.get("link_references", []),
            ))

        # A set local to this source thread prevents duplicate parent edges,
        # but reference records below remain occurrence-level and are kept.
        source_targets_seen: set[str] = set()

        for source_type, source_answer_id, references in source_entities:
            for reference in references:
                link = reference.get("url")
                normalized = normalize_url(link)
                if not normalized:
                    continue

                target_question_id = resolve_link_target(
                    normalized,
                    question_url_map,
                    answer_url_map,
                    documents,
                )
                if not target_question_id:
                    continue

                # Self-edges are excluded from the initial parent graph.
                if target_question_id == source_question_id:
                    continue

                target_document = documents[target_question_id]
                reference_record = {
                    "source_question_id": int(source_question_id),
                    "source_type": source_type,
                    "source_answer_id": source_answer_id,
                    "source_url": source_document.get("url", ""),
                    "target_url": normalized,
                    "anchor_text": reference.get("anchor_text", ""),
                }
                target_document["incoming_link_references"].append(reference_record)
                reference_count += 1

                if target_question_id not in source_targets_seen:
                    source_targets_seen.add(target_question_id)
                    target_document["incoming_links"].append({
                        "source_question_id": int(source_question_id),
                        "source_url": source_document.get("url", ""),
                        "reference_count": 0,
                        "source_types": [],
                        "source_answer_ids": [],
                    })
                    edge_count += 1

                edge = next(
                    item for item in target_document["incoming_links"]
                    if item["source_question_id"] == int(source_question_id)
                )
                edge["reference_count"] += 1
                if source_type not in edge["source_types"]:
                    edge["source_types"].append(source_type)
                if source_answer_id is not None and source_answer_id not in edge["source_answer_ids"]:
                    edge["source_answer_ids"].append(source_answer_id)

    print(f"Unique parent-level incoming edges: {edge_count}")
    print(f"Preserved incoming reference occurrences: {reference_count}")
    return edge_count


# ============================================================================
# 8. OUTPUT AND SUMMARY
# ============================================================================


def save_final_dataset(documents: dict[str, dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = list(documents.values())
    temporary_file = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")
    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temporary_file.replace(OUTPUT_FILE)
    print("\nFinal dataset saved:")
    print(OUTPUT_FILE)


def print_summary(documents: dict[str, dict[str, Any]], state: dict[str, Any]) -> None:
    counts = category_counts(documents)
    total_answers = sum(len(document.get("answers", [])) for document in documents.values())
    questions_with_answers = sum(bool(document.get("answers")) for document in documents.values())
    accepted_collected = sum(
        1
        for document in documents.values()
        for answer in document.get("answers", [])
        if answer.get("is_accepted")
    )
    question_refs = sum(len(document.get("link_references", [])) for document in documents.values())
    answer_refs = sum(
        len(answer.get("link_references", []))
        for document in documents.values()
        for answer in document.get("answers", [])
    )
    incoming_edges = sum(len(document.get("incoming_links", [])) for document in documents.values())
    incoming_refs = sum(len(document.get("incoming_link_references", [])) for document in documents.values())
    completed_supplements = set(state.get("supplement_question_ids_done", []))
    pending_supplements = sum(1 for question_id in documents if question_id not in completed_supplements)

    print("\n" + "=" * 56)
    print("       STACK OVERFLOW COLLECTION SUMMARY")
    print("=" * 56)
    print(f"Total questions: {len(documents)}")
    print(f"Pilot question target: {TARGET_QUESTIONS}")
    print(f"Total selected answers: {total_answers}")
    print(f"Questions with answers: {questions_with_answers}")
    print(f"Accepted answers collected: {accepted_collected}")
    print(f"Questions with answer supplementation pending: {pending_supplements}")
    print(f"Question link-reference occurrences: {question_refs}")
    print(f"Answer link-reference occurrences: {answer_refs}")
    print(f"Unique incoming parent edges: {incoming_edges}")
    print(f"Incoming reference occurrences: {incoming_refs}")
    print(f"API requests made: {API_REQUESTS}")
    print(f"Remaining API quota: {REMAINING_QUOTA}")
    print("\nCATEGORY DISTRIBUTION")
    for category, config in TOPIC_CONFIG.items():
        print(f"{category:<20} {counts.get(category, 0):>5}/{config['target']}")
    print("=" * 56)
    if len(documents) >= TARGET_QUESTIONS:
        print("Pilot question target reached. Coverage still requires the project-plan audit.")
    else:
        print("Pilot target not yet reached; progress is checkpointed.")
        if STOP_COLLECTION:
            print("Collection paused because the API quota is low.")
        print("Collection paused. Check API connectivity/quota, then rerun; ID-based checkpoints resume work.")


def main() -> None:
    global STOP_COLLECTION, TARGET_QUESTIONS, SCOPE

    print("=" * 56)
    print("TECHSEARCH - STACK OVERFLOW DATA COLLECTION")
    print("=" * 56)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not API_KEY:
        print("\nERROR: Stack Exchange API key not found.")
        print("Set STACKEXCHANGE_API_KEY in the project-root .env file or environment.")
        raise SystemExit(2)

    from techsearch.config import load_settings

    SCOPE = load_settings(PROJECT_DIR).scope
    stage = int(os.getenv("TECHSEARCH_SO_TARGET", "5000"))
    if stage not in SCOPE["so_targets"]:
        raise ValueError("Unsupported Stack Overflow acquisition stage.")
    for category in TOPIC_CONFIG.values():
        category["target"] = category["target"] * stage // 5000
    TARGET_QUESTIONS = stage

    print("\nAPI key detected. It will not be displayed.")
    state = load_checkpoint()
    documents = state["documents"]

    try:
        collect_questions(state)
        if not STOP_COLLECTION:
            collect_answers(state)

        derive_incoming_links(documents)
        save_checkpoint(state)
        save_final_dataset(documents)
        print_summary(documents, state)
    except KeyboardInterrupt:
        print("\nInterrupted; saving current progress...")
        save_checkpoint(state)
        print("Checkpoint saved. Run the same command to resume.")
        raise SystemExit(130)
    finally:
        session.close()


if __name__ == "__main__":
    main()
