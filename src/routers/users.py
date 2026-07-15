"""Nutzerprofil (nur eigenes Konto, nur angemeldet). Kontoerstellung läuft über /auth/register.

M9.1: Bis dahin war dieser M1-Router ohne Login-Schutz erreichbar (inkl. DELETE –
Kontoübernahme über erneut geöffnetes Bootstrap-Register möglich). Jetzt: Auth-Pflicht,
Zugriff nur auf das eigene Profil; Nutzerliste und Konto-Löschung sind entfernt.
"""
import os
import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..deps import get_db, get_storage_root, get_user_id, row_or_404
from ..lib.branding import media_type_for, resolve_relpath, save_image_upload
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


# ---------- Profilbild (M12/U10) — ans Router-Ende (Konfliktvermeidung) ----------
@router.post("/{uid}/avatar", response_model=UserOut)
async def upload_avatar(uid: int, file: UploadFile = File(...),
                        conn: sqlite3.Connection = Depends(get_db),
                        user_id: int = Depends(get_user_id),
                        storage_root: str = Depends(get_storage_root)):
    """Eigenes Profilbild hochladen (image/*, max. 5 MB). Ablage im .branding-Baum."""
    _own_or_403(uid, user_id)
    row_or_404(_get(conn, uid), "Nutzer")
    rel = await save_image_upload(file, f"avatar_{uid}", storage_root)
    conn.execute("UPDATE users SET avatar_path = ?, updated_at = datetime('now') WHERE id = ?",
                 (rel, uid))
    conn.commit()
    return _get(conn, uid)


@router.get("/{uid}/avatar")
def get_avatar(uid: int, conn: sqlite3.Connection = Depends(get_db),
               user_id: int = Depends(get_user_id),
               storage_root: str = Depends(get_storage_root)):
    _own_or_403(uid, user_id)
    row = conn.execute("SELECT avatar_path FROM users WHERE id = ?", (uid,)).fetchone()
    if not row or not row["avatar_path"]:
        raise HTTPException(status_code=404, detail="Kein Profilbild hinterlegt.")
    path = resolve_relpath(row["avatar_path"], storage_root)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Profilbild-Datei nicht gefunden.")
    return FileResponse(path, media_type=media_type_for(path))
