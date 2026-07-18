"""U21: Google-Kalender-Sync mit gemocktem Google-Client (kein Netz, keine echten Calls)."""
import json

import pytest

from src.lib import google_cal

# Gültiger Service-Account-JSON (nur Struktur zählt – wird nie an Google gesendet, da gemockt).
DUMMY_KEY = json.dumps({
    "type": "service_account",
    "project_id": "demo",
    "client_email": "svc@demo.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "token_uri": "https://oauth2.googleapis.com/token",
})
CAL_ID = "demo@group.calendar.google.com"


class FakeGoogleClient:
    def __init__(self, list_result=None, next_token="tok-new"):
        self.inserted, self.updated, self.deleted = [], [], []
        self._list = list_result if list_result is not None else []
        self._next_token = next_token

    def list_events(self, sync_token=None):
        return list(self._list), self._next_token

    def insert_event(self, body):
        eid = f"ev-{len(self.inserted) + 1}"
        self.inserted.append((eid, body))
        return {"id": eid, "etag": "etag-i", **body}

    def update_event(self, event_id, body):
        self.updated.append((event_id, body))
        return {"id": event_id, "etag": "etag-u", **body}

    def delete_event(self, event_id):
        self.deleted.append(event_id)


def _install(monkeypatch, fake):
    monkeypatch.setattr(google_cal, "_make_google_client", lambda kj, cid: fake)
    return fake


def _connect_google(client):
    r = client.put("/api/settings/google-key", json={"keyJson": DUMMY_KEY, "calendarId": CAL_ID})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- Settings-Endpunkte
def test_settings_reports_no_google_by_default(client, auth):
    s = client.get("/api/settings").json()
    assert s["googleKeySet"] is False
    assert s["googleCalendarId"] is None
    assert s["googleLastSync"] is None


def test_set_and_delete_google_key(client, auth):
    body = _connect_google(client)
    assert body["googleKeySet"] is True
    assert body["googleCalendarId"] == CAL_ID

    # Rohdaten in der DB sind verschlüsselt (kein Klartext des Schlüssels).
    import sqlite3
    c = sqlite3.connect(client.app.state.db_path)
    cipher = c.execute("SELECT google_key_cipher FROM user_settings").fetchone()[0]
    c.close()
    assert cipher is not None and b"service_account" not in cipher

    dele = client.delete("/api/settings/google-key").json()
    assert dele["googleKeySet"] is False
    assert dele["googleCalendarId"] is None


def test_google_key_rejects_invalid_json(client, auth):
    r = client.put("/api/settings/google-key", json={"keyJson": "kein json", "calendarId": CAL_ID})
    assert r.status_code == 400


def test_google_key_rejects_non_service_account(client, auth):
    r = client.put("/api/settings/google-key",
                   json={"keyJson": json.dumps({"type": "authorized_user"}), "calendarId": CAL_ID})
    assert r.status_code == 400


def test_google_key_requires_calendar_id(client, auth):
    r = client.put("/api/settings/google-key", json={"keyJson": DUMMY_KEY, "calendarId": "  "})
    assert r.status_code == 400


# ---------------------------------------------------------------- Sync-Endpunkt
def test_sync_without_key_returns_400(client, auth):
    r = client.post("/api/calendar/google/sync")
    assert r.status_code == 400
    assert "Google-Schlüssel" in r.json()["detail"]


def test_sync_pushes_new_local_entry(client, auth, monkeypatch):
    _connect_google(client)
    fake = _install(monkeypatch, FakeGoogleClient())
    client.post("/api/calendar", json={"title": "Wandertag", "entryDate": "2026-09-10", "allDay": True})

    r = client.post("/api/calendar/google/sync")
    assert r.status_code == 200, r.text
    assert r.json() == {"pushed": 1, "pulled": 0, "deleted": 0}
    assert len(fake.inserted) == 1
    # Ganztägig → Google-Body nutzt date (nicht dateTime), Ende exklusiv +1 Tag.
    _, body = fake.inserted[0]
    assert body["start"] == {"date": "2026-09-10"}
    assert body["end"] == {"date": "2026-09-11"}

    # Zweiter Sync ohne Änderung pusht nichts erneut (Mapping gesetzt, updated_at < last_sync).
    fake2 = _install(monkeypatch, FakeGoogleClient())
    r2 = client.post("/api/calendar/google/sync")
    assert r2.json()["pushed"] == 0
    assert fake2.inserted == []


