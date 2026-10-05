from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from stats42 import auth as authmod
from stats42 import helpboard
from stats42.db import (CursusUser, HelpRequest, LearningResource, MentorOffer, MentorProject, Project, ProjectUser, ResourceProposal, User, init_db,
                        user_data_tables)
from stats42.helpboard import MAX_OFFER_PROJECTS, MAX_OPEN_REQUESTS, clean_text, validate_url

from test_auth import CFG, login, make_client

ORIGIN = {"Origin": "https://42madrid.example"}
ADMIN_CFG = authmod.AuthConfig(**{**CFG.__dict__, "admin_logins": frozenset({"u14"})})
NOW = datetime.now(timezone.utc)


@pytest.fixture
def engine():
    """Campus con 3 proyectos con actividad y 5 alumnos: u13 y u14 validaron libft; u12 solo libft; u15 y u16 nada."""
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    factory = init_db(eng)
    with factory() as s:
        s.add_all([Project(id=1, name="libft", slug="libft"), Project(id=2, name="get_next_line", slug="gnl"),
                   Project(id=3, name="ft_printf", slug="printf")])
        for uid, lvl in [(12, 3.0), (13, 6.0), (14, 8.5), (15, 1.0), (16, 2.0)]:
            s.add(User(id=uid, login=f"u{uid}", kind="student", pool_year="2025", pool_month="may", active=True, alumni=False, staff=False))
            s.add(CursusUser(id=uid, user_id=uid, cursus_id=21, level=lvl))
        k = 0
        for pid in (1, 2, 3):                      # actividad de relleno para que cada proyecto salga en los desplegables
            for _ in range(25):
                k += 1
                s.add(ProjectUser(id=k, user_id=99, project_id=pid, status="finished", validated=False, final_mark=40, cursus_ids=[21]))
        def validated(uid, pid, mark, days_ago):
            nonlocal k
            k += 1
            s.add(ProjectUser(id=k, user_id=uid, project_id=pid, status="finished", validated=True, final_mark=mark,
                              marked_at=NOW - timedelta(days=days_ago)))
        validated(12, 1, 100, 50)
        validated(13, 1, 110, 200)
        validated(13, 2, 90, 100)
        validated(14, 1, 125, 300)
        validated(14, 3, 80, 40)
        s.commit()
    return eng


@pytest.fixture
def store():
    return create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


def user(engine, store, uid, cfg=CFG):
    c, _ = make_client(engine, cfg=cfg, settings_engine=store, me={"id": uid, "login": f"u{uid}", "usual_first_name": f"N{uid}"})
    login(c)
    return c


def post(c, path, **body):
    return c.post(path, json=body, headers=ORIGIN)


# ---------------------------------------------------------------- validación pura

@pytest.mark.parametrize("url", [
    "http://example.com/guia", "javascript:alert(1)", "data:text/html,<script>1</script>", "ftp://example.com/x",
    "https://user:pass@example.com/", "https://example.com:8443/", "https://127.0.0.1/x", "https://[::1]/x", "https://10.0.0.5/x",
    "https://localhost/x", "https://intranet.local/x", "https://servicio.internal/x", "https://exámple.com/x",
    "https://example.com/a b", "https://example.com/\x00", "https://example.com/‮reverse", "https:///nada", "https://sinpunto/x",
    "//example.com/x", "", "   ", "https://example.com/" + "a" * 300,
])
def test_hostile_or_sloppy_links_are_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_valid_links_are_normalised():
    assert validate_url(" https://Docs.Python.org/3/tutorial/#frag ") == "https://Docs.Python.org/3/tutorial/"      # sin fragmento
    assert validate_url("https://example.com:443/x") == "https://example.com:443/x"


def test_clean_text_flattens_whitespace_and_strips_invisible_tricks():
    assert clean_text("hola\n\n  mundo\t!", min_len=1, max_len=50, field="x") == "hola mundo !"
    assert clean_text("ab‮cd​ef\x07", min_len=1, max_len=50, field="x") == "ab cd ef"        # bidi, ancho cero y control
    with pytest.raises(ValueError):
        clean_text("  ", min_len=3, max_len=10, field="Título")
    with pytest.raises(ValueError):
        clean_text("x" * 11, min_len=0, max_len=10, field="Nota")
    assert clean_text(None, min_len=0, max_len=10, field="Nota") == ""


