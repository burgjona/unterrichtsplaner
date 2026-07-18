"""Google-Kalender-Sync (U21) via Service-Account.

Authentifizierung ohne OAuth-Flow: aus dem hinterlegten Service-Account-JSON-Schlüssel
erzeugt `google-auth` ein OAuth2-Access-Token (Scope calendar). Die Calendar-REST-Aufrufe
laufen über httpx. Der Schlüssel liegt AES-256-GCM-verschlüsselt in user_settings.

Sync-Richtungen:
  push  – Dashboard→Google: neue (`google_event_id IS NULL`) und seit letztem Sync
          geänderte (`updated_at > google_last_sync`) Einträge hochladen.
  pull  – Google→Dashboard: Events listen (inkrementell via syncToken, sonst voll),
          upserten (mit gesetzter `google_event_id`), stornierte lokal entfernen.
Konflikt = last-write-wins: das neuere `updated`/`updated_at` gewinnt.

`_make_google_client(...)` kapselt die Auth + den REST-Client, damit Tests sie mocken
können (analog `ai._make_client`). NIE echte Google-Calls in Tests.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple
from urllib.parse import quote

from .security import decrypt_secret

SCOPE = "https://www.googleapis.com/auth/calendar"
TZ = "Europe/Berlin"
API_BASE = "https://www.googleapis.com/calendar/v3"


class NoGoogleKey(Exception):
    """Kein Google-Service-Account-Schlüssel bzw. keine Kalender-ID hinterlegt."""


class SyncTokenInvalid(Exception):
    """Der gespeicherte syncToken ist abgelaufen (HTTP 410) – Vollsync nötig."""


# ---------------------------------------------------------------- REST-Client
class GoogleCalendarClient:
    """Dünner REST-Wrapper um die Google-Calendar-Events-API (httpx)."""

    def __init__(self, access_token: str, calendar_id: str, http=None):
        import httpx
        self._token = access_token
        self._cal = calendar_id
        self._http = http or httpx.Client(timeout=30.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _events_url(self) -> str:
        return f"{API_BASE}/calendars/{quote(self._cal)}/events"

    def list_events(self, sync_token: Optional[str] = None) -> Tuple[List[dict], Optional[str]]:
        """Alle Events (paginiert) + neuen nextSyncToken. 410 → SyncTokenInvalid."""
        events: List[dict] = []
        base_params = {"maxResults": 250, "showDeleted": True, "singleEvents": True}
        if sync_token:
            base_params["syncToken"] = sync_token
        page_token = None
        next_sync = None
        while True:
            params = dict(base_params)
            if page_token:
                params["pageToken"] = page_token
            resp = self._http.get(self._events_url(), headers=self._headers(), params=params)
            if resp.status_code == 410:
                raise SyncTokenInvalid()
            resp.raise_for_status()
            data = resp.json()
            events.extend(data.get("items", []))
            next_sync = data.get("nextSyncToken", next_sync)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return events, next_sync

    def insert_event(self, body: dict) -> dict:
        resp = self._http.post(self._events_url(), headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()

    def update_event(self, event_id: str, body: dict) -> dict:
        url = f"{self._events_url()}/{quote(event_id)}"
        resp = self._http.put(url, headers=self._headers(), json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_event(self, event_id: str) -> None:
        url = f"{self._events_url()}/{quote(event_id)}"
        resp = self._http.delete(url, headers=self._headers())
        # 404/410 = schon weg → als Erfolg behandeln.
        if resp.status_code not in (200, 204, 404, 410):
            resp.raise_for_status()


def _make_google_client(key_json: str, calendar_id: str) -> GoogleCalendarClient:
    """Service-Account-JSON → Access-Token → REST-Client. In Tests gemockt."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    info = json.loads(key_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    creds.refresh(Request())
    return GoogleCalendarClient(creds.token, calendar_id)


