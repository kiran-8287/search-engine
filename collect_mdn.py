#!/usr/bin/env python3
"""Collect the scoped English MDN corpus for TechSearch.

MDN Markdown is parsed before HTML/text extraction. Markdown code fences remain
code tokens, MDN reference macros retain their visible labels, supported
reference macros become resolvable links, and all output text is stored as
ordered section-aware segments rather than a whitespace-flattened string.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urljoin, urlparse, urlunparse, urldefrag
from urllib.request import urlretrieve

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

try:
    from markdown_it import MarkdownIt
except ImportError as error:  # Fail clearly instead of silently falling back to unsafe parsing.
    raise RuntimeError(
        "MDN collection requires markdown-it-py. Install it with: "
        "python -m pip install markdown-it-py"
    ) from error


# ============================================================================
# 1. CONFIGURATION
# ============================================================================

def archive_filesystem_path(path: Path) -> Path:
    """Use extended-length paths for deep MDN archive directories on Windows."""
    if os.name != "nt":
        return path
    absolute = os.path.normpath(path.absolute())
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = Path(
    os.getenv("TECHSEARCH_PROJECT_DIR", str(SCRIPT_DIR))
).resolve()

DATA_DIR = Path(os.getenv("TECHSEARCH_DATA_DIR", str(PROJECT_DIR / "data")))
REVISION = os.getenv("TECHSEARCH_MDN_REVISION")
if REVISION and not re.fullmatch(r"[a-f0-9]{40}", REVISION):
    raise ValueError("TECHSEARCH_MDN_REVISION must be a full commit SHA")
MDN_ZIP_URL = f"https://github.com/mdn/content/archive/{REVISION}.zip" if REVISION else None
DOWNLOAD_DIR = DATA_DIR / "downloads"
if REVISION:
    DOWNLOAD_DIR = DOWNLOAD_DIR / "mdn" / REVISION
DOWNLOAD_DIR = archive_filesystem_path(DOWNLOAD_DIR)
RAW_DIR = DATA_DIR / "raw"
ZIP_PATH = DOWNLOAD_DIR / "mdn_content.zip"
EXTRACT_DIR = DOWNLOAD_DIR / "mdn_content"
OUTPUT_FILE = RAW_DIR / "mdn_documents.json"
SOURCE_URL_MAP_FILE = RAW_DIR / "mdn_source_path_to_url.json"
COLLECTION_REPORT_FILE = RAW_DIR / "mdn_collection_report.json"

MDN_ORIGIN = "https://developer.mozilla.org"
MDN_DOCS_PREFIX = f"{MDN_ORIGIN}/en-US/docs/"

# These are inclusion roots, not numerical quotas. The project specification
# calls for every usable English page in the scoped families, not a 5,000-page
# random sample.
TOPIC_PATHS = (
    "web/api",
    "web/javascript",
    "web/css",
    "web/html",
    "web/http",
    "learn_web_development",
    "glossary",
    "web/accessibility",
    "web/security",
    "web/performance",
    "web/progressive_web_apps",
)
if os.getenv("TECHSEARCH_MDN_TOPIC_PATHS"):
    configured_roots = json.loads(os.environ["TECHSEARCH_MDN_TOPIC_PATHS"])
    if not isinstance(configured_roots, list) or any(
        not isinstance(root, str) or not re.fullmatch(r"[a-z0-9_/-]+", root) or root.startswith("/")
        or ".." in PurePosixPath(root).parts for root in configured_roots
    ):
        raise ValueError("Invalid configured MDN source roots.")
    TOPIC_PATHS = tuple(configured_roots)
if REVISION:
    scope_key = hashlib.sha256("\n".join(sorted(TOPIC_PATHS)).encode("utf-8")).hexdigest()[:12]
    EXTRACT_DIR = DOWNLOAD_DIR / f"mdn-source-{scope_key}"

SKIP_HTML_TAGS = {"script", "style", "noscript", "template"}
BLOCK_CONTAINER_TAGS = {
    "article", "body", "div", "dl", "fieldset", "footer", "form",
    "main", "ol", "section", "table", "tbody", "thead", "tfoot", "ul",
}
HEADING_TAGS = {f"h{level}" for level in range(1, 7)}

SOURCE_PATH_URL_MAP: dict[str, str] = {}
COLLECTION_DIAGNOSTICS: dict[str, Any] = {
    "files_discovered": 0,
    "documents_parsed": 0,
    "duplicate_source_paths": [],
    "duplicate_canonical_urls": [],
    "parse_errors": [],
    "unresolved_macro_count": 0,
    "unresolved_macro_examples": [],
    "topics": {},
}


# ============================================================================
# 2. DOWNLOAD AND SAFE EXTRACTION
# ============================================================================


def ensure_directories() -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def download_mdn() -> None:
    ensure_directories()
    if ZIP_PATH.exists() and ZIP_PATH.stat().st_size > 0:
        print("MDN ZIP already downloaded.")
        return
    if not MDN_ZIP_URL:
        raise RuntimeError("Acquire new content with python -m techsearch collect --source mdn to resolve a commit.")

    print("Downloading MDN content repository...")
    temporary_zip = ZIP_PATH.with_suffix(".zip.part")
    try:
        urlretrieve(MDN_ZIP_URL, temporary_zip)
        if not temporary_zip.exists() or temporary_zip.stat().st_size == 0:
            raise RuntimeError("The downloaded MDN archive is empty.")
        temporary_zip.replace(ZIP_PATH)
    finally:
        temporary_zip.unlink(missing_ok=True)
    print("MDN download completed.")


def is_scoped_source_member(path: PurePosixPath) -> bool:
    parts = path.parts
    if parts[:2] != ("files", "en-us"):
        parts = parts[1:]
    if parts[:2] != ("files", "en-us"):
        return False
    source_path = "/".join(parts[2:])
    return source_path == "_redirects.txt" or (
        path.name == "index.md" and any(
            source_path.startswith(root.rstrip("/") + "/") for root in TOPIC_PATHS
        )
    )


def safe_extract_zip(zip_path: Path, destination: Path, *, scoped: bool = False) -> None:
    """Validate archive paths and optionally extract only configured English sources."""
    destination = archive_filesystem_path(destination)
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive_filesystem_path(zip_path), "r") as archive:
        selected = []
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise RuntimeError(f"Unsafe path in MDN archive: {member.filename}")
            if scoped and not is_scoped_source_member(path):
                continue
            member_path = (destination / member.filename).resolve()
            try:
                member_path.relative_to(destination_resolved)
            except ValueError as error:
                raise RuntimeError(
                    f"Unsafe path in MDN archive: {member.filename}"
                ) from error
            selected.append(member)
        archive.extractall(destination, members=selected)


def get_mdn_content_root(base: Path | None = None) -> Path | None:
    """Locate the MDN English content directory in common ZIP layouts."""
    base = EXTRACT_DIR if base is None else base
    candidates = [
        base / "files" / "en-us",
        *base.glob("*/files/en-us"),
    ]

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    return None


def extract_mdn() -> None:
    expected_folder = get_mdn_content_root()
    if expected_folder is not None:
        if REVISION:
            stamp = EXTRACT_DIR / ".archive-sha256"
            with ZIP_PATH.open("rb") as archive:
                checksum = hashlib.file_digest(archive, "sha256").hexdigest()
            if not stamp.is_file() or stamp.read_text(encoding="utf-8").strip() != checksum:
                raise ValueError("Existing pinned extraction has conflicting provenance. Preserve it and select a new data directory.")
        print(f"MDN files already extracted: {expected_folder}")
        return

    if not ZIP_PATH.exists():
        raise FileNotFoundError(f"MDN archive not found: {ZIP_PATH}")

    print("Extracting MDN repository...")
    if EXTRACT_DIR.exists():
        raise ValueError(f"An existing extraction at {EXTRACT_DIR} is incomplete. Preserve it and select a new data directory.")
    with tempfile.TemporaryDirectory(prefix=".mdn-extract-", dir=DOWNLOAD_DIR) as temporary:
        destination = Path(temporary) / "content"
        safe_extract_zip(ZIP_PATH, destination, scoped=bool(REVISION))
        expected_folder = get_mdn_content_root(destination)
        if expected_folder is None or (REVISION and not expected_folder.parent.parent.name.endswith(REVISION)):
            raise ValueError("Archive layout does not contain the expected MDN English snapshot.")
        relative = expected_folder.relative_to(destination)
        if REVISION:
            with ZIP_PATH.open("rb") as archive:
                checksum = hashlib.file_digest(archive, "sha256").hexdigest()
            (destination / ".archive-sha256").write_text(checksum + "\n", encoding="utf-8")
        destination.rename(EXTRACT_DIR)
        expected_folder = EXTRACT_DIR / relative

    print(f"MDN extraction completed: {expected_folder}")


# ============================================================================
# 3. FRONT MATTER AND CANONICAL URLS
# ============================================================================


def split_front_matter(raw_text: str) -> tuple[dict[str, Any], str]:
    raw_text = raw_text.lstrip("\ufeff")
    match = re.match(
        r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)(.*)\Z",
        raw_text,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError("Markdown file is missing valid YAML front matter.")

    metadata_value = yaml.safe_load(match.group(1))
    if not isinstance(metadata_value, dict):
        raise ValueError("YAML front matter must be a mapping.")
    return metadata_value, match.group(2)


def slug_from_front_matter(
    metadata: dict[str, Any],
    relative_path: Path,
) -> str:
    """Prefer MDN's canonical front-matter slug and preserve its casing."""
    slug_value = metadata.get("slug")
    if isinstance(slug_value, str) and slug_value.strip():
        slug = slug_value.strip()
        parsed = urlparse(slug)
        if parsed.scheme in ("http", "https"):
            path = parsed.path
            docs_marker = "/en-US/docs/"
            if docs_marker in path:
                return path.split(docs_marker, 1)[1].strip("/")
            return path.strip("/")
        if "/en-US/docs/" in slug:
            slug = slug.split("/en-US/docs/", 1)[1]
        elif slug.startswith("/docs/"):
            slug = slug[len("/docs/"):]
        elif slug.startswith("docs/"):
            slug = slug[len("docs/"):]
        return slug.strip("/")

    # This fallback preserves source-path spelling. It is deliberately used
    # only when the authoritative front-matter slug is absent.
    return relative_path.parent.as_posix().strip("/")


