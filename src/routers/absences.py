"""Abwesenheiten: Krank / Frei / Fortbildung / Exkursion / Kur / Dienstreise.

Ein Datensatz je zusammenhängendem Zeitraum. Der Stundenplan bleibt unverändert – eine
Abwesenheit verschiebt ausschließlich die bereits terminierten Sequenzstunden der betroffenen
Klassen nach hinten (blockübergreifend bis zum Schuljahresende) und zieht die verknüpften
lessons-Termine samt Auto-Kalendereintrag mit.

Kaskadenprinzip: Alle Sequenzstunden einer Klasse mit demselben Datum bilden eine
"Tagesgruppe". Ab der ersten Gruppe, die in den Abwesenheitszeitraum fällt, rutscht jede
Gruppe auf den jeweils nächsten realen Unterrichtstag der Klasse (Ferien, Feiertage und
Abwesenheiten übersprungen). Sobald eine Gruppe wieder auf ihrem eigenen, freien Termin
liegt, ist die Kaskade eingeholt und der Rest bleibt unangetastet.

Zurückrollen: Jede Verschiebung wird in absence_shifts protokolliert. Beim Löschen (oder beim
Ändern des Zeitraums) wird zurückgesetzt, was seither NICHT von Hand geändert wurde – der
Vergleich läuft über das protokollierte new_date/new_time gegen den Ist-Zustand.

Offline-Sync: bewusst online-only (wie /sequenz-stunden/shift) – die Verschiebung braucht den
aktuellen Serverstand (Stundenplan, Ferien, Kollisionen). Die *Folgen* (sequenz_stunden,
lessons, calendar_entries) synchronisieren über deren eigene sync_log-Trigger ganz normal.
"""
import sqlite3
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import (
    AbsenceApplyOut, AbsenceClassImpact, AbsenceCreate, AbsenceDeleteOut, AbsenceOut,
    AbsencePreviewOut, AbsenceRange, AbsenceUpdate, AbsenceWarning,
)
from .lessons import _sync_calendar_entry
from .sequenzplan import next_teaching_day

router = APIRouter(prefix="/absences", tags=["absences"])

KIND_LABELS = {
    "krank": "Krank",
    "frei": "Frei",
    "fortbildung": "Fortbildung",
    "exkursion": "Exkursion",
    "kur": "Kur",
    "dienstreise": "Dienstreise",
}
ABSENCE_CATEGORY = ("Abwesenheit", "#7c3aed")

# Suchfenster für den nächsten Unterrichtstag: großzügig, damit auch die Sommerferien
# überbrückt werden – der Schuljahresrand begrenzt ohnehin zusätzlich.
_MAX_SEARCH_DAYS = 400


def _out(row) -> AbsenceOut:
    d = dict(row)
    return AbsenceOut(
        id=d["id"], start_date=d["start_date"], end_date=d["end_date"], kind=d["kind"],
        kind_label=KIND_LABELS.get(d["kind"], d["kind"]), note=d["note"],
        shifted_count=d.get("shifted_count", 0) or 0,
        created_at=d["created_at"], updated_at=d["updated_at"],
    )


def _fetch(conn, user_id, aid):
    return conn.execute(
        "SELECT a.*, (SELECT COUNT(*) FROM absence_shifts s WHERE s.absence_id = a.id) AS shifted_count "
        "FROM absences a WHERE a.id = ? AND a.user_id = ?",
        (aid, user_id),
    ).fetchone()


def _validate_range(start_date: str, end_date: str) -> None:
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="Das Enddatum liegt vor dem Startdatum.")


def _overlapping(conn, user_id, start_date, end_date, exclude_id=None):
    sql = ("SELECT id FROM absences WHERE user_id = ? AND start_date <= ? AND end_date >= ?")
    params = [user_id, end_date, start_date]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    return conn.execute(sql, params).fetchone()


