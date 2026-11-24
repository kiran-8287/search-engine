"""Portable, explicit commands for local construction and research."""
from __future__ import annotations

import argparse
import importlib.metadata
import os
import sys
from pathlib import Path

from . import collection, corpus, dense, evaluation, experiments, graph, pipeline
from .config import load_settings
from .io import now, write_json
from .query import MODES
from .service import SearchService

DEFAULT_WORKLOAD = ["Promise.all", "css grid", "event delegation", "aria-live", "CORS preflight", "=== value"]


def doctor(settings, offline=False):
    packages = {}
    for package in ("techsearch", "beautifulsoup4", "fastapi", "httpx", "markdown-it-py", "numpy",
                    "python-dotenv", "PyYAML", "requests", "uvicorn", "sentence-transformers",
                    "huggingface-hub", "scipy", "scikit-learn", "pytest", "pytest-playwright"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    result = {"python": sys.version.split()[0], "supported": (3, 11) <= sys.version_info[:2] < (3, 13),
              "packages": packages, "config_fingerprint": settings.fingerprint,
              "credentials_present": {key: bool(os.environ.get(key)) for key in
                                      ("STACKEXCHANGE_API_KEY", "TECHSEARCH_ANNOTATION_API_KEY")},
              "stages": pipeline.status(settings)}
    if offline:
        service = SearchService(settings, pipeline.open_release(settings, verify=True))
        lexical = service.search("source:mdn OR source:stackoverflow", mode="boolean")
        if not lexical["results"]:
            raise ValueError("Offline lexical readiness search returned no canonical parents.")
        result["offline"] = {"release_id": service.release.id, "lexical": "ready", "dense": "not-built"}
        if service.release.info.get("dense"):
            dense.load_encoder(settings, service.release.info["dense"]["model"], verify=True)
            semantic = service.search("browser event propagation", mode="semantic")
            result["offline"]["dense"] = "encoder and exact search available"
            result["offline"]["dense_result_count"] = len(semantic["results"])
    return result


def sealed(args):
    if args.split == "test" and not args.confirm_sealed:
        raise ValueError("For test execution, finalize settings using development only and pass --confirm-sealed.")


def parser():
    cli = argparse.ArgumentParser(prog="techsearch", description=__doc__)
    cli.add_argument("--root", type=Path, help="Project directory containing config, frontend and collectors")
    commands = cli.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("doctor", help="Print dependencies, configured credential presence and stages")
    cmd.add_argument("--offline", action="store_true", help="Explicitly check the active release, including its local encoder")
    for name, help_text in (
        ("status", "Show pipeline stage and raw availability"),
        ("inspect-data", "Inspect raw exports and scope without altering the exports"),
        ("preprocess", "Build or reuse a canonical JSONL snapshot"),
        ("build-graph", "Recompute the active release's induced MDN graph and save diagnostics"),
        ("freeze-evaluation", "Freeze benchmark intent IDs, text, classes and splits"),
    ):
        commands.add_parser(name, help=help_text)
    cmd = commands.add_parser("collect", help="Explicit network acquisition using a supplied collector")
    cmd.add_argument("--source", required=True, choices=tuple(corpus.RAW_FILES))
    cmd.add_argument("--revision", help="MDN content commit SHA. The first acquisition resolves main when omitted.")
    cmd.add_argument("--target", type=int, default=5000, help="Stack Overflow staged target")
    cmd.add_argument("--resume", action="store_true", help="Resume through the saved collector checkpoint")
    for name, help_text in (("collect-compat", "Acquire and map a pinned browser-compat-data archive"),
                            ("download-model", "Explicitly download and locally pin the configured encoder")):
        cmd = commands.add_parser(name, help=help_text)
        if name == "collect-compat":
            cmd.add_argument("--revision", help="Full BCD commit SHA")
    for name, help_text in (("build-indexes", "Build and activate an immutable lexical or dense release"),
                            ("pipeline", "Resume offline from available raw files and cached artifacts")):
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("--lexical-only", action="store_true", help="Skip dense artifacts even if a local encoder exists")
        if name == "pipeline":
            cmd.add_argument("--resume", action="store_true", required=True, help="Resume offline stages")
    cmd = commands.add_parser("validate-release", help="Verify active artifact checksums and structure")
    cmd.add_argument("--deep", action="store_true", help="Read every document and cross-check every compressed posting")
    cmd = commands.add_parser("search", help="Search from the same service used by the API")
    cmd.add_argument("query")
    cmd.add_argument("--mode", choices=("auto", *MODES), default="auto")
    cmd.add_argument("--source", choices=tuple(corpus.RAW_FILES))
    cmd.add_argument("--topic")
    cmd.add_argument("--ranker", choices=("bm25", "tfidf", "likelihood"), default="bm25")
    cmd.add_argument("--strategy", choices=("taat", "daat"), default="taat")
    cmd.add_argument("--depth", type=int)
    cmd = commands.add_parser("experiments", help="Run measured offline retrieval experiments")
    cmd.add_argument("--suite", choices=("compression", "taat-daat", "retrieval", "latent", "all"), default="all")
    cmd.add_argument("--query", action="append", help="Repeat for an explicit workload")
    cmd.add_argument("--repeats", type=int, default=3)
    cmd.add_argument("--sample", type=int, default=2500, help="Maximum sample for LSI and K-means")
    cmd.add_argument("--components", type=int, default=48)
    cmd.add_argument("--clusters", type=int, default=12)
    for name in ("benchmark", "evaluate"):
        cmd = commands.add_parser(name, help=f"{name.capitalize()} a frozen development or sealed test split")
        cmd.add_argument("--split", required=True, choices=("dev", "test"))
        cmd.add_argument("--confirm-sealed", action="store_true")
        cmd.add_argument("--ablations", action="store_true")
        if name == "evaluate":
            cmd.add_argument("--annotate", action="store_true", help="Explicitly send pooled evidence to the configured provider")
            cmd.add_argument("--limit", type=int, default=50, help="New pooled judgments allowed in this invocation")
    cmd = commands.add_parser("serve", help="Start the app against an existing release")
    cmd.add_argument("--host", default="localhost")
    cmd.add_argument("--port", type=int, default=8000)
    cmd = commands.add_parser("package-demo", help="Write an offline local demonstration ZIP from the active release")
    cmd.add_argument("--output", type=Path)
    return cli


def as_report(service, args):
    settings, release = service.settings, service.release
    if not 1 <= args.repeats <= 25 or not 4 <= args.sample <= 15000 or not 2 <= args.components <= 256 or not 2 <= args.clusters <= 128:
        raise ValueError("Experiment workload exceeds its allowed range.")
    workload = args.query or DEFAULT_WORKLOAD
    if len(workload) > 100 or any(len(query) > settings.search["query_length"] for query in workload):
        raise ValueError("Use a workload of at most 100 permitted queries.")
    output = {}
    if args.suite in {"all", "compression"}:
        report = experiments.compression_report(release, workload, args.repeats)
        output["compression"] = experiments.save_report(settings, release, "compression", report)
    if args.suite in {"all", "taat-daat"}:
        measured = experiments.execution_report(service, workload, args.repeats)
        output["taat-daat"] = experiments.save_report(settings, release, "taat-daat",
                                                      {"queries": workload, "rows": measured, "repeats": args.repeats,
                                                       "note": "Fresh readers reuse the OS file cache. Python tracing adds overhead."})
    if args.suite in {"all", "latent"}:
        latent = experiments.latent_report(service, args.sample, args.components, args.clusters,
                                           settings.default["resources"]["seed"], workload)
        output["latent"] = experiments.save_report(settings, release, "latent", latent)
    if args.suite in {"all", "retrieval"}:
        output["retrieval"] = experiments.save_report(settings, release, "retrieval",
                                                       experiments.retrieval_report(service, workload))
    return {name: {"release_id": item["release_id"], "created_at": item["created_at"]} for name, item in output.items()}


def dispatch(args, settings):
    name = args.command
    if name == "doctor":
        return doctor(settings, args.offline)
    if name == "status":
        return pipeline.status(settings)
    if name == "inspect-data":
        details = corpus.inspect(settings)
        write_json(settings.path("data") / "manifests/raw-inspection.json", {"at": now(), "sources": details})
        return details
    if name == "collect":
        if args.revision and args.source != "mdn":
            raise ValueError("Revision applies to MDN only.")
        return collection.collect(settings, args.source, revision=args.revision, target=args.target)
    if name == "collect-compat":
        return collection.collect_compat(settings, args.revision)
    if name in {"preprocess", "build-indexes", "download-model", "pipeline", "freeze-evaluation"}:
        with pipeline.writer_lock(settings.root):
            if name == "preprocess":
                return pipeline.preprocess(settings)
            if name == "build-indexes":
                return pipeline.build(settings, args.lexical_only)
            if name == "download-model":
                return dense.download_model(settings)
            if name == "freeze-evaluation":
                item = evaluation.freeze(settings)
                return {"protocol": item["group_fingerprint"], "intent_groups": len(item["groups"])}
            canonical = pipeline.preprocess(settings)
            release = pipeline.build(settings, args.lexical_only)
            return {"canonical": canonical["id"], "release": release["release_id"], "dense": bool(release["dense"])}
    if name == "serve":
        import uvicorn

        from .api import create_app

        if not 1 <= args.port <= 65535:
            raise ValueError("Port must be between 1 and 65535.")
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return None
    if name == "validate-release":
        release = pipeline.open_release(settings, verify=True, deep=args.deep)
        return {"release_id": release.id, "status": "validated", "deep": args.deep}
    release = pipeline.open_release(settings, verify=name == "package-demo")
    if name == "build-graph":
        output = settings.path("artifacts") / "reports" / release.id / "graph-ranks.json"
        measured = graph.build_graph(release.path, release.info["graph_config"], output=output)
        return experiments.save_report(settings, release, "graph", measured)
    if name == "package-demo":
        from .packaging import package_demo

        return package_demo(settings, release, args.output)
    service = SearchService(settings, release)
    if name == "search":
        return service.search(args.query, mode=args.mode, source=args.source, topic=args.topic, ranker=args.ranker,
                              strategy=args.strategy, depth=args.depth)
    if name == "experiments":
        return as_report(service, args)
    if name == "benchmark":
        sealed(args)
        return evaluation.benchmark(settings, service, args.split, ablations=args.ablations)
    if name == "evaluate":
        sealed(args)
        if not 1 <= args.limit <= 200:
            raise ValueError("Use an annotation budget between 1 and 200 judgments.")
        with pipeline.writer_lock(settings.root):
            return evaluation.evaluate(settings, service, args.split, annotate=args.annotate,
                                       limit=args.limit, ablations=args.ablations)
    raise ValueError("Unknown command.")


def main(argv=None):
    import json

    args = parser().parse_args(argv)
    try:
        settings = load_settings(args.root)
        result = dispatch(args, settings)
        if result is not None:
            print(json.dumps(result, indent=2, ensure_ascii=True))
        if isinstance(result, dict) and result.get("status") in {"blocked", "partial"}:
            return 2
        if args.command == "doctor" and not result["supported"]:
            return 2
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Saved checkpoints and active releases are retained.", file=sys.stderr)
        return 130
    except (KeyError, ImportError, LookupError, OSError, ValueError, RuntimeError) as error:
        print(f"TechSearch: {error}", file=sys.stderr)
        return 2
