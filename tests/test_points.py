"""Conexión mentor-alumno y puntos de mentoría: el mentor se ofrece a ESA petición, el alumno agradece, el mentor confirma y el alumno
valida el proyecto entre 48 h y 120 días después. Solo entonces cuenta el punto."""
from datetime import timedelta

from sqlalchemy.orm import Session

from stats42 import points as pointsmod
from stats42.db import HelpOffer, HelpRequest, MentorThanks, ProjectUser
from stats42.helpboard import purge

from test_helpboard import ADMIN_CFG, NOW, engine, post, store, user  # noqa: F401

MSG = "No entiendo cómo reservar memoria con malloc"


def ask(engine, store, asker=15, mentor=13, project=1, projects=None, offer_help=True):
    m = user(engine, store, mentor)
    post(m, "/api/help/offer", active=True, project_ids=projects or [project])
    a = user(engine, store, asker)
    rid = post(a, "/api/help/requests", project_id=project, message=MSG).json()["id"]
    if offer_help:
        assert post(m, f"/api/help/requests/{rid}/offer").status_code == 200
    return a, m, rid


def thank(a, rid, who="u13", ok=True):
    return post(a, f"/api/help/requests/{rid}/close", helped_by=who, no_code=ok)


def confirm(m, ok=True, no_code=True):
    tid = m.get("/api/help/overview").json()["confirmations"][0]["id"]
    return post(m, f"/api/help/thanks/{tid}/confirm", ok=ok, no_code=no_code)


def validate(engine, uid, project, when, k=[9500]):       # noqa: B006 - contador compartido a propósito
    k[0] += 1
    with Session(engine) as s:
        s.add(ProjectUser(id=k[0], user_id=uid, project_id=project, status="finished", validated=True, final_mark=100, marked_at=when))
        s.commit()


def points_of(c):
    return c.get("/api/help/overview").json()["points"]


def full_flow(engine, store, asker=15, mentor=13, project=1, days=3):
    a, m, rid = ask(engine, store, asker, mentor, project)
    assert thank(a, rid, f"u{mentor}").status_code == 200
    assert confirm(m).status_code == 200
    validate(engine, asker, project, NOW + timedelta(days=days))
    return a, m


# ---------------------------------------------------------------- tramos

def test_tiers_are_named_and_the_next_one_is_announced():
    assert [pointsmod.tier(n) for n in (0, 1, 4, 5, 14, 15, 99)] == [None, "Brote", "Brote", "Caña", "Caña", "Bosque", "Bosque"]
    assert pointsmod.next_tier(0) == {"name": "Brote", "needs": 1} and pointsmod.next_tier(3) == {"name": "Caña", "needs": 2}
    assert pointsmod.next_tier(15) is None


# ---------------------------------------------------------------- "Quiero ayudar"

def test_a_mentor_can_offer_to_help_a_request_and_the_asker_sees_who(engine, store):
    a, m, rid = ask(engine, store)
    mine = a.get("/api/help/overview").json()["requests"][0]
    assert [(r["login"], r["points"], r["tier"]) for r in mine["responders"]] == [("u13", 0, None)]
    inbox = m.get("/api/help/overview").json()["incoming"]
    assert [(i["id"], i["offered"]) for i in inbox] == [(rid, True)]


def test_offering_is_idempotent_and_can_be_withdrawn(engine, store):
    a, m, rid = ask(engine, store)
    assert post(m, f"/api/help/requests/{rid}/offer").status_code == 200
    with Session(store) as db:
        assert db.query(HelpOffer).count() == 1
    assert post(m, f"/api/help/requests/{rid}/withdraw").json() == {"id": rid, "offered": False}
    assert a.get("/api/help/overview").json()["requests"][0]["responders"] == []
    assert m.get("/api/help/overview").json()["incoming"][0]["offered"] is False


def test_only_active_mentors_of_that_project_who_validated_it_can_offer(engine, store):
    a, m, rid = ask(engine, store, offer_help=False)
    u14 = user(engine, store, 14)                                                    # validó libft pero no se ofreció como mentor
    assert post(u14, f"/api/help/requests/{rid}/offer").status_code == 422
    post(u14, "/api/help/offer", active=True, project_ids=[3])                      # mentor, pero de printf
    assert post(u14, f"/api/help/requests/{rid}/offer").status_code == 422
    u16 = user(engine, store, 16)                                                    # no validó nada
    assert post(u16, f"/api/help/requests/{rid}/offer").status_code == 422
    assert post(a, f"/api/help/requests/{rid}/offer").status_code == 404            # nadie se ofrece a su propia petición
    post(m, "/api/help/offer", active=False, project_ids=[1])
    assert post(m, f"/api/help/requests/{rid}/offer").status_code == 422             # mentor desactivado
    with Session(store) as db:
        assert db.query(HelpOffer).count() == 0


