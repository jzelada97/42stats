"""Cabeceras, límites de entrada, ritmo de peticiones y logs: la superficie que un atacante puede tocar."""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from stats42 import api as api_module
from stats42 import auth as authmod
from stats42.api import MAX_BODY, RateLimiter, _clean, create_app
from stats42.db import CursusUser, User, init_db

from test_auth import CFG, login, make_client  # noqa: F401  (fixtures y ayudas del flujo de login)
from test_auth import engine  # noqa: F401


def test_page_headers_block_framing_base_tag_and_plugins(engine):
    c, _ = make_client(engine)
    r = c.get("/login")
    csp = r.headers["content-security-policy"]
    for directive in ("frame-ancestors 'none'", "base-uri 'none'", "object-src 'none'", "form-action 'self'", "script-src 'self'"):
        assert directive in csp, directive
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]          # los scripts nunca pueden ser inline
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["strict-transport-security"] == "max-age=31536000"            # sin includeSubDomains
    assert "camera=()" in r.headers["permissions-policy"] and r.headers["cross-origin-opener-policy"] == "same-origin"


def test_hsts_is_not_sent_when_the_site_is_not_https(engine):
    cfg = authmod.AuthConfig(**{**CFG.__dict__, "base_url": "http://localhost:8042"})
    c, _ = make_client(engine, cfg=cfg)
    assert "strict-transport-security" not in c.get("/login").headers


@pytest.mark.parametrize("headers,body,status", [
    ({"Content-Type": "text/plain"}, "deadline=2026-12-01", 415),                    # no es JSON
    ({"Content-Type": "application/x-www-form-urlencoded"}, "deadline=2026-12-01", 415),
    ({"Content-Type": "application/json"}, '{"deadline": null, "relleno": "' + "a" * (MAX_BODY + 10) + '"}', 413),
])
def test_post_bodies_must_be_small_json(engine, headers, body, status):
    c, _ = make_client(engine)
    login(c)
    r = c.post("/api/me/settings", content=body, headers={**headers, "Origin": "https://42madrid.example"})
    assert r.status_code == status


def test_unknown_json_fields_and_sql_like_strings_never_reach_storage(engine):
    c, _ = make_client(engine)
    login(c)
    r = c.post("/api/me/settings", json={"deadline": "2026-12-01'; DROP TABLE user_settings;--"}, headers={"Origin": "https://42madrid.example"})
    assert r.status_code == 422                                                       # solo se aceptan fechas reales
    r = c.post("/api/me/settings", json={"deadline": "2026-12-01", "user_id": 13, "is_admin": True}, headers={"Origin": "https://42madrid.example"})
    assert r.status_code == 200 and set(r.json()) == {"deadline", "freeze_until"}      # campos extra se ignoran: no se puede elegir el id


def test_settings_writes_are_rate_limited_per_user(engine, monkeypatch):
    c, _ = make_client(engine)
    login(c)
    codes = [c.post("/api/me/settings", json={"deadline": "2026-12-01"}, headers={"Origin": "https://42madrid.example"}).status_code
             for _ in range(22)]
    assert codes[:20] == [200] * 20 and codes[20:] == [429, 429]
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + 61)                          # pasa la ventana: se puede volver a escribir
    assert c.post("/api/me/settings", json={"deadline": "2026-12-01"}, headers={"Origin": "https://42madrid.example"}).status_code == 200


def test_one_student_cannot_lock_the_campus_out_of_the_login_page(engine):
    """El campus sale por una sola IP: /auth/login no llama a 42, así que no se limita y nadie puede agotarlo para los demás."""
    c, _ = make_client(engine)
    assert all(c.get("/auth/login").headers["location"].startswith("https://api.intra.42.fr/oauth/authorize") for _ in range(100))
    assert login(c).headers["location"] == "/me"


def test_exchanges_with_42_are_capped_globally_to_protect_the_app_quota(engine):
    c, _ = make_client(engine)
    results = [login(c).headers["location"] for _ in range(42)]
    assert results[0] == "/me" and results[-1] == "/login?error=limite"