def canonical_url_from_slug(slug: str) -> str:
    encoded_path = "/".join(
        quote(part, safe="-._~:@!$&'()*+,;=%")
        for part in slug.strip("/").split("/")
        if part
    )
    return MDN_DOCS_PREFIX + encoded_path


def normalize_source_link(url: str | None, page_url: str) -> str | None:
    if not url:
        return None
    try:
        candidate = urljoin(page_url, url.strip())
        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return None
        hostname = parsed.hostname.lower()
        netloc = f"[{hostname}]" if ":" in hostname else hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        scheme = "https" if hostname == "developer.mozilla.org" else parsed.scheme
        return urlunparse((scheme, netloc, parsed.path, "", parsed.query, parsed.fragment))
    except (TypeError, ValueError):
        return None


# ============================================================================
# 4. MDN MACRO PARSING AND RESOLUTION
# ============================================================================


def split_macro_arguments(argument_text: str) -> list[str]:
    """Split macro arguments without splitting commas inside strings/calls."""
    values: list[str] = []
    buffer: list[str] = []
    quote_char: str | None = None
    escaped = False
    depth = 0

    for character in argument_text:
        if escaped:
            buffer.append(character)
            escaped = False
            continue
        if character == "\\" and quote_char:
            buffer.append(character)
            escaped = True
            continue
        if quote_char:
            buffer.append(character)
            if character == quote_char:
                quote_char = None
            continue
        if character in ("\"", "'"):
            quote_char = character
            buffer.append(character)
        elif character in "([{":
            depth += 1
            buffer.append(character)
        elif character in ")]}":
            depth = max(0, depth - 1)
            buffer.append(character)
        elif character == "," and depth == 0:
            values.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(character)

    if buffer or argument_text.strip():
        values.append("".join(buffer).strip())
    return values