def test_at_most_five_mentors_can_offer_to_the_same_request(engine, store, monkeypatch):
    monkeypatch.setattr(pointsmod, "MAX_RESPONDERS", 1)
    a, m, rid = ask(engine, store)
    post(user(engine, store, 14), "/api/help/offer", active=True, project_ids=[1])
    r = post(user(engine, store, 14), f"/api/help/requests/{rid}/offer")
    assert r.status_code == 422 and "mentores ofrecidos" in r.json()["detail"]


def test_offering_to_a_missing_or_closed_request_is_404_and_needs_a_session(engine, store):
    a, m, rid = ask(engine, store)
    post(a, f"/api/help/requests/{rid}/close")
    assert post(m, f"/api/help/requests/{rid}/offer").status_code == 404
    assert post(m, "/api/help/requests/999/offer").status_code == 404
    m.cookies.clear()
    assert post(m, f"/api/help/requests/{rid}/offer").status_code == 401
    with Session(store) as db:
        assert db.query(HelpOffer).count() == 0                                      # cerrar borra también las ofertas


# ---------------------------------------------------------------- agradecer

def test_you_can_only_thank_a_mentor_who_offered_to_that_request(engine, store):
    a, m, rid = ask(engine, store)
    post(user(engine, store, 14), "/api/help/offer", active=True, project_ids=[1])   # u14 es mentor de libft pero no se ofreció a esta petición
    for who in ("u14", "u16", "u15", "u99"):
        assert thank(a, rid, who).status_code == 422
    with Session(store) as db:
        assert db.query(MentorThanks).count() == 0
    assert a.get("/api/help/overview").json()["requests"] != []                      # la petición sigue abierta


def test_thanking_needs_the_no_code_confirmation(engine, store):
    a, m, rid = ask(engine, store)
    assert post(a, f"/api/help/requests/{rid}/close", helped_by="u13").status_code == 422
    assert thank(a, rid, ok=False).status_code == 422


def test_closing_without_thanks_just_closes_and_only_the_asker_can_thank(engine, store):
    a, m, rid = ask(engine, store)
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    assert thank(admin, rid).status_code == 403
    assert post(admin, f"/api/help/requests/{rid}/close").status_code == 200        # cerrar sí puede
    with Session(store) as db:
        assert db.query(MentorThanks).count() == 0


def test_one_thanks_per_asker_and_project(engine, store):
    a, m, rid = ask(engine, store)
    thank(a, rid)
    rid2 = post(a, "/api/help/requests", project_id=1, message=MSG + " otra vez").json()["id"]
    post(m, f"/api/help/requests/{rid2}/offer")
    r = thank(a, rid2)
    assert r.status_code == 422 and "Ya agradeciste" in r.json()["detail"]


def test_at_most_two_points_per_mentor_student_pair(engine, store):
    validate(engine, 13, 3, NOW - timedelta(days=10))                                # u13 también validó printf
    a, m, rid = ask(engine, store, project=1, projects=[1, 2, 3])
    assert thank(a, rid).status_code == 200
    for project, expected in ((2, 200), (3, 422)):
        rid = post(a, "/api/help/requests", project_id=project, message=MSG + f" {project}").json()["id"]
        post(m, f"/api/help/requests/{rid}/offer")
        r = thank(a, rid)
        assert r.status_code == expected, r.text
    assert "máximo por pareja" in r.json()["detail"]


def test_weekly_cap_on_thanks_given(engine, store, monkeypatch):
    monkeypatch.setattr(pointsmod, "THANKS_PER_WEEK", 1)
    a, m, rid = ask(engine, store, project=1, projects=[1, 2])
    assert thank(a, rid).status_code == 200
    rid2 = post(a, "/api/help/requests", project_id=2, message=MSG + " gnl").json()["id"]
    post(m, f"/api/help/requests/{rid2}/offer")
    r = thank(a, rid2)
    assert r.status_code == 422 and "por semana" in r.json()["detail"]


# ---------------------------------------------------------------- los tres lados del punto

def test_a_point_needs_the_thanks_the_mentors_confirmation_and_the_asker_validating(engine, store):
    a, m, rid = ask(engine, store)
    assert thank(a, rid).json()["thanked"] == "u13"
    p = points_of(m)
    assert (p["verified"], p["pending"], p["to_confirm"]) == (0, 1, 1)               # falta confirmación y validación
    assert confirm(m).status_code == 200
    p = points_of(m)
    assert (p["verified"], p["pending"], p["to_confirm"]) == (0, 1, 0)               # confirmado, falta que el alumno valide
    validate(engine, 15, 1, NOW + timedelta(days=3))
    p = points_of(m)
    assert (p["verified"], p["pending"], p["tier"]) == (1, 0, "Brote")


