"""Persönlicher Stundenplan des Lehrers (U27, nutzer-gescoped).

Fünf Ressourcen unter /stundenplan:
  * kinds     – Eintragstypen (Unterricht/Aufsicht/…), genau einer ist Default.
  * slots     – Klingelraster (Stunden + Pausen), über position sortiert.
  * plans     – Pläne mit Gültigkeit-ab-Datum; optionales Kopieren beim Anlegen.
  * entries   – Einträge je Plan/Slot/Wochentag/A-B-Woche (span_slots = Höhe).
  * settings  – A/B-Wochen-Parität; GET liefert zusätzlich ISO-Woche/Typ für heute.

Die A/B-Woche wird IMMER serverseitig aufgelöst (GET /resolved): Montag → ISO-KW →
Parität → A/B. Beim ersten GET jedes Nutzers werden Default-Typen, ein Klingelraster,
ein Plan und die Settings-Zeile idempotent angelegt (_seed_defaults).
"""
import sqlite3
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import (
    TimetableEntryCreate, TimetableEntryOut, TimetableEntryUpdate,
    TimetableKindCreate, TimetableKindOut, TimetableKindUpdate,
    TimetablePlanCreate, TimetablePlanOut, TimetablePlanUpdate,
    TimetableResolved, TimetableResolvedDay, TimetableResolvedItem,
    TimetableSettingsOut, TimetableSettingsUpdate,
    TimetableSlotCreate, TimetableSlotOut, TimetableSlotUpdate,
)

router = APIRouter(prefix="/stundenplan", tags=["stundenplan"])

# Fachfarben (Klasse ohne eigene Eintrags-Farbe): Deutsch grün, WTH orange.
SUBJECT_COLORS = {"Deutsch": "#16a34a", "WTH": "#f97316"}

# Standard-Typen (name, color, sort_order, is_default) – Reihenfolge = sort_order 0..6.
DEFAULT_KINDS = [
    ("Unterricht", "#16a34a", 0, 0),
    ("Aufsicht", "#eab308", 1, 0),
    ("Seminar/Hospitation", "#7c3aed", 2, 0),
    ("GTA/AG", "#0ea5e9", 3, 0),
    ("Förderunterricht", "#14b8a6", 4, 0),
    ("Dienstberatung/Konferenz", "#64748b", 5, 0),
    ("Sonstiges", "#94a3b8", 6, 1),
]

# Standard-Klingelraster (position, slot_type, label, start, end) – position 0..10.
DEFAULT_SLOTS = [
    (0, "break", "Frühaufsicht", "07:10", "07:25"),
    (1, "lesson", "1.", "07:30", "08:15"),
    (2, "lesson", "2.", "08:25", "09:10"),
    (3, "break", "Hofpause", "09:10", "09:30"),
    (4, "lesson", "3.", "09:30", "10:15"),
    (5, "lesson", "4.", "10:25", "11:10"),
    (6, "lesson", "5.", "11:20", "12:05"),
    (7, "break", "Mittagspause", "12:05", "12:45"),
    (8, "lesson", "6.", "12:45", "13:30"),
    (9, "lesson", "7.", "13:40", "14:25"),
    (10, "lesson", "8.", "14:30", "15:15"),
]


# ---------------------------------------------------------------- Helfer
def _monday_of(d: date) -> date:
    """Montag der ISO-Woche, in der d liegt (weekday(): Montag == 0)."""
    return d - timedelta(days=d.weekday())


def _week_type_for(iso_week: int, week_a_parity: str) -> str:
    """A, wenn die Parität der KW der eingestellten A-Wochen-Parität entspricht, sonst B."""
    parity = "odd" if iso_week % 2 == 1 else "even"
    return "A" if parity == week_a_parity else "B"


def _require_owned(conn, table: str, row_id: int, user_id: int, entity: str) -> None:
    """404, falls die Zeile nicht existiert oder einem anderen Nutzer gehört.
    table stammt ausschließlich aus internen Literalen (kein Nutzer-Input)."""
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE id = ? AND user_id = ?", (row_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{entity} nicht gefunden.")


def _validate_span(conn, user_id: int, slot_id: int, span_slots: int) -> None:
    """Ab dem Anker-Slot müssen (nach position sortiert) mindestens span_slots Slots
    existieren – sonst ragt der Eintrag über das Klingelraster hinaus."""
    ordered = conn.execute(
        "SELECT id FROM timetable_slots WHERE user_id = ? ORDER BY position, id", (user_id,)
    ).fetchall()
    idx = next((i for i, s in enumerate(ordered) if s["id"] == slot_id), None)
    if idx is None:                                   # defensiv (Slot vorab geprüft)
        raise HTTPException(status_code=404, detail="Slot nicht gefunden.")
    if idx + span_slots > len(ordered):
        raise HTTPException(status_code=400, detail="Span ragt über das Klingelraster hinaus.")


