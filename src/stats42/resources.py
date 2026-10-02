"""Qué se sincroniza de la API y cómo se traduce cada registro a una fila."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .config import Settings
from .db import Base, CursusUser, Project, ProjectUser, User


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def map_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "login": u["login"],
        "kind": u.get("kind"),
        "pool_year": u.get("pool_year"),
        "pool_month": u.get("pool_month"),
        "active": bool(u.get("active?")),
        "alumni": bool(u.get("alumni?")),
        "staff": bool(u.get("staff?")),
        "correction_point": u.get("correction_point"),
        "wallet": u.get("wallet"),
        "created_at": _dt(u.get("created_at")),
        "updated_at": _dt(u.get("updated_at")),
        "alumnized_at": _dt(u.get("alumnized_at")),
    }


def map_cursus_user(c: dict) -> dict:
    return {
        "id": c["id"],
        "user_id": c["user"]["id"],
        "cursus_id": c["cursus_id"],
        "level": c.get("level"),
        "begin_at": _dt(c.get("begin_at")),
        "end_at": _dt(c.get("end_at")),
        "blackholed_at": _dt(c.get("blackholed_at")),
        "has_coalition": c.get("has_coalition"),
        "created_at": _dt(c.get("created_at")),
        "updated_at": _dt(c.get("updated_at")),
    }


def map_project(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "slug": p["slug"],
        "difficulty": p.get("difficulty"),
        "exam": p.get("exam"),
    }


def map_project_user(pu: dict) -> dict:
    return {
        "id": pu["id"],
        "user_id": pu["user"]["id"],
        "project_id": pu["project"]["id"],
        "status": pu.get("status"),
        "final_mark": pu.get("final_mark"),
        "validated": pu.get("validated?"),
        "current_team_id": pu.get("current_team_id"),
        "cursus_ids": pu.get("cursus_ids"),
        "created_at": _dt(pu.get("created_at")),
        "marked_at": _dt(pu.get("marked_at")),
        "updated_at": _dt(pu.get("updated_at")),
    }


@dataclass(frozen=True)
class Resource:
    name: str
    path: str
    model: type[Base]
    mapper: Callable[[dict], dict]
    params: dict = field(default_factory=dict)
    incremental: bool = True  # admite range[updated_at]; si no, se recarga entero


def build_resources(s: Settings) -> dict[str, Resource]:
    rs = [
        Resource("users", f"/v2/campus/{s.campus_id}/users", User, map_user),
        Resource(
            "cursus_users", "/v2/cursus_users", CursusUser, map_cursus_user,
            {"filter[campus_id]": s.campus_id, "filter[cursus_id]": s.cursus_id},
        ),
        Resource(
            "projects", f"/v2/cursus/{s.cursus_id}/projects", Project, map_project,
            incremental=False,
        ),
        Resource(
            "project_users", "/v2/projects_users", ProjectUser, map_project_user,
            {"filter[campus]": s.campus_id},
        ),
    ]
    return {r.name: r for r in rs}