# ---------------------------------------------------------------- acceso

@pytest.mark.parametrize("method,path", [
    ("get", "/api/help/overview"), ("get", "/api/help/mentors?project_id=1"), ("get", "/api/help/resources"),
    ("post", "/api/help/resources"), ("post", "/api/help/offer"), ("post", "/api/help/requests"), ("post", "/api/help/requests/1/close"),
])
def test_every_help_endpoint_requires_a_session(engine, store, method, path):
    c, _ = make_client(engine, settings_engine=store)
    r = c.request(method.upper(), path, json={} if method == "post" else None, headers=ORIGIN)
    assert r.status_code == 401


def test_admin_endpoints_reject_visitors_and_ordinary_students(engine, store):
    anon, _ = make_client(engine, settings_engine=store)
    assert anon.get("/api/admin/help/pending").status_code == 401
    c = user(engine, store, 12, cfg=ADMIN_CFG)
    assert c.get("/api/admin/help/pending").status_code == 403
    assert c.post("/api/admin/help/resources/1/approve", headers=ORIGIN, json={}).status_code == 403


# ---------------------------------------------------------------- mentoría

def test_only_validated_projects_can_be_offered(engine, store):
    c = user(engine, store, 15)                                          # u15 no ha validado nada
    r = post(c, "/api/help/offer", active=True, project_ids=[1])
    assert r.status_code == 422 and "validados" in r.json()["detail"]
    c12 = user(engine, store, 12)                                        # u12 solo validó libft
    assert post(c12, "/api/help/offer", active=True, project_ids=[2]).status_code == 422
    assert post(c12, "/api/help/offer", active=True, project_ids=[1], note="Explico punteros").json()["project_ids"] == [1]


def test_offer_validation_limits_and_cleaning(engine, store):
    c = user(engine, store, 13)
    assert post(c, "/api/help/offer", active=True, project_ids=[]).status_code == 422                 # activa sin proyectos
    assert post(c, "/api/help/offer", active=True, project_ids=list(range(100, 100 + MAX_OFFER_PROJECTS + 1))).status_code == 422
    assert post(c, "/api/help/offer", active=True, project_ids=[1], note="x" * 201).status_code == 422
    r = post(c, "/api/help/offer", active=True, project_ids=[1, 1, 2], note="Hola\n‮ mundo")
    assert r.status_code == 200 and r.json()["project_ids"] == [1, 2] and r.json()["note"] == "Hola mundo"
    assert post(c, "/api/help/offer", active=False, project_ids=[]).status_code == 200                # desactivar no exige proyectos
    assert c.get("/api/help/overview").json()["offer"]["active"] is False


def test_offer_replaces_the_previous_project_list(engine, store):
    c = user(engine, store, 13)
    post(c, "/api/help/offer", active=True, project_ids=[1, 2])
    post(c, "/api/help/offer", active=True, project_ids=[2])
    with Session(store) as db:
        assert [p for (p,) in db.query(MentorProject.project_id).filter_by(user_id=13)] == [2]


def test_mentor_list_shows_only_active_verified_mentors_and_no_ids(engine, store):
    for uid, pids in ((13, [1, 2]), (14, [1, 3]), (12, [1])):
        post(user(engine, store, uid), "/api/help/offer", active=True, project_ids=pids, note=f"nota {uid}")
    asker = user(engine, store, 15)
    r = asker.get("/api/help/mentors?project_id=1").json()["mentors"]
    assert {m["login"] for m in r} == {"u12", "u13", "u14"}
    m14 = next(m for m in r if m["login"] == "u14")
    assert m14["level"] == 8.5 and m14["mark"] == 125 and m14["note"] == "nota 14" and m14["validated_on"]
    assert "user_id" not in asker.get("/api/help/mentors?project_id=1").text
    assert {m["login"] for m in asker.get("/api/help/mentors?project_id=3").json()["mentors"]} == {"u14"}
    assert user(engine, store, 13).get("/api/help/mentors?project_id=1").json()["mentors"] != []      # y no se lista a sí mismo
    assert "u13" not in {m["login"] for m in user(engine, store, 13).get("/api/help/mentors?project_id=1").json()["mentors"]}