# ---------------------------------------------------------------- Kalendereintrag
def _absence_category_id(conn, user_id: int) -> int:
    """Kategorie "Abwesenheit" (einmalig je Nutzer angelegt) – bewusst eine eigene Kategorie,
    damit die Einträge im Kalender sofort als solche erkennbar und filterbar sind."""
    name, color = ABSENCE_CATEGORY
    row = conn.execute(
        "SELECT id FROM calendar_categories WHERE user_id = ? AND name = ?", (user_id, name)
    ).fetchone()
    if row:
        return row["id"]
    nxt = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM calendar_categories WHERE user_id = ?",
        (user_id,),
    ).fetchone()["n"]
    cur = conn.execute(
        "INSERT INTO calendar_categories(user_id, name, color, sort_order, updated_at) "
        "VALUES (?,?,?,?, strftime('%Y-%m-%d %H:%M:%f','now'))",
        (user_id, name, color, nxt),
    )
    return cur.lastrowid


def _sync_absence_entry(conn, user_id: int, row) -> None:
    """Hält den ganztägigen Kalendereintrag der Abwesenheit synchron (ein- oder mehrtägig,
    je nach Länge des Zeitraums)."""
    label = KIND_LABELS.get(row["kind"], row["kind"])
    title = f"{label} – {row['note'].strip()}" if (row["note"] or "").strip() else label
    end_date = row["end_date"] if row["end_date"] != row["start_date"] else None
    existing = conn.execute(
        "SELECT id FROM calendar_entries WHERE absence_id = ? AND user_id = ?",
        (row["id"], user_id),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE calendar_entries SET title = ?, entry_date = ?, end_date = ?, notes = ?, "
            "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ?",
            (title, row["start_date"], end_date, row["note"], existing["id"]),
        )
        return
    conn.execute(
        "INSERT INTO calendar_entries(user_id, title, entry_date, end_date, entry_type, "
        "is_fixed, all_day, auto_generated, category_id, notes, absence_id, updated_at) "
        "VALUES (?,?,?,?, 'normal', 1, 1, 1, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f','now'))",
        (user_id, title, row["start_date"], end_date, _absence_category_id(conn, user_id),
         row["note"], row["id"]),
    )


# ---------------------------------------------------------------- Verschiebe-Engine
def _in_range(iso: str, start: str, end: str) -> bool:
    return start <= iso <= end


def _school_days(conn, user_id: int, start: str, end: str) -> int:
    """Mo–Fr im Zeitraum abzüglich Ferien/Feiertagen – nur zur Anzeige in der Vorschau."""
    ferien = [(r["start_date"], r["end_date"]) for r in conn.execute(
        "SELECT start_date, end_date FROM school_dates WHERE user_id = ?", (user_id,)
    ).fetchall()]
    d, last, n = date.fromisoformat(start), date.fromisoformat(end), 0
    while d <= last:
        iso = d.isoformat()
        if d.weekday() < 5 and not any(s <= iso <= e for s, e in ferien):
            n += 1
        d += timedelta(days=1)
    return n


def _cards_from(conn, user_id: int, from_date: str):
    """Alle terminierten Sequenzstunden ab from_date, klassenweise und chronologisch.
    "Verschoben nach ..."-Hinweiszeilen (moved_to_id) sind reine Historie und bleiben außen vor."""
    return conn.execute(
        "SELECT s.id, s.date, s.sort_order, s.lesson_id, s.title, "
        "       s.is_lk, s.is_referat, s.is_komplexe_arbeit, s.is_klassenarbeit, "
        "       p.class_id AS class_id, c.name AS class_name, c.subject AS subject, "
        "       c.school_year_id AS school_year_id, l.time AS lesson_time "
        "FROM sequenz_stunden s "
        "JOIN stoff_plan_blocks b ON b.id = s.block_id "
        "JOIN stoff_plans p ON p.id = b.plan_id "
        "JOIN classes c ON c.id = p.class_id "
        "LEFT JOIN lessons l ON l.id = s.lesson_id "
        "WHERE s.user_id = ? AND s.date IS NOT NULL AND s.date >= ? AND s.moved_to_id IS NULL "
        "ORDER BY p.class_id, s.date, s.sort_order, s.id",
        (user_id, from_date),
    ).fetchall()


def _year_end(conn, user_id: int, school_year_id) -> Optional[str]:
    if school_year_id is None:
        return None
    row = conn.execute(
        "SELECT end_date FROM school_years WHERE id = ? AND user_id = ?", (school_year_id, user_id)
    ).fetchone()
    return row["end_date"] if row else None


