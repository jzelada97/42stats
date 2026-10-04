import json
from urllib.parse import parse_qs, parse_qsl, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from stats42 import auth as authmod
from stats42 import probe
from stats42.api import create_app
from stats42.client import FortyTwoClient
from stats42.db import CursusUser, User, init_db

CFG = authmod.AuthConfig(uid="the-uid", secret="the-secret", session_secret="session-secret-for-tests",
                         base_url="https://42madrid.example")


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    factory = init_db(eng)
    with factory() as s:
        s.add(User(id=12, login="u12", kind="student", pool_year="2025", pool_month="may", active=True, alumni=False, staff=False,
                   correction_point=3))
        s.add(CursusUser(id=1, user_id=12, cursus_id=21, level=3.0))
        s.commit()
    return eng


def fake_42(me=None, token_status=200):
    """API de 42 simulada: intercambio de código y /v2/me."""
    seen = {"token_request": None}
    me = me or {"id": 12, "login": "u12", "usual_first_name": "Ada"}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/oauth/token":
            seen["token_request"] = dict(parse_qsl(req.content.decode()))
            return httpx.Response(token_status, json={"access_token": "tok-user"} if token_status == 200 else {"error": "invalid_grant"})
        if req.url.path == "/v2/me":
            assert req.headers["authorization"] == "Bearer tok-user"
            return httpx.Response(200, json=me)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def make_client(engine, cfg=CFG, **kw):
    http, seen = fake_42(**kw)
    app = create_app(engine, 21, auth=cfg, http=http)
    return TestClient(app, follow_redirects=False, base_url="https://42madrid.example"), seen


def login(client):
    r = client.get("/auth/login")
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    return client.get("/auth/callback", params={"code": "CODE", "state": state})


def test_login_redirects_to_42_with_state_and_hardened_cookie(engine):
    c, _ = make_client(engine)
    r = c.get("/auth/login")
    assert r.status_code == 302
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == authmod.AUTHORIZE_URL
    assert q["client_id"] == ["the-uid"] and q["response_type"] == ["code"] and q["scope"] == ["public"]
    assert q["redirect_uri"] == ["https://42madrid.example/auth/callback"] and len(q["state"][0]) >= 20
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie


def test_login_unconfigured_returns_503_instead_of_redirecting(engine):
    c, _ = make_client(engine, cfg=authmod.AuthConfig())
    assert c.get("/auth/login").status_code == 503
    assert c.get("/api/session").json() == {"login_enabled": False, "logged_in": False, "login": None, "name": None}


def test_successful_login_creates_session_without_storing_the_token(engine):
    c, seen = make_client(engine)
    r = login(c)
    assert r.status_code == 302 and r.headers["location"] == "/me"
    assert seen["token_request"]["grant_type"] == "authorization_code" and seen["token_request"]["code"] == "CODE"
    assert seen["token_request"]["redirect_uri"] == "https://42madrid.example/auth/callback"
    raw = c.cookies.get(authmod.SESSION_COOKIE)
    data = URLSafeTimedSerializer(CFG.session_secret, salt="session").loads(raw)
    assert set(data) == {"uid", "login", "name"} and "tok-user" not in raw and "tok-user" not in json.dumps(data)
    assert c.get("/api/session").json() == {"login_enabled": True, "logged_in": True, "login": "u12", "name": "Ada"}


def test_logged_in_user_gets_own_analysis_and_page(engine):
    c, _ = make_client(engine)
    login(c)
    r = c.get("/api/me")
    assert r.status_code == 200 and r.json()["login"] == "u12" and r.json()["status"]["key"] in ("normal", "attention", "great")
    assert r.headers["cache-control"] == "no-store"
    assert c.get("/me").status_code == 200


def test_anonymous_visitors_get_401_and_are_redirected_to_login(engine):
    c, _ = make_client(engine)
    assert c.get("/api/me").status_code == 401
    r = c.get("/me")
    assert r.status_code == 302 and r.headers["location"] == "/login"
    assert c.get("/login").status_code == 200


@pytest.mark.parametrize("params,cookie_state", [
    ({"code": "CODE", "state": "otro-valor"}, True),   # state distinto al de la cookie
    ({"code": "CODE", "state": "x"}, False),           # sin cookie de state (ataque CSRF)
    ({"state": "x"}, True),                            # sin código
])
def test_callback_rejects_bad_state(engine, params, cookie_state):
    c, _ = make_client(engine)
    if cookie_state:
        c.get("/auth/login")
    r = c.get("/auth/callback", params=params)
    assert r.status_code == 302 and r.headers["location"] == "/login?error=estado"
    assert authmod.SESSION_COOKIE not in c.cookies


def test_callback_user_cancelled_or_42_rejects_code(engine):
    c, _ = make_client(engine)
    assert c.get("/auth/callback", params={"error": "access_denied"}).headers["location"] == "/login?error=denegado"
    c2, _ = make_client(engine, token_status=400)
    assert login(c2).headers["location"] == "/login?error=intercambio"
    assert authmod.SESSION_COOKIE not in c2.cookies


def test_user_not_in_campus_data_cannot_log_in(engine):
    c, _ = make_client(engine, me={"id": 777, "login": "stranger"})
    r = login(c)
    assert r.headers["location"] == "/login?error=fuera-de-campus" and authmod.SESSION_COOKIE not in c.cookies


def test_tampered_or_expired_session_is_treated_as_logged_out(engine, monkeypatch):
    c, _ = make_client(engine)
    login(c)
    good = c.cookies.get(authmod.SESSION_COOKIE)
    c.cookies.set(authmod.SESSION_COOKIE, good[:-3] + "xyz", domain="42madrid.example")
    assert c.get("/api/session").json()["logged_in"] is False
    c.cookies.set(authmod.SESSION_COOKIE, good, domain="42madrid.example")
    assert c.get("/api/session").json()["logged_in"] is True
    monkeypatch.setattr(authmod, "SESSION_TTL", -1)                        # ya caducada
    assert c.get("/api/session").json()["logged_in"] is False


