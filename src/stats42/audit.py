"""Auditoría: ¿lo que hay en la base de datos es todo lo que la API sirve?

`X-Total` de la API cuenta filas que luego no entrega (p. ej. datos de cuentas anonimizadas), así que no sirve
para comprobar la carga. Se mide lo que la API realmente sirve buscando por bisección la última página con datos.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .client import FortyTwoClient
from .resources import Resource


@dataclass
class AuditRow:
    resource: str
    api_total: int   # lo que anuncia X-Total
    served: int      # lo que la API realmente entrega
    in_db: int
    windowed: bool   # el recurso solo se carga en parte (initial_lookback)

    @property
    def hidden(self) -> int:
        return max(self.api_total - self.served, 0)

    @property
    def missing(self) -> int:
        return max(self.served - self.in_db, 0)

    @property
    def tolerance(self) -> int:
        # los datos siguen cambiando mientras se audita: se admite un 0,1 % (mínimo 50 filas)
        return max(50, self.served // 1000)

    @property
    def ok(self) -> bool:
        return self.missing <= self.tolerance


def served_rows(client: FortyTwoClient, res: Resource, params: dict) -> tuple[int, int]:
    """(X-Total, filas que la API entrega de verdad) con ~log2(páginas) peticiones."""
    p = {**params, "sort": "id", "page[size]": 100}
    total = int(client.get(res.path, {**p, "page[size]": 1}).headers.get("X-Total") or 0)
    if total == 0:
        return 0, 0
    lo, hi = 1, (total + 99) // 100 + 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if client.get(res.path, {**p, "page[number]": mid}).json():
            lo = mid
        else:
            hi = mid - 1
    last = len(client.get(res.path, {**p, "page[number]": lo}).json())
    return total, (lo - 1) * 100 + last


def audit_resource(factory: sessionmaker[Session], client: FortyTwoClient, res: Resource,
                   now: datetime | None = None) -> AuditRow:
    now = now or datetime.now(timezone.utc)
    params = dict(res.params)
    where = []
    windowed = bool(res.initial_lookback and res.incremental)
    if windowed:  # recursos con primera carga limitada: se compara solo esa ventana
        since = now - res.initial_lookback
        params[f"range[{res.range_field}]"] = f"{since:%Y-%m-%dT%H:%M:%SZ},{now:%Y-%m-%dT%H:%M:%SZ}"
        where.append(getattr(res.model, res.range_field) >= since.replace(tzinfo=None))
    api_total, served = served_rows(client, res, params)
    with factory() as s:
        in_db = s.scalar(select(func.count()).select_from(res.model).where(*where)) or 0
    return AuditRow(res.name, api_total, served, in_db, windowed)
