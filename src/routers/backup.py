"""Vollsicherung zum Herunterladen: konsistenter DB-Snapshot + optional die Materialdateien.

Zweck (Sicherheitsrunde U28): jederzeit aus dem Browser ein vollständiges, garantiert
öffenbares Backup ziehen zu können - ohne SSH-Zugang zur NAS. Ergänzt (ersetzt nicht)
die automatische Sicherung über Hyper Backup, siehe DEPLOY.md.

Kein Nutzer-Scoping der Daten: die Sicherung umfasst bauartbedingt die ganze Datei.
Das ist zulaessig, weil die App per Briefing genau ein Konto kennt (Registrierung sperrt
sich nach dem ersten Konto selbst); der Endpunkt bleibt aber anmeldepflichtig.
"""
import os
import shutil
import sqlite3
import tempfile
import urllib.parse

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ..deps import get_db, get_storage_root, get_user_id
from ..lib.backup import backup_filename, build_backup_zip

router = APIRouter(prefix="/backup", tags=["backup"])


def _work_root(db_path: str) -> str:
    """Arbeitsverzeichnis möglichst neben der DB wählen: dort liegt das Daten-Volume
    mit echtem Plattenplatz - /tmp im Container ist knapp, sobald storage/ mitgesichert wird."""
    if db_path and db_path != ":memory:":
        parent = os.path.dirname(os.path.abspath(db_path))
        if os.path.isdir(parent) and os.access(parent, os.W_OK):
            return parent
    return tempfile.gettempdir()


@router.get("")
def download_backup(
    request: Request,
    include_storage: bool = Query(True, alias="includeStorage"),
    conn: sqlite3.Connection = Depends(get_db),
    user_id: int = Depends(get_user_id),
    storage_root: str = Depends(get_storage_root),
):
    """Liefert die Sicherung als ZIP (data.db, manifest.json, optional storage/)."""
    work_dir = tempfile.mkdtemp(prefix="ldb-backup-", dir=_work_root(request.app.state.db_path))
    fname = backup_filename()
    zip_path = os.path.join(work_dir, fname)
    try:
        build_backup_zip(conn, zip_path, storage_root=storage_root,
                         include_storage=include_storage,
                         app_version=request.app.version, work_dir=work_dir)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    ascii_fb = "".join(c if c.isascii() else "_" for c in fname)  # ASCII-Fallback für den Header
    disposition = (f"attachment; filename=\"{ascii_fb}\"; "
                   f"filename*=UTF-8''{urllib.parse.quote(fname)}")  # RFC 5987
    return FileResponse(
        zip_path, media_type="application/zip",
        headers={"Content-Disposition": disposition},
        # Erst nach dem Ausliefern aufräumen - sonst zieht FileResponse ins Leere.
        background=BackgroundTask(shutil.rmtree, work_dir, ignore_errors=True),
    )
