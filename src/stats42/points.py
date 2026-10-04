"""Puntos de mentoría. Un punto solo cuenta cuando está VERIFICADO:

1. quien pidió ayuda lo agradece al cerrar su petición (una vez por proyecto, a un mentor que de verdad figura para él), y
2. después valida ese proyecto según nuestros datos (cuyo `marked_at` es posterior a la petición).

Así nadie fabrica puntos con amigos que no avanzan: el alumno tiene que haber pedido ayuda, haber agradecido y haber validado.
Tramos con nombre, sin ranking numérico: un ranking empuja a pasar código para sumar, y eso en 42 es cheating.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import HelpRequest, MentorOffer, MentorProject, MentorThanks, ProjectUser

TIERS = ((15, "Bosque"), (5, "Caña"), (1, "Brote"))      # de más a menos
THANKS_PER_WEEK = 3
PENDING_TTL = timedelta(days=365)                         # un agradecimiento que nunca se verifica no se guarda para siempre


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
    """Marca como verificados los agradecimientos cuyo alumno ya validó el proyecto después de pedir ayuda."""
    stmt = select(MentorThanks).where(MentorThanks.verified.is_(False), MentorThanks.asker_uid > 0)
    if mentors is not None:
        if not mentors:
            return
        stmt = stmt.where(MentorThanks.mentor_uid.in_(mentors))
    rows = db.execute(stmt).scalars().all()
    if not rows:
        return
    done = {(u, p): at for u, p, at in ms.execute(
        select(ProjectUser.user_id, ProjectUser.project_id, func.max(ProjectUser.marked_at))
        .where(ProjectUser.validated.is_(True), ProjectUser.user_id.in_({r.asker_uid for r in rows}),
               ProjectUser.project_id.in_({r.project_id for r in rows}), ProjectUser.marked_at.is_not(None))
        .group_by(ProjectUser.user_id, ProjectUser.project_id))}
    now, changed = datetime.now(timezone.utc), False
    for r in rows:
        at = done.get((r.asker_uid, r.project_id))
        if at is not None and _aware(at) >= _aware(r.asked_at):
            r.verified, r.verified_at, changed = True, now, True
    if changed:
        db.commit()


def counts(db: Session, ms: Session, mentor_uids: list[int]) -> dict[int, dict]:
    """Puntos verificados y pendientes de cada mentor (verifica antes lo que ya se pueda verificar)."""
    out = {u: {"verified": 0, "pending": 0} for u in mentor_uids}
    if not mentor_uids:
        return out
    verify_pending(db, ms, mentor_uids)
    for uid, verified, n in db.execute(select(MentorThanks.mentor_uid, MentorThanks.verified, func.count())
                                       .where(MentorThanks.mentor_uid.in_(mentor_uids))
                                       .group_by(MentorThanks.mentor_uid, MentorThanks.verified)):
        out[uid]["verified" if verified else "pending"] = n
    for c in out.values():
        c["tier"], c["next"] = tier(c["verified"]), next_tier(c["verified"])
    return out


def give_thanks(db: Session, ms: Session, req: HelpRequest, mentor_login: str, now: datetime | None = None) -> str | None:
    """Anota el agradecimiento de quien pidió `req` al mentor indicado. Devuelve el motivo del rechazo, o None si se anotó."""
    now = now or datetime.now(timezone.utc)
    offer = db.execute(select(MentorOffer).where(MentorOffer.login == mentor_login)).scalars().first()
    if offer is None or not offer.active or offer.user_id == req.user_id or db.get(MentorProject, (offer.user_id, req.project_id)) is None:
        return "Ese alumno no figura como mentor de este proyecto."
    if ms.scalar(select(ProjectUser.id).where(ProjectUser.user_id == offer.user_id, ProjectUser.project_id == req.project_id,
                                              ProjectUser.validated.is_(True)).limit(1)) is None:
        return "Ese alumno no figura como mentor de este proyecto."
    if db.scalar(select(MentorThanks.id).where(MentorThanks.asker_uid == req.user_id, MentorThanks.project_id == req.project_id)) is not None:
        return "Ya agradeciste la ayuda de este proyecto."
    since = (now - timedelta(days=7)).replace(tzinfo=None)
    if (db.scalar(select(func.count()).select_from(MentorThanks)
                  .where(MentorThanks.asker_uid == req.user_id, MentorThanks.created_at >= since)) or 0) >= THANKS_PER_WEEK:
        return f"Puedes agradecer como mucho {THANKS_PER_WEEK} ayudas por semana."
    db.add(MentorThanks(asker_uid=req.user_id, mentor_uid=offer.user_id, project_id=req.project_id, asked_at=req.created_at,
                        created_at=now, verified=False))
    return None
