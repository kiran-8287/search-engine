
import os
import re
import json
import time
import html
import requests

from pathlib import Path
from collections import defaultdict
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv


# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data" / "raw"

DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = DATA_DIR / "stackoverflow_documents.json"
CHECKPOINT_FILE = PROJECT_DIR / "stackoverflow_checkpoint.json"

load_dotenv(PROJECT_DIR / ".env")

API_KEY = os.getenv("STACKEXCHANGE_API_KEY")

API_URL = "https://api.stackexchange.com/2.3"

SITE = "stackoverflow"
PAGE_SIZE = 100
MAX_PAGES_PER_TAG = 25
MAX_ANSWERS_PER_QUESTION = 3

TARGET_QUESTIONS = 5000

# Stop making requests when the API reports a low quota.
MINIMUM_QUOTA = 5

TOPIC_CONFIG = {
    "javascript": {
        "target": 1200,
        "tags": ["javascript", "jquery", "json"]
    },
    "html": {
        "target": 800,
        "tags": ["html"]
    },
    "css": {
        "target": 800,
        "tags": ["css"]
    },
    "web_apis": {
        "target": 1000,
        "tags": [
            "dom",
            "fetch-api",
            "xmlhttprequest",
            "websocket",
            "service-worker",
            "webassembly"
        ]
    },
    "http": {
        "target": 500,
        "tags": [
            "http",
            "https",
            "http-headers",
            "rest",
            "cors"
        ]
    },
    "general_web": {
        "target": 700,
        "tags": ["web", "browser", "frontend"]
    }
}

session = requests.Session()

API_REQUESTS = 0
REMAINING_QUOTA = None
STOP_COLLECTION = False


# ============================================================
# 2. API REQUEST FUNCTION
# ============================================================

def api_get(endpoint, params=None):

    global API_REQUESTS
    global REMAINING_QUOTA
    global STOP_COLLECTION

    if STOP_COLLECTION:
        return []

    request_params = {
        "site": SITE,
        "pagesize": PAGE_SIZE,
        "filter": "withbody"
    }

    if params:
        request_params.update(params)

    if API_KEY:
        request_params["key"] = API_KEY

    url = f"{API_URL}/{endpoint.lstrip('/')}"

    try:

        API_REQUESTS += 1

        response = session.get(
            url,
            params=request_params,
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

        REMAINING_QUOTA = data.get(
            "quota_remaining",
            REMAINING_QUOTA
        )

        if "backoff" in data:
            wait_time = int(data["backoff"])
            print(f"API backoff: waiting {wait_time} seconds")
            time.sleep(wait_time)

        if "error_id" in data:

            print(
                "API ERROR:",
                data.get("error_name"),
                data.get("error_message")
            )

            return []

        if REMAINING_QUOTA is not None:
            if REMAINING_QUOTA <= MINIMUM_QUOTA:
                print(
                    "\nAPI quota is low:",
                    REMAINING_QUOTA
                )
                STOP_COLLECTION = True

        return data.get("items", [])

    except requests.exceptions.RequestException as error:

        print("\nRequest failed:", error)
        return []

    except ValueError as error:

        print("\nCould not decode API response:", error)
        return []


# ============================================================
# 3. CHECKPOINT HANDLING
# ============================================================

def load_checkpoint():

    if not CHECKPOINT_FILE.exists():

        return {
            "documents": {},
            "tag_pages": {},
            "accepted_batches_done": [],
            "supplement_batches_done": []
        }

    try:

        with CHECKPOINT_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            saved = json.load(file)

        raw_documents = saved.get("documents", [])

        documents = {}

        # Support old dictionary-format checkpoints.
        if isinstance(raw_documents, dict):

            for key, value in raw_documents.items():

                if not isinstance(value, dict):
                    continue

                question_id = value.get(
                    "question_id",
                    key
                )

                documents[str(question_id)] = value

        # Support list-format checkpoints.
        elif isinstance(raw_documents, list):

            for item in raw_documents:

                if not isinstance(item, dict):
                    continue

                question_id = item.get("question_id")

                if question_id is not None:
                    documents[str(question_id)] = item

        else:

            raise ValueError(
                "Unknown checkpoint document format."
            )

        state = {
            "documents": documents,

            # New pagination tracking.
            "tag_pages": saved.get("tag_pages", {}),

            "accepted_batches_done": saved.get(
                "accepted_batches_done", []
            ),

            "supplement_batches_done": saved.get(
                "supplement_batches_done", []
            )
        }

        print("\nCheckpoint loaded successfully.")
        print("Previously collected questions:", len(documents))

        return state

    except Exception as error:

        raise RuntimeError(
            f"Checkpoint could not be loaded: {error}. "
            "Your original checkpoint has not been deleted."
        )


def save_checkpoint(state):

    temporary_file = CHECKPOINT_FILE.with_suffix(".tmp")

    with temporary_file.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            {
                "documents": state["documents"],
                "tag_pages": state["tag_pages"],
                "accepted_batches_done": state[
                    "accepted_batches_done"
                ],
                "supplement_batches_done": state[
                    "supplement_batches_done"
                ]
            },
            file,
            ensure_ascii=False,
            indent=2
        )

    temporary_file.replace(CHECKPOINT_FILE)