def test_validating_without_the_mentors_confirmation_does_not_count(engine, store):
    a, m, rid = ask(engine, store)
    thank(a, rid)
    validate(engine, 15, 1, NOW + timedelta(days=3))
    p = points_of(m)
    assert (p["verified"], p["to_confirm"]) == (0, 1)
    with Session(store) as db:
        assert db.query(MentorThanks).one().verified is True                         # verificado, pero sin el sí del mentor no suma


def test_the_validation_must_fall_between_48_hours_and_120_days_after_asking(engine, store):
    user(engine, store, 13)                                                          # crea las tablas de la base escribible
    for k, (delta, counts) in enumerate([(timedelta(hours=1), 0), (timedelta(hours=47), 0), (timedelta(days=-5), 0),
                                         (timedelta(days=121), 0), (timedelta(hours=49), 1)]):
        asker = 15 + (k % 2)                                                         # alternar alumnos para no chocar con el tope por pareja
        project = 1
        with Session(store) as db:
            db.query(MentorThanks).delete()
            db.query(HelpRequest).delete()
            db.commit()
        with Session(engine) as s:
            s.query(ProjectUser).filter(ProjectUser.user_id == asker, ProjectUser.project_id == project).delete()
            s.commit()
        a, m, rid = ask(engine, store, asker=asker, project=project)
        thank(a, rid)
        confirm(m)
        with Session(store) as db:
            asked = db.query(MentorThanks).one().asked_at
        validate(engine, asker, project, asked.replace(tzinfo=NOW.tzinfo) + delta)
        assert points_of(m)["verified"] == counts, (delta, counts)


def test_the_mentor_can_deny_having_helped_and_the_thanks_disappears(engine, store):
    a, m, rid = ask(engine, store)
    thank(a, rid)
    assert confirm(m, ok=False, no_code=False).status_code == 200
    with Session(store) as db:
        assert db.query(MentorThanks).count() == 0
    assert m.get("/api/help/overview").json()["confirmations"] == []


def test_confirming_needs_the_no_code_tick_and_only_the_mentor_can_do_it(engine, store):
    a, m, rid = ask(engine, store)
    thank(a, rid)
    tid = m.get("/api/help/overview").json()["confirmations"][0]["id"]
    assert post(m, f"/api/help/thanks/{tid}/confirm", ok=True, no_code=False).status_code == 422
    assert post(a, f"/api/help/thanks/{tid}/confirm", ok=True, no_code=True).status_code == 404       # quien agradeció no puede confirmarse a sí mismo
    assert post(user(engine, store, 14), f"/api/help/thanks/{tid}/confirm", ok=True, no_code=True).status_code == 404
    assert post(m, f"/api/help/thanks/{tid}/confirm", ok=True, no_code=True).status_code == 200
    assert post(m, f"/api/help/thanks/{tid}/confirm", ok=True, no_code=True).status_code == 200      # repetir no rompe nada
    assert post(m, "/api/help/thanks/999/confirm", ok=True, no_code=True).status_code == 404


def test_a_mentor_never_sees_who_thanked_them(engine, store):
    a, m, rid = ask(engine, store)
    thank(a, rid)
    o = m.get("/api/help/overview").json()
    assert set(o["confirmations"][0]) == {"id", "project", "days"} and "u15" not in str(o)


# ---------------------------------------------------------------- lista de mentores y avisos

def test_mentor_list_shows_tiers_and_puts_the_most_thanked_first(engine, store):
    post(user(engine, store, 14), "/api/help/offer", active=True, project_ids=[1])
    full_flow(engine, store)
    got = user(engine, store, 16).get("/api/help/mentors?project_id=1").json()["mentors"]
    assert [(x["login"], x["points"], x["tier"]) for x in got] == [("u13", 1, "Brote"), ("u14", 0, None)]


def test_summary_counts_what_is_waiting_for_each_user(engine, store):
    a, m, rid = ask(engine, store, offer_help=False)
    assert m.get("/api/help/summary").json() == {"incoming": 1, "offers": 0, "to_confirm": 0, "total": 1}      # una petición sin responder
    post(m, f"/api/help/requests/{rid}/offer")
    assert m.get("/api/help/summary").json()["incoming"] == 0                                                  # ya me ofrecí
    assert a.get("/api/help/summary").json() == {"incoming": 0, "offers": 1, "to_confirm": 0, "total": 1}      # alguien se ofreció a mi petición
    thank(a, rid)
    assert m.get("/api/help/summary").json() == {"incoming": 0, "offers": 0, "to_confirm": 1, "total": 1}      # y luego debe confirmar
    m.cookies.clear()
    assert m.get("/api/help/summary").status_code == 401


