"""Jahres-Verplanung (deterministischer Platzhalter, in M7 durch Claude ersetzt).

Verteilt die Lernbereiche einer Klasse über das Schuljahr – Grundlage:
Stundenrichtwerte + Wochenstunden + Ferien/Feiertage + fixe Termine. Liefert nur
einen Vorschlag (Preview); nichts wird automatisch gespeichert.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..lib.planning import distribute_lernbereiche, effective_blocks, resolve_track
from ..schemas import (
    PlanningRequest, PlanningResult, PlanNoteIn, PlanNoteOut,
    PlanNoteSyncCreate, PlanNoteSyncUpdate,
)

router = APIRouter(prefix="/planning", tags=["planning"])


def _get_plan_note(conn, user_id, pid):
    row = conn.execute(
        "SELECT * FROM plan_notes WHERE id = ? AND user_id = ?", (pid, user_id)
    ).fetchone()
    return PlanNoteOut(**dict(row)) if row else None


def _apply_create(conn, user_id, body: PlanNoteSyncCreate) -> PlanNoteOut:
    # Klasse/Schuljahr müssen dem Nutzer gehören (Scoping + FK-Schutz, wie beim alten Upsert).
    row_or_404(conn.execute("SELECT id FROM classes WHERE id=? AND user_id=?",
                            (body.class_id, user_id)).fetchone(), "Klasse")
    row_or_404(conn.execute("SELECT id FROM school_years WHERE id=? AND user_id=?",
                            (body.school_year_id, user_id)).fetchone(), "Schuljahr")
    try:
        # Bewusst ein reines INSERT (kein ON CONFLICT DO UPDATE wie beim alten Upsert-Endpunkt):
        # legen zwei Geräte offline beide eine erste Notiz für dieselbe Klasse/Schuljahr an,
        # soll das als Konflikt auffallen statt die zuerst angewandte Version still zu überschreiben.
        cur = conn.execute(
            "INSERT INTO plan_notes(user_id, class_id, school_year_id, text, updated_at) "
            "VALUES (?,?,?,?, strftime('%Y-%m-%d %H:%M:%f','now'))",
            (user_id, body.class_id, body.school_year_id, body.text or ""),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Für diese Klasse/dieses Schuljahr existieren bereits Ideen — bitte neu laden.",
        )
    return _get_plan_note(conn, user_id, cur.lastrowid)


def _apply_update(conn, user_id, pid: int, body: PlanNoteSyncUpdate) -> PlanNoteOut:
    row_or_404(_get_plan_note(conn, user_id, pid), "Jahresplan-Ideen")
    conn.execute(
        "UPDATE plan_notes SET text = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
        "WHERE id = ? AND user_id = ?",
        (body.text or "", pid, user_id),
    )
    return _get_plan_note(conn, user_id, pid)


def _apply_delete(conn, user_id, pid: int) -> None:
    cur = conn.execute("DELETE FROM plan_notes WHERE id = ? AND user_id = ?", (pid, user_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Jahresplan-Ideen nicht gefunden.")


@router.post("/preview", response_model=PlanningResult)
def preview(body: PlanningRequest, conn: sqlite3.Connection = Depends(get_db),
            user_id: int = Depends(get_user_id)):
    sy = row_or_404(
        conn.execute("SELECT * FROM school_years WHERE id = ? AND user_id = ?",
                     (body.school_year_id, user_id)).fetchone(), "Schuljahr")
    cls = row_or_404(
        conn.execute("SELECT * FROM classes WHERE id = ? AND user_id = ?",
                     (body.class_id, user_id)).fetchone(), "Klasse")

    track = resolve_track(cls["subject"], cls["grade"], cls["track"])
    lbs = conn.execute(
        """SELECT id, code, title, richtwert_ustd FROM lernbereiche
           WHERE subject = ? AND grade = ? AND track = ? ORDER BY sort_order""",
        (cls["subject"], cls["grade"], track),
    ).fetchall()
    if not lbs:
        raise HTTPException(
            status_code=404,
            detail="Keine Lernbereiche für Fach/Klassenstufe/Bildungsgang dieser Klasse gefunden.",
        )
    blocks = effective_blocks(cls["subject"], [dict(r) for r in lbs])

    ferien = [(r["start_date"], r["end_date"]) for r in conn.execute(
        "SELECT start_date, end_date FROM school_dates WHERE school_year_id = ? AND user_id = ?",
        (body.school_year_id, user_id))]
    fixed = [r["entry_date"] for r in conn.execute(
        "SELECT entry_date FROM calendar_entries WHERE user_id = ? AND class_id = ? AND is_fixed = 1",
        (user_id, body.class_id))]

    return distribute_lernbereiche(
        sy["start_date"], sy["end_date"], cls["weekly_hours"],
        blocks, ferien, fixed,
    )


@router.get("/notes", response_model=PlanNoteOut)
def get_notes(class_id: int = Query(alias="classId"),
              school_year_id: int = Query(alias="schoolYearId"),
              conn: sqlite3.Connection = Depends(get_db),
              user_id: int = Depends(get_user_id)):
    row = conn.execute(
        "SELECT id, text, updated_at FROM plan_notes WHERE user_id=? AND class_id=? AND school_year_id=?",
        (user_id, class_id, school_year_id)).fetchone()
    return PlanNoteOut(
        id=(row["id"] if row else None),
        class_id=class_id, school_year_id=school_year_id,
        text=(row["text"] if row else ""),
        updated_at=(row["updated_at"] if row else None),
    )


@router.put("/notes", response_model=PlanNoteOut)
def put_notes(body: PlanNoteIn, conn: sqlite3.Connection = Depends(get_db),
              user_id: int = Depends(get_user_id)):
    # Klasse/Schuljahr müssen dem Nutzer gehören (Scoping + FK-Schutz).
    row_or_404(conn.execute("SELECT id FROM classes WHERE id=? AND user_id=?",
                            (body.class_id, user_id)).fetchone(), "Klasse")
    row_or_404(conn.execute("SELECT id FROM school_years WHERE id=? AND user_id=?",
                            (body.school_year_id, user_id)).fetchone(), "Schuljahr")
    conn.execute(
        """INSERT INTO plan_notes (user_id, class_id, school_year_id, text, updated_at)
           VALUES (?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f','now'))
           ON CONFLICT(user_id, class_id, school_year_id)
           DO UPDATE SET text=excluded.text, updated_at=strftime('%Y-%m-%d %H:%M:%f','now')""",
        (user_id, body.class_id, body.school_year_id, body.text or ""))
    conn.commit()
    row = conn.execute(
        "SELECT id, text, updated_at FROM plan_notes WHERE user_id=? AND class_id=? AND school_year_id=?",
        (user_id, body.class_id, body.school_year_id)).fetchone()
    return PlanNoteOut(id=row["id"], class_id=body.class_id, school_year_id=body.school_year_id,
                       text=row["text"], updated_at=row["updated_at"])


# ---------- Sync-Handler-Registry (src/routers/sync.py) ----------

def _sync_fetch(conn, user_id, entity_id):
    return _get_plan_note(conn, user_id, entity_id)


def _sync_create(conn, user_id, payload: dict) -> PlanNoteOut:
    return _apply_create(conn, user_id, PlanNoteSyncCreate(**payload))


def _sync_update(conn, user_id, entity_id, payload: dict) -> PlanNoteOut:
    return _apply_update(conn, user_id, entity_id, PlanNoteSyncUpdate(**payload))


def _sync_delete(conn, user_id, entity_id) -> None:
    _apply_delete(conn, user_id, entity_id)


SYNC_HANDLER = {
    "fetch": _sync_fetch,
    "create": _sync_create,
    "update": _sync_update,
    "delete": _sync_delete,
}
