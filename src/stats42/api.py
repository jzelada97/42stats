"""API pública (solo agregados) y servidor de la web."""
from __future__ import annotations

import logging
import os
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from . import auth as authmod
from . import helpboard
from . import probe as probemod
from . import stats
from .client import FortyTwoClient
from .db import User, UserSession, UserSetting, make_engine, make_readonly_engine, user_data_tables
from .ratelimit import RateLimiter

log = logging.getLogger("stats42.auth")
WEB_DIR = Path(__file__).parent / "web"
PRIVATE_PATHS = {"/", "/api/me", "/api/session", "/me", "/login", "/campus", "/ayuda"}
# Sin scripts inline ni conexiones a otros sitios; nadie puede enmarcar la web (clickjacking) ni cambiar <base>.
CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
MAX_BODY = 2048          # los POST de esta web son un par de fechas: cualquier cosa mayor es un abuso


def _clean(text: str, limit: int = 300) -> str:
    """Texto externo para un log: sin saltos de línea ni caracteres de control (evita falsificar líneas de log)."""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", text)[:limit]

# TTL en segundos por consulta: las pesadas se recalculan poco; los datos cambian una vez al día.
TTL = {"overview": 60, "levels": 300, "cohorts": 300, "signups": 600, "projects": 600,
       "projects_monthly": 600, "blackholes": 300, "milestones": 600, "attendance": 900, "evaluations": 600, "events": 300, "me_ctx": 600}


class SettingsIn(BaseModel):
    deadline: date | None = None
    freeze_until: date | None = None


