"""Estadísticas agregadas del campus. Solo devuelven agregados, nunca datos de personas."""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from .db import (CursusUser, Evaluation, Event, Exam, Location, Project, ProjectUser, Quest, QuestUser, SyncState,
                 User)

RISK_DAYS = 30
# Un cursus cerrado cuenta como "blackholeado" si se cierra entre 1 día antes y 60 después de su fecha de
# blackhole (en los datos, el sistema lo cierra el mismo día o al siguiente). Si se cierra más de 1 día antes,
# es una baja anterior al blackhole. Más de 60 días después o sin fecha: no se clasifica.
BLACKHOLE_LAG_DAYS = (-1, 60)
TZ = ZoneInfo("Europe/Madrid")
MAX_SESSION = timedelta(hours=12)  # una sesión más larga es un logout que no se registró
HOST_RE = re.compile(r"^c(\d+)r(\d+)s(\d+)$")  # cluster, fila, puesto: c3r5s1
DURATION_BUCKETS = [(15, "<15m"), (30, "15-30m"), (60, "30-60m"), (120, "1-2h"),
                    (240, "2-4h"), (480, "4-8h"), (float("inf"), ">8h")]
MARK_BUCKETS = [(0, 0, "0"), (1, 49, "1-49"), (50, 79, "50-79"), (80, 99, "80-99"), (100, 100, "100"),
                (101, 1000, "101-125")]


# Recursos que sincroniza el job; mientras alguno no tenga su primera carga completa, las cifras son parciales.
SYNC_RESOURCES = ("users", "cursus_users", "projects", "events", "exams", "quests", "quest_users", "project_users",
                  "evaluations", "locations")


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
    """Alumnos del cursus (solo `kind = student`: no cuentan las de staff ni las externas).

    `current` = cursus abierto y NO graduado (alumni): es el alumno que sigue en el programa. Quien ya es alumni se separa
    como `graduated`, porque conserva el cursus abierto pero ya no avanza ni corre ningún plazo."""
    rows = s.execute(
        select(CursusUser.user_id, CursusUser.level, CursusUser.end_at, CursusUser.blackholed_at, User.alumni)
        .join(User, User.id == CursusUser.user_id)
        .where(CursusUser.cursus_id == cursus_id, User.kind == "student")
    ).all()
    out = []
    for user_id, level, end_at, bh, alumni in rows:
        end_at, bh = _aware(end_at), _aware(bh)
        m = {"user_id": user_id, "level": level, "blackholed_at": bh, "end_at": end_at, "alumni": bool(alumni),
             "current": (end_at is None or end_at > now) and not alumni}
        m["outcome"] = _outcome(m)
        out.append(m)
    return out


CLOSED = ("blackholed", "dropped", "other")        # cursus cerrado sin graduarse, sea cual sea su relación con la fecha de la API