# ------------------------------------------------------------- Mapping-Helfer
def _entry_to_body(row) -> dict:
    """calendar_entries-Zeile → Google-Event-Body (all_day = date, sonst dateTime)."""
    body = {"summary": row["title"] or "(ohne Titel)"}
    if row["all_day"]:
        start = row["entry_date"]
        end_incl = row["end_date"] or row["entry_date"]
        # Google-Ganztagesende ist EXKLUSIV → +1 Tag.
        end_excl = (date.fromisoformat(end_incl) + timedelta(days=1)).isoformat()
        body["start"] = {"date": start}
        body["end"] = {"date": end_excl}
    else:
        start_time = row["start_time"] or "00:00"
        start_dt = f"{row['entry_date']}T{start_time}:00"
        end_date = row["end_date"] or row["entry_date"]
        if row["end_time"]:
            end_dt = f"{end_date}T{row['end_time']}:00"
        else:
            end_dt = (datetime.fromisoformat(start_dt) + timedelta(hours=1)).isoformat(timespec="seconds")
        body["start"] = {"dateTime": start_dt, "timeZone": TZ}
        body["end"] = {"dateTime": end_dt, "timeZone": TZ}
    return body


def _split_dt(s: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not s:
        return None, None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    return dt.date().isoformat(), dt.strftime("%H:%M")


def _event_to_fields(event: dict) -> dict:
    """Google-Event → Feld-Dict für calendar_entries."""
    start = event.get("start", {}) or {}
    end = event.get("end", {}) or {}
    title = event.get("summary") or "(ohne Titel)"
    if "date" in start:  # ganztägig
        entry_date = start["date"]
        end_date = None
        end_excl = end.get("date")
        if end_excl:
            end_incl = (date.fromisoformat(end_excl) - timedelta(days=1)).isoformat()
            if end_incl > entry_date:
                end_date = end_incl
        return {"title": title, "entry_date": entry_date, "end_date": end_date,
                "start_time": None, "end_time": None, "all_day": 1}
    s_date, s_time = _split_dt(start.get("dateTime"))
    e_date, e_time = _split_dt(end.get("dateTime"))
    end_date = e_date if (e_date and e_date != s_date) else None
    return {"title": title, "entry_date": s_date, "end_date": end_date,
            "start_time": s_time, "end_time": e_time, "all_day": 0}


def _parse_google_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_local_ts(s: Optional[str]) -> Optional[datetime]:
    """SQLite-UTC-Zeit ('YYYY-MM-DD HH:MM:SS') → aware UTC-datetime."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _iso_utc(dt: Optional[datetime]) -> str:
    """Aware datetime → SQLite-kompatible UTC-Zeichenkette (vergleichbar mit datetime('now'))."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ Sync-Kern
def _load_config(conn: sqlite3.Connection, user_id: int) -> Optional[dict]:
    row = conn.execute(
        """SELECT google_key_cipher, google_key_nonce, google_calendar_id,
                  google_sync_token, google_last_sync
             FROM user_settings WHERE user_id = ?""",
        (user_id,),
    ).fetchone()
    if not row or not row["google_key_cipher"] or not row["google_calendar_id"]:
        return None
    try:
        key_json = decrypt_secret(row["google_key_cipher"], row["google_key_nonce"])
    except Exception:
        return None
    return {"key_json": key_json, "calendar_id": row["google_calendar_id"],
            "sync_token": row["google_sync_token"], "last_sync": row["google_last_sync"]}


def push_entry(client, entry) -> Tuple[Optional[str], Optional[str]]:
    """Ein calendar_entries-Row nach Google hochladen (insert/update). Gibt (event_id, etag)."""
    body = _entry_to_body(entry)
    gid = entry["google_event_id"] if "google_event_id" in entry.keys() else None
    ev = client.update_event(gid, body) if gid else client.insert_event(body)
    return ev.get("id"), ev.get("etag")


def _push(conn: sqlite3.Connection, user_id: int, client, last_sync: Optional[str]) -> int:
    pushed = 0
    # Geänderte Einträge ZUERST auslesen (nur bereits gemappte). Muss vor dem Insert der
    # neuen Einträge geschehen, sonst würden frisch hochgeladene Einträge (deren
    # google_event_id gerade gesetzt wird) hier fälschlich erneut als "geändert" gepusht.
    changed = []
    if last_sync:
        changed = conn.execute(
            """SELECT * FROM calendar_entries
                 WHERE user_id = ? AND google_event_id IS NOT NULL
                   AND updated_at IS NOT NULL AND updated_at > ?""",
            (user_id, last_sync),
        ).fetchall()

    # Neue Einträge (noch nie hochgeladen).
    for r in conn.execute(
        "SELECT * FROM calendar_entries WHERE user_id = ? AND google_event_id IS NULL",
        (user_id,),
    ).fetchall():
        ev = client.insert_event(_entry_to_body(r))
        conn.execute(
            "UPDATE calendar_entries SET google_event_id = ?, google_etag = ? WHERE id = ? AND user_id = ?",
            (ev.get("id"), ev.get("etag"), r["id"], user_id),
        )
        pushed += 1

    # Seit letztem Sync lokal geänderte Einträge nach Google spiegeln.
    for r in changed:
        ev = client.update_event(r["google_event_id"], _entry_to_body(r))
        conn.execute(
            "UPDATE calendar_entries SET google_etag = ? WHERE id = ? AND user_id = ?",
            (ev.get("etag"), r["id"], user_id),
        )
        pushed += 1
    conn.commit()
    return pushed


def pull_events(conn: sqlite3.Connection, user_id: int, client,
                sync_token: Optional[str] = None) -> Tuple[int, int, Optional[str]]:
    """Google-Events übernehmen. Gibt (pulled, deleted, new_sync_token)."""
    try:
        events, new_token = client.list_events(sync_token)
    except SyncTokenInvalid:
        events, new_token = client.list_events(None)  # Vollsync bei abgelaufenem Token

    pulled = 0
    deleted = 0
    for ev in events:
        gid = ev.get("id")
        if not gid:
            continue
        existing = conn.execute(
            "SELECT id, updated_at FROM calendar_entries WHERE user_id = ? AND google_event_id = ?",
            (user_id, gid),
        ).fetchone()
        if ev.get("status") == "cancelled":
            if existing:
                conn.execute("DELETE FROM calendar_entries WHERE id = ? AND user_id = ?",
                             (existing["id"], user_id))
                deleted += 1
            continue
        fields = _event_to_fields(ev)
        if not fields["entry_date"]:
            continue  # unbrauchbares Event (weder date noch dateTime)
        g_updated = _parse_google_ts(ev.get("updated"))
        etag = ev.get("etag")
        if existing:
            # Last-write-wins: lokale Version neuer → Google-Änderung verwerfen.
            local_ts = _parse_local_ts(existing["updated_at"])
            if local_ts and g_updated and local_ts > g_updated:
                continue
            conn.execute(
                """UPDATE calendar_entries
                     SET title = ?, entry_date = ?, end_date = ?, start_time = ?, end_time = ?,
                         all_day = ?, google_etag = ?, updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (fields["title"], fields["entry_date"], fields["end_date"], fields["start_time"],
                 fields["end_time"], fields["all_day"], etag, _iso_utc(g_updated),
                 existing["id"], user_id),
            )
            pulled += 1
        else:
            conn.execute(
                """INSERT INTO calendar_entries
                     (user_id, title, entry_date, end_date, start_time, end_time, all_day,
                      entry_type, is_fixed, google_event_id, google_etag, updated_at)
                   VALUES (?,?,?,?,?,?,?,'normal',0,?,?,?)""",
                (user_id, fields["title"], fields["entry_date"], fields["end_date"],
                 fields["start_time"], fields["end_time"], fields["all_day"], gid, etag,
                 _iso_utc(g_updated)),
            )
            pulled += 1
    conn.commit()
    return pulled, deleted, new_token


def sync(conn: sqlite3.Connection, user_id: int) -> dict:
    """Vollständiger Abgleich (push + pull). Aktualisiert last_sync/sync_token.

    Wirft NoGoogleKey, wenn kein Schlüssel/keine Kalender-ID hinterlegt ist.
    """
    cfg = _load_config(conn, user_id)
    if cfg is None:
        raise NoGoogleKey()

    client = _make_google_client(cfg["key_json"], cfg["calendar_id"])
    pushed = _push(conn, user_id, client, cfg["last_sync"])
    pulled, deleted, new_token = pull_events(conn, user_id, client, cfg["sync_token"])

    conn.execute(
        """UPDATE user_settings
             SET google_last_sync = datetime('now'), google_sync_token = ?
           WHERE user_id = ?""",
        (new_token, user_id),
    )
    conn.commit()
    return {"pushed": pushed, "pulled": pulled, "deleted": deleted}
