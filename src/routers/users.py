"""Nutzerprofil (nur eigenes Konto, nur angemeldet). Kontoerstellung läuft über /auth/register.

M9.1: Bis dahin war dieser M1-Router ohne Login-Schutz erreichbar (inkl. DELETE –
Kontoübernahme über erneut geöffnetes Bootstrap-Register möglich). Jetzt: Auth-Pflicht,
Zugriff nur auf das eigene Profil; Nutzerliste und Konto-Löschung sind entfernt.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _get(conn: sqlite3.Connection, uid: int):
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return UserOut(**dict(row)) if row else None


def _own_or_403(uid: int, user_id: int) -> None:
    if uid != user_id:
        raise HTTPException(status_code=403, detail="Zugriff nur auf das eigene Profil.")


@router.get("/{uid}", response_model=UserOut)
def get_user(uid: int, conn: sqlite3.Connection = Depends(get_db),
             user_id: int = Depends(get_user_id)):
    _own_or_403(uid, user_id)
    return row_or_404(_get(conn, uid), "Nutzer")


@router.put("/{uid}", response_model=UserOut)
def update_user(uid: int, body: UserUpdate, conn: sqlite3.Connection = Depends(get_db),
                user_id: int = Depends(get_user_id)):
    _own_or_403(uid, user_id)
    fields = body.model_dump(exclude_unset=True)
    row_or_404(_get(conn, uid), "Nutzer")
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = uid
        try:
            conn.execute(
                f"UPDATE users SET {cols}, updated_at = datetime('now') WHERE id = :id", fields
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="E-Mail bereits vergeben.")
    return _get(conn, uid)