# ---------------------------------------------------------------- administración

def test_admin_sees_pairs_and_flags_and_can_revoke_points(engine, store):
    validate(engine, 13, 3, NOW - timedelta(days=10))
    a, m, rid = ask(engine, store, project=1, projects=[1, 2, 3])
    thank(a, rid)
    confirm(m)
    rid2 = post(a, "/api/help/requests", project_id=2, message=MSG + " 2").json()["id"]
    post(m, f"/api/help/requests/{rid2}/offer")
    thank(a, rid2)
    confirm(m)
    validate(engine, 15, 1, NOW + timedelta(days=3))
    validate(engine, 15, 2, NOW + timedelta(days=3))
    assert points_of(m)["verified"] == 2

    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    ov = admin.get("/api/admin/help/points").json()
    assert ov["mentors"][0]["login"] == "u13" and ov["mentors"][0]["verified"] == 2 and ov["mentors"][0]["askers"] == 1
    assert "pareja repetida" in ov["mentors"][0]["flags"]
    assert {(r["mentor"], r["asker"], r["status"]) for r in ov["recent"]} == {("u13", "u15", "cuenta")}
    tid = ov["recent"][0]["id"]
    assert post(admin, f"/api/admin/help/thanks/{tid}/revoke").json() == {"id": tid, "revoked": True}
    assert points_of(m)["verified"] == 1
    assert post(admin, "/api/admin/help/thanks/999/revoke").status_code == 404
    assert {r["status"] for r in admin.get("/api/admin/help/points").json()["recent"]} == {"cuenta", "anulado"}


def test_only_admins_can_see_or_revoke(engine, store):
    a, m, rid = ask(engine, store)
    thank(a, rid)
    for who in (a, m):
        assert who.get("/api/admin/help/points").status_code == 403
        assert post(who, "/api/admin/help/thanks/1/revoke").status_code == 403
    a.cookies.clear()
    assert a.get("/api/admin/help/points").status_code == 401


def test_a_revoked_thanks_still_blocks_thanking_again_for_that_project(engine, store):
    a, m, rid = ask(engine, store)
    thank(a, rid)
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    tid = admin.get("/api/admin/help/points").json()["recent"][0]["id"]
    post(admin, f"/api/admin/help/thanks/{tid}/revoke")
    rid2 = post(a, "/api/help/requests", project_id=1, message=MSG + " otra").json()["id"]
    post(m, f"/api/help/requests/{rid2}/offer")
    assert thank(a, rid2).status_code == 422


# ---------------------------------------------------------------- borrado y retención

def test_deleting_my_data_keeps_verified_points_anonymous_and_drops_the_rest(engine, store):
    a, m = full_flow(engine, store)
    assert points_of(m)["verified"] == 1
    assert post(a, "/api/me/delete").json() == {"deleted": True}
    with Session(store) as db:
        row = db.query(MentorThanks).one()
        assert row.asker_uid < 0 and row.verified is True                             # el mentor conserva su punto, sin saber de quién
    assert points_of(m)["verified"] == 1


def test_deleting_my_data_drops_pending_thanks_given_all_received_and_my_offers(engine, store):
    a, m, rid = ask(engine, store)
    thank(a, rid)
    post(a, "/api/me/delete")
    with Session(store) as db:
        assert db.query(MentorThanks).count() == 0                                    # pendiente: se borra con quien agradeció
    a, m, rid = ask(engine, store, asker=16)
    post(m, "/api/me/delete")
    with Session(store) as db:
        assert db.query(HelpOffer).count() == 0 and db.query(MentorThanks).count() == 0
    a, m, rid = ask(engine, store, asker=12, mentor=14, project=3)
    post(a, "/api/me/delete")
    with Session(store) as db:
        assert db.query(HelpOffer).count() == 0                                       # las ofertas a mi petición se van con ella


def test_unfinished_thanks_expire_after_a_year_and_orphan_offers_are_purged(engine, store):
    a, m, rid = ask(engine, store)
    thank(a, rid)
    with Session(store) as db:
        db.query(MentorThanks).update({"created_at": NOW - timedelta(days=400)})
        db.add(HelpOffer(request_id=4242, mentor_uid=13, created_at=NOW))             # oferta de una petición que ya no existe
        db.commit()
        purge(db)
        assert db.query(MentorThanks).count() == 0 and db.query(HelpOffer).count() == 0
