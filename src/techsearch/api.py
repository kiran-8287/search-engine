"""Versioned one-origin API with bounded requests and fixed search snapshots."""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .config import load_settings
from .dense import DenseUnavailable
from .evaluation import GROQ_PROFILE, GROQ_PROMPT, GROQ_RUN, lab_settings, matches_groq_report, matches_lab_run
from .feedback import SnapshotMissing, search_id
from .io import WorkloadError, digest, read_json
from .pipeline import RELEASE_ID, ReleaseUnavailable, open_release, status
from .query import QueryError
from .repository import Documents
from .service import SearchService, document_detail, page_of

Mode = Literal["auto", "keyword", "boolean", "phrase", "prefix", "fuzzy", "semantic", "hybrid", "field"]
Source = Literal["mdn", "stackoverflow"]
Ranker = Literal["bm25", "tfidf", "likelihood"]
SESSION = re.compile("[a-f0-9]{32}")
REPORTS = {"compression", "taat-daat", "graph", "latent", "retrieval", "benchmark-dev", "benchmark-test",
           "evaluation-dev", "evaluation-test", "ablations-dev", "ablations-test",
           "evaluation-ablations-dev", "evaluation-ablations-test",
           "lab-dev", "lab-test", "evaluation-lab-dev", "evaluation-lab-test", GROQ_RUN, "evaluation-" + GROQ_RUN}


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    query: str = Field(default="", max_length=2048)
    mode: Mode = "auto"
    source: Source | None = None
    topic: str | None = Field(default=None, max_length=50)
    ranker: Ranker = "bm25"
    strategy: Literal["taat", "daat"] = "taat"
    k1: float | None = Field(default=None, gt=0, le=5)
    b: float | None = Field(default=None, ge=0, le=1)
    rrf_k: int | None = Field(default=None, ge=1, le=500)
    cutoff: float | None = Field(default=None, gt=0, lt=1)
    depth: int | None = Field(default=None, ge=1, le=1000)
    authority: bool = False
    diversify: bool = False
    apply_feedback: bool = False
    page_size: int = Field(default=10, ge=1, le=25)


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: SearchRequest
    right: SearchRequest


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    document: str = Field(min_length=1, max_length=450)
    value: Literal[-1, 1]


def get_session(request, response):
    value = request.cookies.get("techsearch_session")
    if not value or not SESSION.fullmatch(value):
        value = search_id()
        response.set_cookie("techsearch_session", value, httponly=True, samesite="strict", max_age=7 * 86400,
                            secure=request.url.scheme == "https")
    return value


