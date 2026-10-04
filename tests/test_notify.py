"""Avisos por correo: opt-in explícito (pasando por 42), plantillas fijas, topes y nada que se pueda usar como altavoz."""
import smtplib
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from stats42 import mailer as mailmod
from stats42 import notify as notifymod
from stats42.cli import app as cli_app
from stats42.db import MailPref
from stats42.mailer import SmtpConfig, SmtpMailer, mask_email, valid_email
from stats42.notify import Notifier

from test_auth import make_client
from test_helpboard import NOW, engine, store  # noqa: F401
from test_points import MSG, confirm, thank

HOSTILE = '<script>alert(1)</script> <img src=x onerror=alert(2)>'


class FakeMailer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, to, subject, body):
        if self.fail:
            raise RuntimeError("SMTP caído")
        self.sent.append((to, subject, body))


def person(engine, store, uid, mailer, email=None, notify=False):
    me = {"id": uid, "login": f"u{uid}", "usual_first_name": f"N{uid}"}
    if email is not None:
        me["email"] = email
    c, seen = make_client(engine, settings_engine=store, app_kw={"mailer": mailer, "notify_sync": True}, me=me)
    r = c.get("/auth/login", params={"purpose": "notify"} if notify else {})
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    return c, c.get("/auth/callback", params={"code": "CODE", "state": state})


def prefs(store):
    with Session(store) as db:
        return {p.user_id: p.email for p in db.query(MailPref)}


def post(c, path, **body):
    return c.post(path, json=body, headers={"Origin": "https://42madrid.example"})


# ---------------------------------------------------------------- validación y SMTP

@pytest.mark.parametrize("email,ok", [("ana@student.42madrid.com", True), ("a.b+c@x.es", True), ("", False), ("sin-arroba", False), ("a@b", False),
                                      ("a@b.com\nBcc: x@y.com", False), ("a b@c.com", False), ("a@b.com, c@d.com", False), ("<a@b.com>", False), (None, False), (5, False),
                                      ("a" * 250 + "@b.com", False)])
def test_only_plain_single_addresses_are_accepted(email, ok):
    assert valid_email(email) is ok


def test_masking_shows_only_the_first_letter():
    assert mask_email("ana@student.42madrid.com") == "a***@student.42madrid.com"


