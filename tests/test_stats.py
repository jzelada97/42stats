from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from stats42 import stats
from stats42.api import create_app
from stats42.db import (CursusUser, Evaluation, Event, Exam, Location, Project, ProjectUser, SyncState,
                        User, init_db)

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)  # sábado
UTC = timezone.utc


def dt(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


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
                           validated=bool(i % 2), created_at=dt("2026-08-01T10:00:00"),
                           marked_at=dt("2026-08-05T10:00:00") if i % 2 else dt("2026-09-10T10:00:00"))
               for i in range(1, 21)]
        pus.append(ProjectUser(id=99, user_id=2, project_id=2, status="in_progress", final_mark=None, validated=None))
        s.add_all(pus)
        s.add(SyncState(resource="users", status="idle", last_run_at="2026-10-03T04:30:00Z"))

        # Lunes 2026-09-28 (hora de Madrid = UTC+2): 10:00-12:30 y 13:00-14:00; y una sesión abierta sin cierre.
        s.add_all([
            Location(id=1, user_id=1, host="c3r5s1", begin_at=dt("2026-09-28T08:00:00"), end_at=dt("2026-09-28T10:30:00")),
            Location(id=2, user_id=2, host="c1r1s1", begin_at=dt("2026-09-28T11:00:00"), end_at=dt("2026-09-28T12:00:00")),
            Location(id=3, user_id=2, host="raro", begin_at=dt("2026-09-30T08:00:00"), end_at=None),
            Location(id=4, user_id=9, host="c2r2s2", begin_at=dt("2025-01-01T08:00:00"), end_at=dt("2025-01-01T09:00:00")),
        ])
        s.add_all([
            Evaluation(id=1, corrector_id=1, project_id=1, final_mark=100, flag_name="Ok", flag_positive=True,
                       truant=False, filled_at=dt("2026-08-10T10:00:00")),
            Evaluation(id=2, corrector_id=2, project_id=1, final_mark=0, flag_name="Incomplete work",
                       flag_positive=False, truant=False, filled_at=dt("2026-09-10T10:00:00")),
            Evaluation(id=3, corrector_id=1, project_id=2, final_mark=125, flag_name="Ok", flag_positive=True,
                       truant=True, filled_at=dt("2026-09-12T10:00:00")),
            Evaluation(id=4, corrector_id=2, project_id=2, final_mark=None, flag_name="Ok", flag_positive=True,
                       truant=False, filled_at=None, begin_at=NOW + timedelta(days=1)),
        ])
        s.add_all([
            Event(id=1, name="Charla", kind="event", nbr_subscribers=10, max_people=0, begin_at=dt("2026-09-05T15:00:00")),
            Event(id=2, name="Hackathon", kind="conference", nbr_subscribers=50, max_people=100,
                  begin_at=dt("2026-10-10T09:00:00"), location="Cluster 1"),
            Exam(id=1, name="Exam Rank 02", nbr_subscribers=12, max_people=90, begin_at=dt("2026-10-29T09:00:00")),
        ])
        s.commit()
    return eng


def run(engine, fn, *args, **kw):
    with Session(engine) as s:
        return fn(s, *args, **kw)


def test_overview(engine):
    o = run(engine, stats.overview, 21, NOW)
    assert o["students"] == 5 and o["active"] == 4
    assert (o["cursus_members"], o["cursus_current"], o["cursus_ended"]) == (3, 2, 1)
    assert o["avg_level"] == 2.15 and o["at_risk"] == 1
    assert (o["sessions"], o["evaluations"], o["events"], o["exams"]) == (4, 4, 2, 1)
    assert o["last_sync"] == "2026-10-03T04:30:00Z"


def test_levels_histogram_fills_gaps(engine):
    assert run(engine, stats.levels, 21, NOW) == [
        {"level": 0, "count": 1}, {"level": 1, "count": 0}, {"level": 2, "count": 0}, {"level": 3, "count": 1}]


def test_cohorts(engine):
    c = {x["year"]: x for x in run(engine, stats.cohorts, 21, NOW)}
    assert c["2025"]["pool"] == 3 and c["2025"]["in_cursus"] == 2 and c["2025"]["retention"] == 1.0
    assert c["2024"]["pool"] == 2 and c["2024"]["current"] == 0 and c["2024"]["retention"] == 0.0


