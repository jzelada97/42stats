"""Registro de accesos: se anota al entrar, solo lo ven los admins, caduca a los 90 días y se borra con "Borrar mis datos"."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from stats42 import logins as loginsmod
from stats42.db import LoginRecord

from test_helpboard import ADMIN_CFG, NOW, engine, post, store, user  # noqa: F401


def test_logging_in_is_recorded_with_first_last_and_count(engine, store):
    user(engine, store, 13)
    user(engine, store, 13)
    user(engine, store, 15)
    with Session(store) as db:
        rows = {r.login: r for r in db.query(LoginRecord)}
        assert set(rows) == {"u13", "u15"} and rows["u13"].logins == 2 and rows["u15"].logins == 1
        assert rows["u13"].first_at <= rows["u13"].last_at
    assert {c.name for c in LoginRecord.__table__.columns} == {"user_id", "login", "first_at", "last_at", "logins"}     # sin IP


def test_summary_counts_distinct_students_per_window_and_lists_the_latest_first():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    LoginRecord.__table__.create(eng)
    now = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
    with Session(eng) as db:
        for uid, login, ago_h, n in [(1, "hoy", 2, 3), (2, "esta_semana", 24 * 3, 1), (3, "este_mes", 24 * 20, 5), (4, "antiguo", 24 * 60, 1)]:
            at = now - timedelta(hours=ago_h)
            db.add(LoginRecord(user_id=uid, login=login, first_at=at, last_at=at, logins=n))
        db.commit()
        s = loginsmod.summary(db, now)
        assert (s["day"], s["week"], s["month"], s["total"]) == (1, 2, 3, 4)
        assert [r["login"] for r in s["recent"]] == ["hoy", "esta_semana", "este_mes", "antiguo"]
        assert s["recent"][0]["last"] == "2026-10-04T13:00+00:00" and s["recent"][0]["logins"] == 3      # con zona: el navegador la pasa a hora local
        loginsmod.purge(db, now)
        assert db.query(LoginRecord).count() == 4                                                      # ninguno pasa aún de 90 días
        loginsmod.purge(db, now + timedelta(days=40))
        assert sorted(r.login for r in db.query(LoginRecord)) == ["esta_semana", "este_mes", "hoy"]    # el de 100 días cae
        loginsmod.purge(db, now + timedelta(days=200))
        assert db.query(LoginRecord).count() == 0


def test_only_admins_can_read_the_access_log(engine, store):
    user(engine, store, 15)
    assert user(engine, store, 13).get("/api/admin/logins").status_code == 403
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    s = admin.get("/api/admin/logins").json()
    assert s["total"] == 3 and s["day"] == 3 and {r["login"] for r in s["recent"]} == {"u13", "u14", "u15"}
    assert "user_id" not in str(s)
    admin.cookies.clear()
    assert admin.get("/api/admin/logins").status_code == 401


def test_delete_my_data_removes_my_access_record(engine, store):
    c = user(engine, store, 13)
    user(engine, store, 15)
    assert post(c, "/api/me/delete").json() == {"deleted": True}
    with Session(store) as db:
        assert [r.login for r in db.query(LoginRecord)] == ["u15"]


def test_a_failure_recording_the_access_never_blocks_the_login(engine, store, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def boom(*a, **k):
        raise OperationalError("insert", {}, Exception("disco lleno"))
    monkeypatch.setattr(loginsmod, "record_login", boom)
    c = user(engine, store, 13)
    assert c.get("/api/me").status_code != 401                              # la sesión se creó igualmente
