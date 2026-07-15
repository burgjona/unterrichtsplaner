"""M11 (U5): Jahresplan-Notizen (Freitext) + Stoffplan-Prompt (gemischt / LB1+2-Integration).

KI wird über einen gemockten Anthropic-Client getestet – nie echte API-Calls.
Muster für den Fake-Client aus tests/test_ai.py übernommen (bewusst dupliziert, um
Konflikte mit Parallel-Agenten an test_ai.py zu vermeiden).
"""
import json

import pytest

from src.lib import ai


# ---- Fake Anthropic client (Muster aus tests/test_ai.py) ----
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
    state = {"makes": 0, "calls": []}

    def make(api_key):
        state["makes"] += 1
        return _FakeClient(payload, state["calls"])

    monkeypatch.setattr(ai, "_make_client", make)
    return state


def _set_key(client):
    assert client.put("/api/settings/api-key", json={"apiKey": "sk-ant-test-0000"}).status_code == 200


def _mk_year(client):
    return client.post("/api/school-years",
                       json={"label": "2025/2026", "startDate": "2025-08-11", "endDate": "2026-06-30"}).json()


def _mk_class(client, track="gemischt", grade=8):
    return client.post("/api/classes",
                       json={"name": "8a", "subject": "Deutsch", "grade": grade, "track": track,
                             "weeklyHours": 4}).json()


def _seed_rs_lbs(client, grade=8):
    for n, ustd in [(1, 10), (2, 10), (3, 20), (4, 20), (5, 20), (6, 20)]:
        client.post("/api/lernbereiche",
                    json={"subject": "Deutsch", "grade": grade, "track": "RS", "code": f"LB{n}",
                          "title": f"Thema {n}", "richtwertUstd": ustd})


# ---------- Notizen: Upsert & Roundtrip ----------
def test_plan_notes_roundtrip_and_upsert(client, auth):
    sy = _mk_year(client)
    cls = _mk_class(client)

    # Ohne vorhandene Notiz: leerer Text.
    r0 = client.get(f"/api/planning/notes?classId={cls['id']}&schoolYearId={sy['id']}")
    assert r0.status_code == 200, r0.text
    assert r0.json()["text"] == ""

    # PUT legt an.
    r1 = client.put("/api/planning/notes",
                    json={"classId": cls["id"], "schoolYearId": sy["id"], "text": "Projektwoche im Mai"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["text"] == "Projektwoche im Mai"

    # GET liefert dieselbe Notiz.
    assert client.get(f"/api/planning/notes?classId={cls['id']}&schoolYearId={sy['id']}").json()["text"] == "Projektwoche im Mai"

    # PUT erneut → Upsert (überschreibt, kein Duplikat/Fehler).
    r2 = client.put("/api/planning/notes",
                    json={"classId": cls["id"], "schoolYearId": sy["id"], "text": "Lektüre im Herbst"})
    assert r2.status_code == 200, r2.text
    assert client.get(f"/api/planning/notes?classId={cls['id']}&schoolYearId={sy['id']}").json()["text"] == "Lektüre im Herbst"


def test_plan_notes_scoping_foreign_class_404(client, auth):
    sy = _mk_year(client)
    r = client.put("/api/planning/notes",
                   json={"classId": 9999, "schoolYearId": sy["id"], "text": "x"})
    assert r.status_code == 404


# ---------- Stoffplan-Prompt: Freitext + Gemischt + keine LB1/2-Blöcke ----------
def test_stoffplan_prompt_contains_notes_gemischt_and_no_lb12(client, auth, monkeypatch):
    sy = _mk_year(client)
    cls = _mk_class(client, track="gemischt", grade=8)
    _seed_rs_lbs(client, grade=8)
    client.put("/api/planning/notes",
               json={"classId": cls["id"], "schoolYearId": sy["id"], "text": "Projektwoche im Mai einplanen"})

    payload = json.dumps({"blocks": [{"code": "LB3", "title": "Thema 3", "ustd": 25, "weeks": 7, "note": "x"}]})
    state = _install(monkeypatch, payload)
    _set_key(client)

    r = client.post("/api/ai/stoffplan", json={"schoolYearId": sy["id"], "classId": cls["id"]})
    assert r.status_code == 200, r.text
    prompt = state["calls"][0]["messages"][0]["content"]

    # Freitext des Lehrers ist enthalten und als vorrangig markiert.
    assert "Projektwoche im Mai einplanen" in prompt
    assert "Vorrang vor den Standardregeln" in prompt
    # Gemischt-Anweisung (RS-Ausrichtung + HS-Differenzierung).
    assert "gemischter Bildungsgang" in prompt
    assert "Realschulbildungsgang" in prompt
    # LB1/2-Integrationsanweisung + LB1/LB2 tauchen nicht mehr als eigene Blöcke auf.
    assert "Lernbereiche 1 und 2" in prompt
    assert "- LB1:" not in prompt and "- LB2:" not in prompt


def test_stoffplan_prompt_no_gemischt_hint_for_rs_class(client, auth, monkeypatch):
    """Reine RS-Klasse: keine Gemischt-Anweisung, aber weiterhin LB1/2-Integration (Deutsch)."""
    sy = _mk_year(client)
    cls = _mk_class(client, track="RS", grade=8)
    _seed_rs_lbs(client, grade=8)

    payload = json.dumps({"blocks": [{"code": "LB3", "title": "Thema 3", "ustd": 25, "weeks": 7, "note": "x"}]})
    state = _install(monkeypatch, payload)
    _set_key(client)

    r = client.post("/api/ai/stoffplan", json={"schoolYearId": sy["id"], "classId": cls["id"]})
    assert r.status_code == 200, r.text
    prompt = state["calls"][0]["messages"][0]["content"]
    assert "gemischter Bildungsgang" not in prompt
    assert "Lernbereiche 1 und 2" in prompt
    assert "- LB1:" not in prompt
