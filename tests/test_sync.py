from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from stats42.db import ProjectUser, SyncState, User, init_db
from stats42.resources import Resource, map_project_user, map_user

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def user(i, **kw):
    return {"id": i, "login": f"u{i}", "kind": "student", "pool_year": "2025", "pool_month": "may",
            "active?": True, "alumni?": False, "staff?": False, "correction_point": 5, "wallet": 10,
            "created_at": "2026-01-01T10:00:00.000Z", "updated_at": "2026-09-01T10:00:00.000Z",
            "alumnized_at": None, **kw}


class FakeClient:
    """Imita FortyTwoClient.paginate sobre páginas predefinidas; puede fallar tras N páginas."""

    def __init__(self, pages, fail_after=None):
        self.pages, self.fail_after, self.calls = pages, fail_after, []

    def paginate(self, path, params=None, *, page_size=100, start_page=1):
        self.calls.append({"path": path, "params": params, "start_page": start_page})
        for n in range(start_page, len(self.pages) + 1):
            if self.fail_after is not None and n > self.fail_after:
                raise RuntimeError("corte de red")
            yield n, self.pages[n - 1]


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    return init_db(engine)


RES = Resource("users", "/v2/campus/22/users", User, map_user)


def count(factory, model):
    with factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_first_sync_loads_everything_and_sets_watermark(factory):
    from stats42.sync import sync_resource

    client = FakeClient([[user(1), user(2)], [user(3)]])
    r = sync_resource(factory, client, RES, now=NOW)
    assert r.rows == 3 and count(factory, User) == 3
    assert client.calls[0]["params"]["range[updated_at]"].startswith("2013-01-01")
    with factory() as s:
        st = s.get(SyncState, "users")
        assert st.status == "idle" and st.watermark == "2026-10-02T12:00:00Z"


def test_second_sync_is_incremental_with_overlap_and_idempotent(factory):
    from stats42.sync import sync_resource

    sync_resource(factory, FakeClient([[user(1), user(2)]]), RES, now=NOW)
    later = NOW + timedelta(days=1)
    client = FakeClient([[user(2, correction_point=99), user(3)]])
    sync_resource(factory, client, RES, now=later)
    assert client.calls[0]["params"]["range[updated_at]"] == "2026-10-01T12:00:00Z,2026-10-03T12:00:00Z"
    assert count(factory, User) == 3  # el 2 se actualiza, no se duplica
    with factory() as s:
        assert s.get(User, 2).correction_point == 99


def test_interrupted_sync_resumes_same_window_from_checkpoint(factory):
    from stats42.sync import sync_resource

    pages = [[user(1)], [user(2)], [user(3)]]
    with pytest.raises(RuntimeError):
        sync_resource(factory, FakeClient(pages, fail_after=1), RES, now=NOW)
    with factory() as s:
        st = s.get(SyncState, "users")
        assert st.status == "running" and st.next_page == 2

    client = FakeClient(pages)
    r = sync_resource(factory, client, RES, now=NOW + timedelta(hours=3))
    assert r.resumed and client.calls[0]["start_page"] == 2
    assert r.until == "2026-10-02T12:00:00Z"  # la ventana original, no la nueva
    assert count(factory, User) == 3


def test_full_flag_ignores_watermark(factory):
    from stats42.sync import sync_resource

    sync_resource(factory, FakeClient([[user(1)]]), RES, now=NOW)
    client = FakeClient([[user(1)]])
    sync_resource(factory, client, RES, full=True, now=NOW + timedelta(days=5))
    assert client.calls[0]["params"]["range[updated_at]"].startswith("2013-01-01")


def test_non_incremental_resource_sends_no_range(factory):
    from stats42.db import Project
    from stats42.resources import map_project
    from stats42.sync import sync_resource

    res = Resource("projects", "/v2/cursus/21/projects", Project, map_project, incremental=False)
    client = FakeClient([[{"id": 1, "name": "libft", "slug": "libft", "difficulty": 1000, "exam": False}]])
    sync_resource(factory, client, res, now=NOW)
    assert "range[updated_at]" not in client.calls[0]["params"]
    assert count(factory, Project) == 1