def unquote_macro_argument(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
        inner = value[1:-1]
        return re.sub(r"\\([\\'\"])", r"\1", inner)
    return value


def parse_macro_body(body: str) -> tuple[str, list[str]] | None:
    match = re.match(
        r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*(?:\((.*)\))?\s*$",
        body,
        flags=re.DOTALL,
    )
    if not match:
        return None
    name = match.group(1)
    raw_args = match.group(2)
    if raw_args is None:
        return name, []
    return name, [unquote_macro_argument(value) for value in split_macro_arguments(raw_args)]


def find_macro_end(text: str, start: int) -> int | None:
    """Find the closing braces while respecting quoted strings and nesting."""
    depth = 1
    index = start + 2
    quote_char: str | None = None
    escaped = False

    while index < len(text) - 1:
        character = text[index]
        pair = text[index:index + 2]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote_char:
            escaped = True
            index += 1
            continue
        if quote_char:
            if character == quote_char:
                quote_char = None
            index += 1
            continue
        if character in ("\"", "'"):
            quote_char = character
            index += 1
            continue
        if pair == "{{":
            depth += 1
            index += 2
            continue
        if pair == "}}":
            depth -= 1
            if depth == 0:
                return index + 2
            index += 2
            continue
        index += 1
    return None


def append_macro_anchor(url: str, args: list[str]) -> str:
    """Append an embedded or explicit anchor used by reference macros."""
    embedded = None
    if args and "#" in args[0]:
        base, fragment = args[0].split("#", 1)
        args[0] = base
        embedded = fragment
    explicit = args[2].strip() if len(args) > 2 else ""
    fragment = embedded or explicit.lstrip("#")
    return f"{url}#{fragment}" if fragment else url


def macro_target(macro_name: str, args: list[str]) -> tuple[str, str | None]:
    """Resolve common MDN rari reference macros to canonical page URLs.

    The MDN build system has page indexes for DOM, JavaScript and CSS names.
    This offline collector applies the documented URL conventions and
    conservative name normalization; any unsupported macro is still rendered
    as a visible label and recorded in ``unresolved_macros``.
    """
    normalized = re.sub(r"[^a-z0-9]", "", macro_name.casefold())
    first = args[0].strip() if args else ""
    second = args[1].strip() if len(args) > 1 else ""

    # For htmlattrxref, arg 2 is the associated element/global-attribute
    # context, not a custom display label.
    label = first if normalized == "htmlattrxref" else (second or first)

    non_link_labels = {
        "compat": "Browser compatibility information",
        "specifications": "Specifications",
        "seecompattable": "Experimental feature; check browser compatibility",
        "optionalinline": "Optional",
        "readonlyinline": "Read only",
        "nonstandardinline": "Non-standard",
        "experimentalinline": "Experimental",
        "deprecatedinline": "Deprecated",
        "nonstandardheader": "Non-standard",
        "experimentalheader": "Experimental",
        "deprecatedheader": "Deprecated",
        "securecontextheader": "Secure context required",
        "securecontextinline": "Secure context required",
        "availableinworkers": "Available in workers",
        "embedlivesample": "Interactive example",
        "embedghlivesample": "Interactive example",
        "livesamplelink": "View live sample",
        "inheritancediagram": "Inheritance diagram",
        "previous": "Previous page",
        "next": "Next page",
        "previousnext": "Previous and next pages",
        "apiref": "API reference",
    }
    if normalized in non_link_labels:
        return non_link_labels[normalized], None

    if not label:
        label = re.sub(r"([a-z])([A-Z])", r"\1 \2", macro_name).replace("_", " ")

    if normalized == "glossary" and first:
        return label, append_macro_anchor(canonical_url_from_slug(f"Glossary/{first}"), args)

    if normalized in {"domxref", "event"} and first:
        # rari normalizes `()` and prototype notation, then resolves dotted
        # API names as nested Web/API pages. The alias map handles common
        # browser-global roots when the offline API-name index is unavailable.
        api_name = first.split("#", 1)[0]
        api_name = api_name.replace(" ", "_").replace("()", "")
        api_name = api_name.replace(".prototype.", ".")
        known_globals = {
            "document": "Document",
            "window": "Window",
            "navigator": "Navigator",
            "location": "Location",
            "history": "History",
            "console": "Console",
            "screen": "Screen",
            "performance": "Performance",
            "crypto": "Crypto",
            "customElements": "CustomElementRegistry",
            "localStorage": "Storage",
            "sessionStorage": "Storage",
        }
        if "/" in api_name:
            api_path = api_name
        elif "." in api_name:
            root, remainder = api_name.split(".", 1)
            root = known_globals.get(root, root)
            api_path = root + "/" + remainder.replace(".", "/")
        else:
            api_path = known_globals.get(api_name, api_name)
        url = canonical_url_from_slug(f"Web/API/{api_path}")
        return label, append_macro_anchor(url, args)

    if normalized in {"jsxref", "jsxsref"} and first:
        js_name = first.split("#", 1)[0]
        js_name = js_name.replace("()", "").replace(".prototype.", ".")
        if "/" in js_name:
            js_path = js_name
        elif "." in js_name:
            js_path = "Global_Objects/" + js_name.replace(".", "/")
        elif js_name in {
            "typeof", "instanceof", "new", "delete", "void", "in", "yield",
            "async_function", "await", "super", "this",
        }:
            js_path = "Operators/" + js_name
        elif js_name in {
            "if...else", "for", "for...in", "for...of", "while", "do...while",
            "try...catch", "switch", "break", "continue", "return", "throw",
            "const", "let", "var", "function", "class", "import", "export",
        }:
            js_path = "Statements/" + js_name
        else:
            js_path = "Global_Objects/" + js_name
        url = canonical_url_from_slug(f"Web/JavaScript/Reference/{js_path}")
        return label, append_macro_anchor(url, args)

    if normalized == "cssxref" and first:
        css_name = first.split("#", 1)[0]
        css_name = css_name.replace("&lt;", "<").replace("&gt;", ">")
        if css_name.startswith("<") and css_name.endswith(">"):
            css_slug = css_name[1:-1] + "_value"
            css_path = f"Web/CSS/Reference/Values/{css_slug}"
        elif css_name.startswith(":"):
            css_path = f"Web/CSS/Reference/Selectors/{css_name}"
        elif css_name.startswith("@"):
            css_path = f"Web/CSS/Reference/At-rules/{css_name}"
        elif css_name.endswith("()"):
            css_path = f"Web/CSS/Reference/Values/{css_name[:-2]}_function"
        else:
            css_path = f"Web/CSS/Reference/Properties/{css_name}"
        return label, append_macro_anchor(canonical_url_from_slug(css_path), args)

    if normalized in {"htmlelement", "htmlmlelement"} and first:
        if not second:
            label = f"<{first}>"
        url = canonical_url_from_slug(f"Web/HTML/Reference/Elements/{first}")
        return label, append_macro_anchor(url, args)

    if normalized == "htmlattrxref" and first:
        context = second.strip(" /")
        if context.casefold() in {"global_attributes", "global attributes"}:
            path = f"Web/HTML/Global_attributes/{first}"
        elif context:
            path = f"Web/HTML/Element/{context}#attr-{first}"
        else:
            path = f"Web/HTML/Attributes/{first}"
        return label, canonical_url_from_slug(path.split("#", 1)[0]) + (
            "#" + path.split("#", 1)[1] if "#" in path else ""
        )

    if normalized in {"svgattr", "svgattrxref"} and first:
        url = canonical_url_from_slug(f"Web/SVG/Reference/Attribute/{first}")
        return label, append_macro_anchor(url, args)

    if normalized in {"svgelement", "svgelementxref"} and first:
        if not second:
            label = f"<{first}>"
        url = canonical_url_from_slug(f"Web/SVG/Reference/Element/{first}")
        return label, append_macro_anchor(url, args)

    if normalized == "mathmlelement" and first:
        url = canonical_url_from_slug(f"Web/MathML/Reference/Element/{first}")
        return label, append_macro_anchor(url, args)

    http_paths = {
        "httpheader": "Web/HTTP/Reference/Headers",
        "httpmethod": "Web/HTTP/Reference/Methods",
        "httpstatus": "Web/HTTP/Reference/Status",
    }
    if normalized in http_paths and first:
        url = canonical_url_from_slug(f"{http_paths[normalized]}/{first}")
        return label, append_macro_anchor(url, args)

    if normalized in {"webextapiref", "webextapitype"} and first:
        return label, canonical_url_from_slug(f"Mozilla/Add-ons/WebExtensions/API/{first}")

    if normalized == "rfc" and first:
        number = re.search(r"\d+", first)
        if number:
            return label or f"RFC {number.group(0)}", f"https://datatracker.ietf.org/doc/html/rfc{number.group(0)}"

    # Unknown macros are not removed. Their best available display label
    # remains in the text, and the raw macro is retained in diagnostics.
    return label or macro_name, None

def replace_macros_in_text(
    text: str,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    output: list[str] = []
    resolved_links: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    cursor = 0

    while True:
        start = text.find("{{", cursor)
        if start < 0:
            output.append(text[cursor:])
            break
        end = find_macro_end(text, start)
        if end is None:
            output.append(text[cursor:])
            break

        output.append(text[cursor:start])
        raw_macro = text[start:end]
        parsed = parse_macro_body(text[start + 2:end - 2])
        if parsed is None:
            output.append(raw_macro)
            unresolved.append({"raw": raw_macro, "macro_name": "unknown", "label": raw_macro})
            cursor = end
            continue

        macro_name, args = parsed
        label, target_url = macro_target(macro_name, args)
        output.append(label)
        if target_url:
            resolved_links.append({
                "url": target_url,
                "anchor_text": label,
                "macro": macro_name,
                "raw": raw_macro,
            })
        elif re.sub(r"[^a-z0-9]", "", macro_name.casefold()) not in {
            "compat", "specifications", "specname", "spec2", "seecompattable",
            "optionalinline", "readonlyinline", "nonstandardinline",
            "experimentalinline", "deprecatedinline", "nonstandardheader",
            "experimentalheader", "deprecatedheader", "securecontextheader",
            "securecontextinline", "availableinworkers", "embedlivesample",
            "embedghlivesample", "livesamplelink", "embedinteractiveexample",
            "inheritancediagram", "previous", "next", "previousnext", "apiref",
        }:
            unresolved.append({
                "raw": raw_macro,
                "macro_name": macro_name,
                "label": label,
            })
        cursor = end

    return "".join(output), resolved_links, unresolved


def preprocess_markdown_tokens(
    tokens: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve macros in Markdown text tokens, never in code tokens."""
    resolved_links: list[dict[str, Any]] = []
    unresolved_macros: list[dict[str, Any]] = []

    for token in tokens:
        if token.type == "inline" and token.children:
            for child in token.children:
                # `code_inline`, `html_inline`, and fenced code are not text
                # tokens and must not be macro-expanded.
                if child.type != "text":
                    continue
                replaced, links, unresolved = replace_macros_in_text(child.content)
                child.content = replaced
                resolved_links.extend(links)
                unresolved_macros.extend(unresolved)

    return resolved_links, unresolved_macros


# ============================================================================
# 5. STRUCTURED MARKDOWN / HTML EXTRACTION
# ============================================================================


def clean_prose_text(value: str) -> str:
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
    page_url: str,
    link_references: list[dict[str, Any]],
    skip_descendants: set[str] | None = None,
) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag) or node.name in SKIP_HTML_TAGS:
        return ""

    if node.name == "br":
        return "\n"
    if node.name == "img":
        return str(node.get("alt", ""))
    if skip_descendants and node.name in skip_descendants:
        return ""

    if node.name == "a" and node.get("href"):
        target = normalize_source_link(str(node.get("href")), page_url)
        if target:
            link_references.append({
                "url": target,
                "anchor_text": clean_prose_text(node.get_text("", strip=False)),
                "source": "markdown_or_html_link",
            })

    parts: list[str] = []
    block_children = {"blockquote", "div", "li", "ol", "p", "pre", "ul"}
    for child in node.children:
        child_text = extract_node_text(
            child,
            page_url=page_url,
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
    classes = [str(value) for value in pre.get("class", [])]
    code = pre.find("code")
    if code:
        classes.extend(str(value) for value in code.get("class", []))
    for class_name in classes:
        match = re.search(r"(?:language|lang)-([A-Za-z0-9_+#.-]+)", class_name)
        if match:
            return match.group(1)
    return None


def extract_markdown_segments(
    rendered_html: str,
    *,
    page_url: str,
    canonical_slug: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract ordered blocks from Markdown-rendered HTML.

    This is deliberately downstream of MarkdownIt. In particular, fenced code
    is rendered as escaped text inside <pre><code>, so examples containing
    HTML are never reinterpreted as document markup and discarded.
    """
    soup = BeautifulSoup(rendered_html, "html.parser")
    segments: list[dict[str, Any]] = []
    link_references: list[dict[str, Any]] = []
    heading_path: list[str] = []
    section_anchor: str | None = None

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
            "segment_id": f"mdn:{canonical_slug}:segment:{ordinal:04d}",
            "ordinal": ordinal,
            "type": segment_type,
            "text": cleaned,
            "heading_path": heading_path.copy(),
        }
        if language:
            segment["language"] = language
        if segment_type == "code":
            segment["code"] = cleaned
        if source_anchor or section_anchor:
            segment["source_anchor"] = source_anchor or section_anchor
        segments.append(segment)

    def walk(node: Any) -> None:
        nonlocal section_anchor
        if isinstance(node, NavigableString):
            if str(node).strip():
                add_segment("paragraph", str(node))
            return
        if not isinstance(node, Tag) or node.name in SKIP_HTML_TAGS:
            return

        name = node.name.lower()
        if name == "pre":
            code_node = node.find("code")
            source = code_node if code_node else node
            add_segment("code", source.get_text("", strip=False), language=extract_code_language(node))
            return

        if name in HEADING_TAGS:
            text_value = extract_node_text(
                node,
                page_url=page_url,
                link_references=link_references,
            )
            level = int(name[1])
            heading_path[:] = heading_path[:level - 1]
            heading_path.append(clean_prose_text(text_value))
            section_anchor = str(node.get("id")) if node.get("id") else None
            add_segment(
                "heading",
                text_value,
                source_anchor=str(node.get("id")) if node.get("id") else None,
            )
            return

        if name == "p":
            text_value = extract_node_text(
                node,
                page_url=page_url,
                link_references=link_references,
            )
            add_segment("paragraph", text_value)
            return

        if name == "li":
            # Keep a list item as one segment, but do not flatten a nested list
            # or a preformatted example into this item's prose segment.
            text_value = extract_node_text(
                node,
                page_url=page_url,
                link_references=link_references,
                skip_descendants={"ul", "ol", "pre"},
            )
            add_segment("list_item", text_value)
            for child in node.find_all(["ul", "ol", "pre"], recursive=False):
                walk(child)
            for nested_list in node.find_all(["ul", "ol"], recursive=True):
                if nested_list.parent is not node:
                    # Nested list descendants are reached from their closest
                    # list item, so do not walk them twice here.
                    continue
            return

        if name in {"dt", "dd"}:
            text_value = extract_node_text(
                node,
                page_url=page_url,
                link_references=link_references,
            )
            add_segment("definition_term" if name == "dt" else "definition_description", text_value)
            return

        if name == "tr":
            cells: list[str] = []
            for cell in node.find_all(["th", "td"], recursive=False):
                cells.append(clean_prose_text(extract_node_text(
                    cell,
                    page_url=page_url,
                    link_references=link_references,
                )))
            add_segment("table_row", " | ".join(cell for cell in cells if cell))
            return

        if name == "blockquote":
            text_value = extract_node_text(
                node,
                page_url=page_url,
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

        text_value = extract_node_text(
            node,
            page_url=page_url,
            link_references=link_references,
        )
        add_segment("paragraph", text_value)

    for child in soup.contents:
        walk(child)

    return segments, link_references


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
        if hostname == "developer.mozilla.org":
            internal.append(link)
        else:
            external.append(link)
    return internal, external


def segments_to_content(segments: list[dict[str, Any]]) -> str:
    return "\n\n".join(segment["text"] for segment in segments).strip()


def determine_category(relative_path: Path) -> str:
    parts = relative_path.parts
    if parts and parts[0] == "web" and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0] if parts else "unknown"


# ============================================================================
# 6. PARSE AN INDIVIDUAL MDN DOCUMENT
# ============================================================================


def parse_document(file_path: Path, mdn_root: Path) -> dict[str, Any] | None:
    try:
        raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        metadata, raw_content = split_front_matter(raw_text)

        title_value = metadata.get("title", "")
        if not isinstance(title_value, str) or not title_value.strip():
            raise ValueError("Missing or invalid front-matter title.")
        title = title_value.strip()

        relative_path = file_path.relative_to(mdn_root)
        canonical_slug = slug_from_front_matter(metadata, relative_path)
        if not canonical_slug:
            raise ValueError("Could not determine canonical MDN slug.")
        page_url = canonical_url_from_slug(canonical_slug)

        # Parse Markdown into tokens first. Markdown code blocks are distinct
        # token types; macros are only transformed in ordinary text tokens.
        # MDN content uses GitHub-flavored tables in addition to CommonMark.
        # The GFM-like preset keeps code fences as protected tokens while
        # parsing tables into real block structure before BeautifulSoup runs.
        markdown_parser = MarkdownIt("gfm-like", {"html": True, "breaks": False}).disable("linkify")
        tokens = markdown_parser.parse(raw_content)
        macro_links, unresolved_macros = preprocess_markdown_tokens(tokens)
        rendered_html = markdown_parser.renderer.render(tokens, markdown_parser.options, {})

        segments, html_link_references = extract_markdown_segments(
            rendered_html,
            page_url=page_url,
            canonical_slug=canonical_slug,
        )

        macro_link_references: list[dict[str, Any]] = []
        for reference in macro_links:
            target = normalize_source_link(reference.get("url"), page_url)
            if target:
                macro_link_references.append({
                    "url": target,
                    "anchor_text": reference.get("anchor_text", ""),
                    "source": "mdn_macro",
                    "macro": reference.get("macro", ""),
                    "raw_macro": reference.get("raw", ""),
                })

        # Keep reference occurrences in their own collection. The outgoing
        # URL lists below are unique graph-oriented parent-level destinations.
        link_references = html_link_references + macro_link_references
        outgoing = unique_urls(link_references)
        internal, external = split_links(outgoing)

        short_title = metadata.get("short-title", "")
        page_type = metadata.get("page-type", "")
        if not isinstance(short_title, str):
            short_title = ""
        if not isinstance(page_type, str):
            page_type = ""

        redirects = metadata.get("redirects", [])
        if isinstance(redirects, str):
            redirects = [redirects]
        if not isinstance(redirects, list):
            redirects = []
        redirects = [value for value in redirects if isinstance(value, str) and value.strip()]

        content = segments_to_content(segments)
        code_blocks = [
            {
                "code_id": f"mdn:{canonical_slug}:code:{index:04d}",
                "segment_id": segment["segment_id"],
                "language": segment.get("language"),
                "code": segment["code"],
            }
            for index, segment in enumerate(
                (segment for segment in segments if segment.get("type") == "code")
            )
        ]

        source_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        document = {
            "id": f"mdn:{canonical_slug}",
            "source_path": relative_path.as_posix(),
            "canonical_slug": canonical_slug,
            "title": title,
            "url": page_url,
            "content": content,
            "segments": segments,
            "code_blocks": code_blocks,
            "short_title": short_title,
            "source": "MDN",
            "category": determine_category(relative_path),
            "page_type": page_type,
            "status": metadata.get("status") or [],
            "outgoing_links": outgoing,
            "link_references": link_references,
            "internal_links": internal,
            "external_links": external,
            "redirects": redirects,
            "unresolved_macros": unresolved_macros,
            "content_hash": source_hash,
            "language": "en",
        }
        return document

    except Exception as error:
        COLLECTION_DIAGNOSTICS["parse_errors"].append({
            "source_path": file_path.relative_to(mdn_root).as_posix(),
            "error": str(error),
        })
        print(f"Error processing {file_path}: {error}")
        return None


# ============================================================================
# 7. COLLECT ALL DOCUMENTS IN THE APPROVED SCOPE
# ============================================================================


def collect_documents() -> list[dict[str, Any]]:
    mdn_root = get_mdn_content_root()
    if mdn_root is None:
        raise FileNotFoundError(
            f"MDN English source folder (files/en-us) not found under: {EXTRACT_DIR}"
        )

    SOURCE_PATH_URL_MAP.clear()
    COLLECTION_DIAGNOSTICS.update({
        "files_discovered": 0,
        "documents_parsed": 0,
        "duplicate_source_paths": [],
        "duplicate_canonical_urls": [],
        "parse_errors": [],
        "unresolved_macro_count": 0,
        "unresolved_macro_examples": [],
        "topics": {},
    })

    collected: list[dict[str, Any]] = []
    used_source_paths: set[str] = set()
    canonical_url_to_document: dict[str, dict[str, Any]] = {}
    eligible_files: list[Path] = []

    for topic in TOPIC_PATHS:
        topic_path = mdn_root / topic
        if not topic_path.exists():
            print(f"Topic path unavailable in this MDN revision: {topic}")
            COLLECTION_DIAGNOSTICS["topics"][topic] = {
                "files_discovered": 0,
                "documents_collected": 0,
                "path_available": False,
            }
            continue
        files = sorted(topic_path.rglob("index.md"), key=lambda path: path.as_posix().casefold())
        eligible_files.extend(files)
        COLLECTION_DIAGNOSTICS["topics"][topic] = {
            "files_discovered": len(files),
            "documents_collected": 0,
            "path_available": True,
        }

    # A file can be reachable from only one configured topic root in the
    # current scope, but de-duplicate paths defensively and keep deterministic
    # ordering across runs.
    eligible_files = sorted(set(eligible_files), key=lambda path: path.as_posix().casefold())
    COLLECTION_DIAGNOSTICS["files_discovered"] = len(eligible_files)
    print(f"\nDiscovered {len(eligible_files)} MDN Markdown pages in the configured scope.")

    for file_path in eligible_files:
        source_path = file_path.relative_to(mdn_root).as_posix()
        if source_path in used_source_paths:
            COLLECTION_DIAGNOSTICS["duplicate_source_paths"].append(source_path)
            continue
        used_source_paths.add(source_path)

        document = parse_document(file_path, mdn_root)
        if document is None:
            continue

        # The mapping is retained even when two source files resolve to the
        # same canonical page, so source-path provenance is never lost.
        SOURCE_PATH_URL_MAP[source_path] = document["url"]
        COLLECTION_DIAGNOSTICS["documents_parsed"] += 1
        COLLECTION_DIAGNOSTICS["unresolved_macro_count"] += len(document["unresolved_macros"])
        if len(COLLECTION_DIAGNOSTICS["unresolved_macro_examples"]) < 100:
            for macro in document["unresolved_macros"]:
                if len(COLLECTION_DIAGNOSTICS["unresolved_macro_examples"]) >= 100:
                    break
                COLLECTION_DIAGNOSTICS["unresolved_macro_examples"].append({
                    "source_path": source_path,
                    **macro,
                })

        canonical_url = document["url"]
        if canonical_url in canonical_url_to_document:
            COLLECTION_DIAGNOSTICS["duplicate_canonical_urls"].append({
                "source_path": source_path,
                "canonical_url": canonical_url,
                "kept_source_path": canonical_url_to_document[canonical_url]["source_path"],
            })
            continue

        canonical_url_to_document[canonical_url] = document
        collected.append(document)
        topic = document["category"]
        if topic in COLLECTION_DIAGNOSTICS["topics"]:
            COLLECTION_DIAGNOSTICS["topics"][topic]["documents_collected"] += 1

    print(f"Collected {len(collected)} unique canonical MDN documents.")
    redirects_path = mdn_root / "_redirects.txt"
    if redirects_path.is_file():
        destination_by_key = {urldefrag(document["url"]).url.casefold(): document for document in collected}
        for line in redirects_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            column = line.split()
            if len(column) < 2:
                continue
            target = normalize_source_link(column[1], MDN_ORIGIN)
            document = destination_by_key.get(urldefrag(target).url.casefold()) if target else None
            if document:
                document["redirects"].append(column[0])
    return collected


# ============================================================================
# 8. SAVE DATASET, SOURCE MAPPING, AND COLLECTION REPORT
# ============================================================================


def atomic_json_write(path: Path, value: Any, *, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = path.with_suffix(path.suffix + ".tmp")
    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=indent, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    temporary_file.replace(path)


def save_documents(documents: list[dict[str, Any]]) -> None:
    atomic_json_write(OUTPUT_FILE, documents, indent=2)
    print("\nMDN dataset saved:")
    print(OUTPUT_FILE)


def save_source_url_mapping() -> None:
    atomic_json_write(SOURCE_URL_MAP_FILE, SOURCE_PATH_URL_MAP, indent=2)
    print("Source-path to canonical-URL mapping saved:")
    print(SOURCE_URL_MAP_FILE)


def save_collection_report(documents: list[dict[str, Any]]) -> None:
    category_counts: dict[str, int] = {}
    documents_with_links = 0
    total_outgoing = 0
    total_link_references = 0
    total_code_blocks = 0

    for document in documents:
        category = document.get("category", "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
        documents_with_links += int(bool(document.get("outgoing_links")))
        total_outgoing += len(document.get("outgoing_links", []))
        total_link_references += len(document.get("link_references", []))
        total_code_blocks += len(document.get("code_blocks", []))

    report = {
        **COLLECTION_DIAGNOSTICS,
        "documents_saved": len(documents),
        "unique_ids": len({document["id"] for document in documents}),
        "unique_urls": len({document["url"] for document in documents}),
        "documents_with_links": documents_with_links,
        "total_unique_outgoing_urls": total_outgoing,
        "total_link_reference_occurrences": total_link_references,
        "total_code_blocks": total_code_blocks,
        "category_counts": category_counts,
        "source_path_mapping_entries": len(SOURCE_PATH_URL_MAP),
    }
    atomic_json_write(COLLECTION_REPORT_FILE, report, indent=2)


def print_summary(documents: list[dict[str, Any]]) -> None:
    category_counts: dict[str, int] = {}
    total_outgoing = 0
    total_references = 0
    total_code_blocks = 0
    documents_with_links = 0

    for document in documents:
        category = document.get("category", "unknown")
        category_counts[category] = category_counts.get(category, 0) + 1
        total_outgoing += len(document.get("outgoing_links", []))
        total_references += len(document.get("link_references", []))
        total_code_blocks += len(document.get("code_blocks", []))
        documents_with_links += int(bool(document.get("outgoing_links")))

    print("\n" + "=" * 52)
    print("               MDN COLLECTION SUMMARY")
    print("=" * 52)
    print(f"Documents collected: {len(documents)}")
    print(f"Unique source IDs: {len({doc['id'] for doc in documents})}")
    print(f"Unique canonical URLs: {len({doc['url'] for doc in documents})}")
    print(f"Source-path mappings: {len(SOURCE_PATH_URL_MAP)}")
    print(f"Documents with outgoing links: {documents_with_links}")
    print(f"Unique outgoing URLs: {total_outgoing}")
    print(f"Link reference occurrences: {total_references}")
    print(f"Code blocks preserved: {total_code_blocks}")
    print(f"Unresolved macros retained for review: {COLLECTION_DIAGNOSTICS['unresolved_macro_count']}")
    print(f"Parse errors: {len(COLLECTION_DIAGNOSTICS['parse_errors'])}")
    print("\nCATEGORY DISTRIBUTION")
    for category, count in sorted(category_counts.items()):
        print(f"{category:<35} {count:>6}")
    print("=" * 52)


def main() -> None:
    print("=" * 52)
    print("              MDN DATA COLLECTION")
    print("=" * 52)
    ensure_directories()
    download_mdn()
    extract_mdn()
    documents = collect_documents()
    save_documents(documents)
    save_source_url_mapping()
    save_collection_report(documents)
    print_summary(documents)


if __name__ == "__main__":
    main()
