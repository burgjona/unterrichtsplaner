"""CRUD Stunden inkl. normalisierter Phasen (nutzer-gescoped).

Klafki = 5 Spalten, Bibox = 3 Spalten, Meyer-Ampel = JSON-Vektor[10].
Phasen liegen in lesson_phases; Insert/Update laufen transaktional (with conn),
sodass keine verwaisten Phasen entstehen.
"""
import json
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import (
    Bibox, Klafki, LernzielIn, LernzielOut, LessonCreate, LessonOut, LessonUpdate,
    MaterialOut, PhaseIn, PhaseOut,
)

router = APIRouter(prefix="/lessons", tags=["lessons"])

_LESSON_COLS = (
    "class_id", "lernbereich_id", "title", "subject", "grade", "lesson_type",
    "duration_minutes", "time", "date",
    "klafki_gegenwart", "klafki_zukunft", "klafki_exemplarisch", "klafki_zugang",
    "klafki_struktur", "meyer_plan_json", "diff", "selbst_lernen",
    "bibox_werk", "bibox_seite", "bibox_notiz",
)


def _sync_calendar_entry(conn, user_id: int, lesson_id: int) -> None:
    """Hält den automatisch erzeugten Kalendereintrag einer terminierten Stunde synchron."""
    l = conn.execute(
        "SELECT date, title, class_id FROM lessons WHERE id = ? AND user_id = ?", (lesson_id, user_id)
    ).fetchone()
    if l is None:
        return
    existing = conn.execute(
        "SELECT id FROM calendar_entries WHERE lesson_id = ? AND auto_generated = 1", (lesson_id,)
    ).fetchone()
    if l["date"]:
        if existing:
            conn.execute(
                "UPDATE calendar_entries SET title = ?, entry_date = ?, class_id = ? WHERE id = ?",
                (l["title"], l["date"], l["class_id"], existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO calendar_entries(user_id, class_id, lesson_id, title, entry_date, entry_type, auto_generated) "
                "VALUES (?,?,?,?,?, 'normal', 1)",
                (user_id, l["class_id"], lesson_id, l["title"], l["date"]),
            )
    elif existing:
        conn.execute("DELETE FROM calendar_entries WHERE id = ?", (existing["id"],))


def _lesson_values(body, klafki: Klafki, bibox: Bibox, meyer_plan) -> dict:
    return {
        "class_id": body.class_id,
        "lernbereich_id": body.lernbereich_id,
        "title": body.title,
        "subject": body.subject,
        "grade": body.grade,
        "lesson_type": body.lesson_type,
        "duration_minutes": body.duration_minutes,
        "time": body.time,
        "date": body.date,
        "klafki_gegenwart": klafki.gegenwart,
        "klafki_zukunft": klafki.zukunft,
        "klafki_exemplarisch": klafki.exemplarisch,
        "klafki_zugang": klafki.zugang,
        "klafki_struktur": klafki.struktur,
        "meyer_plan_json": json.dumps(meyer_plan) if meyer_plan is not None else None,
        "diff": body.diff,
        "selbst_lernen": body.selbst_lernen,
        "bibox_werk": bibox.werk,
        "bibox_seite": bibox.seite,
        "bibox_notiz": bibox.notiz,
    }


def _insert_phases(conn, lesson_id: int, phases: List[PhaseIn]) -> None:
    for i, p in enumerate(phases):
        conn.execute(
            """INSERT INTO lesson_phases
               (lesson_id, sort_order, phase_name, minutes, social_form, method,
                material, teacher_activity, student_activity, gme)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (lesson_id, i, p.phase_name, p.minutes, p.social_form, p.method,
             p.material, p.teacher_activity, p.student_activity, p.gme),
        )


def _insert_lernziele(conn, lesson_id: int, ziele: List[LernzielIn]) -> None:
    for i, z in enumerate(ziele):
        # sort_order: expliziter Wert falls gesetzt (>0), sonst Reihenfolge in der Liste
        so = z.sort_order if z.sort_order else i
        conn.execute(
            """INSERT INTO lesson_lernziele
               (lesson_id, kind, text, bloom_stufe, phase_sort_order, sort_order)
               VALUES (?,?,?,?,?,?)""",
            (lesson_id, z.kind, z.text, z.bloom_stufe, z.phase_sort_order, so),
        )


def _row_to_out(conn, row) -> LessonOut:
    d = dict(row)
    phases = conn.execute(
        "SELECT * FROM lesson_phases WHERE lesson_id = ? ORDER BY sort_order", (d["id"],)
    ).fetchall()
    ziele = conn.execute(
        "SELECT * FROM lesson_lernziele WHERE lesson_id = ? ORDER BY sort_order, id", (d["id"],)
    ).fetchall()
    return LessonOut(
        id=d["id"], title=d["title"], subject=d["subject"], grade=d["grade"],
        class_id=d["class_id"], lernbereich_id=d["lernbereich_id"],
        lesson_type=d["lesson_type"], duration_minutes=d["duration_minutes"],
        time=d["time"], date=d["date"],
        klafki=Klafki(
            gegenwart=d["klafki_gegenwart"] or "", zukunft=d["klafki_zukunft"] or "",
            exemplarisch=d["klafki_exemplarisch"] or "", zugang=d["klafki_zugang"] or "",
            struktur=d["klafki_struktur"] or "",
        ),
        meyer_plan=json.loads(d["meyer_plan_json"]) if d["meyer_plan_json"] else None,
        diff=d["diff"], selbst_lernen=d["selbst_lernen"],
        bibox=Bibox(werk=d["bibox_werk"] or "", seite=d["bibox_seite"] or "", notiz=d["bibox_notiz"] or ""),
        phases=[PhaseOut(**dict(p)) for p in phases],
        lernziele=[LernzielOut(
            id=z["id"], kind=z["kind"], text=z["text"], bloom_stufe=z["bloom_stufe"],
            phase_sort_order=z["phase_sort_order"], sort_order=z["sort_order"],
        ) for z in ziele],
        created_at=d["created_at"], updated_at=d["updated_at"],
    )


def _fetch(conn, user_id, lid):
    return conn.execute(
        "SELECT * FROM lessons WHERE id = ? AND user_id = ?", (lid, user_id)
    ).fetchone()


@router.post("", response_model=LessonOut, status_code=201)
def create(body: LessonCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    vals = _lesson_values(body, body.klafki, body.bibox, body.meyer_plan)
    vals["user_id"] = user_id
    cols = ", ".join(["user_id", *_LESSON_COLS])
    placeholders = ", ".join(f":{c}" for c in ["user_id", *_LESSON_COLS])
    try:
        with conn:
            cur = conn.execute(f"INSERT INTO lessons({cols}) VALUES ({placeholders})", vals)
            _insert_phases(conn, cur.lastrowid, body.phases)
            _insert_lernziele(conn, cur.lastrowid, body.lernziele)
            _sync_calendar_entry(conn, user_id, cur.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige Referenz: {exc}")
    return _row_to_out(conn, _fetch(conn, user_id, cur.lastrowid))


@router.get("", response_model=List[LessonOut])
def list_(
    class_id: Optional[int] = Query(None, alias="classId"),
    subject: Optional[str] = None,
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    sql = "SELECT * FROM lessons WHERE user_id = ?"
    params = [user_id]
    if class_id is not None:
        sql += " AND class_id = ?"
        params.append(class_id)
    if subject is not None:
        sql += " AND subject = ?"
        params.append(subject)
    sql += " ORDER BY id"
    return [_row_to_out(conn, r) for r in conn.execute(sql, params).fetchall()]


@router.get("/{lid}", response_model=LessonOut)
def get_(lid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row = row_or_404(_fetch(conn, user_id, lid), "Stunde")
    return _row_to_out(conn, row)


@router.get("/{lid}/materials", response_model=List[MaterialOut])
def lesson_materials(lid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_fetch(conn, user_id, lid), "Stunde")
    rows = conn.execute(
        """SELECT m.* FROM materials m JOIN material_lessons ml ON ml.material_id = m.id
           WHERE ml.lesson_id = ? AND m.user_id = ? ORDER BY m.id""",
        (lid, user_id),
    ).fetchall()
    return [MaterialOut(**dict(r)) for r in rows]


@router.put("/{lid}", response_model=LessonOut)
def update(lid: int, body: LessonUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_fetch(conn, user_id, lid), "Stunde")
    data = body.model_dump(exclude_unset=True)
    sets = {}
    for key in ("class_id", "lernbereich_id", "title", "subject", "grade",
                "lesson_type", "duration_minutes", "time", "date", "diff", "selbst_lernen"):
        if key in data:
            sets[key] = data[key]
    if "klafki" in data and body.klafki is not None:
        k = body.klafki
        sets.update(klafki_gegenwart=k.gegenwart, klafki_zukunft=k.zukunft,
                    klafki_exemplarisch=k.exemplarisch, klafki_zugang=k.zugang,
                    klafki_struktur=k.struktur)
    if "bibox" in data and body.bibox is not None:
        b = body.bibox
        sets.update(bibox_werk=b.werk, bibox_seite=b.seite, bibox_notiz=b.notiz)
    if "meyer_plan" in data:
        sets["meyer_plan_json"] = json.dumps(body.meyer_plan) if body.meyer_plan is not None else None
    with conn:
        if sets:
            cols = ", ".join(f"{k} = :{k}" for k in sets)
            sets.update(id=lid, uid=user_id)
            conn.execute(
                f"UPDATE lessons SET {cols}, updated_at = datetime('now') WHERE id = :id AND user_id = :uid",
                sets,
            )
        if "phases" in data and body.phases is not None:
            conn.execute("DELETE FROM lesson_phases WHERE lesson_id = ?", (lid,))
            _insert_phases(conn, lid, body.phases)
        if "lernziele" in data and body.lernziele is not None:
            conn.execute("DELETE FROM lesson_lernziele WHERE lesson_id = ?", (lid,))
            _insert_lernziele(conn, lid, body.lernziele)
        _sync_calendar_entry(conn, user_id, lid)
    return _row_to_out(conn, _fetch(conn, user_id, lid))


@router.delete("/{lid}", status_code=204)
def delete(lid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    # Auto-Kalendereintrag der Stunde mit entfernen (manuelle bleiben via ON DELETE SET NULL).
    conn.execute("DELETE FROM calendar_entries WHERE lesson_id = ? AND auto_generated = 1", (lid,))
    cur = conn.execute("DELETE FROM lessons WHERE id = ? AND user_id = ?", (lid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Stunde nicht gefunden.")
