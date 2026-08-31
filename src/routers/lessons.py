"""CRUD Stunden inkl. normalisierter Phasen (nutzer-gescoped).

Klafki = 5 Spalten, Bibox = 3 Spalten, Meyer-Ampel = JSON-Vektor[10].
Phasen liegen in lesson_phases; Insert/Update laufen transaktional (with conn),
sodass keine verwaisten Phasen entstehen.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import (
    Bibox, Klafki, LernzielIn, LernzielOut, LessonCreate, LessonMoveSlotIn, LessonMoveSlotOut,
    LessonOut, LessonUpcomingSlotOut, LessonUpdate, MaterialOut, PhaseIn, PhaseOut, Tafelbild,
)
from .calendar import _set_entry_classes

router = APIRouter(prefix="/lessons", tags=["lessons"])

_LESSON_COLS = (
    "class_id", "lernbereich_id", "title", "subject", "grade", "lesson_type",
    "duration_minutes", "time", "date",
    "klafki_gegenwart", "klafki_zukunft", "klafki_exemplarisch", "klafki_zugang",
    "klafki_struktur", "meyer_plan_json", "diff", "selbst_lernen",
    "bibox_werk", "bibox_seite", "bibox_notiz",
    "tafelbild_eingabe", "tafelbild_json", "tafelbild_notiz",
    "tafelbild_bild_material_id", "hefteintrag",
)


def _sync_calendar_entry(conn, user_id: int, lesson_id: int) -> None:
    """Hält den mit der Stunde verknüpften Kalendereintrag synchron.

    Verknüpft ist entweder ein automatisch erzeugter Eintrag oder ein manueller Termin,
    den der Nutzer per "jetzt Unterrichtsstunde planen" explizit mit dieser Stunde
    verlinkt hat (siehe /calendar PUT). Beide werden gleich behandelt, damit aus einem
    manuellen Termin heraus geplante Stunden nicht zusätzlich einen Auto-Eintrag erzeugen.
    """
    l = conn.execute(
        "SELECT date, title, class_id, time, duration_minutes FROM lessons WHERE id = ? AND user_id = ?",
        (lesson_id, user_id),
    ).fetchone()
    if l is None:
        return
    all_day = 1 if not l["time"] else 0
    start_time = l["time"] if l["time"] else None
    end_time = None
    if l["time"]:
        try:
            start_dt = datetime.strptime(l["time"], "%H:%M")
            end_time = (start_dt + timedelta(minutes=l["duration_minutes"] or 45)).strftime("%H:%M")
        except ValueError:
            all_day, start_time = 1, None
    # archivierte Einträge zählen nicht als "existing" – sonst würde ein Nutzer, der einen
    # archivierten Auto-Eintrag hat, bei jeder Stunden-Aktualisierung nur dessen (weiterhin
    # verstecktes) archived_at-Feld erben, statt einen neuen sichtbaren Eintrag zu bekommen.
    existing = conn.execute(
        "SELECT id, auto_generated FROM calendar_entries WHERE lesson_id = ? AND archived_at IS NULL",
        (lesson_id,),
    ).fetchone()
    if l["date"]:
        # calendar_entry_classes (Mehrfach-Klassen-Auswahl, sonst nur für manuelle Termine
        # gepflegt) muss hier mitgezogen werden — sonst zeigt die Kalender-Anzeige (die
        # class_ids gegenüber der Einzel-class_id-Spalte bevorzugt) nach einem Klassenwechsel
        # der Stunde weiterhin die alte Klasse an, obwohl class_id längst aktuell ist.
        class_ids = [l["class_id"]] if l["class_id"] is not None else []
        if existing:
            conn.execute(
                "UPDATE calendar_entries SET title = ?, entry_date = ?, class_id = ?, "
                "all_day = ?, start_time = ?, end_time = ?, "
                "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ?",
                (l["title"], l["date"], l["class_id"], all_day, start_time, end_time, existing["id"]),
            )
            _set_entry_classes(conn, user_id, existing["id"], class_ids)
        else:
            cur = conn.execute(
                "INSERT INTO calendar_entries"
                "(user_id, class_id, lesson_id, title, entry_date, all_day, start_time, end_time, "
                "entry_type, auto_generated, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?, 'normal', 1, strftime('%Y-%m-%d %H:%M:%f','now'))",
                (user_id, l["class_id"], lesson_id, l["title"], l["date"], all_day, start_time, end_time),
            )
            _set_entry_classes(conn, user_id, cur.lastrowid, class_ids)
    elif existing:
        if existing["auto_generated"]:
            conn.execute("DELETE FROM calendar_entries WHERE id = ?", (existing["id"],))
        else:
            # manueller Termin bleibt erhalten, verliert aber die Verknüpfung.
            conn.execute(
                "UPDATE calendar_entries SET lesson_id = NULL, "
                "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ?",
                (existing["id"],),
            )


def _lesson_values(body, klafki: Klafki, bibox: Bibox, meyer_plan, tafelbild: Tafelbild) -> dict:
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
        "tafelbild_eingabe": body.tafelbild_eingabe,
        "tafelbild_json": json.dumps(tafelbild.model_dump()) if tafelbild is not None else None,
        "tafelbild_notiz": body.tafelbild_notiz,
        "tafelbild_bild_material_id": body.tafelbild_bild_material_id,
        "hefteintrag": body.hefteintrag,
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
        tafelbild_eingabe=d["tafelbild_eingabe"],
        tafelbild=Tafelbild(**json.loads(d["tafelbild_json"])) if d["tafelbild_json"] else Tafelbild(),
        tafelbild_notiz=d["tafelbild_notiz"],
        tafelbild_bild_material_id=d["tafelbild_bild_material_id"],
        hefteintrag=d["hefteintrag"],
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


def _apply_create_lesson(conn, user_id: int, body: LessonCreate) -> LessonOut:
    vals = _lesson_values(body, body.klafki, body.bibox, body.meyer_plan, body.tafelbild)
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


@router.post("", response_model=LessonOut, status_code=201)
def create(body: LessonCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    return _apply_create_lesson(conn, user_id, body)


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
           WHERE ml.lesson_id = ? AND m.user_id = ? AND m.archived_at IS NULL ORDER BY m.id""",
        (lid, user_id),
    ).fetchall()
    return [MaterialOut(**dict(r)) for r in rows]