def _units(cards) -> List[list]:
    """Eine Tagesgruppe in Termin-Einheiten zerlegen: Karten derselben verknüpften Stunde
    (Doppelstunde = 2 Karten an 1 lessons-Zeile) belegen zusammen genau einen Slot."""
    units, by_lesson = [], {}
    for c in cards:
        lid = c["lesson_id"]
        if lid is None:
            units.append([c])
            continue
        if lid not in by_lesson:
            by_lesson[lid] = []
            units.append(by_lesson[lid])
        by_lesson[lid].append(c)
    return units


def _plan_shifts(conn, user_id: int, start: str, end: str, exclude_absence_id=None):
    """Berechnet (ohne zu schreiben), welche Sequenzstunden wohin rutschen.

    Liefert (moves, overflow): moves = [(card_row, new_date, new_time), ...],
    overflow = [card_row, ...] (kein Platz mehr im Schuljahr)."""
    extra = [(start, end)]
    moves, overflow = [], []
    cards = _cards_from(conn, user_id, start)

    by_class = {}
    for c in cards:
        by_class.setdefault(c["class_id"], []).append(c)

    for class_id, class_cards in by_class.items():
        # Tagesgruppen bilden (Reihenfolge kommt schon sortiert aus der Query).
        groups, current = [], []
        for c in class_cards:
            if current and c["date"] != current[0]["date"]:
                groups.append(current)
                current = []
            current.append(c)
        if current:
            groups.append(current)

        year_end = _year_end(conn, user_id, class_cards[0]["school_year_id"])
        cursor = None
        started = False
        for g in groups:
            old = g[0]["date"]
            blocked = _in_range(old, start, end)
            if not started and not blocked:
                cursor = old
                continue                       # vor der Abwesenheit – unberührt
            started = True
            if not blocked and (cursor is None or old > cursor):
                cursor = old                   # Kaskade eingeholt – Rest bleibt stehen
                continue
            after = cursor if cursor is not None else (
                (date.fromisoformat(old) - timedelta(days=1)).isoformat()
            )
            day = next_teaching_day(conn, user_id, class_id, after,
                                    max_days=_MAX_SEARCH_DAYS, extra_blocked=extra)
            if day is None or (year_end and day["date"] > year_end):
                overflow.extend(g)
                continue                       # cursor bleibt – Folgegruppen laufen ins Gleiche
            slots = day["slots"]
            for i, unit in enumerate(_units(g)):
                slot = slots[i] if i < len(slots) else slots[-1]
                for card in unit:
                    moves.append((card, day["date"], slot["time"]))
            cursor = day["date"]

    return moves, overflow


def _impact(conn, user_id: int, start: str, end: str, moves, overflow) -> AbsencePreviewOut:
    per_class = {}
    for card, new_date, _t in moves:
        e = per_class.setdefault(card["class_id"], {
            "class_id": card["class_id"], "class_name": card["class_name"],
            "subject": card["subject"], "shifted": 0, "dates": [], "new_dates": [], "overflow": 0,
        })
        e["shifted"] += 1
        e["dates"].append(card["date"])
        e["new_dates"].append(new_date)
    for card in overflow:
        e = per_class.setdefault(card["class_id"], {
            "class_id": card["class_id"], "class_name": card["class_name"],
            "subject": card["subject"], "shifted": 0, "dates": [], "new_dates": [], "overflow": 0,
        })
        e["overflow"] += 1
        e["dates"].append(card["date"])

    classes = [AbsenceClassImpact(
        class_id=e["class_id"], class_name=e["class_name"], subject=e["subject"],
        shifted=e["shifted"], first_date=min(e["dates"]), last_old_date=max(e["dates"]),
        last_new_date=max(e["new_dates"]) if e["new_dates"] else None, overflow=e["overflow"],
    ) for e in sorted(per_class.values(), key=lambda x: x["class_name"])]

    def _art(card):
        if card["is_klassenarbeit"]:
            return "Klassenarbeit"
        if card["is_komplexe_arbeit"]:
            return "Komplexe Leistung"
        if card["is_lk"]:
            return "Leistungskontrolle"
        if card["is_referat"]:
            return "Referat"
        return ""

    warnings = []
    seen = set()
    for card, new_date, _t in moves:
        art = _art(card)
        if art and card["id"] not in seen:
            seen.add(card["id"])
            warnings.append(AbsenceWarning(class_name=card["class_name"], title=card["title"],
                                           art=art, old_date=card["date"], new_date=new_date))
    for card in overflow:
        art = _art(card)
        if art and card["id"] not in seen:
            seen.add(card["id"])
            warnings.append(AbsenceWarning(class_name=card["class_name"], title=card["title"],
                                           art=art, old_date=card["date"], new_date=None))

    return AbsencePreviewOut(
        start_date=start, end_date=end, school_days=_school_days(conn, user_id, start, end),
        shifted=len(moves), overflow=len(overflow), classes=classes, warnings=warnings,
    )


