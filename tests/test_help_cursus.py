"""La ayuda solo trabaja con el 42cursus y agrupa los proyectos por círculo (Common Core Rank), calculado con los datos."""
from datetime import timedelta

from sqlalchemy.orm import Session

from stats42.db import Project, ProjectUser, Quest, QuestUser
from stats42.helpboard import MIN_RANK_VOTES, default_rank, project_options, project_ranks, rank_groups

from test_helpboard import ADMIN_CFG, GOOD, NOW, engine, post, store, user  # noqa: F401


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


def tag_ranks(engine, users=(12, 13, 14)):
    """Línea de tiempo (hace N días): libft -> Rank 02 -> gnl -> Rank 03. printf (u14, hace 40 días) llega tras su último rank."""
    ago = lambda d: NOW - timedelta(days=d)  # noqa: E731
    libft = {12: 50, 13: 200, 14: 300}
    gnl = {12: 40, 13: 100, 14: 120}
    r3 = {12: 20, 13: 60, 14: 90}
    with Session(engine) as s:
        s.add_all([Quest(id=100, name="Common Core Rank 02", cursus_id=21), Quest(id=101, name="Common Core Rank 03", cursus_id=21)])
        k = 9300
        for u in users:
            for qid, when in ((100, libft[u] - 5), (101, r3[u])):
                k += 1
                s.add(QuestUser(id=k, user_id=u, quest_id=qid, validated_at=ago(when)))
        for u in (12, 14):                                      # u13 ya valida gnl en el fixture
            k += 1
            s.add(ProjectUser(id=k, user_id=u, project_id=2, status="finished", validated=True, final_mark=90, marked_at=ago(gnl[u]), cursus_ids=[21]))
        s.commit()


# ---------------------------------------------------------------- cursus

def test_only_the_main_cursus_projects_are_offered(engine):
    tag_cursus(engine)
    with Session(engine) as s:
        assert {o["id"]: o["cursus_id"] for o in project_options(s)} == {1: 21, 2: 21, 3: 9}      # sin filtro: cada uno en el suyo
        only = project_options(s, 21)
        assert [(o["name"], o["cursus_id"]) for o in only] == [("get_next_line", 21), ("libft", 21)]   # sin rank: por dificultad


def test_projects_without_cursus_data_are_left_out_when_filtering(engine):
    with Session(engine) as s:
        for pu in s.query(ProjectUser):
            pu.cursus_ids = None
        s.commit()
        assert project_options(s, 21) == []


def test_requests_and_resources_for_other_cursus_are_refused(engine, store):
    tag_cursus(engine)
    c = user(engine, store, 15)
    assert post(c, "/api/help/requests", project_id=3, message="necesito ayuda con la piscina por favor").status_code == 422
    assert post(c, "/api/help/resources", **{**GOOD, "project_id": 3}).status_code == 422
    assert post(c, "/api/help/requests", project_id=1, message="necesito ayuda con libft por favor").status_code == 200


def test_panel_only_offers_help_links_for_projects_that_have_a_help_section(engine, store):
    tag_cursus(engine)
    with Session(engine) as s:
        s.add_all([ProjectUser(id=9100, user_id=15, project_id=1, status="in_progress", cursus_ids=[21]),
                   ProjectUser(id=9101, user_id=15, project_id=3, status="in_progress", cursus_ids=[9])])
        s.commit()
    got = {p["id"]: p["help"] for p in user(engine, store, 15).get("/api/me").json()["projects"]["in_progress"]}
    assert got == {1: True, 3: False}


# ---------------------------------------------------------------- círculos (ranks)

def test_a_project_belongs_to_the_rank_students_validated_right_after_it(engine):
    tag_ranks(engine)
    with Session(engine) as s:
        assert project_ranks(s, [1, 2, 3], 21) == {1: 2, 2: 3}             # printf: un solo caso y posterior a su último rank


def test_a_rank_needs_enough_students_to_be_trusted(engine):
    tag_ranks(engine, users=(12, 13))                                       # solo 2 alumnos con rank: libft = 2 votos < mínimo
    assert MIN_RANK_VOTES == 3
    with Session(engine) as s:
        assert project_ranks(s, [1, 2, 3], 21) == {}


def test_options_are_ordered_by_rank_then_difficulty_and_unplaced_go_last(engine):
    tag_ranks(engine)
    with Session(engine) as s:
        opts = project_options(s, 21)
        assert [(o["name"], o["rank"]) for o in opts] == [("libft", 2), ("get_next_line", 3), ("ft_printf", None)]
        assert rank_groups(opts) == [{"id": 2, "name": "Rank 02", "projects": 1}, {"id": 3, "name": "Rank 03", "projects": 1},
                                     {"id": None, "name": "Sin rank", "projects": 1}]


def test_default_rank_is_where_the_student_is_working(engine):
    tag_ranks(engine)
    with Session(engine) as s:
        opts = project_options(s, 21)
        assert default_rank(s, 15, opts, {}) == 2                           # nada validado: el primero
        assert default_rank(s, 13, opts, {1: {}, 2: {}}) is None            # lo único que queda no tiene rank: la web usa el primero
        s.add(ProjectUser(id=9400, user_id=15, project_id=2, status="in_progress", cursus_ids=[21]))
        s.commit()
        assert default_rank(s, 15, opts, {}) == 3                           # su proyecto en curso manda


def test_overview_exposes_ranks_default_and_which_validated_projects_can_be_offered(engine, store):
    tag_ranks(engine)
    o = user(engine, store, 14).get("/api/help/overview").json()
    assert [r["id"] for r in o["ranks"]] == [2, 3, None]
    assert {p["id"]: p["rank"] for p in o["projects"]} == {1: 2, 2: 3, 3: None}
    assert {v["id"]: (v["rank"], v["in_help"]) for v in o["validated"]} == {1: (2, True), 2: (3, True), 3: (None, True)}


def test_resources_can_be_filtered_by_rank_and_general_ones_always_show(engine, store):
    tag_ranks(engine)
    admin = user(engine, store, 14, cfg=ADMIN_CFG)
    c = user(engine, store, 13)
    for i, (pid, title) in enumerate([(1, "de libft"), (2, "de gnl"), (None, "general")]):
        rid = post(c, "/api/help/resources", **{**GOOD, "project_id": pid, "title": title, "url": f"https://guia{i}.example.com/x"}).json()["id"]
        post(admin, f"/api/admin/help/resources/{rid}/approve")
    titles = lambda q: sorted(r["title"] for r in c.get("/api/help/resources" + q).json()["resources"])  # noqa: E731
    assert titles("") == ["de gnl", "de libft", "general"]
    assert titles("?rank=2") == ["de libft", "general"]
    assert titles("?rank=3") == ["de gnl", "general"]
    assert titles("?rank=4") == ["general"]
    assert titles("?project_id=2&rank=2") == ["de gnl", "general"]                               # el proyecto concreto manda
    assert c.get("/api/help/resources?rank=100").status_code == 422 and c.get("/api/help/resources?rank=-1").status_code == 422


# ---------------------------------------------------------------- página

def test_help_page_has_a_circle_picker_and_a_requests_section_that_is_always_visible(engine, store):
    html = user(engine, store, 13).get("/ayuda").text
    assert 'id="rank-select"' in html and 'id="peticiones"' in html and 'href="#peticiones"' in html
    assert 'id="incoming-card"' not in html                                                      # ya no se esconde cuando está vacía