def test_a_mentor_who_loses_the_validation_disappears(engine, store):
    post(user(engine, store, 13), "/api/help/offer", active=True, project_ids=[2])
    asker = user(engine, store, 15)
    assert [m["login"] for m in asker.get("/api/help/mentors?project_id=2").json()["mentors"]] == ["u13"]
    with Session(engine) as s:
        for pu in s.query(ProjectUser).filter_by(user_id=13, project_id=2):
            pu.validated = False
        s.commit()
    assert asker.get("/api/help/mentors?project_id=2").json()["mentors"] == []


def test_inactive_offers_are_hidden(engine, store):
    c = user(engine, store, 13)
    post(c, "/api/help/offer", active=True, project_ids=[1])
    post(c, "/api/help/offer", active=False, project_ids=[1])
    assert user(engine, store, 15).get("/api/help/mentors?project_id=1").json()["mentors"] == []


# ---------------------------------------------------------------- peticiones de ayuda

def test_help_request_lifecycle_and_matching(engine, store):
    post(user(engine, store, 13), "/api/help/offer", active=True, project_ids=[1])
    asker = user(engine, store, 15)
    r = post(asker, "/api/help/requests", project_id=1, message="No entiendo cómo reservar memoria con malloc")
    assert r.status_code == 200 and [m["login"] for m in r.json()["mentors"]] == ["u13"]
    mine = asker.get("/api/help/overview").json()["requests"]
    assert len(mine) == 1 and mine[0]["project"] == "libft" and [m["login"] for m in mine[0]["mentors"]] == ["u13"]
    inbox = user(engine, store, 13).get("/api/help/overview").json()["incoming"]       # el mentor la ve, con login pero sin id ni nivel
    assert [(i["login"], i["project"]) for i in inbox] == [("u15", "libft")] and "user_id" not in str(inbox) and "level" not in inbox[0]
    assert post(asker, f"/api/help/requests/{r.json()['id']}/close").status_code == 200
    assert asker.get("/api/help/overview").json()["requests"] == []
    with Session(store) as db:                                                         # cerrar borra el texto, no lo archiva
        assert db.query(HelpRequest).count() == 0
    assert user(engine, store, 13).get("/api/help/overview").json()["incoming"] == []


def test_request_rules(engine, store):
    c = user(engine, store, 15)
    ok = dict(project_id=1, message="Necesito una explicación de punteros")
    assert post(c, "/api/help/requests", project_id=1, message="corto").status_code == 422            # mensaje demasiado corto
    assert post(c, "/api/help/requests", project_id=1, message="x" * 281).status_code == 422
    assert post(c, "/api/help/requests", project_id=999, message="Un proyecto que no existe del todo").status_code == 422
    assert post(user(engine, store, 13), "/api/help/requests", **ok).status_code == 422               # ya lo tiene validado
    assert post(c, "/api/help/requests", **ok).status_code == 200
    assert post(c, "/api/help/requests", **ok).status_code == 422                                       # duplicada para el mismo proyecto
    assert post(c, "/api/help/requests", project_id=2, message="Necesito ayuda con get_next_line").status_code == 200
    assert post(c, "/api/help/requests", project_id=3, message="Necesito ayuda con ft_printf ya").status_code == 200
    r = post(c, "/api/help/requests", project_id=1, message="otra petición cualquiera de ayuda")
    assert r.status_code == 422                                                                       # ya son MAX_OPEN_REQUESTS
    assert len(c.get("/api/help/overview").json()["requests"]) == MAX_OPEN_REQUESTS


