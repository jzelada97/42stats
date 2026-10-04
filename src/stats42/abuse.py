"""Registro de quién choca con los límites de ritmo: para que un admin vea patrones, sin bloquear a nadie automáticamente."""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AbuseEvent

log = logging.getLogger("stats42.abuse")
FLUSH_EVERY = 10.0      # segundos: bajo un ataque se escribe una vez cada tanto, no una por petición rechazada


class AbuseRecorder:
    def __init__(self, settings_db):
        self.settings_db = settings_db
        self.pending: dict[tuple[int, str], dict] = {}     # (uid, tipo) -> golpes sin volcar y última escritura
        self.lock = threading.Lock()

    def note(self, uid: int, login: str, kind: str) -> None:
        key, now = (uid, kind), time.monotonic()
        with self.lock:
            e = self.pending.setdefault(key, {"hits": 0, "flushed": -FLUSH_EVERY})
            e["hits"] += 1
            if now - e["flushed"] < FLUSH_EVERY:
                return
            hits, e["hits"], e["flushed"] = e["hits"], 0, now
        login = re.sub(r"[^A-Za-z0-9_-]", "?", login or "")[:50]
        log.warning("límite alcanzado: uid=%s login=%s tipo=%s golpes=%s", uid, login, kind, hits)
        stamp = datetime.now(timezone.utc)
        try:
            with Session(self.settings_db()) as db:
                row = db.get(AbuseEvent, (uid, kind)) or AbuseEvent(user_id=uid, kind=kind, hits=0, first_at=stamp)
                row.login, row.hits, row.last_at = login, (row.hits or 0) + hits, stamp
                db.add(row)
                db.commit()
        except Exception as exc:        # el registro nunca debe romper la petición que ya se está rechazando
            log.warning("no se pudo guardar el aviso de límite (%s)", type(exc).__name__)

    def recent(self, db: Session, limit: int = 50) -> list[dict]:
        rows = db.execute(select(AbuseEvent).order_by(AbuseEvent.last_at.desc()).limit(limit)).scalars().all()
        return [{"login": r.login, "kind": r.kind, "hits": r.hits,
                 "first": r.first_at.date().isoformat() if r.first_at else None,
                 "last": r.last_at.isoformat(timespec="minutes") if r.last_at else None} for r in rows]
