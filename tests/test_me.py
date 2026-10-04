from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from stats42 import stats
from stats42.db import (CursusUser, Evaluation, Location, Project, ProjectUser, Quest, QuestUser, User, init_db)

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
UTC = timezone.utc
BEGIN = NOW - timedelta(days=300)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    factory = init_db(eng)
    with factory() as s:
        s.add_all([Quest(id=44, name="Common Core Rank 00", cursus_id=21), Quest(id=45, name="Common Core Rank 01", cursus_id=21),
                   Project(id=1, name="libft", slug="libft")])
        for i in range(1, 13):   # promoción de 12 alumnos, niveles 1.0 .. 6.5 (el 12 es el mejor y el 1 el peor)
            s.add(User(id=i, login=f"u{i}", kind="student", pool_year="2025", pool_month="may", active=True, alumni=False,
                       staff=False, correction_point=0 if i == 1 else 5))
            s.add(CursusUser(id=i, user_id=i, cursus_id=21, level=1.0 + 0.5 * (i - 1), begin_at=BEGIN,
                             blackholed_at=NOW + timedelta(days=90)))
            if i != 1:   # todos menos el 1 validaron el Rank 00 a los 30 días: la mediana "Inicio → Rank 00" será 30
                s.add(QuestUser(id=100 + i, user_id=i, quest_id=44, validated_at=BEGIN + timedelta(days=30)))
                s.add(Location(id=i, user_id=i, host="c1r1s1", begin_at=NOW - timedelta(days=3), end_at=NOW - timedelta(days=3) + timedelta(hours=1)))
        # el 12 es muy activo, valida el Rank 01 a los 100 días y evalúa a menudo
        s.add(QuestUser(id=200, user_id=12, quest_id=45, validated_at=BEGIN + timedelta(days=100)))
        s.add_all([Location(id=500 + k, user_id=12, host="c1r1s1", begin_at=NOW - timedelta(days=k), end_at=NOW - timedelta(days=k) + timedelta(hours=4))
                   for k in range(1, 8)])
        s.add_all([Evaluation(id=k, corrector_id=12, project_id=1, final_mark=100, filled_at=NOW - timedelta(days=10 * k)) for k in range(1, 5)])
        s.add(ProjectUser(id=1, user_id=1, project_id=1, status="in_progress", created_at=NOW - timedelta(days=100)))
        s.add(ProjectUser(id=2, user_id=12, project_id=1, status="finished", validated=True, marked_at=NOW - timedelta(days=20),
                          created_at=NOW - timedelta(days=40)))
        s.add(User(id=99, login="piscinero", kind="student", pool_year="2026", pool_month="april", active=True, alumni=False, staff=False))
        s.commit()
    return eng


def analyse(engine, uid):
    with Session(engine) as s:
        ctx = stats.cohort_context(s, 21, NOW)
        return stats.me(s, uid, ctx, 21, NOW)


def test_percentile_counts_ties_as_half():
    assert stats._percentile([1, 2, 3], 2) == 0.5
    assert stats._percentile([1, 2, 3], 10) == 1.0 and stats._percentile([], 1) is None


def test_best_student_goes_great_with_all_signals_good(engine):
    a = analyse(engine, 12)
    assert a["status"]["key"] == "great"
    assert {x["key"]: x["state"] for x in a["signals"]} == {"activity": "good", "pace": "good", "milestone": "good", "evaluations": "good"}
    assert a["next_milestone"] is None                       # solo hay 2 ranks y los tiene
    assert [m["label"] for m in a["milestones"]] == ["Rank 00", "Rank 01"] and a["milestones"][1]["days_from_previous"] == 70
    assert a["activity"]["hours_30d"] >= 28 and a["projects"]["validated_90d"] == 1
    assert len(a["activity"]["weekly"]) == 12 and a["tips"] == []