def test_nobody_can_close_someone_elses_request_but_an_admin_can(engine, store):
    asker = user(engine, store, 15)
    rid = post(asker, "/api/help/requests", project_id=1, message="Necesito ayuda con libft por favor").json()["id"]
    assert post(user(engine, store, 16), f"/api/help/requests/{rid}/close").status_code == 404        # no revela que existe
    assert post(user(engine, store, 14, cfg=ADMIN_CFG), f"/api/help/requests/{rid}/close").status_code == 200
    assert post(asker, "/api/help/requests/99999/close").status_code == 404


def test_old_requests_expire_and_mentors_only_see_their_projects(engine, store):
    post(user(engine, store, 13), "/api/help/offer", active=True, project_ids=[1])               # u13 ofrece libft, no gnl
    old = NOW - timedelta(days=31)
    with Session(store) as db:
        db.add_all([HelpRequest(user_id=15, login="u15", project_id=1, message="petición antigua de ayuda", status="open", created_at=old),
                    HelpRequest(user_id=16, login="u16", project_id=2, message="piden gnl y no me interesa", status="open", created_at=NOW)])
        db.commit()
    assert user(engine, store, 13).get("/api/help/overview").json()["incoming"] == []
    assert user(engine, store, 15).get("/api/help/overview").json()["requests"] == []


# ---------------------------------------------------------------- recursos y moderación

GOOD = dict(project_id=1, title="Guía de punteros en C", url="https://www.cs.cmu.edu/guia", kind="guía", confirm_no_solution=True)


def test_resource_must_be_confirmed_valid_and_goes_to_moderation(engine, store):
    c = user(engine, store, 15)
    assert post(c, "/api/help/resources", **{**GOOD, "confirm_no_solution": False}).status_code == 422
    assert post(c, "/api/help/resources", **{**GOOD, "url": "http://insegura.com/x"}).status_code == 422
    assert post(c, "/api/help/resources", **{**GOOD, "url": "https://127.0.0.1/x"}).status_code == 422
    assert post(c, "/api/help/resources", **{**GOOD, "kind": "solución completa"}).status_code == 422       # tipo no permitido
    assert post(c, "/api/help/resources", **{**GOOD, "project_id": 999}).status_code == 422
    assert post(c, "/api/help/resources", **{**GOOD, "title": "x"}).status_code == 422
    r = post(c, "/api/help/resources", **GOOD)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert post(c, "/api/help/resources", **GOOD).status_code == 422                                          # enlace repetido
    assert user(engine, store, 16).get("/api/help/resources?project_id=1").json()["resources"] == []         # nadie más la ve aún
    assert [x["title"] for x in c.get("/api/help/resources?project_id=1").json()["mine_pending"]] == ["Guía de punteros en C"]


def test_admin_approves_and_rejects_and_only_approved_resources_are_public(engine, store):
    c = user(engine, store, 15)
    ids = [post(c, "/api/help/resources", **{**GOOD, "url": f"https://example.org/g{i}", "title": f"Guía {i} de libft"}).json()["id"] for i in range(3)]
    post(c, "/api/help/resources", project_id=None, title="Manual de gdb general", url="https://sourceware.org/gdb/doc", kind="documentación",
         confirm_no_solution=True)
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    pend = admin.get("/api/admin/help/pending").json()["resources"]
    assert len(pend) == 4 and {p["by"] for p in pend} == {"u15"} and "General" in {p["project"] for p in pend}
    assert admin.post(f"/api/admin/help/resources/{ids[0]}/approve", headers=ORIGIN, json={}).json()["status"] == "approved"
    assert admin.post(f"/api/admin/help/resources/{ids[1]}/reject", headers=ORIGIN, json={}).json()["status"] == "rejected"
    assert admin.post(f"/api/admin/help/resources/{ids[2]}/borrar", headers=ORIGIN, json={}).status_code == 400
    assert admin.post("/api/admin/help/resources/99999/approve", headers=ORIGIN, json={}).status_code == 404
    pend_general = next(p for p in admin.get("/api/admin/help/pending").json()["resources"] if p["project"] == "General")
    admin.post(f"/api/admin/help/resources/{pend_general['id']}/approve", headers=ORIGIN, json={})
    seen = user(engine, store, 16).get("/api/help/resources?project_id=1").json()["resources"]
    assert {x["title"] for x in seen} == {"Guía 0 de libft", "Manual de gdb general"}                          # el rechazado y el pendiente no salen
    assert user(engine, store, 16).get("/api/help/resources?project_id=2").json()["resources"][0]["title"] == "Manual de gdb general"   # lo general sí


