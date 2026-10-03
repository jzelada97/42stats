"""Estadísticas agregadas del campus. Solo devuelven agregados, nunca datos de personas."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .db import CursusUser, Project, ProjectUser, SyncState, User

RISK_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite devuelve fechas sin zona horaria; todas están guardadas en UTC.
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _members(s: Session, cursus_id: int, now: datetime) -> list[dict]:
    """Alumnos del cursus; `current` = cursus todavía abierto."""
    rows = s.execute(
        select(CursusUser.user_id, CursusUser.level, CursusUser.end_at, CursusUser.blackholed_at)
        .where(CursusUser.cursus_id == cursus_id)
    ).all()
    out = []
    for user_id, level, end_at, bh in rows:
        end_at, bh = _aware(end_at), _aware(bh)
        out.append({"user_id": user_id, "level": level, "blackholed_at": bh,
                    "current": end_at is None or end_at > now})
    return out


def overview(s: Session, cursus_id: int = 21, now: datetime | None = None) -> dict:
    now = now or _now()
    count = lambda *where: s.scalar(select(func.count()).select_from(User).where(*where))  # noqa: E731
    members = _members(s, cursus_id, now)
    current = [m for m in members if m["current"]]
    levels = [m["level"] for m in current if m["level"] is not None]
    horizon = now + timedelta(days=RISK_DAYS)
    last_sync = s.scalar(select(func.max(SyncState.last_run_at)))
    return {
        "users_total": s.scalar(select(func.count()).select_from(User)),
        "students": count(User.kind == "student"),
        "active": count(User.kind == "student", User.active.is_(True)),
        "alumni": count(User.alumni.is_(True)),
        "cursus_members": len(members),
        "cursus_current": len(current),
        "cursus_ended": len(members) - len(current),
        "avg_level": round(sum(levels) / len(levels), 2) if levels else None,
        "at_risk": sum(1 for m in current if m["blackholed_at"] and now <= m["blackholed_at"] <= horizon),
        "risk_days": RISK_DAYS,
        "project_users": s.scalar(select(func.count()).select_from(ProjectUser)),
        "last_sync": last_sync,
    }


def levels(s: Session, cursus_id: int = 21, now: datetime | None = None) -> list[dict]:
    """Histograma de nivel (partes enteras) de los alumnos con el cursus abierto."""
    now = now or _now()
    counts = Counter(int(m["level"]) for m in _members(s, cursus_id, now)
                     if m["current"] and m["level"] is not None)
    if not counts:
        return []
    return [{"level": n, "count": counts.get(n, 0)} for n in range(0, max(counts) + 1)]


def cohorts(s: Session, cursus_id: int = 21, now: datetime | None = None) -> list[dict]:
    """Por promoción (año de la piscina): cuántos entraron y cuántos siguen en el cursus."""
    now = now or _now()
    members = {m["user_id"]: m for m in _members(s, cursus_id, now)}
    pools: dict[str, dict] = defaultdict(lambda: {"pool": 0, "in_cursus": 0, "current": 0, "levels": []})
    for uid, year in s.execute(
        select(User.id, User.pool_year).where(User.kind == "student", User.pool_year.is_not(None))
    ):
        c = pools[year]
        c["pool"] += 1
        m = members.get(uid)
        if m:
            c["in_cursus"] += 1
            if m["current"]:
                c["current"] += 1
                if m["level"] is not None:
                    c["levels"].append(m["level"])
    out = []
    for year, c in sorted(pools.items(), key=lambda kv: kv[0], reverse=True):
        lv = c["levels"]
        out.append({
            "year": year, "pool": c["pool"], "in_cursus": c["in_cursus"], "current": c["current"],
            "retention": round(c["current"] / c["in_cursus"], 3) if c["in_cursus"] else None,
            "avg_level": round(sum(lv) / len(lv), 2) if lv else None,
        })
    return out


def signups(s: Session, months: int = 36) -> list[dict]:
    """Altas de alumnos por mes (fecha de creación de la cuenta), con los meses vacíos a 0."""
    counts = Counter(
        d.strftime("%Y-%m")
        for (d,) in s.execute(select(User.created_at).where(User.kind == "student", User.created_at.is_not(None)))
    )
    if not counts:
        return []
    now = _now()
    y, m = now.year, now.month
    keys = []
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    keys.reverse()
    first = min(counts)
    return [{"month": k, "count": counts.get(k, 0)} for k in keys if k >= first]


def projects(s: Session, min_attempts: int = 20, limit: int = 25) -> list[dict]:
    """Proyectos del 42cursus con más intentos: tasa de validación y nota media."""
    finished = case((ProjectUser.status == "finished", 1), else_=0)
    validated = case((ProjectUser.validated.is_(True), 1), else_=0)
    mark = case((ProjectUser.status == "finished", ProjectUser.final_mark))
    rows = s.execute(
        select(
            Project.id, Project.name, func.count().label("attempts"),
            func.sum(finished), func.sum(validated), func.avg(mark),
        )
        .join(Project, Project.id == ProjectUser.project_id)
        .group_by(Project.id, Project.name)
        .having(func.count() >= min_attempts)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": pid, "name": name, "attempts": attempts, "finished": int(fin or 0),
            "validated": int(val or 0),
            "validation_rate": round(int(val or 0) / int(fin), 3) if fin else None,
            "avg_mark": round(avg, 1) if avg is not None else None,
        }
        for pid, name, attempts, fin, val, avg in rows
    ]