def create_app(
    engine: Engine | None = None,
    cursus_id: int | None = None,
    auth: authmod.AuthConfig | None = None,
    http: httpx.Client | None = None,
    app_client: Callable[[], FortyTwoClient] | None = None,
    settings_engine: Engine | None = None,
    require_login: bool | None = None,
) -> FastAPI:
    engine = engine or make_readonly_engine(os.environ.get("FT_DATABASE_URL", "sqlite:///data/stats42.db"))
    cursus_id = cursus_id or int(os.environ.get("FT_CURSUS_ID", "21"))
    cfg = auth or authmod.AuthConfig.from_env()
    # Por defecto, las estadísticas del campus solo las ve quien se autenticó con 42 (FT_REQUIRE_LOGIN=0 para desarrollo).
    if require_login is None:
        require_login = os.environ.get("FT_REQUIRE_LOGIN", "1").lower() not in ("0", "false", "no")
    http = http or httpx.Client(timeout=30, headers={"User-Agent": "stats42/0.1"})
    app_client = app_client or (lambda: FortyTwoClient(cfg.uid, cfg.secret))
    app = FastAPI(title="42stats", docs_url=None, redoc_url=None, openapi_url=None)
    cache: dict[str, tuple[float, Any]] = {}
    store: dict[str, Engine] = {}
    # En el campus muchos alumnos salen por la misma IP pública: el límite por IP es solo un tope contra abusos groseros.
    # El que protege el cupo de 42 (2 peticiones/s para toda la aplicación) es el global, y solo cuenta logins con estado válido.
    auth_limiter = RateLimiter(300, 60)       # por IP: callbacks
    exchange_limiter = RateLimiter(40, 60)    # global: canjes de código con 42 (cada uno son 2 llamadas)
    settings_limiter = RateLimiter(20, 60)    # por alumno: guardados de deadline y freeze
    me_limiter = RateLimiter(60, 60)          # por alumno: lecturas de /api/me (consulta mucho más que el resto)
    used_states: dict[str, float] = {}        # un intento por state: repetir un callback no vuelve a llamar a 42
    key_locks: dict[str, threading.Lock] = {}

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "?"

    def guard_body(request: Request):
        """Los POST solo aceptan JSON pequeño: además de limitar abusos, un Content-Type JSON obliga a otros sitios a un preflight CORS."""
        if request.method not in ("POST", "PUT", "PATCH"):
            return None
        if not request.headers.get("content-type", "").lower().startswith("application/json"):
            return JSONResponse({"detail": "Se esperaba JSON."}, status_code=415)
        length = request.headers.get("content-length", "")
        if not length.isdigit():
            return JSONResponse({"detail": "Falta Content-Length."}, status_code=411)
        if int(length) > MAX_BODY:
            return JSONResponse({"detail": "Cuerpo demasiado grande."}, status_code=413)
        return None

    def settings_db() -> Engine:
        """Base aparte (escribible) con lo que indica cada alumno; se crea al primer uso."""
        if "e" not in store:
            e = settings_engine or make_engine(os.environ.get("FT_SETTINGS_DATABASE_URL", "sqlite:///data/user_settings.db"))
            for table in user_data_tables():
                table.create(e, checkfirst=True)
            store["e"] = e
        return store["e"]

    def cached(key: str, compute: Callable[[], Any]) -> Any:
        hit = cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL[key]:
            return hit[1]
        with key_locks.setdefault(key, threading.Lock()):     # al caducar, uno recalcula y el resto espera su resultado
            hit = cache.get(key)
            if hit and time.monotonic() - hit[0] < TTL[key]:
                return hit[1]
            value = compute()
            cache[key] = (time.monotonic(), value)
            return value

    def session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    def member(request: Request) -> None:
        """Las rutas de estadísticas solo responden a una sesión válida (alumno del campus que entró con 42)."""
        if require_login and current_user(request) is None:
            raise HTTPException(status_code=401, detail="Inicia sesión con 42 para ver las estadísticas.")

    @app.exception_handler(OperationalError)
    async def _no_data(_: Request, __: OperationalError) -> JSONResponse:
        return JSONResponse({"detail": "Datos aún no disponibles (sincronización en curso)."}, status_code=503)

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        resp = guard_body(request) or await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        if cfg.secure_cookies:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"   # sin includeSubDomains: otros proyectos comparten dominio
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = CSP
        path = request.url.path
        if path in PRIVATE_PATHS or path.startswith(("/auth/", "/api/")) and path != "/api/health":
            # Todo lo de /api/ depende de la sesión (y en el campus los ordenadores se comparten): el navegador no guarda
            # nada. El rendimiento lo da la caché del servidor, no la del navegador.
            resp.headers["Cache-Control"] = "no-store"
        elif path.startswith("/static/"):
            resp.headers.setdefault("Cache-Control", "public, max-age=300")
        return resp

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/overview", dependencies=[Depends(member)])
    def overview(s: Session = Depends(session)) -> dict:
        return cached("overview", lambda: stats.overview(s, cursus_id))

    @app.get("/api/levels", dependencies=[Depends(member)])
    def levels(s: Session = Depends(session)) -> list[dict]:
        return cached("levels", lambda: stats.levels(s, cursus_id))

    @app.get("/api/cohorts", dependencies=[Depends(member)])
    def cohorts(s: Session = Depends(session)) -> list[dict]:
        return cached("cohorts", lambda: stats.cohorts(s, cursus_id))

    @app.get("/api/blackholes", dependencies=[Depends(member)])
    def blackholes(s: Session = Depends(session)) -> dict:
        return cached("blackholes", lambda: stats.blackholes(s, cursus_id))

    @app.get("/api/milestones", dependencies=[Depends(member)])
    def milestones(s: Session = Depends(session)) -> dict:
        return cached("milestones", lambda: stats.milestones(s, cursus_id))

    @app.get("/api/habits", dependencies=[Depends(member)])
    def habits(s: Session = Depends(session)) -> dict:
        ctx = cached("me_ctx", lambda: stats.cohort_context(s, cursus_id))
        return stats.habits_from_ctx(ctx) or {"students": 0, "quartiles": [], "bounds": []}

    @app.get("/api/signups", dependencies=[Depends(member)])
    def signups(s: Session = Depends(session)) -> list[dict]:
        return cached("signups", lambda: stats.signups(s))

    @app.get("/api/projects", dependencies=[Depends(member)])
    def projects(s: Session = Depends(session)) -> list[dict]:
        return cached("projects", lambda: stats.projects_by_cursus(s))

    @app.get("/api/projects/monthly", dependencies=[Depends(member)])
    def projects_monthly(s: Session = Depends(session)) -> list[dict]:
        return cached("projects_monthly", lambda: stats.projects_monthly(s))

    @app.get("/api/attendance", dependencies=[Depends(member)])
    def attendance(s: Session = Depends(session)) -> dict:
        return cached("attendance", lambda: stats.attendance(s))

    @app.get("/api/evaluations", dependencies=[Depends(member)])
    def evaluations(s: Session = Depends(session)) -> dict:
        return cached("evaluations", lambda: stats.evaluations(s))

    @app.get("/api/events", dependencies=[Depends(member)])
    def events(s: Session = Depends(session)) -> dict:
        return cached("events", lambda: stats.events_exams(s))

    # ------------------------------------------------------------ login con 42 y panel personal
    def current_user(request: Request) -> dict | None:
        """Sesión válida = cookie firmada y reciente CON su fila en la base: salir o caducar la revoca aunque alguien copiara la cookie."""
        data = authmod.unsign(cfg, "session", request.cookies.get(authmod.SESSION_COOKIE), authmod.SESSION_TTL) if cfg.enabled else None
        if not (isinstance(data, dict) and "uid" in data and isinstance(data.get("sid"), str)):
            return None
        try:
            with Session(settings_db()) as db:
                row = db.get(UserSession, data["sid"])
                alive = row is not None and row.user_id == data["uid"]
        except SQLAlchemyError:
            return None                      # ante la duda, sin sesión
        return data if alive else None

    def _cookie(resp, name: str, value: str, max_age: int | None) -> None:
        resp.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax", secure=cfg.secure_cookies, path="/")

    def open_session(uid: int) -> str:
        sid = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        with Session(settings_db()) as db:
            db.query(UserSession).filter(UserSession.created_at < now - timedelta(seconds=authmod.SESSION_TTL)).delete()
            db.add(UserSession(sid=sid, user_id=uid, created_at=now))
            db.commit()
        return sid

    def close_sessions(*, sid: str | None = None, uid: int | None = None) -> None:
        with Session(settings_db()) as db:
            q = db.query(UserSession)
            q.filter(UserSession.sid == sid).delete() if sid else q.filter(UserSession.user_id == uid).delete()
            db.commit()

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
    def auth_login(request: Request):
        if not cfg.enabled:
            return JSONResponse({"detail": "El login con 42 aún no está configurado."}, status_code=503)
        state = authmod.new_state()           # no llama a 42: no hace falta limitarlo (y un solo alumno agotaría el cupo del campus)
        resp = RedirectResponse(authmod.authorize_url(cfg, state), status_code=302)
        _cookie(resp, authmod.STATE_COOKIE, authmod.sign(cfg, "state", state), authmod.STATE_TTL)
        return resp

    def run_admin_probe(token: str, uid: int, login: str) -> None:
        try:
            probemod.save_probe(cfg.probe_dir, login, probemod.run_probe(token, uid, http, app_client()))
        except Exception as e:  # nunca debe afectar al login, pero tampoco fallar en silencio
            log.warning("sondeo de administrador falló (%s)", type(e).__name__)

    def finish_login(request: Request, code: str | None, state: str | None, error: str | None):
        if not cfg.enabled:
            return JSONResponse({"detail": "El login con 42 aún no está configurado."}, status_code=503)
        if not auth_limiter.allow(client_ip(request)):
            return _fail("limite")
        if error:
            return _fail("denegado")
        expected = authmod.unsign(cfg, "state", request.cookies.get(authmod.STATE_COOKIE), authmod.STATE_TTL)
        if not code or not state or not expected or state != expected:
            return _fail("estado")
        now = time.monotonic()
        for k in [k for k, t in used_states.items() if now - t > authmod.STATE_TTL]:
            used_states.pop(k, None)
        if state in used_states:
            return _fail("estado")
        used_states[state] = now
        if not exchange_limiter.allow("42"):
            return _fail("limite")
        try:
            token = authmod.exchange_code(cfg, code, http)
            me = authmod.fetch_me(token, http)
        except httpx.HTTPStatusError as e:
            # El cuerpo de error de 42 no lleva secretos (p. ej. invalid_grant); el código y el token nunca se registran.
            log.warning("login: 42 respondió %s en %s: %s", e.response.status_code, e.request.url.path, _clean(e.response.text))
            return _fail("intercambio")
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("login: fallo al hablar con 42 (%s): %s", type(e).__name__, _clean(str(e)))
            return _fail("intercambio")
        with Session(engine) as db:
            known = db.get(User, me["id"]) is not None
        if not known:       # solo alumnos del campus que ya están en nuestros datos
            return _fail("fuera-de-campus")
        if me["login"] in cfg.admin_logins and cfg.probe_dir:
            # En segundo plano y espaciado: ~20 llamadas seguidas agotaban el límite de 42 y hacían fallar otros logins.
            threading.Thread(target=run_admin_probe, args=(token, me["id"], me["login"]), daemon=True).start()
        resp = RedirectResponse("/me", status_code=302)
        resp.delete_cookie(authmod.STATE_COOKIE, path="/")
        name = me.get("usual_first_name") or me.get("first_name") or me["login"]
        sid = open_session(me["id"])
        # Sin max_age: cookie de sesión, desaparece al cerrar el navegador. La firma caduca a las 12 h y la fila se revoca al salir.
        _cookie(resp, authmod.SESSION_COOKIE, authmod.sign(cfg, "session", {"uid": me["id"], "login": me["login"], "name": name, "sid": sid}),
                None)
        return resp

    @app.get("/auth/callback")
    def auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
        return finish_login(request, code, state, error)

    @app.get("/auth/logout")
    def auth_logout(request: Request):
        u = current_user(request)
        if u is not None:
            close_sessions(sid=u["sid"])
        resp = RedirectResponse("/", status_code=302)
        resp.delete_cookie(authmod.SESSION_COOKIE, path="/")
        return resp

    @app.get("/api/me")
    def api_me(request: Request, s: Session = Depends(session)):
        u = current_user(request)
        if u is None:
            return JSONResponse({"detail": "Inicia sesión con 42 para ver tu panel."}, status_code=401)
        if not me_limiter.allow(str(u["uid"])):
            return JSONResponse({"detail": "Demasiadas consultas seguidas. Espera un minuto."}, status_code=429, headers={"Retry-After": "60"})
        ctx = cached("me_ctx", lambda: stats.cohort_context(s, cursus_id))
        with Session(settings_db()) as db:
            row = db.get(UserSetting, u["uid"])
            mine = {"deadline": row.deadline, "freeze_until": row.freeze_until} if row else {}
        data = stats.me(s, u["uid"], ctx, cursus_id, settings=mine)
        if data is None:
            return JSONResponse({"detail": "No tenemos datos de tu cuenta todavía."}, status_code=404)
        with Session(settings_db()) as db:                 # ayuda disponible para cada proyecto en curso
            counts = helpboard.project_help_counts(db, s, [p["id"] for p in data["projects"]["in_progress"]], u["uid"], cursus_id)
        for p in data["projects"]["in_progress"]:
            p.update(counts.get(p["id"], {"mentors": 0, "resources": 0}))
        return data

    def origin_error(request: Request):
        """Defensa extra contra peticiones lanzadas desde otros sitios (además de SameSite=Lax y del Content-Type JSON)."""
        origin = request.headers.get("origin")
        if origin and cfg.base_url and origin.rstrip("/") != cfg.base_url:
            return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
        return None

    @app.post("/api/me/settings")
    def save_settings(body: SettingsIn, request: Request):
        u = current_user(request)
        if u is None:
            return JSONResponse({"detail": "Inicia sesión con 42."}, status_code=401)
        if not settings_limiter.allow(str(u["uid"])):
            return JSONResponse({"detail": "Demasiados cambios seguidos. Espera un minuto."}, status_code=429,
                                headers={"Retry-After": "60"})
        if (err := origin_error(request)) is not None:
            return err
        today = datetime.now(timezone.utc).date()
        if body.deadline is not None and not (today - timedelta(days=60) <= body.deadline <= today + timedelta(days=800)):
            return JSONResponse({"detail": "El deadline debe estar entre hace 60 días y 800 días desde hoy."}, status_code=422)
        if body.freeze_until is not None and not (today - timedelta(days=365) <= body.freeze_until <= today + timedelta(days=365)):
            return JSONResponse({"detail": "El freeze debe estar a menos de un año de hoy."}, status_code=422)
        with Session(settings_db()) as db:
            row = db.get(UserSetting, u["uid"])
            if body.deadline is None and body.freeze_until is None:     # borrar: no se conserva una fila vacía
                if row:
                    db.delete(row)
            else:
                row = row or UserSetting(user_id=u["uid"])
                row.deadline, row.freeze_until, row.updated_at = body.deadline, body.freeze_until, datetime.now(timezone.utc)
                db.add(row)
            db.commit()
        return {"deadline": body.deadline.isoformat() if body.deadline else None,
                "freeze_until": body.freeze_until.isoformat() if body.freeze_until else None}

    @app.post("/api/me/delete")
    def delete_my_data(request: Request):
        """Borra todo lo que esta web guarda de ti (ajustes, mentoría, peticiones, envíos) y cierra tu sesión."""
        u = current_user(request)
        if u is None:
            return JSONResponse({"detail": "Inicia sesión con 42."}, status_code=401)
        if (err := origin_error(request)) is not None:
            return err
        with Session(settings_db()) as db:
            helpboard.erase_user(db, u["uid"])
            db.query(UserSetting).filter(UserSetting.user_id == u["uid"]).delete()
            db.commit()
        close_sessions(uid=u["uid"])
        resp = JSONResponse({"deleted": True})
        resp.delete_cookie(authmod.SESSION_COOKIE, path="/")
        return resp

    helpboard.register(app, current_user=current_user, main_engine=engine, settings_db=settings_db,
                       admin_logins=cfg.admin_logins, origin_error=origin_error, cursus_id=cursus_id)

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
        if current_user(request) is not None:
            return RedirectResponse("/me", status_code=302)
        return FileResponse(WEB_DIR / "login.html", media_type="text/html; charset=utf-8")

    @app.get("/ayuda")
    def ayuda_page(request: Request):
        if current_user(request) is None:
            return RedirectResponse("/login", status_code=302)
        return FileResponse(WEB_DIR / "ayuda.html", media_type="text/html; charset=utf-8")

    @app.get("/campus")
    def campus_page(request: Request):
        if require_login and current_user(request) is None:
            return RedirectResponse("/login", status_code=302)
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/robots.txt")
    def robots() -> Response:
        return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


app = create_app()
