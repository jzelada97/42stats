"""Registro de quién choca con los límites: solo uid y login, sin IP, visible para admins y con retención de 30 días."""
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from stats42 import abuse as abuse_module
from stats42.db import AbuseEvent
from stats42.helpboard import erase_user, purge

from test_auth import engine as auth_engine  # noqa: F401
from test_auth import login, make_client
from test_helpboard import ADMIN_CFG, NOW, engine, post, store, user  # noqa: F401


def hammer(c, path="/api/help/overview", n=125):
    return [c.get(path).status_code for _ in range(n)]


def test_hitting_a_limit_is_recorded_with_login_and_kind_but_no_ip(engine, store, caplog):
    c = user(engine, store, 13)
    with caplog.at_level(logging.WARNING, logger="stats42.abuse"):
        assert hammer(c)[-1] == 429
    with Session(store) as db:
        row = db.query(AbuseEvent).one()
        assert (row.user_id, row.login, row.kind) == (13, "u13", "lectura-ayuda") and row.hits >= 1
    assert "uid=13 login=u13 tipo=lectura-ayuda" in caplog.text
    assert {col.name for col in AbuseEvent.__table__.columns} == {"user_id", "kind", "login", "hits", "first_at", "last_at"}


def test_a_flood_writes_to_the_database_in_batches_not_once_per_rejected_request(engine, store, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(abuse_module.time, "monotonic", lambda: t[0])
    c = user(engine, store, 13)
    codes = hammer(c, n=130)                                          # 10 rechazadas dentro de la misma ventana de 10 s
    assert codes.count(429) >= 9
    with Session(store) as db:
        assert db.query(AbuseEvent).one().hits == 1                   # la primera se vuelca al instante, el resto queda pendiente
    t[0] += 11
    c.get("/api/help/overview")
    with Session(store) as db:
        assert db.query(AbuseEvent).one().hits == codes.count(429) + 1                       # nada se pierde: se suma lo pendiente


def test_other_limits_are_recorded_too(engine, store):
    c = user(engine, store, 13)
    for _ in range(25):
        post(c, "/api/me/settings", deadline=(NOW + timedelta(days=100)).date().isoformat())
    with Session(store) as db:
        assert "ajustes" in [r.kind for r in db.query(AbuseEvent)]


def test_me_limit_is_recorded(auth_engine):
    c, _ = make_client(auth_engine)
    login(c)
    for _ in range(62):
        c.get("/api/me")
    with Session(c.settings_engine) as db:
        assert [r.kind for r in db.query(AbuseEvent)] == ["lectura-me"]


def test_only_admins_can_read_the_list(engine, store):
    hammer(user(engine, store, 13))
    assert user(engine, store, 15).get("/api/admin/help/abuse").status_code == 403
    assert user(engine, store, 14).get("/api/admin/help/abuse").status_code == 403           # u14 no es admin con la config normal
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    events = admin.get("/api/admin/help/abuse").json()["events"]
    assert [(e["login"], e["kind"]) for e in events] == [("u13", "lectura-ayuda")] and "user_id" not in str(events)


def test_anonymous_visitors_cannot_read_the_list(engine, store):
    c = user(engine, store, 13)
    c.cookies.clear()
    assert c.get("/api/admin/help/abuse").status_code == 401


def test_records_expire_after_30_days_and_vanish_with_the_user_data(engine, store):
    user(engine, store, 13)                                                                   # crea las tablas
    with Session(store) as db:
        db.add_all([AbuseEvent(user_id=1, kind="ajustes", login="viejo", hits=3, first_at=NOW - timedelta(days=50), last_at=NOW - timedelta(days=40)),
                    AbuseEvent(user_id=2, kind="ajustes", login="nuevo", hits=1, first_at=NOW, last_at=NOW),
                    AbuseEvent(user_id=3, kind="ajustes", login="borrame", hits=1, first_at=NOW, last_at=NOW)])
        db.commit()
        purge(db)
        assert sorted(r.login for r in db.query(AbuseEvent)) == ["borrame", "nuevo"]
        erase_user(db, 3)
        db.commit()
        assert [r.login for r in db.query(AbuseEvent)] == ["nuevo"]
