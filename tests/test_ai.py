"""M7: KI-Endpunkte mit gemocktem Anthropic-Client (kein Netz, keine Kosten)."""
import json

import pytest

from src.lib import ai


# ---- Fake Anthropic client ----
class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Usage:
    input_tokens = 1200
    output_tokens = 400
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.messages = self

    def create(self, **kwargs):  # client.messages.create(...)
        return _Resp(self._payload)


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    ai._prompt_cache.clear()
    yield
    ai._prompt_cache.clear()


def _install(monkeypatch, payload):
    state = {"makes": 0}

    def make(api_key):
        state["makes"] += 1
        return _FakeClient(payload)

    monkeypatch.setattr(ai, "_make_client", make)
    return state


def _set_key(client):
    assert client.put("/api/settings/api-key", json={"apiKey": "sk-ant-test-0000"}).status_code == 200


def test_ai_requires_api_key(client, auth):
    r = client.post("/api/ai/lesson-suggestion", json={"ideas": "Balladen"})
    assert r.status_code == 400
    assert "API-Key" in r.json()["detail"]


def test_lesson_suggestion_cache_and_usage(client, auth, monkeypatch):
    payload = json.dumps({
        "title": "Balladen szenisch erschließen",
        "klafki": {"gegenwart": "Alltagsbezug", "zukunft": "", "exemplarisch": "", "zugang": "", "struktur": ""},
        "meyerPlan": ["gruen"] * 10,
        "phases": [{"phaseName": "Einstieg", "minutes": 10, "socialForm": "Plenum", "method": "Hörimpuls",
                    "material": "", "teacherActivity": "spielt vor", "studentActivity": "", "gme": ""}],
    })
    state = _install(monkeypatch, payload)
    _set_key(client)

    r = client.post("/api/ai/lesson-suggestion", json={"ideas": "Balladen szenisch", "subject": "Deutsch", "grade": 8})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False
    assert body["suggestion"]["title"] == "Balladen szenisch erschließen"
    assert body["suggestion"]["meyerPlan"][0] == "gruen"
    assert state["makes"] == 1

    # identischer Prompt -> lokaler Cache, kein zweiter API-Call
    r2 = client.post("/api/ai/lesson-suggestion", json={"ideas": "Balladen szenisch", "subject": "Deutsch", "grade": 8})
    assert r2.json()["cached"] is True
    assert state["makes"] == 1  # kein erneuter Client-Aufbau

    usage = client.get("/api/ai/usage").json()
    assert usage["totalUsd"] > 0
    assert usage["rows"][0]["model"] == "claude-sonnet-4-6"
    assert usage["rows"][0]["outputTokens"] == 400  # genau ein geloggter Call


def test_asuv_suggestion(client, auth, monkeypatch):
    lesson = client.post("/api/lessons", json={"title": "Balladen", "subject": "Deutsch", "grade": 8,
                                               "klafki": {"gegenwart": "Alltag"}}).json()
    payload = json.dumps({f: "Text" for f in
                          ["bedingungOrg", "bedingungLern", "bedingungEinordnung", "ziele", "sachanalyse",
                           "quellen", "didaktisch", "reduktion", "methodisch"]})
    _install(monkeypatch, payload)
    _set_key(client)
    r = client.post(f"/api/ai/asuv/{lesson['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]["sachanalyse"] == "Text"


def test_stoffplan_suggestion(client, auth, monkeypatch):
    sy = client.post("/api/school-years", json={"label": "2025/2026", "startDate": "2025-08-11", "endDate": "2026-06-30"}).json()
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    client.post("/api/lernbereiche", json={"subject": "Deutsch", "grade": 8, "track": "RS", "code": "LB1", "title": "Gewusst wie", "richtwertUstd": 15})
    payload = json.dumps({"blocks": [{"code": "LB1", "title": "Gewusst wie", "ustd": 15, "weeks": 5, "note": "Übungsstunde vor LUE"}]})
    _install(monkeypatch, payload)
    _set_key(client)
    r = client.post("/api/ai/stoffplan", json={"schoolYearId": sy["id"], "classId": cls["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]["blocks"][0]["code"] == "LB1"
