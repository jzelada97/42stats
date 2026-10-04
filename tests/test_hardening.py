"""Hallazgos de la revisión de seguridad: sesión revocable, un intento por state, borrado de datos, texto y enlaces tramposos."""
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from stats42 import auth as authmod
from stats42.db import HelpRequest, LearningResource, MentorOffer, UserSession, UserSetting
from stats42.helpboard import MAX_MARKS, clean_text, purge, validate_url

from test_auth import CFG, login, make_client
from test_auth import engine as auth_engine  # noqa: F401
from test_helpboard import ADMIN_CFG, GOOD, NOW, engine, post, store, user  # noqa: F401


# ---------------------------------------------------------------- sesión

def test_session_cookie_dies_with_the_browser_and_logout_revokes_a_copied_cookie(auth_engine):
    c, _ = make_client(auth_engine)
    r = login(c)
    cookie = [h for h in r.headers.get_list("set-cookie") if h.startswith("stats42_session=")][0].lower()
    assert "max-age" not in cookie and "expires" not in cookie and "httponly" in cookie       # cookie de sesión del navegador
    stolen = c.cookies.get("stats42_session")
    assert c.get("/api/me").status_code != 401
    assert c.get("/auth/logout").status_code == 302

    attacker = TestClient(c.app, follow_redirects=False, base_url="https://42madrid.example")
    attacker.cookies.set("stats42_session", stolen)                                              # la misma cookie, copiada antes de salir
    assert attacker.get("/api/me").status_code == 401 and attacker.get("/me").status_code == 302
    assert attacker.post("/api/help/offer", json={"active": False}, headers={"Origin": "https://42madrid.example"}).status_code == 401


def test_session_without_a_server_side_record_is_worthless(auth_engine):
    c, _ = make_client(auth_engine)
    login(c)
    with Session(c.settings_engine) as db:
        db.query(UserSession).delete()
        db.commit()
    assert c.get("/api/me").status_code == 401


def test_a_cookie_with_the_right_signature_but_for_another_user_is_refused(auth_engine):
    c, _ = make_client(auth_engine)
    login(c)
    with Session(c.settings_engine) as db:
        db.query(UserSession).update({"user_id": 999})
        db.commit()
    assert c.get("/api/session").json()["logged_in"] is False


def test_expired_sessions_are_purged_when_someone_logs_in(auth_engine):
    c, _ = make_client(auth_engine)
    login(c)
    with Session(c.settings_engine) as db:
        db.query(UserSession).update({"created_at": NOW - timedelta(days=2)})
        db.commit()
    login(make_client(auth_engine, settings_engine=c.settings_engine)[0])
    with Session(c.settings_engine) as db:
        assert db.query(UserSession).count() == 1


def test_a_login_callback_can_only_be_used_once_per_state(auth_engine):
    c, seen = make_client(auth_engine)
    r = c.get("/auth/login")
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    assert c.get("/auth/callback", params={"code": "CODE", "state": state}).headers["location"] == "/me"
    again = c.get("/auth/callback", params={"code": "CODE", "state": state})                     # repetir el mismo callback
    assert again.headers["location"] == "/me"                                                    # ya tienes sesión: sigue, sin error
    fresh = TestClient(c.app, follow_redirects=False, base_url="https://42madrid.example")
    fresh.cookies.set(authmod.STATE_COOKIE, c.cookies.get(authmod.STATE_COOKIE) or "x")
    assert fresh.get("/auth/callback", params={"code": "CODE", "state": state}).headers["location"] == "/login?error=estado"


def test_a_repeated_callback_never_calls_42_twice_and_does_not_scare_a_logged_in_user(auth_engine):
    c, seen = make_client(auth_engine)
    state = parse_qs(urlparse(c.get("/auth/login").headers["location"]).query)["state"][0]
    c.get("/auth/callback", params={"code": "CODE", "state": state})
    first = dict(seen)
    for _ in range(3):                                                                           # atrás, recarga, doble clic...
        assert c.get("/auth/callback", params={"code": "CODE", "state": state}).headers["location"] == "/me"
    assert seen == first
    assert c.get("/login").headers["location"] == "/me"                                          # con sesión, /login lleva al panel


def test_the_login_failure_reasons_are_logged_without_secrets(auth_engine, caplog):
    import logging
    c, _ = make_client(auth_engine)
    with caplog.at_level(logging.INFO, logger="stats42.auth"):
        c.get("/auth/callback", params={"code": "SECRETO", "state": "x"})                        # sin cookie de estado
        c.cookies.set(authmod.STATE_COOKIE, "basura")
        c.get("/auth/callback", params={"code": "SECRETO", "state": "x"})                        # cookie manipulada
    assert "no envió la cookie de estado" in caplog.text and "caducada" in caplog.text and "SECRETO" not in caplog.text


# ---------------------------------------------------------------- borrar mis datos y retención

def test_delete_my_data_wipes_everything_the_site_keeps_and_ends_the_session(engine, store):
    c = user(engine, store, 13)
    post(c, "/api/help/offer", active=True, note="explico punteros", project_ids=[1])
    post(c, "/api/help/resources", **GOOD)
    post(c, "/api/me/settings", deadline=(NOW + timedelta(days=100)).date().isoformat())
    other = user(engine, store, 15)
    post(other, "/api/help/requests", project_id=1, message="No entiendo cómo reservar memoria con malloc")

    assert post(c, "/api/me/delete").json() == {"deleted": True}
    with Session(store) as db:
        assert db.query(MentorOffer).filter_by(user_id=13).count() == 0
        assert db.query(LearningResource).filter_by(submitted_by=13).count() == 0
        assert db.query(UserSetting).filter_by(user_id=13).count() == 0
        assert db.query(UserSession).filter_by(user_id=13).count() == 0
        assert db.query(HelpRequest).filter_by(user_id=15).count() == 1                          # lo de otros no se toca
    assert c.get("/api/me").status_code == 401


