"""
Elasticsearch IR Demo — 7 query types, all scored with BM25

The 7 query types demonstrated (menu options 1-7):
    1. Multi-match search
    2. Phrase search          (match_phrase)
    3. Prefix search          (match_phrase_prefix)
    4. Fuzzy search           (match + fuzziness)
    5. Wildcard search        (wildcard)
    6. Regular-expression search (regexp)
    7. Boolean query          (bool: must / should / must_not)

"""

import json
from elasticsearch import helpers
from es_connection import es

INDEX = "ir_demo"
JSON_FILE = "sample_movies.json"


# --------------------------------------------------------------------------
# 1. Index setup
# --------------------------------------------------------------------------
def build_index():
    if es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)

    es.indices.create(
        index=INDEX,
        settings={
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "similarity": {
                "bm25_similarity": {
                    "type": "BM25",
                    "k1": 1.2,  
                    "b": 0.75,  
                }
            },
        },
        mappings={
            "properties": {
                "id": {"type": "integer"},
                "title": {
                    "type": "text",
                    "similarity": "bm25_similarity",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "body": {
                    "type": "text",
                    "similarity": "bm25_similarity",
                },
                "url": {"type": "keyword"},
            }
        },
    )


def load_documents():
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        movies = json.load(f)

    actions = [
        {
            "_index": INDEX,
            "_id": doc_id,
            "_source": {
                "id": doc_id,
                "title": movie["title"],
                "body": movie["body"],
                "url": movie.get("URL", ""),
            },
        }
        for doc_id, movie in enumerate(movies, start=1)
    ]

    helpers.bulk(es, actions)
    es.indices.refresh(index=INDEX)
    print(f"Indexed {len(actions)} documents.\n")


# --------------------------------------------------------------------------
# 2. Helper
# --------------------------------------------------------------------------
def print_hits(result):
    hits = result["hits"]["hits"]
    if not hits:
        print("No results.\n")
        return
    print("\nResults:")
    for rank, hit in enumerate(hits, 1):
        s = hit["_source"]
        print(f"{rank}. {s['title']} | score={hit['_score']:.4f}")
    print()


# --------------------------------------------------------------------------
# 3. Query type demonstrations 
# --------------------------------------------------------------------------
def multi_match_search():
    query = input("  Query text (e.g. 'superhero saves the world'): ").strip()
    result = es.search(
        index=INDEX,
        query={"multi_match": {"query": query, "fields": ["title^2", "body"]}},
        size=5,
    )
    print_hits(result)


def phrase_search():
    print("  Example: 'dawn of justice' -> Batman v Superman: Dawn of Justice")
    phrase = input("Enter query: ").strip()
    result = es.search(
        index=INDEX,
        query={"match_phrase": {"title": {"query": phrase, "slop": 1}}},
        size=5,
    )
    print_hits(result)


def prefix_search():
    print("  Example: 'hobb' -> The Hobbit: ... titles")
    prefix = input("Enter query: ").strip()
    result = es.search(
        index=INDEX,
        query={"match_phrase_prefix": {"title": prefix}},
        size=5,
    )
    print_hits(result)


def fuzzy_search():
    print("  Example: 'supermn' (typo) -> Superman Returns")
    term = input("Enter query: ").strip()
    result = es.search(
        index=INDEX,
        query={
            "fuzzy": {
                "title": {
                    "value": term,
                    "fuzziness": "AUTO",
                    "rewrite": "scoring_boolean",
                }
            }
        },
        size=5,
    )
    print_hits(result)


def wildcard_search():
    print("  Example: '*Spider-Man*' -> The Amazing Spider-Man, etc.")
    pattern = input("Enter query: ").strip()
    result = es.search(
        index=INDEX,
        query={
            "wildcard": {
                "title.keyword": {
                    "value": pattern,
                    "case_insensitive": True,
                    "rewrite": "scoring_boolean",
                }
            }
        },
        size=5,
    )
    print_hits(result)


def regex_search():
    print("  Example: 'Pirates.*Caribbean.*' -> all Pirates of the Caribbean titles")
    pattern = input("Enter query: ").strip()
    result = es.search(
        index=INDEX,
        query={
            "regexp": {
                "title.keyword": {
                    "value": pattern,
                    "case_insensitive": True,
                    "rewrite": "scoring_boolean",
                }
            }
        },
        size=5,
    )
    print_hits(result)


def boolean_search():
    print("  Example: body mentions 'superhero' AND title has 'Batman' OR 'Superman',")
    print("           but title must NOT contain 'Returns'")
    result = es.search(
        index=INDEX,
        query={
            "bool": {
                "must": [
                    {"match": {"body": "superhero"}}
                ],
                "should": [
                    {"match": {"title": "Batman"}},
                    {"match": {"title": "Superman"}},
                ],
                "minimum_should_match": 1,
                "must_not": [
                    {"match_phrase": {"title": "Returns"}}
                ],
            }
        },
        size=10,
    )
    print_hits(result)


# --------------------------------------------------------------------------
# 4. Menu
# --------------------------------------------------------------------------
MENU = {
    "1": ("Multi-match search", multi_match_search),
    "2": ("Phrase search", phrase_search),
    "3": ("Prefix search", prefix_search),
    "4": ("Fuzzy search", fuzzy_search),
    "5": ("Wildcard search", wildcard_search),
    "6": ("Regular-expression search", regex_search),
    "7": ("Boolean query", boolean_search),
}


def print_menu():
    print("Choose a query type (all scored with BM25):")
    for key, (label, _) in MENU.items():
        print(f"  {key}. {label}")
    print("  exit. Quit")


def main():
    if not es.ping():
        raise RuntimeError("Elasticsearch is not running.")

    build_index()
    load_documents()

    while True:
        print_menu()
        choice = input("> ").strip().lower()

        if choice == "exit":
            break

        entry = MENU.get(choice)
        if not entry:
            print("Invalid choice.\n")
            continue

        _, fn = entry
        fn()


if __name__ == "__main__":
    main()
