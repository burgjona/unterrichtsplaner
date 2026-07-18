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


@router.post("", response_model=ClassOut, status_code=201)
def create(body: ClassCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        """INSERT INTO classes
           (user_id, school_year_id, name, subject, grade, track,
            weekly_hours, parallel_group, visible_in_calendar)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, body.school_year_id, body.name, body.subject, body.grade, body.track,
         body.weekly_hours, body.parallel_group, int(body.visible_in_calendar)),
    )
    conn.commit()
    return _get(conn, user_id, cur.lastrowid)


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
    row_or_404(_get(conn, user_id, cid), "Klasse")
    fields = body.model_dump(exclude_unset=True)
    if "visible_in_calendar" in fields:
        fields["visible_in_calendar"] = int(fields["visible_in_calendar"])
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=cid, uid=user_id)
        conn.execute(
            f"UPDATE classes SET {cols}, updated_at = datetime('now') WHERE id = :id AND user_id = :uid",
            fields,
        )
        conn.commit()
    return _get(conn, user_id, cid)


@router.post("/{cid}/restore", response_model=ClassOut)
def restore(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, cid), "Klasse")
    conn.execute(
        "UPDATE classes SET archived_at = NULL, updated_at = datetime('now') WHERE id = ? AND user_id = ?",
        (cid, user_id),
    )
    conn.commit()
    return _get(conn, user_id, cid)


@router.delete("/{cid}", status_code=204)
def delete(cid: int, hard: bool = False, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, cid), "Klasse")
    if hard:
        conn.execute("DELETE FROM classes WHERE id = ? AND user_id = ?", (cid, user_id))
    else:
        conn.execute(
            "UPDATE classes SET archived_at = datetime('now') WHERE id = ? AND user_id = ?",
            (cid, user_id),
        )
    conn.commit()
