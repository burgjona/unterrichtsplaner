"""Nutzerprofil (lesen/ändern/löschen). Kontoerstellung läuft über /auth/register."""
import sqlite3
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, row_or_404
from ..schemas import UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _get(conn: sqlite3.Connection, uid: int):
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return UserOut(**dict(row)) if row else None


@router.get("", response_model=List[UserOut])
def list_users(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [UserOut(**dict(r)) for r in rows]


@router.get("/{uid}", response_model=UserOut)
def get_user(uid: int, conn: sqlite3.Connection = Depends(get_db)):
    return row_or_404(_get(conn, uid), "Nutzer")


@router.put("/{uid}", response_model=UserOut)
def update_user(uid: int, body: UserUpdate, conn: sqlite3.Connection = Depends(get_db)):
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


@router.delete("/{uid}", status_code=204)
def delete_user(uid: int, conn: sqlite3.Connection = Depends(get_db)):
    cur = conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Nutzer nicht gefunden.")
