"""Hintergrund-Benachrichtigungen (Web Push, M2).

Ein Minuten-Takt im App-Prozess (Thread, gestartet in main.py) erledigt zwei Dinge:

1. Erinnerungen 5 Minuten vor allem mit Uhrzeit (Absprache mit dem Nutzer): jeder
   Eintrag des aufgelösten U27-Stundenplans (inkl. erfasster Vertretungen und
   Tropentage, jeder Typ – auch Dienstberatung) und jeder Kalendertermin mit Uhrzeit.
   Der Stundenplan gilt pauschal und schweigt daher an Wochenenden und Ferien-/Feier-
   tagen; Kalendertermine sind bewusst datiert und erinnern immer. An Abwesenheits-
   tagen: gar nichts. Aufsichten (U27-Typ bzw. Titel enthält "Aufsicht") bekommen
   einen eigenen Nachrichtentext.
2. Schulmanager-Abgleich alle 15 Minuten (Mo–Fr, 6–18 Uhr): Vertretung, Ausfall,
   neue und geänderte Aufsicht – jede Änderung genau einmal, nur künftige.

Doppelversand verhindert push_sent (Schlüssel wird VOR dem Versand eingetragen).
Der Container startet genau einen uvicorn-Prozess, daher läuft auch nur ein Takt.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from ..db import connect
from ..routers import stundenplan
from . import push, schulmanager_diff, schulmanager_ical

log = logging.getLogger(__name__)

# Der Container läuft in UTC – Stundenzeiten sind Ortszeit.
TZ = ZoneInfo("Europe/Berlin")
LEAD = timedelta(minutes=5)
POLL_EVERY_MIN = 15
POLL_HOURS = (6, 18)            # [von, bis) Ortszeit, Mo–Fr
BULK_LIMIT = 3                  # mehr neue Änderungen auf einmal -> eine Sammelnachricht
KEEP_SENT_DAYS = 60
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
CATEGORY_LABELS = {
    "vertretung": "Vertretung",
    "ausfall": "Ausfall",
    "aufsicht_neu": "Neue Aufsicht",
    "aufsicht_geaendert": "Aufsicht geändert",
}


def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def _claim(conn: sqlite3.Connection, user_id: int, key: str) -> bool:
    """True, wenn der Schlüssel neu ist (-> jetzt senden); False = schon gemeldet."""
    cur = conn.execute("INSERT OR IGNORE INTO push_sent (user_id, key) VALUES (?, ?)", (user_id, key))
    conn.commit()
    return cur.rowcount == 1


def _users_with_devices(conn: sqlite3.Connection) -> List[int]:
    return [r["user_id"] for r in conn.execute("SELECT DISTINCT user_id FROM push_subscriptions")]


def _join(*parts: Optional[str]) -> str:
    return " · ".join(p for p in parts if p)


def _fmt_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{WOCHENTAGE[d.weekday()]} {d.strftime('%d.%m.%Y')}"


def _room(room: Optional[str]) -> Optional[str]:
    if not room:
        return None
    return room if room.lower().startswith("raum") else f"Raum {room}"


def _is_supervision(name: Optional[str]) -> bool:
    return "aufsicht" in (name or "").lower()


# ---------------------------------------------------------------- Erinnerungen
def due_reminders(conn: sqlite3.Connection, user_id: int, now: datetime) -> List[dict]:
    """Alles mit Uhrzeit, das in (now, now + 5 Min.] beginnt. Das Fenster statt eines
    exakten Zeitpunkts überbrückt verpasste Takte (Neustart, langsamer Abruf)."""
    today = now.date()
    iso = today.isoformat()
    absent = conn.execute(
        "SELECT 1 FROM absences WHERE user_id = ? AND start_date <= ? AND end_date >= ? LIMIT 1",
        (user_id, iso, iso),
    ).fetchone()
    if absent is not None:
        return []

    # (Art, Beginn, Zeitspanne, Titel, Ort, Slot-Label) – Stundenplan zuerst: bei gleichem
    # Beginn gewinnt sein Eintrag (der Kalender führt geplante Stunden oft zusätzlich).
    candidates = []
    school_day = today.weekday() <= 4 and not schulmanager_diff._is_holiday(
        today, schulmanager_diff._load_holiday_ranges(conn, user_id))
    if school_day:
        week = stundenplan.resolved(start=iso, conn=conn, user_id=user_id)
        for it in week.days[today.weekday()].items:
            start = it.time_range.split("–", 1)[0]
            kind = "aufsicht" if _is_supervision(it.kind_name) else "termin"
            room = _room(it.subtitle) if it.class_id is not None else it.subtitle
            candidates.append((kind, start, it.time_range, it.title, room, it.slot_label))
    for r in conn.execute(
        "SELECT title, start_time, end_time, room FROM calendar_entries "
        "WHERE user_id = ? AND entry_date = ? AND all_day = 0 AND start_time IS NOT NULL "
        "AND archived_at IS NULL AND absence_id IS NULL",
        (user_id, iso),
    ).fetchall():
        span = r["start_time"] + (f"–{r['end_time']}" if r["end_time"] else "")
        kind = "aufsicht" if _is_supervision(r["title"]) else "termin"
        candidates.append((kind, r["start_time"], span, r["title"], r["room"], None))

    out, seen = [], set()
    for kind, start, span, title, room, slot_label in candidates:
        try:
            begins = datetime.combine(today, datetime.strptime(start, "%H:%M").time())
        except ValueError:
            continue
        delta = begins - now
        if not (timedelta(0) < delta <= LEAD):
            continue
        # Ein Schlüssel je Beginn: derselbe Termin aus U27 und Kalender -> eine Nachricht.
        key = f"erinnerung:{iso}:{start}"
        if key in seen:
            continue
        seen.add(key)
        minutes = max(1, -(-int(delta.total_seconds()) // 60))  # aufrunden: 4:59 -> 5
        if kind == "aufsicht":
            detail = title if title and title.strip().lower() != "aufsicht" else None
            out.append({"key": key, "title": f"Aufsicht in {minutes} Min.",
                        "body": _join(detail, span, room)})
        else:
            slot = f"{slot_label} Stunde" if slot_label and slot_label.endswith(".") else None
            out.append({"key": key, "title": f"{title} in {minutes} Min.",
                        "body": _join(slot, span, room)})
    return out


def run_reminders(conn: sqlite3.Connection, now: datetime) -> None:
    for user_id in _users_with_devices(conn):
        try:
            for r in due_reminders(conn, user_id, now):
                if _claim(conn, user_id, r["key"]):
                    push.send_to_user(conn, user_id, r["title"], r["body"], tag=r["key"])
        except Exception:
            log.exception("Erinnerungen für Nutzer %s fehlgeschlagen", user_id)


# ---------------------------------------------------------------- Schulmanager
def is_poll_time(now: datetime) -> bool:
    return (now.weekday() < 5 and POLL_HOURS[0] <= now.hour < POLL_HOURS[1]
            and now.minute % POLL_EVERY_MIN == 0)


def schulmanager_changes(conn: sqlite3.Connection, user_id: int, now: datetime) -> List[dict]:
    """Künftige Abweichungen laut Feed, je mit stabilem Schlüssel. Wirft NoIcalUrl."""
    events = schulmanager_ical.fetch_and_parse(conn, user_id)
    changes = schulmanager_diff.compute_changes(conn, user_id, events)
    out = []
    for category, label in CATEGORY_LABELS.items():
        for c in changes.get(category, []):
            try:
                begins = datetime.fromisoformat(f"{c['date']}T{c['start']}")
            except (KeyError, TypeError, ValueError):
                continue
            if begins <= now:
                continue
            ref = c.get("actual") or c.get("expected") or {}
            title, room = ref.get("title") or "", ref.get("room") or ""
            span = f"{c['start']}–{c['end']}" if c.get("end") else c["start"]
            room_text = f"jetzt {room}" if category == "aufsicht_geaendert" and room else room
            out.append({
                "key": f"schulmanager:{category}:{c['date']}:{c['start']}:{title}:{room}",
                "label": label, "date": c["date"], "start": c["start"],
                "title": f"{label}: {title}" if title else label,
                "body": _join(_fmt_day(c["date"]), span, room_text),
            })
    out.sort(key=lambda x: (x["date"], x["start"]))
    return out


def run_schulmanager(conn: sqlite3.Connection, now: datetime) -> None:
    if not is_poll_time(now):
        return
    users = [r["user_id"] for r in conn.execute(
        "SELECT DISTINCT p.user_id FROM push_subscriptions p "
        "JOIN user_settings s ON s.user_id = p.user_id "
        "WHERE s.schulmanager_ical_cipher IS NOT NULL"
    )]
    for user_id in users:
        try:
            changes = schulmanager_changes(conn, user_id, now)
        except schulmanager_ical.NoIcalUrl:
            continue
        except Exception as exc:  # Feed nicht erreichbar o. Ä.: nächster Abruf in 15 Min.
            log.warning("Schulmanager-Abruf für Nutzer %s fehlgeschlagen: %s", user_id, exc)
            continue
        fresh = [c for c in changes if _claim(conn, user_id, c["key"])]
        if len(fresh) > BULK_LIMIT:
            # Z. B. beim ersten Abruf nach dem Aktivieren: eine Sammelnachricht statt Flut.
            preview = "; ".join(
                f"{c['label']} {WOCHENTAGE[date.fromisoformat(c['date']).weekday()]} "
                f"{date.fromisoformat(c['date']).strftime('%d.%m.')} {c['start']}"
                for c in fresh[:BULK_LIMIT]
            )
            push.send_to_user(conn, user_id, f"Schulmanager: {len(fresh)} neue Änderungen",
                              preview + " …", tag="schulmanager")
        else:
            for c in fresh:
                push.send_to_user(conn, user_id, c["title"], c["body"], tag=c["key"])


# ---------------------------------------------------------------- Takt
def tick(db_path: str, now: Optional[datetime] = None) -> None:
    now = now or now_local()
    conn = connect(db_path)
    try:
        for step in (run_reminders, run_schulmanager):  # Erinnerungen zuerst (zeitkritisch)
            try:
                step(conn, now)
            except Exception:
                log.exception("Benachrichtigungs-Schritt %s fehlgeschlagen", step.__name__)
        if now.hour == 3 and now.minute == 0:
            conn.execute("DELETE FROM push_sent WHERE sent_at < datetime('now', ?)",
                         (f"-{KEEP_SENT_DAYS} days",))
            conn.commit()
    finally:
        conn.close()


class Scheduler:
    """Daemon-Thread: ruft tick() kurz nach jeder vollen Minute auf."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="push-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(60 - (time.time() % 60) + 1):
            try:
                tick(self.db_path)
            except Exception:
                log.exception("Benachrichtigungs-Takt fehlgeschlagen")