# ============================================================
# 4. HTML CONTENT AND LINK EXTRACTION
# ============================================================

def normalize_url(url):

    if not url:
        return None

    try:

        parsed = urlparse(url.strip())

        if not parsed.scheme:
            return None

        if parsed.scheme not in ("http", "https"):
            return None

        hostname = (parsed.hostname or "").lower()

        if hostname in (
            "stackoverflow.com",
            "www.stackoverflow.com"
        ):
            hostname = "stackoverflow.com"

        path = re.sub(r"/+", "/", parsed.path)

        # Remove trailing slash except for root.
        if path != "/":
            path = path.rstrip("/")

        return urlunparse((
            "https",
            hostname,
            path,
            "",
            parsed.query,
            ""
        ))

    except Exception:
        return None


def extract_content_and_links(body):

    if not body:
        return "", [], [], []

    soup = BeautifulSoup(body, "html.parser")

    outgoing_links = []

    for anchor in soup.find_all("a", href=True):

        link = normalize_url(anchor["href"])

        if link and link not in outgoing_links:
            outgoing_links.append(link)

    internal_links = []
    external_links = []

    for link in outgoing_links:

        hostname = (urlparse(link).hostname or "").lower()

        if (
            hostname == "stackoverflow.com"
            or hostname.endswith(".stackoverflow.com")
        ):
            internal_links.append(link)
        else:
            external_links.append(link)

    # Preserve code content.
    for code in soup.find_all("code"):
        code.insert_before("\n")
        code.insert_after("\n")

    text_content = soup.get_text(
        separator=" ",
        strip=True
    )

    text_content = html.unescape(text_content)
    text_content = re.sub(r"\s+", " ", text_content).strip()

    return (
        text_content,
        outgoing_links,
        internal_links,
        external_links
    )


# ============================================================
# 5. CATEGORY COUNTING
# ============================================================

def category_counts(documents):

    counts = defaultdict(int)

    for document in documents.values():

        category = document.get(
            "category",
            "unknown"
        )

        counts[category] += 1

    return counts


# ============================================================
# 6. QUESTION COLLECTION
# ============================================================

