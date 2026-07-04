"""Reflexionen (nutzer-gescoped). Rein manuell (keine Auto-Logik, BRIEFING Nicht-Ziele).

- POST /reflections            Reflexion zu einer Stunde erfassen
- GET  /reflections            Journal (mit Stundentitel)
- GET  /reflections/open       Stunden ohne Reflexion und nicht übersprungen
- POST /reflections/skip       Stunde als "keine Reflexion nötig" markieren
"""
import json
import sqlite3
from typing import List

from fastapi import APIRouter, Depends

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import (
    OpenReflectionOut, ReflectionCreate, ReflectionOut, SkipReflectionIn,
)

router = APIRouter(prefix="/reflections", tags=["reflections"])


def summarize_ampel(values) -> str:
    vals = values or []
    g = vals.count("gruen")
    y = vals.count("gelb")
    r = vals.count("rot")
    return f"{g} grün / {y} gelb / {r} rot"


def _lesson_of_user(conn, user_id, lesson_id):
    return conn.execute(
        "SELECT id, title FROM lessons WHERE id = ? AND user_id = ?", (lesson_id, user_id)
    ).fetchone()


@router.post("", response_model=ReflectionOut, status_code=201)
def create(body: ReflectionCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    lesson = row_or_404(_lesson_of_user(conn, user_id, body.lesson_id), "Stunde")
    summary = summarize_ampel(body.meyer_ist)
    cur = conn.execute(
        """INSERT INTO reflections(user_id, lesson_id, meyer_ist_json, ampel_summary, text)
           VALUES (?,?,?,?,?)""",
        (user_id, body.lesson_id,
         json.dumps(body.meyer_ist) if body.meyer_ist is not None else None,
         summary, body.text),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM reflections WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _to_out(dict(row), lesson["title"])


def _to_out(d, lesson_title=None) -> ReflectionOut:
    return ReflectionOut(
        id=d["id"], lesson_id=d["lesson_id"], lesson_title=lesson_title,
        meyer_ist=json.loads(d["meyer_ist_json"]) if d["meyer_ist_json"] else None,
        ampel_summary=d["ampel_summary"], text=d["text"], created_at=d["created_at"],
    )


@router.get("", response_model=List[ReflectionOut])
def list_(conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        """SELECT r.*, l.title AS lesson_title
           FROM reflections r JOIN lessons l ON l.id = r.lesson_id
           WHERE r.user_id = ? ORDER BY r.id DESC""",
        (user_id,),
    ).fetchall()
    return [_to_out(dict(r), r["lesson_title"]) for r in rows]


@router.get("/open", response_model=List[OpenReflectionOut])
def open_reflections(conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        """SELECT id, title, subject, grade FROM lessons l
           WHERE l.user_id = ? AND l.reflection_skipped = 0
             AND NOT EXISTS (SELECT 1 FROM reflections r WHERE r.lesson_id = l.id)
           ORDER BY l.id""",
        (user_id,),
    ).fetchall()
    return [OpenReflectionOut(lesson_id=r["id"], title=r["title"],
                              subject=r["subject"], grade=r["grade"]) for r in rows]


@router.post("/skip", status_code=204)
def skip(body: SkipReflectionIn, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_lesson_of_user(conn, user_id, body.lesson_id), "Stunde")
    conn.execute(
        "UPDATE lessons SET reflection_skipped = 1 WHERE id = ? AND user_id = ?",
        (body.lesson_id, user_id),
    )
    conn.commit()
