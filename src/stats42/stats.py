"""Estadísticas agregadas del campus. Solo devuelven agregados, nunca datos de personas."""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from .db import CursusUser, Evaluation, Event, Exam, Location, Project, ProjectUser, SyncState, User

RISK_DAYS = 30
TZ = ZoneInfo("Europe/Madrid")
MAX_SESSION = timedelta(hours=12)  # una sesión más larga es un logout que no se registró
HOST_RE = re.compile(r"^c(\d+)r(\d+)s(\d+)$")  # cluster, fila, puesto: c3r5s1
DURATION_BUCKETS = [(15, "<15m"), (30, "15-30m"), (60, "30-60m"), (120, "1-2h"),
                    (240, "2-4h"), (480, "4-8h"), (float("inf"), ">8h")]
MARK_BUCKETS = [(0, 0, "0"), (1, 49, "1-49"), (50, 79, "50-79"), (80, 99, "80-99"), (100, 100, "100"),
                (101, 1000, "101-125")]


# Recursos que sincroniza el job; mientras alguno no tenga su primera carga completa, las cifras son parciales.
SYNC_RESOURCES = ("users", "cursus_users", "projects", "events", "exams", "project_users", "evaluations", "locations")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite devuelve fechas sin zona horaria; todas están guardadas en UTC.
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _month(s: Session, col):
    """Expresión SQL 'YYYY-MM' (SQLite y PostgreSQL)."""
    if s.get_bind().dialect.name == "sqlite":
        return func.strftime("%Y-%m", col)
    return func.to_char(col, "YYYY-MM")


def _last_months(n: int, now: datetime | None = None) -> list[str]:
    now = now or _now()
    y, m = now.year, now.month
    keys = []
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return keys[::-1]


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


def _count(s: Session, model, *where) -> int:
    return s.scalar(select(func.count()).select_from(model).where(*where)) or 0


# ---------------------------------------------------------------- resumen

def overview(s: Session, cursus_id: int = 21, now: datetime | None = None) -> dict:
    now = now or _now()
    members = _members(s, cursus_id, now)
    current = [m for m in members if m["current"]]
    levels = [m["level"] for m in current if m["level"] is not None]
    horizon = now + timedelta(days=RISK_DAYS)
    return {
        "users_total": _count(s, User),
        "students": _count(s, User, User.kind == "student"),
        "active": _count(s, User, User.kind == "student", User.active.is_(True)),
        "alumni": _count(s, User, User.alumni.is_(True)),
        "cursus_members": len(members),
        "cursus_current": len(current),
        "cursus_ended": len(members) - len(current),
        "avg_level": round(sum(levels) / len(levels), 2) if levels else None,
        "at_risk": sum(1 for m in current if m["blackholed_at"] and now <= m["blackholed_at"] <= horizon),
        "risk_days": RISK_DAYS,
        "project_users": _count(s, ProjectUser),
        "sessions": _count(s, Location),
        "evaluations": _count(s, Evaluation),
        "events": _count(s, Event),
        "exams": _count(s, Exam),
        "last_sync": s.scalar(select(func.max(SyncState.last_run_at))),
        "loading": _loading(s),
    }


def _loading(s: Session) -> list[str]:
    """Recursos sin su primera carga completa (sin marca de agua)."""
    done = {r for (r,) in s.execute(select(SyncState.resource).where(SyncState.watermark.is_not(None)))}
    return [r for r in SYNC_RESOURCES if r not in done]


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
    m = _month(s, User.created_at)
    counts = dict(s.execute(
        select(m, func.count()).where(User.kind == "student", User.created_at.is_not(None)).group_by(m)
    ).all())
    if not counts:
        return []
    first = min(counts)
    return [{"month": k, "count": counts.get(k, 0)} for k in _last_months(months) if k >= first]


# ---------------------------------------------------------------- proyectos

def _done():
    """Intento terminado: estado finished, o ya con resultado (validated no nulo) aunque el estado sea otro."""
    return or_(ProjectUser.status == "finished", ProjectUser.validated.is_not(None))