def collect_questions(state):

    documents = state["documents"]
    tag_pages = state["tag_pages"]

    print("\n========== QUESTION COLLECTION ==========")

    for category, config in TOPIC_CONFIG.items():

        if STOP_COLLECTION:
            break

        target = config["target"]

        counts = category_counts(documents)
        current_count = counts.get(category, 0)

        print(f"\nCategory: {category}")
        print(f"Current: {current_count}/{target}")

        if current_count >= target:

            print("Target already reached. Skipping.")
            continue

        for tag in config["tags"]:

            if STOP_COLLECTION:
                break

            counts = category_counts(documents)
            current_count = counts.get(category, 0)

            if current_count >= target:
                break

            # Start at page 1 for an incomplete category.
            # Existing question IDs are skipped, so this safely
            # repairs old/incomplete pagination checkpoints.
            page = 1

            print(f"\nSearching tag: {tag}")

            while page <= MAX_PAGES_PER_TAG:

                if STOP_COLLECTION:
                    break

                counts = category_counts(documents)
                current_count = counts.get(category, 0)

                if current_count >= target:
                    break

                print(
                    f"  Page {page} | "
                    f"{current_count}/{target}"
                )

                items = api_get(
                    "questions",
                    {
                        "tagged": tag,
                        "page": page,
                        "pagesize": PAGE_SIZE,
                        "order": "desc",
                        "sort": "votes"
                    }
                )

                if STOP_COLLECTION:
                    break

                if not items:
                    print("  No more questions returned.")
                    break

                added = 0

                for question in items:

                    question_id = str(
                        question["question_id"]
                    )

                    if question_id in documents:
                        continue

                    counts = category_counts(documents)

                    if counts.get(category, 0) >= target:
                        break

                    content, outgoing, internal, external = (
                        extract_content_and_links(
                            question.get("body", "")
                        )
                    )

                    owner = question.get("owner", {})

                    documents[question_id] = {

                        "id": question_id,
                        "question_id": int(question_id),

                        "title": question.get("title", ""),
                        "content": content,

                        "url": question.get("link", ""),

                        "outgoing_links": outgoing,
                        "internal_links": internal,
                        "external_links": external,

                        "incoming_links": [],

                        "tags": question.get("tags", []),

                        "score": question.get("score", 0),
                        "view_count": question.get(
                            "view_count", 0
                        ),

                        "answer_count": question.get(
                            "answer_count", 0
                        ),

                        "accepted_answer_id": question.get(
                            "accepted_answer_id"
                        ),

                        "question_author": owner.get(
                            "display_name"
                        ),

                        "creation_date": question.get(
                            "creation_date"
                        ),

                        "last_activity_date": question.get(
                            "last_activity_date"
                        ),

                        "content_license": question.get(
                            "content_license"
                        ),

                        "source": "Stack Overflow",
                        "category": category,

                        "answers": []
                    }

                    added += 1

                print(f"  New questions added: {added}")

                # Save after every page.
                state["tag_pages"][tag] = page
                save_checkpoint(state)

                if not items or len(items) < PAGE_SIZE:
                    break

                page += 1

                time.sleep(0.2)

        counts = category_counts(documents)

        print(
            f"\nCompleted {category}: "
            f"{counts.get(category, 0)}/{target}"
        )

        save_checkpoint(state)

    print("\nQuestion collection stage finished.")

    save_checkpoint(state)


# ============================================================
# 7. ANSWER COLLECTION
# ============================================================

def add_answers_to_documents(documents, answers):

    added = 0

    for answer in answers:

        question_id = str(
            answer.get("question_id", "")
        )

        if question_id not in documents:
            continue

        document = documents[question_id]

        answer_id = answer.get("answer_id")

        if answer_id is None:
            continue

        existing_ids = {
            item.get("answer_id")
            for item in document["answers"]
        }

        if answer_id in existing_ids:
            continue

        content, outgoing, internal, external = (
            extract_content_and_links(
                answer.get("body", "")
            )
        )

        owner = answer.get("owner", {})

        answer_document = {

            "answer_id": answer_id,

            "content": content,

            "url": (
                f"https://stackoverflow.com/a/{answer_id}"
            ),

            "outgoing_links": outgoing,
            "internal_links": internal,
            "external_links": external,

            "score": answer.get("score", 0),

            "is_accepted": answer.get(
                "is_accepted", False
            ),

            "author": owner.get("display_name"),

            "creation_date": answer.get(
                "creation_date"
            ),

            "content_license": answer.get(
                "content_license"
            )
        }

        document["answers"].append(answer_document)
        added += 1

    return added