def test_projects_rates_and_median_days(engine):
    p = run(engine, stats.projects, min_attempts=20)
    assert [x["name"] for x in p] == ["libft"]
    assert (p[0]["finished"], p[0]["validated"], p[0]["validation_rate"], p[0]["avg_mark"]) == (20, 10, 0.5, 75.0)
    assert p[0]["median_days"] == 22.0  # 10 intentos de 4 días y 10 de 40
    assert run(engine, stats.projects, min_attempts=1)[1]["in_progress"] == 1


def test_validation_rate_never_exceeds_100_percent(engine):
    with Session(engine) as s:  # validado pero con otro estado (p. ej. a la espera de corrección)
        s.add(ProjectUser(id=500, user_id=3, project_id=1, status="waiting_for_correction", final_mark=100, validated=True,
                          created_at=dt("2026-08-01T10:00:00"), marked_at=dt("2026-08-02T10:00:00")))
        s.commit()
    p = run(engine, stats.projects, min_attempts=20)[0]
    assert p["validated"] == 11 and p["finished"] == 21 and p["validation_rate"] <= 1


def test_overview_reports_resources_still_loading(engine):
    o = run(engine, stats.overview, 21, NOW)
    assert "locations" in o["loading"] and "users" in o["loading"]  # la fixture no tiene marcas de agua
    with Session(engine) as s:
        s.merge(SyncState(resource="locations", status="idle", watermark="2026-10-03T00:00:00Z"))
        s.commit()
    assert "locations" not in run(engine, stats.overview, 21, NOW)["loading"]


def test_projects_monthly_splits_validated_and_failed(engine):
    m = {x["month"]: x for x in run(engine, stats.projects_monthly)}
    assert (m["2026-08"]["validated"], m["2026-08"]["failed"]) == (10, 0)
    assert (m["2026-09"]["validated"], m["2026-09"]["failed"]) == (0, 10)


def test_signups_has_no_gaps(engine):
    sg = run(engine, stats.signups)
    assert sg and sg[0]["month"] == "2025-05" and sg[0]["count"] == 5
    months = [x["month"] for x in sg]
    assert months == sorted(months) and len(set(months)) == len(months)


def test_attendance_heatmap_uses_madrid_time_and_window(engine):
    a = run(engine, stats.attendance, 90, NOW)
    assert a["sessions"] == 3 and a["unique_users"] == 2          # la de 2025 queda fuera de la ventana
    cell = next(c for c in a["heatmap"] if c["weekday"] == 0 and c["hour"] == 10)   # lunes 10:00 Madrid
    assert cell["value"] == round(1 / 13, 1)                       # 13 lunes en la ventana
    assert next(c for c in a["heatmap"] if c["weekday"] == 0 and c["hour"] == 8)["value"] == 0
    d = next(x for x in a["daily"] if x["date"] == "2026-09-28")
    assert d["hours"] == 3.5 and d["users"] == 2
    assert len(a["daily"]) == 90


def test_attendance_durations_cap_open_sessions_and_parse_hosts(engine):
    a = run(engine, stats.attendance, 90, NOW)
    dur = {x["label"]: x["count"] for x in a["durations"]}
    assert dur["2-4h"] == 1 and dur["1-2h"] == 1 and dur[">8h"] == 1   # abierta: tope de 12 h
    assert {(x["cluster"], x["row"], x["seat"]) for x in a["seats"]} == {(3, 5, 1), (1, 1, 1)}  # "raro" se ignora
    assert a["clusters"] == [{"cluster": 1, "sessions": 1}, {"cluster": 3, "sessions": 1}]
    assert a["peak"]["value"] > 0


def test_evaluations(engine):
    e = run(engine, stats.evaluations, 36, NOW)
    assert e["total"] == 3 and e["avg_mark"] == 75.0 and e["positive_share"] == round(2 / 3, 3)
    assert e["truant"] == 1 and e["scheduled"] == 1 and e["active_correctors_90d"] == 2
    assert {f["name"]: f["count"] for f in e["flags"]} == {"Ok": 2, "Incomplete work": 1}
    assert {m["label"]: m["count"] for m in e["marks"]}["0"] == 1
    sep = next(m for m in e["monthly"] if m["month"] == "2026-09")
    assert sep["count"] == 2 and sep["avg_mark"] == 62.5


def test_events_and_exams(engine):
    x = run(engine, stats.events_exams, 24, NOW)
    assert [e["name"] for e in x["upcoming_events"]] == ["Hackathon"]
    assert x["upcoming_events"][0]["max_people"] == 100 and x["upcoming_events"][0]["kind"] == "conference"
    assert x["upcoming_exams"][0]["name"] == "Exam Rank 02"
    assert {k["kind"] for k in x["kinds"]} == {"event", "conference"}
    assert sum(m["count"] for m in x["events_monthly"]) == 2


