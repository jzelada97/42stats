"""CLI: `stats42 check | sync | status | backup`."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import typer
from pydantic import ValidationError
from sqlalchemy import func, select

from .client import ApiError, FortyTwoClient
from .config import Settings
from .db import SyncState, init_db, make_engine
from .resources import build_resources
from .sync import sync_resource

app = typer.Typer(no_args_is_help=True, help="Sincroniza y analiza datos de 42 Madrid.")


def _settings() -> Settings:
    try:
        return Settings()
    except ValidationError:
        typer.secho("Faltan FT_UID y FT_SECRET (en el entorno o en .env). Mira .env.example.", fg="red")
        raise typer.Exit(1)


def _client(s: Settings) -> FortyTwoClient:
    return FortyTwoClient(s.uid, s.secret, base_url=s.api_base, user_agent=s.user_agent)


@app.command()
def check(
    total: bool = typer.Option(False, "--total", help="Sin filtro de fechas: total de registros y nº de peticiones de la carga."),
) -> None:
    """Prueba cada recurso con 1 petición: comprueba filtros y muestra el nº de registros."""
    s = _settings()
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _client(s) as c:
        for r in build_resources(s).values():
            params = {**r.params, "sort": "id", "page[size]": 1}
            if r.incremental and not total:
                params[f"range[{r.range_field}]"] = f"{since},{until}"
            try:
                n = c.get(r.path, params).headers.get("X-Total")
                what = "total" if (total or not r.incremental) else "últimas 24 h"
                pages = f" · ~{-(-int(n) // 100)} peticiones" if total and n and n.isdigit() else ""
                typer.secho(f"OK   {r.name:<14} {what}: {n}{pages}", fg="green")
            except ApiError as e:
                typer.secho(f"FAIL {r.name:<14} {e}", fg="red")


@app.command()
def sync(
    resources: Optional[list[str]] = typer.Argument(None, help="Recursos (por defecto, todos)."),
    full: bool = typer.Option(False, "--full", help="Ignora la marca de agua y recarga todo."),
    verbose: bool = typer.Option(False, "-v"),
) -> None:
    """Sincroniza los recursos con la base de datos (incremental y reanudable)."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # una línea por petición es demasiado ruido
    s = _settings()
    factory = init_db(make_engine(s.database_url))
    available = build_resources(s)
    names = resources or list(available)
    unknown = [n for n in names if n not in available]
    if unknown:
        typer.secho(f"Recursos desconocidos: {unknown}. Disponibles: {list(available)}", fg="red")
        raise typer.Exit(1)
    failed = []
    with _client(s) as c:
        for n in names:
            try:
                r = sync_resource(factory, c, available[n], full=full)
            except ApiError as e:  # un recurso roto no debe frenar a los demás
                typer.secho(f"{n}: FALLÓ ({e})", fg="red")
                failed.append(n)
                continue
            tag = " (reanudado)" if r.resumed else ""
            typer.echo(f"{r.resource}: {r.rows} filas{tag}  ventana {r.since} → {r.until}")
        typer.echo(f"Peticiones: {c.requests}")
    if failed:
        typer.secho(f"Recursos con error: {failed}", fg="red")
        raise typer.Exit(1)


@app.command()
def audit(
    resources: Optional[list[str]] = typer.Argument(None, help="Recursos (por defecto, todos)."),
) -> None:
    """Compara la base de datos con lo que la API realmente sirve (no con X-Total, que sobreestima)."""
    from .audit import audit_resource

    s = _settings()
    factory = init_db(make_engine(s.database_url))
    available = build_resources(s)
    names = resources or list(available)
    bad = False
    typer.echo(f"{'recurso':<14}{'X-Total':>9}{'sirve API':>11}{'en BD':>9}{'ocultas':>9}{'faltan':>8}  veredicto")
    with _client(s) as c:
        for n in names:
            try:
                r = audit_resource(factory, c, available[n])
            except ApiError as e:
                typer.secho(f"{n:<14}FALLÓ ({e})", fg="red")
                bad = True
                continue
            verdict = "completo" if r.ok else "INCOMPLETO"
            note = " (ventana reciente)" if r.windowed else ""
            typer.secho(f"{r.resource:<14}{r.api_total:>9}{r.served:>11}{r.in_db:>9}{r.hidden:>9}{r.missing:>8}  {verdict}{note}",
                        fg="green" if r.ok else "red")
            bad |= not r.ok
    typer.echo("«ocultas» = filas que la API cuenta en X-Total pero no entrega; no se pueden cargar.")
    if bad:
        raise typer.Exit(1)


@app.command()
def backup(
    dest: Path = typer.Option(..., "--dest", help="Carpeta donde guardar las copias."),
    keep: int = typer.Option(14, "--keep", min=1, help="Copias que se conservan de cada base."),
) -> None:
    """Copia la base del campus y la de ajustes de usuarios (comprobada, comprimida y rotada)."""
    from .backup import backup_databases

    urls = [os.environ.get("FT_DATABASE_URL", "sqlite:///data/stats42.db"),
            os.environ.get("FT_SETTINGS_DATABASE_URL", "sqlite:///data/user_settings.db")]
    try:
        made = backup_databases(urls, dest, keep)
    except Exception as e:      # una copia mala debe hacer fallar el servicio para que el timer lo deje registrado
        typer.secho(f"Copia FALLIDA: {e}", fg="red")
        raise typer.Exit(1)
    if not made:
        typer.secho("No hay ninguna base SQLite que copiar.", fg="red")
        raise typer.Exit(1)
    for f in made:
        typer.echo(f"{f.name}  {f.stat().st_size / 1e6:.1f} MB")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Dirección de escucha."),  # nosec B104: en el contenedor; el puerto no se publica en el host
    port: int = typer.Option(8042, help="Puerto (dentro del contenedor; no se publica en el host)."),
) -> None:
    """Arranca la API y la web (solo lectura sobre la base de datos)."""
    import uvicorn

    uvicorn.run("stats42.api:app", host=host, port=port, access_log=False, proxy_headers=True,
                forwarded_allow_ips="*")


@app.command()
def status() -> None:
    """Muestra el estado de sincronización y el nº de filas por tabla."""
    s = _settings()
    factory = init_db(make_engine(s.database_url))
    resources = build_resources(s)
    with factory() as sess:
        states = {st.resource: st for st in sess.scalars(select(SyncState))}
        for name, r in resources.items():
            n = sess.scalar(select(func.count()).select_from(r.model))
            st = states.get(name)
            info = f"{st.status}, marca de agua {st.watermark}, última ejecución {st.last_run_at}" if st else "sin sincronizar"
            typer.echo(f"{name:<14} {n:>8} filas · {info}")