def _seed_defaults(conn, user_id: int) -> None:
    """Legt Typen, Klingelraster, Plan und Settings-Zeile einmalig an (idempotent).
    Marker = Existenz der timetable_settings-Zeile. Double-Checked-Locking via
    BEGIN IMMEDIATE gegen parallele Erst-Requests desselben Nutzers."""
    if conn.execute(
        "SELECT 1 FROM timetable_settings WHERE user_id = ? LIMIT 1", (user_id,)
    ).fetchone():
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute(
            "SELECT 1 FROM timetable_settings WHERE user_id = ? LIMIT 1", (user_id,)
        ).fetchone():
            conn.rollback()
            return
        conn.executemany(
            "INSERT INTO timetable_kinds(user_id, name, color, sort_order, is_default) "
            "VALUES (?,?,?,?,?)",
            [(user_id, name, color, order, is_def) for name, color, order, is_def in DEFAULT_KINDS],
        )
        conn.executemany(
            "INSERT INTO timetable_slots(user_id, position, slot_type, label, start_time, end_time) "
            "VALUES (?,?,?,?,?,?)",
            [(user_id, pos, stype, label, start, end)
             for pos, stype, label, start, end in DEFAULT_SLOTS],
        )
        conn.execute(
            "INSERT INTO timetable_plans(user_id, name, valid_from) VALUES (?,?,?)",
            (user_id, "Stundenplan", _monday_of(date.today()).isoformat()),
        )
        conn.execute(
            "INSERT INTO timetable_settings(user_id, week_a_parity) VALUES (?, 'odd')", (user_id,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _settings_out(conn, user_id: int) -> TimetableSettingsOut:
    row = conn.execute(
        "SELECT week_a_parity FROM timetable_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    parity = row["week_a_parity"] if row else "odd"
    iso_week = date.today().isocalendar()[1]
    return TimetableSettingsOut(
        week_a_parity=parity, iso_week=iso_week,
        current_week_type=_week_type_for(iso_week, parity),
    )


# ---------------------------------------------------------------- Typen (kinds)
def _get_kind(conn, user_id, kid):
    row = conn.execute(
        "SELECT * FROM timetable_kinds WHERE id = ? AND user_id = ?", (kid, user_id)
    ).fetchone()
    return TimetableKindOut(**dict(row)) if row else None


@router.get("/kinds", response_model=List[TimetableKindOut])
def list_kinds(conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _seed_defaults(conn, user_id)
    rows = conn.execute(
        "SELECT * FROM timetable_kinds WHERE user_id = ? ORDER BY sort_order, id", (user_id,)
    ).fetchall()
    return [TimetableKindOut(**dict(r)) for r in rows]


@router.post("/kinds", response_model=TimetableKindOut, status_code=201)
def create_kind(body: TimetableKindCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        "INSERT INTO timetable_kinds(user_id, name, color, sort_order) VALUES (?,?,?,?)",
        (user_id, body.name, body.color, body.sort_order),
    )
    conn.commit()
    return _get_kind(conn, user_id, cur.lastrowid)


@router.put("/kinds/{kid}", response_model=TimetableKindOut)
def update_kind(kid: int, body: TimetableKindUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get_kind(conn, user_id, kid), "Typ")
    fields = body.model_dump(exclude_unset=True)     # is_default nicht im Schema → unveränderbar
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=kid, uid=user_id)
        conn.execute(f"UPDATE timetable_kinds SET {cols} WHERE id = :id AND user_id = :uid", fields)
        conn.commit()
    return _get_kind(conn, user_id, kid)


@router.delete("/kinds/{kid}", status_code=204)
def delete_kind(kid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row = conn.execute(
        "SELECT * FROM timetable_kinds WHERE id = ? AND user_id = ?", (kid, user_id)
    ).fetchone()
    row_or_404(row, "Typ")
    if row["is_default"]:
        raise HTTPException(status_code=400, detail="Der Standard-Typ kann nicht gelöscht werden.")
    # Bestehende Einträge auf den Default-Typ umhängen (kind_id ist ON DELETE RESTRICT).
    default = conn.execute(
        "SELECT id FROM timetable_kinds WHERE user_id = ? AND is_default = 1 LIMIT 1", (user_id,)
    ).fetchone()
    if default is not None:
        conn.execute(
            "UPDATE timetable_entries SET kind_id = ?, updated_at = datetime('now') "
            "WHERE kind_id = ? AND user_id = ?",
            (default["id"], kid, user_id),
        )
    conn.execute("DELETE FROM timetable_kinds WHERE id = ? AND user_id = ?", (kid, user_id))
    conn.commit()


# ---------------------------------------------------------------- Slots
def _get_slot(conn, user_id, sid):
    row = conn.execute(
        "SELECT * FROM timetable_slots WHERE id = ? AND user_id = ?", (sid, user_id)
    ).fetchone()
    return TimetableSlotOut(**dict(row)) if row else None


@router.get("/slots", response_model=List[TimetableSlotOut])
def list_slots(conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _seed_defaults(conn, user_id)
    rows = conn.execute(
        "SELECT * FROM timetable_slots WHERE user_id = ? ORDER BY position, id", (user_id,)
    ).fetchall()
    return [TimetableSlotOut(**dict(r)) for r in rows]


@router.post("/slots", response_model=TimetableSlotOut, status_code=201)
def create_slot(body: TimetableSlotCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        "INSERT INTO timetable_slots(user_id, position, slot_type, label, start_time, end_time) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, body.position, body.slot_type, body.label, body.start_time, body.end_time),
    )
    conn.commit()
    return _get_slot(conn, user_id, cur.lastrowid)


@router.put("/slots/{sid}", response_model=TimetableSlotOut)
def update_slot(sid: int, body: TimetableSlotUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get_slot(conn, user_id, sid), "Slot")
    fields = body.model_dump(exclude_unset=True)
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=sid, uid=user_id)
        conn.execute(f"UPDATE timetable_slots SET {cols} WHERE id = :id AND user_id = :uid", fields)
        conn.commit()
    return _get_slot(conn, user_id, sid)


@router.delete("/slots/{sid}", status_code=204)
def delete_slot(sid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    # Einträge mit diesem Anker-Slot verschwinden per DB-CASCADE (slot_id).
    cur = conn.execute("DELETE FROM timetable_slots WHERE id = ? AND user_id = ?", (sid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Slot nicht gefunden.")


# ---------------------------------------------------------------- Pläne
def _get_plan(conn, user_id, pid):
    row = conn.execute(
        "SELECT * FROM timetable_plans WHERE id = ? AND user_id = ?", (pid, user_id)
    ).fetchone()
    return TimetablePlanOut(**dict(row)) if row else None


@router.get("/plans", response_model=List[TimetablePlanOut])
def list_plans(conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _seed_defaults(conn, user_id)
    rows = conn.execute(
        "SELECT * FROM timetable_plans WHERE user_id = ? ORDER BY valid_from, id", (user_id,)
    ).fetchall()
    return [TimetablePlanOut(**dict(r)) for r in rows]


@router.post("/plans", response_model=TimetablePlanOut, status_code=201)
def create_plan(body: TimetablePlanCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    if body.copy_from_plan_id is not None:           # Quellplan muss dem Nutzer gehören
        _require_owned(conn, "timetable_plans", body.copy_from_plan_id, user_id, "Quellplan")
    try:
        cur = conn.execute(
            "INSERT INTO timetable_plans(user_id, name, valid_from) VALUES (?,?,?)",
            (user_id, body.name, body.valid_from),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Für dieses Datum existiert bereits ein Plan.")
    new_id = cur.lastrowid
    if body.copy_from_plan_id is not None:           # Einträge des Quellplans duplizieren
        conn.execute(
            "INSERT INTO timetable_entries"
            "(user_id, plan_id, slot_id, kind_id, class_id, weekday, week_type, span_slots, label, room, color) "
            "SELECT user_id, ?, slot_id, kind_id, class_id, weekday, week_type, span_slots, label, room, color "
            "FROM timetable_entries WHERE plan_id = ? AND user_id = ?",
            (new_id, body.copy_from_plan_id, user_id),
        )
    conn.commit()
    return _get_plan(conn, user_id, new_id)


@router.put("/plans/{pid}", response_model=TimetablePlanOut)
def update_plan(pid: int, body: TimetablePlanUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get_plan(conn, user_id, pid), "Plan")
    fields = body.model_dump(exclude_unset=True)
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=pid, uid=user_id)
        try:
            conn.execute(f"UPDATE timetable_plans SET {cols} WHERE id = :id AND user_id = :uid", fields)
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=400, detail="Für dieses Datum existiert bereits ein Plan.")
    return _get_plan(conn, user_id, pid)


@router.delete("/plans/{pid}", status_code=204)
def delete_plan(pid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get_plan(conn, user_id, pid), "Plan")
    count = conn.execute(
        "SELECT COUNT(*) FROM timetable_plans WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    if count <= 1:
        raise HTTPException(status_code=400, detail="Der letzte Plan kann nicht gelöscht werden.")
    conn.execute("DELETE FROM timetable_plans WHERE id = ? AND user_id = ?", (pid, user_id))
    conn.commit()                                    # Einträge des Plans per DB-CASCADE


# ---------------------------------------------------------------- Einträge
def _entry_row(conn, user_id, eid):
    return conn.execute(
        "SELECT * FROM timetable_entries WHERE id = ? AND user_id = ?", (eid, user_id)
    ).fetchone()


def _get_entry(conn, user_id, eid):
    row = _entry_row(conn, user_id, eid)
    return TimetableEntryOut(**dict(row)) if row else None


@router.get("/entries", response_model=List[TimetableEntryOut])
def list_entries(
    plan_id: int = Query(alias="planId"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    _seed_defaults(conn, user_id)
    _require_owned(conn, "timetable_plans", plan_id, user_id, "Plan")
    rows = conn.execute(
        "SELECT e.* FROM timetable_entries e "
        "JOIN timetable_slots s ON s.id = e.slot_id "
        "WHERE e.plan_id = ? AND e.user_id = ? "
        "ORDER BY e.weekday, s.position, e.id",
        (plan_id, user_id),
    ).fetchall()
    return [TimetableEntryOut(**dict(r)) for r in rows]


@router.post("/entries", response_model=TimetableEntryOut, status_code=201)
def create_entry(body: TimetableEntryCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _require_owned(conn, "timetable_plans", body.plan_id, user_id, "Plan")
    _require_owned(conn, "timetable_slots", body.slot_id, user_id, "Slot")
    _require_owned(conn, "timetable_kinds", body.kind_id, user_id, "Typ")
    if body.class_id is not None:
        _require_owned(conn, "classes", body.class_id, user_id, "Klasse")
    _validate_span(conn, user_id, body.slot_id, body.span_slots)
    cur = conn.execute(
        "INSERT INTO timetable_entries"
        "(user_id, plan_id, slot_id, kind_id, class_id, weekday, week_type, span_slots, label, room, color) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, body.plan_id, body.slot_id, body.kind_id, body.class_id, body.weekday,
         body.week_type, body.span_slots, body.label, body.room, body.color),
    )
    conn.commit()
    return _get_entry(conn, user_id, cur.lastrowid)


@router.put("/entries/{eid}", response_model=TimetableEntryOut)
def update_entry(eid: int, body: TimetableEntryUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    existing = _entry_row(conn, user_id, eid)
    row_or_404(existing, "Eintrag")
    fields = body.model_dump(exclude_unset=True)
    # Geänderte Fremdschlüssel müssen dem Nutzer gehören.
    if fields.get("plan_id") is not None:
        _require_owned(conn, "timetable_plans", fields["plan_id"], user_id, "Plan")
    if fields.get("slot_id") is not None:
        _require_owned(conn, "timetable_slots", fields["slot_id"], user_id, "Slot")
    if fields.get("kind_id") is not None:
        _require_owned(conn, "timetable_kinds", fields["kind_id"], user_id, "Typ")
    if fields.get("class_id") is not None:
        _require_owned(conn, "classes", fields["class_id"], user_id, "Klasse")
    # Span mit den effektiven Werten (neu oder bestehend) erneut prüfen.
    eff_slot = fields.get("slot_id") or existing["slot_id"]
    eff_span = fields.get("span_slots") or existing["span_slots"]
    _validate_span(conn, user_id, eff_slot, eff_span)
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=eid, uid=user_id)
        conn.execute(
            f"UPDATE timetable_entries SET {cols}, updated_at = datetime('now') "
            "WHERE id = :id AND user_id = :uid",
            fields,
        )
        conn.commit()
    return _get_entry(conn, user_id, eid)


@router.delete("/entries/{eid}", status_code=204)
def delete_entry(eid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute("DELETE FROM timetable_entries WHERE id = ? AND user_id = ?", (eid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden.")


# ---------------------------------------------------------------- Settings
@router.get("/settings", response_model=TimetableSettingsOut)
def get_settings(conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _seed_defaults(conn, user_id)
    return _settings_out(conn, user_id)


@router.put("/settings", response_model=TimetableSettingsOut)
def put_settings(body: TimetableSettingsUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _seed_defaults(conn, user_id)                    # Settings-Zeile sicherstellen
    conn.execute(
        "UPDATE timetable_settings SET week_a_parity = ?, updated_at = datetime('now') "
        "WHERE user_id = ?",
        (body.week_a_parity, user_id),
    )
    conn.commit()
    return _settings_out(conn, user_id)


# ---------------------------------------------------------------- Aufgelöste Woche
@router.get("/resolved", response_model=TimetableResolved)
def resolved(
    start: str = Query(alias="start", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    _seed_defaults(conn, user_id)
    try:
        d = date.fromisoformat(start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum (YYYY-MM-DD erwartet).")
    monday = _monday_of(d)
    iso_week = monday.isocalendar()[1]

    prow = conn.execute(
        "SELECT week_a_parity FROM timetable_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    week_a_parity = prow["week_a_parity"] if prow else "odd"
    week_type = _week_type_for(iso_week, week_a_parity)

    # Plan mit MAX(valid_from) <= Montag; Fallback: ältester Plan des Nutzers.
    plan = conn.execute(
        "SELECT * FROM timetable_plans WHERE user_id = ? AND valid_from <= ? "
        "ORDER BY valid_from DESC, id DESC LIMIT 1",
        (user_id, monday.isoformat()),
    ).fetchone()
    if plan is None:
        plan = conn.execute(
            "SELECT * FROM timetable_plans WHERE user_id = ? ORDER BY valid_from, id LIMIT 1",
            (user_id,),
        ).fetchone()

    days = [
        TimetableResolvedDay(date=(monday + timedelta(days=wd)).isoformat(), weekday=wd, items=[])
        for wd in range(5)
    ]
    if plan is None:                                 # dank Seeding praktisch unerreichbar
        return TimetableResolved(
            week_start=monday.isoformat(), iso_week=iso_week, week_type=week_type,
            plan_id=0, plan_name="", days=days,
        )

    # Slots (Reihenfolge) einmalig laden – für Span/timeRange.
    ordered = conn.execute(
        "SELECT id, label, start_time, end_time FROM timetable_slots "
        "WHERE user_id = ? ORDER BY position, id",
        (user_id,),
    ).fetchall()
    slot_by_id = {s["id"]: s for s in ordered}
    idx_by_id = {s["id"]: i for i, s in enumerate(ordered)}
    kinds = {k["id"]: k for k in conn.execute(
        "SELECT id, name, color FROM timetable_kinds WHERE user_id = ?", (user_id,)
    ).fetchall()}
    classes = {c["id"]: c for c in conn.execute(
        "SELECT id, name, subject FROM classes WHERE user_id = ?", (user_id,)
    ).fetchall()}

    entries = conn.execute(
        "SELECT e.* FROM timetable_entries e "
        "JOIN timetable_slots s ON s.id = e.slot_id "
        "WHERE e.plan_id = ? AND e.user_id = ? AND e.week_type IN ('both', ?) "
        "ORDER BY e.weekday, s.position, e.id",
        (plan["id"], user_id, week_type),
    ).fetchall()

    for e in entries:
        anchor = slot_by_id.get(e["slot_id"])
        if anchor is None:                           # defensiv (Slot-CASCADE räumt sonst auf)
            continue
        end_idx = min(idx_by_id[e["slot_id"]] + e["span_slots"] - 1, len(ordered) - 1)
        time_range = f'{anchor["start_time"]}–{ordered[end_idx]["end_time"]}'

        cls = classes.get(e["class_id"]) if e["class_id"] is not None else None
        kind = kinds.get(e["kind_id"])

        # Farbe: Eintrags-Farbe → Fachfarbe (Klasse) → Typ-Farbe.
        color = e["color"]
        if not color and cls is not None:
            color = SUBJECT_COLORS.get(cls["subject"])
        if not color:
            color = kind["color"] if kind else "#94a3b8"

        # Titel: Label → "{Klasse} {Fach}" → Typ-Name.
        if e["label"]:
            title = e["label"]
        elif cls is not None:
            title = f'{cls["name"]} {cls["subject"]}'
        else:
            title = kind["name"] if kind else ""

        days[e["weekday"]].items.append(TimetableResolvedItem(
            entry_id=e["id"], slot_id=e["slot_id"], slot_label=anchor["label"],
            time_range=time_range, title=title, subtitle=e["room"] or "", color=color,
            kind_id=e["kind_id"], kind_name=(kind["name"] if kind else ""),
            class_id=e["class_id"], week_type=e["week_type"], span_slots=e["span_slots"],
            source="plan",
        ))

    return TimetableResolved(
        week_start=monday.isoformat(), iso_week=iso_week, week_type=week_type,
        plan_id=plan["id"], plan_name=plan["name"], days=days,
    )
