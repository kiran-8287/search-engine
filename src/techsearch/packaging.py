"""Package the active release and the files needed to run a local demo."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

import yaml
from dotenv import dotenv_values

from .dense import load_encoder, model_path
from .io import dumps, file_hash, now
from .pipeline import RELEASE_ID

PUBLIC_FILES = (
    ".gitignore", "README.md", "pyproject.toml", "collect_mdn.py", "collect_stackoverflow.py",
    "config/evaluation-queries.tsv",
    "docs/ATTRIBUTION.md", "docs/CLEANUP_REPORT.md", "docs/CODE_MAP.md", "docs/DATA_DICTIONARY.md",
    "docs/DECISIONS.md", "docs/DEMO_RUN_SHEET.md", "docs/EXECUTION_REPORT.md", "docs/IMPLEMENTATION_STATUS.md",
    "docs/IR_LAB.md", "docs/MASTER_ARCHITECTURE.md", "docs/PROJECT_CONTEXT.md", "docs/SIMPLIFICATION_REPORT.md",
    "frontend/index.html", "frontend/lab.html", "frontend/assets/favicon.ico", "frontend/assets/css/site.css",
    "frontend/assets/js/shared.js", "frontend/assets/js/search.js", "frontend/assets/js/lab.js",
    "frontend/assets/js/lab-reports.js",
    "scripts/bootstrap.py", "scripts/package_demo.py", "scripts/start.py", "scripts/verify_app.py",
    *(f"src/techsearch/{name}.py" for name in (
        "__init__", "__main__", "api", "cli", "collection", "compression", "config", "corpus", "dense", "evaluation",
        "experiments", "feedback", "graph", "indexing", "io", "packaging", "pipeline", "preprocessing", "query",
        "repository", "retrieval", "service",
    )),
)
CREDENTIAL_NAMES = ("STACKEXCHANGE_API_KEY", "TECHSEARCH_ANNOTATION_API_KEY")
DEFAULT_FIELDS = {
    "search": ("field_weights", "k1", "b", "mu", "rrf_k", "candidate_depth", "max_results",
               "query_length", "query_tokens", "nesting", "expansion", "vocabulary_scan",
               "max_query_posting_occurrences", "dense_min_similarity", "dense_unanchored_min_similarity"),
    "dense": ("model", "revision", "chunk_tokens", "overlap_tokens", "batch_size"),
    "graph": ("damping", "tolerance", "iterations", "window", "weight"),
    "resources": ("seed", "max_artifact_bytes", "max_dense_bytes", "max_dense_passages", "postings_shard_rows"),
}
SCOPE_FIELDS = ("mdn_roots", "mdn_exclusions", "browser_tags", "so_exclusions", "so_targets")
EVALUATION_FIELDS = ("min_groups_per_split", "classes", "pool_depth", "recall_depth", "latency_repeats")


def demo_configs(settings):
    # Export known settings and reset paths and annotation connection details for a new installation.
    default = {section: {key: settings.default[section][key] for key in keys}
               for section, keys in DEFAULT_FIELDS.items()}
    default["paths"] = {"data": "data", "artifacts": "artifacts", "runtime": "data/runtime", "frontend": "frontend"}
    scope = {key: settings.scope[key] for key in SCOPE_FIELDS}
    evaluation = {key: settings.evaluation[key] for key in EVALUATION_FIELDS}
    annotation = settings.evaluation["annotation"]
    evaluation["annotation"] = {"endpoint": "https://api.openai.com/v1/chat/completions", "model": None,
                                "prompt_version": annotation["prompt_version"], "audit_fraction": annotation["audit_fraction"]}
    return {"config/default.yaml": default, "config/scope.yaml": scope, "config/evaluation.yaml": evaluation}


def credential_values(root):
    # Use configured values only to reject accidental copies in inputs.
    values = {os.getenv(key) for key in CREDENTIAL_NAMES}
    for name in (".env", ".env.example"):
        local = root / name
        if local.is_file():
            fields = dotenv_values(local, interpolate=False)
            values.update(fields.get(key) for key in CREDENTIAL_NAMES)
    return tuple(value.encode("utf-8") for value in values if value)


def reject_credentials(name, data, credentials):
    if any(value in data for value in credentials):
        raise ValueError(f"A configured credential was found in demo input {name}. Remove it before packaging.")


def archive_file(archive, name, source, credentials):
    # Follow no links from a normally allowed input into private local data.
    if source.resolve(strict=True) != source.absolute():
        raise ValueError("Demo input files must use direct paths.")
    tail = b""
    overlap = max((len(value) - 1 for value in credentials), default=0)
    with source.open("rb") as file, archive.open(name, "w", force_zip64=True) as packed:
        while chunk := file.read(1024 * 1024):
            if credentials:
                combined = tail + chunk
                reject_credentials(name, combined, credentials)
                tail = combined[-overlap:] if overlap else b""
            packed.write(chunk)


def package_demo(settings, release, output=None):
    root = settings.root
    if not RELEASE_ID.fullmatch(release.id):
        raise ValueError("Invalid demo release identifier.")
    output = (output or (settings.path("artifacts") / f"techsearch-demo-{release.id}.zip")).resolve()
    if output.exists():
        raise ValueError(f"Output already exists: {output}. Choose another filename.")
    credentials = credential_values(root)
    model = release.info["dense"]["model"] if release.info.get("dense") else None
    entries = {name: root / name for name in PUBLIC_FILES if (root / name).is_file()}
    release_prefix = f"artifacts/releases/{release.id}"
    for name in ("manifest.json", *release.info["files"]):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", name):
            raise ValueError("Unsafe release artifact filename.")
        entries[f"{release_prefix}/{name}"] = release.path / name
    if model:
        revision = model["revision"]
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Invalid demo encoder revision.")
        encoder = model_path(settings) / revision
        for filename in model["files"]:
            parts = PurePosixPath(filename).parts
            if (not parts or "/".join(parts) != filename
                    or not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part) for part in parts)
                    or not (Path(filename).suffix in {".json", ".txt", ".safetensors"}
                            or Path(filename).name == "README.md" or Path(filename).name.startswith("LICENSE"))):
                raise ValueError("Unsafe encoder artifact filename.")
            entries[f"artifacts/models/encoder/{revision}/{filename}"] = encoder / filename
        load_encoder(settings, model, verify=True)

    manifests = {
        "artifacts/releases/active.json": {"release_id": release.id},
        "bundle-manifest.json": {"release_id": release.id, "created_at": now(), "dense": bool(model),
                                 "storage_version": release.info["schema_version"], "python": "3.11 or 3.12",
                                 "purpose": "local demonstration", "release_manifest_sha256": file_hash(release.path / "manifest.json"),
                                 "encoder_revision": model["revision"] if model else None},
    }
    if model:
        manifests["artifacts/models/encoder/active.json"] = model
    generated = {name: (dumps(value) + "\n").encode("utf-8") for name, value in manifests.items()}
    generated.update({name: yaml.safe_dump(value, sort_keys=False).encode("utf-8")
                      for name, value in demo_configs(settings).items()})
    generated[".env.example"] = "".join(f"{key}=\n" for key in CREDENTIAL_NAMES).encode("utf-8")
    for name in entries:
        reject_credentials("an archive filename", name.encode("utf-8"), credentials)
    for name, data in generated.items():
        reject_credentials(name, data, credentials)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as file:
            temporary = Path(file.name)
        with ZipFile(temporary, mode="w", compression=ZIP_DEFLATED, compresslevel=4, allowZip64=True) as archive:
            for name, source in entries.items():
                archive_file(archive, name, source, credentials)
            for name, data in generated.items():
                archive.writestr(name, data)
        if output.exists():
            raise ValueError(f"Output appeared while preparing the bundle: {output}")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"release_id": release.id, "dense": bool(model), "bundle": str(output), "bytes": output.stat().st_size}
