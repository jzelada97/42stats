"""Ayuda entre alumnos: recursos de estudio, mentores y peticiones de ayuda.

Reglas que importan:
- Un alumno solo puede ofrecerse como mentor en proyectos que, según nuestros datos, ya tiene VALIDADOS.
- Los recursos son guías, documentación, vídeos o herramientas, nunca soluciones: compartir o copiar código de un proyecto
  cuenta como cheating en 42. Cada recurso lo aprueba a mano un administrador antes de publicarse.
- Todo texto libre es corto, de una sola línea y se trata como texto plano; los enlaces son https y sin trucos.
"""
from __future__ import annotations

import ipaddress
import re
from collections import Counter, defaultdict
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from . import logins as loginsmod
from . import points as pointsmod
from .stats import RANK_RE
from .db import (AbuseEvent, CursusUser, MentorThanks, Quest, QuestUser, HelpRequest, LearningResource, MentorOffer, MentorProject, Project, ProjectUser)
from .ratelimit import RateLimiter

KINDS = ("guía", "vídeo", "documentación", "herramienta", "otro")
REQUEST_TTL = timedelta(days=30)
MAX_OPEN_REQUESTS = 3
MAX_OFFER_PROJECTS = 10
MIN_ATTEMPTS_FOR_OPTION = 20          # solo proyectos con actividad real aparecen en los desplegables

MAX_ID = 2**31 - 1
ID = Annotated[int, Field(ge=1, le=MAX_ID)]
MAX_MARKS = 3                         # marcas combinantes seguidas (acentos): más es "zalgo" que desborda el diseño
# Letras "en blanco" que se ven como un hueco (relleno hangul, braille vacío, combinador de grafemas...) y no son de categoría C.
_BLANKS = {0x115F, 0x1160, 0x3164, 0xFFA0, 0x2800, 0x034F, 0x17B4, 0x17B5}
# Enlaces o referencias a sitios de código: aquí se explican conceptos, no se pasan soluciones.
_LINKISH = re.compile(r"https?:|www\.|\b[a-z0-9-]+\.(?:com|org|net|io|dev|es|fr|eu|me|app|ly|gg|xyz|tk|sh|co|ai|cc|to)\b"
                      r"|github|gitlab|pastebin|gist\b|bitbucket", re.I)


def _hidden(ch: str) -> bool:
    """Control, formato (bidi, ancho cero, soft hyphen, tags), uso privado, sin asignar, sustitutos o letras en blanco."""
    return unicodedata.category(ch)[0] == "C" or ord(ch) in _BLANKS


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


# ---------------------------------------------------------------- validación de texto y enlaces

def _scrub(value: str) -> str:
    out, marks = [], 0
    for ch in value:
        if _hidden(ch):
            ch = " "
        if unicodedata.category(ch) in ("Mn", "Me"):
            marks += 1
            if marks > MAX_MARKS:
                continue
        else:
            marks = 0
        out.append(ch)
    return "".join(out)


def clean_text(value: str | None, *, min_len: int, max_len: int, field: str) -> str:
    text = re.sub(r"\s+", " ", _scrub(value or "")).strip()
    if _LINKISH.search(text):
        raise ValueError(f"{field}: no incluyas enlaces ni sitios de código; aquí se explican conceptos, no se comparten soluciones.")
    if len(text) < min_len:
        raise ValueError(f"{field}: escribe al menos {min_len} caracteres.")
    if len(text) > max_len:
        raise ValueError(f"{field}: máximo {max_len} caracteres.")
    return text


