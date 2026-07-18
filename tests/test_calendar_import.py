"""U20: Jahresplan-Import — Analyse (KI gemockt) + Commit (echte DB, kein Netz)."""
import json
from pathlib import Path

import pytest

from src.lib import ai

FIX = Path(__file__).parent / "fixtures" / "sample.pdf"


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Usage:
    input_tokens = 800
    output_tokens = 200
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


class _FakeClient:
    def __init__(self, payload, calls):
        self._payload = payload
        self.messages = self
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        return _Resp(self._payload)


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    ai._prompt_cache.clear()
    yield
    ai._prompt_cache.clear()


def _install(monkeypatch, payload):
    state = {"calls": []}
    monkeypatch.setattr(ai, "_make_client", lambda api_key: _FakeClient(payload, state["calls"]))
    return state


def _set_key(client):
    assert client.put("/api/settings/api-key", json={"apiKey": "sk-ant-test-0000"}).status_code == 200


def _analyze(client):
    return client.post("/api/calendar/import/analyze",
                       files={"file": ("jahresplan.pdf", FIX.read_bytes(), "application/pdf")})


def test_analyze_requires_api_key(client, auth):
    r = _analyze(client)
    assert r.status_code == 400
    assert "API-Key" in r.json()["detail"]


def test_analyze_returns_suggestions_camelcase(client, auth, monkeypatch):
    payload = json.dumps({"termine": [
        {"datum": "2025-10-13", "endDatum": "2025-10-25", "titel": "Herbstferien",
         "kategorieVorschlag": "Organisatorisch"},
        {"datum": "2025-12-19", "endDatum": None, "titel": "Weihnachtsfeier",
         "kategorieVorschlag": ""},
    ]})
    state = _install(monkeypatch, payload)
    _set_key(client)
    r = _analyze(client)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 2
    assert data[0]["datum"] == "2025-10-13"
    assert data[0]["endDatum"] == "2025-10-25"
    assert data[0]["kategorieVorschlag"] == "Organisatorisch"
    assert data[1]["endDatum"] is None
    assert data[1]["kategorieVorschlag"] is None  # leerer String -> null
    # Verfügbare Kategorien landen im Prompt (Mapping-Grundlage).
    assert "Verfügbare Kategorien:" in state["calls"][0]["messages"][0]["content"]


def test_analyze_bad_json_502(client, auth, monkeypatch):
    _install(monkeypatch, "<html>kein JSON")
    _set_key(client)
    r = _analyze(client)
    assert r.status_code == 502
    assert "JSON" in r.json()["detail"]


def test_commit_creates_entries_with_category(client, auth):
    cats = client.get("/api/calendar-categories").json()  # seedet Standard-Kategorien
    cid = cats[0]["id"]
    r = client.post("/api/calendar/import/commit", json={"entries": [
        {"datum": "2025-10-13", "endDatum": "2025-10-25", "titel": "Herbstferien", "categoryId": cid},
        {"datum": "2025-12-19", "titel": "Weihnachtsfeier"},
    ]})
    assert r.status_code == 201, r.text
    created = r.json()
    assert len(created) == 2
    assert created[0]["allDay"] is True
    assert created[0]["entryType"] == "normal"
    assert created[0]["categoryId"] == cid
    assert created[0]["endDate"] == "2025-10-25"

    entries = client.get("/api/calendar").json()
    titles = {e["title"]: e for e in entries}
    assert "Herbstferien" in titles and "Weihnachtsfeier" in titles
    assert titles["Herbstferien"]["categoryId"] == cid


def test_commit_foreign_category_400(client, auth):
    r = client.post("/api/calendar/import/commit", json={"entries": [
        {"datum": "2025-10-13", "titel": "Herbstferien", "categoryId": 999999},
    ]})
    assert r.status_code == 400
    assert "Kategorie" in r.json()["detail"]


def test_commit_skips_incomplete_rows(client, auth):
    r = client.post("/api/calendar/import/commit", json={"entries": [
        {"datum": "", "titel": "ohne Datum"},
        {"datum": "2025-11-01", "titel": "   "},
        {"datum": "2025-11-05", "titel": "gültig"},
    ]})
    assert r.status_code == 201, r.text
    created = r.json()
    assert len(created) == 1
    assert created[0]["title"] == "gültig"
