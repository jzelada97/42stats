"""Cifras agregadas del POC (docs/POC.md): cuántos alumnos terminan blackholeados o de baja, cuándo y con qué progreso.

Solo imprime recuentos y medianas: nunca un alumno concreto. Usa las mismas reglas que la web (stats._members, stats.cohorts).

Se ejecuta contra la base de la VM sin tocarla (conexión de solo lectura):

    docker run --rm -i -v stats42_stats42_data:/data --entrypoint python stats42:latest - < scripts/poc_numbers.py

o en local, con la base en data/stats42.db:  python scripts/poc_numbers.py  (cambia DB más abajo o usa FT_DATABASE_URL).
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
        members = stats._members(s, CURSUS, now)
        out["students_in_db"] = s.scalar(select(func.count()).select_from(User).where(User.kind == "student"))
        out["members"] = {"total": len(members), **dict(Counter(m["outcome"] for m in members))}
        out["cohorts"] = stats.cohorts(s, CURSUS)
        bh = stats.blackholes(s, CURSUS)
        out["bh_history_24m"] = [(h["month"], h["count"]) for h in bh.get("history", [])[-24:]]
        out["bh_open_with_past_api_date"] = bh.get("stale")
        ov = stats.overview(s, CURSUS)
        out["open_with_api_blackhole_within_30d"] = ov.get("at_risk")

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

        # quién se va y con qué progreso
        for kind in ("blackholed", "dropped"):
            grp = [m for m in members if m["outcome"] == kind]
            days = [(m["end_at"] - begin[m["user_id"]]).total_seconds() / 86400 for m in grp if begin.get(m["user_id"]) and m["end_at"]]
            lv = [m["level"] for m in grp if m["level"] is not None]
            top = Counter(best(m["user_id"]) for m in grp)
            out[kind] = {
                "n": len(grp), "median_days_in_cursus": round(statistics.median(days)) if days else None,
                "median_level_at_close": round(statistics.median(lv), 1) if lv else None,
                "share_level_below_3": round(sum(x < 3 for x in lv) / len(lv), 3) if lv else None,
                "share_level_below_5": round(sum(x < 5 for x in lv) / len(lv), 3) if lv else None,
                "share_no_rank": round(top[-1] / len(grp), 3) if grp else None,
                "share_up_to_rank01": round(sum(v for k, v in top.items() if k <= 1) / len(grp), 3) if grp else None,
                "max_rank_validated": {rank_label(k): v for k, v in sorted(top.items())},
            }

        # alumnos con el cursus abierto: cuántos tienen aún ranks por validar y cuánto llevan sin validar uno
        cur = [m["user_id"] for m in members if m["outcome"] == "current"]
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
            "median_level": round(statistics.median([m["level"] for m in members if m["outcome"] == "current" and m["level"] is not None]), 1),
        }
        out["median_days_between_milestones"] = [(x["label"], x["median_days"], x["n"]) for x in stats.milestones(s, CURSUS).get("steps", [])]
        out["project_attempts_in_db"] = s.scalar(select(func.count()).select_from(ProjectUser))
    return out


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=1, default=str))