def validate_url(raw: str | None) -> str:
    """Solo https público: sin credenciales, puertos raros, IPs, hosts internos ni caracteres de control."""
    raw = (raw or "").strip()
    if not raw or len(raw) > 300 or any(_hidden(c) for c in raw) or re.search(r"[\s\\]", raw):
        raise ValueError("El enlace no es válido.")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise ValueError("El enlace no es válido.") from None
    if parts.scheme != "https":
        raise ValueError("Solo se admiten enlaces https.")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValueError("El enlace no puede llevar usuario ni contraseña.")
    if port not in (None, 443):
        raise ValueError("El enlace no puede usar un puerto distinto del 443.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or "." not in host or not host.isascii():
        raise ValueError("El enlace debe apuntar a un dominio público.")
    if not re.fullmatch(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}", host.rsplit(".", 1)[1]):   # 127.1, 0x7f.1, 0177.0.0.1: no son dominios
        raise ValueError("El enlace debe apuntar a un dominio público.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("No se admiten enlaces a direcciones IP.")
    if host == "localhost" or host.endswith((".local", ".localhost", ".internal", ".lan", ".home", ".corp")):
        raise ValueError("El enlace debe apuntar a un dominio público.")
    return parts._replace(fragment="").geturl()


# ---------------------------------------------------------------- cuerpos de petición

class ResourceIn(BaseModel):
    project_id: ID | None = None
    title: str = Field(max_length=200)
    url: str = Field(max_length=400)
    kind: Literal["guía", "vídeo", "documentación", "herramienta", "otro"]
    confirm_no_solution: bool = False


class OfferIn(BaseModel):
    active: bool = True
    note: str = Field(default="", max_length=400)
    project_ids: list[ID] = Field(default_factory=list, max_length=50)


class RequestIn(BaseModel):
    project_id: ID
    message: str = Field(max_length=600)


class CloseIn(BaseModel):
    helped_by: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{2,50}$")      # login del mentor al que se agradece
    no_code: bool = False                                                                # "me explicó, sin darme código"


# ---------------------------------------------------------------- consultas

def project_options(ms: Session, cursus_id: int | None = None) -> list[dict]:
    """Proyectos con actividad real, cada uno en SU cursus: el más habitual entre los intentos de los alumnos de Madrid.

    Con `cursus_id` solo quedan los de ese cursus (la ayuda se limita al 42cursus: piscinas y cursus obsoletos fuera).
    El orden dentro de un cursus sigue la dificultad (que es más o menos el orden del currículo) y luego el nombre.
    """
    rows = ms.execute(
        select(Project.id, Project.name, Project.difficulty).join(ProjectUser, ProjectUser.project_id == Project.id)
        .group_by(Project.id, Project.name, Project.difficulty).having(func.count() >= MIN_ATTEMPTS_FOR_OPTION)).all()
    ids = {r[0] for r in rows}
    seen: dict[int, Counter] = {}
    for pid, cids in ms.execute(select(ProjectUser.project_id, ProjectUser.cursus_ids)):
        if pid in ids and cids:
            seen.setdefault(pid, Counter()).update(cids)
    primary = {pid: min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] for pid, c in seen.items()}
    if cursus_id is not None:
        rows = [r for r in rows if primary.get(r[0]) == cursus_id]
    rank = project_ranks(ms, [r[0] for r in rows], cursus_id) if cursus_id is not None else {}
    rows.sort(key=lambda r: (rank.get(r[0]) is None, rank.get(r[0], 0), r[2] is None, r[2] or 0, r[1].lower()))
    return [{"id": i, "name": n, "cursus_id": primary.get(i), "rank": rank.get(i)} for i, n, _ in rows]


MIN_RANK_VOTES = 3


def project_ranks(ms: Session, project_ids: list[int], cursus_id: int) -> dict[int, int]:
    """Círculo (Common Core Rank) de cada proyecto, sacado de los datos: el rank que el alumno validó justo DESPUÉS de validar
    el proyecto, y se queda el más habitual entre alumnos. Sin al menos MIN_RANK_VOTES casos, el proyecto no tiene círculo."""
    rank_of = {qid: int(m[1]) for qid, name in ms.execute(select(Quest.id, Quest.name).where(Quest.cursus_id == cursus_id))
               if name and (m := RANK_RE.match(name))}
    if not rank_of or not project_ids:
        return {}
    done: dict[int, dict[int, datetime]] = defaultdict(dict)
    for uid, qid, at in ms.execute(select(QuestUser.user_id, QuestUser.quest_id, QuestUser.validated_at)
                                   .where(QuestUser.quest_id.in_(list(rank_of)), QuestUser.validated_at.is_not(None))):
        n, at = rank_of[qid], aware(at)
        if n not in done[uid] or at < done[uid][n]:
            done[uid][n] = at
    votes: dict[int, Counter] = {}
    for pid, uid, marked in ms.execute(select(ProjectUser.project_id, ProjectUser.user_id, ProjectUser.marked_at)
                                       .where(ProjectUser.validated.is_(True), ProjectUser.project_id.in_(project_ids),
                                              ProjectUser.marked_at.is_not(None))):
        later = [(at, n) for n, at in done.get(uid, {}).items() if at >= aware(marked)]
        if later:
            votes.setdefault(pid, Counter())[min(later)[1]] += 1
    out = {}
    for pid, c in votes.items():
        n, count = min(c.items(), key=lambda kv: (-kv[1], kv[0]))
        if count >= MIN_RANK_VOTES:
            out[pid] = n
    return out


def rank_groups(projects: list[dict]) -> list[dict]:
    """Círculos (ranks) que tienen proyectos, en orden, y 'Sin rank' al final para los que no se pueden situar."""
    count = Counter(p["rank"] for p in projects)
    groups = [{"id": n, "name": f"Rank {n:02d}", "projects": count[n]} for n in sorted(k for k in count if k is not None)]
    if None in count:
        groups.append({"id": None, "name": "Sin rank", "projects": count[None]})
    return groups


def default_rank(ms: Session, uid: int, projects: list[dict], validated: dict) -> int | None:
    """El círculo donde está trabajando: el de su proyecto en curso o, si no, el primero con algo que aún no ha validado."""
    by_id = {p["id"]: p for p in projects}
    for (pid,) in ms.execute(select(ProjectUser.project_id).where(ProjectUser.user_id == uid, ProjectUser.status == "in_progress")):
        if pid in by_id and by_id[pid]["rank"] is not None:
            return by_id[pid]["rank"]
    todo = [p["rank"] for p in projects if p["rank"] is not None and p["id"] not in validated]
    return min(todo) if todo else None


def validated_projects(ms: Session, user_id: int) -> dict[int, dict]:
    rows = ms.execute(
        select(ProjectUser.project_id, Project.name, func.max(ProjectUser.final_mark), func.max(ProjectUser.marked_at))
        .join(Project, Project.id == ProjectUser.project_id)
        .where(ProjectUser.user_id == user_id, ProjectUser.validated.is_(True))
        .group_by(ProjectUser.project_id, Project.name)).all()
    return {pid: {"id": pid, "name": name, "mark": mark if mark is not None and 0 <= mark <= 125 else None,
                  "date": aware(at).date().isoformat() if at else None} for pid, name, mark, at in rows}


def _levels(ms: Session, ids: list[int], cursus_id: int) -> dict[int, float | None]:
    if not ids:
        return {}
    return {uid: (round(lv, 1) if lv is not None else None) for uid, lv in ms.execute(
        select(CursusUser.user_id, CursusUser.level).where(CursusUser.user_id.in_(ids), CursusUser.cursus_id == cursus_id))}


def mentors_for(db: Session, ms: Session, project_id: int, exclude_uid: int, cursus_id: int, limit: int = 20) -> list[dict]:
    offers = db.execute(
        select(MentorOffer).join(MentorProject, MentorProject.user_id == MentorOffer.user_id)
        .where(MentorProject.project_id == project_id, MentorOffer.active.is_(True), MentorOffer.user_id != exclude_uid)
        .order_by(MentorOffer.updated_at.desc()).limit(limit * 2)).scalars().all()
    ids = [o.user_id for o in offers]
    proof = {uid: (mark, at) for uid, mark, at in ms.execute(
        select(ProjectUser.user_id, func.max(ProjectUser.final_mark), func.max(ProjectUser.marked_at))
        .where(ProjectUser.user_id.in_(ids), ProjectUser.project_id == project_id, ProjectUser.validated.is_(True))
        .group_by(ProjectUser.user_id))} if ids else {}
    levels = _levels(ms, ids, cursus_id)
    points = pointsmod.counts(db, ms, [i for i in ids if i in proof])
    out = []
    for o in sorted((o for o in offers if o.user_id in proof), key=lambda o: -points[o.user_id]["verified"]):   # estable: a igualdad, el más reciente
        mark, at = proof[o.user_id]
        out.append({"login": o.login, "note": o.note, "level": levels.get(o.user_id),
                    "mark": mark if mark is not None and 0 <= mark <= 125 else None,
                    "validated_on": aware(at).date().isoformat() if at else None,
                    "points": points[o.user_id]["verified"], "tier": points[o.user_id]["tier"]})
        if len(out) == limit:
            break
    return out


def project_help_counts(db: Session, ms: Session, project_ids: list[int], uid: int, cursus_id: int) -> dict[int, dict]:
    """Mentores disponibles y recursos aprobados para cada proyecto (para mostrar ayuda junto al proyecto en curso)."""
    out = {}
    for pid in project_ids:
        res = db.scalar(select(func.count()).select_from(LearningResource).where(
            LearningResource.status == "approved",
            (LearningResource.project_id == pid) | LearningResource.project_id.is_(None))) or 0
        out[pid] = {"mentors": len(mentors_for(db, ms, pid, uid, cursus_id, limit=20)), "resources": res}
    return out


def _live_requests(db: Session, **where):
    since = utcnow() - REQUEST_TTL
    stmt = select(HelpRequest).where(HelpRequest.status == "open", HelpRequest.created_at >= since.replace(tzinfo=None))
    for col, val in where.items():
        stmt = stmt.where(getattr(HelpRequest, col) == val)
    return stmt


def incoming_requests(db: Session, ms: Session, uid: int, cursus_id: int, limit: int = 30) -> list[dict]:
    offer = db.get(MentorOffer, uid)
    if offer is None or not offer.active:
        return []
    pids = [p for (p,) in db.execute(select(MentorProject.project_id).where(MentorProject.user_id == uid))]
    if not pids:
        return []
    # solo de proyectos que sigue teniendo validados
    pids = [p for p in pids if p in validated_projects(ms, uid)]
    reqs = db.execute(_live_requests(db).where(HelpRequest.project_id.in_(pids), HelpRequest.user_id != uid)
                      .order_by(HelpRequest.created_at.desc()).limit(limit)).scalars().all()
    names = dict(ms.execute(select(Project.id, Project.name).where(Project.id.in_(pids))).all()) if pids else {}
    now = utcnow()
    return [{"id": r.id, "login": r.login, "project_id": r.project_id, "project": names.get(r.project_id, "?"),
             "message": r.message,
             "days_waiting": (now - aware(r.created_at)).days} for r in reqs]


# ---------------------------------------------------------------- retención y borrado

RESOURCE_REJECTED_TTL = timedelta(days=30)
ABUSE_TTL = timedelta(days=30)


def purge(db: Session) -> None:
    """Limitación del plazo de conservación: peticiones caducadas o cerradas y envíos rechazados antiguos no se guardan."""
    now = utcnow().replace(tzinfo=None)
    db.query(HelpRequest).filter((HelpRequest.created_at < now - REQUEST_TTL) | (HelpRequest.status != "open")).delete()
    db.query(LearningResource).filter(LearningResource.status == "rejected",
                                      LearningResource.created_at < now - RESOURCE_REJECTED_TTL).delete()
    db.query(AbuseEvent).filter(AbuseEvent.last_at < now - ABUSE_TTL).delete()
    loginsmod.purge(db)
    db.query(MentorThanks).filter(MentorThanks.verified.is_(False), MentorThanks.created_at < now - pointsmod.PENDING_TTL).delete()
    db.commit()


def erase_user(db: Session, uid: int) -> None:
    """Todo lo que la ayuda guarda de un alumno. Los recursos ya aprobados se quedan, pero sin su nombre."""
    db.query(HelpRequest).filter(HelpRequest.user_id == uid).delete()
    db.query(MentorThanks).filter(MentorThanks.mentor_uid == uid).delete()          # los puntos recibidos se van con el mentor
    db.query(MentorThanks).filter(MentorThanks.asker_uid == uid, MentorThanks.verified.is_(False)).delete()
    db.query(MentorThanks).filter(MentorThanks.asker_uid == uid).update({"asker_uid": -MentorThanks.id}, synchronize_session=False)    # lo ya verificado se queda, anónimo
    db.query(AbuseEvent).filter(AbuseEvent.user_id == uid).delete()
    db.query(MentorProject).filter(MentorProject.user_id == uid).delete()
    db.query(MentorOffer).filter(MentorOffer.user_id == uid).delete()
    db.query(LearningResource).filter(LearningResource.submitted_by == uid, LearningResource.status != "approved").delete()
    db.query(LearningResource).filter(LearningResource.submitted_by == uid).update({"submitted_by": 0, "submitted_login": ""})


# ---------------------------------------------------------------- rutas

def register(app: FastAPI, *, current_user, main_engine: Engine, settings_db, admin_logins, origin_error, cursus_id: int = 21,
             abuse=None):
    limits = {"read": RateLimiter(120, 60), "resource": RateLimiter(5, 3600), "offer": RateLimiter(20, 3600), "request": RateLimiter(10, 3600),
              "admin": RateLimiter(240, 60), "attempt": RateLimiter(60, 3600)}
    cache: dict = {}

    def options(ms: Session) -> list[dict]:
        hit = cache.get("options")
        if hit and time.monotonic() - hit[0] < 600:
            return hit[1]
        value = project_options(ms, cursus_id)
        cache["options"] = (time.monotonic(), value)
        return value

    app.state.help_options = options          # lo usa el panel para saber en qué proyectos hay sección de ayuda

    def unauth():
        return JSONResponse({"detail": "Inicia sesión con 42."}, status_code=401)

    def require_user(request: Request) -> None:
        """Dependencia: se resuelve antes de validar el cuerpo, así un visitante recibe 401 y no detalles de validación."""
        u = current_user(request)
        if u is None:
            raise HTTPException(status_code=401, detail="Inicia sesión con 42.")
        if not limits["read"].allow(str(u["uid"])):
            if abuse is not None:
                abuse.note(u["uid"], u["login"], "lectura-ayuda")
            raise HTTPException(status_code=429, detail="Demasiadas consultas seguidas. Espera un minuto.", headers={"Retry-After": "60"})

    guard = [Depends(require_user)]

    def bad(msg: str, status: int = 422):
        return JSONResponse({"detail": msg}, status_code=status)

    def too_many(u: dict, kind: str):
        if abuse is not None:
            abuse.note(u["uid"], u["login"], kind)
        return JSONResponse({"detail": "Demasiadas acciones seguidas. Espera un poco."}, status_code=429, headers={"Retry-After": "60"})

    def is_admin(u: dict) -> bool:
        return u["login"] in admin_logins

    @app.get("/api/help/overview", dependencies=guard)
    def overview(request: Request):
        u = current_user(request)
        if u is None:
            return unauth()
        uid = u["uid"]
        with Session(main_engine) as ms, Session(settings_db()) as db:
            if time.monotonic() - cache.get("purged", -3600.0) >= 3600:
                cache["purged"] = time.monotonic()
                purge(db)
            validated = validated_projects(ms, uid)
            offer = db.get(MentorOffer, uid)
            offered = [p for (p,) in db.execute(select(MentorProject.project_id).where(MentorProject.user_id == uid))]
            by_id = {o["id"]: o for o in options(ms)}
            names = {i: o["name"] for i, o in by_id.items()}
            mine = []
            for r in db.execute(_live_requests(db, user_id=uid).order_by(HelpRequest.created_at.desc())).scalars():
                mine.append({"id": r.id, "project_id": r.project_id, "project": names.get(r.project_id, "?"), "message": r.message,
                             "days": (utcnow() - aware(r.created_at)).days,
                             "mentors": mentors_for(db, ms, r.project_id, uid, cursus_id, limit=5)})
            return {
                "is_admin": is_admin(u),
                "projects": options(ms),
                "ranks": rank_groups(options(ms)),
                "default_rank": default_rank(ms, uid, options(ms), validated),
                "validated": sorted(({**v, "rank": by_id.get(v["id"], {}).get("rank"), "in_help": v["id"] in by_id} for v in validated.values()),
                                    key=lambda v: v["name"]),
                "offer": {"active": offer.active, "note": offer.note, "project_ids": sorted(offered)} if offer else None,
                "requests": mine,
                "incoming": incoming_requests(db, ms, uid, cursus_id),
                "points": pointsmod.counts(db, ms, [uid])[uid],
                "max_open_requests": MAX_OPEN_REQUESTS,
            }

    @app.get("/api/help/mentors", dependencies=guard)
    def mentors(request: Request, project_id: Annotated[int, Query(ge=1, le=MAX_ID)]):
        u = current_user(request)
        if u is None:
            return unauth()
        with Session(main_engine) as ms, Session(settings_db()) as db:
            return {"project_id": project_id, "mentors": mentors_for(db, ms, project_id, u["uid"], cursus_id)}

    @app.get("/api/help/resources", dependencies=guard)
    def resources(request: Request, project_id: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
                  rank: Annotated[int | None, Query(ge=0, le=99)] = None):
        u = current_user(request)
        if u is None:
            return unauth()
        with Session(main_engine) as ms, Session(settings_db()) as db:
            names = {o["id"]: o["name"] for o in options(ms)}
            stmt = select(LearningResource).where(LearningResource.status == "approved")
            if project_id is not None:
                stmt = stmt.where((LearningResource.project_id == project_id) | LearningResource.project_id.is_(None))
            elif rank is not None:                  # todo un círculo: sus proyectos y lo general
                of_rank = [o["id"] for o in options(ms) if o["rank"] == rank]
                stmt = stmt.where(LearningResource.project_id.in_(of_rank) | LearningResource.project_id.is_(None))
            rows = db.execute(stmt.order_by(LearningResource.created_at.desc()).limit(60)).scalars().all()
            mine = db.execute(select(LearningResource).where(LearningResource.submitted_by == u["uid"], LearningResource.status != "approved")
                              .order_by(LearningResource.created_at.desc()).limit(10)).scalars().all()
            fmt = lambda r: {"id": r.id, "title": r.title, "url": r.url, "kind": r.kind, "project_id": r.project_id,  # noqa: E731
                             "project": names.get(r.project_id) if r.project_id else "General", "status": r.status}
            return {"resources": [fmt(r) for r in rows], "mine_pending": [fmt(r) for r in mine]}

    @app.post("/api/help/resources", dependencies=guard)
    def add_resource(body: ResourceIn, request: Request):
        u = current_user(request)
        if u is None:
            return unauth()
        if (err := origin_error(request)) is not None:
            return err
        if not limits["attempt"].allow(str(u["uid"])):
            return too_many(u, "ayuda-intentos")
        if not body.confirm_no_solution:
            return bad("Confirma que el recurso explica el tema y no contiene la solución del proyecto.")
        try:
            title = clean_text(body.title, min_len=3, max_len=120, field="Título")
            url = validate_url(body.url)
        except ValueError as e:
            return bad(str(e))
        with Session(main_engine) as ms, Session(settings_db()) as db:
            if body.project_id is not None and body.project_id not in {o["id"] for o in options(ms)}:
                return bad("Ese proyecto no existe.")
            if db.execute(select(LearningResource.id).where(LearningResource.url == url, LearningResource.status != "rejected")).first():
                return bad("Ese enlace ya está en la lista o pendiente de revisión.")
            if not limits["resource"].allow(str(u["uid"])):     # solo cuentan los envíos válidos
                return too_many(u, "ayuda-recursos")
            r = LearningResource(project_id=body.project_id, title=title, url=url, kind=body.kind, submitted_by=u["uid"],
                                 submitted_login=u["login"][:50], status="pending", created_at=utcnow())
            db.add(r)
            db.commit()
            return {"id": r.id, "status": "pending"}

    @app.post("/api/help/offer", dependencies=guard)
    def set_offer(body: OfferIn, request: Request):
        u = current_user(request)
        if u is None:
            return unauth()
        if (err := origin_error(request)) is not None:
            return err
        if not limits["attempt"].allow(str(u["uid"])):
            return too_many(u, "ayuda-intentos")
        try:
            note = clean_text(body.note, min_len=0, max_len=200, field="Nota")
        except ValueError as e:
            return bad(str(e))
        ids = sorted(set(body.project_ids))
        if len(ids) > MAX_OFFER_PROJECTS:
            return bad(f"Puedes ofrecer ayuda en {MAX_OFFER_PROJECTS} proyectos como máximo.")
        with Session(main_engine) as ms, Session(settings_db()) as db:
            validated = validated_projects(ms, u["uid"])
            not_yours = [i for i in ids if i not in validated]
            if not_yours:
                return bad("Solo puedes ofrecer ayuda en proyectos que ya tienes validados.")
            if body.active and not ids:
                return bad("Elige al menos un proyecto para ofrecer ayuda.")
            if not limits["offer"].allow(str(u["uid"])):
                return too_many(u, "ayuda-ofertas")
            offer = db.get(MentorOffer, u["uid"]) or MentorOffer(user_id=u["uid"])
            offer.login, offer.note, offer.active, offer.updated_at = u["login"][:50], note, body.active, utcnow()
            db.add(offer)
            db.query(MentorProject).filter(MentorProject.user_id == u["uid"]).delete()
            db.add_all(MentorProject(user_id=u["uid"], project_id=i) for i in ids)
            db.commit()
            return {"active": offer.active, "note": offer.note, "project_ids": ids}

    @app.post("/api/help/requests", dependencies=guard)
    def create_request(body: RequestIn, request: Request):
        u = current_user(request)
        if u is None:
            return unauth()
        if (err := origin_error(request)) is not None:
            return err
        if not limits["attempt"].allow(str(u["uid"])):
            return too_many(u, "ayuda-intentos")
        try:
            message = clean_text(body.message, min_len=10, max_len=280, field="Mensaje")
        except ValueError as e:
            return bad(str(e))
        with Session(main_engine) as ms, Session(settings_db()) as db:
            if body.project_id not in {o["id"] for o in options(ms)}:
                return bad("Ese proyecto no existe.")
            if body.project_id in validated_projects(ms, u["uid"]):
                return bad("Ya tienes ese proyecto validado.")
            open_reqs = db.execute(_live_requests(db, user_id=u["uid"])).scalars().all()
            if len(open_reqs) >= MAX_OPEN_REQUESTS:
                return bad(f"Ya tienes {MAX_OPEN_REQUESTS} peticiones abiertas. Cierra alguna antes de crear otra.")
            if any(r.project_id == body.project_id for r in open_reqs):
                return bad("Ya tienes una petición abierta para ese proyecto.")
            if not limits["request"].allow(str(u["uid"])):
                return too_many(u, "ayuda-peticiones")
            r = HelpRequest(user_id=u["uid"], login=u["login"][:50], project_id=body.project_id, message=message,
                            status="open", created_at=utcnow())
            db.add(r)
            db.commit()
            return {"id": r.id, "mentors": mentors_for(db, ms, body.project_id, u["uid"], cursus_id, limit=5)}

    @app.post("/api/help/requests/{request_id}/close", dependencies=guard)
    def close_request(request_id: Annotated[int, Path(ge=1, le=MAX_ID)], body: CloseIn, request: Request):
        u = current_user(request)
        if u is None:
            return unauth()
        if (err := origin_error(request)) is not None:
            return err
        with Session(main_engine) as ms, Session(settings_db()) as db:
            r = db.get(HelpRequest, request_id)
            if r is None or (r.user_id != u["uid"] and not is_admin(u)):
                return bad("No encontrada.", 404)       # no se distingue "no existe" de "no es tuya"
            thanked = None
            if body.helped_by:
                if r.user_id != u["uid"]:
                    return bad("Solo quien pidió ayuda puede agradecerla.", 403)
                if not body.no_code:
                    return bad("Confirma que te explicó sin darte código.")
                if not limits["attempt"].allow(str(u["uid"])):
                    return too_many(u, "ayuda-intentos")
                if (why := pointsmod.give_thanks(db, ms, r, body.helped_by)) is not None:
                    return bad(why)
                thanked = body.helped_by
            db.delete(r)                    # el texto libre no se conserva: cerrar es borrar
            db.commit()
            if thanked:                     # si ya había validado el proyecto, el punto queda verificado al momento
                mentor = db.execute(select(MentorOffer.user_id).where(MentorOffer.login == thanked)).scalar()
                pointsmod.verify_pending(db, ms, [mentor])
            return {"id": request_id, "status": "closed", "thanked": thanked}

    # ------------------------------------------------------------ moderación (solo administradores)
    @app.get("/api/admin/help/pending", dependencies=guard)
    def pending(request: Request):
        u = current_user(request)
        if u is None or not is_admin(u):
            return JSONResponse({"detail": "No autorizado."}, status_code=403 if u else 401)
        with Session(main_engine) as ms, Session(settings_db()) as db:
            names = {o["id"]: o["name"] for o in options(ms)}
            rows = db.execute(select(LearningResource).where(LearningResource.status == "pending")
                              .order_by(LearningResource.created_at).limit(100)).scalars().all()
            return {"resources": [{"id": r.id, "title": r.title, "url": r.url, "kind": r.kind, "by": r.submitted_login,
                                   "project": names.get(r.project_id) if r.project_id else "General"} for r in rows]}

    @app.get("/api/admin/help/abuse", dependencies=guard)
    def abuse_list(request: Request):
        u = current_user(request)
        if u is None or not is_admin(u):
            return JSONResponse({"detail": "No autorizado."}, status_code=403 if u else 401)
        if abuse is None:
            return {"events": []}
        with Session(settings_db()) as db:
            return {"events": abuse.recent(db)}

    @app.post("/api/admin/help/resources/{resource_id}/{action}", dependencies=guard)
    def review(resource_id: Annotated[int, Path(ge=1, le=MAX_ID)], action: str, request: Request):
        u = current_user(request)
        if u is None or not is_admin(u):
            return JSONResponse({"detail": "No autorizado."}, status_code=403 if u else 401)
        if (err := origin_error(request)) is not None:
            return err
        if action not in ("approve", "reject") or not limits["admin"].allow(str(u["uid"])):
            return bad("Acción no válida.", 400)
        with Session(settings_db()) as db:
            r = db.get(LearningResource, resource_id)
            if r is None:
                return bad("No encontrado.", 404)
            r.status, r.reviewed_by = ("approved" if action == "approve" else "rejected"), u["uid"]
            db.commit()
            return {"id": r.id, "status": r.status}
