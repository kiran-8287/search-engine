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
from .feedback import SnapshotMissing, search_id
from .io import WorkloadError, read_json
from .pipeline import ReleaseUnavailable, open_release, status
from .query import QueryError
from .repository import Documents
from .service import SearchService, document_detail, page_of

Mode = Literal["auto", "keyword", "boolean", "phrase", "prefix", "fuzzy", "semantic", "hybrid", "field"]
Source = Literal["mdn", "stackoverflow"]
Ranker = Literal["bm25", "tfidf", "likelihood"]
SESSION = re.compile("[a-f0-9]{32}")
REPORTS = {"compression", "taat-daat", "graph", "latent", "retrieval", "benchmark-dev", "benchmark-test",
           "evaluation-dev", "evaluation-test", "ablations-dev", "ablations-test",
           "evaluation-ablations-dev", "evaluation-ablations-test"}


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

    def load_report(name):
        if name not in REPORTS:
            raise HTTPException(404, "Unknown report.")
        active = service()
        if name == "graph":
            return {"name": name, "status": "available", "release_id": active.release.id, "report": active.release.info["graph"]}
        path = settings.path("artifacts") / "reports" / active.release.id / f"{name}.json"
        if path.is_file():
            saved = read_json(path)
            return {"status": saved["report"].get("status", "available"), **saved}
        if name == "compression":
            return {"name": name, "status": "build-only", "release_id": active.release.id,
                    "report": {"codecs": active.release.info["lexical"]["compression"]}}
        return {"name": name, "status": "not-run", "release_id": active.release.id}

    @app.get("/api/v1/reports/{name}")
    def report(name: str):
        return load_report(name)

    @app.get("/api/v1/benchmarks/{split}")
    def benchmarks(split: Literal["dev", "test"]):
        return load_report(f"benchmark-{split}")

    @app.get("/api/v1/pipeline")
    def pipeline():
        stages = status(settings)
        return {name: ({key: item[key] for key in ("status", "reason", "release_id", "shortfall", "id", "revision") if key in item}
                       if isinstance(item, dict) and name != "raw" else item) for name, item in stages.items()}

    @app.get("/api/v1/exports/reports/{name}")
    def report_export(name: str, response: Response):
        response.headers["Content-Disposition"] = f'attachment; filename="{name}.json"' if name in REPORTS else "attachment"
        return load_report(name)

    @app.get("/api/v1/exports/search/{sid}")
    def snapshot_export(sid: str, request: Request, response: Response):
        result = snapshot_for(sid, request, response)
        response.headers["Content-Disposition"] = 'attachment; filename="techsearch-results.json"'
        return result

    return app