def test_new_entry_after_prior_sync_pushed_once(client, auth, monkeypatch):
    # Regression: eine NACH einem ersten Sync angelegte Stunde darf nur einmal (insert),
    # nicht zusätzlich als "geändert" (update) hochgeladen werden.
    _connect_google(client)
    _install(monkeypatch, FakeGoogleClient())
    client.post("/api/calendar/google/sync")  # erster Sync setzt last_sync

    fake = _install(monkeypatch, FakeGoogleClient())
    client.post("/api/calendar", json={"title": "Neu", "entryDate": "2026-09-20", "allDay": True})
    r = client.post("/api/calendar/google/sync")
    assert r.json()["pushed"] == 1
    assert len(fake.inserted) == 1
    assert fake.updated == []  # kein zusätzlicher Update-Call


def test_sync_pulls_allday_and_timed_events(client, auth, monkeypatch):
    _connect_google(client)
    events = [
        {"id": "gA", "status": "confirmed", "summary": "Konferenz",
         "updated": "2030-01-01T10:00:00.000Z",
         "start": {"date": "2026-09-01"}, "end": {"date": "2026-09-02"}},
        {"id": "gB", "status": "confirmed", "summary": "Elternabend",
         "updated": "2030-01-01T10:00:00.000Z",
         "start": {"dateTime": "2026-09-05T18:00:00+02:00"},
         "end": {"dateTime": "2026-09-05T19:30:00+02:00"}},
    ]
    _install(monkeypatch, FakeGoogleClient(list_result=events))

    r = client.post("/api/calendar/google/sync")
    assert r.status_code == 200, r.text
    assert r.json()["pulled"] == 2

    entries = client.get("/api/calendar").json()
    by_title = {e["title"]: e for e in entries}
    assert by_title["Konferenz"]["allDay"] is True
    assert by_title["Konferenz"]["entryDate"] == "2026-09-01"
    assert by_title["Konferenz"]["endDate"] is None  # 09-02 exklusiv → eintägig
    ea = by_title["Elternabend"]
    assert ea["allDay"] is False
    assert ea["entryDate"] == "2026-09-05"
    assert ea["startTime"] == "18:00"
    assert ea["endTime"] == "19:30"

    # Sync-Token wurde gespeichert.
    s = client.get("/api/settings").json()
    assert s["googleLastSync"] is not None


def test_sync_deletes_cancelled_event(client, auth, monkeypatch):
    _connect_google(client)
    # 1) Ein Event hereinziehen.
    ev = {"id": "gDel", "status": "confirmed", "summary": "Projekttag",
          "updated": "2030-01-01T10:00:00.000Z",
          "start": {"date": "2026-10-01"}, "end": {"date": "2026-10-02"}}
    _install(monkeypatch, FakeGoogleClient(list_result=[ev]))
    client.post("/api/calendar/google/sync")
    assert any(e["title"] == "Projekttag" for e in client.get("/api/calendar").json())

    # 2) Storniertes Event → lokaler Eintrag wird entfernt.
    cancelled = {"id": "gDel", "status": "cancelled"}
    _install(monkeypatch, FakeGoogleClient(list_result=[cancelled]))
    r = client.post("/api/calendar/google/sync")
    assert r.json()["deleted"] == 1
    assert not any(e["title"] == "Projekttag" for e in client.get("/api/calendar").json())


def test_last_write_wins_keeps_newer_local(client, auth, monkeypatch):
    _connect_google(client)
    fake = _install(monkeypatch, FakeGoogleClient())
    client.post("/api/calendar", json={"title": "Lokal aktuell", "entryDate": "2026-11-01", "allDay": True})
    client.post("/api/calendar/google/sync")  # push → bekommt google_event_id "ev-1"

    # Google meldet dasselbe Event mit ÄLTEREM updated + abweichendem Titel → lokal gewinnt.
    stale = {"id": "ev-1", "status": "confirmed", "summary": "Alt aus Google",
             "updated": "2000-01-01T00:00:00.000Z",
             "start": {"date": "2026-11-01"}, "end": {"date": "2026-11-02"}}
    _install(monkeypatch, FakeGoogleClient(list_result=[stale]))
    r = client.post("/api/calendar/google/sync")
    assert r.json()["pulled"] == 0  # verworfen

    titles = [e["title"] for e in client.get("/api/calendar").json()]
    assert "Lokal aktuell" in titles
    assert "Alt aus Google" not in titles


# ---------------------------------------------------------------- Mapping-Helfer (Unit)
def test_event_to_fields_multiday_allday():
    ev = {"summary": "Ferien", "start": {"date": "2026-12-21"}, "end": {"date": "2026-12-25"}}
    f = google_cal._event_to_fields(ev)
    assert f["all_day"] == 1 and f["entry_date"] == "2026-12-21" and f["end_date"] == "2026-12-24"


def test_sync_requires_login(client):
    assert client.post("/api/calendar/google/sync").status_code == 401
