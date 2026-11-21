"""Prepare a local, versioned demonstration bundle from an existing release."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .dense import load_encoder, model_path
from .io import dumps, file_hash, now


def package_demo(settings, release, output=None):
    root = settings.root
    output = (output or (settings.path("artifacts") / f"techsearch-demo-{release.id}.zip")).resolve()
    model = release.info["dense"]["model"] if release.info.get("dense") else None
    if model:
        load_encoder(settings, model, verify=True)
    if output.exists():
        raise ValueError(f"Output already exists: {output}. Choose another filename.")
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = {}
    for name in (".env.example", ".gitignore", "README.md", "pyproject.toml", "collect_mdn.py", "collect_stackoverflow.py"):
        entries[name] = root / name
    for section in ("config", "docs", "frontend", "scripts", "src"):
        for source in sorted((root / section).rglob("*")):
            relative = source.relative_to(root)
            if (source.is_file() and source.suffix in {".py", ".yaml", ".tsv", ".html", ".css", ".js", ".md"}
                    and not any(name.startswith(".") or name == "__pycache__" for name in relative.parts)):
                entries[relative.as_posix()] = source
    release_prefix = f"artifacts/releases/{release.id}"
    for name in ("manifest.json", *release.info["files"]):
        entries[f"{release_prefix}/{name}"] = release.path / name
    if model:
        prefix = f'artifacts/models/encoder/{model["revision"]}'
        for filename in model["files"]:
            entries[f"{prefix}/{filename}"] = model_path(settings) / model["revision"] / filename
    reports = settings.path("artifacts") / "reports" / release.id
    for path in sorted(reports.glob("*")):
        if path.is_file() and path.suffix in {".json", ".csv"}:
            entries[f"artifacts/reports/{release.id}/{path.name}"] = path
    active = {
        "artifacts/releases/active.json": {"release_id": release.id},
        "bundle-manifest.json": {"release_id": release.id, "created_at": now(), "dense": bool(model),
                                 "storage_version": release.info["schema_version"], "python": "3.11 or 3.12",
                                 "purpose": "local demonstration", "release_manifest_sha256": file_hash(release.path / "manifest.json"),
                                 "encoder_revision": model["revision"] if model else None}
    }
    if model:
        active["artifacts/models/encoder/active.json"] = model

    import yaml

    # Portable bundles always use internal paths, even if the build used external paths.
    bundled_config = {**settings.default, "paths": {"data": "data", "artifacts": "artifacts",
                                                     "runtime": "data/runtime", "frontend": "frontend"}}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as file:
            temporary = Path(file.name)
        with ZipFile(temporary, mode="w", compression=ZIP_DEFLATED, compresslevel=4, allowZip64=True) as archive:
            for name, source in entries.items():
                if name not in {"config/default.yaml", "config/scope.yaml", "config/evaluation.yaml"}:
                    archive.write(source, arcname=name)
            archive.writestr("config/default.yaml", yaml.safe_dump(bundled_config, sort_keys=False))
            archive.writestr("config/scope.yaml", yaml.safe_dump(settings.scope, sort_keys=False))
            archive.writestr("config/evaluation.yaml", yaml.safe_dump(settings.evaluation, sort_keys=False))
            for name, value in active.items():
                archive.writestr(name, dumps(value) + "\n")
        if output.exists():
            raise ValueError(f"Output appeared while preparing the bundle: {output}")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"release_id": release.id, "dense": bool(model), "bundle": str(output), "bytes": output.stat().st_size}
