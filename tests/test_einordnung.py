"""M12/U7: KI-Einordnung freier Stunden (Lernbereichs-/Lernziel-Vorschlag).

Anthropic-Client gemockt (kein Netz, keine Kosten) – Muster aus tests/test_ai.py.
"""
import json

import pytest

from src.lib import ai


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Usage:
    input_tokens = 300
    output_tokens = 80
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


def test_einordnung_routing_is_haiku():
    assert ai.ROUTING["einordnung"] == "haiku"


def test_einordnung_free_lesson(client, auth, monkeypatch):
    client.post("/api/lernbereiche", json={"subject": "Deutsch", "grade": 8, "track": "RS",
                                           "code": "LB3", "title": "Balladen", "richtwertUstd": 15})
    lesson = client.post("/api/lessons", json={"title": "Freie Stunde", "subject": "Deutsch", "grade": 8}).json()
    payload = json.dumps({"lernbereichCode": "LB3", "lernbereichTitle": "Balladen",
                          "lernzielHinweis": "Merkmale der Ballade erkennen", "begruendung": "passt thematisch"})
    state = _install(monkeypatch, payload)
    _set_key(client)

    r = client.post(f"/api/ai/einordnung/{lesson['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False
    assert body["suggestion"]["lernbereichCode"] == "LB3"
    assert state["makes"] == 1
    # Kandidaten-Lernbereich landet im Prompt
    prompt = state["calls"][0]["messages"][0]["content"]
    assert "LB3" in prompt and "Balladen" in prompt


def test_einordnung_requires_api_key(client, auth):
    client.post("/api/lernbereiche", json={"subject": "Deutsch", "grade": 8, "track": "RS",
                                           "code": "LB3", "title": "Balladen"})
    lesson = client.post("/api/lessons", json={"title": "Freie Stunde", "subject": "Deutsch", "grade": 8}).json()
    r = client.post(f"/api/ai/einordnung/{lesson['id']}")
    assert r.status_code == 400
    assert "API-Key" in r.json()["detail"]


def test_einordnung_no_candidates_404(client, auth, monkeypatch):
    _install(monkeypatch, "{}")
    _set_key(client)
    # Klassenstufe ohne Lernbereiche -> keine Kandidaten
    lesson = client.post("/api/lessons", json={"title": "Freie Stunde", "subject": "WTH", "grade": 5}).json()
    r = client.post(f"/api/ai/einordnung/{lesson['id']}")
    assert r.status_code == 404


def test_einordnung_foreign_lesson_404(client, auth, app, monkeypatch):
    _install(monkeypatch, "{}")
    _set_key(client)
    import sqlite3
    conn = sqlite3.connect(app.state.db_path)
    conn.execute("INSERT INTO users(email, display_name, password_hash) VALUES ('fremd7@t.de', 'F', 'hash')")
    other_id = conn.execute("SELECT id FROM users WHERE email='fremd7@t.de'").fetchone()[0]
    cur = conn.execute("INSERT INTO lessons(user_id, title, subject, grade) VALUES (?, 'Fremd', 'Deutsch', 8)",
                       (other_id,))
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    r = client.post(f"/api/ai/einordnung/{lid}")
    assert r.status_code == 404