def test_map_user_drops_personal_fields():
    row = map_user(user(1, email="a@b.c", phone="123", first_name="X", last_name="Y"))
    assert not {"email", "phone", "first_name", "last_name"} & set(row)


def test_map_project_user_extracts_nested_ids():
    row = map_project_user({
        "id": 9, "user": {"id": 5}, "project": {"id": 7, "name": "libft"}, "status": "finished",
        "final_mark": 100, "validated?": True, "current_team_id": 3, "cursus_ids": [21],
        "created_at": "2026-09-01T10:00:00.000Z", "marked_at": "2026-09-03T10:00:00.000Z",
        "updated_at": "2026-09-03T10:00:00.000Z",
    })
    assert (row["user_id"], row["project_id"], row["validated"], row["cursus_ids"]) == (5, 7, True, [21])
    assert row["marked_at"].tzinfo is not None


def test_map_project_user_tolerates_missing_cursus_ids():
    row = map_project_user({"id": 1, "user": {"id": 5}, "project": {"id": 7}, "status": "in_progress"})
    assert row["cursus_ids"] == []


def test_file_engine_uses_wal_so_reader_does_not_block_writer(tmp_path):
    from sqlalchemy import text

    from stats42.db import make_engine

    eng = make_engine(f"sqlite:///{tmp_path / 'x.db'}")
    with eng.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA busy_timeout")).scalar() == 60000


def test_map_location_and_overlap_uses_begin_at(factory):
    from stats42.db import Location
    from stats42.resources import build_resources, map_location
    from stats42.config import Settings
    from stats42.sync import sync_resource

    row = map_location({"id": 1, "user": {"id": 5}, "host": "c3r5s1", "campus_id": 22, "primary": True,
                        "begin_at": "2026-10-02T16:39:00.000Z", "end_at": None})
    assert (row["user_id"], row["host"], row["end_at"]) == (5, "c3r5s1", None)

    res = build_resources(Settings(uid="u", secret="s"))["locations"]
    assert res.range_field == "begin_at"
    sync_resource(factory, FakeClient([[{"id": 1, "user": {"id": 5}, "host": "c1r1s1", "campus_id": 22,
                                         "primary": True, "begin_at": "2026-10-01T10:00:00.000Z", "end_at": None}]]),
                  res, now=NOW)
    client = FakeClient([[]])
    sync_resource(factory, client, res, now=NOW + timedelta(days=1))
    assert client.calls[0]["params"]["range[begin_at]"] == "2026-09-29T12:00:00Z,2026-10-03T12:00:00Z"
    assert count(factory, Location) == 1


def test_map_evaluation_handles_invisible_corrector_and_no_text():
    from stats42.resources import map_evaluation

    row = map_evaluation({
        "id": 9, "scale_id": 3, "corrector": "invisible", "team": {"id": 4, "project_id": 8},
        "flag": {"name": "Ok", "positive": True}, "truant": {}, "final_mark": 100,
        "comment": "texto privado", "feedback": "otro texto",
        "begin_at": "2026-10-02T16:00:00.000Z", "filled_at": None,
        "created_at": "2026-10-02T15:00:00.000Z", "updated_at": "2026-10-02T15:00:00.000Z",
    })
    assert row["corrector_id"] is None and row["project_id"] == 8 and row["truant"] is False
    assert "comment" not in row and "feedback" not in row


def test_map_event_and_exam():
    from stats42.resources import map_event, map_exam

    assert map_event({"id": 1, "name": "x", "kind": "event", "max_people": None, "nbr_subscribers": 3,
                      "begin_at": "2026-10-29T09:00:00.000Z"})["nbr_subscribers"] == 3
    assert map_exam({"id": 2, "name": "Exam Rank 02", "max_people": 90, "nbr_subscribers": 0,
                     "begin_at": "2026-10-29T09:00:00.000Z"})["max_people"] == 90
