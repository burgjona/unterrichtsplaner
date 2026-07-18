"""CRUD Kalendereinträge (nutzer-gescoped). Auto-Erzeugung aus Stunden = Meilenstein 4."""
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import CalendarCreate, CalendarOut, CalendarUpdate

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _get(conn, user_id, cid):
    row = conn.execute(
        "SELECT * FROM calendar_entries WHERE id = ? AND user_id = ?", (cid, user_id)
    ).fetchone()
    return CalendarOut(**dict(row)) if row else None


def _category_owned(conn, user_id, category_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM calendar_categories WHERE id = ? AND user_id = ?", (category_id, user_id)
    ).fetchone() is not None


@router.post("", response_model=CalendarOut, status_code=201)
def create(body: CalendarCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    # Kategorie (falls gesetzt) muss dem Nutzer gehören.
    if body.category_id is not None and not _category_owned(conn, user_id, body.category_id):
        raise HTTPException(status_code=400, detail="Unbekannte Kategorie.")
    try:
        cur = conn.execute(
            """INSERT INTO calendar_entries
               (user_id, class_id, lesson_id, school_year_id, title, entry_date, end_date,
                start_time, end_time, all_day, entry_type, category_id, is_fixed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, body.class_id, body.lesson_id, body.school_year_id, body.title,
             body.entry_date, body.end_date, body.start_time, body.end_time,
             int(body.all_day), body.entry_type, body.category_id, int(body.is_fixed)),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültiger Eintrag: {exc}")
    return _get(conn, user_id, cur.lastrowid)


@router.get("", response_model=List[CalendarOut])
def list_(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    class_id: Optional[int] = Query(None, alias="classId"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    sql = "SELECT * FROM calendar_entries WHERE user_id = ?"
    params = [user_id]
    if from_ is not None:
        sql += " AND entry_date >= ?"
        params.append(from_)
    if to is not None:
        sql += " AND entry_date <= ?"
        params.append(to)
    if class_id is not None:
        sql += " AND class_id = ?"
        params.append(class_id)
    sql += " ORDER BY entry_date"
    return [CalendarOut(**dict(r)) for r in conn.execute(sql, params).fetchall()]


@router.get("/{cid}", response_model=CalendarOut)
def get_(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    return row_or_404(_get(conn, user_id, cid), "Kalendereintrag")


@router.put("/{cid}", response_model=CalendarOut)
def update(cid: int, body: CalendarUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, cid), "Kalendereintrag")
    fields = body.model_dump(exclude_unset=True)
    if fields.get("category_id") is not None and not _category_owned(conn, user_id, fields["category_id"]):
        raise HTTPException(status_code=400, detail="Unbekannte Kategorie.")
    if "is_fixed" in fields:
        fields["is_fixed"] = int(fields["is_fixed"])
    if "all_day" in fields:
        fields["all_day"] = int(fields["all_day"])
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=cid, uid=user_id)
        conn.execute(
            f"UPDATE calendar_entries SET {cols} WHERE id = :id AND user_id = :uid", fields
        )
        conn.commit()
    return _get(conn, user_id, cid)


@router.delete("/{cid}", status_code=204)
def delete(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute("DELETE FROM calendar_entries WHERE id = ? AND user_id = ?", (cid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Kalendereintrag nicht gefunden.")
