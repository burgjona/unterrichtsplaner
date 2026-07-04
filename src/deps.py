"""FastAPI-Dependencies: DB-Connection pro Request und Session-basiertes Nutzer-Scoping.

Seit Meilenstein 2 wird der Nutzer über das HttpOnly-Session-Cookie bestimmt
(nicht mehr über X-User-Id). Die Router bleiben unverändert – sie hängen weiter
an der Dependency get_user_id.
"""
import sqlite3
from typing import Iterator

from fastapi import Depends, HTTPException, Request

from .config import settings
from .db import connect


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_user_id(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> int:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
    row = conn.execute(
        "SELECT user_id FROM sessions WHERE token = ? AND expires_at > datetime('now')",
        (token,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Sitzung ungültig oder abgelaufen.")
    return row["user_id"]


def get_storage_root(request: Request) -> str:
    return getattr(request.app.state, "storage_root", settings.storage_root)


def row_or_404(row, entity: str = "Ressource"):
    if row is None:
        raise HTTPException(status_code=404, detail=f"{entity} nicht gefunden.")
    return row
