"""Jahres-Verplanung (deterministischer Platzhalter, in M7 durch Claude ersetzt).

Verteilt die Lernbereiche einer Klasse über das Schuljahr – Grundlage:
Stundenrichtwerte + Wochenstunden + Ferien/Feiertage + fixe Termine. Liefert nur
einen Vorschlag (Preview); nichts wird automatisch gespeichert.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, get_user_id, row_or_404
from ..lib.planning import distribute_lernbereiche
from ..schemas import PlanningRequest, PlanningResult

router = APIRouter(prefix="/planning", tags=["planning"])


@router.post("/preview", response_model=PlanningResult)
def preview(body: PlanningRequest, conn: sqlite3.Connection = Depends(get_db),
            user_id: int = Depends(get_user_id)):
    sy = row_or_404(
        conn.execute("SELECT * FROM school_years WHERE id = ? AND user_id = ?",
                     (body.school_year_id, user_id)).fetchone(), "Schuljahr")
    cls = row_or_404(
        conn.execute("SELECT * FROM classes WHERE id = ? AND user_id = ?",
                     (body.class_id, user_id)).fetchone(), "Klasse")

    lbs = conn.execute(
        """SELECT id, code, title, richtwert_ustd FROM lernbereiche
           WHERE subject = ? AND grade = ? AND track = ? ORDER BY sort_order""",
        (cls["subject"], cls["grade"], cls["track"]),
    ).fetchall()
    if not lbs:
        raise HTTPException(
            status_code=404,
            detail="Keine Lernbereiche für Fach/Klassenstufe/Bildungsgang dieser Klasse gefunden.",
        )

    ferien = [(r["start_date"], r["end_date"]) for r in conn.execute(
        "SELECT start_date, end_date FROM school_dates WHERE school_year_id = ? AND user_id = ?",
        (body.school_year_id, user_id))]
    fixed = [r["entry_date"] for r in conn.execute(
        "SELECT entry_date FROM calendar_entries WHERE user_id = ? AND class_id = ? AND is_fixed = 1",
        (user_id, body.class_id))]

    return distribute_lernbereiche(
        sy["start_date"], sy["end_date"], cls["weekly_hours"],
        [dict(r) for r in lbs], ferien, fixed,
    )
