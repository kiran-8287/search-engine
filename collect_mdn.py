
import json
import re
import zipfile
import random

from pathlib import Path
from urllib.request import urlretrieve
from urllib.parse import urljoin, urlparse, urldefrag

import yaml
from bs4 import BeautifulSoup


# ==================================================
# 1. CONFIGURATION
# ==================================================

MDN_ZIP_URL = (
    "https://github.com/mdn/content/archive/refs/heads/main.zip"
)

DOWNLOAD_DIR = Path("data/downloads")
RAW_DIR = Path("data/raw")

ZIP_PATH = DOWNLOAD_DIR / "mdn_content.zip"
EXTRACT_DIR = DOWNLOAD_DIR / "mdn_content"

OUTPUT_FILE = RAW_DIR / "mdn_documents.json"

TARGET_DOCUMENTS = 5000
RANDOM_SEED = 42


# Target number of documents from each topic.
# Total = 5000

TOPIC_TARGETS = {
    "web/api": 1900,
    "web/javascript": 900,
    "web/css": 700,
    "web/html": 500,
    "web/http": 300,
    "learn_web_development": 300,
    "glossary": 200,
    "web/accessibility": 100,
    "web/security": 50,
    "web/performance": 25,
    "web/progressive_web_apps": 25
}


# ==================================================
# 2. CREATE DIRECTORIES
# ==================================================

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)


# ==================================================
# 3. DOWNLOAD MDN REPOSITORY
# ==================================================

def download_mdn():

    if ZIP_PATH.exists():

        print("MDN ZIP already downloaded.")
        return

    print("Downloading MDN repository...")

    urlretrieve(MDN_ZIP_URL, ZIP_PATH)

    print("MDN download completed.")


# ==================================================
# 4. EXTRACT MDN REPOSITORY
# ==================================================

def extract_mdn():

    expected_folder = EXTRACT_DIR / "files" / "en-us"

    if expected_folder.exists():

        print("MDN files already extracted.")
        return

    print("Extracting MDN repository...")

    with zipfile.ZipFile(ZIP_PATH, "r") as zip_ref:

        zip_ref.extractall(EXTRACT_DIR)

    print("MDN extraction completed.")


# ==================================================
# 5. CLEAN DOCUMENT CONTENT
# ==================================================

def clean_content(raw_content):

    content = raw_content

    # Remove MDN macros
    content = re.sub(
        r"\{\{.*?\}\}",
        "",
        content,
        flags=re.DOTALL
    )

    # Remove Markdown images
    content = re.sub(
        r"!\[[^\]]*\]\([^)]+\)",
        "",
        content
    )

    # Preserve Markdown link text
    # Link destinations are extracted separately
    content = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        content
    )

    # Convert HTML into readable text
    soup = BeautifulSoup(
        content,
        "html.parser"
    )

    content = soup.get_text(separator=" ")

    # Remove inline code formatting characters
    content = content.replace("`", "")

    # Normalize whitespace
    content = re.sub(
        r"\s+",
        " ",
        content
    )

    return content.strip()


# ==================================================
# 6. EXTRACT OUTGOING LINKS
# ==================================================

def extract_links(raw_content, page_url):

    links = set()

    # ----------------------------------------------
    # Extract inline Markdown links
    # Example: [JavaScript](https://example.com)
    # ----------------------------------------------

    markdown_links = re.findall(
        r'(?<!!)\[[^\]]+\]\(\s*<?([^\s)>]+)',
        raw_content
    )

    # ----------------------------------------------
    # Extract HTML hyperlinks
    # Example: <a href="https://example.com">
    # ----------------------------------------------

    soup = BeautifulSoup(
        raw_content,
        "html.parser"
    )

    html_links = [
        tag.get("href")
        for tag in soup.find_all("a", href=True)
    ]

    # ----------------------------------------------
    # Combine and process links
    # ----------------------------------------------

    for link in markdown_links + html_links:

        link = link.strip()

        if not link:
            continue

        # Ignore non-web links
        if link.startswith(
            ("mailto:", "javascript:", "data:")
        ):
            continue

        # Convert relative links into absolute URLs
        absolute_url = urljoin(
            page_url,
            link
        )

        parsed = urlparse(absolute_url)

        # Keep HTTP and HTTPS links only
        if parsed.scheme not in ("http", "https"):
            continue

        # Remove URL fragments
        absolute_url = urldefrag(
            absolute_url
        ).url

        links.add(absolute_url)

    # ----------------------------------------------
    # Separate internal and external links
    # ----------------------------------------------

    internal_links = []
    external_links = []

    for link in sorted(links):

        hostname = (
            urlparse(link).hostname or ""
        ).lower()

        if hostname == "developer.mozilla.org":

            internal_links.append(link)

        else:

            external_links.append(link)

    return {

        "outgoing_links": sorted(links),

        "internal_links": internal_links,

        "external_links": external_links

    }