def _outcome(m: dict) -> str:
    """current | graduated | blackholed | dropped | other.

    En 42 NO existe la baja voluntaria: quien se quiere ir deja de venir y acaba blackholeado. Por eso todo cursus cerrado sin
    graduarse (`CLOSED`) es, en la práctica, un cierre por blackhole. Lo que distingue estas etiquetas es solo la relación entre el
    cierre y la fecha de blackhole que devuelve la API, que es orientativa (no refleja los plazos por milestone ni los freezes):
    `blackholed` = cierra entre 1 día antes y 60 después de esa fecha; `dropped` = cierra antes; `other` = cierra mucho después o no
    hay fecha. `dropped` NO significa baja voluntaria."""
    if m["alumni"]:
        return "graduated"
    if m["current"]:
        return "current"
    if m["blackholed_at"] is None or m["end_at"] is None:
        return "other"
    lag = (m["end_at"] - m["blackholed_at"]).total_seconds() / 86400
    if BLACKHOLE_LAG_DAYS[0] <= lag <= BLACKHOLE_LAG_DAYS[1]:
        return "blackholed"
    return "dropped" if lag < BLACKHOLE_LAG_DAYS[0] else "other"


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
        "cursus_graduated": sum(1 for m in members if m["outcome"] == "graduated"),
        "cursus_closed": sum(1 for m in members if m["outcome"] in CLOSED),
        "cursus_ended": len(members) - len(current),
        "cursus_blackholed": sum(1 for m in members if m["outcome"] == "blackholed"),
        "cursus_dropped": sum(1 for m in members if m["outcome"] == "dropped"),
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
    pools: dict[str, dict] = defaultdict(
        lambda: {"pool": 0, "in_cursus": 0, "current": 0, "graduated": 0, "closed": 0, "blackholed": 0, "dropped": 0, "levels": []})
    for uid, year in s.execute(
        select(User.id, User.pool_year).where(User.kind == "student", User.pool_year.is_not(None))
    ):
        c = pools[year]
        c["pool"] += 1
        m = members.get(uid)
        if m:
            c["in_cursus"] += 1
            if m["outcome"] in ("blackholed", "dropped"):
                c[m["outcome"]] += 1
            if m["outcome"] in CLOSED:
                c["closed"] += 1
            if m["outcome"] == "graduated":
                c["graduated"] += 1
            if m["current"]:
                c["current"] += 1
                if m["level"] is not None:
                    c["levels"].append(m["level"])
    out = []
    for year, c in sorted(pools.items(), key=lambda kv: kv[0], reverse=True):
        lv = c["levels"]
        out.append({
            "year": year, "pool": c["pool"], "in_cursus": c["in_cursus"], "current": c["current"], "graduated": c["graduated"],
            "closed": c["closed"], "blackholed": c["blackholed"], "dropped": c["dropped"],
            # retención = la parte de la promoción que NO ha cerrado el cursus sin graduarse (sigue en el programa o se graduó)
            "retention": round((c["in_cursus"] - c["closed"]) / c["in_cursus"], 3) if c["in_cursus"] else None,
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

CHEAT_MARK = -42  # 42 marca con -42 los intentos con cheating: no son un intento normal y no cuentan en las stats
MARK_MIN, MARK_MAX = 0, 125  # la API contiene notas corruptas (p. ej. 1.149.710.997 o -42) que destrozan las medias


def _not_cheat():
    return or_(ProjectUser.final_mark.is_(None), ProjectUser.final_mark != CHEAT_MARK)


def _valid_mark():
    return and_(ProjectUser.final_mark >= MARK_MIN, ProjectUser.final_mark <= MARK_MAX)


def _done():
    """Intento terminado: estado finished, o ya con resultado (validated no nulo) aunque el estado sea otro."""
    return or_(ProjectUser.status == "finished", ProjectUser.validated.is_not(None))


def projects(s: Session, min_attempts: int = 20, limit: int | None = 60) -> list[dict]:
    """Proyectos del 42cursus con más intentos: validación, nota media y tiempo mediano."""
    done = _done()
    finished = case((done, 1), else_=0)
    validated = case((ProjectUser.validated.is_(True), 1), else_=0)
    in_progress = case((ProjectUser.status == "in_progress", 1), else_=0)
    mark = case((and_(done, _valid_mark()), ProjectUser.final_mark))
    rows = s.execute(
        select(
            Project.id, Project.name, Project.difficulty, func.count().label("attempts"),
            func.sum(finished), func.sum(validated), func.sum(in_progress), func.avg(mark), Project.cursus_names,
        )
        .join(Project, Project.id == ProjectUser.project_id)
        .where(_not_cheat())
        .group_by(Project.id, Project.name, Project.difficulty, Project.cursus_names)
        .having(func.count() >= min_attempts)
        .order_by(func.count().desc())
        .limit(limit)  # None = sin límite
    ).all()
    ids = [r[0] for r in rows]
    days: dict[int, list[float]] = defaultdict(list)
    if ids:
        for pid, created, marked in s.execute(
            select(ProjectUser.project_id, ProjectUser.created_at, ProjectUser.marked_at)
            .where(ProjectUser.project_id.in_(ids), _done(), _not_cheat(),
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
            "cursus": cursus,
        }
        for pid, name, diff, attempts, fin, val, prog, avg, cursus in rows
    ]


def _cursus_names(s: Session) -> dict[int, str]:
    """id de cursus -> nombre, a partir del catálogo de proyectos."""
    names: dict[int, str] = {}
    for ids, nm in s.execute(select(Project.cursus_ids, Project.cursus_names)
                             .where(Project.cursus_ids.is_not(None), Project.cursus_names.is_not(None))):
        parts = [x.strip() for x in nm.split(", ")]
        if len(ids) == len(parts):
            names.update(zip(ids, parts))
    return names


def projects_by_cursus(s: Session, min_attempts: int = 10, per_cursus: int = 25,
                       min_cursus_attempts: int = 100) -> list[dict]:
    """Un grupo por cursus con sus proyectos más intentados.

    El cursus es el del INTENTO (project_users.cursus_ids): el que cursaba el alumno de Madrid al hacerlo. No el
    cursus al que pertenece el proyecto en el catálogo, que incluye otros campus (C Piscine Brussels, etc.).
    """
    acc: dict[tuple[int, int], dict] = {}
    for pid, cids, status, validated, mark, created, marked in s.execute(
        select(ProjectUser.project_id, ProjectUser.cursus_ids, ProjectUser.status, ProjectUser.validated,
               ProjectUser.final_mark, ProjectUser.created_at, ProjectUser.marked_at).where(_not_cheat())
    ):
        done = status == "finished" or validated is not None
        days = None
        if done and marked is not None and created is not None:
            d = (_aware(marked) - _aware(created)).total_seconds() / 86400
            days = d if d >= 0 else None
        for cid in cids or []:
            a = acc.setdefault((cid, pid), {"attempts": 0, "finished": 0, "validated": 0, "in_progress": 0,
                                            "marks": [], "days": []})
            a["attempts"] += 1
            a["finished"] += done
            a["validated"] += validated is True
            a["in_progress"] += status == "in_progress"
            if done and mark is not None and MARK_MIN <= mark <= MARK_MAX:
                a["marks"].append(mark)
            if days is not None:
                a["days"].append(days)

    project_names = dict(s.execute(select(Project.id, Project.name)).all())
    cursus_names = _cursus_names(s)
    by_cursus: dict[int, list[dict]] = defaultdict(list)
    for (cid, pid), a in acc.items():
        if a["attempts"] < min_attempts or pid not in project_names:
            continue
        by_cursus[cid].append({
            "id": pid, "name": project_names[pid], "attempts": a["attempts"], "finished": a["finished"],
            "validated": a["validated"], "in_progress": a["in_progress"],
            "validation_rate": round(a["validated"] / a["finished"], 3) if a["finished"] else None,
            "avg_mark": round(sum(a["marks"]) / len(a["marks"]), 1) if a["marks"] else None,
            "median_days": round(statistics.median(a["days"]), 1) if a["days"] else None,
        })
    out = []
    for cid, rows in by_cursus.items():
        total = sum(r["attempts"] for r in rows)
        if total < min_cursus_attempts:
            continue
        rows.sort(key=lambda r: -r["attempts"])
        out.append({"names": [cursus_names.get(cid, f"Cursus {cid}")], "cursus_ids": [cid],
                    "projects_count": len(rows), "attempts": total, "rows": rows[:per_cursus]})
    return sorted(out, key=lambda g: -g["attempts"])


def projects_monthly(s: Session, months: int = 36) -> list[dict]:
    """Proyectos terminados por mes (por fecha de nota), separando validados y no validados."""
    m = _month(s, ProjectUser.marked_at)
    rows = s.execute(
        select(m, func.sum(case((ProjectUser.validated.is_(True), 1), else_=0)), func.count())
        .where(_done(), _not_cheat(), ProjectUser.marked_at.is_not(None))
        .group_by(m)
    ).all()
    data = {k: (int(v or 0), int(t)) for k, v, t in rows}
    if not data:
        return []
    first = min(data)
    return [{"month": k, "validated": data.get(k, (0, 0))[0],
             "failed": data.get(k, (0, 0))[1] - data.get(k, (0, 0))[0]}
            for k in _last_months(months) if k >= first]


def blackholes(s: Session, cursus_id: int = 21, now: datetime | None = None, weeks: int = 26) -> dict:
    """Blackholes de los próximos `weeks` semanas (alumnos con el cursus abierto), por semana. Solo agregados."""
    now = now or _now()
    monday = (now - timedelta(days=now.weekday())).date()
    buckets: Counter = Counter()
    history: Counter = Counter()
    later = stale = 0
    for m in _members(s, cursus_id, now):
        bh = m["blackholed_at"]
        if m["outcome"] in CLOSED and m["end_at"] is not None:
            history[m["end_at"].strftime("%Y-%m")] += 1          # por mes de CIERRE: la fecha de la API es orientativa
        if m["current"] and bh is not None and bh < now - timedelta(days=1):
            stale += 1  # cursus abierto con fecha de blackhole ya pasada: no se sabe si es un blackhole real
        if not m["current"] or bh is None or bh < now:
            continue
        idx = (bh.date() - monday).days // 7
        if idx < weeks:
            buckets[idx] += 1
        else:
            later += 1
    return {
        "weeks": [{"week": (monday + timedelta(weeks=i)).isoformat(), "count": buckets.get(i, 0)} for i in range(weeks)],
        "later": later,
        "upcoming": sum(buckets.values()) + later,
        # cursus cerrados sin graduarse (casi todos, por blackhole) por MES DE CIERRE (no por año de piscina), últimos 24 meses
        "history": [{"month": k, "count": history.get(k, 0)} for k in _last_months(24, now)],
        "history_total": sum(history.values()),
        "stale": stale,
    }


# ---------------------------------------------------------------- milestones (ritmo)

RANK_RE = re.compile(r"^Common Core Rank (\d+)$")
STALLED_BUCKETS = [(30, "<30 días"), (90, "30-90 días"), (180, "90-180 días"), (365, "180-365 días"),
                   (float("inf"), ">365 días")]


def milestones(s: Session, cursus_id: int = 21, now: datetime | None = None) -> dict:
    """Ritmo de progreso por milestone (Common Core Rank 00..05). Solo agregados.

    El deadline real de cada milestone no está en la API pública; esto mide el ritmo: en qué rank está cada
    alumno, cuánto tarda entre ranks y cuánto lleva sin validar uno nuevo.
    """
    now = now or _now()
    ranks = sorted((int(m[1]), qid, name) for qid, name in
                   s.execute(select(Quest.id, Quest.name).where(Quest.cursus_id == cursus_id))
                   if name and (m := RANK_RE.match(name)))
    labels = {n: f"Rank {n:02d}" for n, _, _ in ranks}
    empty = {"ranks": [labels[n] for n, _, _ in ranks], "students": 0, "by_rank": [], "stalled": [], "steps": []}
    if not ranks:
        return empty
    rank_of = {qid: n for n, qid, _ in ranks}

    members = _members(s, cursus_id, now)
    begin = dict(s.execute(select(CursusUser.user_id, CursusUser.begin_at).where(CursusUser.cursus_id == cursus_id)).all())
    done: dict[int, dict[int, datetime]] = defaultdict(dict)   # usuario -> rank -> primera fecha de validación
    for uid, qid, at in s.execute(
        select(QuestUser.user_id, QuestUser.quest_id, QuestUser.validated_at)
        .where(QuestUser.quest_id.in_(list(rank_of)), QuestUser.validated_at.is_not(None))
    ):
        n, at = rank_of[qid], _aware(at)
        if n not in done[uid] or at < done[uid][n]:   # la API duplica algunas filas: se queda la primera
            done[uid][n] = at

    # -- alumnos con el cursus abierto: rank actual y días desde el último milestone
    by_rank: Counter = Counter()
    stalled: Counter = Counter()
    current = [m for m in members if m["current"]]
    for m in current:
        d = done.get(m["user_id"], {})
        by_rank[max(d) if d else None] += 1
        last = max(d.values()) if d else _aware(begin.get(m["user_id"]))
        if last is not None:
            days = (now - last).total_seconds() / 86400
            stalled[next(lbl for lim, lbl in STALLED_BUCKETS if days < lim)] += 1

    # -- tiempo entre milestones, con todos los alumnos (no staff) que tienen ambos extremos
    member_ids = {m["user_id"] for m in members}
    steps = []
    firsts = [(done[m["user_id"]][ranks[0][0]] - _aware(begin[m["user_id"]])).total_seconds() / 86400
              for m in members if m["user_id"] in done and ranks[0][0] in done[m["user_id"]]
              and begin.get(m["user_id"]) is not None]
    firsts = [d for d in firsts if d >= 0]
    if firsts:
        steps.append({"label": f"Inicio → {labels[ranks[0][0]]}", "median_days": round(statistics.median(firsts), 1), "n": len(firsts)})
    for (a, _, _), (b, _, _) in zip(ranks, ranks[1:]):
        gaps = [(d[b] - d[a]).total_seconds() / 86400 for uid, d in done.items() if uid in member_ids and a in d and b in d]
        gaps = [g for g in gaps if g >= 0]
        if gaps:
            steps.append({"label": f"{labels[a]} → {labels[b]}", "median_days": round(statistics.median(gaps), 1), "n": len(gaps)})

    ordered = [None] + [n for n, _, _ in ranks]
    return {
        "ranks": [labels[n] for n, _, _ in ranks],
        "students": len(current),
        "by_rank": [{"label": labels[n] if n is not None else "Sin rank", "count": by_rank.get(n, 0)} for n in ordered],
        "stalled": [{"label": lbl, "count": stalled.get(lbl, 0)} for _, lbl in STALLED_BUCKETS],
        "steps": steps,
    }


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


# ---------------------------------------------------------------- panel personal

def _hours_by_user(s: Session, now: datetime, days: int) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for uid, b, e in s.execute(select(Location.user_id, Location.begin_at, Location.end_at)
                               .where(Location.begin_at >= now - timedelta(days=days))):
        b, e = _aware(b), _aware(e)
        if b is None:
            continue
        stop = min(e if e else min(now, b + MAX_SESSION), b + MAX_SESSION)
        if stop > b:
            out[uid] += (stop - b).total_seconds() / 3600
    return out


def _percentile(sorted_values: list[float], x: float) -> float | None:
    """Fracción de la muestra por debajo de x (los empates cuentan la mitad)."""
    if not sorted_values:
        return None
    below = sum(1 for v in sorted_values if v < x)
    equal = sum(1 for v in sorted_values if v == x)
    return (below + equal / 2) / len(sorted_values)


def cohort_context(s: Session, cursus_id: int = 21, now: datetime | None = None) -> dict:
    """Distribuciones del campus con las que se compara a cada alumno. Pesado: se calcula una vez y se cachea."""
    now = now or _now()
    members = _members(s, cursus_id, now)
    begin = {uid: _aware(b) for uid, b in s.execute(
        select(CursusUser.user_id, CursusUser.begin_at).where(CursusUser.cursus_id == cursus_id)).all()}
    current = [m for m in members if m["current"] and m["level"] is not None]
    hours = _hours_by_user(s, now, 30)
    pairs = [(m["level"] / ((now - begin[m["user_id"]]).days / 30.44), hours.get(m["user_id"], 0.0))
             for m in current if begin.get(m["user_id"]) and (now - begin[m["user_id"]]).days >= 91]
    paces = sorted(p for p, _ in pairs)
    open_ids = [m["user_id"] for m in members if m["current"]]
    levels = Counter(int(m["level"]) for m in current)
    ms = milestones(s, cursus_id, now)
    return {
        "paces": paces,
        "pace_hours": pairs,
        "hours": sorted(hours.get(u, 0.0) for u in open_ids),
        "hours_by_user": dict(hours),
        "level_hist": [{"level": n, "count": levels.get(n, 0)} for n in range(0, (max(levels) if levels else 0) + 1)],
        "steps": {x["label"]: x["median_days"] for x in ms["steps"]},
    }


HABIT_LABELS = ["25 % más lento", "Medio-lento", "Medio-rápido", "25 % más rápido"]


def habits_from_ctx(ctx: dict, min_students: int = 40) -> dict | None:
    """Horas de uso de cada cuartil de ritmo de progreso (nivel por mes). Solo agregados; correlación, no causa."""
    pairs = sorted(ctx.get("pace_hours") or [])
    n = len(pairs)
    if n < min_students:
        return None
    groups = [pairs[i * n // 4:(i + 1) * n // 4] for i in range(4)]
    return {
        "students": n,
        "quartiles": [{"label": HABIT_LABELS[i], "n": len(g), "median_hours_30d": round(statistics.median(h for _, h in g), 1),
                       "pace_max": round(g[-1][0], 2)} for i, g in enumerate(groups)],
        "bounds": [round(pairs[n // 4][0], 4), round(pairs[n // 2][0], 4), round(pairs[3 * n // 4][0], 4)],
    }


def project_context(s: Session, project_id: int, min_attempts: int = 10) -> dict | None:
    """Cómo les va a los alumnos con un proyecto: intentos terminados, porcentaje que valida, mediana de días y nota media."""
    rows = s.execute(select(ProjectUser.validated, ProjectUser.created_at, ProjectUser.marked_at, ProjectUser.final_mark)
                     .where(ProjectUser.project_id == project_id, _done(), _not_cheat())).all()
    if len(rows) < min_attempts:
        return None
    validated = [r for r in rows if r.validated is True]
    days = []
    for r in validated:
        if r.created_at and r.marked_at:
            d = (_aware(r.marked_at) - _aware(r.created_at)).total_seconds() / 86400
            if d >= 0:
                days.append(d)
    marks = [r.final_mark for r in validated if r.final_mark is not None and MARK_MIN <= r.final_mark <= MARK_MAX]
    return {"attempts": len(rows), "validation_rate": round(len(validated) / len(rows), 3),
            "median_days": round(statistics.median(days), 1) if days else None,
            "avg_mark": round(sum(marks) / len(marks), 1) if marks else None}


def _sig(key: str, label: str, state: str, value: str, detail: str) -> dict:
    return {"key": key, "label": label, "state": state, "value": value, "detail": detail}


def _my_habits(ctx: dict, my_pace: float | None, hours30: float) -> dict | None:
    h = habits_from_ctx(ctx)
    if h is None:
        return None
    mine = None
    if my_pace is not None:
        mine = {"quartile": sum(1 for b in h["bounds"] if my_pace >= b), "hours_30d": round(hours30, 1)}
    return {"students": h["students"], "quartiles": h["quartiles"], "mine": mine}


def me(s: Session, user_id: int, ctx: dict, cursus_id: int = 21, now: datetime | None = None,
       settings: dict | None = None) -> dict | None:
    """Análisis de UN alumno (solo se sirve a su propio usuario). Reglas transparentes, sin modelo."""
    now = now or _now()
    user = s.get(User, user_id)
    if user is None:
        return None
    cu = s.execute(select(CursusUser).where(CursusUser.user_id == user_id, CursusUser.cursus_id == cursus_id)).scalars().first()
    end = _aware(cu.end_at) if cu else None
    in_cursus = cu is not None and (end is None or end > now)
    begin = _aware(cu.begin_at) if cu else None
    signals: list[dict] = []
    tips: list[str] = []
    settings = settings or {}
    freeze_until = settings.get("freeze_until")      # dato indicado por el alumno, no viene de 42
    deadline = settings.get("deadline")
    frozen = in_cursus and freeze_until is not None and freeze_until >= now.date()

    # ---- actividad (sesiones de los últimos 84 días y última conexión)
    monday = (now - timedelta(days=now.weekday())).date()
    weeks = [monday - timedelta(weeks=i) for i in range(11, -1, -1)]
    weekly = {w: 0.0 for w in weeks}
    for b, e in s.execute(select(Location.begin_at, Location.end_at)
                          .where(Location.user_id == user_id, Location.begin_at >= now - timedelta(days=84))):
        b, e = _aware(b), _aware(e)
        stop = min(e if e else min(now, b + MAX_SESSION), b + MAX_SESSION)
        w = b.date() - timedelta(days=b.weekday())
        if w in weekly and stop > b:
            weekly[w] += (stop - b).total_seconds() / 3600
    last = _aware(s.scalar(select(func.max(Location.begin_at)).where(Location.user_id == user_id)))
    since_last = (now - last).days if last else None
    hours30 = ctx["hours_by_user"].get(user_id, 0.0)
    pct_h = _percentile(ctx["hours"], hours30) if in_cursus else None
    if frozen:
        a_state, a_detail = "ok", f"En freeze hasta {freeze_until.isoformat()}: no se evalúa la actividad."
    elif since_last is None or since_last > 21:
        a_state = "warn"
        a_detail = "No constan sesiones recientes en el campus." if since_last is None else f"Llevas {since_last} días sin conectarte."
        tips.append("Planifica una sesión corta esta semana: volver a un ritmo regular pesa más que esperar a un bloque largo.")
    elif pct_h is not None and pct_h >= 0.5 and since_last <= 7:
        a_state, a_detail = "good", "Estás por encima de la mediana de horas de tu cursus."
    else:
        a_state, a_detail = "ok", "Actividad en la media o por debajo de la mediana de tu cursus."
    signals.append(_sig("activity", "Actividad", a_state, f"{hours30:.0f} h en 30 días",
                        a_detail + (f" Última conexión hace {since_last} días." if since_last is not None and a_state != "warn" else "")))

    # ---- ritmo de nivel
    level = cu.level if cu else None
    my_pace = None
    if in_cursus and level is not None and begin:
        months = max((now - begin).days / 30.44, 0.1)
        my_pace = level / months
        pct = _percentile(ctx["paces"], my_pace) if months >= 3 else None
        if pct is None:
            signals.append(_sig("pace", "Ritmo de nivel", "ok", f"nivel {level:.2f}",
                                "Llevas poco tiempo en el cursus para compararte con fiabilidad."))
        else:
            state = "good" if pct >= 0.66 else "ok" if pct >= 0.33 else "warn"
            signals.append(_sig("pace", "Ritmo de nivel", state, f"nivel {level:.2f} en {months:.0f} meses",
                                f"Avanzas más rápido que el {round(pct * 100)} % de los alumnos con el cursus abierto."))
            if state == "warn":
                tips.append("Tu nivel sube más despacio que el de la mayoría. Elige el siguiente proyecto de tu milestone y reserva horas fijas cada semana.")

    # ---- milestones (Common Core Rank 00..05)
    ranks = sorted((int(m[1]), qid) for qid, name in
                   s.execute(select(Quest.id, Quest.name).where(Quest.cursus_id == cursus_id))
                   if name and (m := RANK_RE.match(name)))
    done: dict[int, datetime] = {}
    if ranks:
        rank_of = {qid: n for n, qid in ranks}
        for qid, at in s.execute(select(QuestUser.quest_id, QuestUser.validated_at)
                                 .where(QuestUser.user_id == user_id, QuestUser.quest_id.in_(list(rank_of)),
                                        QuestUser.validated_at.is_not(None))):
            n, at = rank_of[qid], _aware(at)
            if n not in done or at < done[n]:
                done[n] = at
    timeline, prev = [], begin
    for n, _ in ranks:
        if n in done:
            timeline.append({"label": f"Rank {n:02d}", "date": done[n].date().isoformat(),
                             "days_from_previous": round((done[n] - prev).total_seconds() / 86400) if prev else None})
            prev = done[n]
    next_ms = None
    if in_cursus and ranks:
        pending = [n for n, _ in ranks if n not in done]
        if not pending:
            signals.append(_sig("milestone", "Milestones", "good", "todos validados", "Has validado todos los Common Core Rank."))
        else:
            nxt = pending[0]
            anchor = max(done.values()) if done else begin
            days = (now - anchor).days if anchor else None
            prev_label = f"Rank {max(done):02d}" if done else None
            step = f"{prev_label} → Rank {nxt:02d}" if prev_label else f"Inicio → Rank {nxt:02d}"
            typical = ctx["steps"].get(step) if prev_label else ctx["steps"].get(f"Inicio → Rank {ranks[0][0]:02d}")
            if days is None:
                state = "ok"
            elif typical is None:
                state = "ok"
            else:
                state = "good" if days <= typical else "ok" if days <= typical * 1.5 else "warn"
            if frozen and state == "warn":
                state = "ok"                       # en freeze no se marca un milestone como atrasado
            next_ms = {"label": f"Rank {nxt:02d}", "days_since_last": days, "typical_days": typical}
            detail = (f"Llevas {days} días desde tu último hito; lo habitual hasta el siguiente son {typical:.0f}."
                      if days is not None and typical is not None else "No hay datos suficientes para comparar el siguiente hito.")
            signals.append(_sig("milestone", "Siguiente milestone", state, f"Rank {nxt:02d}", detail))
            if state == "warn":
                tips.append(f"Llevas {days} días sin validar un milestone y lo habitual son {typical:.0f}. Identifica qué proyecto te frena y pide ayuda a alguien que ya lo tenga.")

    # ---- deadline indicado por el alumno
    days_left = (deadline - now.date()).days if deadline is not None else None
    if in_cursus and days_left is not None:
        typical = next_ms["typical_days"] if next_ms else None
        if frozen:
            d_state, d_detail = "ok", "Estás en freeze: tu deadline queda en pausa."
        elif days_left < 0:
            d_state, d_detail = "warn", f"El deadline que indicaste pasó hace {-days_left} días. Actualízalo si cambió."
            tips.append("Tu deadline indicado ya pasó. Si 42 te lo movió, actualízalo aquí para que el análisis sea fiable.")
        elif typical is None:
            d_state, d_detail = "ok", f"Te quedan {days_left} días hasta tu deadline."
        elif days_left >= typical:
            d_state, d_detail = "good", f"Te quedan {days_left} días y lo habitual para el siguiente paso son {typical:.0f}."
        elif days_left >= typical * 0.5:
            d_state, d_detail = "ok", f"Te quedan {days_left} días; lo habitual para el siguiente paso son {typical:.0f}. Vas justo."
        else:
            d_state, d_detail = "warn", f"Te quedan {days_left} días y lo habitual para el siguiente paso son {typical:.0f}."
            tips.append(f"Te quedan {days_left} días hasta tu deadline y el siguiente milestone suele llevar {typical:.0f}. Prioriza ese proyecto esta semana.")
        signals.append(_sig("deadline", "Tu deadline", d_state, f"{days_left} días", d_detail + " (dato indicado por ti)"))

    # ---- evaluaciones y proyectos
    evals90 = s.scalar(select(func.count()).select_from(Evaluation).where(
        Evaluation.corrector_id == user_id, Evaluation.filled_at >= now - timedelta(days=90))) or 0
    points = user.correction_point
    if evals90 >= 3:
        e_state, e_detail = "good", "Evalúas con regularidad."
    elif evals90 >= 1:
        e_state, e_detail = "ok", "Has evaluado alguna vez en los últimos 90 días."
    elif points is not None and points <= 2:
        e_state, e_detail = "warn", "Casi no te quedan puntos de corrección y no has evaluado en 90 días."
        tips.append("Evalúa a otros alumnos para recuperar puntos de corrección; además se aprende mucho de los proyectos ajenos.")
    else:
        e_state, e_detail = "ok", "No has evaluado en los últimos 90 días."
    signals.append(_sig("evaluations", "Evaluaciones", e_state, f"{evals90} en 90 días",
                        e_detail + (f" Puntos de corrección: {points}." if points is not None else "")))

    ongoing = []
    for pid, name, created in s.execute(select(Project.id, Project.name, ProjectUser.created_at)
                                        .join(Project, Project.id == ProjectUser.project_id)
                                        .where(ProjectUser.user_id == user_id, ProjectUser.status == "in_progress")
                                        .order_by(ProjectUser.created_at)):
        c = _aware(created)
        ongoing.append({"id": pid, "name": name, "days": (now - c).days if c else None})
    for o in ongoing[:8]:
        o["context"] = project_context(s, o["id"])
    stuck = [o for o in ongoing if o["days"] is not None and o["days"] > 60]
    if stuck:
        ctx_p = stuck[0].get("context") or {}
        typical = f" Lo habitual para validarlo son {ctx_p['median_days']:.0f} días." if ctx_p.get("median_days") else ""
        tips.append(f"Tienes «{stuck[0]['name']}» en curso desde hace {stuck[0]['days']} días.{typical} Si estás bloqueado, divide el proyecto en partes pequeñas y avanza una por sesión, o pide ayuda en la sección Ayuda.")
    validated90 = s.scalar(select(func.count()).select_from(ProjectUser).where(
        ProjectUser.user_id == user_id, ProjectUser.validated.is_(True), ProjectUser.marked_at >= now - timedelta(days=90))) or 0

    # ---- veredicto
    warns = sum(1 for x in signals if x["state"] == "warn")
    goods = sum(1 for x in signals if x["state"] == "good")
    if not in_cursus:
        status = {"key": "none", "label": "Sin cursus abierto", "summary": "No tienes el 42cursus abierto: te mostramos tu actividad."}
    elif frozen:
        status = {"key": "frozen", "label": "En freeze", "summary": f"Indicaste un freeze hasta {freeze_until.isoformat()}: no marcamos alertas de actividad ni de milestones."}
    elif warns >= 2:
        status = {"key": "attention", "label": "Necesita atención", "summary": "Varias señales por debajo de la media de tu cursus. Mira los consejos."}
    elif warns == 1:
        status = {"key": "normal", "label": "Normal, con un punto a vigilar", "summary": "Vas en la media, con una señal que conviene mejorar."}
    elif goods >= 3:
        status = {"key": "great", "label": "Va muy bien", "summary": "Estás por encima de la media de tu cursus en casi todo."}
    else:
        status = {"key": "normal", "label": "Normal", "summary": "Estás en la media de tu cursus."}

    bh = _aware(cu.blackholed_at) if cu else None
    return {
        "login": user.login,
        "pool": " ".join(x for x in (user.pool_month, user.pool_year) if x),
        "in_cursus": in_cursus,
        "level": round(level, 2) if level is not None else None,
        "days_in_cursus": (now - begin).days if begin else None,
        "blackhole_api": bh.date().isoformat() if bh else None,   # orientativo: no es el deadline real
        "status": status,
        "signals": signals,
        "tips": tips,
        "milestones": timeline,
        "next_milestone": next_ms,
        "level_context": {"hist": ctx["level_hist"], "my_bucket": int(level) if level is not None else None,
                          "percentile": round(_percentile(ctx["paces"], my_pace), 3) if my_pace is not None and ctx["paces"] else None},
        "activity": {"hours_30d": round(hours30, 1), "last_session_days_ago": since_last,
                     "weekly": [{"week": w.isoformat(), "hours": round(h, 1)} for w, h in weekly.items()]},
        "projects": {"validated_90d": validated90, "in_progress": ongoing[:8]},
        "evaluations": {"done_90d": evals90, "correction_points": points},
        "habits": _my_habits(ctx, my_pace, hours30),
        "self_reported": {"deadline": deadline.isoformat() if deadline else None,
                          "freeze_until": freeze_until.isoformat() if freeze_until else None,
                          "frozen": bool(frozen), "days_to_deadline": days_left},
    }
