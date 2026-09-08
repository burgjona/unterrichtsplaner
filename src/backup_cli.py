"""Sicherung von der Kommandozeile - für den nächtlichen Lauf im Synology-Task-Scheduler.

Aufruf im laufenden Container:

    docker exec lehrer-dashboard python -m src.backup_cli /data/_backup

Nutzt dieselbe Logik wie der Download-Endpunkt (VACUUM INTO + ZIP), braucht aber keine
Anmeldung: der Aufruf kommt per docker exec aus der NAS selbst, nicht über das Netz.

Aufräumen ist bewusst eingebaut statt im Shell-Skript: die Routine fasst ausschließlich
Dateien mit dem eigenen Namenspräfix im angegebenen Ordner an - ein "find -delete" im
Task-Scheduler wäre bei einem Tippfehler im Pfad deutlich gefährlicher.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import settings
from .db import connect
from .lib.backup import BACKUP_PREFIX, backup_filename, build_backup_zip


def cleanup(target_dir: str, keep: int) -> list[str]:
    """Behält die neuesten `keep` eigenen Sicherungen, löscht ältere. keep <= 0 = nie löschen."""
    if keep <= 0:
        return []
    own = sorted(Path(target_dir).glob(f"{BACKUP_PREFIX}*.zip"),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for path in own[keep:]:
        path.unlink()
        removed.append(path.name)
    return removed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sicherung von Datenbank und Materialdateien.")
    ap.add_argument("zielordner", help="Ordner, in dem die ZIP-Datei abgelegt wird")
    ap.add_argument("--ohne-materialien", action="store_true",
                    help="nur die Datenbank sichern (deutlich kleiner und schneller)")
    ap.add_argument("--behalte", type=int, default=14, metavar="N",
                    help="nur die N neuesten Sicherungen behalten (0 = nie aufräumen)")
    args = ap.parse_args(argv)

    target = Path(args.zielordner)
    target.mkdir(parents=True, exist_ok=True)
    zip_path = target / backup_filename()
    # Der Name hat Minutenauflösung. Zwei Läufe in derselben Minute (etwa beim Testen
    # von Hand) würden sich sonst still überschreiben - also durchnummerieren.
    if zip_path.exists():
        stamm = zip_path.stem
        n = 2
        while zip_path.exists():
            zip_path = target / f"{stamm}_{n}.zip"
            n += 1

    conn = connect(settings.db_path)
    try:
        build_backup_zip(conn, str(zip_path), storage_root=settings.storage_root,
                         include_storage=not args.ohne_materialien,
                         app_version=os.environ.get("GIT_COMMIT", "unbekannt"),
                         work_dir=str(target))
    finally:
        conn.close()

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"Sicherung geschrieben: {zip_path} ({size_mb:.1f} MB)")
    for name in cleanup(str(target), args.behalte):
        print(f"  alte Sicherung entfernt: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