def test_admin_can_see_who_proposes_resources_and_who_gets_rejected(engine, store):
    troll = user(engine, store, 15)
    good = user(engine, store, 16)
    ids = [post(troll, "/api/help/resources", **{**GOOD, "url": f"https://example.org/t{i}", "title": f"Recurso troll {i}"}).json()["id"] for i in range(3)]
    ok = post(good, "/api/help/resources", **{**GOOD, "url": "https://example.org/bueno", "title": "Guía muy buena de libft"}).json()["id"]
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    for i in ids[:2]:
        admin.post(f"/api/admin/help/resources/{i}/reject", headers=ORIGIN, json={})
    admin.post(f"/api/admin/help/resources/{ok}/approve", headers=ORIGIN, json={})
    log = admin.get("/api/admin/help/resources/log").json()
    assert [p["login"] for p in log["people"]] == ["u15", "u16"]                       # primero quien más rechazos acumula
    u15, u16 = log["people"]
    assert (u15["sent"], u15["rejected"], u15["pending"], u15["approved"], u15["flag"]) == (3, 2, 1, 0, True)
    assert (u16["sent"], u16["approved"], u16["flag"]) == (1, 1, False)
    assert len(log["recent"]) == 4 and {r["status"] for r in log["recent"]} == {"pending", "rejected", "approved"}
    assert all(r["days"] == 0 and r["by"] in ("u15", "u16") for r in log["recent"])
    assert admin.get("/api/admin/help/pending").json()["resources"][0]["days"] == 0     # lo pendiente también dice desde cuándo


def test_resource_log_is_only_for_admins_and_keeps_the_trace_of_people_who_erased_their_data(engine, store):
    troll = user(engine, store, 15)
    post(troll, "/api/help/resources", **GOOD)
    assert troll.get("/api/admin/help/resources/log").status_code == 403
    anon, _ = make_client(engine, settings_engine=store)
    assert anon.get("/api/admin/help/resources/log").status_code == 401
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    rid = admin.get("/api/admin/help/pending").json()["resources"][0]["id"]
    admin.post(f"/api/admin/help/resources/{rid}/reject", headers=ORIGIN, json={})
    troll.post("/api/me/delete", headers=ORIGIN, json={})                                   # borrar los datos NO borra quién propuso qué
    log = admin.get("/api/admin/help/resources/log").json()
    assert [(p["login"], p["rejected"]) for p in log["people"]] == [("u15", 1)] and log["recent"][0]["by"] == "u15"


# ---------------------------------------------------------------- la cuarentena: aislada, sin forma de meter ni sacar nada

def _stored(c):
    with Session(c.app.state.proposals_db()) as q:
        return [(r.title, r.url, r.kind, r.project_id, r.submitted_login) for r in q.query(ResourceProposal)]


def _settings_rows(store):
    with Session(store) as db:
        return {t.name: db.execute(t.select()).fetchall() for t in user_data_tables()}


def test_a_proposal_only_ever_touches_the_quarantine_database(engine, store):
    c = user(engine, store, 15)
    before = _settings_rows(store)
    r = post(c, "/api/help/resources", **GOOD)
    assert r.status_code == 200 and set(r.json()) == {"id", "status"}                        # la respuesta no devuelve nada más
    assert c.app.state.proposals_db() is not store                                           # otra base, no la de sesiones, correos y puntos
    assert _settings_rows(store) == before                                                  # ni una fila nueva en la base de ajustes
    assert _stored(c) == [("Guía de punteros en C", "https://www.cs.cmu.edu/guia", "guía", 1, "u15")]
    assert "resource_proposals" not in {t.name for t in user_data_tables()}                  # ni se vuelca ni se borra con la base de usuarios


