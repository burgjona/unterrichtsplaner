"""Sequenzplan: Einzelstunden-Ebene je Stoffplan-Block (eigenständiges Objekt, optionale
Verknüpfung zu einer lessons-Zeile über sequenz_stunden.lesson_id -- 1:1 im Regelfall, 2:1 bei
einer aus 2 Sequenzstunden gebildeten Doppelstunde). Nutzer-Scoping läuft über den referenzierten
Block -> Stoffplan (stoff_plan_blocks.plan_id -> stoff_plans.user_id).
"""
import sqlite3
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import (
    SequenzStundeCalendarEntryIn, SequenzStundeCreate, SequenzStundeLinkIn, SequenzStundeOut,
    SequenzStundeReorderIn, SequenzStundeShiftIn, SequenzStundeShiftOut, SequenzStundeUpdate,
)
from .lessons import _sync_calendar_entry

router = APIRouter(prefix="/sequenz-stunden", tags=["sequenzplan"])


def _load_block(conn, user_id, block_id):
    """Block + zugehöriger Stoffplan, nutzergescoped über den Plan (analog stoffplan.py)."""
    row = conn.execute(
        "SELECT b.*, p.class_id AS plan_class_id, p.user_id AS plan_user_id "
        "FROM stoff_plan_blocks b JOIN stoff_plans p ON p.id = b.plan_id "
        "WHERE b.id = ? AND p.user_id = ?",
        (block_id, user_id),
    ).fetchone()
    return row_or_404(row, "Block")


def _fetch(conn, user_id, sid):
    return conn.execute(
        "SELECT s.* FROM sequenz_stunden s WHERE s.id = ? AND s.user_id = ?", (sid, user_id)
    ).fetchone()


def _out(row) -> SequenzStundeOut:
    d = dict(row)
    return SequenzStundeOut(
        id=d["id"], block_id=d["block_id"], sort_order=d["sort_order"], title=d["title"],
        grobziel=d["grobziel"], notes=d["notes"],
        is_lk=bool(d["is_lk"]), is_referat=bool(d["is_referat"]),
        is_komplexe_arbeit=bool(d["is_komplexe_arbeit"]), is_klassenarbeit=bool(d["is_klassenarbeit"]),
        weitere_notenart=d["weitere_notenart"], date=d["date"], lesson_id=d["lesson_id"],
        created_at=d["created_at"], updated_at=d["updated_at"],
    )


