"""Cifras agregadas del POC (docs/POC.md): cuántos alumnos terminan blackholeados o de baja, cuándo y con qué progreso.

Solo cuenta ALUMNOS (kind = student): las cuentas de staff (admin) y las externas que tienen un registro en el 42cursus se excluyen.
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
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stats42 import stats
from stats42.db import CursusUser, ProjectUser, Quest, QuestUser, User, make_readonly_engine
from stats42.stats import RANK_RE

sys.stdout.reconfigure(encoding="utf-8")
DB = os.environ.get("FT_DATABASE_URL", "sqlite:////data/stats42.db")
CURSUS = 21
now = datetime.now(timezone.utc)
aware = lambda d: d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d  # noqa: E731
rank_label = lambda k: "ninguno" if k == -1 else f"Rank {k:02d}"  # noqa: E731


def main() -> dict:
    out = {"generated": now.isoformat(timespec="minutes")}
    with Session(make_readonly_engine(DB)) as s:
        kind = dict(s.execute(select(User.id, User.kind)).all())
        all_members = stats._members(s, CURSUS, now)
        members = [m for m in all_members if kind.get(m["user_id"]) == "student"]
        out["accounts"] = {"users_in_db": len(kind), "students_in_db": sum(k == "student" for k in kind.values()),
                           "with_42cursus_record": len(all_members), "with_42cursus_record_students": len(members),
                           "excluded_non_students": Counter(kind.get(m["user_id"]) for m in all_members if kind.get(m["user_id"]) != "student")}
        out["members"] = {"total": len(members), **dict(Counter(m["outcome"] for m in members))}
        out["cohorts"] = stats.cohorts(s, CURSUS)                      # ya cuenta solo alumnos con año de piscina

        # fechas de blackhole de la API (orientativas), solo alumnos
        monthly = Counter(m["blackholed_at"].strftime("%Y-%m") for m in members if m["outcome"] == "blackholed" and m["blackholed_at"])
        months = sorted(monthly)[-24:]
        last24 = [(now - timedelta(days=30 * i)).strftime("%Y-%m") for i in range(23, -1, -1)]
        out["bh_history_24m"] = [(mo, monthly.get(mo, 0)) for mo in sorted(set(last24))]
        cur_members = [m for m in members if m["outcome"] == "current"]
        out["open_with_past_api_date"] = sum(1 for m in cur_members if m["blackholed_at"] and m["blackholed_at"] < now)
        out["open_with_api_blackhole_within_30d"] = sum(1 for m in cur_members if m["blackholed_at"] and now <= m["blackholed_at"] < now + timedelta(days=30))

        ranks = {qid: int(RANK_RE.match(name)[1]) for qid, name in s.execute(select(Quest.id, Quest.name).where(Quest.cursus_id == CURSUS))
                 if name and RANK_RE.match(name)}
        top_rank = max(ranks.values())
        got, when = defaultdict(set), defaultdict(dict)
        for uid, qid, at in s.execute(select(QuestUser.user_id, QuestUser.quest_id, QuestUser.validated_at)
                                      .where(QuestUser.quest_id.in_(list(ranks)), QuestUser.validated_at.is_not(None))):
            r, at = ranks[qid], aware(at)
            got[uid].add(r)
            if r not in when[uid] or at < when[uid][r]:
                when[uid][r] = at
        begin = {u: aware(b) for u, b in s.execute(select(CursusUser.user_id, CursusUser.begin_at).where(CursusUser.cursus_id == CURSUS))}
        best = lambda uid: max(got[uid]) if got[uid] else -1  # noqa: E731
        last = {u: max(w.values()) for u, w in when.items()}

        # quién se va y con qué progreso
        for outcome in ("blackholed", "dropped"):
            grp = [m for m in members if m["outcome"] == outcome]
            days = [(m["end_at"] - begin[m["user_id"]]).total_seconds() / 86400 for m in grp if begin.get(m["user_id"]) and m["end_at"]]
            lv = [m["level"] for m in grp if m["level"] is not None]
            top = Counter(best(m["user_id"]) for m in grp)
            out[outcome] = {
                "n": len(grp), "median_days_in_cursus": round(statistics.median(days)) if days else None,
                "median_level_at_close": round(statistics.median(lv), 1) if lv else None,
                "share_level_below_3": round(sum(x < 3 for x in lv) / len(lv), 3) if lv else None,
                "share_level_below_5": round(sum(x < 5 for x in lv) / len(lv), 3) if lv else None,
                "share_no_rank": round(top[-1] / len(grp), 3) if grp else None,
                "share_up_to_rank01": round(sum(v for k, v in top.items() if k <= 1) / len(grp), 3) if grp else None,
                "max_rank_validated": {rank_label(k): v for k, v in sorted(top.items())},
            }

        # alumnos con el cursus abierto: cuántos tienen aún ranks por validar y cuánto llevan sin validar uno
        cur = [m["user_id"] for m in cur_members]
        pending = [u for u in cur if top_rank not in got[u]]
        buckets = Counter()
        for u in pending:
            ref = last.get(u) or begin.get(u)
            d = (now - ref).days if ref else None
            buckets["sin dato" if d is None else "<30" if d < 30 else "30-90" if d < 90 else "90-180" if d < 180 else "180-365" if d < 365 else ">365"] += 1
        out["open"] = {
            "total": len(cur), "all_ranks_done": len(cur) - len(pending), "with_pending_ranks": len(pending),
            "pending_days_since_last_rank": dict(buckets),
            "pending_over_90d": sum(v for k, v in buckets.items() if k in ("90-180", "180-365", ">365")),
            "pending_over_180d": sum(v for k, v in buckets.items() if k in ("180-365", ">365")),
            "median_level": round(statistics.median([m["level"] for m in cur_members if m["level"] is not None]), 1),
            "none_validated": sum(1 for u in cur if not got[u]),
        }

        # mediana de días entre milestones, solo alumnos que validaron ambos
        students = {m["user_id"] for m in members}
        steps = []
        first = [(when[u][0] - begin[u]).total_seconds() / 86400 for u in students if 0 in when[u] and begin.get(u)]
        first = [d for d in first if d >= 0]
        steps.append(("Inicio → Rank 00", round(statistics.median(first), 1), len(first)))
        for a, b in zip(range(top_rank), range(1, top_rank + 1)):
            gaps = [(when[u][b] - when[u][a]).total_seconds() / 86400 for u in students if a in when[u] and b in when[u]]
            gaps = [g for g in gaps if g >= 0]
            if gaps:
                steps.append((f"Rank {a:02d} → Rank {b:02d}", round(statistics.median(gaps), 1), len(gaps)))
        out["median_days_between_milestones"] = steps
        out["project_attempts_in_db"] = s.scalar(select(func.count()).select_from(ProjectUser))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=1, default=str))
