"""CRUD Schuljahre (nutzer-gescoped)."""
import sqlite3
from typing import List

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, get_user_id, row_or_404
from ..lib import holidays
from ..schemas import SchoolDateOut, SchoolYearCreate, SchoolYearOut, SchoolYearUpdate

router = APIRouter(prefix="/school-years", tags=["school-years"])


def _fetch_and_store_dates(conn, user_id, sy_id, start_date, end_date) -> int:
    """Best-effort: Ferien/Feiertage (SN) für die Schuljahresspanne abrufen und speichern."""
    rows = holidays.collect_school_dates(int(start_date[:4]), int(end_date[:4]))
    stored = 0
    for r in rows:
        if r["end_date"] < start_date or r["start_date"] > end_date:
            continue  # außerhalb des Schuljahres
        cur = conn.execute(
            """INSERT OR IGNORE INTO school_dates
               (user_id, school_year_id, kind, name, start_date, end_date, source)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, sy_id, r["kind"], r["name"], r["start_date"], r["end_date"], r["source"]),
        )
        stored += cur.rowcount
    conn.commit()
    return stored


def _get(conn, user_id, sid):
    row = conn.execute(
        "SELECT * FROM school_years WHERE id = ? AND user_id = ?", (sid, user_id)
    ).fetchone()
    return SchoolYearOut(**dict(row)) if row else None


@router.post("", response_model=SchoolYearOut, status_code=201)
def create(body: SchoolYearCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    try:
        cur = conn.execute(
            "INSERT INTO school_years(user_id, label, start_date, end_date) VALUES (?,?,?,?)",
            (user_id, body.label, body.start_date, body.end_date),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Schuljahr-Label bereits vorhanden.")
    try:
        _fetch_and_store_dates(conn, user_id, cur.lastrowid, body.start_date, body.end_date)
    except Exception:  # Abruf best-effort – Schuljahr entsteht auch ohne Netz
        pass
    return _get(conn, user_id, cur.lastrowid)


@router.get("", response_model=List[SchoolYearOut])
def list_(conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        "SELECT * FROM school_years WHERE user_id = ? ORDER BY start_date", (user_id,)
    ).fetchall()
    return [SchoolYearOut(**dict(r)) for r in rows]


@router.get("/{sid}", response_model=SchoolYearOut)
def get_(sid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    return row_or_404(_get(conn, user_id, sid), "Schuljahr")


@router.put("/{sid}", response_model=SchoolYearOut)
def update(sid: int, body: SchoolYearUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, sid), "Schuljahr")
    fields = body.model_dump(exclude_unset=True)
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=sid, uid=user_id)
        conn.execute(f"UPDATE school_years SET {cols} WHERE id = :id AND user_id = :uid", fields)
        conn.commit()
    return _get(conn, user_id, sid)


@router.delete("/{sid}", status_code=204)
def delete(sid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute("DELETE FROM school_years WHERE id = ? AND user_id = ?", (sid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Schuljahr nicht gefunden.")


@router.get("/{sid}/dates", response_model=List[SchoolDateOut])
def list_dates(sid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, sid), "Schuljahr")
    rows = conn.execute(
        "SELECT * FROM school_dates WHERE school_year_id = ? AND user_id = ? ORDER BY start_date",
        (sid, user_id),
    ).fetchall()
    return [SchoolDateOut(**dict(r)) for r in rows]


@router.post("/{sid}/refresh-dates", response_model=List[SchoolDateOut])
def refresh_dates(sid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    sy = row_or_404(_get(conn, user_id, sid), "Schuljahr")
    conn.execute("DELETE FROM school_dates WHERE school_year_id = ? AND user_id = ?", (sid, user_id))
    conn.commit()
    try:
        _fetch_and_store_dates(conn, user_id, sid, sy.start_date, sy.end_date)
    except Exception:
        raise HTTPException(status_code=502, detail="Abruf der Ferien/Feiertage fehlgeschlagen.")
    return list_dates(sid, conn, user_id)