def collect_answers(state):

    documents = state["documents"]

    print("\n========== ANSWER COLLECTION ==========")

    question_list = list(documents.values())

    # --------------------------------------------------------
    # Accepted answers
    # --------------------------------------------------------

    accepted_ids = []

    for document in question_list:

        answer_id = document.get("accepted_answer_id")

        if answer_id:
            accepted_ids.append(int(answer_id))

    accepted_ids = list(dict.fromkeys(accepted_ids))

    print("\nAccepted answer IDs:", len(accepted_ids))

    completed_batches = set(
        state["accepted_batches_done"]
    )

    for start in range(0, len(accepted_ids), 100):

        if STOP_COLLECTION:
            break

        batch = accepted_ids[start:start + 100]
        batch_number = start // 100

        if batch_number in completed_batches:
            continue

        ids = ";".join(map(str, batch))

        answers = api_get(
            f"answers/{ids}",
            {
                "pagesize": 100,
                "order": "desc",
                "sort": "votes"
            }
        )

        if STOP_COLLECTION:
            break

        added = add_answers_to_documents(
            documents,
            answers
        )

        print(
            f"Accepted batch {batch_number + 1}: "
            f"{added} answers added"
        )

        state["accepted_batches_done"].append(
            batch_number
        )

        save_checkpoint(state)

        time.sleep(0.2)

    # --------------------------------------------------------
    # Additional answers
    # --------------------------------------------------------

    question_ids = list(documents.keys())

    completed_batches = set(
        state["supplement_batches_done"]
    )

    print("\nCollecting additional answers...")

    for start in range(0, len(question_ids), 100):

        if STOP_COLLECTION:
            break

        batch = question_ids[start:start + 100]
        batch_number = start // 100

        if batch_number in completed_batches:
            continue

        ids = ";".join(batch)

        answers = api_get(
            f"questions/{ids}/answers",
            {
                "pagesize": 100,
                "order": "desc",
                "sort": "votes"
            }
        )

        if STOP_COLLECTION:
            break

        added = add_answers_to_documents(
            documents,
            answers
        )

        print(
            f"Additional answer batch "
            f"{batch_number + 1}: {added} answers added"
        )

        state["supplement_batches_done"].append(
            batch_number
        )

        save_checkpoint(state)

        time.sleep(0.2)

    # Keep the highest-scoring answers, including accepted answers.
    for document in documents.values():

        answers = document["answers"]

        answers.sort(
            key=lambda item: (
                item.get("is_accepted", False),
                item.get("score", 0)
            ),
            reverse=True
        )

        document["answers"] = answers[
            :MAX_ANSWERS_PER_QUESTION
        ]

    save_checkpoint(state)

    print("\nAnswer collection stage finished.")


# ============================================================
# 8. INCOMING LINK DERIVATION
# ============================================================

def derive_incoming_links(documents):

    print("\n========== INCOMING LINK DERIVATION ==========")

    question_url_map = {}
    answer_url_map = {}

    for question_id, document in documents.items():

        question_url = normalize_url(
            document.get("url", "")
        )

        if question_url:
            question_url_map[question_url] = question_id

        for answer in document.get("answers", []):

            answer_id = answer.get("answer_id")

            if answer_id:

                answer_url = normalize_url(
                    f"https://stackoverflow.com/a/{answer_id}"
                )

                answer_url_map[answer_url] = question_id

    # Reset incoming links before rebuilding.
    for document in documents.values():
        document["incoming_links"] = []

    incoming_count = 0

    for source_question_id, document in documents.items():

        sources = [
            (
                "question",
                None,
                document.get("internal_links", [])
            )
        ]

        for answer in document.get("answers", []):

            sources.append(
                (
                    "answer",
                    answer.get("answer_id"),
                    answer.get("internal_links", [])
                )
            )

        for source_type, source_answer_id, links in sources:

            for link in links:

                normalized = normalize_url(link)

                if not normalized:
                    continue

                target_question_id = None

                # Direct question URL.
                if normalized in question_url_map:

                    target_question_id = (
                        question_url_map[normalized]
                    )

                # Direct answer URL.
                elif normalized in answer_url_map:

                    target_question_id = (
                        answer_url_map[normalized]
                    )

                # Resolve /questions/{id}/...
                else:

                    match = re.search(
                        r"/questions/(\d+)",
                        normalized
                    )

                    if match:

                        possible_id = match.group(1)

                        if possible_id in documents:
                            target_question_id = possible_id

                    # Resolve /q/{id}
                    if not target_question_id:

                        match = re.search(
                            r"/q/(\d+)",
                            normalized
                        )

                        if match:

                            possible_id = match.group(1)

                            if possible_id in documents:
                                target_question_id = possible_id

                if not target_question_id:
                    continue

                target_document = documents[
                    target_question_id
                ]

                target_document["incoming_links"].append({

                    "source_question_id": int(
                        source_question_id
                    ),

                    "source_type": source_type,

                    "source_answer_id": source_answer_id,

                    "source_url": document.get("url", "")

                })

                incoming_count += 1

    print("Incoming links derived:", incoming_count)

    return incoming_count


