"""Copias de seguridad de las bases SQLite: instantánea consistente (aunque la sincronización esté escribiendo), comprobada y rotada."""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url


def sqlite_file(url: str) -> Path | None:
    u = make_url(url)
    if u.get_backend_name() != "sqlite" or not u.database or u.database == ":memory:":
        return None
    return Path(u.database)


def backup_one(src: Path, dest: Path, stamp: str) -> Path:
    """Copia `src` con la API de copias de SQLite (consistente con WAL), comprueba la copia y la guarda comprimida."""
    tmp = dest / f".{src.stem}-{stamp}.tmp"
    out = dest / f"{src.stem}-{stamp}.db.gz"
    try:
        with closing(sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True, timeout=60)) as s, closing(sqlite3.connect(tmp)) as d:
            s.backup(d)
            verdict = d.execute("PRAGMA integrity_check").fetchone()[0]
        if verdict != "ok":
            raise RuntimeError(f"{src.name}: la copia no pasa la comprobación de integridad ({verdict})")
        with open(tmp, "rb") as f, gzip.open(out, "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g)
        os.chmod(out, 0o600)
        return out
    finally:
        tmp.unlink(missing_ok=True)


def rotate(dest: Path, stem: str, keep: int) -> list[Path]:
    """Deja solo las `keep` copias más recientes de cada base (el nombre lleva la fecha, así que ordenar por nombre basta)."""
    files = sorted(dest.glob(f"{stem}-*.db.gz"))
    old = files[:-keep] if keep > 0 else files
    for f in old:
        f.unlink()
    return old


def backup_databases(urls: list[str], dest: Path, keep: int = 14, now: datetime | None = None) -> list[Path]:
    """Una copia por cada base SQLite que exista. Una base que falta se salta; una copia corrupta lanza error (y no rota nada)."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    made = []
    for url in urls:
        src = sqlite_file(url)
        if src is None or not src.exists():
            continue
        made.append(backup_one(src, dest, stamp))
        rotate(dest, src.stem, keep)
    return made
