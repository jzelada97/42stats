"""Cifras agregadas del POC (docs/POC.md): cuántos alumnos cierran el cursus sin graduarse, cuándo y con qué progreso.

Cuenta ALUMNOS (kind = student): las cuentas de staff (admin) y las externas se excluyen, y los alumni (graduados) se separan de los activos.
En 42 no existe la baja voluntaria: todo cursus cerrado sin graduarse es, en la práctica, un cierre por blackhole. Las etiquetas
blackholed / dropped / other solo describen la relación entre el cierre y la fecha de blackhole de la API, que es orientativa.
Solo imprime recuentos y medianas: nunca un alumno concreto. Usa las mismas reglas que la web (stats._members, stats.cohorts).

Se ejecuta contra la base de la VM sin tocarla (conexión de solo lectura):

    docker run --rm -i -v stats42_stats42_data:/data --entrypoint python stats42:latest - < scripts/poc_numbers.py

o en local, con la base en data/stats42.db:  FT_DATABASE_URL=sqlite:///data/stats42.db python scripts/poc_numbers.py
"""
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stats42 import stats
from stats42.db import CursusUser, ProjectUser, Quest, QuestUser, User, make_readonly_engine
from stats42.stats import CLOSED, RANK_RE

sys.stdout.reconfigure(encoding="utf-8")
DB = os.environ.get("FT_DATABASE_URL", "sqlite:////data/stats42.db")
CURSUS = 21
now = datetime.now(timezone.utc)
aware = lambda d: d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d  # noqa: E731
rank_label = lambda k: "ninguno" if k == -1 else f"Rank {k:02d}"  # noqa: E731
pct = lambda a, b: round(a / b, 3) if b else None  # noqa: E731


def quantiles(values):
    q = statistics.quantiles(values, n=10) if len(values) >= 10 else [min(values)] * 9 + [max(values)]
    return {"median": round(statistics.median(values), 1), "p10": round(q[0], 1), "p90": round(q[-1], 1)}