def create_app(settings=None):
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = None
        app.state.problem = None
        try:
            app.state.service = SearchService(settings, open_release(settings, verify=True), persistent=True)
        except (ReleaseUnavailable, OSError, ValueError, KeyError, TypeError) as error:
            app.state.problem = str(error)
        yield

    app = FastAPI(title="TechSearch", version="1", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url="/api/v1/openapi.json")
    frontend = settings.path("frontend")

    def service():
        if app.state.service is None:
            raise HTTPException(503, app.state.problem or "Release unavailable. Run preprocess and build-indexes.")
        return app.state.service

    def run(body, session):
        options = body.model_dump(exclude={"page_size"})
        options.pop("query")
        try:
            return page_of(service().search(body.query, session=session, **options), 1, body.page_size)
        except (QueryError, WorkloadError) as error:
            raise HTTPException(422, str(error)) from error
        except DenseUnavailable as error:
            raise HTTPException(503, str(error)) from error

    def snapshot_for(sid, request, response):
        try:
            return service().runtime.get(get_session(request, response), sid)
        except SnapshotMissing as error:
            raise HTTPException(404, str(error)) from error

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(frontend / "index.html")

    @app.get("/lab", include_in_schema=False)
    def lab():
        return FileResponse(frontend / "lab.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(frontend / "assets" / "favicon.ico", media_type="image/vnd.microsoft.icon")

    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/api/v1/health")
    def health():
        return {"status": "alive"}

    @app.get("/api/v1/readiness")
    def ready():
        active = service()
        return {"status": "ready", "release_id": active.release.id, "dense_index": bool(active.release.info.get("dense")),
                "dense_error": active.dense_error}

    @app.get("/api/v1/filters")
    def filters():
        return {"source": ["mdn", "stackoverflow"],
                "topic": sorted(set(settings.scope["mdn_roots"].values()) | set(settings.scope["browser_tags"]))}

    @app.post("/api/v1/search")
    def search(body: SearchRequest, request: Request, response: Response):
        return run(body, get_session(request, response))

    @app.get("/api/v1/search/{sid}")
    def search_page(sid: str, request: Request, response: Response,
                    page: int = Query(1, ge=1, le=1000), size: int = Query(10, ge=1, le=25)):
        return page_of(snapshot_for(sid, request, response), page, size)

    @app.get("/api/v1/documents/{stable:path}")
    def document(stable: str, release: str | None = Query(None, pattern=r"^[a-f0-9]{24}$")):
        try:
            active = service()
            if release and release != active.release.id:
                archived = open_release(settings, release)
                return document_detail(Documents(archived.path), archived.id, stable)
            return active.document(stable)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ReleaseUnavailable as error:
            raise HTTPException(404, str(error)) from error

    @app.get("/api/v1/suggestions")
    def suggestions(q: str = Query("", max_length=80)):
        return {"suggestions": service().suggestions(q)}

    @app.post("/api/v1/feedback", status_code=204)
    def feedback(body: Judgment, request: Request, response: Response):
        try:
            service().runtime.judge(get_session(request, response), body.search_id, body.document, body.value)
        except SnapshotMissing as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.post("/api/v1/compare")
    def compare(body: Comparison, request: Request, response: Response):
        session = get_session(request, response)
        result = {}
        for name, options in (("left", body.left), ("right", body.right)):
            try:
                result[name] = run(options, session)
            except HTTPException as error:
                result[name] = {"error": error.detail, "status": error.status_code}
        return result

    @app.get("/api/v1/index")
    def index():
        active = service()
        info = active.release.info
        return {"release_id": active.release.id, "lexical": info["lexical"],
                "dense": {k: v for k, v in info["dense"].items() if k != "model"} if info["dense"] else None,
                "artifact_bytes": sum(item["bytes"] for item in info["files"].values()), "seconds": info["seconds"]}

    def saved_report(name, release_id):
        path = settings.path("artifacts") / "reports" / release_id / f"{name}.json"
        if not path.is_file():
            return None
        try:
            saved = read_json(path)
        except (OSError, ValueError) as error:
            raise HTTPException(409, "The saved report could not be read.") from error
        if not isinstance(saved, dict) or saved.get("name") != name or saved.get("release_id") != release_id:
            raise HTTPException(409, "The saved report does not match the selected release or report.")
        report = saved.get("report")
        if not isinstance(report, dict) or report.get("release_id", release_id) != release_id:
            raise HTTPException(409, "The saved report does not match the selected release or report.")
        split = name.rsplit("-", 1)[-1]
        if split in {"dev", "test"} and report.get("split", split) != split:
            raise HTTPException(409, "The saved report does not match the selected split.")
        return {"status": report.get("status", "available"), **saved}

    def load_report(name, release_id=None):
        if name not in REPORTS:
            raise HTTPException(404, "Unknown report.")
        active = service().release
        selected_id = release_id or active.id
        use_active = selected_id == active.id
        if not use_active and not (settings.path("artifacts") / "reports" / selected_id).is_dir():
            raise HTTPException(404, "Unknown report release.")
        # Existing Graph clients receive the graph embedded in the active build.
        if name == "graph" and release_id is None:
            return {"name": name, "status": "available", "release_id": active.id, "report": active.info["graph"]}
        saved = saved_report(name, selected_id)
        if saved is not None:
            return saved
        if use_active and name == "graph":
            return {"name": name, "status": "build-only", "release_id": active.id, "report": active.info["graph"]}
        if use_active and name == "compression":
            return {"name": name, "status": "build-only", "release_id": active.id,
                    "report": {"codecs": active.info["lexical"]["compression"]}}
        return {"name": name, "status": "not-run", "release_id": selected_id}

    @app.get("/api/v1/report-inventory")
    def report_inventory():
        active_id = service().release.id
        directory = settings.path("artifacts") / "reports"
        historical = sorted(path.name for path in directory.glob("*")
                            if path.is_dir() and RELEASE_ID.fullmatch(path.name) and path.name != active_id)
        releases = {}
        for release_id in [active_id, *historical]:
            availability = {}
            for name in sorted(REPORTS):
                try:
                    saved = saved_report(name, release_id)
                except HTTPException:
                    availability[name] = "invalid"
                    continue
                if saved is not None:
                    availability[name] = saved["status"]
                elif release_id == active_id and name in {"graph", "compression"}:
                    availability[name] = "build-only"
            if availability or release_id == active_id:
                releases[release_id] = availability

        protocol = {key: settings.evaluation[key] for key in ("pool_depth", "recall_depth", "latency_repeats")}
        frozen = settings.path("data") / "evaluation" / "frozen.json"
        if frozen.is_file():
            try:
                catalog = read_json(frozen)
                protocol["groups"] = {split: sum(group["split"] == split for group in catalog["groups"])
                                      for split in ("dev", "test")}
                protocol["fingerprint"] = catalog["group_fingerprint"]
            except (OSError, ValueError, KeyError, TypeError):
                protocol["catalog_unavailable"] = True
        return {"active_release_id": active_id, "releases": releases, "protocol": protocol}

    @app.get("/api/v1/reports/{name}")
    def report(name: str, release: str | None = Query(None, pattern=r"^[a-f0-9]{24}$")):
        return load_report(name, release)

    @app.get("/api/v1/lab")
    def lab_measurements(response: Response):
        """Resolve the Lab data against the same release used by Search."""
        active = service().release
        response.headers["Cache-Control"] = "no-store"
        result = {"release_id": active.id, "documents": active.info["lexical"]["parents"],
                  "configuration": settings.fingerprint, "measurement": None, "quality": None,
                  "experiment_settings": lab_settings(settings),
                  "search_settings": {key: settings.search[key] for key in ("max_results", "k1", "b", "rrf_k")}}
        try:
            frozen = read_json(settings.path("data") / "evaluation" / "frozen.json")
            protocol = frozen["group_fingerprint"]
            groups = frozen["groups"]
            if protocol != digest(groups) or not all(isinstance(group, dict) for group in groups):
                return result
        except (OSError, ValueError, KeyError, TypeError):
            return result
        try:
            subset = saved_report(GROQ_RUN, active.id)
            profile = read_json(settings.path("data") / "evaluation" / f"{GROQ_PROFILE}.json") if subset else None
            full = saved_report("lab-dev", active.id) if subset else None
            if (subset and full and full["report"].get("run_id") == profile.get("source_run_id")
                    and matches_groq_report(settings, subset["report"], profile, active.id, protocol)):
                result["measurement"] = subset["report"]
                result["full_development_timing"] = True
                graded = saved_report("evaluation-" + GROQ_RUN, active.id)
                if graded:
                    quality = graded["report"]
                    if (quality.get("profile") == GROQ_PROFILE and quality.get("protocol") == profile["protocol"]
                            and quality.get("prompt_version") == GROQ_PROMPT
                            and quality.get("measurement_run_id") == subset["report"]["run_id"]):
                        result["quality"] = quality
                return result
        except (HTTPException, OSError, ValueError, KeyError, AttributeError, TypeError):
            if result["measurement"]:
                return result
        for split in ("test", "dev"):
            try:
                saved = saved_report(f"lab-{split}", active.id)
            except HTTPException:
                continue
            if not saved:
                continue
            run = saved["report"]
            query_count = sum(group.get("split") == split for group in groups)
            paired = run.get("paired_queries")
            if (not matches_lab_run(settings, run, active.id, split, protocol)
                    or run.get("query_count") != query_count or not run.get("run_id")
                    or type(paired) is not int or not 0 < paired <= query_count):
                continue
            result["measurement"] = run
            try:
                graded = saved_report(f"evaluation-lab-{split}", active.id)
            except HTTPException:
                graded = None
            if graded:
                quality = graded["report"]
                prompt = settings.evaluation["annotation"]["prompt_version"]
                if (quality.get("measurement_run_id") == run["run_id"] and quality.get("protocol") == protocol
                        and quality.get("prompt_version", prompt) == prompt):
                    result["quality"] = quality
            break
        return result

    @app.get("/api/v1/benchmarks/{split}")
    def benchmarks(split: Literal["dev", "test"], release: str | None = Query(None, pattern=r"^[a-f0-9]{24}$")):
        return load_report(f"benchmark-{split}", release)

    @app.get("/api/v1/pipeline")
    def pipeline():
        stages = status(settings)
        return {name: ({key: item[key] for key in ("status", "reason", "release_id", "shortfall", "id", "revision") if key in item}
                       if isinstance(item, dict) and name != "raw" else item) for name, item in stages.items()}

    @app.get("/api/v1/exports/reports/{name}")
    def report_export(name: str, response: Response, release: str | None = Query(None, pattern=r"^[a-f0-9]{24}$")):
        result = load_report(name, release)
        filename = f"{name}-{result['release_id']}.json" if release else f"{name}.json"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return result

    @app.get("/api/v1/exports/search/{sid}")
    def snapshot_export(sid: str, request: Request, response: Response):
        result = snapshot_for(sid, request, response)
        response.headers["Content-Disposition"] = 'attachment; filename="techsearch-results.json"'
        return result

    return app
