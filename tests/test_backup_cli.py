"""Sicherung von der Kommandozeile (nächtlicher Lauf auf der NAS)."""
import json
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import backup_cli
from src.lib.backup import BACKUP_PREFIX


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Echte DB + Materialordner, wie sie im Container liegen."""
    db = tmp_path / "data.db"
    storage = tmp_path / "storage"
    (storage / "Deutsch").mkdir(parents=True)
    (storage / "Deutsch" / "Übung_Größe.txt").write_text("äöüß", encoding="utf-8")
    from src.db import init_db
    init_db(str(db)).close()
    # settings ist eine frozene Dataclass - deshalb das Modul-Attribut ersetzen,
    # nicht einzelne Felder patchen.
    monkeypatch.setattr(backup_cli, "settings",
                        SimpleNamespace(db_path=str(db), storage_root=str(storage)))
    return tmp_path


def test_writes_a_restorable_backup(cli_env, capsys):
    ziel = cli_env / "backups"
    assert backup_cli.main([str(ziel)]) == 0

    zips = list(ziel.glob("*.zip"))
    assert len(zips) == 1
    zf = zipfile.ZipFile(zips[0])
    assert "data.db" in zf.namelist()
    assert "storage/Deutsch/Übung_Größe.txt" in zf.namelist()   # Umlaute erhalten

    restored = cli_env / "restored.db"
    restored.write_bytes(zf.read("data.db"))
    conn = sqlite3.connect(str(restored))
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()
    assert "Sicherung geschrieben" in capsys.readouterr().out


def test_can_skip_materials(cli_env):
    ziel = cli_env / "backups"
    backup_cli.main([str(ziel), "--ohne-materialien"])
    zf = zipfile.ZipFile(next(ziel.glob("*.zip")))
    assert [n for n in zf.namelist() if n.startswith("storage/")] == []
    assert json.loads(zf.read("manifest.json"))["includesStorage"] is False


def test_two_runs_in_the_same_minute_do_not_overwrite(cli_env):
    """Der Dateiname hat nur Minutenauflösung - zwei Läufe müssen trotzdem zwei
    Sicherungen ergeben, sonst verschwindet die erste unbemerkt."""
    ziel = cli_env / "backups"
    backup_cli.main([str(ziel)])
    backup_cli.main([str(ziel)])
    zips = sorted(p.name for p in ziel.glob("*.zip"))
    assert len(zips) == 2, zips
    assert zips[1].endswith("_2.zip")


def test_creates_the_target_folder(cli_env):
    ziel = cli_env / "gibt" / "es" / "noch" / "nicht"
    assert backup_cli.main([str(ziel)]) == 0
    assert list(ziel.glob("*.zip"))


# ---------- Aufraeumen: loescht Dateien, deshalb besonders eng gepruefte Zusagen ----------

def _alte_sicherungen(ordner: Path, n: int) -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        p = ordner / f"{BACKUP_PREFIX}2026-01-{i+1:02d}_0300.zip"
        p.write_text("alt")
        import os
        os.utime(p, (1_000_000 + i, 1_000_000 + i))   # aufsteigendes Alter


def test_cleanup_keeps_the_newest(cli_env):
    ordner = cli_env / "backups"
    _alte_sicherungen(ordner, 5)
    entfernt = backup_cli.cleanup(str(ordner), keep=2)
    assert len(entfernt) == 3
    assert len(list(ordner.glob("*.zip"))) == 2
    # die beiden juengsten sind geblieben
    assert {p.name for p in ordner.glob("*.zip")} == {
        f"{BACKUP_PREFIX}2026-01-05_0300.zip", f"{BACKUP_PREFIX}2026-01-04_0300.zip"}


def test_cleanup_never_touches_foreign_files(cli_env):
    """Kernzusage: nur eigene Sicherungen, nichts anderes im Ordner."""
    ordner = cli_env / "backups"
    _alte_sicherungen(ordner, 4)
    fremd = [ordner / "Klassenarbeit.pdf", ordner / "urlaub.zip",
             ordner / "backup-von-hand.zip", ordner / "wichtig.docx"]
    for f in fremd:
        f.write_text("nicht anfassen")

    backup_cli.cleanup(str(ordner), keep=1)
    for f in fremd:
        assert f.exists(), f"{f.name} wurde geloescht!"
    assert f.read_text() == "nicht anfassen"


def test_cleanup_off_by_default_value_zero(cli_env):
    ordner = cli_env / "backups"
    _alte_sicherungen(ordner, 3)
    assert backup_cli.cleanup(str(ordner), keep=0) == []
    assert len(list(ordner.glob("*.zip"))) == 3


def test_cleanup_is_not_recursive(cli_env):
    """Ein Unterordner darf nie mit ausgeraeumt werden."""
    ordner = cli_env / "backups"
    unter = ordner / "archiv"
    _alte_sicherungen(ordner, 3)
    _alte_sicherungen(unter, 3)
    backup_cli.cleanup(str(ordner), keep=1)
    assert len(list(unter.glob("*.zip"))) == 3
