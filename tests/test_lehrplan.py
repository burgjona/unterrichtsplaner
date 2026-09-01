"""Lehrplan-Abhakmodul: Checkliste je Klasse + Abhak-Status + KI-Feinziele."""
import json
import sqlite3

import pytest

from src.lib import ai
from src.seed import seed_lehrplan_ziele, seed_lernbereiche


# ---- Fake Anthropic client (Muster aus tests/test_lernziele.py) ----
class _Usage:
    input_tokens, output_tokens, cache_read_input_tokens = 800, 200, 0


class _Resp:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = _Usage()
        self.stop_reason = "end_turn"


class _FakeClient:
    def __init__(self, payload, calls):
        self._payload, self.messages, self._calls = payload, self, calls

    def stream(self, **kwargs):
        self._calls.append(kwargs)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return _Resp(self._payload)


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    ai._prompt_cache.clear()
    yield
    ai._prompt_cache.clear()


def _install_ai(monkeypatch, payload):
    state = {"calls": []}
    monkeypatch.setattr(ai, "_make_client", lambda api_key: _FakeClient(payload, state["calls"]))
    return state


def _set_key(client):
    assert client.put("/api/settings/api-key", json={"apiKey": "sk-ant-test-0000"}).status_code == 200


@pytest.fixture
def seeded(app):
    conn = sqlite3.connect(app.state.db_path)
    seed_lernbereiche(conn)
    seed_lehrplan_ziele(conn)
    conn.close()
    return app


def _make_class(client, **over):
    body = {"name": "8b", "subject": "Deutsch", "grade": 8, "track": "RS", "weeklyHours": 4}
    body.update(over)
    r = client.post("/api/classes", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_checklist_matches_class_scope(seeded, client, auth):
    cid = _make_class(client, grade=8, track="RS")
    r = client.get("/api/lehrplan/checklist", params={"classId": cid})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["subject"] == "Deutsch" and data["grade"] == 8 and data["track"] == "RS"
    assert len(data["ziele"]) == 4
    assert [z["text"] for z in data["ziele"]][0] == "Entwickeln des Leseverstehens"
    assert len(data["lernbereiche"]) == 6
    assert all(z["checkedAt"] is None for z in data["ziele"])
    assert data["lernbereiche"][0]["richtwertUstd"] is not None


def test_check_toggle_roundtrip(seeded, client, auth):
    cid = _make_class(client)
    lb = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()["lernbereiche"][0]

    r = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "lb", "itemRef": lb["id"], "checked": True})
    assert r.status_code == 200, r.text
    assert r.json()["checked"] is True and r.json()["checkedAt"]

    data = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()
    hit = next(x for x in data["lernbereiche"] if x["id"] == lb["id"])
    assert hit["checkedAt"] is not None

    # Erneut True => idempotent (kein zweiter Datensatz, checkedAt bleibt)
    r2 = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "lb", "itemRef": lb["id"], "checked": True})
    assert r2.json()["checkedAt"] == r.json()["checkedAt"]

    # Abwaehlen
    r3 = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "lb", "itemRef": lb["id"], "checked": False})
    assert r3.json()["checked"] is False and r3.json()["checkedAt"] is None
    data = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()
    assert next(x for x in data["lernbereiche"] if x["id"] == lb["id"])["checkedAt"] is None


def test_check_ziel_and_scoping(seeded, client, auth):
    cid = _make_class(client)
    ziel = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()["ziele"][0]
    r = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "ziel", "itemRef": ziel["id"], "checked": True})
    assert r.status_code == 200 and r.json()["checked"] is True

    # Andere Klasse (anderes Schuljahr / anderer Kurs) startet leer
    cid2 = _make_class(client, name="8c")
    data2 = client.get("/api/lehrplan/checklist", params={"classId": cid2}).json()
    assert all(z["checkedAt"] is None for z in data2["ziele"])


def test_check_rejects_out_of_scope_ref(seeded, client, auth):
    d8 = _make_class(client, name="8b", grade=8, track="RS")
    d7 = _make_class(client, name="7a", grade=7, track="RS")
    # LB aus Klasse 7 gegen Klasse 8 abhaken -> 404
    lb7 = client.get("/api/lehrplan/checklist", params={"classId": d7}).json()["lernbereiche"][0]
    r = client.put("/api/lehrplan/checks", json={
        "classId": d8, "itemType": "lb", "itemRef": lb7["id"], "checked": True})
    assert r.status_code == 404