def main() -> dict:
    out = {"generated": now.isoformat(timespec="minutes")}
    with Session(make_readonly_engine(DB)) as s:
        kind = dict(s.execute(select(User.id, User.kind)).all())
        with_record = [uid for (uid,) in s.execute(select(CursusUser.user_id).where(CursusUser.cursus_id == CURSUS))]
        members = stats._members(s, CURSUS, now)                      # solo alumnos; los alumni quedan como «graduated»
        out["accounts"] = {"users_in_db": len(kind), "students_in_db": sum(k == "student" for k in kind.values()),
                           "with_42cursus_record": len(with_record), "counted_students": len(members),
                           "excluded_non_students": dict(Counter(kind.get(u) for u in with_record if kind.get(u) != "student"))}
        by = Counter(m["outcome"] for m in members)
        closed = [m for m in members if m["outcome"] in CLOSED]
        out["members"] = {"total": len(members), "active": by["current"], "graduated": by["graduated"], "closed_without_graduating": len(closed),
                          "closed_by_relation_to_api_date": {k: by[k] for k in CLOSED}}
        # Graduados: el campo alumni de la API (alumni?) frente a quien solo tiene los seis ranks. Todo sobre alumnos (kind = student).
        students = {u for u in with_record if kind.get(u) == "student"}
        alumni = {u for (u,) in s.execute(select(User.id).where(User.kind == "student", User.alumni.is_(True)))}
        rank_of = {qid: int(m[1]) for qid, name in s.execute(select(Quest.id, Quest.name).where(Quest.cursus_id == CURSUS)) if name and (m := RANK_RE.match(name))}
        last = [qid for qid, n in rank_of.items() if n == max(rank_of.values())]
        six = {u for (u,) in s.execute(select(QuestUser.user_id).where(QuestUser.quest_id.in_(last), QuestUser.validated_at.is_not(None)))} & students
        out["graduates"] = {"alumni_flag_in_db": len(alumni), "alumni_in_42cursus": len(alumni & students), "alumni_outside_42cursus": len(alumni - students),
                            "six_ranks_in_42cursus": len(six), "six_ranks_not_alumni": len(six - alumni), "alumni_without_six_ranks": len((alumni & students) - six),
                            "students_without_42cursus_record": out["accounts"]["students_in_db"] - len(students)}
        out["cohorts"] = stats.cohorts(s, CURSUS)
        out["closures_by_month_24m"] = [(h["month"], h["count"]) for h in stats.blackholes(s, CURSUS).get("history", [])]
        cur_members = [m for m in members if m["outcome"] == "current"]
        past = [(now - m["blackholed_at"]).days for m in cur_members if m["blackholed_at"] and m["blackholed_at"] < now]
        out["active_with_past_api_date"] = {"n": len(past), "median_days_past": statistics.median(past) if past else None}
        out["active_with_api_blackhole_within_30d"] = sum(1 for m in cur_members if m["blackholed_at"] and now <= m["blackholed_at"] < now.replace(year=now.year + 5) and (m["blackholed_at"] - now).days < 30)

        ranks = {qid: int(RANK_RE.match(name)[1]) for qid, name in s.execute(select(Quest.id, Quest.name).where(Quest.cursus_id == CURSUS))
                 if name and RANK_RE.match(name)}
        top_rank = max(ranks.values())
        got, last = defaultdict(set), {}
        for uid, qid, at in s.execute(select(QuestUser.user_id, QuestUser.quest_id, QuestUser.validated_at)
                                      .where(QuestUser.quest_id.in_(list(ranks)), QuestUser.validated_at.is_not(None))):
            got[uid].add(ranks[qid])
            at = aware(at)
            if uid not in last or at > last[uid]:
                last[uid] = at
        begin = {u: aware(b) for u, b in s.execute(select(CursusUser.user_id, CursusUser.begin_at).where(CursusUser.cursus_id == CURSUS))}
        best = lambda uid: max(got[uid]) if got[uid] else -1  # noqa: E731

        def profile(group):
            days = [(m["end_at"] - begin[m["user_id"]]).total_seconds() / 86400 for m in group if begin.get(m["user_id"]) and m["end_at"]]
            lv = [m["level"] for m in group if m["level"] is not None]
            top = Counter(best(m["user_id"]) for m in group)
            lag = [(m["end_at"] - m["blackholed_at"]).total_seconds() / 86400 for m in group if m["end_at"] and m["blackholed_at"]]
            return {
                "n": len(group), "median_days_in_cursus": round(statistics.median(days)) if days else None,
                "median_level_at_close": round(statistics.median(lv), 1) if lv else None,
                "share_level_below_3": pct(sum(x < 3 for x in lv), len(lv)), "share_level_below_5": pct(sum(x < 5 for x in lv), len(lv)),
                "share_no_rank": pct(top[-1], len(group)), "share_up_to_rank01": pct(sum(v for k, v in top.items() if k <= 1), len(group)),
                "max_rank_validated": {rank_label(k): v for k, v in sorted(top.items())},
                "days_from_api_date_to_close": quantiles(lag) if lag else None,
            }
        out["closed_profile"] = {"all": profile(closed), **{k: profile([m for m in members if m["outcome"] == k]) for k in CLOSED}}

        # alumnos activos: cuántos tienen aún ranks por validar y cuánto llevan sin validar uno
        cur = [m["user_id"] for m in cur_members]
        pending = [u for u in cur if top_rank not in got[u]]
        buckets = Counter()
        for u in pending:
            ref = last.get(u) or begin.get(u)
            d = (now - ref).days if ref else None
            buckets["sin dato" if d is None else "<30" if d < 30 else "30-90" if d < 90 else "90-180" if d < 180 else "180-365" if d < 365 else ">365"] += 1
        out["active"] = {
            "total": len(cur), "all_ranks_done": len(cur) - len(pending), "with_pending_ranks": len(pending),
            "pending_days_since_last_rank": dict(buckets),
            "pending_over_90d": sum(v for k, v in buckets.items() if k in ("90-180", "180-365", ">365")),
            "pending_over_180d": sum(v for k, v in buckets.items() if k in ("180-365", ">365")),
            "median_level": round(statistics.median([m["level"] for m in cur_members if m["level"] is not None]), 1),
            "none_validated": sum(1 for u in cur if not got[u]),
        }
        out["median_days_between_milestones"] = [(x["label"], x["median_days"], x["n"]) for x in stats.milestones(s, CURSUS).get("steps", [])]
        out["project_attempts_in_db"] = s.scalar(select(func.count()).select_from(ProjectUser))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=1, default=str))