HOSTILE_TITLES = [
    "Robert'); DROP TABLE resource_proposals;-- guía", "' OR '1'='1' -- manual de gdb", "\"; DELETE FROM user_sessions; -- apuntes",
    "<script>fetch('/api/admin/logins')</script> apuntes", "<img src=x onerror=alert(1)> apuntes", "{{7*7}} ${7*7} #{7*7} apuntes",
    "%s%s%s%n %d apuntes", "../../etc/passwd apuntes", "apuntes\x00con nulo", "apuntes\r\nSet-Cookie: a=b", "\u202eevil.exe apuntes",
]


@pytest.mark.parametrize("title", HOSTILE_TITLES)
def test_hostile_titles_are_stored_as_inert_text_and_nothing_else_changes(engine, store, title):
    c = user(engine, store, 15)
    other = user(engine, store, 16)
    before = _settings_rows(store)
    r = post(c, "/api/help/resources", **{**GOOD, "title": title})
    assert r.status_code in (200, 422)
    assert r.status_code != 200 or set(r.json()) == {"id", "status"}
    assert _settings_rows(store) == before                                                  # nada llega a la base de ajustes
    with Session(c.app.state.proposals_db()) as q:                                           # y la cuarentena sigue entera
        assert q.query(ResourceProposal).count() == (1 if r.status_code == 200 else 0)
    assert other.get("/api/help/resources?project_id=1").json() == {"resources": [], "mine_pending": []}   # los demás no ven nada
    assert user(engine, store, 16).get("/api/help/overview").status_code == 200


@pytest.mark.parametrize("url", [
    "https://example.org/x'; DROP TABLE resource_proposals;--", "javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "file:///etc/passwd",
    "https://user:pass@example.org/", "https://example.org:8443/x", "https://127.0.0.1/x", "https://[::1]/x", "https://0x7f.1/x", "https://localhost/x",
    "https://exa mple.org/x", "https://example.org/\\evil", "//example.org/x", "https://ex\u0430mple.org/x", "https://example.org/\x00",
    "ftp://example.org/x", "https://" + "a" * 400 + ".org/x",
])
def test_hostile_links_never_reach_the_quarantine(engine, store, url):
    c = user(engine, store, 15)
    r = post(c, "/api/help/resources", **{**GOOD, "url": url})
    assert r.status_code == 422 or (r.status_code == 200 and url.startswith("https://example.org/x'"))   # la comilla en la ruta es válida: se guarda inerte
    assert len(_stored(c)) == (1 if r.status_code == 200 else 0)


@pytest.mark.parametrize("body", [
    {**GOOD, "title": ["lista"]}, {**GOOD, "title": {"a": 1}}, {**GOOD, "title": None}, {**GOOD, "kind": "<b>x</b>"}, {**GOOD, "kind": "guía'; --"},
    {**GOOD, "project_id": "1 OR 1=1"}, {**GOOD, "project_id": -1}, {**GOOD, "project_id": 10**30}, {**GOOD, "project_id": 1.5},
    {**GOOD, "confirm_no_solution": "yes please"}, {**GOOD, "status": "approved"}, {**GOOD, "submitted_by": 1}, {"title": "solo título"}, [], "texto",
])
def test_malformed_or_extra_fields_are_refused_or_ignored(engine, store, body):
    c = user(engine, store, 15)
    r = c.post("/api/help/resources", json=body, headers=ORIGIN)
    assert r.status_code in (200, 422)
    for _, _, _, _, login in _stored(c):
        assert login == "u15"                                                               # el autor sale de la sesión, nunca del cuerpo
    with Session(c.app.state.proposals_db()) as q:
        assert all(p.status == "pending" and p.submitted_by == 15 for p in q.query(ResourceProposal))     # y nadie puede darse por aprobado


def test_oversized_bodies_and_other_content_types_are_refused_before_anything_is_read(engine, store):
    c = user(engine, store, 15)
    assert c.post("/api/help/resources", content="x" * 50_000, headers={**ORIGIN, "Content-Type": "application/json"}).status_code == 413
    assert c.post("/api/help/resources", content="title=a&url=b", headers={**ORIGIN, "Content-Type": "application/x-www-form-urlencoded"}).status_code == 415
    assert c.post("/api/help/resources", json=GOOD, headers={"Origin": "https://evil.example"}).status_code == 403
    assert _stored(c) == []


