"""La ayuda separa los proyectos por cursus: cada proyecto en el suyo, el principal primero y los recursos filtrables por cursus."""
from sqlalchemy.orm import Session

from stats42.db import LearningResource, Project, ProjectUser
from stats42.helpboard import cursus_groups, project_options

from test_helpboard import ADMIN_CFG, GOOD, engine, post, store, user  # noqa: F401


def tag_cursus(engine):
    """libft y gnl cursan el 42cursus (21); printf, la piscina (9). Un intento suelto de libft en la piscina no cambia su cursus."""
    with Session(engine) as s:
        for pid, ids in ((1, [21]), (2, [21]), (3, [9])):
            s.query(ProjectUser).filter(ProjectUser.project_id == pid).update({"cursus_ids": ids})
        s.add(ProjectUser(id=9001, user_id=98, project_id=1, status="finished", validated=False, final_mark=10, cursus_ids=[9]))
        s.add(Project(id=4, name="rarísimo", slug="raro", difficulty=1, cursus_ids=[21], cursus_names="42cursus"))
        s.query(Project).filter(Project.id.in_((1, 2))).update({"cursus_ids": [21, 9], "cursus_names": "42cursus, C Piscine"}, synchronize_session=False)
        s.query(Project).filter(Project.id == 3).update({"cursus_ids": [9], "cursus_names": "C Piscine"})
        s.query(Project).filter(Project.id == 1).update({"difficulty": 5})
        s.query(Project).filter(Project.id == 2).update({"difficulty": 2})
        s.commit()


def test_each_project_goes_to_its_most_common_cursus_and_groups_are_named_and_ordered(engine):
    tag_cursus(engine)
    with Session(engine) as s:
        opts = project_options(s)
        assert {o["id"]: o["cursus_id"] for o in opts} == {1: 21, 2: 21, 3: 9}
        assert [o["name"] for o in opts if o["cursus_id"] == 21] == ["get_next_line", "libft"]       # por dificultad, no por alfabeto
        groups = cursus_groups(s, opts, 21)
        assert [(g["id"], g["name"], g["projects"]) for g in groups] == [(21, "42cursus", 2), (9, "C Piscine", 1)]


def test_projects_without_cursus_data_fall_into_others_at_the_end(engine):
    with Session(engine) as s:                                                  # sin cursus_ids en los intentos
        opts = project_options(s)
        assert {o["cursus_id"] for o in opts} == {None}
        assert [(g["id"], g["name"]) for g in cursus_groups(s, opts, 21)] == [(None, "Otros")]


def test_overview_exposes_cursus_groups_and_tags_validated_projects(engine, store):
    tag_cursus(engine)
    o = user(engine, store, 13).get("/api/help/overview").json()
    assert o["default_cursus"] == 21 and [c["id"] for c in o["cursus"]] == [21, 9]
    assert {p["id"]: p["cursus_id"] for p in o["projects"]} == {1: 21, 2: 21, 3: 9}
    assert {v["id"]: v["cursus_id"] for v in o["validated"]} == {1: 21, 2: 21}


def test_resources_can_be_filtered_by_cursus_and_general_ones_always_show(engine, store):
    tag_cursus(engine)
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    c = user(engine, store, 13)
    for i, (pid, title) in enumerate([(1, "de libft"), (3, "de printf"), (None, "general")]):
        rid = post(c, "/api/help/resources", **{**GOOD, "project_id": pid, "title": title, "url": f"https://guia{i}.example.com/x"}).json()["id"]
        post(admin, f"/api/admin/help/resources/{rid}/approve")
    titles = lambda q: sorted(r["title"] for r in c.get("/api/help/resources" + q).json()["resources"])  # noqa: E731
    assert titles("") == ["de libft", "de printf", "general"]
    assert titles("?cursus_id=21") == ["de libft", "general"]
    assert titles("?cursus_id=9") == ["de printf", "general"]
    assert titles("?project_id=3&cursus_id=21") == ["de printf", "general"]                      # el proyecto concreto manda
    assert c.get("/api/help/resources?cursus_id=99999999999999999999").status_code == 422
