"""Sincronización incremental y reanudable de la API de 42 a la base de datos.

Cada ejecución trabaja sobre una ventana fija [since, until] de `updated_at`:
  - since = marca de agua anterior menos 1 día de solape (o el inicio si es la 1ª vez)
  - until = momento de arrancar
Tras cada página se guarda un checkpoint (`next_page`); si el proceso se corta,
la siguiente ejecución retoma la misma ventana donde se quedó. Los upserts son
idempotentes, así que repetir páginas no duplica nada.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from .client import FortyTwoClient
from .db import SyncState, upsert
from .resources import Resource

log = logging.getLogger(__name__)

EPOCH = "2013-01-01T00:00:00Z"  # anterior a la existencia de 42
OVERLAP = timedelta(days=1)


@dataclass
class SyncResult:
    resource: str
    rows: int
    resumed: bool
    since: str
    until: str


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def sync_resource(
    factory: sessionmaker[Session],
    client: FortyTwoClient,
    res: Resource,
    *,
    full: bool = False,
    now: datetime | None = None,
) -> SyncResult:
    now = now or datetime.now(timezone.utc)

    with factory() as s:
        st = s.get(SyncState, res.name) or SyncState(resource=res.name, status="idle", next_page=1)
        resumed = st.status == "running" and bool(st.window_until) and not full
        if resumed:
            since, until, page = st.window_since, st.window_until, st.next_page
        else:
            since = EPOCH if (full or not st.watermark) else _iso(_parse(st.watermark) - OVERLAP)
            until, page = _iso(now), 1
            st.status, st.window_since, st.window_until, st.next_page = "running", since, until, 1
        s.add(st)
        s.commit()

    params = {**res.params, "sort": "id"}
    if res.incremental:
        params["range[updated_at]"] = f"{since},{until}"

    total = 0
    for pg, items in client.paginate(res.path, params, start_page=page):
        rows = [res.mapper(i) for i in items]
        with factory() as s:
            upsert(s, res.model, rows)
            s.get(SyncState, res.name).next_page = pg + 1
            s.commit()
        total += len(rows)
        log.info("%s: página %d (%d filas)", res.name, pg, total)

    with factory() as s:
        st = s.get(SyncState, res.name)
        st.status, st.watermark, st.next_page = "idle", until, 1
        st.last_run_at, st.last_count = _iso(now), total
        s.commit()
    return SyncResult(res.name, total, resumed, since, until)
