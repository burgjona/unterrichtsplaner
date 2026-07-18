"""Notizen ("Gedanken sammeln") – nutzer-gescoped (U17).

Zwei Sichtbarkeiten (scope): 'allgemein' (klassenübergreifend, class_id NULL) und
'klasse' (an eine Klasse gebunden; school_year_id wird aus der Klasse abgeleitet).

Archiv: Das ✕ bzw. "Notiz archivieren" setzt archived_at (Soft-Delete); POST /restore
holt zurück; DELETE ist endgültiges Löschen (im Archiv nutzbar). GET liefert
standardmäßig nur aktive Notizen aktiver Klassen; ?archived=true liefert die
archivierten – inklusive Notizen, deren Klasse zwischenzeitlich archiviert wurde.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import NoteCreate, NoteOut, NoteUpdate

router = APIRouter(prefix="/notes", tags=["notes"])


def _get(conn, user_id, nid):
    row = conn.execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?", (nid, user_id)
    ).fetchone()
    return NoteOut(**dict(row)) if row else None


@router.post("", response_model=NoteOut, status_code=201)
def create(body: NoteCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    if body.scope not in ("allgemein", "klasse"):
        raise HTTPException(status_code=400, detail="scope muss 'allgemein' oder 'klasse' sein.")
    class_id = None
    school_year_id = None
    if body.scope == "klasse":
        if not body.class_id:
            raise HTTPException(status_code=400, detail="Für scope 'klasse' ist classId erforderlich.")
        cls = conn.execute(
            "SELECT id, school_year_id FROM classes WHERE id = ? AND user_id = ?",
            (body.class_id, user_id),
        ).fetchone()
        row_or_404(cls, "Klasse")
        class_id = cls["id"]
        school_year_id = cls["school_year_id"]
    cur = conn.execute(
        "INSERT INTO notes(user_id, scope, class_id, school_year_id, body_md) VALUES (?,?,?,?,?)",
        (user_id, body.scope, class_id, school_year_id, body.body_md or ""),
    )
    conn.commit()
    return _get(conn, user_id, cur.lastrowid)


@router.get("", response_model=List[NoteOut])
def list_(
    scope: Optional[str] = Query(None, alias="scope"),
    class_id: Optional[int] = Query(None, alias="classId"),
    archived: bool = Query(False, alias="archived"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    # LEFT JOIN auf classes, damit "Klasse archiviert" ins Archiv fällt, auch wenn
    # die Notiz selbst noch archived_at IS NULL hat.
    sql = ("SELECT n.* FROM notes n "
           "LEFT JOIN classes c ON c.id = n.class_id "
           "WHERE n.user_id = ?")
    params = [user_id]
    if archived:
        sql += " AND (n.archived_at IS NOT NULL OR c.archived_at IS NOT NULL)"
    else:
        sql += " AND n.archived_at IS NULL AND (n.class_id IS NULL OR c.archived_at IS NULL)"
    if scope:
        sql += " AND n.scope = ?"
        params.append(scope)
    if class_id is not None:
        sql += " AND n.class_id = ?"
        params.append(class_id)
    sql += " ORDER BY n.id"
    rows = conn.execute(sql, params).fetchall()
    return [NoteOut(**dict(r)) for r in rows]


@router.put("/{nid}", response_model=NoteOut)
def update(nid: int, body: NoteUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, nid), "Notiz")
    conn.execute(
        "UPDATE notes SET body_md = ?, updated_at = datetime('now') WHERE id = ? AND user_id = ?",
        (body.body_md or "", nid, user_id),
    )
    conn.commit()
    return _get(conn, user_id, nid)


@router.post("/{nid}/archive", response_model=NoteOut)
def archive(nid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, nid), "Notiz")
    conn.execute(
        "UPDATE notes SET archived_at = datetime('now'), updated_at = datetime('now') "
        "WHERE id = ? AND user_id = ?",
        (nid, user_id),
    )
    conn.commit()
    return _get(conn, user_id, nid)


@router.post("/{nid}/restore", response_model=NoteOut)
def restore(nid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, nid), "Notiz")
    conn.execute(
        "UPDATE notes SET archived_at = NULL, updated_at = datetime('now') "
        "WHERE id = ? AND user_id = ?",
        (nid, user_id),
    )
    conn.commit()
    return _get(conn, user_id, nid)


@router.delete("/{nid}", status_code=204)
def delete(nid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (nid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notiz nicht gefunden.")
