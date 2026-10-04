"""API pública (solo agregados) y servidor de la web."""
from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from . import auth as authmod
from . import probe as probemod
from . import stats
from .client import FortyTwoClient
from .db import User, make_readonly_engine

WEB_DIR = Path(__file__).parent / "web"
PRIVATE_PATHS = {"/api/me", "/api/session", "/me", "/login"}
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:"

# TTL en segundos por consulta: las pesadas se recalculan poco; los datos cambian una vez al día.
TTL = {"overview": 60, "levels": 300, "cohorts": 300, "signups": 600, "projects": 600,
       "projects_monthly": 600, "blackholes": 300, "milestones": 600, "attendance": 900, "evaluations": 600, "events": 300, "me_ctx": 600}


def create_app(
    engine: Engine | None = None,
    cursus_id: int | None = None,
    auth: authmod.AuthConfig | None = None,
    http: httpx.Client | None = None,
    app_client: Callable[[], FortyTwoClient] | None = None,
) -> FastAPI:
    engine = engine or make_readonly_engine(os.environ.get("FT_DATABASE_URL", "sqlite:///data/stats42.db"))
    cursus_id = cursus_id or int(os.environ.get("FT_CURSUS_ID", "21"))
    cfg = auth or authmod.AuthConfig.from_env()
    http = http or httpx.Client(timeout=30, headers={"User-Agent": "stats42/0.1"})
    app_client = app_client or (lambda: FortyTwoClient(cfg.uid, cfg.secret))
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
        if path in PRIVATE_PATHS or path.startswith("/auth/"):
            resp.headers["Cache-Control"] = "no-store"   # respuestas ligadas a una sesión: nunca se cachean
        elif path.startswith("/api/") and path != "/api/health":
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

    # ------------------------------------------------------------ login con 42 y panel personal
    def current_user(request: Request) -> dict | None:
        data = authmod.unsign(cfg, "session", request.cookies.get(authmod.SESSION_COOKIE), authmod.SESSION_TTL) if cfg.enabled else None
        return data if isinstance(data, dict) and "uid" in data else None

    def _cookie(resp, name: str, value: str, max_age: int) -> None:
        resp.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax", secure=cfg.secure_cookies, path="/")

    def _fail(code: str) -> RedirectResponse:
        resp = RedirectResponse(f"/login?error={code}", status_code=302)
        resp.delete_cookie(authmod.STATE_COOKIE, path="/")
        return resp

    @app.get("/api/session")
    def session_info(request: Request) -> dict:
        u = current_user(request)
        return {"login_enabled": cfg.enabled, "logged_in": u is not None, "login": u["login"] if u else None,
                "name": u.get("name") if u else None}

    @app.get("/auth/login")
    def auth_login():
        if not cfg.enabled:
            return JSONResponse({"detail": "El login con 42 aún no está configurado."}, status_code=503)
        state = authmod.new_state()
        resp = RedirectResponse(authmod.authorize_url(cfg, state), status_code=302)
        _cookie(resp, authmod.STATE_COOKIE, authmod.sign(cfg, "state", state), authmod.STATE_TTL)
        return resp

    def finish_login(request: Request, code: str | None, state: str | None, error: str | None):
        if not cfg.enabled:
            return JSONResponse({"detail": "El login con 42 aún no está configurado."}, status_code=503)
        if error:
            return _fail("denegado")
        expected = authmod.unsign(cfg, "state", request.cookies.get(authmod.STATE_COOKIE), authmod.STATE_TTL)
        if not code or not state or not expected or state != expected:
            return _fail("estado")
        try:
            token = authmod.exchange_code(cfg, code, http)
            me = authmod.fetch_me(token, http)
        except (httpx.HTTPError, KeyError, ValueError):
            return _fail("intercambio")
        with Session(engine) as db:
            known = db.get(User, me["id"]) is not None
        if not known:       # solo alumnos del campus que ya están en nuestros datos
            return _fail("fuera-de-campus")
        if me["login"] in cfg.admin_logins and cfg.probe_dir:
            try:
                results = probemod.run_probe(token, me["id"], http, app_client())
                probemod.save_probe(cfg.probe_dir, me["login"], results)
            except Exception:  # el sondeo nunca debe impedir entrar
                pass
        resp = RedirectResponse("/me", status_code=302)
        resp.delete_cookie(authmod.STATE_COOKIE, path="/")
        name = me.get("usual_first_name") or me.get("first_name") or me["login"]
        _cookie(resp, authmod.SESSION_COOKIE, authmod.sign(cfg, "session", {"uid": me["id"], "login": me["login"], "name": name}),
                authmod.SESSION_TTL)
        return resp

    @app.get("/auth/callback")
    def auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
        return finish_login(request, code, state, error)

    @app.get("/auth/logout")
    def auth_logout():
        resp = RedirectResponse("/", status_code=302)
        resp.delete_cookie(authmod.SESSION_COOKIE, path="/")
        return resp

    @app.get("/api/me")
    def api_me(request: Request, s: Session = Depends(session)):
        u = current_user(request)
        if u is None:
            return JSONResponse({"detail": "Inicia sesión con 42 para ver tu panel."}, status_code=401)
        ctx = cached("me_ctx", lambda: stats.cohort_context(s, cursus_id))
        data = stats.me(s, u["uid"], ctx, cursus_id)
        if data is None:
            return JSONResponse({"detail": "No tenemos datos de tu cuenta todavía."}, status_code=404)
        return data

    @app.get("/login")
    def login_page() -> FileResponse:
        return FileResponse(WEB_DIR / "login.html", media_type="text/html; charset=utf-8")

    @app.get("/me")
    def me_page(request: Request):
        if current_user(request) is None:
            return RedirectResponse("/login", status_code=302)
        return FileResponse(WEB_DIR / "me.html", media_type="text/html; charset=utf-8")

    @app.get("/")
    def index(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
        # Si en 42 solo se pudo registrar el dominio como dirección de retorno, el login termina aquí.
        if state and (code or error):
            return finish_login(request, code, state, error)
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


app = create_app()