@router.get("", response_model=List[SequenzStundeOut])
def list_(block_id: int = Query(alias="blockId"), conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _load_block(conn, user_id, block_id)
    rows = conn.execute(
        "SELECT * FROM sequenz_stunden WHERE block_id = ? AND user_id = ? ORDER BY sort_order, id",
        (block_id, user_id),
    ).fetchall()
    return [_out(r) for r in rows]


@router.get("/suggest-date")
def suggest_date(block_id: int = Query(alias="blockId"), after: Optional[str] = Query(default=None),
                  conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    """Vorschlag für das voraussichtliche Datum einer neuen Sequenzstunde: nächster freier
    Unterrichtstermin der Klasse nach der zuletzt terminierten Stunde im Block – ohne bereits
    terminierte Stunde wird ab dem Blockstart aus dem Stoffverteilungsplan gesucht. Über `after`
    kann der Aufrufer den Ausgangspunkt selbst vorgeben (z.B. beim client-seitigen Vorbelegen
    mehrerer neuer, noch ungespeicherter Karten in Folge – etwa nach einem KI-Vorschlag)."""
    block = _load_block(conn, user_id, block_id)
    if after:
        after_date = after
    else:
        last = conn.execute(
            "SELECT date FROM sequenz_stunden WHERE block_id = ? AND user_id = ? AND date IS NOT NULL "
            "ORDER BY date DESC LIMIT 1",
            (block_id, user_id),
        ).fetchone()
        if last:
            after_date = last["date"]
        elif block["start_date"]:
            after_date = (date.fromisoformat(block["start_date"]) - timedelta(days=1)).isoformat()
        else:
            return {"date": None}
    slot = _next_class_slot(conn, user_id, block["plan_class_id"], after_date)
    return {"date": slot["date"] if slot else None, "spanSlots": slot["span_slots"] if slot else None}


def _apply_create_sequenz(conn, user_id, body: SequenzStundeCreate) -> SequenzStundeOut:
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Titel darf nicht leer sein.")
    _load_block(conn, user_id, body.block_id)
    if body.sort_order is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM sequenz_stunden WHERE block_id = ?",
            (body.block_id,),
        ).fetchone()
        sort_order = row["n"]
    else:
        sort_order = body.sort_order
    cur = conn.execute(
        "INSERT INTO sequenz_stunden "
        "(user_id, block_id, sort_order, title, grobziel, notes, is_lk, is_referat, "
        " is_komplexe_arbeit, is_klassenarbeit, weitere_notenart, date, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?, strftime('%Y-%m-%d %H:%M:%f','now'))",
        (user_id, body.block_id, sort_order, body.title.strip(), body.grobziel, body.notes,
         int(body.is_lk), int(body.is_referat), int(body.is_komplexe_arbeit),
         int(body.is_klassenarbeit), body.weitere_notenart, body.date),
    )
    return _out(_fetch(conn, user_id, cur.lastrowid))


@router.post("", response_model=SequenzStundeOut, status_code=201)
def create(body: SequenzStundeCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    result = _apply_create_sequenz(conn, user_id, body)
    conn.commit()
    return result


def _apply_update_sequenz(conn, user_id, sid: int, body: SequenzStundeUpdate) -> SequenzStundeOut:
    row_or_404(_fetch(conn, user_id, sid), "Sequenzstunde")
    data = body.model_dump(exclude_unset=True)
    sets = {}
    for key in ("title", "grobziel", "notes", "weitere_notenart", "date"):
        if key in data:
            sets[key] = data[key]
    for key in ("is_lk", "is_referat", "is_komplexe_arbeit", "is_klassenarbeit"):
        if key in data:
            sets[key] = int(data[key])
    if "title" in sets and not (sets["title"] or "").strip():
        raise HTTPException(status_code=400, detail="Titel darf nicht leer sein.")
    if sets:
        cols = ", ".join(f"{k} = :{k}" for k in sets)
        sets.update(id=sid, uid=user_id)
        conn.execute(
            f"UPDATE sequenz_stunden SET {cols}, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
            "WHERE id = :id AND user_id = :uid",
            sets,
        )
    return _out(_fetch(conn, user_id, sid))


@router.put("/{sid}", response_model=SequenzStundeOut)
def update(sid: int, body: SequenzStundeUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    result = _apply_update_sequenz(conn, user_id, sid, body)
    conn.commit()
    return result


def _apply_delete_sequenz(conn, user_id, sid: int) -> None:
    cur = conn.execute("DELETE FROM sequenz_stunden WHERE id = ? AND user_id = ?", (sid, user_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Sequenzstunde nicht gefunden.")


@router.delete("/{sid}", status_code=204)
def delete(sid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _apply_delete_sequenz(conn, user_id, sid)
    conn.commit()


# ---------- Sync-Handler-Registry: sequenz_stunden (src/routers/sync.py) ----------
# Nur Kern-CRUD ist sync-fähig. reorder/link/apply-calendar-entry/shift bleiben Online-REST:
# reorder verlangt zwingend das vollständige Set aller Block-ids (fragil bei einer Queue aus
# unabhängigen Einzel-Mutationen), shift berechnet live den nächsten freien Stundenplan-Slot
# und verschiebt kaskadierend verknüpfte lessons-Termine — beides braucht ohnehin den
# aktuellen Serverstand, kein sinnvoller Offline-Anwendungsfall (analog "Kumulierte Ansicht"
# in stoffplan.js, die schon vor dieser Einheit bewusst online-only blieb).

def _sync_fetch_sequenz(conn, user_id, entity_id):
    row = _fetch(conn, user_id, entity_id)
    return _out(row) if row is not None else None


def _sync_create_sequenz(conn, user_id, payload: dict) -> SequenzStundeOut:
    return _apply_create_sequenz(conn, user_id, SequenzStundeCreate(**payload))


def _sync_update_sequenz(conn, user_id, entity_id, payload: dict) -> SequenzStundeOut:
    return _apply_update_sequenz(conn, user_id, entity_id, SequenzStundeUpdate(**payload))


def _sync_delete_sequenz(conn, user_id, entity_id) -> None:
    _apply_delete_sequenz(conn, user_id, entity_id)


SYNC_HANDLER = {
    "fetch": _sync_fetch_sequenz,
    "create": _sync_create_sequenz,
    "update": _sync_update_sequenz,
    "delete": _sync_delete_sequenz,
}


@router.post("/reorder", response_model=List[SequenzStundeOut])
def reorder(body: SequenzStundeReorderIn, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _load_block(conn, user_id, body.block_id)
    existing = {r["id"] for r in conn.execute(
        "SELECT id FROM sequenz_stunden WHERE block_id = ? AND user_id = ?", (body.block_id, user_id)
    ).fetchall()}
    if set(body.ordered_ids) != existing:
        raise HTTPException(status_code=400, detail="ordered_ids muss genau alle Stunden des Blocks enthalten.")
    with conn:
        for i, sid in enumerate(body.ordered_ids):
            # updated_at NUR bei tatsächlicher sort_order-Änderung bumpen — sonst würde jeder
            # Aufruf (auch ohne echte Umsortierung, z. B. direkt nach dem Speichern einer
            # einzelnen Karte) den Offline-Sync-Client mit einem stillen, unsichtbaren Update
            # aus dem Tritt bringen (dessen lokal gecachtes updatedAt würde beim nächsten
            # Bearbeiten dieser Karte einen falschen Konflikt auslösen).
            conn.execute(
                "UPDATE sequenz_stunden SET sort_order = ?, "
                "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
                "WHERE id = ? AND user_id = ? AND sort_order != ?",
                (i, sid, user_id, i),
            )
    rows = conn.execute(
        "SELECT * FROM sequenz_stunden WHERE block_id = ? AND user_id = ? ORDER BY sort_order, id",
        (body.block_id, user_id),
    ).fetchall()
    return [_out(r) for r in rows]


@router.post("/{sid}/link", response_model=SequenzStundeOut)
def link(sid: int, body: SequenzStundeLinkIn, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_fetch(conn, user_id, sid), "Sequenzstunde")
    if body.lesson_id is not None:
        row_or_404(conn.execute(
            "SELECT id FROM lessons WHERE id = ? AND user_id = ?", (body.lesson_id, user_id)
        ).fetchone(), "Stunde")
        # Bis zu 2 Sequenzstunden je Lesson (Doppelstunde: 2 Einzelstunden -> 1 Lesson à 90 Min.).
        linked_count = conn.execute(
            "SELECT COUNT(*) AS n FROM sequenz_stunden WHERE lesson_id = ? AND user_id = ? AND id != ?",
            (body.lesson_id, user_id, sid),
        ).fetchone()["n"]
        if linked_count >= 2:
            raise HTTPException(status_code=400, detail="Diese Stunde ist bereits mit 2 Sequenzstunden verknüpft.")
    with conn:
        conn.execute(
            "UPDATE sequenz_stunden SET lesson_id = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ? AND user_id = ?",
            (body.lesson_id, sid, user_id),
        )
    return _out(_fetch(conn, user_id, sid))


@router.post("/{sid}/apply-calendar-entry", response_model=SequenzStundeOut)
def apply_calendar_entry(sid: int, body: SequenzStundeCalendarEntryIn, conn=Depends(get_db),
                         user_id: int = Depends(get_user_id)):
    """Setzt den Typ (Klassenarbeit/komplexe Arbeit -> 'exam', LK/Referat -> 'lu') des bereits
    automatisch erzeugten Kalendereintrags einer verknüpften, terminierten Stunde. Legt keinen
    neuen Eintrag an (der existiert schon dank lessons._sync_calendar_entry, sobald ein Datum
    gesetzt ist) – nur dessen entry_type wird von 'normal' auf die gewünschte Notenart geändert."""
    row = row_or_404(_fetch(conn, user_id, sid), "Sequenzstunde")
    if row["lesson_id"] is None:
        raise HTTPException(status_code=400, detail="Diese Sequenzstunde ist noch mit keiner Unterrichtsstunde verknüpft.")
    lesson = conn.execute(
        "SELECT date FROM lessons WHERE id = ? AND user_id = ?", (row["lesson_id"], user_id)
    ).fetchone()
    if lesson is None or not lesson["date"]:
        raise HTTPException(status_code=400, detail="Die verknüpfte Stunde hat noch kein Datum.")
    with conn:
        cur = conn.execute(
            "UPDATE calendar_entries SET entry_type = ?, "
            "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE lesson_id = ? AND auto_generated = 1",
            (body.type, row["lesson_id"]),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Kein automatischer Kalendereintrag für diese Stunde gefunden.")
    return _out(_fetch(conn, user_id, sid))


def _budget_for_block(conn, user_id, block_row) -> int:
    """Richtwert-Stunden für den Block: explizit gesetzter block.ustd hat Vorrang, sonst
    lernbereiche.richtwert_ustd über lb_code + Klassen-subject/grade/track (resolve_track)."""
    if block_row["ustd"]:
        return block_row["ustd"]
    if not block_row["lb_code"]:
        return None
    cls = conn.execute(
        "SELECT subject, grade, track FROM classes WHERE id = ? AND user_id = ?",
        (block_row["plan_class_id"], user_id),
    ).fetchone()
    if not cls:
        return None
    from ..lib.planning import resolve_track
    track = resolve_track(cls["subject"], cls["grade"], cls["track"])
    lb = conn.execute(
        "SELECT richtwert_ustd FROM lernbereiche WHERE subject=? AND grade=? AND track=? AND code=?",
        (cls["subject"], cls["grade"], track, block_row["lb_code"]),
    ).fetchone()
    return lb["richtwert_ustd"] if lb else None


def _week_type_for(iso_week: int, week_a_parity: str) -> str:
    """A, wenn die Parität der KW der eingestellten A-Wochen-Parität entspricht, sonst B.
    Dupliziert bewusst die (sehr kurze) Logik aus routers/stundenplan.py::_week_type_for –
    ein Router-übergreifender Import wäre hier die unschönere Abhängigkeitsrichtung."""
    parity = "odd" if iso_week % 2 == 1 else "even"
    return "A" if parity == week_a_parity else "B"


def _next_class_slot(conn, user_id: int, class_id: int, after_date_iso: str, max_days: int = 90):
    """Nächster laut Stundenplan realer Unterrichtstermin dieser Klasse nach after_date_iso
    (Ferien übersprungen, A/B-Wochen berücksichtigt). Ignoriert Tropentage/Vertretungen
    (Einzeltermin-Sonderfälle) – best effort für die optionale Kalenderverschiebung.
    Liefert {"date": iso, "time": "HH:MM", "span_slots": int} oder None, falls nichts gefunden
    wurde. span_slots > 1 markiert eine laut Stundenplan echte Doppelstunde an diesem Tag –
    Aufrufer, die Sequenzstunden-Karten terminieren, sollen dafür zwei Karten auf dasselbe
    Datum legen statt nur eine einzelne."""
    try:
        start = date.fromisoformat(after_date_iso[:10])
    except (ValueError, TypeError):
        return None
    ferien = [(r["start_date"], r["end_date"]) for r in conn.execute(
        "SELECT start_date, end_date FROM school_dates WHERE user_id = ?", (user_id,)
    ).fetchall()]
    prow = conn.execute(
        "SELECT week_a_parity FROM timetable_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    week_a_parity = prow["week_a_parity"] if prow else "odd"

    day = start + timedelta(days=1)
    for _ in range(max_days):
        if day.weekday() < 5:
            in_ferien = any(s <= day.isoformat() <= e for s, e in ferien)
            if not in_ferien:
                monday = day - timedelta(days=day.weekday())
                iso_week = monday.isocalendar()[1]
                week_type = _week_type_for(iso_week, week_a_parity)
                plan = conn.execute(
                    "SELECT id FROM timetable_plans WHERE user_id = ? AND valid_from <= ? "
                    "ORDER BY valid_from DESC, id DESC LIMIT 1",
                    (user_id, monday.isoformat()),
                ).fetchone()
                if plan:
                    entry = conn.execute(
                        "SELECT s.start_time, e.span_slots FROM timetable_entries e "
                        "JOIN timetable_slots s ON s.id = e.slot_id "
                        "WHERE e.plan_id = ? AND e.user_id = ? AND e.class_id = ? AND e.weekday = ? "
                        "AND e.week_type IN ('both', ?) ORDER BY s.position, e.id LIMIT 1",
                        (plan["id"], user_id, class_id, day.weekday(), week_type),
                    ).fetchone()
                    if entry:
                        return {"date": day.isoformat(), "time": entry["start_time"],
                                "span_slots": entry["span_slots"]}
        day += timedelta(days=1)
    return None


@router.post("/{sid}/shift", response_model=SequenzStundeShiftOut)
def shift(sid: int, body: SequenzStundeShiftIn, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    """"Nach hinten verschieben": erhöht sort_order dieser und aller nachfolgenden Stunden im
    Block um 1 (öffnet eine Lücke am Anfang der Verschiebung) – immer. Wenn with_calendar
    gesetzt ist, werden zusätzlich alle verknüpften, noch nicht vergangenen lessons-Termine
    dieser und der nachfolgenden Stunden auf den jeweils nächsten realen Unterrichtstermin
    der Klasse verschoben."""
    row = row_or_404(_fetch(conn, user_id, sid), "Sequenzstunde")
    block_id = row["block_id"]
    today = date.today().isoformat()
    with conn:
        shifted = conn.execute(
            "SELECT id, lesson_id FROM sequenz_stunden "
            "WHERE block_id = ? AND user_id = ? AND sort_order >= ? ORDER BY sort_order",
            (block_id, user_id, row["sort_order"]),
        ).fetchall()
        conn.execute(
            "UPDATE sequenz_stunden SET sort_order = sort_order + 1, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
            "WHERE block_id = ? AND user_id = ? AND sort_order >= ?",
            (block_id, user_id, row["sort_order"]),
        )
        if body.with_calendar:
            for s in shifted:
                if s["lesson_id"] is None:
                    continue
                lesson = conn.execute(
                    "SELECT id, class_id, date FROM lessons WHERE id = ? AND user_id = ?",
                    (s["lesson_id"], user_id),
                ).fetchone()
                if lesson is None or not lesson["date"] or lesson["date"] < today or lesson["class_id"] is None:
                    continue
                nxt = _next_class_slot(conn, user_id, lesson["class_id"], lesson["date"])
                if nxt is None:
                    continue
                conn.execute(
                    "UPDATE lessons SET date = ?, time = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ?",
                    (nxt["date"], nxt["time"], lesson["id"]),
                )
                _sync_calendar_entry(conn, user_id, lesson["id"])
    planned_count = conn.execute(
        "SELECT COUNT(*) AS n FROM sequenz_stunden WHERE block_id = ? AND user_id = ?",
        (block_id, user_id),
    ).fetchone()["n"]
    block_row = _load_block(conn, user_id, block_id)
    richtwert = _budget_for_block(conn, user_id, block_row)
    over_budget = richtwert is not None and planned_count > richtwert
    return SequenzStundeShiftOut(over_budget=over_budget, planned_count=planned_count, richtwert_ustd=richtwert)
