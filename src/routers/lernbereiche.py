"""Lernbereich-Referenz (global, geseedet aus den LP-Dateien).

GET ist offen und filterbar; POST/PUT/DELETE dienen Korrekturen/Erweiterungen
der Referenz und sind nicht nutzer-gescoped.
"""
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, row_or_404
from ..schemas import LernbereichCreate, LernbereichOut

router = APIRouter(prefix="/lernbereiche", tags=["lernbereiche"])


def _get(conn, lid):
    row = conn.execute("SELECT * FROM lernbereiche WHERE id = ?", (lid,)).fetchone()
    return LernbereichOut(**dict(row)) if row else None


@router.get("", response_model=List[LernbereichOut])
def list_(
    subject: Optional[str] = None,
    grade: Optional[int] = None,
    track: Optional[str] = None,
    conn=Depends(get_db),
):
    sql = "SELECT * FROM lernbereiche WHERE 1=1"
    params = []
    for col, val in (("subject", subject), ("grade", grade), ("track", track)):
        if val is not None:
            sql += f" AND {col} = ?"
            params.append(val)
    sql += " ORDER BY subject, grade, track, sort_order"
    return [LernbereichOut(**dict(r)) for r in conn.execute(sql, params).fetchall()]


@router.get("/{lid}", response_model=LernbereichOut)
def get_(lid: int, conn=Depends(get_db)):
    return row_or_404(_get(conn, lid), "Lernbereich")


@router.post("", response_model=LernbereichOut, status_code=201)
def create(body: LernbereichCreate, conn=Depends(get_db)):
    try:
        cur = conn.execute(
            """INSERT INTO lernbereiche
               (subject, grade, track, code, title, richtwert_ustd, sort_order, source)
               VALUES (?,?,?,?,?,?,?,?)""",
            (body.subject, body.grade, body.track, body.code, body.title,
             body.richtwert_ustd, body.sort_order, body.source),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Lernbereich (Fach/Stufe/Bildungsgang/Code) existiert bereits.")
    return _get(conn, cur.lastrowid)


@router.delete("/{lid}", status_code=204)
def delete(lid: int, conn=Depends(get_db)):
    cur = conn.execute("DELETE FROM lernbereiche WHERE id = ?", (lid,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Lernbereich nicht gefunden.")
