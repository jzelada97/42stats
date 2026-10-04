"""La ayuda solo trabaja con el 42cursus: piscinas y cursus obsoletos no salen, y cada proyecto cuenta en su cursus principal."""
from sqlalchemy.orm import Session

from stats42.db import Project, ProjectUser
from stats42.helpboard import cursus_groups, project_options

from test_helpboard import ADMIN_CFG, GOOD, engine, post, store, user  # noqa: F401


def tag_cursus(engine):
    """libft y gnl cursan el 42cursus (21); printf, la piscina (9). Un intento suelto de libft en la piscina no cambia su cursus."""
    with Session(engine) as s:
        for pid, ids in ((1, [21]), (2, [21]), (3, [9])):
            s.query(ProjectUser).filter(ProjectUser.project_id == pid).update({"cursus_ids": ids})
        s.add(ProjectUser(id=9001, user_id=98, project_id=1, status="finished", validated=False, final_mark=10, cursus_ids=[9]))
        s.query(Project).filter(Project.id.in_((1, 2))).update({"cursus_ids": [21, 9], "cursus_names": "42cursus, C Piscine"}, synchronize_session=False)
        s.query(Project).filter(Project.id == 3).update({"cursus_ids": [9], "cursus_names": "C Piscine"})
        s.query(Project).filter(Project.id == 1).update({"difficulty": 5})
        s.query(Project).filter(Project.id == 2).update({"difficulty": 2})
        s.commit()


def test_only_the_main_cursus_projects_are_offered_and_ordered_by_difficulty(engine):
    tag_cursus(engine)
    with Session(engine) as s:
        assert {o["id"]: o["cursus_id"] for o in project_options(s)} == {1: 21, 2: 21, 3: 9}      # sin filtro: cada uno en el suyo
        only = project_options(s, 21)
        assert [(o["name"], o["cursus_id"]) for o in only] == [("get_next_line", 21), ("libft", 21)]   # dificultad, no alfabeto
        assert [(g["id"], g["name"]) for g in cursus_groups(s, only, 21)] == [(21, "42cursus")]


def test_projects_without_cursus_data_are_left_out_when_filtering(engine):
    with Session(engine) as s:
        for pu in s.query(ProjectUser):
            pu.cursus_ids = None
        s.commit()
        assert project_options(s, 21) == []
        assert [(g["id"], g["name"]) for g in cursus_groups(s, project_options(s), 21)] == [(None, "Otros")]


def test_overview_has_one_cursus_and_hides_piscina_projects(engine, store):
    tag_cursus(engine)
    o = user(engine, store, 14).get("/api/help/overview").json()
    assert o["default_cursus"] == 21 and [c["id"] for c in o["cursus"]] == [21]
    assert {p["id"] for p in o["projects"]} == {1, 2}
    assert {v["id"]: v["cursus_id"] for v in o["validated"]} == {1: 21, 3: None}                 # lo validado fuera del 42cursus no se ofrece


def test_requests_and_resources_for_other_cursus_are_refused(engine, store):
    tag_cursus(engine)
    c = user(engine, store, 15)
    assert post(c, "/api/help/requests", project_id=3, message="necesito ayuda con la piscina por favor").status_code == 422
    assert post(c, "/api/help/resources", **{**GOOD, "project_id": 3}).status_code == 422
    assert post(c, "/api/help/requests", project_id=1, message="necesito ayuda con libft por favor").status_code == 200


def test_resources_can_still_be_filtered_by_cursus_and_general_ones_always_show(engine, store):
    tag_cursus(engine)
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    c = user(engine, store, 13)
    for i, (pid, title) in enumerate([(1, "de libft"), (2, "de gnl"), (None, "general")]):
        rid = post(c, "/api/help/resources", **{**GOOD, "project_id": pid, "title": title, "url": f"https://guia{i}.example.com/x"}).json()["id"]
        post(admin, f"/api/admin/help/resources/{rid}/approve")
    titles = lambda q: sorted(r["title"] for r in c.get("/api/help/resources" + q).json()["resources"])  # noqa: E731
    assert titles("") == ["de gnl", "de libft", "general"]
    assert titles("?cursus_id=21") == ["de gnl", "de libft", "general"]
    assert titles("?cursus_id=9") == ["general"]
    assert titles("?project_id=2&cursus_id=9") == ["de gnl", "general"]                           # el proyecto concreto manda
    assert c.get("/api/help/resources?cursus_id=99999999999999999999").status_code == 422


def test_panel_only_offers_help_links_for_projects_that_have_a_help_section(engine, store):
    tag_cursus(engine)
    with Session(engine) as s:
        s.add_all([ProjectUser(id=9100, user_id=15, project_id=1, status="in_progress", cursus_ids=[21]),
                   ProjectUser(id=9101, user_id=15, project_id=3, status="in_progress", cursus_ids=[9])])
        s.commit()
    c = user(engine, store, 15)
    got = {p["id"]: p["help"] for p in c.get("/api/me").json()["projects"]["in_progress"]}
    assert got == {1: True, 3: False}
