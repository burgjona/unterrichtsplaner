"""M1b: Soll/Ist-Abgleich zwischen Schulmanager-Feed und Dashboard.

Unterricht (regularLesson/specialLesson) wird gegen den aufgelösten U27-Stundenplan
(stundenplan.resolved() – bezieht bereits erfasste Vertretungen aus timetable_overrides
mit ein) verglichen; Aufsichten (supervision) gegen bestehende calendar_entries
(Planungskalender). Absprache mit dem Nutzer:
  - Referenzpunkt Unterricht = U27-Stundenplan, NICHT calendar_entries.
  - Referenzpunkt Aufsicht = calendar_entries, NICHT U27.
  - Ist bereits ein timetable_overrides-Eintrag für den Slot/Tag vorhanden
    (source == "override"), gilt die Abweichung als schon manuell erfasst und wird
    nicht erneut gemeldet.
  - Reines Lesen, keine Persistenz: die Review-Liste wird bei jedem Aufruf frisch
    berechnet ("Ignorieren" ist bewusst nur clientseitig für die laufende Sitzung).

Reihum wird `stundenplan.resolved(...)` direkt aufgerufen (kein neuer Netz-/DB-Layer) –
Depends(...)-Defaults sind beim direkten Python-Aufruf einfach ignorierte Default-Werte,
solange conn/user_id explizit übergeben werden.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from ..routers import stundenplan
from .schulmanager_ical import IcsEvent

_CLASS_CODE_RE = re.compile(r"\(([^()]+)\)\s*$")


def _class_code(summary: str) -> Optional[str]:
    m = _CLASS_CODE_RE.search(summary.strip())
    return m.group(1) if m else None


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _load_holiday_ranges(conn: sqlite3.Connection, user_id: int) -> List[Tuple[str, str]]:
    rows = conn.execute(
        "SELECT start_date, end_date FROM school_dates WHERE user_id = ? AND kind IN ('feiertag','ferien')",
        (user_id,),
    ).fetchall()
    return [(r["start_date"], r["end_date"]) for r in rows]


def _is_holiday(d: date, ranges: List[Tuple[str, str]]) -> bool:
    iso = d.isoformat()
    return any(start <= iso <= end for start, end in ranges)


def _load_classes(conn: sqlite3.Connection, user_id: int) -> Dict[int, dict]:
    return {c["id"]: dict(c) for c in conn.execute(
        "SELECT id, name, subject FROM classes WHERE user_id = ?", (user_id,)
    ).fetchall()}


def _resolved_weeks(conn: sqlite3.Connection, user_id: int, start: date, end: date) -> List["stundenplan.TimetableResolved"]:
    """Ein /resolved-Aufruf je Kalenderwoche zwischen start und end (inklusive)."""
    weeks = []
    monday = _monday(start)
    last_monday = _monday(end)
    while monday <= last_monday:
        weeks.append(stundenplan.resolved(start=monday.isoformat(), conn=conn, user_id=user_id))
        monday += timedelta(days=7)
    return weeks


def _index_unterricht(weeks: List["stundenplan.TimetableResolved"]) -> Dict[Tuple[str, str], "stundenplan.TimetableResolvedItem"]:
    """(Datum, Start-Zeit) -> Item, nur Einträge mit Klassenbezug (Aufsichten haben keinen)."""
    idx: Dict[Tuple[str, str], "stundenplan.TimetableResolvedItem"] = {}
    for wk in weeks:
        for day in wk.days:
            for item in day.items:
                if item.class_id is None:
                    continue
                start_time = item.time_range.split("–", 1)[0]
                idx[(day.date, start_time)] = item
    return idx


def _room_matches(feed_location: Optional[str], plan_room: Optional[str]) -> bool:
    """Grobe Übereinstimmung statt exakter Gleichheit – Schulmanager schreibt Räume anders
    ("Raum Zi. 3.21 (Zi. 33)") als das eigene Stundenplan-Feld ("3.21")."""
    if not plan_room or not feed_location:
        return True  # nichts Vergleichbares -> kein Widerspruch unterstellen
    return plan_room in feed_location or feed_location in plan_room


def _change(ev: IcsEvent, expected: Optional[dict], class_id: Optional[int] = None) -> dict:
    return {
        "date": ev["start"][:10],
        "start": ev["start"][11:16],
        "end": ev["end"][11:16] if ev.get("end") else None,
        "expected": expected,
        "actual": {"title": ev["summary"], "room": ev.get("location"), "uid": ev["uid"]},
        # Für "Ausarbeiten" im Frontend (öffnet den Unterrichtsplanung-Editor über dieselbe
        # Zuordnungslogik wie die U27-Stundenplan-Ansicht) – nur bei Unterricht gesetzt.
        "class_id": class_id,
    }


def compute_changes(conn: sqlite3.Connection, user_id: int, events: List[IcsEvent]) -> dict:
    """events = schulmanager_ical.parse_ics(...)-Ergebnis. Liefert nur Abweichungen,
    kategorisiert in vertretung / ausfall / aufsicht_neu / aufsicht_geaendert."""
    lessons = [e for e in events if e["kind"] in ("regularLesson", "specialLesson") and not e["all_day"]]
    supervisions = [e for e in events if e["kind"] == "supervision" and not e["all_day"]]

    result: dict = {"vertretung": [], "ausfall": [], "aufsicht_neu": [], "aufsicht_geaendert": []}

    if lessons:
        dates = [date.fromisoformat(e["start"][:10]) for e in lessons]
        date_min, date_max = min(dates), max(dates)
        idx = _index_unterricht(_resolved_weeks(conn, user_id, date_min, date_max))
        classes = _load_classes(conn, user_id)
        holiday_ranges = _load_holiday_ranges(conn, user_id)
        consumed: set = set()

        for ev in lessons:
            key = (ev["start"][:10], ev["start"][11:16])
            consumed.add(key)
            item = idx.get(key)

            if item is None:
                result["vertretung"].append(_change(ev, expected=None))
                continue
            if item.source == "override":
                continue  # schon manuell erfasst (U30) -> keine erneute Meldung

            expected_name = classes.get(item.class_id, {}).get("name") if item.class_id is not None else None
            feed_code = _class_code(ev["summary"])
            deviates = (
                ev["kind"] == "specialLesson"
                or bool(feed_code and expected_name and feed_code != expected_name)
                or not _room_matches(ev.get("location"), item.subtitle)
            )
            if deviates:
                result["vertretung"].append(_change(
                    ev, expected={"title": item.title, "room": item.subtitle}, class_id=item.class_id,
                ))

        for (day_str, time_str), item in idx.items():
            if item.source == "override" or (day_str, time_str) in consumed:
                continue
            d = date.fromisoformat(day_str)
            if not (date_min <= d <= date_max) or _is_holiday(d, holiday_ranges):
                continue
            result["ausfall"].append({
                "date": day_str, "start": time_str, "end": item.time_range.split("–", 1)[1],
                "expected": {"title": item.title, "room": item.subtitle}, "actual": None,
                "class_id": item.class_id,
            })

    for ev in supervisions:
        day_str, time_str = ev["start"][:10], ev["start"][11:16]
        existing = conn.execute(
            "SELECT id, room FROM calendar_entries WHERE user_id = ? AND entry_date = ? AND start_time = ?",
            (user_id, day_str, time_str),
        ).fetchone()
        if existing is None:
            result["aufsicht_neu"].append(_change(ev, expected=None))
        elif not _room_matches(ev.get("location"), existing["room"]):
            change = _change(ev, expected={"title": None, "room": existing["room"]})
            change["entry_id"] = existing["id"]
            result["aufsicht_geaendert"].append(change)

    return result