def test_nobody_can_read_other_peoples_proposals_and_only_admins_can_review(engine, store):
    a, b = user(engine, store, 15), user(engine, store, 16)
    rid = post(a, "/api/help/resources", **GOOD).json()["id"]
    assert [x["title"] for x in a.get("/api/help/resources?project_id=1").json()["mine_pending"]] == ["Guía de punteros en C"]
    assert b.get("/api/help/resources?project_id=1").json() == {"resources": [], "mine_pending": []}
    assert b.get("/api/help/overview").status_code == 200 and "Guía de punteros" not in b.get("/api/help/overview").text
    for path in ("/api/admin/help/pending", "/api/admin/help/resources/log"):
        assert b.get(path).status_code == 403
    assert b.post(f"/api/admin/help/resources/{rid}/approve", headers=ORIGIN, json={}).status_code == 403
    assert _stored(a)[0][4] == "u15" and len(_stored(a)) == 1


def test_approving_publishes_a_copy_without_personal_data_and_a_proposal_is_reviewed_only_once(engine, store):
    a = user(engine, store, 15)
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    rid = post(a, "/api/help/resources", **GOOD).json()["id"]
    assert admin.post(f"/api/admin/help/resources/{rid}/approve", headers=ORIGIN, json={}).json()["status"] == "approved"
    assert admin.post(f"/api/admin/help/resources/{rid}/reject", headers=ORIGIN, json={}).status_code == 409      # ya revisada
    assert admin.post(f"/api/admin/help/resources/{rid}/approve", headers=ORIGIN, json={}).status_code == 409     # y no se publica dos veces
    with Session(store) as db:
        pub = db.query(LearningResource).one()
        assert (pub.title, pub.url, pub.submitted_by, pub.submitted_login) == ("Guía de punteros en C", "https://www.cs.cmu.edu/guia", 0, "")
    with Session(a.app.state.proposals_db()) as q:
        p = q.get(ResourceProposal, rid)
        assert p.status == "approved" and p.reviewed_by == 14 and p.reviewed_at is not None and p.published_id == pub.id
    public = user(engine, store, 16).get("/api/help/resources?project_id=1").json()["resources"]
    assert [x["title"] for x in public] == ["Guía de punteros en C"] and set(public[0]) == {"id", "title", "url", "kind", "project_id", "project", "status"}


def test_proposals_that_lived_in_the_settings_database_move_to_the_quarantine_once(engine, store):
    from stats42.helpboard import migrate_legacy_resources

    user(engine, store, 13)                                                                  # crea las tablas
    with Session(store) as s, Session(user(engine, store, 14).app.state.proposals_db()) as q:
        s.add_all([
            LearningResource(project_id=1, title="vieja pendiente", url="https://a.example.com/x", kind="guía", submitted_by=15, submitted_login="u15", status="pending", created_at=NOW),
            LearningResource(project_id=1, title="vieja aprobada", url="https://b.example.com/x", kind="guía", submitted_by=15, submitted_login="u15", status="approved", created_at=NOW),
        ])
        s.commit()
        migrate_legacy_resources(s, q)
        migrate_legacy_resources(s, q)                                                      # idempotente
        assert sorted((p.title, p.status, p.submitted_login) for p in q.query(ResourceProposal)) == [("vieja aprobada", "approved", "u15"), ("vieja pendiente", "pending", "u15")]
        assert [(r.title, r.submitted_login) for r in s.query(LearningResource)] == [("vieja aprobada", "")]      # lo publicado se queda sin nombre


def test_resource_submissions_are_rate_limited(engine, store):
    c = user(engine, store, 15)
    codes = [post(c, "/api/help/resources", **{**GOOD, "url": f"https://example.org/r{i}", "title": f"Recurso número {i}"}).status_code for i in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]