def _apply(conn, user_id: int, absence_id: int, start: str, end: str) -> AbsencePreviewOut:
    """Verschiebung berechnen, schreiben und protokollieren. Erwartet, dass die Abwesenheit
    bereits in der DB steht (next_teaching_day liest sie als Sperrzeitraum mit)."""
    moves, overflow = _plan_shifts(conn, user_id, start, end)
    seen_lessons = set()
    for card, new_date, new_time in moves:
        conn.execute(
            "UPDATE sequenz_stunden SET date = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
            "WHERE id = ? AND user_id = ?",
            (new_date, card["id"], user_id),
        )
        lesson_id = card["lesson_id"]
        old_time = card["lesson_time"]
        if lesson_id is not None and lesson_id not in seen_lessons:
            seen_lessons.add(lesson_id)
            conn.execute(
                "UPDATE lessons SET date = ?, time = ?, "
                "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ? AND user_id = ?",
                (new_date, new_time, lesson_id, user_id),
            )
            _sync_calendar_entry(conn, user_id, lesson_id)
        conn.execute(
            "INSERT INTO absence_shifts(absence_id, user_id, sequenz_stunde_id, lesson_id, "
            "old_date, old_time, new_date, new_time) VALUES (?,?,?,?,?,?,?,?)",
            (absence_id, user_id, card["id"], lesson_id, card["date"], old_time,
             new_date, new_time),
        )
    return _impact(conn, user_id, start, end, moves, overflow)


def _rollback(conn, user_id: int, absence_id: int) -> AbsenceDeleteOut:
    """Setzt die protokollierten Verschiebungen zurück – aber nur dort, wo seither nichts von
    Hand geändert wurde (Ist-Datum == protokolliertes new_date). Alles andere bleibt stehen."""
    rows = conn.execute(
        "SELECT * FROM absence_shifts WHERE absence_id = ? AND user_id = ? ORDER BY id DESC",
        (absence_id, user_id),
    ).fetchall()
    restored, kept, lessons_done = 0, 0, set()
    for r in rows:
        card = conn.execute(
            "SELECT date FROM sequenz_stunden WHERE id = ? AND user_id = ?",
            (r["sequenz_stunde_id"], user_id),
        ).fetchone()
        if card is None:
            continue                            # Karte gelöscht – nichts zurückzusetzen
        if card["date"] != r["new_date"]:
            kept += 1
            continue
        conn.execute(
            "UPDATE sequenz_stunden SET date = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
            "WHERE id = ? AND user_id = ?",
            (r["old_date"], r["sequenz_stunde_id"], user_id),
        )
        restored += 1
        lid = r["lesson_id"]
        if lid is None or lid in lessons_done:
            continue
        lessons_done.add(lid)
        lesson = conn.execute(
            "SELECT date, time FROM lessons WHERE id = ? AND user_id = ?", (lid, user_id)
        ).fetchone()
        if lesson is None or lesson["date"] != r["new_date"]:
            continue                            # Stunde inzwischen anders terminiert
        conn.execute(
            "UPDATE lessons SET date = ?, time = ?, "
            "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ? AND user_id = ?",
            (r["old_date"], r["old_time"], lid, user_id),
        )
        _sync_calendar_entry(conn, user_id, lid)
    conn.execute("DELETE FROM absence_shifts WHERE absence_id = ? AND user_id = ?",
                 (absence_id, user_id))
    return AbsenceDeleteOut(restored=restored, kept=kept)


