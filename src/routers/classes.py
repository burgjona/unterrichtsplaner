"""CRUD Klassen (nutzer-gescoped). DELETE = Soft-Archiv (?hard=true = echtes Löschen).

Entfernen einer Klasse invalidiert keine Planungsdaten: Soft-Delete behält die
Zeile (archiviert); Hard-Delete setzt lessons.class_id / calendar.class_id via
ON DELETE SET NULL auf NULL – die Stunden/Termine bleiben erhalten.
"""
import sqlite3
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import ClassCreate, ClassOut, ClassUpdate

router = APIRouter(prefix="/classes", tags=["classes"])


def _get(conn, user_id, cid):
    row = conn.execute(
        "SELECT * FROM classes WHERE id = ? AND user_id = ?", (cid, user_id)
    ).fetchone()
    return ClassOut(**dict(row)) if row else None


def _apply_create(conn, user_id, body: ClassCreate) -> ClassOut:
    cur = conn.execute(
        """INSERT INTO classes
           (user_id, school_year_id, name, subject, grade, track,
            weekly_hours, parallel_group, visible_in_calendar)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, body.school_year_id, body.name, body.subject, body.grade, body.track,
         body.weekly_hours, body.parallel_group, int(body.visible_in_calendar)),
    )
    return _get(conn, user_id, cur.lastrowid)


def _apply_update(conn, user_id, cid: int, body: ClassUpdate) -> ClassOut:
    row_or_404(_get(conn, user_id, cid), "Klasse")
    fields = body.model_dump(exclude_unset=True)
    if "visible_in_calendar" in fields:
        fields["visible_in_calendar"] = int(fields["visible_in_calendar"])
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=cid, uid=user_id)
        conn.execute(
            f"UPDATE classes SET {cols}, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
            "WHERE id = :id AND user_id = :uid",
            fields,
        )
    return _get(conn, user_id, cid)


def _apply_delete(conn, user_id, cid: int) -> None:
    # Generischer Sync-Op 'delete' = Soft-Archiv (analog zum REST-Endpunkt ohne ?hard=true) —
    # das ist die häufige, alltägliche Aktion ("Klasse aus der Liste entfernen"), nicht das
    # seltene endgültige Löschen. Hard-Delete (?hard=true) und restore bleiben online-only,
    # wie bei notes/todos.
    row_or_404(_get(conn, user_id, cid), "Klasse")
    conn.execute(
        "UPDATE classes SET archived_at = strftime('%Y-%m-%d %H:%M:%f','now'), "
        "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ? AND user_id = ?",
        (cid, user_id),
    )


@router.post("", response_model=ClassOut, status_code=201)
def create(body: ClassCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    result = _apply_create(conn, user_id, body)
    conn.commit()
    return result


@router.get("", response_model=List[ClassOut])
def list_(
    include_archived: bool = Query(False, alias="includeArchived"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    sql = "SELECT * FROM classes WHERE user_id = ?"
    if not include_archived:
        sql += " AND archived_at IS NULL"
    sql += " ORDER BY name"
    return [ClassOut(**dict(r)) for r in conn.execute(sql, (user_id,)).fetchall()]


@router.get("/{cid}", response_model=ClassOut)
def get_(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    return row_or_404(_get(conn, user_id, cid), "Klasse")


@router.put("/{cid}", response_model=ClassOut)
def update(cid: int, body: ClassUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    result = _apply_update(conn, user_id, cid, body)
    conn.commit()
    return result


@router.post("/{cid}/restore", response_model=ClassOut)
def restore(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, cid), "Klasse")
    conn.execute(
        "UPDATE classes SET archived_at = NULL, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
        "WHERE id = ? AND user_id = ?",
        (cid, user_id),
    )
    conn.commit()
    return _get(conn, user_id, cid)


@router.delete("/{cid}", status_code=204)
def delete(cid: int, hard: bool = False, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    if hard:
        row_or_404(_get(conn, user_id, cid), "Klasse")
        conn.execute("DELETE FROM classes WHERE id = ? AND user_id = ?", (cid, user_id))
        conn.commit()
    else:
        _apply_delete(conn, user_id, cid)
        conn.commit()


# ---------- Sync-Handler-Registry (src/routers/sync.py) ----------
# 'delete' bildet auf das Soft-Archiv ab (siehe _apply_delete-Kommentar). restore und
# Hard-Delete (?hard=true) bleiben online-only, analog notes/todos archive/restore.

def _sync_fetch(conn, user_id, entity_id):
    return _get(conn, user_id, entity_id)


def _sync_create(conn, user_id, payload: dict) -> ClassOut:
    return _apply_create(conn, user_id, ClassCreate(**payload))


def _sync_update(conn, user_id, entity_id, payload: dict) -> ClassOut:
    return _apply_update(conn, user_id, entity_id, ClassUpdate(**payload))


def _sync_delete(conn, user_id, entity_id) -> None:
    _apply_delete(conn, user_id, entity_id)


SYNC_HANDLER = {
    "fetch": _sync_fetch,
    "create": _sync_create,
    "update": _sync_update,
    "delete": _sync_delete,
}