def _apply_update_lesson(conn, user_id: int, lid: int, body: LessonUpdate) -> LessonOut:
    row_or_404(_fetch(conn, user_id, lid), "Stunde")
    data = body.model_dump(exclude_unset=True)
    sets = {}
    for key in ("class_id", "lernbereich_id", "title", "subject", "grade",
                "lesson_type", "duration_minutes", "time", "date", "diff", "selbst_lernen",
                "tafelbild_eingabe", "tafelbild_notiz", "tafelbild_bild_material_id",
                "hefteintrag"):
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
    if "tafelbild" in data and body.tafelbild is not None:
        sets["tafelbild_json"] = json.dumps(body.tafelbild.model_dump())
    if "meyer_plan" in data:
        sets["meyer_plan_json"] = json.dumps(body.meyer_plan) if body.meyer_plan is not None else None
    if "reflection_skipped" in data and body.reflection_skipped is not None:
        sets["reflection_skipped"] = int(body.reflection_skipped)
    # phases/lernziele werden eingebettet im lessons-Sync-Payload transportiert (kein eigener
    # entity_type) — ändern sie sich ohne sonstige Spaltenänderung, muss updated_at trotzdem
    # bumpen, sonst bleibt sync_log stumm und andere Geräte sehen die neuen Phasen nie.
    touches_children = ("phases" in data and body.phases is not None) or \
        ("lernziele" in data and body.lernziele is not None)
    with conn:
        if sets or touches_children:
            cols = ", ".join(f"{k} = :{k}" for k in sets)
            cols = f"{cols}, " if cols else ""
            sets.update(id=lid, uid=user_id)
            conn.execute(
                f"UPDATE lessons SET {cols}updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
                f"WHERE id = :id AND user_id = :uid",
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


@router.put("/{lid}", response_model=LessonOut)
def update(lid: int, body: LessonUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    return _apply_update_lesson(conn, user_id, lid, body)


def _apply_delete_lesson(conn, user_id: int, lid: int) -> None:
    # Auto-Kalendereintrag der Stunde mit entfernen (manuelle bleiben via ON DELETE SET NULL).
    conn.execute("DELETE FROM calendar_entries WHERE lesson_id = ? AND auto_generated = 1", (lid,))
    cur = conn.execute("DELETE FROM lessons WHERE id = ? AND user_id = ?", (lid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Stunde nicht gefunden.")


@router.delete("/{lid}", status_code=204)
def delete(lid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _apply_delete_lesson(conn, user_id, lid)


@router.get("/{lid}/upcoming-slots", response_model=List[LessonUpcomingSlotOut])
def upcoming_slots(lid: int, count: int = Query(default=8, ge=1, le=20),
                    conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    """Liste der nächsten laut Stundenplan realen Unterrichtstermine der Klasse dieser Stunde –
    Auswahlbasis für "Stunde verschieben" im Planungskalender (nur echte Stundenplan-Slots
    wählbar, kein Freitext-Datum)."""
    from .sequenzplan import _next_class_slot   # lokal: sequenzplan.py importiert umgekehrt von hier
    row = row_or_404(_fetch(conn, user_id, lid), "Stunde")
    if row["class_id"] is None:
        return []
    after = row["date"] or date.today().isoformat()
    slots = []
    for _ in range(count):
        nxt = _next_class_slot(conn, user_id, row["class_id"], after)
        if nxt is None:
            break
        slots.append(LessonUpcomingSlotOut(date=nxt["date"], time=nxt["time"], span_slots=nxt["span_slots"]))
        after = nxt["date"]
    return slots


@router.post("/{lid}/move-to-slot", response_model=LessonMoveSlotOut)
def move_to_slot(lid: int, body: LessonMoveSlotIn, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    """"Stunde verschieben" im Planungskalender: setzt Datum/Uhrzeit der Stunde neu (Auswahl aus
    upcoming_slots) und verschiebt eine ggf. verknüpfte Sequenzstunde mit an eine neue Zeile am
    Zielort – die Ursprungszeile bleibt stehen (moved_to_id verweist auf die neue Zeile), siehe
    sequenzplan.py::move_sequenz_for_lesson."""
    from .sequenzplan import move_sequenz_for_lesson   # lokal: s. upcoming_slots oben
    row_or_404(_fetch(conn, user_id, lid), "Stunde")
    with conn:
        conn.execute(
            "UPDATE lessons SET date = ?, time = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
            "WHERE id = ? AND user_id = ?",
            (body.date, body.time, lid, user_id),
        )
        _sync_calendar_entry(conn, user_id, lid)
        moved = move_sequenz_for_lesson(conn, user_id, lid, body.date, body.with_calendar)
    lesson_out = _row_to_out(conn, _fetch(conn, user_id, lid))
    if moved is None:
        return LessonMoveSlotOut(lesson=lesson_out)
    new_id, over_budget, planned_count, richtwert = moved
    return LessonMoveSlotOut(
        lesson=lesson_out, new_sequenz_stunde_id=new_id,
        over_budget=over_budget, planned_count=planned_count, richtwert_ustd=richtwert,
    )


# ---------- Sync-Handler-Registry: lessons (src/routers/sync.py) ----------
# phases/lernziele sind eingebettet im Payload (Nutzer-Entscheidung: kein eigener
# entity_type, siehe _apply_update_lesson-Kommentar) — sync.py behandelt lessons daher wie
# jede andere Einzeltabellen-Entität.

def _sync_fetch_lesson(conn, user_id, entity_id):
    row = _fetch(conn, user_id, entity_id)
    return _row_to_out(conn, row) if row is not None else None


def _sync_create_lesson(conn, user_id, payload: dict) -> LessonOut:
    return _apply_create_lesson(conn, user_id, LessonCreate(**payload))


def _sync_update_lesson(conn, user_id, entity_id, payload: dict) -> LessonOut:
    return _apply_update_lesson(conn, user_id, entity_id, LessonUpdate(**payload))


def _sync_delete_lesson(conn, user_id, entity_id) -> None:
    _apply_delete_lesson(conn, user_id, entity_id)


SYNC_HANDLER = {
    "fetch": _sync_fetch_lesson,
    "create": _sync_create_lesson,
    "update": _sync_update_lesson,
    "delete": _sync_delete_lesson,
}
