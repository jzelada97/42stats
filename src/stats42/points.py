"""Puntos de mentoría. Un punto solo cuenta cuando está VERIFICADO por tres lados:

1. el mentor se ofreció a ESA petición ("Quiero ayudar") y quien pidió ayuda lo agradeció al cerrarla,
2. el mentor confirmó que explicó sin dar código, y
3. el alumno validó ese proyecto según nuestros datos, entre 48 horas y 120 días después de pedir ayuda.

Más topes contra el abuso: un agradecimiento por alumno y proyecto, como mucho 2 puntos por pareja mentor-alumno y 3 agradecimientos
por semana. La ayuda ocurre fuera de la web, así que no se puede comprobar al 100 %: se sube el coste del abuso y se deja a un
admin ver las anomalías y anular puntos. Tramos con nombre, sin ranking numérico: un ranking empuja a pasar código para sumar.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import HelpOffer, HelpRequest, MentorOffer, MentorProject, MentorThanks, ProjectUser, User

TIERS = ((15, "Bosque"), (5, "Caña"), (1, "Brote"))      # de más a menos
THANKS_PER_WEEK = 3
MAX_PER_PAIR = 2
MIN_WAIT = timedelta(hours=48)                            # validar antes sugiere que el proyecto ya estaba hecho al pedir ayuda
MAX_WAIT = timedelta(days=120)
PENDING_TTL = timedelta(days=365)                         # un agradecimiento que nunca se completa no se guarda para siempre
MAX_RESPONDERS = 5                                        # mentores que pueden ofrecerse a la vez a una misma petición


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def tier(points: int) -> str | None:
    return next((name for need, name in TIERS if points >= need), None)


def next_tier(points: int) -> dict | None:
    ahead = [(need, name) for need, name in TIERS if need > points]
    if not ahead:
        return None
    need, name = min(ahead)
    return {"name": name, "needs": need - points}


def verify_pending(db: Session, ms: Session, mentors: list[int] | None = None) -> None:
    """Marca como verificados los agradecimientos cuyo alumno validó el proyecto dentro de la ventana permitida."""
    stmt = select(MentorThanks).where(MentorThanks.verified.is_(False), MentorThanks.asker_uid > 0, MentorThanks.revoked.is_(False))
    if mentors is not None:
        if not mentors:
            return
        stmt = stmt.where(MentorThanks.mentor_uid.in_(mentors))
    rows = db.execute(stmt).scalars().all()
    if not rows:
        return
    attempts: dict[tuple[int, int], list[datetime]] = defaultdict(list)
    for u, p, at in ms.execute(
        select(ProjectUser.user_id, ProjectUser.project_id, ProjectUser.marked_at)
        .where(ProjectUser.validated.is_(True), ProjectUser.user_id.in_({r.asker_uid for r in rows}),
               ProjectUser.project_id.in_({r.project_id for r in rows}), ProjectUser.marked_at.is_not(None))):
        attempts[(u, p)].append(_aware(at))
    now, changed = datetime.now(timezone.utc), False
    for r in rows:
        asked = _aware(r.asked_at)
        if any(asked + MIN_WAIT <= at <= asked + MAX_WAIT for at in attempts.get((r.asker_uid, r.project_id), [])):
            r.verified, r.verified_at, changed = True, now, True
    if changed:
        db.commit()


def counts(db: Session, ms: Session, mentor_uids: list[int]) -> dict[int, dict]:
    """Por mentor: puntos (verificados Y confirmados), pendientes y agradecimientos que aún debe confirmar."""
    out = {u: {"verified": 0, "pending": 0, "to_confirm": 0} for u in mentor_uids}
    if not mentor_uids:
        return out
    verify_pending(db, ms, mentor_uids)
    for uid, verified, confirmed, n in db.execute(
            select(MentorThanks.mentor_uid, MentorThanks.verified, MentorThanks.confirmed, func.count())
            .where(MentorThanks.mentor_uid.in_(mentor_uids), MentorThanks.revoked.is_(False))
            .group_by(MentorThanks.mentor_uid, MentorThanks.verified, MentorThanks.confirmed)):
        if verified and confirmed:
            out[uid]["verified"] += n
        else:
            out[uid]["pending"] += n
        if not confirmed:
            out[uid]["to_confirm"] += n
    for c in out.values():
        c["tier"], c["next"] = tier(c["verified"]), next_tier(c["verified"])
    return out


def _is_live_mentor(db: Session, ms: Session, uid: int, project_id: int) -> bool:
    offer = db.get(MentorOffer, uid)
    return bool(offer and offer.active and db.get(MentorProject, (uid, project_id)) is not None and
                ms.scalar(select(ProjectUser.id).where(ProjectUser.user_id == uid, ProjectUser.project_id == project_id,
                                                       ProjectUser.validated.is_(True)).limit(1)) is not None)


def offer_help(db: Session, ms: Session, req: HelpRequest, mentor_uid: int) -> str | None:
    """"Quiero ayudar": un mentor se ofrece a una petición concreta. Devuelve el motivo del rechazo, o None."""
    if req.user_id == mentor_uid:
        return "No puedes ofrecerte a tu propia petición."
    if not _is_live_mentor(db, ms, mentor_uid, req.project_id):
        return "Solo puedes ofrecerte en proyectos que ya validaste y en los que figuras como mentor."
    if db.scalar(select(HelpOffer.id).where(HelpOffer.request_id == req.id, HelpOffer.mentor_uid == mentor_uid)) is not None:
        return None
    if (db.scalar(select(func.count()).select_from(HelpOffer).where(HelpOffer.request_id == req.id)) or 0) >= MAX_RESPONDERS:
        return f"Ya hay {MAX_RESPONDERS} mentores ofrecidos a esta petición."
    db.add(HelpOffer(request_id=req.id, mentor_uid=mentor_uid, created_at=datetime.now(timezone.utc)))
    return None


def give_thanks(db: Session, ms: Session, req: HelpRequest, mentor_login: str, now: datetime | None = None) -> str | None:
    """Anota el agradecimiento de quien pidió `req` al mentor que se ofreció a ella. Devuelve el motivo del rechazo, o None."""
    now = now or datetime.now(timezone.utc)
    offer = db.execute(select(MentorOffer).where(MentorOffer.login == mentor_login)).scalars().first()
    if offer is None or offer.user_id == req.user_id or \
            db.scalar(select(HelpOffer.id).where(HelpOffer.request_id == req.id, HelpOffer.mentor_uid == offer.user_id)) is None:
        return "Solo puedes agradecer a quien se ofreció a ayudarte en esta petición."
    if not _is_live_mentor(db, ms, offer.user_id, req.project_id):
        return "Ese mentor ya no figura como mentor de este proyecto."
    if db.scalar(select(MentorThanks.id).where(MentorThanks.asker_uid == req.user_id, MentorThanks.project_id == req.project_id)) is not None:
        return "Ya agradeciste la ayuda de este proyecto."
    if (db.scalar(select(func.count()).select_from(MentorThanks).where(
            MentorThanks.asker_uid == req.user_id, MentorThanks.mentor_uid == offer.user_id, MentorThanks.revoked.is_(False))) or 0) >= MAX_PER_PAIR:
        return f"Ya agradeciste {MAX_PER_PAIR} veces a este mentor: es el máximo por pareja."
    since = (now - timedelta(days=7)).replace(tzinfo=None)
    if (db.scalar(select(func.count()).select_from(MentorThanks)
                  .where(MentorThanks.asker_uid == req.user_id, MentorThanks.created_at >= since)) or 0) >= THANKS_PER_WEEK:
        return f"Puedes agradecer como mucho {THANKS_PER_WEEK} ayudas por semana."
    db.add(MentorThanks(asker_uid=req.user_id, mentor_uid=offer.user_id, project_id=req.project_id, asked_at=req.created_at,
                        created_at=now, verified=False, confirmed=False))
    return None


def respond(db: Session, mentor_uid: int, thanks_id: int, ok: bool) -> str | None:
    """El mentor confirma (o niega) que explicó sin dar código. Negar borra el agradecimiento: no cuenta y el alumno puede agradecer a otro."""
    row = db.get(MentorThanks, thanks_id)
    if row is None or row.mentor_uid != mentor_uid or row.revoked:
        return "No encontrado."
    if row.confirmed:
        return None
    if ok:
        row.confirmed, row.confirmed_at = True, datetime.now(timezone.utc)
    else:
        db.delete(row)
    return None


def admin_overview(db: Session, ms: Session, names: dict[int, str], recent: int = 40) -> dict:
    """Lo que un admin necesita para detectar abusos: puntos por mentor, cuántos alumnos distintos, parejas repetidas y lo último."""
    verify_pending(db, ms)
    rows = db.execute(select(MentorThanks).order_by(MentorThanks.created_at.desc())).scalars().all()
    week = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)
    by_mentor: dict[int, list[MentorThanks]] = defaultdict(list)
    for r in rows:
        by_mentor[r.mentor_uid].append(r)
    ids = {r.mentor_uid for r in rows} | {r.asker_uid for r in rows if r.asker_uid > 0}
    logins = dict(ms.execute(select(User.id, User.login).where(User.id.in_(ids))).all()) if ids else {}
    mentors = []
    for uid, rs in by_mentor.items():
        live = [r for r in rs if not r.revoked]
        pair = defaultdict(int)
        for r in live:
            pair[r.asker_uid] += 1
        flags = []
        if any(n >= MAX_PER_PAIR for k, n in pair.items() if k > 0):
            flags.append("pareja repetida")
        if sum(1 for r in live if r.created_at and r.created_at >= week) >= 4:
            flags.append("muchos en 7 días")
        mentors.append({"login": logins.get(uid, "?"), "verified": sum(1 for r in live if r.verified and r.confirmed),
                        "pending": sum(1 for r in live if not (r.verified and r.confirmed)),
                        "askers": len(pair), "last7": sum(1 for r in live if r.created_at and r.created_at >= week), "flags": flags})
    mentors.sort(key=lambda m: (-len(m["flags"]), -m["verified"]))

    def status(r: MentorThanks) -> str:
        if r.revoked:
            return "anulado"
        if r.verified and r.confirmed:
            return "cuenta"
        if not r.confirmed:
            return "falta confirmación del mentor"
        return "falta que el alumno valide"
    return {"mentors": mentors[:40], "recent": [
        {"id": r.id, "mentor": logins.get(r.mentor_uid, "?"), "asker": logins.get(r.asker_uid), "project": names.get(r.project_id, "?"),
         "status": status(r), "days": (datetime.now(timezone.utc) - _aware(r.created_at)).days if r.created_at else None, "revoked": r.revoked}
        for r in rows[:recent]]}


def revoke(db: Session, thanks_id: int, admin_uid: int) -> bool:
    row = db.get(MentorThanks, thanks_id)
    if row is None:
        return False
    row.revoked, row.revoked_by = True, admin_uid
    return True


def open_offers_for(db: Session, request_ids: list[int]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = defaultdict(list)
    if request_ids:
        for rid, uid in db.execute(select(HelpOffer.request_id, HelpOffer.mentor_uid).where(HelpOffer.request_id.in_(request_ids))
                                   .order_by(HelpOffer.created_at)):
            out[rid].append(uid)
    return out