def test_deleting_my_data_keeps_approved_resources_but_removes_my_name(engine, store):
    c = user(engine, store, 13)
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    rid = post(c, "/api/help/resources", **GOOD).json()["id"]
    post(admin, f"/api/admin/help/resources/{rid}/approve")
    post(c, "/api/me/delete")
    with Session(store) as db:
        r = db.get(LearningResource, rid)
        assert r.status == "approved" and r.submitted_by == 0 and r.submitted_login == ""


def test_delete_my_data_needs_a_session_and_the_right_origin(engine, store):
    assert TestClient(user(engine, store, 13).app, base_url="https://42madrid.example").post("/api/me/delete", json={}).status_code == 401
    assert user(engine, store, 13).post("/api/me/delete", json={}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_purge_drops_old_closed_and_rejected_text(engine, store):
    old = NOW - timedelta(days=45)
    user(engine, store, 13)                                                                  # crea las tablas de la base escribible
    with Session(store) as db:
        db.add_all([
            HelpRequest(user_id=15, login="u15", project_id=1, message="caducada hace mucho tiempo", status="open", created_at=old),
            HelpRequest(user_id=16, login="u16", project_id=1, message="cerrada sin borrar por si acaso", status="closed", created_at=NOW),
            HelpRequest(user_id=12, login="u12", project_id=1, message="viva y reciente, se queda aquí", status="open", created_at=NOW),
            LearningResource(project_id=1, title="viejo", url="https://a.example.com/x", kind="guía", submitted_by=15, submitted_login="u15",
                             status="rejected", created_at=old),
            LearningResource(project_id=1, title="reciente", url="https://b.example.com/x", kind="guía", submitted_by=15, submitted_login="u15",
                             status="rejected", created_at=NOW),
        ])
        db.commit()
        purge(db)
        assert [r.login for r in db.query(HelpRequest)] == ["u12"]
        assert [r.title for r in db.query(LearningResource)] == ["reciente"]


# ---------------------------------------------------------------- texto invisible y enlaces tramposos

@pytest.mark.parametrize("text", ["ㅤ" * 12, "ᅟ" * 12, "⠀" * 12, "­" * 12, "\U000e0041" * 12, "؜" * 12, "‍" * 12])
def test_invisible_filler_cannot_pass_the_minimum_length(text):
    with pytest.raises(ValueError):
        clean_text(text, min_len=10, max_len=280, field="Mensaje")


def test_zalgo_marks_are_capped():
    out = clean_text("a" + "́" * 130 + "b", min_len=1, max_len=280, field="x")
    assert out == "a" + "́" * MAX_MARKS + "b"
    assert clean_text("canción ñandú", min_len=1, max_len=50, field="x") == "canción ñandú"       # los acentos normales siguen valiendo


@pytest.mark.parametrize("text", ["mi solución en github.com/x/libft", "mira https://pastebin.com/abc", "www.algo.org te lo explica",
                                  "está en gitlab", "visita misitio.io para el código"])
def test_notes_and_requests_cannot_carry_links_or_code_sites(text):
    with pytest.raises(ValueError):
        clean_text(text, min_len=1, max_len=200, field="Nota")


@pytest.mark.parametrize("url", ["https://127.1/", "https://0x7f.1/", "https://0177.0.0.1/", "https://2130706433.0/",
                                 "https://evil.tk\\.docs.python.org/", "https://example.com\\@evil.tk/"])
def test_ip_tricks_and_backslashes_are_not_links(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_normal_links_still_work():
    assert validate_url("https://docs.python.org/3/library/re.html") == "https://docs.python.org/3/library/re.html"
    assert validate_url("https://xn--bcher-kva.example/x").startswith("https://xn--bcher-kva.example")


# ---------------------------------------------------------------- ids enormes

@pytest.mark.parametrize("path", ["/api/help/mentors?project_id=99999999999999999999", "/api/help/resources?project_id=99999999999999999999",
                                  "/api/help/mentors?project_id=0"])
def test_huge_or_zero_ids_are_422_not_500(engine, store, path):
    assert user(engine, store, 13).get(path).status_code == 422


def test_huge_ids_in_bodies_and_paths_are_422(engine, store):
    c = user(engine, store, 13)
    assert post(c, "/api/help/requests", project_id=99999999999999999999, message="una pregunta suficientemente larga").status_code == 422
    assert post(c, "/api/help/requests/99999999999999999999/close").status_code == 422
    assert post(c, "/api/help/offer", active=True, project_ids=[99999999999999999999]).status_code == 422


# ---------------------------------------------------------------- consumo

def test_reads_are_throttled_per_student_not_per_ip(engine, store):
    c = user(engine, store, 13)
    codes = [c.get("/api/help/overview").status_code for _ in range(125)]
    assert codes[0] == 200 and codes[-1] == 429
    assert user(engine, store, 14).get("/api/help/overview").status_code == 200                # otro alumno no se ve afectado


def test_me_is_throttled_per_student(auth_engine):
    c, _ = make_client(auth_engine)
    login(c)
    codes = [c.get("/api/me").status_code for _ in range(62)]
    assert 429 in codes and codes.index(429) >= 59
