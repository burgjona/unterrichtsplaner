"""Konsistente Sicherung von Datenbank und Materialablage.

Warum nicht einfach data.db kopieren: die DB läuft im WAL-Modus (db.connect),
d.h. frisch geschriebene Seiten stehen noch in data.db-wal. Eine bloße Dateikopie
kann deshalb einen unvollständigen Stand erwischen. `VACUUM INTO` schreibt
stattdessen im laufenden Betrieb eine in sich geschlossene, defragmentierte
Einzeldatei; sqlite3.Connection.backup() dient als Rückfallebene für sehr alte
SQLite-Versionen (VACUUM INTO gibt es erst ab 3.27).

Keine Router-Logik hier - das hält die Funktionen testbar.
"""
from __future__ import annotations

import json
import os
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path


BACKUP_PREFIX = "lehrer-dashboard-backup-"


def backup_filename(when: datetime | None = None) -> str:
    """Einheitlicher Dateiname für Download und Automatik - die Aufräumroutine
    erkennt eigene Sicherungen an diesem Präfix und fasst nichts anderes an."""
    return f"{BACKUP_PREFIX}{(when or datetime.now()).strftime('%Y-%m-%d_%H%M')}.zip"


def snapshot_db(conn: sqlite3.Connection, dest: str) -> str:
    """Schreibt einen konsistenten Snapshot der offenen DB nach dest.

    dest darf noch nicht existieren (Vorgabe von VACUUM INTO).
    """
    if os.path.exists(dest):
        raise FileExistsError(dest)
    conn.commit()  # VACUUM INTO scheitert innerhalb einer offenen Transaktion
    try:
        conn.execute("VACUUM INTO ?", (dest,))
    except sqlite3.OperationalError:
        # Aeltere SQLite-Versionen kennen VACUUM INTO nicht - Online-Backup-API nutzen.
        target = sqlite3.connect(dest)
        try:
            conn.backup(target)
        finally:
            target.close()
    return dest


def build_manifest(conn: sqlite3.Connection, *, app_version: str, include_storage: bool,
                   storage_files: int) -> dict:
    """Beschreibt den Sicherungsstand - entscheidend, um beim Zurückspielen zu
    erkennen, ob Backup und Programmstand zusammenpassen (Migrationen!)."""
    try:
        migrations = [r[0] for r in conn.execute(
            "SELECT filename FROM schema_migrations ORDER BY filename")]
    except sqlite3.OperationalError:
        migrations = []
    return {
        "createdAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "appVersion": app_version,
        "schemaMigrations": migrations,
        "lastMigration": migrations[-1] if migrations else None,
        "includesStorage": include_storage,
        "storageFileCount": storage_files,
        "restoreHint": (
            "data.db in das Volume ldb_data legen (Container gestoppt), storage/ nach "
            "ldb_storage. Vorher vorhandene data.db-wal und data.db-shm löschen."
        ),
    }


def _storage_entries(storage_root: str) -> list[tuple[Path, str]]:
    """(absoluter Pfad, ZIP-Name) je Datei unter storage_root - Umlaute bleiben erhalten."""
    root = Path(storage_root)
    if not root.is_dir():
        return []
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries.append((path, str(Path("storage") / path.relative_to(root))))
    return entries


def build_backup_zip(conn: sqlite3.Connection, out_path: str, *, storage_root: str,
                     include_storage: bool, app_version: str, work_dir: str) -> str:
    """Packt DB-Snapshot (+ optional storage/) samt manifest.json nach out_path."""
    db_snapshot = os.path.join(work_dir, "data.db")
    snapshot_db(conn, db_snapshot)

    entries = _storage_entries(storage_root) if include_storage else []
    manifest = build_manifest(conn, app_version=app_version,
                              include_storage=include_storage, storage_files=len(entries))

    # ZIP_DEFLATED: die SQLite-Datei komprimiert sehr gut, PDFs kaum - schadet aber nicht.
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_snapshot, "data.db")
        for src, arcname in entries:
            zf.write(src, arcname)
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))  # Umlaute erhalten
    os.remove(db_snapshot)
    return out_path