def test_stats_have_no_personal_fields(engine):
    with Session(engine) as s:
        blob = str([stats.overview(s), stats.levels(s), stats.cohorts(s), stats.signups(s),
                    stats.projects(s, 1), stats.attendance(s, 90, NOW), stats.evaluations(s)])
    assert "u1" not in blob and "login" not in blob and "corrector_id" not in blob and "user_id" not in blob


def test_api_endpoints_and_headers(engine):
    c = TestClient(create_app(engine, 21))
    assert c.get("/api/health").json() == {"status": "ok"}
    for path in ("overview", "levels", "cohorts", "signups", "projects", "projects/monthly",
                 "attendance", "evaluations", "events"):
        assert c.get(f"/api/{path}").status_code == 200, path
    r = c.get("/api/overview")
    assert r.headers["cache-control"] == "public, max-age=300"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert "max-age" not in c.get("/api/health").headers.get("cache-control", "")


def test_api_caches_expensive_queries(engine, monkeypatch):
    calls = {"n": 0}
    real = stats.attendance

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(stats, "attendance", counting)
    c = TestClient(create_app(engine, 21))
    c.get("/api/attendance"), c.get("/api/attendance")
    assert calls["n"] == 1


def test_api_returns_503_when_tables_missing():
    empty = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    assert TestClient(create_app(empty, 21)).get("/api/overview").status_code == 503


def test_index_and_static_assets_served():
    web = TestClient(create_app(create_engine("sqlite://"), 21))
    r = web.get("/")
    assert r.status_code == 200 and "42" in r.text
    assert r.text.count("<script") == 1 and 'src="/static/app.js"' in r.text  # sin JS inline (la CSP lo bloquea)
    for asset in ("/static/app.js", "/static/style.css"):
        assert web.get(asset).status_code == 200, asset


def test_readonly_engine_survives_many_concurrent_requests(tmp_path):
    """Regresión: con el pool por defecto de SQLite, >5 peticiones simultáneas mataban el proceso (SIGSEGV)."""
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy.pool import NullPool

    from stats42.db import make_engine, make_readonly_engine

    url = f"sqlite:///{tmp_path / 'ro.db'}"
    factory = init_db(make_engine(url))
    with factory() as s:
        s.add_all([user(i) for i in range(1, 40)])
        s.commit()
    ro = make_readonly_engine(url)
    assert isinstance(ro.pool, NullPool)
    client = TestClient(create_app(ro, 21))
    paths = ["overview", "levels", "cohorts", "signups", "projects", "attendance", "evaluations", "events"] * 6
    with ThreadPoolExecutor(max_workers=16) as ex:
        codes = list(ex.map(lambda p: client.get(f"/api/{p}").status_code, paths))
    assert set(codes) == {200}
    with pytest.raises(Exception):  # sigue siendo de solo lectura
        with ro.connect() as c:
            c.exec_driver_sql("DELETE FROM users")


def test_readonly_connection_can_be_used_from_another_thread(tmp_path):
    """Regresión: FastAPI abre la sesión en un hilo y ejecuta el endpoint en otro."""
    from concurrent.futures import ThreadPoolExecutor

    from stats42.db import make_engine, make_readonly_engine

    url = f"sqlite:///{tmp_path / 'x.db'}"
    init_db(make_engine(url))
    ro = make_readonly_engine(url)
    with ro.connect() as conn:
        with ThreadPoolExecutor(1) as ex:
            assert ex.submit(lambda: conn.exec_driver_sql("select 1").scalar()).result() == 1


def test_corrupt_marks_are_ignored_in_average(engine):
    """Regresión: un intento con nota 1.149.710.997 dejaba la media de libft en 467.843,8."""
    with Session(engine) as s:
        s.add_all([
            ProjectUser(id=701, user_id=1, project_id=1, status="finished", final_mark=1149710997, validated=True),
            ProjectUser(id=702, user_id=2, project_id=1, status="finished", final_mark=-42, validated=False),
        ])
        s.commit()
    p = run(engine, stats.projects, min_attempts=20)[0]
    assert p["avg_mark"] == 75.0           # ninguna de las dos notas inválidas entra en la media
    assert p["finished"] == 21             # la corrupta cuenta como intento; la de -42 (cheating) no cuenta nada
    assert p["attempts"] == 21


def test_projects_expose_cursus_of_each_project(engine):
    with Session(engine) as s:
        s.get(Project, 1).cursus_names = "42cursus, Python Piscine"
        s.commit()
    assert run(engine, stats.projects, min_attempts=20)[0]["cursus"] == "42cursus, Python Piscine"


