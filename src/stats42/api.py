"""API pública (solo agregados) y servidor de la web."""
from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from . import stats
from .db import make_readonly_engine

WEB_DIR = Path(__file__).parent / "web"
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:"

# TTL en segundos por consulta: las pesadas se recalculan poco; los datos cambian una vez al día.
TTL = {"overview": 60, "levels": 300, "cohorts": 300, "signups": 600, "projects": 600,
       "projects_monthly": 600, "blackholes": 300, "milestones": 600, "attendance": 900, "evaluations": 600, "events": 300}


def create_app(engine: Engine | None = None, cursus_id: int | None = None) -> FastAPI:
    engine = engine or make_readonly_engine(os.environ.get("FT_DATABASE_URL", "sqlite:///data/stats42.db"))
    cursus_id = cursus_id or int(os.environ.get("FT_CURSUS_ID", "21"))
    app = FastAPI(title="42stats", docs_url=None, redoc_url=None, openapi_url=None)
    cache: dict[str, tuple[float, Any]] = {}

    def cached(key: str, compute: Callable[[], Any]) -> Any:
        hit = cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL[key]:
            return hit[1]
        value = compute()
        cache[key] = (time.monotonic(), value)
        return value

    def session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    @app.exception_handler(OperationalError)
    async def _no_data(_: Request, __: OperationalError) -> JSONResponse:
        return JSONResponse({"detail": "Datos aún no disponibles (sincronización en curso)."}, status_code=503)

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = CSP
        path = request.url.path
        if path.startswith("/api/") and path != "/api/health":
            resp.headers.setdefault("Cache-Control", "public, max-age=300")
        elif path.startswith("/static/"):
            resp.headers.setdefault("Cache-Control", "public, max-age=300")
        return resp

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/overview")
    def overview(s: Session = Depends(session)) -> dict:
        return cached("overview", lambda: stats.overview(s, cursus_id))

    @app.get("/api/levels")
    def levels(s: Session = Depends(session)) -> list[dict]:
        return cached("levels", lambda: stats.levels(s, cursus_id))

    @app.get("/api/cohorts")
    def cohorts(s: Session = Depends(session)) -> list[dict]:
        return cached("cohorts", lambda: stats.cohorts(s, cursus_id))

    @app.get("/api/blackholes")
    def blackholes(s: Session = Depends(session)) -> dict:
        return cached("blackholes", lambda: stats.blackholes(s, cursus_id))

    @app.get("/api/milestones")
    def milestones(s: Session = Depends(session)) -> dict:
        return cached("milestones", lambda: stats.milestones(s, cursus_id))

    @app.get("/api/signups")
    def signups(s: Session = Depends(session)) -> list[dict]:
        return cached("signups", lambda: stats.signups(s))

    @app.get("/api/projects")
    def projects(s: Session = Depends(session)) -> list[dict]:
        return cached("projects", lambda: stats.projects_by_cursus(s))

    @app.get("/api/projects/monthly")
    def projects_monthly(s: Session = Depends(session)) -> list[dict]:
        return cached("projects_monthly", lambda: stats.projects_monthly(s))

    @app.get("/api/attendance")
    def attendance(s: Session = Depends(session)) -> dict:
        return cached("attendance", lambda: stats.attendance(s))

    @app.get("/api/evaluations")
    def evaluations(s: Session = Depends(session)) -> dict:
        return cached("evaluations", lambda: stats.evaluations(s))

    @app.get("/api/events")
    def events(s: Session = Depends(session)) -> dict:
        return cached("events", lambda: stats.events_exams(s))

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


app = create_app()
