"""Puntos de mentoría: solo cuentan cuando están verificados (agradecidos Y el alumno validó el proyecto después de pedir ayuda)."""
from datetime import timedelta

from sqlalchemy.orm import Session

from stats42 import points as pointsmod
from stats42.db import MentorThanks, ProjectUser
from stats42.helpboard import erase_user

from test_helpboard import ADMIN_CFG, NOW, engine, post, store, user  # noqa: F401

MSG = "No entiendo cómo reservar memoria con malloc"


def ask(engine, store, asker=15, mentor=13, project=1, offer=True):
    m = user(engine, store, mentor)
    if offer:
        post(m, "/api/help/offer", active=True, project_ids=[project])
    a = user(engine, store, asker)
    rid = post(a, "/api/help/requests", project_id=project, message=MSG).json()["id"]
    return a, m, rid


def close(a, rid, **body):
    return post(a, f"/api/help/requests/{rid}/close", **body)


def validate(engine, uid, project, when, k=[9500]):       # noqa: B006 - contador compartido a propósito
    k[0] += 1
    with Session(engine) as s:
        s.add(ProjectUser(id=k[0], user_id=uid, project_id=project, status="finished", validated=True, final_mark=100, marked_at=when))
        s.commit()


def points_of(c):
    return c.get("/api/help/overview").json()["points"]


def test_tiers_are_named_and_the_next_one_is_announced():
    assert [pointsmod.tier(n) for n in (0, 1, 4, 5, 14, 15, 99)] == [None, "Brote", "Brote", "Caña", "Caña", "Bosque", "Bosque"]
    assert pointsmod.next_tier(0) == {"name": "Brote", "needs": 1} and pointsmod.next_tier(3) == {"name": "Caña", "needs": 2}
    assert pointsmod.next_tier(15) is None


def test_a_thanks_is_pending_until_the_asker_validates_the_project_afterwards(engine, store):
    a, m, rid = ask(engine, store)
    r = close(a, rid, helped_by="u13", no_code=True)
    assert r.status_code == 200 and r.json()["thanked"] == "u13"
    assert points_of(m) == {"verified": 0, "pending": 1, "tier": None, "next": {"name": "Brote", "needs": 1}}
    validate(engine, 15, 1, NOW + timedelta(days=2))                               # el alumno valida libft DESPUÉS de pedir ayuda
    p = points_of(m)
    assert (p["verified"], p["pending"], p["tier"]) == (1, 0, "Brote")
    with Session(store) as db:
        assert db.query(MentorThanks).one().verified is True                       # la verificación se guarda


def test_a_validation_from_before_asking_for_help_does_not_verify(engine, store):
    a, m, rid = ask(engine, store)
    close(a, rid, helped_by="u13", no_code=True)
    validate(engine, 15, 1, NOW - timedelta(days=30))
    assert (points_of(m)["verified"], points_of(m)["pending"]) == (0, 1)


def test_if_the_asker_already_validated_by_closing_time_the_point_is_instant(engine, store):
    a, m, rid = ask(engine, store)
    validate(engine, 15, 1, NOW + timedelta(hours=1))
    close(a, rid, helped_by="u13", no_code=True)
    assert points_of(m)["verified"] == 1


def test_thanking_needs_the_no_code_confirmation(engine, store):
    a, m, rid = ask(engine, store)
    assert close(a, rid, helped_by="u13").status_code == 422
    assert close(a, rid, helped_by="u13", no_code=False).status_code == 422
    assert a.get("/api/help/overview").json()["requests"] != []                      # la petición sigue abierta


def test_you_can_only_thank_mentors_of_that_project(engine, store):
    a, m, rid = ask(engine, store)
    for who in ("u16", "u15", "u99"):                                                # no es mentor, uno mismo, no existe
        assert close(a, rid, helped_by=who, no_code=True).status_code == 422
    post(user(engine, store, 12), "/api/help/offer", active=True, project_ids=[1])
    post(user(engine, store, 14), "/api/help/offer", active=True, project_ids=[3])    # u14 ofrece printf, no libft
    assert close(a, rid, helped_by="u14", no_code=True).status_code == 422
    post(m, "/api/help/offer", active=False, project_ids=[1])                         # mentor desactivado
    assert close(a, rid, helped_by="u13", no_code=True).status_code == 422
    with Session(store) as db:
        assert db.query(MentorThanks).count() == 0


