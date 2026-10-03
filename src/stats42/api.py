"""API pública (solo agregados) y servidor de la web."""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from . import stats
from .db import make_readonly_engine

WEB_DIR = Path(__file__).parent / "web"
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:"


def create_app(engine: Engine | None = None, cursus_id: int | None = None) -> FastAPI:
    engine = engine or make_readonly_engine(os.environ.get("FT_DATABASE_URL", "sqlite:///data/stats42.db"))
    cursus_id = cursus_id or int(os.environ.get("FT_CURSUS_ID", "21"))
    app = FastAPI(title="42stats", docs_url=None, redoc_url=None, openapi_url=None)

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
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            resp.headers.setdefault("Cache-Control", "public, max-age=300")
        return resp

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/overview")
    def overview(s: Session = Depends(session)) -> dict:
        return stats.overview(s, cursus_id)

    @app.get("/api/levels")
    def levels(s: Session = Depends(session)) -> list[dict]:
        return stats.levels(s, cursus_id)

    @app.get("/api/cohorts")
    def cohorts(s: Session = Depends(session)) -> list[dict]:
        return stats.cohorts(s, cursus_id)

    @app.get("/api/signups")
    def signups(s: Session = Depends(session)) -> list[dict]:
        return stats.signups(s)

    @app.get("/api/projects")
    def projects(s: Session = Depends(session)) -> list[dict]:
        return stats.projects(s)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")

    return app


app = create_app()
