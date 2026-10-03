"""Qué se sincroniza de la API y cómo se traduce cada registro a una fila."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import Settings
from .db import Base, CursusUser, Evaluation, Event, Exam, Location, Project, ProjectUser, User


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
        "cursus_ids": pu.get("cursus_ids") or [],  # la columna ya existente en la VM es NOT NULL
        "created_at": _dt(pu.get("created_at")),
        "marked_at": _dt(pu.get("marked_at")),
        "updated_at": _dt(pu.get("updated_at")),
    }


def map_location(l: dict) -> dict:
    return {
        "id": l["id"],
        "user_id": l["user"]["id"],
        "host": l.get("host"),
        "campus_id": l.get("campus_id"),
        "is_primary": l.get("primary"),
        "begin_at": _dt(l.get("begin_at")),
        "end_at": _dt(l.get("end_at")),
    }


def map_evaluation(e: dict) -> dict:
    # corrector puede venir como "invisible" en vez de un objeto
    corrector = e.get("corrector") if isinstance(e.get("corrector"), dict) else {}
    team = e.get("team") if isinstance(e.get("team"), dict) else {}
    flag = e.get("flag") if isinstance(e.get("flag"), dict) else {}
    return {
        "id": e["id"],
        "corrector_id": corrector.get("id"),
        "team_id": team.get("id"),
        "project_id": team.get("project_id"),
        "scale_id": e.get("scale_id"),
        "final_mark": e.get("final_mark"),
        "flag_name": flag.get("name"),
        "flag_positive": flag.get("positive"),
        "truant": bool(e.get("truant")),
        "begin_at": _dt(e.get("begin_at")),
        "filled_at": _dt(e.get("filled_at")),
        "created_at": _dt(e.get("created_at")),
        "updated_at": _dt(e.get("updated_at")),
    }


def map_event(e: dict) -> dict:
    return {
        "id": e["id"],
        "name": e.get("name"),
        "kind": e.get("kind"),
        "location": e.get("location"),
        "max_people": e.get("max_people"),
        "nbr_subscribers": e.get("nbr_subscribers"),
        "begin_at": _dt(e.get("begin_at")),
        "end_at": _dt(e.get("end_at")),
        "created_at": _dt(e.get("created_at")),
        "updated_at": _dt(e.get("updated_at")),
    }


def map_exam(x: dict) -> dict:
    return {
        "id": x["id"],
        "name": x.get("name"),
        "location": x.get("location"),
        "max_people": x.get("max_people"),
        "nbr_subscribers": x.get("nbr_subscribers"),
        "begin_at": _dt(x.get("begin_at")),
        "end_at": _dt(x.get("end_at")),
        "created_at": _dt(x.get("created_at")),
        "updated_at": _dt(x.get("updated_at")),
    }


@dataclass(frozen=True)
class Resource:
    name: str
    path: str
    model: type[Base]
    mapper: Callable[[dict], dict]
    params: dict = field(default_factory=dict)
    incremental: bool = True  # admite range[<range_field>]; si no, se recarga entero
    range_field: str = "updated_at"
    overlap: timedelta = timedelta(days=1)  # solape con la ejecución anterior
    # Primera carga: solo este periodo hacia atrás (None = todo). `sync --full` lo ignora.
    initial_lookback: timedelta | None = None


def build_resources(s: Settings) -> dict[str, Resource]:
    # Orden de menor a mayor volumen: un fallo en los grandes no bloquea a los pequeños.
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
        Resource("events", f"/v2/campus/{s.campus_id}/events", Event, map_event, incremental=False),
        Resource("exams", f"/v2/campus/{s.campus_id}/exams", Exam, map_exam, incremental=False),
        Resource(
            "project_users", "/v2/projects_users", ProjectUser, map_project_user,
            {"filter[campus]": s.campus_id},
        ),
        Resource(
            "evaluations", "/v2/scale_teams", Evaluation, map_evaluation,
            {"filter[campus_id]": s.campus_id},
        ),
        # Las sesiones terminan después de empezar: se filtra por inicio, con solape de 3 días.
        Resource(
            "locations", f"/v2/campus/{s.campus_id}/locations", Location, map_location,
            range_field="begin_at", overlap=timedelta(days=3),
            initial_lookback=timedelta(days=400),  # 750.000 sesiones en total; las stats usan lo reciente
        ),
    ]
    return {r.name: r for r in rs}
