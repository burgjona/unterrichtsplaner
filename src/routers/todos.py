"""To-dos der Heute-Ansicht (nutzer-gescoped).

DELETE ist endgültiges Löschen (im Archiv nutzbar). Das ✕ im Heute-View
archiviert stattdessen soft (POST /archive → archived_at gesetzt); POST /restore
holt einen archivierten Eintrag zurück. GET liefert standardmäßig nur
nicht-archivierte To-dos; ?archived=true liefert die archivierten.

Offline-Sync (Rollout): create/update/delete laufen über dieselben _apply_*-Funktionen
wie der REST-Endpunkt UND den generischen Sync-Push (src/routers/sync.py) — siehe
notes.py für das Vorbild. archive/restore bleiben bewusst online-only (nicht im
generischen 3-Op-Sync-Modell abgebildet, analog notes.py).
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


def _apply_create(conn, user_id, body: TodoCreate) -> TodoOut:
    if body.source not in ("system", "manuell"):
        raise HTTPException(status_code=400, detail="source muss 'system' oder 'manuell' sein.")
    try:
        cur = conn.execute(
            "INSERT INTO todos(user_id, text, source, hefter_lesson_id, updated_at) "
            "VALUES (?,?,?,?, strftime('%Y-%m-%d %H:%M:%f','now'))",
            (user_id, body.text, body.source, body.hefter_lesson_id),
        )
    except sqlite3.IntegrityError:
        # Hefter-To-do für diese Stunde existiert schon (Doppelanlage bei Sync-Race) —
        # idempotent den vorhandenen zurückgeben statt 500.
        if body.hefter_lesson_id is not None:
            row = conn.execute(
                "SELECT * FROM todos WHERE user_id = ? AND hefter_lesson_id = ?",
                (user_id, body.hefter_lesson_id),
            ).fetchone()
            if row is not None:
                return TodoOut(**dict(row))
        raise
    return _get(conn, user_id, cur.lastrowid)


def _apply_update(conn, user_id, tid: int, body: TodoUpdate) -> TodoOut:
    row_or_404(_get(conn, user_id, tid), "To-do")
    fields = body.model_dump(exclude_unset=True)
    if "done" in fields:
        fields["done"] = int(fields["done"])
    if fields:
        # Millisekunden-Auflösung ist Pflicht für die Sync-Konflikterkennung (vgl. notes.py).
        cols = ", ".join(f"{k} = :{k}" for k in fields) + ", updated_at = strftime('%Y-%m-%d %H:%M:%f','now')"
        fields.update(id=tid, uid=user_id)
        conn.execute(f"UPDATE todos SET {cols} WHERE id = :id AND user_id = :uid", fields)
    return _get(conn, user_id, tid)


def _apply_delete(conn, user_id, tid: int) -> None:
    cur = conn.execute("DELETE FROM todos WHERE id = ? AND user_id = ?", (tid, user_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="To-do nicht gefunden.")


@router.post("", response_model=TodoOut, status_code=201)
def create(body: TodoCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    result = _apply_create(conn, user_id, body)
    conn.commit()
    return result


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
    result = _apply_update(conn, user_id, tid, body)
    conn.commit()
    return result


@router.post("/{tid}/archive", response_model=TodoOut)
def archive(tid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, tid), "To-do")
    conn.execute(
        "UPDATE todos SET archived_at = datetime('now'), updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
        "WHERE id = ? AND user_id = ?",
        (tid, user_id),
    )
    conn.commit()
    return _get(conn, user_id, tid)


@router.post("/{tid}/restore", response_model=TodoOut)
def restore(tid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, tid), "To-do")
    conn.execute(
        "UPDATE todos SET archived_at = NULL, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
        "WHERE id = ? AND user_id = ?",
        (tid, user_id),
    )
    conn.commit()
    return _get(conn, user_id, tid)


@router.delete("/{tid}", status_code=204)
def delete(tid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _apply_delete(conn, user_id, tid)
    conn.commit()


# ---------- Sync-Handler-Registry (src/routers/sync.py) ----------

def _sync_fetch(conn, user_id, entity_id):
    return _get(conn, user_id, entity_id)


def _sync_create(conn, user_id, payload: dict) -> TodoOut:
    return _apply_create(conn, user_id, TodoCreate(**payload))


def _sync_update(conn, user_id, entity_id, payload: dict) -> TodoOut:
    return _apply_update(conn, user_id, entity_id, TodoUpdate(**payload))


def _sync_delete(conn, user_id, entity_id) -> None:
    _apply_delete(conn, user_id, entity_id)


SYNC_HANDLER = {
    "fetch": _sync_fetch,
    "create": _sync_create,
    "update": _sync_update,
    "delete": _sync_delete,
}
