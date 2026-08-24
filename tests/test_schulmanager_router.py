"""M1c: GET /api/schulmanager/changes – Feed abrufen (gemockter HTTP-Client) + diffen."""
from src.lib import schulmanager_ical

ICS_URL = "https://login.schulmanager-online.de/ical/schedules/testtoken"

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:Schulmanager Online
BEGIN:VEVENT
UID:supervision_1_2026-08-24@schulmanager-online.de
DTSTAMP:20260824T060000Z
SUMMARY:Aufsicht: Ebene 1
DTSTART;TZID=Europe/Berlin:20260824T092000
DTEND;TZID=Europe/Berlin:20260824T093500
LOCATION:Ebene 1: Cafeteria
END:VEVENT
END:VCALENDAR
"""


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


def test_changes_without_url_returns_400(client, auth):
    r = client.get("/api/schulmanager/changes")
    assert r.status_code == 400


def test_changes_requires_login(client):
    assert client.get("/api/schulmanager/changes").status_code == 401


def test_changes_returns_categorized_list(client, auth, monkeypatch):
    client.put("/api/settings/schulmanager-ical", json={"url": ICS_URL})
    monkeypatch.setattr(schulmanager_ical, "_make_http_client", lambda timeout=15.0: FakeHttpClient(SAMPLE_ICS))

    r = client.get("/api/schulmanager/changes")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["vertretung"] == []
    assert body["ausfall"] == []
    assert len(body["aufsichtNeu"]) == 1
    item = body["aufsichtNeu"][0]
    assert item["date"] == "2026-08-24"
    assert item["start"] == "09:20"
    assert item["actual"]["room"] == "Ebene 1: Cafeteria"