def test_session_signed_with_another_secret_is_rejected(engine):
    c, _ = make_client(engine)
    forged = URLSafeTimedSerializer("otro-secreto", salt="session").dumps({"uid": 12, "login": "u12", "name": "x"})
    c.cookies.set(authmod.SESSION_COOKIE, forged, domain="42madrid.example")
    assert c.get("/api/me").status_code == 401


def test_logout_clears_the_session(engine):
    c, _ = make_client(engine)
    login(c)
    r = c.get("/auth/logout")
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert c.get("/api/session").json()["logged_in"] is False


def test_user_without_data_gets_404_not_someone_elses_data(engine):
    c, _ = make_client(engine)
    login(c)
    with Session(engine) as s:
        s.delete(s.get(User, 12))
        s.commit()
    assert c.get("/api/me").status_code == 404


# ---------------------------------------------------------------- sondeo para administradores

def user_and_app_clients(user_json, app_json):
    def user_handler(req):
        return httpx.Response(200, json=user_json)

    def app_handler(req):
        if req.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "app", "expires_in": 7200})
        return httpx.Response(200, json=app_json)

    return (httpx.Client(transport=httpx.MockTransport(user_handler)),
            FortyTwoClient("u", "s", min_interval=0, transport=httpx.MockTransport(app_handler)))


def test_probe_reports_extra_keys_visible_only_with_the_user_token():
    http, app = user_and_app_clients({"id": 12, "freeze_until": "2026-12-01", "a": {"b": 1}}, {"id": 12})
    res = probe.run_probe("tok", 12, http, app)
    me = next(x for x in res if x["endpoint"] == "/v2/me")
    assert me["user_token_status"] == 200 and me["app_token_status"] == 200
    assert {"freeze_until", "a", "a.b"} <= set(me["extra_keys_with_user_token"])
    assert "freeze_until" in me["keys_of_interest"]
    assert any(x["endpoint"].startswith("intrapy") for x in res)


def test_probe_is_written_only_for_admins_and_never_blocks_login(engine, tmp_path):
    http, _ = fake_42()
    user_http, app = user_and_app_clients({"id": 12}, {"id": 12})

    def combined(req):
        return http.send(req) if req.url.host == "api.intra.42.fr" and req.url.path in ("/oauth/token", "/v2/me") else user_http.send(req)

    shared = httpx.Client(transport=httpx.MockTransport(combined))
    cfg = authmod.AuthConfig(**{**CFG.__dict__, "admin_logins": frozenset({"u12"}), "probe_dir": str(tmp_path)})
    c = TestClient(create_app(engine, 21, auth=cfg, http=shared, app_client=lambda: app), follow_redirects=False,
                   base_url="https://42madrid.example")
    assert login(c).headers["location"] == "/me"
    assert (tmp_path / "probe-u12.json").exists()
    assert "tok-user" not in (tmp_path / "probe-u12.json").read_text()

    other = authmod.AuthConfig(**{**CFG.__dict__, "admin_logins": frozenset({"alguien"}), "probe_dir": str(tmp_path / "otro")})
    (tmp_path / "otro").mkdir()
    c2 = TestClient(create_app(engine, 21, auth=other, http=shared, app_client=lambda: app), follow_redirects=False,
                    base_url="https://42madrid.example")
    login(c2)
    assert not list((tmp_path / "otro").iterdir())      # un alumno normal no dispara el sondeo


def test_callback_also_works_on_the_site_root_when_only_the_domain_is_registered(engine):
    cfg = authmod.AuthConfig(**{**CFG.__dict__, "redirect_override": "https://42madrid.example"})
    c, seen = make_client(engine, cfg=cfg)
    r = c.get("/auth/login")
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["redirect_uri"] == ["https://42madrid.example"]           # la que hay registrada en 42, sin ruta
    r = c.get("/", params={"code": "CODE", "state": q["state"][0]})
    assert r.status_code == 302 and r.headers["location"] == "/me"
    assert seen["token_request"]["redirect_uri"] == "https://42madrid.example"   # mismo valor al canjear el código
    assert c.get("/api/session").json()["logged_in"] is True


def test_root_is_the_login_screen_for_visitors_and_sends_members_to_their_panel(engine):
    c, _ = make_client(engine)
    r = c.get("/")
    assert r.status_code == 200 and "Entrar con 42" in r.text and r.headers["cache-control"] == "no-store"
    assert "Resumen" not in r.text                                  # la portada ya no es el panel del campus
    assert c.get("/campus").status_code == 200 and "Cómo está el campus hoy" in c.get("/campus").text
    login(c)
    r = c.get("/")
    assert r.status_code == 302 and r.headers["location"] == "/me"   # con sesión, la portada lleva a su panel


def test_root_ignores_forged_oauth_params(engine):
    c, _ = make_client(engine)
    r = c.get("/", params={"code": "CODE", "state": "forjado"})          # sin cookie de state: se rechaza
    assert r.status_code == 302 and r.headers["location"] == "/login?error=estado"


def test_failed_exchange_logs_42s_reason_but_never_the_code_or_secret(engine, caplog):
    c, _ = make_client(engine, token_status=400)
    with caplog.at_level("WARNING", logger="stats42.auth"):
        r = login(c)
    assert r.headers["location"] == "/login?error=intercambio"
    text = " ".join(rec.getMessage() for rec in caplog.records)
    assert "400" in text and "invalid_grant" in text
    assert "CODE" not in text and CFG.secret not in text and "tok-user" not in text
