"""Copias de seguridad: consistentes con WAL, comprobadas, rotadas y restaurables de verdad."""
import gzip
import sqlite3
import stat
import sys
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from stats42.backup import backup_databases, sqlite_file
from stats42.cli import app

NOW = datetime(2026, 10, 5, 4, 30, tzinfo=timezone.utc)


def make_db(path, rows=3, wal=True):
    con = sqlite3.connect(path)
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (v) VALUES (?)", [(f"fila {i}",) for i in range(rows)])
    con.commit()
    return con


def restore(gz, tmp_path):
    out = tmp_path / "restored.db"
    out.write_bytes(gzip.decompress(gz.read_bytes()))
    with sqlite3.connect(out) as con:
        return con.execute("PRAGMA integrity_check").fetchone()[0], [r[0] for r in con.execute("SELECT v FROM t ORDER BY id")]


def test_backup_restores_to_the_same_data_even_while_the_db_is_open_in_wal_mode(tmp_path):
    con = make_db(tmp_path / "stats42.db", rows=5)                    # conexión abierta y con WAL, como la sincronización
    con.execute("INSERT INTO t (v) VALUES ('tardía')")
    con.commit()
    made = backup_databases([f"sqlite:///{tmp_path / 'stats42.db'}"], tmp_path / "copias", keep=3, now=NOW)
    assert [m.name for m in made] == ["stats42-20261005-043000.db.gz"]
    verdict, rows = restore(made[0], tmp_path)
    assert verdict == "ok" and rows == [f"fila {i}" for i in range(5)] + ["tardía"]
    con.close()


def test_backups_are_private_and_leave_no_temp_files(tmp_path):
    make_db(tmp_path / "a.db").close()
    dest = tmp_path / "copias"
    (out,) = backup_databases([f"sqlite:///{tmp_path / 'a.db'}"], dest, now=NOW)
    if sys.platform != "win32":
        assert stat.S_IMODE(out.stat().st_mode) == 0o600 and stat.S_IMODE(dest.stat().st_mode) == 0o700
    assert [f.name for f in dest.iterdir()] == [out.name]


def test_only_the_newest_copies_of_each_database_are_kept(tmp_path):
    make_db(tmp_path / "stats42.db").close()
    make_db(tmp_path / "user_settings.db").close()
    urls = [f"sqlite:///{tmp_path / 'stats42.db'}", f"sqlite:///{tmp_path / 'user_settings.db'}"]
    dest = tmp_path / "copias"
    for d in range(5):
        backup_databases(urls, dest, keep=2, now=NOW + timedelta(days=d))
    names = sorted(f.name for f in dest.iterdir())
    assert names == ["stats42-20261008-043000.db.gz", "stats42-20261009-043000.db.gz",
                     "user_settings-20261008-043000.db.gz", "user_settings-20261009-043000.db.gz"]


def test_missing_and_non_sqlite_databases_are_skipped(tmp_path):
    make_db(tmp_path / "ok.db").close()
    made = backup_databases([f"sqlite:///{tmp_path / 'no_existe.db'}", "sqlite://", "postgresql://u:p@h/db", f"sqlite:///{tmp_path / 'ok.db'}"],
                            tmp_path / "copias", now=NOW)
    assert [m.name for m in made] == ["ok-20261005-043000.db.gz"]
    assert sqlite_file("sqlite://") is None and sqlite_file("postgresql://u:p@h/db") is None


def test_a_corrupt_source_fails_loudly_and_rotates_nothing(tmp_path):
    make_db(tmp_path / "stats42.db").close()
    dest = tmp_path / "copias"
    backup_databases([f"sqlite:///{tmp_path / 'stats42.db'}"], dest, keep=1, now=NOW)
    (tmp_path / "roto.db").write_bytes(b"esto no es una base de datos sqlite, solo basura " * 50)
    with pytest.raises(Exception):
        backup_databases([f"sqlite:///{tmp_path / 'roto.db'}"], dest, keep=1, now=NOW + timedelta(days=1))
    assert [f.name for f in dest.iterdir()] == ["stats42-20261005-043000.db.gz"]                 # la buena sigue ahí y no quedan temporales


def test_cli_backup_reports_files_and_fails_when_there_is_nothing_to_copy(tmp_path, monkeypatch):
    make_db(tmp_path / "stats42.db").close()
    monkeypatch.setenv("FT_DATABASE_URL", f"sqlite:///{tmp_path / 'stats42.db'}")
    monkeypatch.setenv("FT_SETTINGS_DATABASE_URL", f"sqlite:///{tmp_path / 'nada.db'}")
    ok = CliRunner().invoke(app, ["backup", "--dest", str(tmp_path / "c")])
    assert ok.exit_code == 0 and "stats42-" in ok.output and "nada" not in ok.output
    monkeypatch.setenv("FT_DATABASE_URL", "sqlite://")
    assert CliRunner().invoke(app, ["backup", "--dest", str(tmp_path / "c2")]).exit_code == 1
