"""M11: Lernziele-Modul (SMART/Bloom) + 45/90-Minuten-Dauer.

Deckt Lesson-Roundtrip (Create/Out/Update-Replace), Dauer-Validierung, den KI-Endpunkt
mit gemocktem Anthropic-Client und die Seed-Erweiterung (detail_md) ab. Kein Netz.
"""
import json
import sqlite3

import pytest

from src.db import init_db
from src.lib import ai
from src.seed import seed_lernbereiche


# ---- Fake Anthropic client (Muster aus tests/test_ai.py) ----
class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Usage:
    input_tokens = 1000
    output_tokens = 300
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


# ---------- 1) Lesson-Roundtrip: Dauer + Lernziele ----------
def test_lesson_duration_and_lernziele_roundtrip(client, auth):
    body = {
        "title": "Balladen szenisch", "subject": "Deutsch", "grade": 7,
        "durationMinutes": 90,
        "phases": [{"phaseName": "Einstieg"}, {"phaseName": "Erarbeitung"}],
        "lernziele": [
            {"kind": "grob", "text": "Merkmale der Ballade verstehen", "bloomStufe": "Verstehen", "phaseSortOrder": None},
            {"kind": "fein", "text": "drei Balladenmerkmale benennen", "bloomStufe": "Erinnern", "phaseSortOrder": 1},
        ],
    }
    r = client.post("/api/lessons", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["durationMinutes"] == 90
    assert len(out["lernziele"]) == 2
    grob = next(z for z in out["lernziele"] if z["kind"] == "grob")
    fein = next(z for z in out["lernziele"] if z["kind"] == "fein")
    assert grob["bloomStufe"] == "Verstehen" and grob["phaseSortOrder"] is None
    assert fein["phaseSortOrder"] == 1
    assert all("id" in z for z in out["lernziele"])

    # GET liefert dieselben Ziele zurück
    got = client.get(f"/api/lessons/{out['id']}").json()
    assert got["durationMinutes"] == 90
    assert {z["text"] for z in got["lernziele"]} == {"Merkmale der Ballade verstehen", "drei Balladenmerkmale benennen"}

    # PUT ersetzt Ziele vollständig (replace-on-update) und ändert die Dauer
    upd = client.put(f"/api/lessons/{out['id']}", json={
        "durationMinutes": 45,
        "lernziele": [{"kind": "grob", "text": "Neues einziges Ziel", "bloomStufe": "Anwenden", "phaseSortOrder": 0}],
    })
    assert upd.status_code == 200, upd.text
    u = upd.json()
    assert u["durationMinutes"] == 45
    assert len(u["lernziele"]) == 1
    assert u["lernziele"][0]["text"] == "Neues einziges Ziel"


def test_invalid_duration_422(client, auth):
    r = client.post("/api/lessons", json={"title": "X", "subject": "Deutsch", "durationMinutes": 60})
    assert r.status_code == 422, r.text


def test_default_duration_is_45(client, auth):
    r = client.post("/api/lessons", json={"title": "Ohne Dauer", "subject": "Deutsch"})
    assert r.status_code == 201, r.text
    assert r.json()["durationMinutes"] == 45


# ---------- 2) KI-Endpunkt ----------
def _make_lesson_with_lb(client, app, duration=90, detail="OCR-DETAILTEXT-BallADE-Merkmale"):
    conn = sqlite3.connect(app.state.db_path)
    conn.execute(
        "INSERT INTO lernbereiche(subject, grade, track, code, title, detail_md) "
        "VALUES ('Deutsch', 7, 'RS', 'LB6', 'Fantasie und Wirklichkeit: Balladen', ?)",
        (detail,),
    )
    lb_id = conn.execute("SELECT id FROM lernbereiche WHERE code='LB6' AND grade=7 AND track='RS'").fetchone()[0]
    conn.commit()
    conn.close()
    lesson = client.post("/api/lessons", json={
        "title": "Balladen szenisch", "subject": "Deutsch", "grade": 7, "lessonType": "Einführung",
        "durationMinutes": duration, "lernbereichId": lb_id,
        "phases": [{"phaseName": "Einstieg", "minutes": 10, "socialForm": "Plenum", "method": "Hörimpuls"}],
    }).json()
    return lesson


def test_ai_lernziele_prompt_and_passthrough(client, auth, app, monkeypatch):
    lesson = _make_lesson_with_lb(client, app, duration=90, detail="OCR-DETAILTEXT-BallADE-Merkmale")
    payload = json.dumps({"ziele": [
        {"kind": "grob", "text": "Balladen verstehen", "bloomStufe": "Verstehen", "phaseSortOrder": None},
        {"kind": "fein", "text": "Merkmale benennen", "bloomStufe": "Erinnern", "phaseSortOrder": 1},
    ]})
    state = _install(monkeypatch, payload)
    _set_key(client)

    r = client.post(f"/api/ai/lernziele/{lesson['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False
    assert body["suggestion"]["ziele"][0]["kind"] == "grob"
    assert body["suggestion"]["ziele"][1]["phaseSortOrder"] == 1

    prompt = state["calls"][0]["messages"][0]["content"]
    assert "90 Minuten" in prompt
    assert "mindestens 4 Feinziele" in prompt          # 90-Min.-Dauerregel (2 Grob + >=4 Fein)
    assert "OCR-DETAILTEXT-BallADE-Merkmale" in prompt  # detail_md-Kontext des Lernbereichs


def test_ai_lernziele_45_min_rule(client, auth, app, monkeypatch):
    lesson = _make_lesson_with_lb(client, app, duration=45)
    state = _install(monkeypatch, json.dumps({"ziele": []}))
    _set_key(client)
    r = client.post(f"/api/ai/lernziele/{lesson['id']}")
    assert r.status_code == 200, r.text
    prompt = state["calls"][0]["messages"][0]["content"]
    assert "45 Minuten" in prompt
    assert "mindestens 2 Feinziele" in prompt


def test_ai_lernziele_requires_api_key(client, auth, app):
    lesson = _make_lesson_with_lb(client, app)
    r = client.post(f"/api/ai/lernziele/{lesson['id']}")
    assert r.status_code == 400
    assert "API-Key" in r.json()["detail"]


def test_ai_lernziele_foreign_lesson_404(client, auth):
    r = client.post("/api/ai/lernziele/999999")
    assert r.status_code == 404


# ---------- 3) Seed: detail_md ----------
def test_seed_fills_detail_md(tmp_path):
    conn = init_db(str(tmp_path / "seed.db"))
    seed_lernbereiche(conn)
    n = conn.execute(
        "SELECT COUNT(*) FROM lernbereiche WHERE subject='Deutsch' AND detail_md IS NOT NULL AND length(detail_md) > 50"
    ).fetchone()[0]
    assert n >= 1
    # Idempotenz: zweiter Lauf verändert die Anzahl befüllter Detailtexte nicht
    seed_lernbereiche(conn)
    n2 = conn.execute(
        "SELECT COUNT(*) FROM lernbereiche WHERE subject='Deutsch' AND detail_md IS NOT NULL AND length(detail_md) > 50"
    ).fetchone()[0]
    assert n2 == n
    conn.close()