# ============================================================
# 9. FINAL OUTPUT
# ============================================================

def save_final_dataset(documents):

    output = list(documents.values())

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

    print("\nFinal dataset saved:")
    print(OUTPUT_FILE)


# ============================================================
# 10. COLLECTION SUMMARY
# ============================================================

def print_summary(documents):

    counts = category_counts(documents)

    total_questions = len(documents)

    total_answers = sum(
        len(document.get("answers", []))
        for document in documents.values()
    )

    questions_with_answers = sum(
        1
        for document in documents.values()
        if document.get("answers")
    )

    accepted_answers = sum(
        1
        for document in documents.values()
        for answer in document.get("answers", [])
        if answer.get("is_accepted")
    )

    question_outgoing = sum(
        len(document.get("outgoing_links", []))
        for document in documents.values()
    )

    question_internal = sum(
        len(document.get("internal_links", []))
        for document in documents.values()
    )

    question_external = sum(
        len(document.get("external_links", []))
        for document in documents.values()
    )

    answer_outgoing = sum(
        len(answer.get("outgoing_links", []))
        for document in documents.values()
        for answer in document.get("answers", [])
    )

    answer_internal = sum(
        len(answer.get("internal_links", []))
        for document in documents.values()
        for answer in document.get("answers", [])
    )

    answer_external = sum(
        len(answer.get("external_links", []))
        for document in documents.values()
        for answer in document.get("answers", [])
    )

    print("\n")
    print("=" * 50)
    print("       STACK OVERFLOW COLLECTION SUMMARY")
    print("=" * 50)

    print(f"Total questions: {total_questions}")
    print(f"Question target: {TARGET_QUESTIONS}")
    print(
        f"Remaining questions: "
        f"{max(0, TARGET_QUESTIONS - total_questions)}"
    )

    print(f"Total answers: {total_answers}")
    print(f"Questions with answers: {questions_with_answers}")
    print(f"Accepted answers collected: {accepted_answers}")

    print("\nQUESTION LINKS")
    print(f"Outgoing links: {question_outgoing}")
    print(f"Internal links: {question_internal}")
    print(f"External links: {question_external}")

    print("\nANSWER LINKS")
    print(f"Outgoing links: {answer_outgoing}")
    print(f"Internal links: {answer_internal}")
    print(f"External links: {answer_external}")

    print("\nAPI STATISTICS")
    print(f"API requests made: {API_REQUESTS}")
    print(f"Remaining API quota: {REMAINING_QUOTA}")

    print("\nCATEGORY DISTRIBUTION")

    for category, config in TOPIC_CONFIG.items():

        actual = counts.get(category, 0)

        print(
            f"{category:<20} "
            f"{actual:>5}/{config['target']}"
        )

    print("=" * 50)

    if total_questions >= TARGET_QUESTIONS:
        print("\nQuestion target reached!")
    else:
        print("\nQuestion target not yet reached.")

        if STOP_COLLECTION:
            print("API quota or request limit stopped collection.")

        print("Checkpoint has been saved.")
        print("Run the script again when API quota is available.")


# ============================================================
# 11. MAIN
# ============================================================

def main():

    print("=" * 50)
    print("TECHSEARCH - STACK OVERFLOW DATA COLLECTION")
    print("=" * 50)

    if not API_KEY:

        print("\nERROR: Stack Exchange API key not found.")
        print("Check that .env exists in the project root.")
        print("It must contain:")
        print("STACKEXCHANGE_API_KEY=your_actual_key")
        return

    print("\nAPI key detected.")
    print("The key will not be displayed.")

    state = load_checkpoint()

    documents = state["documents"]

    print("\nStarting question collection...")

    collect_questions(state)

    print("\nStarting answer collection...")

    if not STOP_COLLECTION:
        collect_answers(state)

    print("\nDeriving incoming links...")

    derive_incoming_links(documents)

    save_checkpoint(state)
    save_final_dataset(documents)

    print_summary(documents)

    session.close()


if __name__ == "__main__":
    main()