def test_html_in_text_is_stored_as_text_not_markup(engine, store):
    c = user(engine, store, 15)
    r = post(c, "/api/help/resources", **{**GOOD, "title": "<img src=x onerror=alert(1)> guía"})
    assert r.status_code == 200
    with Session(c.app.state.proposals_db()) as q:
        assert q.query(ResourceProposal).one().title == "<img src=x onerror=alert(1)> guía"      # se guarda literal: escapar es cosa de la salida
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    res = admin.get("/api/admin/help/pending")
    assert res.headers["content-type"].startswith("application/json") and res.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path,body", [
    ("/api/help/offer", dict(active=True, project_ids=[1])), ("/api/help/requests", dict(project_id=1, message="Un mensaje de ayuda válido")),
    ("/api/help/resources", GOOD),
])
def test_writes_from_another_origin_are_refused(engine, store, path, body):
    from stats42.db import user_data_tables

    c = user(engine, store, 13)
    for table in user_data_tables():                  # la web las crea al primer uso; aquí no hubo ninguno
        table.create(store, checkfirst=True)
    r = c.post(path, json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    with Session(store) as db:
        assert db.query(HelpRequest).count() == db.query(LearningResource).count() == db.query(MentorOffer).count() == 0


def test_overview_exposes_only_the_users_own_data(engine, store):
    post(user(engine, store, 13), "/api/help/offer", active=True, project_ids=[1], note="secreto de u13")
    post(user(engine, store, 15), "/api/help/requests", project_id=1, message="Mensaje privado de quien pide ayuda")
    o = user(engine, store, 16).get("/api/help/overview").json()
    assert o["offer"] is None and o["requests"] == [] and o["incoming"] == [] and o["validated"] == []
    assert "u13" not in str(o) and "secreto" not in str(o) and "privado" not in str(o)


def test_invalid_attempts_do_not_burn_the_hourly_quota_of_valid_submissions(engine, store):
    c = user(engine, store, 15)
    for _ in range(10):                                                       # muchos intentos con errores de tecleo
        assert post(c, "/api/help/resources", **{**GOOD, "url": "http://no-https.com/x"}).status_code == 422
    assert post(c, "/api/help/resources", **GOOD).status_code == 200            # el envío correcto sigue pasando


def test_flooding_with_invalid_attempts_is_still_capped(engine, store):
    c = user(engine, store, 15)
    codes = [post(c, "/api/help/requests", project_id=1, message="x").status_code for _ in range(62)]
    assert codes[:60] == [422] * 60 and codes[60:] == [429, 429]


def test_in_progress_projects_show_how_much_help_exists(engine, store):
    with Session(engine) as s:
        s.add(ProjectUser(id=9001, user_id=15, project_id=1, status="in_progress", created_at=NOW - timedelta(days=12)))
        s.commit()
    post(user(engine, store, 13), "/api/help/offer", active=True, project_ids=[1])
    post(user(engine, store, 14), "/api/help/offer", active=True, project_ids=[1, 3])
    c = user(engine, store, 15)
    rid = post(c, "/api/help/resources", **GOOD).json()["id"]
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    admin.post(f"/api/admin/help/resources/{rid}/approve", headers=ORIGIN, json={})
    p = c.get("/api/me").json()["projects"]["in_progress"][0]
    assert (p["name"], p["mentors"], p["resources"]) == ("libft", 2, 1)
    assert "user_id" not in str(p)


def test_habits_endpoint_is_for_members_only_and_aggregated(engine, store):
    anon, _ = make_client(engine, settings_engine=store)
    assert anon.get("/api/habits").status_code == 401
    r = user(engine, store, 15).get("/api/habits")
    assert r.status_code == 200 and r.json()["quartiles"] == []            # cohorte demasiado pequeña en el test: sin cifras


def test_help_page_is_for_members_only_and_has_no_inline_scripts(engine, store):
    anon, _ = make_client(engine, settings_engine=store)
    r = anon.get("/ayuda")
    assert r.status_code == 302 and r.headers["location"] == "/login"
    c = user(engine, store, 15)
    page = c.get("/ayuda")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    assert page.text.count("<script") == page.text.count('<script src="/static/')
    assert "Aprender juntos, sin copiar" in page.text and "cheating" in page.text         # la regla de no copiar, siempre visible
    assert c.get("/static/ayuda.js").status_code == 200