def test_blackholes_by_week_counts_only_open_cursus_and_future_dates(engine):
    with Session(engine) as s:
        s.add_all([
            cu(10, 3, 1.0, bh=NOW + timedelta(days=3)),    # esta semana
            cu(11, 5, 1.0, bh=NOW + timedelta(days=9)),    # semana siguiente
            cu(12, 6, 1.0, bh=NOW + timedelta(days=400)),  # más allá del horizonte
            cu(13, 4, 1.0, bh=NOW - timedelta(days=2)),    # ya pasado
        ])
        s.commit()
    b = run(engine, stats.blackholes, 21, NOW, 26)
    counts = {w["week"]: w["count"] for w in b["weeks"]}
    assert len(b["weeks"]) == 26 and b["later"] == 2        # el 2 (+200 d) y el nuevo (+400 d)
    assert sum(counts.values()) == 3 and b["upcoming"] == 5
    assert "user_id" not in str(b)


def test_map_project_keeps_cursus_names():
    from stats42.resources import map_project

    row = map_project({"id": 5, "name": "Python Module 00", "slug": "python-module-00", "difficulty": 0,
                       "exam": False, "cursus": [{"id": 21, "name": "42cursus"}, {"id": 99, "name": "Python Piscine"}]})
    assert row["cursus_ids"] == [21, 99] and row["cursus_names"] == "42cursus, Python Piscine"
    assert map_project({"id": 6, "name": "x", "slug": "x"})["cursus_names"] is None


def test_init_db_adds_new_columns_to_existing_tables(tmp_path):
    from sqlalchemy import inspect, text

    from stats42.db import make_engine

    eng = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:   # tabla "antigua", sin las columnas cursus_*
        c.execute(text("CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, slug VARCHAR NOT NULL, "
                       "difficulty INTEGER, exam BOOLEAN)"))
        c.execute(text("INSERT INTO projects VALUES (1, 'libft', 'libft', 1, 0)"))
    init_db(eng)
    cols = {c["name"] for c in inspect(eng).get_columns("projects")}
    assert {"cursus_ids", "cursus_names"} <= cols
    with eng.connect() as c:
        assert c.execute(text("SELECT name FROM projects")).scalar() == "libft"   # los datos se conservan


def test_cheating_attempts_do_not_count_anywhere(engine):
    """-42 es la nota que 42 pone por cheating: ni intento, ni terminado, ni validación, ni mes."""
    with Session(engine) as s:
        s.add_all([ProjectUser(id=800 + i, user_id=1, project_id=1, status="finished", final_mark=-42, validated=False,
                               created_at=dt("2026-08-01T10:00:00"), marked_at=dt("2026-07-01T10:00:00")) for i in range(5)])
        s.commit()
    p = run(engine, stats.projects, min_attempts=20)[0]
    assert (p["attempts"], p["finished"], p["validation_rate"]) == (20, 20, 0.5)   # idéntico al caso sin cheating
    months = {m["month"]: m for m in run(engine, stats.projects_monthly)}
    assert "2026-07" not in months                                                   # el mes de esas notas ni aparece


def test_cohorts_split_blackholed_from_early_drop_outs(engine):
    with Session(engine) as s:
        s.add_all([user(20, "2023"), user(21, "2023"), user(22, "2023"), user(23, "2023"), user(24, "2023")])
        s.add_all([
            cu(30, 20, 1.2, end_at=NOW - timedelta(days=9), bh=NOW - timedelta(days=10)),    # cierra 1 día después: blackholeado
            cu(31, 21, 1.4, end_at=NOW - timedelta(days=100), bh=NOW - timedelta(days=20)),  # cierra 80 días antes: baja
            cu(32, 22, 2.0, end_at=NOW - timedelta(days=1), bh=NOW - timedelta(days=200)),   # cierra 199 días después: sin clasificar
            cu(33, 23, 3.0, end_at=NOW - timedelta(days=30), bh=None),                       # sin fecha de blackhole
            cu(34, 24, 1.0, bh=NOW + timedelta(days=50)),                                    # abierto
        ])
        s.commit()
    c = {x["year"]: x for x in run(engine, stats.cohorts, 21, NOW)}["2023"]
    assert (c["pool"], c["in_cursus"], c["current"], c["blackholed"], c["dropped"]) == (5, 5, 1, 1, 1)
    o = run(engine, stats.overview, 21, NOW)
    assert o["cursus_blackholed"] == 1 and o["cursus_dropped"] == 1