def test_worst_student_needs_attention_and_gets_actionable_tips(engine):
    a = analyse(engine, 1)
    assert a["status"]["key"] == "attention"
    assert {x["key"]: x["state"] for x in a["signals"]} == {"activity": "warn", "pace": "warn", "milestone": "warn", "evaluations": "warn"}
    assert a["next_milestone"] == {"label": "Rank 00", "days_since_last": 300, "typical_days": 30.0}
    assert len(a["tips"]) >= 4 and any("100 días" in t for t in a["tips"])    # el proyecto en curso lleva 100 días
    assert a["projects"]["in_progress"] == [{"name": "libft", "days": 100}]
    assert a["level_context"]["percentile"] < 0.1


def test_middle_student_is_normal_with_one_point_to_watch(engine):
    a = analyse(engine, 6)
    states = {x["key"]: x["state"] for x in a["signals"]}
    # nivel y actividad en la media; lleva 270 días desde el Rank 00 y lo habitual hasta el Rank 01 son 70
    assert states == {"activity": "good", "pace": "ok", "milestone": "warn", "evaluations": "ok"}
    assert a["status"]["key"] == "normal" and "vigilar" in a["status"]["label"]
    assert a["next_milestone"]["label"] == "Rank 01" and a["next_milestone"]["days_since_last"] == 270


def test_student_without_open_cursus_gets_activity_only_status(engine):
    a = analyse(engine, 99)
    assert a["in_cursus"] is False and a["status"]["key"] == "none" and a["level"] is None


def test_unknown_user_returns_none(engine):
    assert analyse(engine, 12345) is None


def test_analysis_contains_only_the_users_own_identity(engine):
    blob = str(analyse(engine, 12))
    assert "u12" in blob and "u11" not in blob and "u1'" not in blob


# ---------------------------------------------------------------- freeze y deadline indicados por el alumno

def analyse_with(engine, uid, settings):
    with Session(engine) as s:
        ctx = stats.cohort_context(s, 21, NOW)
        return stats.me(s, uid, ctx, 21, NOW, settings=settings)


def day(n):
    return NOW.date() + timedelta(days=n)


def test_active_freeze_pauses_activity_and_milestone_alerts(engine):
    a = analyse_with(engine, 1, {"freeze_until": day(10)})
    assert a["status"]["key"] == "frozen" and "freeze" in a["status"]["label"].lower()
    states = {x["key"]: x["state"] for x in a["signals"]}
    assert states["activity"] == "ok" and states["milestone"] != "warn"
    assert not any("sesión corta" in t or "sin validar un milestone" in t for t in a["tips"])
    assert a["self_reported"]["frozen"] is True and a["self_reported"]["freeze_until"] == day(10).isoformat()


def test_expired_freeze_has_no_effect(engine):
    a = analyse_with(engine, 1, {"freeze_until": day(-1)})
    assert a["status"]["key"] == "attention" and a["self_reported"]["frozen"] is False


@pytest.mark.parametrize("offset,state", [(20, "warn"), (60, "ok"), (100, "good"), (-5, "warn")])
def test_deadline_signal_compares_days_left_with_the_usual_time_for_the_next_step(engine, offset, state):
    a = analyse_with(engine, 6, {"deadline": day(offset)})     # el alumno 6 va hacia el Rank 01: lo habitual son 70 días
    sig = next(x for x in a["signals"] if x["key"] == "deadline")
    assert sig["state"] == state and sig["value"] == f"{offset} días" and "indicado por ti" in sig["detail"]
    assert a["self_reported"]["days_to_deadline"] == offset
    assert (len(a["tips"]) > len(analyse_with(engine, 6, {})["tips"])) == (state == "warn")


def test_no_settings_means_no_deadline_signal_and_nothing_reported(engine):
    a = analyse_with(engine, 6, None)
    assert not any(x["key"] == "deadline" for x in a["signals"])
    assert a["self_reported"] == {"deadline": None, "freeze_until": None, "frozen": False, "days_to_deadline": None}


def test_deadline_during_freeze_is_paused_not_alarming(engine):
    a = analyse_with(engine, 6, {"deadline": day(5), "freeze_until": day(30)})
    assert next(x for x in a["signals"] if x["key"] == "deadline")["state"] == "ok"