# ==================================================
# 7. PARSE INDIVIDUAL MDN DOCUMENT
# ==================================================

def parse_document(file_path, mdn_root):

    try:

        # Read Markdown file
        raw_text = file_path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        # ------------------------------------------
        # Extract YAML frontmatter
        # ------------------------------------------

        match = re.match(
            r"^---\s*\n(.*?)\n---\s*\n(.*)$",
            raw_text,
            flags=re.DOTALL
        )

        if not match:
            return None

        metadata_text = match.group(1)
        raw_content = match.group(2)

        metadata = yaml.safe_load(metadata_text)

        if not isinstance(metadata, dict):
            return None

        # ------------------------------------------
        # Extract title
        # ------------------------------------------

        title = metadata.get("title", "")

        if not isinstance(title, str):
            return None

        title = title.strip()

        if not title:
            return None

        # ------------------------------------------
        # Construct MDN page URL
        # ------------------------------------------

        relative_path = file_path.relative_to(
            mdn_root
        )

        slug = relative_path.parent.as_posix()

        url = (
            "https://developer.mozilla.org/en-US/docs/"
            + slug.strip("/")
        )

        # ------------------------------------------
        # Extract links BEFORE cleaning content
        # ------------------------------------------

        link_data = extract_links(
            raw_content,
            url
        )

        # ------------------------------------------
        # Clean document content
        # ------------------------------------------

        content = clean_content(raw_content)

        # Ignore very short documents
        if len(content) < 200:
            return None

        # ------------------------------------------
        # Determine broad topic category
        # ------------------------------------------

        parts = relative_path.parts

        if parts[0] == "web" and len(parts) > 1:

            category = "/".join(parts[:2])

        else:

            category = parts[0]

        # ------------------------------------------
        # Optional MDN metadata
        # ------------------------------------------

        short_title = metadata.get(
            "short-title",
            ""
        )

        if not isinstance(short_title, str):
            short_title = ""

        page_type = metadata.get(
            "page-type",
            ""
        )

        if not isinstance(page_type, str):
            page_type = ""

        # ------------------------------------------
        # Return document
        # ------------------------------------------

        document = {

            "id": relative_path.as_posix(),

            "title": title,

            "url": url,

            "content": content,

            "short_title": short_title,

            "source": "MDN",

            "category": category,

            "page_type": page_type,

            "outgoing_links": link_data[
                "outgoing_links"
            ],

            "internal_links": link_data[
                "internal_links"
            ],

            "external_links": link_data[
                "external_links"
            ]

        }

        return document

    except Exception as error:

        print(
            f"Error processing {file_path}: {error}"
        )

        return None


# ==================================================
# 8. COLLECT DOCUMENTS BY TOPIC
# ==================================================

