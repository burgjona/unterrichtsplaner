"""M1a: Schulmanager-ICS-Link speichern/abrufen/parsen (kein Netz, HTTP-Client gemockt)."""
import sqlite3

from src.lib import schulmanager_ical

ICS_URL = "https://login.schulmanager-online.de/ical/schedules/testtoken123"

# Synthetische, gekürzte ICS-Datei (Struktur wie der echte Schulmanager-Feed) – keine echten
# Nutzerdaten. Deckt regularLesson, specialLesson (mit ❇️-Präfix + DESCRIPTION), supervision
# und eine gefaltete Zeile (RFC-5545-Continuation) ab.
SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:Schulmanager Online
CALSCALE:GREGORIAN
BEGIN:VEVENT
UID:regularLesson_1001_2026-08-24@schulmanager-online.de
DTSTAMP:20260824T060000Z
SUMMARY:DE (8a)
DTSTART;TZID=Europe/Berlin:20260824T083500
DTEND;TZID=Europe/Berlin:20260824T092000
LOCATION:Raum Zi. 3.21 (Zi. 33)
END:VEVENT
BEGIN:VEVENT
UID:specialLesson_2002_2026-08-26@schulmanager-online.de
DTSTAMP:20260824T060000Z
SUMMARY:❇️ WTH-8a-1 (8a)
DTSTART;TZID=Europe/Berlin:20260826T113500
DTEND;TZID=Europe/Berlin:20260826T122000
LOCATION:Raum Zi. 1.3 (Zi. 12)
DESCRIPTION:gesamte Klasse - eine sehr lange Beschreibung, die in der ICS-D
 atei über mehrere Zeilen gefaltet sein könnte
END:VEVENT
BEGIN:VEVENT
UID:supervision_3003_2026-08-25@schulmanager-online.de
DTSTAMP:20260824T060000Z
SUMMARY:Aufsicht: Ebene 1
DTSTART;TZID=Europe/Berlin:20260825T092000
DTEND;TZID=Europe/Berlin:20260825T093500
LOCATION:Ebene 1: Cafeteria
END:VEVENT
END:VCALENDAR
"""


# ---------------------------------------------------------------- parse_ics()
def test_parse_ics_kinds_and_fields():
    events = schulmanager_ical.parse_ics(SAMPLE_ICS)
    assert len(events) == 3
    by_kind = {e["kind"]: e for e in events}
    assert set(by_kind) == {"regularLesson", "specialLesson", "supervision"}

    lesson = by_kind["regularLesson"]
    assert lesson["uid"] == "regularLesson_1001_2026-08-24@schulmanager-online.de"
    assert lesson["summary"] == "DE (8a)"
    assert lesson["start"] == "2026-08-24T08:35"
    assert lesson["end"] == "2026-08-24T09:20"
    assert lesson["all_day"] is False
    assert lesson["location"] == "Raum Zi. 3.21 (Zi. 33)"

    special = by_kind["specialLesson"]
    assert special["summary"].startswith("❇")
    # Gefaltete Beschreibungszeile wurde zu einer Zeile zusammengeführt.
    assert "über mehrere Zeilen gefaltet" in special["description"]

    supervision = by_kind["supervision"]
    assert supervision["location"] == "Ebene 1: Cafeteria"


def test_parse_ics_skips_unknown_prefix():
    ics = SAMPLE_ICS.replace("regularLesson_1001", "somethingElse_9_2026-08-24")
    events = schulmanager_ical.parse_ics(ics)
    kinds = {e["kind"] for e in events}
    assert "other" in kinds  # unbekannter Präfix wird nicht verworfen, nur als "other" markiert


def test_parse_ics_ignores_broken_event_without_uid():
    ics = SAMPLE_ICS.replace("UID:regularLesson_1001_2026-08-24@schulmanager-online.de\n", "")
    events = schulmanager_ical.parse_ics(ics)
    assert len(events) == 2  # das kaputte Event fehlt, die anderen zwei bleiben erhalten


# ---------------------------------------------------------------- Settings-Endpunkte
def test_settings_reports_no_schulmanager_by_default(client, auth):
    s = client.get("/api/settings").json()
    assert s["schulmanagerIcalSet"] is False
    assert s["schulmanagerLastSync"] is None


def test_set_and_delete_schulmanager_ical(client, auth):
    r = client.put("/api/settings/schulmanager-ical", json={"url": ICS_URL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schulmanagerIcalSet"] is True

    # Der Link liegt verschlüsselt in der DB (kein Klartext-Token).
    c = sqlite3.connect(client.app.state.db_path)
    cipher = c.execute("SELECT schulmanager_ical_cipher FROM user_settings").fetchone()[0]
    c.close()
    assert cipher is not None and b"testtoken123" not in cipher

    dele = client.delete("/api/settings/schulmanager-ical").json()
    assert dele["schulmanagerIcalSet"] is False


def test_schulmanager_ical_rejects_non_https(client, auth):
    r = client.put("/api/settings/schulmanager-ical", json={"url": "http://unsicher.example/feed.ics"})
    assert r.status_code == 400


def test_schulmanager_ical_rejects_empty(client, auth):
    r = client.put("/api/settings/schulmanager-ical", json={"url": "   "})
    assert r.status_code == 400


# ---------------------------------------------------------------- test-sync (gemockter HTTP-Client)
class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeHttpClient:
    def __init__(self, text):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        return FakeResponse(self._text)


def _install_fake_http(monkeypatch, text):
    monkeypatch.setattr(schulmanager_ical, "_make_http_client", lambda timeout=15.0: FakeHttpClient(text))


def test_test_sync_without_url_returns_400(client, auth):
    r = client.post("/api/settings/schulmanager-ical/test-sync")
    assert r.status_code == 400


def test_test_sync_counts_events_by_kind(client, auth, monkeypatch):
    client.put("/api/settings/schulmanager-ical", json={"url": ICS_URL})
    _install_fake_http(monkeypatch, SAMPLE_ICS)

    r = client.post("/api/settings/schulmanager-ical/test-sync")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert body["byKind"] == {"regularLesson": 1, "specialLesson": 1, "supervision": 1}

    # schulmanager_last_sync wurde gesetzt.
    s = client.get("/api/settings").json()
    assert s["schulmanagerLastSync"] is not None