def test_rate_limiter_window_and_memory_are_bounded(monkeypatch):
    rl = RateLimiter(2, 10)
    t = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: t[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a") and rl.allow("b")
    t[0] = 11
    assert rl.allow("a")
    for i in range(10_100):                                                           # muchas claves distintas no hacen crecer el dict sin tope
        rl.allow(f"k{i}")
        t[0] += 11
    assert len(rl.hits) <= 10_001


def test_log_text_from_outside_cannot_forge_log_lines():
    evil = 'invalid_grant\nINFO fake: login ok for admin\r\x1b[31m'
    cleaned = _clean(evil)
    assert "\n" not in cleaned and "\r" not in cleaned and "\x1b" not in cleaned and cleaned.startswith("invalid_grant")
    assert len(_clean("x" * 1000)) == 300


def test_hostile_text_in_api_data_is_returned_as_data_not_markup(engine):
    """La API devuelve JSON con application/json: aunque un nombre de proyecto lleve HTML, el navegador no lo interpreta."""
    from sqlalchemy.orm import Session

    from stats42.db import Project

    with Session(engine) as s:
        s.add(Project(id=1, name="<img src=x onerror=alert(1)>", slug="x"))
        s.commit()
    c, _ = make_client(engine)
    login(c)
    r = c.get("/api/projects")
    assert r.headers["content-type"].startswith("application/json") and r.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------- las estadísticas del campus solo para miembros

STATS_ENDPOINTS = ["overview", "levels", "cohorts", "blackholes", "milestones", "signups", "projects", "projects/monthly",
                   "attendance", "evaluations", "events"]


@pytest.mark.parametrize("path", STATS_ENDPOINTS)
def test_every_campus_stats_endpoint_requires_a_session(engine, path):
    c, _ = make_client(engine)
    r = c.get(f"/api/{path}")
    assert r.status_code == 401 and "Inicia sesión" in r.json()["detail"]
    login(c)
    assert c.get(f"/api/{path}").status_code == 200


def test_campus_page_redirects_visitors_and_opens_for_members(engine):
    c, _ = make_client(engine)
    r = c.get("/campus")
    assert r.status_code == 302 and r.headers["location"] == "/login" and r.headers["cache-control"] == "no-store"
    login(c)
    assert c.get("/campus").status_code == 200


def test_only_login_health_and_static_assets_are_public(engine):
    c, _ = make_client(engine)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/session").status_code == 200
    assert c.get("/login").status_code == 200 and c.get("/static/style.css").status_code == 200
    assert "/api/overview" not in c.get("/static/login.js").text           # la pantalla de login ya no enseña cifras del campus


def test_user_outside_the_campus_data_cannot_reach_any_stats(engine):
    c, _ = make_client(engine, me={"id": 777, "login": "stranger"})
    login(c)                                                                  # rechazado en el callback: no hay sesión
    assert c.get("/api/overview").status_code == 401 and c.get("/campus").status_code == 302


def test_search_engines_are_told_to_stay_away(engine):
    c, _ = make_client(engine)
    assert c.get("/robots.txt").text.strip().splitlines() == ["User-agent: *", "Disallow: /"]
    assert c.get("/login").headers["x-robots-tag"] == "noindex, nofollow"


def test_stats_responses_are_never_stored_by_the_browser(engine):
    c, _ = make_client(engine)
    login(c)
    assert c.get("/api/overview").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/api/me", "/api/help/overview", "/api/help/mentors?project_id=1", "/api/help/resources",
                                  "/api/session", "/api/overview", "/api/attendance", "/api/habits"])
def test_nothing_under_api_is_cached_by_the_browser(engine, path):
    """Regresión: /api/help/overview llevaba max-age=300 y en un ordenador compartido el siguiente alumno veía lo del anterior."""
    c, _ = make_client(engine)
    login(c)
    assert c.get(path).headers["cache-control"] == "no-store"


def test_only_the_health_check_may_be_cached(engine):
    c, _ = make_client(engine)
    assert "no-store" not in c.get("/api/health").headers.get("cache-control", "")
