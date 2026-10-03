from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from stats42 import stats
from stats42.api import create_app
from stats42.db import CursusUser, Project, ProjectUser, SyncState, User, init_db

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def user(i, year="2025", kind="student", active=True, created="2025-05-10T10:00:00+00:00"):
    return User(id=i, login=f"u{i}", kind=kind, pool_year=year, pool_month="may", active=active,
                alumni=False, staff=False, created_at=datetime.fromisoformat(created))


def cu(i, uid, level, end_at=None, bh=None):
    return CursusUser(id=i, user_id=uid, cursus_id=21, level=level, end_at=end_at, blackholed_at=bh)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    factory = init_db(eng)
    with factory() as s:
        s.add_all([
            user(1, "2025"), user(2, "2025"), user(3, "2025"), user(4, "2024"),
            user(5, "2024", active=False), user(6, "2025", kind="staff"),
        ])
        s.add_all([
            cu(1, 1, 3.4, bh=NOW + timedelta(days=10)),        # actual, en riesgo
            cu(2, 2, 0.9, bh=NOW + timedelta(days=200)),       # actual
            cu(3, 4, 7.2, end_at=NOW - timedelta(days=5)),     # terminado
        ])
        s.add_all([Project(id=1, name="libft", slug="libft", difficulty=1, exam=False),
                   Project(id=2, name="rare", slug="rare", difficulty=1, exam=False)])
        pus = [ProjectUser(id=i, user_id=1, project_id=1, status="finished", final_mark=100 if i % 2 else 50,
                           validated=bool(i % 2)) for i in range(1, 21)]
        pus.append(ProjectUser(id=99, user_id=2, project_id=2, status="in_progress", final_mark=None, validated=None))
        s.add_all(pus)
        s.add(SyncState(resource="users", status="idle", last_run_at="2026-10-03T04:30:00Z"))
        s.commit()
    return eng


def test_overview(engine):
    with Session(engine) as s:
        o = stats.overview(s, 21, NOW)
    assert o["students"] == 5 and o["active"] == 4
    assert (o["cursus_members"], o["cursus_current"], o["cursus_ended"]) == (3, 2, 1)
    assert o["avg_level"] == 2.15 and o["at_risk"] == 1
    assert o["last_sync"] == "2026-10-03T04:30:00Z"


def test_levels_histogram_fills_gaps(engine):
    with Session(engine) as s:
        lv = stats.levels(s, 21, NOW)
    assert lv == [{"level": 0, "count": 1}, {"level": 1, "count": 0}, {"level": 2, "count": 0}, {"level": 3, "count": 1}]


def test_cohorts(engine):
    with Session(engine) as s:
        c = {x["year"]: x for x in stats.cohorts(s, 21, NOW)}
    assert c["2025"]["pool"] == 3 and c["2025"]["in_cursus"] == 2 and c["2025"]["current"] == 2
    assert c["2025"]["retention"] == 1.0
    assert c["2024"]["pool"] == 2 and c["2024"]["current"] == 0 and c["2024"]["retention"] == 0.0


def test_projects_respects_min_attempts_and_rates(engine):
    with Session(engine) as s:
        p = stats.projects(s, min_attempts=20)
    assert [x["name"] for x in p] == ["libft"]
    assert p[0]["finished"] == 20 and p[0]["validated"] == 10
    assert p[0]["validation_rate"] == 0.5 and p[0]["avg_mark"] == 75.0


def test_signups_has_no_gaps(engine):
    with Session(engine) as s:
        sg = stats.signups(s)
    assert sg and sg[0]["month"] == "2025-05" and sg[0]["count"] == 5
    months = [x["month"] for x in sg]
    assert months == sorted(months) and len(set(months)) == len(months)


def test_stats_have_no_personal_fields(engine):
    with Session(engine) as s:
        blob = str([stats.overview(s), stats.levels(s), stats.cohorts(s), stats.signups(s), stats.projects(s, 1)])
    assert "u1" not in blob and "login" not in blob


def test_api_endpoints_and_headers(engine):
    c = TestClient(create_app(engine, 21))
    assert c.get("/api/health").json() == {"status": "ok"}
    for path in ("overview", "levels", "cohorts", "signups", "projects"):
        r = c.get(f"/api/{path}")
        assert r.status_code == 200, path
    r = c.get("/api/overview")
    assert r.headers["cache-control"] == "public, max-age=300"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "cache-control" not in c.get("/api/health").headers or "max-age" not in c.get("/api/health").headers.get("cache-control", "")


def test_api_returns_503_when_tables_missing():
    empty = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    r = TestClient(create_app(empty, 21)).get("/api/overview")
    assert r.status_code == 503


def test_index_served():
    web = TestClient(create_app(create_engine("sqlite://"), 21))
    r = web.get("/")
    assert r.status_code == 200 and "42" in r.text
