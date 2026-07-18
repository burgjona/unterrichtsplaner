"""To-dos der Heute-Ansicht (nutzer-gescoped).

DELETE ist endgültiges Löschen (im Archiv nutzbar). Das ✕ im Heute-View
archiviert stattdessen soft (POST /archive → archived_at gesetzt); POST /restore
holt einen archivierten Eintrag zurück. GET liefert standardmäßig nur
nicht-archivierte To-dos; ?archived=true liefert die archivierten.
"""
import sqlite3
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import TodoCreate, TodoOut, TodoUpdate

router = APIRouter(prefix="/todos", tags=["todos"])


def _get(conn, user_id, tid):
    row = conn.execute(
        "SELECT * FROM todos WHERE id = ? AND user_id = ?", (tid, user_id)
    ).fetchone()
    return TodoOut(**dict(row)) if row else None


@router.post("", response_model=TodoOut, status_code=201)
def create(body: TodoCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    if body.source not in ("system", "manuell"):
        raise HTTPException(status_code=400, detail="source muss 'system' oder 'manuell' sein.")
    cur = conn.execute(
        "INSERT INTO todos(user_id, text, source) VALUES (?,?,?)",
        (user_id, body.text, body.source),
    )
    conn.commit()
    return _get(conn, user_id, cur.lastrowid)


@router.get("", response_model=List[TodoOut])
def list_(
    archived: bool = Query(False, alias="archived"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    cond = "archived_at IS NOT NULL" if archived else "archived_at IS NULL"
    rows = conn.execute(
        f"SELECT * FROM todos WHERE user_id = ? AND {cond} ORDER BY id", (user_id,)
    ).fetchall()
    return [TodoOut(**dict(r)) for r in rows]


@router.put("/{tid}", response_model=TodoOut)
def update(tid: int, body: TodoUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, tid), "To-do")
    fields = body.model_dump(exclude_unset=True)
    if "done" in fields:
        fields["done"] = int(fields["done"])
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=tid, uid=user_id)
        conn.execute(f"UPDATE todos SET {cols} WHERE id = :id AND user_id = :uid", fields)
        conn.commit()
    return _get(conn, user_id, tid)


@router.post("/{tid}/archive", response_model=TodoOut)
def archive(tid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, tid), "To-do")
    conn.execute(
        "UPDATE todos SET archived_at = datetime('now') WHERE id = ? AND user_id = ?",
        (tid, user_id),
    )
    conn.commit()
    return _get(conn, user_id, tid)


@router.post("/{tid}/restore", response_model=TodoOut)
def restore(tid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, tid), "To-do")
    conn.execute(
        "UPDATE todos SET archived_at = NULL WHERE id = ? AND user_id = ?",
        (tid, user_id),
    )
    conn.commit()
    return _get(conn, user_id, tid)


@router.delete("/{tid}", status_code=204)
def delete(tid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute("DELETE FROM todos WHERE id = ? AND user_id = ?", (tid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="To-do nicht gefunden.")
