from __future__ import annotations

import math
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .io import digest

REPO = Path(__file__).resolve().parents[2]
FIELDS = ("title", "heading", "body", "code", "question", "answer", "tag")
METADATA = ("source", "topic", "tag")


def load_yaml(path):
    with path.open(encoding="utf-8") as file:
        value = yaml.safe_load(file)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a configuration mapping in {path}")
    return value


@dataclass(frozen=True)
class Settings:
    root: Path
    default: dict
    scope: dict
    evaluation: dict

    def path(self, key):
        return (self.root / self.default["paths"][key]).resolve()

    @property
    def search(self):
        return self.default["search"]

    @property
    def dense(self):
        return self.default["dense"]

    @property
    def fingerprint(self):
        return digest({"settings": self.default, "scope": self.scope, "evaluation": self.evaluation})


def load_settings(root=None):
    root = Path(root or os.environ.get("TECHSEARCH_PROJECT_DIR") or REPO).resolve()
    load_dotenv(root / ".env", override=False)
    default = load_yaml(root / "config/default.yaml")
    scope = load_yaml(root / "config/scope.yaml")
    evaluation = load_yaml(root / "config/evaluation.yaml")
    sections = {"default": default, "scope": scope, "evaluation": evaluation}
    for name, raw in os.environ.items():
        if not name.startswith("TECHSEARCH_CFG__"):
            continue
        keys = name.removeprefix("TECHSEARCH_CFG__").lower().split("__")
        if keys[0] not in sections:
            keys.insert(0, "default")
        node = sections
        for key in keys[:-1]:
            if not isinstance(node, dict) or key not in node:
                raise ValueError(f"Unknown configuration override {name}")
            node = node[key]
        if not isinstance(node, dict) or keys[-1] not in node:
            raise ValueError(f"Unknown configuration override {name}")
        node[keys[-1]] = yaml.safe_load(raw)
    settings = Settings(root, deepcopy(default), scope, evaluation)
    search, dense = settings.search, settings.dense
    if set(search["field_weights"]) != set(FIELDS) or any(
        not math.isfinite(weight) or not 0 < weight <= 20 for weight in search["field_weights"].values()
    ):
        raise ValueError("Field weights must cover exactly the lexical fields and be between 0 and 20.")
    if not 0 <= search["b"] <= 1 or not 0 < search["k1"] <= 5 or not 0 < search["mu"] <= 10000:
        raise ValueError("Invalid lexical ranking parameters.")
    for key in ("query_length", "query_tokens", "nesting", "expansion", "vocabulary_scan", "max_query_posting_occurrences",
                "candidate_depth", "max_results", "rrf_k"):
        if type(search[key]) is not int or search[key] < 1:
            raise ValueError(f"Invalid positive integer search.{key}")
    if (not search["max_results"] <= search["candidate_depth"] <= 1000
            or not 0 < search["dense_min_similarity"] <= search["dense_unanchored_min_similarity"] < 1):
        raise ValueError("Invalid candidate budget or dense cutoff.")
    if not 0 <= dense["overlap_tokens"] < dense["chunk_tokens"] <= 254 or not 1 <= dense["batch_size"] <= 512:
        raise ValueError("Invalid dense batching or chunk limits.")
    graph = settings.default["graph"]
    if (not 0 < graph["damping"] < 1 or not 0 < graph["tolerance"] < 1
            or type(graph["iterations"]) is not int or graph["iterations"] < 1
            or type(graph["window"]) is not int or not 1 <= graph["window"] <= 1000
            or not 0 <= graph["weight"] <= 1):
        raise ValueError("Invalid graph parameters.")
    for name in ("max_artifact_bytes", "max_dense_bytes", "max_dense_passages", "postings_shard_rows"):
        if settings.default["resources"][name] < 1:
            raise ValueError(f"Invalid resource budget {name}")
    return settings