def projects(s: Session, min_attempts: int = 20, limit: int = 30) -> list[dict]:
    """Proyectos del 42cursus con más intentos: validación, nota media y tiempo mediano."""
    done = _done()
    finished = case((done, 1), else_=0)
    validated = case((ProjectUser.validated.is_(True), 1), else_=0)
    in_progress = case((ProjectUser.status == "in_progress", 1), else_=0)
    mark = case((done, ProjectUser.final_mark))
    rows = s.execute(
        select(
            Project.id, Project.name, Project.difficulty, func.count().label("attempts"),
            func.sum(finished), func.sum(validated), func.sum(in_progress), func.avg(mark),
        )
        .join(Project, Project.id == ProjectUser.project_id)
        .group_by(Project.id, Project.name, Project.difficulty)
        .having(func.count() >= min_attempts)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    ids = [r[0] for r in rows]
    days: dict[int, list[float]] = defaultdict(list)
    if ids:
        for pid, created, marked in s.execute(
            select(ProjectUser.project_id, ProjectUser.created_at, ProjectUser.marked_at)
            .where(ProjectUser.project_id.in_(ids), _done(),
                   ProjectUser.marked_at.is_not(None), ProjectUser.created_at.is_not(None))
        ):
            d = (_aware(marked) - _aware(created)).total_seconds() / 86400
            if d >= 0:
                days[pid].append(d)
    return [
        {
            "id": pid, "name": name, "difficulty": diff, "attempts": attempts,
            "finished": int(fin or 0), "validated": int(val or 0), "in_progress": int(prog or 0),
            "validation_rate": round(int(val or 0) / int(fin), 3) if fin else None,
            "avg_mark": round(avg, 1) if avg is not None else None,
            "median_days": round(statistics.median(days[pid]), 1) if days.get(pid) else None,
        }
        for pid, name, diff, attempts, fin, val, prog, avg in rows
    ]


def projects_monthly(s: Session, months: int = 36) -> list[dict]:
    """Proyectos terminados por mes (por fecha de nota), separando validados y no validados."""
    m = _month(s, ProjectUser.marked_at)
    rows = s.execute(
        select(m, func.sum(case((ProjectUser.validated.is_(True), 1), else_=0)), func.count())
        .where(_done(), ProjectUser.marked_at.is_not(None))
        .group_by(m)
    ).all()
    data = {k: (int(v or 0), int(t)) for k, v, t in rows}
    if not data:
        return []
    first = min(data)
    return [{"month": k, "validated": data.get(k, (0, 0))[0],
             "failed": data.get(k, (0, 0))[1] - data.get(k, (0, 0))[0]}
            for k in _last_months(months) if k >= first]


# ---------------------------------------------------------------- asistencia

def _bucket(minutes: float) -> str:
    return next(label for limit, label in DURATION_BUCKETS if minutes < limit)


def attendance(s: Session, days: int = 90, now: datetime | None = None) -> dict:
    """Ocupación del campus en los últimos `days` días completos (hora de Madrid)."""
    now = now or _now()
    today = now.astimezone(TZ).date()
    start, end = today - timedelta(days=days), today - timedelta(days=1)
    since = datetime.combine(start - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    minutes: dict[tuple[date, int], float] = defaultdict(float)
    day_hours: dict[date, float] = defaultdict(float)
    day_users: dict[date, set] = defaultdict(set)
    durations: Counter = Counter()
    seats: Counter = Counter()  # (cluster, fila, puesto) -> sesiones
    users: set = set()
    n = 0
    total_min = 0.0

    for uid, host, b, e in s.execute(
        select(Location.user_id, Location.host, Location.begin_at, Location.end_at)
        .where(Location.begin_at >= since)
    ):
        b, e = _aware(b), _aware(e)
        if b is None:
            continue
        stop = min(e if e else min(now, b + MAX_SESSION), b + MAX_SESSION)
        if stop <= b:
            continue
        lb, le = b.astimezone(TZ), stop.astimezone(TZ)
        if not (start <= lb.date() <= end):
            continue
        n += 1
        users.add(uid)
        day_users[lb.date()].add(uid)
        mins = (stop - b).total_seconds() / 60
        total_min += mins
        durations[_bucket(mins)] += 1
        cur = lb
        while cur < le:
            nxt = cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            seg = min(nxt, le)
            m = (seg - cur).total_seconds() / 60
            minutes[(cur.date(), cur.hour)] += m
            day_hours[cur.date()] += m / 60
            cur = seg
        mt = HOST_RE.match(host or "")
        if mt:
            seats[(int(mt[1]), int(mt[2]), int(mt[3]))] += 1

    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    weekday_days = Counter(d.weekday() for d in dates)
    acc: dict[tuple[int, int], float] = defaultdict(float)
    for (d, h), m in minutes.items():
        if start <= d <= end:
            acc[(d.weekday(), h)] += m
    heatmap = [{"weekday": wd, "hour": h,
                "value": round(acc[(wd, h)] / 60 / weekday_days[wd], 1) if weekday_days[wd] else 0}
               for wd in range(7) for h in range(24)]
    peak = max(heatmap, key=lambda c: c["value"]) if heatmap else None

    clusters = Counter()
    for (c, _r, _s), k in seats.items():
        clusters[c] += k
    return {
        "days": days,
        "sessions": n,
        "unique_users": len(users),
        "total_hours": round(total_min / 60),
        "avg_session_min": round(total_min / n) if n else None,
        "peak": peak if peak and peak["value"] > 0 else None,
        "heatmap": heatmap,
        "daily": [{"date": d.isoformat(), "hours": round(day_hours.get(d, 0), 1),
                   "users": len(day_users.get(d, ()))} for d in dates],
        "durations": [{"label": label, "count": durations.get(label, 0)} for _, label in DURATION_BUCKETS],
        "clusters": [{"cluster": c, "sessions": k} for c, k in sorted(clusters.items())],
        "seats": [{"cluster": c, "row": r, "seat": st, "sessions": k} for (c, r, st), k in sorted(seats.items())],
    }


# ---------------------------------------------------------------- evaluaciones

def evaluations(s: Session, months: int = 36, now: datetime | None = None) -> dict:
    now = now or _now()
    done = Evaluation.filled_at.is_not(None)
    m = _month(s, Evaluation.filled_at)
    monthly_rows = {k: (c, a) for k, c, a in s.execute(
        select(m, func.count(), func.avg(Evaluation.final_mark)).where(done).group_by(m)).all()}
    first = min(monthly_rows) if monthly_rows else None
    monthly = [{"month": k, "count": monthly_rows.get(k, (0, None))[0],
                "avg_mark": round(monthly_rows[k][1], 1) if k in monthly_rows and monthly_rows[k][1] is not None else None}
               for k in _last_months(months, now) if first and k >= first]

    flags = [{"name": name or "Sin flag", "count": c} for name, c in s.execute(
        select(Evaluation.flag_name, func.count()).where(done).group_by(Evaluation.flag_name)
        .order_by(func.count().desc()))]

    marks = []
    for lo, hi, label in MARK_BUCKETS:
        marks.append({"label": label, "count": _count(
            s, Evaluation, done, Evaluation.final_mark.is_not(None), Evaluation.final_mark >= lo,
            Evaluation.final_mark <= hi)})

    total = _count(s, Evaluation, done)
    positive = _count(s, Evaluation, done, Evaluation.flag_positive.is_(True))
    ninety = now - timedelta(days=90)
    return {
        "total": total,
        "avg_mark": round(s.scalar(select(func.avg(Evaluation.final_mark)).where(done)) or 0, 1) if total else None,
        "positive_share": round(positive / total, 3) if total else None,
        "truant": _count(s, Evaluation, Evaluation.truant.is_(True)),
        "scheduled": _count(s, Evaluation, Evaluation.filled_at.is_(None), Evaluation.begin_at >= now),
        "active_correctors_90d": s.scalar(
            select(func.count(func.distinct(Evaluation.corrector_id)))
            .where(done, Evaluation.filled_at >= ninety, Evaluation.corrector_id.is_not(None))) or 0,
        "monthly": monthly,
        "flags": flags,
        "marks": marks,
    }


# ---------------------------------------------------------------- eventos y exámenes

def events_exams(s: Session, months: int = 24, now: datetime | None = None) -> dict:
    now = now or _now()

    def monthly(model):
        m = _month(s, model.begin_at)
        counts = dict(s.execute(select(m, func.count()).where(model.begin_at.is_not(None)).group_by(m)).all())
        first = min(counts) if counts else None
        return [{"month": k, "count": counts.get(k, 0)} for k in _last_months(months, now) if first and k >= first]

    def upcoming(model, limit, extra=()):
        rows = s.execute(select(model).where(model.begin_at >= now).order_by(model.begin_at).limit(limit)).scalars()
        return [{"name": r.name, "begin_at": _aware(r.begin_at).isoformat(), "location": r.location,
                 "subscribers": r.nbr_subscribers, "max_people": r.max_people or None,
                 **{k: getattr(r, k) for k in extra}} for r in rows]

    kinds = [{"kind": k or "otro", "count": c, "avg_subscribers": round(a, 1) if a is not None else None}
             for k, c, a in s.execute(
                 select(Event.kind, func.count(), func.avg(Event.nbr_subscribers)).group_by(Event.kind)
                 .order_by(func.count().desc()).limit(8))]
    return {
        "events_monthly": monthly(Event),
        "exams_monthly": monthly(Exam),
        "kinds": kinds,
        "upcoming_events": upcoming(Event, 8, ("kind",)),
        "upcoming_exams": upcoming(Exam, 6),
    }