def collect_documents():

    mdn_root = EXTRACT_DIR / "files" / "en-us"

    if not mdn_root.exists():

        raise FileNotFoundError(
            f"MDN folder not found: {mdn_root}"
        )

    collected = []

    used_ids = set()
    used_urls = set()

    print("\nCollecting MDN documents...")

    # ----------------------------------------------
    # Collect documents topic by topic
    # ----------------------------------------------

    for topic, target in TOPIC_TARGETS.items():

        topic_path = mdn_root / topic

        if not topic_path.exists():

            print(
                f"Topic unavailable: {topic}"
            )

            continue

        print(
            f"\nProcessing topic: {topic}"
        )

        files = list(
            topic_path.rglob("index.md")
        )

        # Randomize selection reproducibly
        random.Random(
            RANDOM_SEED
        ).shuffle(files)

        topic_documents = []

        for file_path in files:

            document = parse_document(
                file_path,
                mdn_root
            )

            if document is None:
                continue

            # Avoid duplicate IDs
            if document["id"] in used_ids:
                continue

            # Avoid duplicate URLs
            if document["url"] in used_urls:
                continue

            topic_documents.append(document)

            if len(topic_documents) >= target:
                break

        # Add topic documents to final collection
        collected.extend(topic_documents)

        for document in topic_documents:

            used_ids.add(document["id"])
            used_urls.add(document["url"])

        print(
            f"Collected {len(topic_documents)} "
            f"documents from {topic}"
        )

    # ----------------------------------------------
    # Fill remaining shortage if any
    # ----------------------------------------------

    if len(collected) < TARGET_DOCUMENTS:

        print(
            "\nFilling remaining document shortage..."
        )

        eligible_files = []

        for topic in TOPIC_TARGETS:

            topic_path = mdn_root / topic

            if topic_path.exists():

                eligible_files.extend(
                    topic_path.rglob("index.md")
                )

        random.Random(
            RANDOM_SEED
        ).shuffle(eligible_files)

        for file_path in eligible_files:

            if len(collected) >= TARGET_DOCUMENTS:
                break

            document = parse_document(
                file_path,
                mdn_root
            )

            if document is None:
                continue

            if document["id"] in used_ids:
                continue

            if document["url"] in used_urls:
                continue

            collected.append(document)

            used_ids.add(document["id"])
            used_urls.add(document["url"])

    return collected[:TARGET_DOCUMENTS]


# ==================================================
# 9. SAVE DATASET AS JSON
# ==================================================

def save_documents(documents):

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            documents,
            file,
            indent=4,
            ensure_ascii=False
        )

    print(
        "\nDataset saved successfully."
    )

    print(
        "Output file:",
        OUTPUT_FILE
    )


# ==================================================
# 10. PRINT COLLECTION SUMMARY
# ==================================================

def print_summary(documents):

    print("\n===================================")
    print("          COLLECTION SUMMARY")
    print("===================================")

    print(
        "Total documents:",
        len(documents)
    )

    print(
        "Unique IDs:",
        len({
            doc["id"] for doc in documents
        })
    )

    print(
        "Unique URLs:",
        len({
            doc["url"] for doc in documents
        })
    )

    documents_with_links = sum(
        bool(doc["outgoing_links"])
        for doc in documents
    )

    total_outgoing = sum(
        len(doc["outgoing_links"])
        for doc in documents
    )

    total_internal = sum(
        len(doc["internal_links"])
        for doc in documents
    )

    total_external = sum(
        len(doc["external_links"])
        for doc in documents
    )

    print(
        "Documents with outgoing links:",
        documents_with_links
    )

    print(
        "Total outgoing links:",
        total_outgoing
    )

    print(
        "Total internal links:",
        total_internal
    )

    print(
        "Total external links:",
        total_external
    )

    print("\nCATEGORY DISTRIBUTION:")

    category_counts = {}

    for document in documents:

        category = document["category"]

        category_counts[category] = (
            category_counts.get(category, 0) + 1
        )

    for category, count in sorted(
        category_counts.items()
    ):

        print(
            f"{category:<35} {count}"
        )

    print("\n===================================")


# ==================================================
# 11. MAIN FUNCTION
# ==================================================

def main():

    print("===================================")
    print("       MDN DATA COLLECTION")
    print("===================================")

    # Download repository if needed
    download_mdn()

    # Extract repository if needed
    extract_mdn()

    # Collect documents
    documents = collect_documents()

    # Save JSON dataset
    save_documents(documents)

    # Display results
    print_summary(documents)


if __name__ == "__main__":

    main()