def test_closing_without_thanks_just_closes(engine, store):
    a, m, rid = ask(engine, store)
    assert close(a, rid).json()["thanked"] is None
    with Session(store) as db:
        assert db.query(MentorThanks).count() == 0


def test_only_the_asker_can_thank_not_an_admin(engine, store):
    a, m, rid = ask(engine, store)
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    assert close(admin, rid, helped_by="u13", no_code=True).status_code == 403
    assert close(admin, rid).status_code == 200                                      # cerrar sí puede


def test_one_thanks_per_asker_and_project(engine, store):
    a, m, rid = ask(engine, store)
    close(a, rid, helped_by="u13", no_code=True)
    rid2 = post(a, "/api/help/requests", project_id=1, message=MSG + " otra vez").json()["id"]
    r = close(a, rid2, helped_by="u13", no_code=True)
    assert r.status_code == 422 and "Ya agradeciste" in r.json()["detail"]
    assert close(a, rid2).status_code == 200


def test_weekly_cap_on_thanks_given(engine, store, monkeypatch):
    monkeypatch.setattr(pointsmod, "THANKS_PER_WEEK", 1)
    a, m, rid = ask(engine, store, project=1)
    assert close(a, rid, helped_by="u13", no_code=True).status_code == 200
    post(m, "/api/help/offer", active=True, project_ids=[1, 2])
    rid2 = post(a, "/api/help/requests", project_id=2, message=MSG + " gnl").json()["id"]
    r = close(a, rid2, helped_by="u13", no_code=True)
    assert r.status_code == 422 and "por semana" in r.json()["detail"]


def test_mentor_list_shows_tiers_and_puts_the_most_thanked_first(engine, store):
    post(user(engine, store, 14), "/api/help/offer", active=True, project_ids=[1])
    a, m, rid = ask(engine, store)                                                    # u13 se ofrece después (más reciente que u14)
    close(a, rid, helped_by="u13", no_code=True)
    validate(engine, 15, 1, NOW + timedelta(days=1))
    c = user(engine, store, 16)
    got = c.get("/api/help/mentors?project_id=1").json()["mentors"]
    assert [(x["login"], x["points"], x["tier"]) for x in got] == [("u13", 1, "Brote"), ("u14", 0, None)]


def test_a_mentor_never_sees_who_thanked_them(engine, store):
    a, m, rid = ask(engine, store)
    close(a, rid, helped_by="u13", no_code=True)
    assert "u15" not in str(m.get("/api/help/overview").json()) and "asker" not in str(m.get("/api/help/overview").json())


def test_deleting_my_data_keeps_verified_points_anonymous_and_drops_the_rest(engine, store):
    a, m, rid = ask(engine, store)
    close(a, rid, helped_by="u13", no_code=True)
    validate(engine, 15, 1, NOW + timedelta(days=1))
    assert points_of(m)["verified"] == 1
    assert post(a, "/api/me/delete").json() == {"deleted": True}
    with Session(store) as db:
        row = db.query(MentorThanks).one()
        assert row.asker_uid < 0 and row.verified is True                             # el mentor conserva su punto, sin saber de quién
    assert points_of(m)["verified"] == 1


def test_deleting_my_data_drops_pending_thanks_given_and_all_received(engine, store):
    a, m, rid = ask(engine, store)
    close(a, rid, helped_by="u13", no_code=True)
    post(a, "/api/me/delete")
    with Session(store) as db:
        assert db.query(MentorThanks).count() == 0                                    # pendiente: se borra con quien agradeció
    a, m, rid = ask(engine, store)
    close(a, rid, helped_by="u13", no_code=True)
    post(m, "/api/me/delete")
    with Session(store) as db:
        assert db.query(MentorThanks).count() == 0                                    # recibidos: se van con el mentor


def test_unverified_thanks_expire_after_a_year(engine, store):
    a, m, rid = ask(engine, store)
    close(a, rid, helped_by="u13", no_code=True)
    from stats42.helpboard import purge
    with Session(store) as db:
        db.query(MentorThanks).update({"created_at": NOW - timedelta(days=400)})
        db.commit()
        purge(db)
        assert db.query(MentorThanks).count() == 0


def test_closing_still_needs_a_session_and_json(engine, store):
    c = user(engine, store, 13)
    c.cookies.clear()
    assert post(c, "/api/help/requests/1/close", helped_by="u13", no_code=True).status_code == 401
