from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from stats42.audit import audit_resource, served_rows
from stats42.db import Location, User, init_db
from stats42.resources import Resource, map_user

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class Resp:
    def __init__(self, items, total):
        self._items, self.headers = items, {"X-Total": str(total)}

    def json(self):
        return self._items


class FakeApi:
    """API que anuncia `announced` filas en X-Total pero solo entrega `visible` (como la real)."""

    def __init__(self, visible, announced):
        self.rows, self.announced, self.calls = list(range(visible)), announced, 0

    def get(self, path, params=None):
        self.calls += 1
        size, page = params["page[size]"], params.get("page[number]", 1)
        return Resp(self.rows[(page - 1) * size: page * size], self.announced)


@pytest.fixture
def factory():
    return init_db(create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}))


def fill(factory, n):
    from stats42.db import upsert

    row = {"login": "x", "kind": "student", "pool_year": "2025", "pool_month": "may", "active": True, "alumni": False,
           "staff": False, "correction_point": 1, "wallet": 1, "created_at": None, "updated_at": None, "alumnized_at": None}
    with factory() as s:
        upsert(s, User, [{**row, "id": i} for i in range(n)])
        s.commit()


RES = Resource("users", "/v2/campus/22/users", User, map_user)


@pytest.mark.parametrize("visible,announced", [(0, 0), (1, 1), (99, 99), (100, 100), (101, 130), (1146 * 100 + 38, 156481)])
def test_served_rows_finds_what_the_api_really_delivers(visible, announced):
    api = FakeApi(visible, announced)
    total, served = served_rows(api, RES, {})
    assert (total, served) == (announced, visible)
    assert api.calls < 30  # bisección: no recorre todas las páginas


def test_audit_complete_even_when_api_hides_rows(factory):
    fill(factory, 250)
    r = audit_resource(factory, FakeApi(visible=250, announced=400), RES, NOW)
    assert (r.api_total, r.served, r.in_db, r.hidden, r.missing, r.ok) == (400, 250, 250, 150, 0, True)


def test_audit_detects_missing_rows(factory):
    fill(factory, 100)
    r = audit_resource(factory, FakeApi(visible=5000, announced=5000), RES, NOW)
    assert r.missing == 4900 and not r.ok


def test_audit_tolerates_small_drift_while_syncing(factory):
    fill(factory, 4990)
    assert audit_resource(factory, FakeApi(visible=5000, announced=5000), RES, NOW).ok


def test_audit_windowed_resource_only_counts_recent_rows(factory):
    from stats42.db import upsert

    with factory() as s:
        upsert(s, Location, [
            {"id": 1, "user_id": 1, "host": "c1r1s1", "campus_id": 22, "is_primary": True,
             "begin_at": NOW - timedelta(days=10), "end_at": None},
            {"id": 2, "user_id": 1, "host": "c1r1s1", "campus_id": 22, "is_primary": True,
             "begin_at": NOW - timedelta(days=900), "end_at": None},   # fuera de la ventana de 400 días
        ])
        s.commit()
    res = Resource("locations", "/v2/campus/22/locations", Location, lambda x: x, range_field="begin_at",
                   initial_lookback=timedelta(days=400))
    api = FakeApi(visible=1, announced=1)
    row = audit_resource(factory, api, res, NOW)
    assert row.windowed and row.in_db == 1 and row.ok
