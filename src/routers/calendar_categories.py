"""CRUD Termin-Kategorien (nutzer-gescoped, U11). Unabhängig von entry_type."""
import sqlite3
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import CalendarCategoryCreate, CalendarCategoryOut, CalendarCategoryUpdate

router = APIRouter(prefix="/calendar-categories", tags=["calendar-categories"])

# Beim ersten Laden pro Nutzer angelegte Standard-Kategorien (idempotent).
DEFAULT_CATEGORIES = [
    ("Organisatorisch", "#2563eb", 0),
    ("Leistungsüberprüfung", "#dc2626", 1),
    ("Unterricht/Lernbereich", "#16a34a", 2),
]


def _get(conn, user_id, cid):
    row = conn.execute(
        "SELECT * FROM calendar_categories WHERE id = ? AND user_id = ?", (cid, user_id)
    ).fetchone()
    return CalendarCategoryOut(**dict(row)) if row else None


def _seed_defaults(conn, user_id):
    """Legt einmalig die Standard-Kategorien an, falls der Nutzer noch keine hat."""
    exists = conn.execute(
        "SELECT 1 FROM calendar_categories WHERE user_id = ? LIMIT 1", (user_id,)
    ).fetchone()
    if exists:
        return
    conn.executemany(
        "INSERT INTO calendar_categories(user_id, name, color, sort_order) VALUES (?,?,?,?)",
        [(user_id, name, color, order) for name, color, order in DEFAULT_CATEGORIES],
    )
    conn.commit()


@router.get("", response_model=List[CalendarCategoryOut])
def list_(conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _seed_defaults(conn, user_id)
    rows = conn.execute(
        "SELECT * FROM calendar_categories WHERE user_id = ? ORDER BY sort_order, id", (user_id,)
    ).fetchall()
    return [CalendarCategoryOut(**dict(r)) for r in rows]


@router.post("", response_model=CalendarCategoryOut, status_code=201)
def create(body: CalendarCategoryCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    try:
        cur = conn.execute(
            "INSERT INTO calendar_categories(user_id, name, color, sort_order) VALUES (?,?,?,?)",
            (user_id, body.name, body.color, body.sort_order),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige Kategorie: {exc}")
    return _get(conn, user_id, cur.lastrowid)


@router.put("/{cid}", response_model=CalendarCategoryOut)
def update(cid: int, body: CalendarCategoryUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, cid), "Kategorie")
    fields = body.model_dump(exclude_unset=True)
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=cid, uid=user_id)
        conn.execute(
            f"UPDATE calendar_categories SET {cols} WHERE id = :id AND user_id = :uid", fields
        )
        conn.commit()
    return _get(conn, user_id, cid)


@router.delete("/{cid}", status_code=204)
def delete(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        "DELETE FROM calendar_categories WHERE id = ? AND user_id = ?", (cid, user_id)
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Kategorie nicht gefunden.")
