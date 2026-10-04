"""Modelo de datos. Solo guardamos lo necesario para las stats (sin email, teléfono ni nombres)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Float, Index, Integer, String, UniqueConstraint, create_engine, event
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.engine import make_url


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    login: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str | None]
    pool_year: Mapped[str | None] = mapped_column(String, index=True)
    pool_month: Mapped[str | None]
    active: Mapped[bool]
    alumni: Mapped[bool]
    staff: Mapped[bool]
    correction_point: Mapped[int | None]
    wallet: Mapped[int | None]
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alumnized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CursusUser(Base):
    __tablename__ = "cursus_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    cursus_id: Mapped[int] = mapped_column(Integer, index=True)
    level: Mapped[float | None] = mapped_column(Float)
    begin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blackholed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    has_coalition: Mapped[bool | None]
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str]
    slug: Mapped[str] = mapped_column(String, index=True)
    difficulty: Mapped[int | None]
    exam: Mapped[bool | None]
    cursus_ids: Mapped[Any | None] = mapped_column(JSON)
    cursus_names: Mapped[str | None]  # p. ej. "42cursus, Python Piscine"


class ProjectUser(Base):
    __tablename__ = "project_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str | None] = mapped_column(String, index=True)
    final_mark: Mapped[int | None]
    validated: Mapped[bool | None]
    current_team_id: Mapped[int | None]
    cursus_ids: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_project_users_user_project", "user_id", "project_id"),)


class Location(Base):
    """Sesión de ordenador en el campus (un login en un puesto de un cluster)."""

    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    host: Mapped[str | None]  # p. ej. c3r5s1 = cluster 3, fila 5, puesto 1
    campus_id: Mapped[int | None]
    is_primary: Mapped[bool | None]
    begin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Evaluation(Base):
    """Evaluación entre alumnos (scale_team). No se guardan comentarios ni feedback de texto."""

    __tablename__ = "evaluations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    corrector_id: Mapped[int | None] = mapped_column(Integer, index=True)
    team_id: Mapped[int | None]
    project_id: Mapped[int | None] = mapped_column(Integer, index=True)
    scale_id: Mapped[int | None]
    final_mark: Mapped[int | None]
    flag_name: Mapped[str | None] = mapped_column(String, index=True)
    flag_positive: Mapped[bool | None]
    truant: Mapped[bool | None]
    begin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str | None]
    kind: Mapped[str | None] = mapped_column(String, index=True)
    location: Mapped[str | None]
    max_people: Mapped[int | None]
    nbr_subscribers: Mapped[int | None]
    begin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Exam(Base):
    __tablename__ = "exams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str | None]
    location: Mapped[str | None]
    max_people: Mapped[int | None]
    nbr_subscribers: Mapped[int | None]
    begin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Quest(Base):
    """Misión del cursus; en el currículo nuevo los milestones son los "Common Core Rank 00..05"."""

    __tablename__ = "quests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str | None]
    slug: Mapped[str | None]
    kind: Mapped[str | None]
    internal_name: Mapped[str | None]
    cursus_id: Mapped[int | None] = mapped_column(Integer, index=True)
    position: Mapped[int | None]


class QuestUser(Base):
    __tablename__ = "quest_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    quest_id: Mapped[int] = mapped_column(Integer, index=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_quest_users_user_quest", "user_id", "quest_id"),)


class UserSetting(Base):
    """Datos que el propio alumno indica (42 no los expone): se guardan en una base aparte, escribible por la web."""

    __tablename__ = "user_settings"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    deadline: Mapped[date | None] = mapped_column(Date)
    freeze_until: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningResource(Base):
    """Guía, documentación, vídeo o herramienta para estudiar un proyecto. Nunca soluciones: se aprueba a mano."""

    __tablename__ = "learning_resources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True)   # None = general
    title: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20))
    submitted_by: Mapped[int] = mapped_column(Integer, index=True)
    submitted_login: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)   # pending | approved | rejected
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(Integer)


class MentorOffer(Base):
    """Un alumno que se ofrece a ayudar. Solo se muestra si sigue teniendo validados los proyectos que ofrece."""

    __tablename__ = "mentor_offers"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    login: Mapped[str] = mapped_column(String(50))
    note: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(default=True, index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MentorProject(Base):
    __tablename__ = "mentor_projects"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    project_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)


class HelpRequest(Base):
    __tablename__ = "help_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    login: Mapped[str] = mapped_column(String(50))
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    message: Mapped[str] = mapped_column(String(280))
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)   # open | closed
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AbuseEvent(Base):
    """Quién ha chocado con un límite de ritmo y cuántas veces. Solo uid y login (nunca IP), y se purga a los 30 días."""

    __tablename__ = "abuse_events"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    kind: Mapped[str] = mapped_column(String(30), primary_key=True)
    login: Mapped[str] = mapped_column(String(50))
    hits: Mapped[int] = mapped_column(Integer, default=0)
    first_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class MentorThanks(Base):
    """Un alumno agradece la ayuda de un mentor al cerrar su petición. Cuenta como punto cuando se VERIFICA (ver points.py)."""

    __tablename__ = "mentor_thanks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asker_uid: Mapped[int] = mapped_column(Integer, index=True)       # negativo (= -id) si quien agradeció borró sus datos
    mentor_uid: Mapped[int] = mapped_column(Integer, index=True)
    project_id: Mapped[int] = mapped_column(Integer)
    asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # cuándo pidió ayuda: la validación debe ser posterior
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified: Mapped[bool] = mapped_column(default=False, index=True)       # el alumno validó el proyecto dentro de la ventana
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed: Mapped[bool] = mapped_column(default=False)                  # el mentor confirmó que explicó sin dar código
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False)                    # anulado por un admin: no cuenta y no se puede repetir
    revoked_by: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (UniqueConstraint("asker_uid", "project_id", name="uq_thanks_asker_project"),)


class HelpOffer(Base):
    """"Quiero ayudar": un mentor se ofrece a una petición concreta. Solo se puede agradecer a quien se ofreció."""

    __tablename__ = "help_offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(Integer, index=True)
    mentor_uid: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("request_id", "mentor_uid", name="uq_offer_request_mentor"),)


class MailPref(Base):
    """Quien ha activado los avisos por correo. Existir = tener los avisos activados; desactivarlos borra la fila (y la dirección)."""

    __tablename__ = "mail_prefs"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    email: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_day: Mapped[date | None] = mapped_column(Date)             # tope diario de correos por destinatario
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    last_digest: Mapped[date | None] = mapped_column(Date)


class LoginRecord(Base):
    """Quién ha entrado a la web: una fila por alumno (primer y último acceso y cuántos). Sin IP; se purga a los 90 días."""

    __tablename__ = "login_records"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    login: Mapped[str] = mapped_column(String(50))
    first_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    logins: Mapped[int] = mapped_column(Integer, default=0)


class UserSession(Base):
    """Sesión abierta con 42. La cookie solo lleva el id: si la fila desaparece (salir, caducar), la cookie deja de valer."""

    __tablename__ = "user_sessions"
    sid: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Tablas de la base escribible de la web (la del campus es de solo lectura para ella).
def user_data_tables():
    return [UserSetting.__table__, LearningResource.__table__, MentorOffer.__table__, MentorProject.__table__,
            HelpRequest.__table__, UserSession.__table__, AbuseEvent.__table__,
            LoginRecord.__table__, MentorThanks.__table__, HelpOffer.__table__, MailPref.__table__]


class SyncState(Base):
    """Estado de sincronización por recurso: marca de agua y checkpoint para reanudar."""

    __tablename__ = "sync_state"
    resource: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="idle")  # idle | running
    watermark: Mapped[str | None]  # ISO UTC hasta donde está sincronizado
    window_since: Mapped[str | None]
    window_until: Mapped[str | None]
    next_page: Mapped[int] = mapped_column(Integer, default=1)
    last_run_at: Mapped[str | None]
    last_count: Mapped[int | None]


def make_engine(url: str) -> Engine:
    u = make_url(url)
    engine = create_engine(url)
    if u.get_backend_name() == "sqlite" and u.database and u.database != ":memory:":
        Path(u.database).parent.mkdir(parents=True, exist_ok=True)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(conn, _):
            # WAL: la API lee sin bloquear a la sincronización que escribe.
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=60000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return engine


def make_readonly_engine(url: str) -> Engine:
    """Motor de solo lectura para la API: no puede modificar la BD mientras la sincronización escribe."""
    u = make_url(url)
    if u.get_backend_name() != "sqlite" or not u.database or u.database == ":memory:":
        return create_engine(url)
    path = Path(u.database).resolve().as_posix()
    # NullPool: una conexión nueva por petición. Con el pool por defecto de "sqlite://" (SingletonThreadPool,
    # tope de 5) la API cerraba conexiones aún en uso por otros hilos y el intérprete moría con SIGSEGV.
    # check_same_thread=False: FastAPI abre la sesión en un hilo y ejecuta el endpoint en otro. Es seguro porque
    # cada conexión pertenece a una sola petición y nunca se usa de forma simultánea.
    return create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30, check_same_thread=False),
        poolclass=NullPool,
    )


def add_missing_columns(engine: Engine) -> list[str]:
    """create_all no altera tablas existentes: añade las columnas nuevas (siempre opcionales) que falten."""
    from sqlalchemy import inspect, text

    added = []
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have and col.nullable:
                ddl = col.type.compile(dialect=engine.dialect)
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))
                added.append(f"{table.name}.{col.name}")
    return added


def init_db(engine: Engine) -> sessionmaker[Session]:
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    return sessionmaker(engine, expire_on_commit=False)


def upsert(session: Session, model: type[Base], rows: list[dict]) -> None:
    """INSERT ... ON CONFLICT DO UPDATE por clave primaria (SQLite y PostgreSQL)."""
    if not rows:
        return
    ins = (pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert)(model)
    pk = [c.name for c in model.__table__.primary_key.columns]
    update = {c.name: ins.excluded[c.name] for c in model.__table__.columns if c.name not in pk}
    session.execute(ins.on_conflict_do_update(index_elements=pk, set_=update), rows)
