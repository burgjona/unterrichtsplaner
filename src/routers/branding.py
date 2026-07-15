"""M12/U10: Root-Level-Branding-Routen (Favicon + PWA-Manifest), unauthentifiziert.

Diese Routen liegen bewusst NICHT unter /api und werden in src/main.py VOR dem
StaticFiles-Mount ("/") registriert, damit sie Vorrang haben. Ohne hinterlegtes Logo
liefern sie neutrales Standardverhalten (kein Fehler) – der Browser fragt Favicon/
Manifest auch ohne Session ab, daher hier keine Auth. Single-User: es wird das
zuletzt gesetzte Logo verwendet (unabhängig von der Session).
"""
import os
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse, Response

from ..deps import get_db, get_storage_root
from ..lib.branding import media_type_for, resolve_relpath

router = APIRouter(tags=["branding"])

# 1×1 transparentes GIF als neutrales Fallback-Icon (kein 404 fürs Favicon).
_TRANSPARENT_GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000001002c0000000001"
    "0001000002024401003b"
)
_THEME_COLOR = "#14532d"
_BACKGROUND_COLOR = "#ffffff"


def _logo_abspath(conn: sqlite3.Connection, storage_root: str):
    """Absoluten Pfad des hinterlegten Logos zurückgeben oder None (Single-User)."""
    row = conn.execute(
        "SELECT logo_path FROM user_settings WHERE logo_path IS NOT NULL "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    if not row or not row["logo_path"]:
        return None
    try:
        path = resolve_relpath(row["logo_path"], storage_root)
    except Exception:
        return None
    return path if os.path.exists(path) else None


@router.get("/favicon.ico", include_in_schema=False)
@router.get("/api/branding/favicon", include_in_schema=False)
def favicon(conn: sqlite3.Connection = Depends(get_db),
            storage_root: str = Depends(get_storage_root)):
    path = _logo_abspath(conn, storage_root)
    if path:
        return FileResponse(path, media_type=media_type_for(path))
    return Response(content=_TRANSPARENT_GIF, media_type="image/gif")


@router.get("/manifest.webmanifest", include_in_schema=False)
def manifest(conn: sqlite3.Connection = Depends(get_db),
             storage_root: str = Depends(get_storage_root)):
    path = _logo_abspath(conn, storage_root)
    data = {
        "name": "Lehrer-Dashboard",
        "short_name": "Dashboard",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "theme_color": _THEME_COLOR,
        "background_color": _BACKGROUND_COLOR,
        "icons": [],
    }
    if path:
        mt = media_type_for(path)
        data["icons"] = [
            {"src": "/api/branding/favicon", "sizes": "any", "type": mt, "purpose": "any"},
            {"src": "/api/branding/favicon", "sizes": "512x512", "type": mt, "purpose": "maskable"},
        ]
    return JSONResponse(data, media_type="application/manifest+json")