def test_gemischt_deutsch_falls_back_to_rs(seeded, client, auth):
    cid = _make_class(client, name="8x", grade=8, track="gemischt")
    data = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()
    assert data["trackFallback"] is True
    assert data["classTrack"] == "gemischt"
    assert data["track"] == "RS"
    assert len(data["lernbereiche"]) == 6 and len(data["ziele"]) == 4
    # Abhaken eines angezeigten (RS-)Eintrags funktioniert trotz Klassen-Track 'gemischt'
    lb = data["lernbereiche"][0]
    r = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "lb", "itemRef": lb["id"], "checked": True})
    assert r.status_code == 200 and r.json()["checked"] is True


def test_unknown_class_404(seeded, client, auth):
    assert client.get("/api/lehrplan/checklist", params={"classId": 999999}).status_code == 404
    r = client.put("/api/lehrplan/checks", json={
        "classId": 999999, "itemType": "lb", "itemRef": 1, "checked": True})
    assert r.status_code == 404


def test_bad_item_type_422(seeded, client, auth):
    cid = _make_class(client)
    r = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "quatsch", "itemRef": 1, "checked": True})
    assert r.status_code == 422


def test_requires_auth(seeded, client):
    assert client.get("/api/lehrplan/checklist", params={"classId": 1}).status_code == 401


# ---------- KI-Batch: Feinziele je Lernbereich ----------
_LZ_PAYLOAD = json.dumps({"lernziele": [
    {"anforderung": "Kennen", "text": "Kennen von verschiedenen Lesetechniken",
     "inhalte": ["orientierendes Lesen", "verweilendes Lesen"]},
    {"anforderung": "Beherrschen", "text": "Beherrschen der Interpunktion am Satzende",
     "inhalte": []},
]})


def test_extract_requires_api_key(seeded, client, auth):
    assert client.post("/api/lehrplan/lernziele/extract").status_code == 400


def test_extract_lernziele_batch_and_checklist(seeded, client, auth, monkeypatch):
    st = _install_ai(monkeypatch, _LZ_PAYLOAD)
    _set_key(client)

    r = client.post("/api/lehrplan/lernziele/extract")
    assert r.status_code == 200
    job_id = r.json()["jobId"]

    # BackgroundTasks laufen im TestClient synchron -> Job ist fertig
    status = client.get(f"/api/lehrplan/lernziele/extract/{job_id}").json()
    assert status["status"] == "done", status
    assert status["progress"]["processed"] == status["progress"]["total"] > 0
    assert status["progress"]["failed"] == 0
    assert len(st["calls"]) == status["progress"]["total"]  # ein Call je Lernbereich

    cid = _make_class(client, grade=8, track="RS")
    data = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()
    assert data["lernzieleMissing"] == 0
    lb = data["lernbereiche"][0]
    assert [z["text"] for z in lb["lernziele"]] == [
        "Kennen von verschiedenen Lesetechniken",
        "Beherrschen der Interpunktion am Satzende",
    ]
    assert lb["lernziele"][0]["inhalte"] == "orientierendes Lesen; verweilendes Lesen"
    assert lb["lernziele"][1]["inhalte"] is None

    # abhaken eines Feinziels
    lz = lb["lernziele"][0]
    rr = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "lernziel", "itemRef": lz["id"], "checked": True})
    assert rr.status_code == 200 and rr.json()["checked"] is True
    data2 = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()
    assert data2["lernbereiche"][0]["lernziele"][0]["checkedAt"] is not None


def test_extract_is_idempotent_and_resumes(seeded, client, auth, monkeypatch):
    _install_ai(monkeypatch, _LZ_PAYLOAD)
    _set_key(client)
    j1 = client.post("/api/lehrplan/lernziele/extract").json()["jobId"]
    assert client.get(f"/api/lehrplan/lernziele/extract/{j1}").json()["status"] == "done"
    n1 = None
    # zweiter Lauf: nichts mehr zu tun, keine Dubletten
    st2 = _install_ai(monkeypatch, _LZ_PAYLOAD)
    j2 = client.post("/api/lehrplan/lernziele/extract").json()["jobId"]
    prog = client.get(f"/api/lehrplan/lernziele/extract/{j2}").json()["progress"]
    assert prog["processed"] == prog["total"]
    assert st2["calls"] == []  # kein LB mehr offen -> kein KI-Call

    cid = _make_class(client, grade=7, track="HS")
    lb = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()["lernbereiche"][0]
    assert len(lb["lernziele"]) == 2  # nicht 4
