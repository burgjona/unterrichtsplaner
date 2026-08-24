"""Schulmanager-Online: Lesezugriff auf den persönlichen ICS-Stundenplan-Feed (M1a).

Kein Login, keine inoffizielle API: Schulmanager bietet unter /ical/schedules/<token>
einen personalisierten, stündlich aktualisierten iCal-Feed mit den eigenen Unterrichts-
stunden (UID-Präfix `regularLesson_`/`specialLesson_`) und Aufsichten (`supervision_`).
Der Link ist geheim (Besitz = Lesezugriff) und liegt daher AES-256-GCM-verschlüsselt in
user_settings (Muster: google_cal.py).

Dieses Modul deckt nur Abruf + Parsing ab (M1a). Der Soll/Ist-Abgleich gegen den U27-
Stundenplan bzw. bestehende Kalendereinträge (Erkennung von Vertretung/Ausfall/neuen
Aufsichten) folgt in einem späteren Milestone.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import List, Optional, TypedDict

from .security import decrypt_secret

FETCH_TIMEOUT = 15.0


class NoIcalUrl(Exception):
    """Kein Schulmanager-ICS-Link hinterlegt."""


class IcsEvent(TypedDict):
    uid: str
    kind: str          # "regularLesson" | "specialLesson" | "supervision" | "other"
    summary: str
    start: str          # ISO "YYYY-MM-DDTHH:MM" (all_day: "YYYY-MM-DD")
    end: Optional[str]
    all_day: bool
    location: Optional[str]
    description: Optional[str]


def _make_http_client(timeout: float = FETCH_TIMEOUT):
    """Dünner Wrapper um httpx.Client. In Tests gemockt (analog google_cal._make_google_client)."""
    import httpx
    return httpx.Client(timeout=timeout)


def fetch_ics(url: str) -> str:
    """Lädt den rohen ICS-Text. Wirft bei HTTP-Fehlern (httpx.HTTPStatusError)."""
    with _make_http_client() as http:
        resp = http.get(url)
        resp.raise_for_status()
        return resp.text


_KIND_RE = re.compile(r"^([a-zA-Z]+)_")


def _kind_for_uid(uid: str) -> str:
    m = _KIND_RE.match(uid)
    if not m:
        return "other"
    prefix = m.group(1)
    return prefix if prefix in ("regularLesson", "specialLesson", "supervision") else "other"


def _unfold(raw: str) -> List[str]:
    """RFC-5545-Zeilenfaltung auflösen: Folgezeilen beginnen mit Leerzeichen/Tab."""
    lines: List[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        elif line.strip():
            lines.append(line)
    return lines


def _split_prop(line: str):
    """"DTSTART;TZID=Europe/Berlin:20260824T083500" -> ("DTSTART", {"TZID": "..."}, "20260824T083500")."""
    name_part, _, value = line.partition(":")
    segs = name_part.split(";")
    name = segs[0].upper()
    params = {}
    for seg in segs[1:]:
        k, _, v = seg.partition("=")
        if k:
            params[k.upper()] = v
    return name, params, value


def _parse_dt(value: str) -> tuple[str, bool]:
    """ICS-Datum/-Zeit -> (ISO-String, all_day). UTC-'Z'-Suffix wird nicht konvertiert
    (Schulmanager liefert durchgängig TZID=Europe/Berlin, kein UTC-Fall beobachtet)."""
    value = value.rstrip("Z")
    if "T" in value:
        dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
        return dt.strftime("%Y-%m-%dT%H:%M"), False
    d = datetime.strptime(value, "%Y%m%d").date()
    return d.isoformat(), True


def parse_ics(raw: str) -> List[IcsEvent]:
    """ICS-Text -> Liste der VEVENTs. Unbekannte/kaputte Events werden übersprungen,
    nicht die ganze Datei verworfen (ein fehlerhaftes Event soll nicht alle anderen blockieren)."""
    events: List[IcsEvent] = []
    current: Optional[dict] = None
    for line in _unfold(raw):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                ev = _finish_event(current)
                if ev is not None:
                    events.append(ev)
            current = None
            continue
        if current is None:
            continue  # außerhalb eines VEVENT (VCALENDAR/VTIMEZONE-Header) ignorieren
        name, params, value = _split_prop(line)
        if name == "UID":
            current["uid"] = value
        elif name == "SUMMARY":
            current["summary"] = value
        elif name == "LOCATION":
            current["location"] = value
        elif name == "DESCRIPTION":
            current["description"] = value
        elif name == "DTSTART":
            current["start_raw"] = value
        elif name == "DTEND":
            current["end_raw"] = value
    return events


def _finish_event(fields: dict) -> Optional[IcsEvent]:
    uid = fields.get("uid")
    start_raw = fields.get("start_raw")
    if not uid or not start_raw:
        return None
    start, all_day = _parse_dt(start_raw)
    end = None
    if fields.get("end_raw"):
        end, _ = _parse_dt(fields["end_raw"])
    return IcsEvent(
        uid=uid,
        kind=_kind_for_uid(uid),
        summary=fields.get("summary") or "",
        start=start,
        end=end,
        all_day=all_day,
        location=fields.get("location"),
        description=fields.get("description"),
    )


# ------------------------------------------------------------------ Settings-Zugriff
def load_ical_url(conn: sqlite3.Connection, user_id: int) -> Optional[str]:
    """Entschlüsselte ICS-URL für den Nutzer, oder None wenn keine hinterlegt/entschlüsselbar."""
    row = conn.execute(
        "SELECT schulmanager_ical_cipher, schulmanager_ical_nonce FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row or not row["schulmanager_ical_cipher"]:
        return None
    try:
        return decrypt_secret(row["schulmanager_ical_cipher"], row["schulmanager_ical_nonce"])
    except Exception:
        return None


def fetch_and_parse(conn: sqlite3.Connection, user_id: int) -> List[IcsEvent]:
    """Für M1a: URL laden, Feed abrufen, parsen. Wirft NoIcalUrl, wenn nichts hinterlegt ist."""
    url = load_ical_url(conn, user_id)
    if not url:
        raise NoIcalUrl()
    raw = fetch_ics(url)
    conn.execute(
        "UPDATE user_settings SET schulmanager_last_sync = datetime('now') WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    return parse_ics(raw)
