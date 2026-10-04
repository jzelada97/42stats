"""Registro de accesos a la web: cuántos alumnos entran y cuándo, para que un admin vea el uso. Solo login y fechas, nunca IP."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import LoginRecord

RETENTION = timedelta(days=90)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def record_login(db: Session, uid: int, login: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    row = db.get(LoginRecord, uid) or LoginRecord(user_id=uid, first_at=now, logins=0)
    row.login, row.last_at, row.logins = login[:50], now, (row.logins or 0) + 1
    db.add(row)
    db.commit()


def summary(db: Session, now: datetime | None = None, limit: int = 50) -> dict:
    """Alumnos distintos con un acceso en las últimas 24 h, 7 y 30 días, y los accesos más recientes (fechas en UTC con zona)."""
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    count = lambda days: db.scalar(select(func.count()).select_from(LoginRecord).where(LoginRecord.last_at >= now - timedelta(days=days))) or 0  # noqa: E731
    rows = db.execute(select(LoginRecord).order_by(LoginRecord.last_at.desc()).limit(limit)).scalars().all()
    return {"day": count(1), "week": count(7), "month": count(30),
            "total": db.scalar(select(func.count()).select_from(LoginRecord)) or 0,
            "recent": [{"login": r.login, "last": _aware(r.last_at).isoformat(timespec="minutes"), "first": _aware(r.first_at).date().isoformat(),
                        "logins": r.logins} for r in rows]}


def purge(db: Session, now: datetime | None = None) -> None:
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    db.query(LoginRecord).filter(LoginRecord.last_at < now - RETENTION).delete()