def test_smtp_sends_over_starttls_with_login_and_marks_the_mail_as_automatic(monkeypatch):
    log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            log.append(("conn", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            log.append("tls")

        def login(self, u, p):
            log.append(("login", u))

        def send_message(self, msg):
            log.append(("msg", msg["To"], msg["Subject"], msg["Auto-Submitted"], msg["From"], msg.get_content()))
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    SmtpMailer(SmtpConfig("smtp.example.com", 587, "user", "pw", "42stats <avisos@zelada.es>")).send("ana@x.es", "Hola", "cuerpo")
    assert log[0] == ("conn", "smtp.example.com", 587, 15) and log[1:3] == ["tls", ("login", "user")]
    assert log[3][1:5] == ("ana@x.es", "Hola", "auto-generated", "42stats <avisos@zelada.es>") and "cuerpo" in log[3][5]


def test_header_injection_is_impossible(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: pytest.fail("no debe conectar"))
    m = SmtpMailer(SmtpConfig("h", 587, "", "", "a@b.es"))
    with pytest.raises(ValueError):
        m.send("x@y.com\nBcc: otro@z.com", "s", "b")
    with pytest.raises(ValueError):
        m.send("x@y.com", "asunto\nBcc: otro@z.com", "b")


def test_without_smtp_settings_there_is_no_mailer(monkeypatch):
    for k in ("FT_SMTP_HOST", "FT_MAIL_FROM"):
        monkeypatch.delenv(k, raising=False)
    assert mailmod.from_env() is None
    monkeypatch.setenv("FT_SMTP_HOST", "h")
    assert mailmod.from_env() is None                                               # falta el remitente
    monkeypatch.setenv("FT_MAIL_FROM", "a@b.es")
    assert isinstance(mailmod.from_env(), SmtpMailer)


# ---------------------------------------------------------------- opt-in

def test_without_a_mailer_the_site_offers_no_notifications_and_stores_no_email(engine, store):
    c, r = person(engine, store, 15, None, email="ana@student.42madrid.com", notify=True)
    assert r.headers["location"] == "/me"                                            # el propósito se ignora
    assert c.get("/api/me/notify").json() == {"available": False, "enabled": False, "email": None}
    assert prefs(store) == {}


def test_a_normal_login_never_stores_the_email_even_if_42_sends_it(engine, store):
    c, r = person(engine, store, 15, FakeMailer(), email="ana@student.42madrid.com")
    assert r.headers["location"] == "/me" and prefs(store) == {}
    assert c.get("/api/me/notify").json() == {"available": True, "enabled": False, "email": None}


def test_activating_goes_through_42_and_stores_the_email_only_then(engine, store):
    c, r = person(engine, store, 15, FakeMailer(), email="ana@student.42madrid.com", notify=True)
    assert r.headers["location"] == "/ayuda?avisos=ok#avisos"
    assert prefs(store) == {15: "ana@student.42madrid.com"}
    assert c.get("/api/me/notify").json() == {"available": True, "enabled": True, "email": "a***@student.42madrid.com"}
    for path in ("/api/me/notify", "/api/help/overview", "/api/me"):                   # la dirección entera no sale por ninguna API
        assert "ana@student.42madrid.com" not in c.get(path).text


@pytest.mark.parametrize("email", [None, "", "no-es-un-correo", "a@b", "x@y.com\nBcc: z@w.com"])
def test_a_missing_or_odd_address_is_reported_and_not_stored(engine, store, email):
    c, r = person(engine, store, 15, FakeMailer(), email=email, notify=True)
    assert r.headers["location"] == "/ayuda?avisos=sin-correo#avisos" and prefs(store) == {}
    assert c.get("/api/me").status_code != 401                                        # el login funciona igualmente


def test_the_purpose_cannot_be_forged_in_the_url_of_the_callback(engine, store):
    mailer = FakeMailer()
    c, _ = make_client(engine, settings_engine=store, app_kw={"mailer": mailer, "notify_sync": True},
                       me={"id": 15, "login": "u15", "usual_first_name": "N", "email": "ana@student.42madrid.com"})
    state = parse_qs(urlparse(c.get("/auth/login").headers["location"]).query)["state"][0]
    r = c.get("/auth/callback", params={"code": "CODE", "state": state, "purpose": "notify"})      # el propósito solo vale si va en la cookie firmada
    assert r.headers["location"] == "/me" and prefs(store) == {}


def test_disabling_deletes_the_address_and_needs_a_session_and_origin(engine, store):
    c, _ = person(engine, store, 15, FakeMailer(), email="ana@student.42madrid.com", notify=True)
    assert c.post("/api/me/notify/disable", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert post(c, "/api/me/notify/disable").json() == {"available": True, "enabled": False, "email": None}
    assert prefs(store) == {}
    c.cookies.clear()
    assert post(c, "/api/me/notify/disable").status_code == 401 and c.get("/api/me/notify").status_code == 401


def test_deleting_my_data_deletes_the_address_too(engine, store):
    c, _ = person(engine, store, 15, FakeMailer(), email="ana@student.42madrid.com", notify=True)
    assert post(c, "/api/me/delete").json() == {"deleted": True}
    assert prefs(store) == {}


# ---------------------------------------------------------------- avisos de la conexión mentor-alumno

def scenario(engine, store, mailer, asker_notify=True, mentor_notify=False):
    mentor, _ = person(engine, store, 13, mailer, email="mentor@student.42madrid.com", notify=mentor_notify)
    post(mentor, "/api/help/offer", active=True, project_ids=[1])
    asker, _ = person(engine, store, 15, mailer, email="asker@student.42madrid.com", notify=asker_notify)
    rid = post(asker, "/api/help/requests", project_id=1, message=MSG + " " + HOSTILE).json()["id"]
    return asker, mentor, rid


def test_quiero_ayudar_emails_the_asker_with_a_fixed_template(engine, store):
    mailer = FakeMailer()
    asker, mentor, rid = scenario(engine, store, mailer)
    assert post(mentor, f"/api/help/requests/{rid}/offer").status_code == 200
    (to, subject, body), = mailer.sent
    assert to == "asker@student.42madrid.com" and subject == "u13 quiere ayudarte con libft"
    assert "https://profile.intra.42.fr/users/u13" in body and "/ayuda#pedir" in body and "/ayuda#avisos" in body
    assert "cuando quieras" in body and "nunca pasando código" in body
    assert HOSTILE not in body and "<script>" not in body and "onerror" not in body and MSG not in body    # nada escrito por alumnos
    assert "mentor@student.42madrid.com" not in body                                                  # ni la dirección del mentor


def test_pressing_quiero_ayudar_again_does_not_send_another_email(engine, store):
    mailer = FakeMailer()
    asker, mentor, rid = scenario(engine, store, mailer)
    for _ in range(3):
        post(mentor, f"/api/help/requests/{rid}/offer")
    assert len(mailer.sent) == 1
    post(mentor, f"/api/help/requests/{rid}/withdraw")
    post(mentor, f"/api/help/requests/{rid}/offer")                                                  # retirar y volver a ofrecerse sí es otra oferta
    assert len(mailer.sent) == 2


def test_nobody_is_emailed_unless_they_activated_the_notifications(engine, store):
    mailer = FakeMailer()
    asker, mentor, rid = scenario(engine, store, mailer, asker_notify=False)
    post(mentor, f"/api/help/requests/{rid}/offer")
    assert mailer.sent == []


def test_the_mentor_is_emailed_when_he_is_thanked_to_confirm(engine, store):
    mailer = FakeMailer()
    asker, mentor, rid = scenario(engine, store, mailer, asker_notify=False, mentor_notify=True)
    post(mentor, f"/api/help/requests/{rid}/offer")
    assert thank(asker, rid).status_code == 200
    (to, subject, body), = mailer.sent
    assert to == "mentor@student.42madrid.com" and "confírmala" in subject and "libft" in body and "/ayuda#peticiones" in body
    assert "u15" not in body and "asker@" not in body                                                # no se revela quién agradeció
    assert confirm(mentor).status_code == 200


def test_a_failing_mail_server_never_breaks_the_action(engine, store):
    mailer = FakeMailer(fail=True)
    asker, mentor, rid = scenario(engine, store, mailer)
    assert post(mentor, f"/api/help/requests/{rid}/offer").status_code == 200
    assert asker.get("/api/help/overview").json()["requests"][0]["responders"][0]["login"] == "u13"


def test_daily_cap_per_recipient(engine, store, monkeypatch):
    monkeypatch.setattr(notifymod, "DAILY_CAP", 1)
    mailer = FakeMailer()
    asker, mentor, rid = scenario(engine, store, mailer)
    post(user_offer(engine, store, mailer, 14), f"/api/help/requests/{rid}/offer")
    post(mentor, f"/api/help/requests/{rid}/offer")
    assert len(mailer.sent) == 1                                                                     # el segundo aviso del día no sale
    with Session(store) as db:
        pref = db.get(MailPref, 15)
        pref.sent_day = date.today() - timedelta(days=2)                                             # al día siguiente el contador se reinicia
        db.commit()
    post(mentor, f"/api/help/requests/{rid}/withdraw")
    post(mentor, f"/api/help/requests/{rid}/offer")
    assert len(mailer.sent) == 2


def user_offer(engine, store, mailer, uid):
    c, _ = person(engine, store, uid, mailer, email=f"m{uid}@student.42madrid.com")
    post(c, "/api/help/offer", active=True, project_ids=[1])
    return c


# ---------------------------------------------------------------- resumen diario

def digest_notifier(engine, store, mailer):
    return Notifier(lambda: store, engine, mailer, "https://42madrid.example", sync=True)


def test_the_daily_digest_goes_only_to_opted_in_mentors_with_unanswered_requests(engine, store):
    mailer = FakeMailer()
    asker, mentor, rid = scenario(engine, store, mailer, asker_notify=False, mentor_notify=True)
    other, _ = person(engine, store, 14, mailer, email="otro@student.42madrid.com")               # mentor de libft sin avisos activados
    post(other, "/api/help/offer", active=True, project_ids=[1])
    n = digest_notifier(engine, store, mailer)
    assert n.digest() == 1
    (to, subject, body), = mailer.sent
    assert to == "mentor@student.42madrid.com" and "libft: 1" in body and "/ayuda#peticiones" in body
    assert "u15" not in body and HOSTILE not in body and MSG not in body                            # solo proyectos y cifras
    assert n.digest() == 0                                                                           # no se repite el mismo día
    with Session(store) as db:
        assert db.get(MailPref, 13).last_digest == date.today()


def test_no_digest_when_the_mentor_already_offered_or_nothing_is_waiting(engine, store):
    mailer = FakeMailer()
    asker, mentor, rid = scenario(engine, store, mailer, asker_notify=False, mentor_notify=True)
    post(mentor, f"/api/help/requests/{rid}/offer")                                                  # ya respondió
    assert digest_notifier(engine, store, mailer).digest() == 0
    post(asker, f"/api/help/requests/{rid}/close")                                                   # y ya no hay nada abierto
    assert digest_notifier(engine, store, mailer).digest() == 0 and mailer.sent == []


def test_digest_is_off_without_a_mailer(engine, store):
    asker, mentor, rid = scenario(engine, store, FakeMailer(), asker_notify=False, mentor_notify=True)
    assert Notifier(lambda: store, engine, None, "https://x.example", sync=True).digest() == 0


def test_cli_notify_reports_when_it_is_not_configured(monkeypatch):
    for k in ("FT_SMTP_HOST", "FT_MAIL_FROM"):
        monkeypatch.delenv(k, raising=False)
    r = CliRunner().invoke(cli_app, ["notify"])
    assert r.exit_code == 0 and "no están configurados" in r.output


def test_cli_notify_sends_the_digest(engine, store, tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    mailer = FakeMailer()
    asker, mentor, rid = scenario(engine, store, mailer, asker_notify=False, mentor_notify=True)
    mailer.sent.clear()
    # la CLI abre las bases por URL: se vuelcan las de prueba a ficheros
    campus, settings = tmp_path / "campus.db", tmp_path / "settings.db"
    for src, dst in ((engine, campus), (store, settings)):
        with src.connect() as a, create_engine(f"sqlite:///{dst}").connect() as b:
            a.connection.backup(b.connection.connection)
    monkeypatch.setenv("FT_DATABASE_URL", f"sqlite:///{campus}")
    monkeypatch.setenv("FT_SETTINGS_DATABASE_URL", f"sqlite:///{settings}")
    monkeypatch.setenv("FT_BASE_URL", "https://42madrid.example")
    monkeypatch.setattr(mailmod, "from_env", lambda: mailer)
    r = CliRunner().invoke(cli_app, ["notify"])
    assert r.exit_code == 0 and "Resúmenes enviados: 1" in r.output and len(mailer.sent) == 1


def test_logs_never_contain_the_address_or_the_text(engine, store, caplog):
    import logging
    asker, mentor, rid = scenario(engine, store, FakeMailer(fail=True))
    with caplog.at_level(logging.INFO, logger="stats42.mail"):
        post(mentor, f"/api/help/requests/{rid}/offer")
    assert "asker@student.42madrid.com" not in caplog.text and "SMTP caído" not in caplog.text and "RuntimeError" in caplog.text
    assert NOW  # silencia el aviso de importación sin usar