# ---------------------------------------------------------------- Endpunkte
@router.get("", response_model=List[AbsenceOut])
def list_(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None, alias="to"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    sql = ("SELECT a.*, (SELECT COUNT(*) FROM absence_shifts s WHERE s.absence_id = a.id) "
           "AS shifted_count FROM absences a WHERE a.user_id = ?")
    params = [user_id]
    if to:
        sql += " AND a.start_date <= ?"
        params.append(to)
    if from_:
        sql += " AND a.end_date >= ?"
        params.append(from_)
    sql += " ORDER BY a.start_date DESC, a.id DESC"
    return [_out(r) for r in conn.execute(sql, params).fetchall()]


@router.post("/preview", response_model=AbsencePreviewOut)
def preview(body: AbsenceRange, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    """Was würde passieren? Reine Berechnung, schreibt nichts – Grundlage für die Bestätigung."""
    _validate_range(body.start_date, body.end_date)
    moves, overflow = _plan_shifts(conn, user_id, body.start_date, body.end_date)
    return _impact(conn, user_id, body.start_date, body.end_date, moves, overflow)


@router.post("", response_model=AbsenceApplyOut, status_code=201)
def create(body: AbsenceCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _validate_range(body.start_date, body.end_date)
    if _overlapping(conn, user_id, body.start_date, body.end_date):
        raise HTTPException(status_code=400,
                            detail="In diesem Zeitraum ist bereits eine Abwesenheit eingetragen.")
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO absences(user_id, start_date, end_date, kind, note, updated_at) "
                "VALUES (?,?,?,?,?, strftime('%Y-%m-%d %H:%M:%f','now'))",
                (user_id, body.start_date, body.end_date, body.kind, body.note),
            )
            aid = cur.lastrowid
            result = _apply(conn, user_id, aid, body.start_date, body.end_date)
            _sync_absence_entry(conn, user_id, _fetch(conn, user_id, aid))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige Abwesenheit: {exc}")
    return AbsenceApplyOut(absence=_out(_fetch(conn, user_id, aid)), result=result)


@router.put("/{aid}", response_model=AbsenceApplyOut)
def update(aid: int, body: AbsenceUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    """Ändert Art/Notiz und – falls der Zeitraum wechselt (z. B. verschobene Exkursion) –
    auch die Daten: dann wird erst komplett zurückgerollt und anschließend neu verschoben."""
    row = row_or_404(_fetch(conn, user_id, aid), "Abwesenheit")
    data = body.model_dump(exclude_unset=True)
    start = data.get("start_date", row["start_date"])
    end = data.get("end_date", row["end_date"])
    _validate_range(start, end)
    dates_changed = start != row["start_date"] or end != row["end_date"]
    if dates_changed and _overlapping(conn, user_id, start, end, exclude_id=aid):
        raise HTTPException(status_code=400,
                            detail="In diesem Zeitraum ist bereits eine Abwesenheit eingetragen.")
    with conn:
        if dates_changed:
            _rollback(conn, user_id, aid)
        conn.execute(
            "UPDATE absences SET start_date = ?, end_date = ?, kind = ?, note = ?, "
            "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ? AND user_id = ?",
            (start, end, data.get("kind", row["kind"]), data.get("note", row["note"]),
             aid, user_id),
        )
        if dates_changed:
            result = _apply(conn, user_id, aid, start, end)
        else:
            moves, overflow = [], []
            result = _impact(conn, user_id, start, end, moves, overflow)
        _sync_absence_entry(conn, user_id, _fetch(conn, user_id, aid))
    return AbsenceApplyOut(absence=_out(_fetch(conn, user_id, aid)), result=result)


@router.delete("/{aid}", response_model=AbsenceDeleteOut)
def delete(aid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    """Löschen rollt die Verschiebung automatisch zurück (soweit seither nichts von Hand
    geändert wurde); der Kalendereintrag verschwindet per ON DELETE CASCADE mit."""
    row_or_404(_fetch(conn, user_id, aid), "Abwesenheit")
    with conn:
        result = _rollback(conn, user_id, aid)
        conn.execute("DELETE FROM absences WHERE id = ? AND user_id = ?", (aid, user_id))
    return result
