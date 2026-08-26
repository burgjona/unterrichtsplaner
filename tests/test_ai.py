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
        self.stop_reason = "end_turn"


class _Stream:
    """Fake für client.messages.stream(...) – ai.run() nutzt nur get_final_message()."""

    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._resp


class _FakeClient:
    def __init__(self, payload, calls=None):
        self._payload = payload
        self.messages = self
        self._calls = calls if calls is not None else []

    def stream(self, **kwargs):  # client.messages.stream(...)
        self._calls.append(kwargs)
        return _Stream(_Resp(self._payload))


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


def test_lesson_suggestion_full_fields_in_prompt(client, auth, monkeypatch):
    """M10: Alle Planungsfelder (Titel, Stundentyp, Klasse/Bildungsgang, Datum) landen im Prompt."""
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    payload = json.dumps({
        "title": "Balladen szenisch erschließen",
        "klafki": {"gegenwart": "", "zukunft": "", "exemplarisch": "", "zugang": "", "struktur": ""},
        "meyerPlan": ["gruen"] * 10,
        "phases": [],
    })
    state = _install(monkeypatch, payload)
    _set_key(client)
    r = client.post("/api/ai/lesson-suggestion", json={
        "ideas": "", "title": "Balladen szenisch erschließen", "subject": "Deutsch", "grade": 8,
        "lessonType": "Lehrprobe", "classId": cls["id"], "date": "2026-09-14",
    })
    assert r.status_code == 200, r.text
    prompt = state["calls"][0]["messages"][0]["content"]
    assert "Titel/Thema: Balladen szenisch erschließen" in prompt
    assert "Stundentyp: Lehrprobe" in prompt
    assert "Klasse: 8a" in prompt and "Bildungsgang: RS" in prompt
    assert "Datum der Stunde: 2026-09-14" in prompt


def test_tafelbild_suggestion(client, auth, monkeypatch):
    payload = json.dumps({
        "titel": "Die Ballade",
        "bloecke": [
            {"ueberschrift": "Merkmale", "punkte": ["erzählend", "dramatisch", "lyrisch"], "hervorgehoben": False},
            {"ueberschrift": "", "punkte": ["Ballade = Mischform aus Epik, Lyrik, Dramatik"], "hervorgehoben": True},
        ],
    })
    state = _install(monkeypatch, payload)
    _set_key(client)

    r = client.post("/api/ai/tafelbild", json={"eingabe": "Merkmale der Ballade", "subject": "Deutsch", "grade": 8})
    assert r.status_code == 200, r.text
    body = r.json()["suggestion"]
    assert body["titel"] == "Die Ballade"
    assert body["bloecke"][1]["hervorgehoben"] is True
    prompt = state["calls"][0]["messages"][0]["content"]
    assert "Fach: Deutsch" in prompt and "Klassenstufe: 8" in prompt
    assert "Merkmale der Ballade" in prompt


def test_tafelbild_suggestion_requires_eingabe(client, auth, monkeypatch):
    _install(monkeypatch, "{}")
    _set_key(client)
    r = client.post("/api/ai/tafelbild", json={"eingabe": "  "})
    assert r.status_code == 400
    assert "Tafel" in r.json()["detail"]


def test_lesson_suggestion_requires_ideas_or_title(client, auth, monkeypatch):
    _install(monkeypatch, "{}")
    _set_key(client)
    r = client.post("/api/ai/lesson-suggestion", json={"ideas": "", "subject": "Deutsch"})
    assert r.status_code == 400
    assert "Ideen oder einen Titel" in r.json()["detail"]


def test_lesson_suggestion_foreign_class_404(client, auth, monkeypatch):
    _install(monkeypatch, "{}")
    _set_key(client)
    r = client.post("/api/ai/lesson-suggestion", json={"ideas": "Balladen", "classId": 9999})
    assert r.status_code == 404


def _make_lesson(client):
    return client.post("/api/lessons", json={"title": "Balladen", "subject": "Deutsch", "grade": 8,
                                             "klafki": {"gegenwart": "Alltag"}}).json()


def test_asuv_suggestion_async_job(client, auth, monkeypatch):
    """POST liefert jobId; BackgroundTask (läuft im TestClient nach der Response) schreibt done+suggestion."""
    lesson = _make_lesson(client)
    payload = json.dumps({f: "Text" for f in
                          ["bedingungOrg", "bedingungLern", "bedingungEinordnung", "ziele", "sachanalyse",
                           "quellen", "didaktisch", "reduktion", "methodisch"]})
    _install(monkeypatch, payload)
    _set_key(client)
    r = client.post(f"/api/ai/asuv/{lesson['id']}")
    assert r.status_code == 200, r.text
    job_id = r.json()["jobId"]
    assert isinstance(job_id, int)

    j = client.get(f"/api/ai/jobs/{job_id}")
    assert j.status_code == 200, j.text
    body = j.json()
    assert body["status"] == "done"
    assert body["kind"] == "asuv"
    assert body["result"]["suggestion"]["sachanalyse"] == "Text"
    assert body["result"]["cached"] is False


def test_asuv_requires_api_key_sync(client, auth):
    """Ohne API-Key sofort 400 – es wird kein Job angelegt."""
    lesson = _make_lesson(client)
    r = client.post(f"/api/ai/asuv/{lesson['id']}")
    assert r.status_code == 400
    assert "API-Key" in r.json()["detail"]


def test_asuv_job_error_state(client, auth, monkeypatch):
    """KI liefert kein gültiges JSON -> Job endet mit status=error und Meldung."""
    lesson = _make_lesson(client)
    _install(monkeypatch, "<!DOCTYPE html> kein JSON")
    _set_key(client)
    job_id = client.post(f"/api/ai/asuv/{lesson['id']}").json()["jobId"]
    body = client.get(f"/api/ai/jobs/{job_id}").json()
    assert body["status"] == "error"
    assert "JSON" in body["error"]


def test_ai_job_foreign_user_404(client, auth, app):
    """Job eines fremden Nutzers ist nicht abrufbar (user_id-Scoping)."""
    import sqlite3
    conn = sqlite3.connect(app.state.db_path)
    conn.execute("INSERT INTO users(email, display_name, password_hash) VALUES ('fremd@t.de', 'F', 'hash')")
    other_id = conn.execute("SELECT id FROM users WHERE email='fremd@t.de'").fetchone()[0]
    cur = conn.execute("INSERT INTO ai_jobs(user_id, kind, status) VALUES (?, 'asuv', 'pending')", (other_id,))
    conn.commit()
    job_id = cur.lastrowid
    conn.close()
    r = client.get(f"/api/ai/jobs/{job_id}")
    assert r.status_code == 404


def test_stoffplan_suggestion(client, auth, monkeypatch):
    sy = client.post("/api/school-years", json={"label": "2025/2026", "startDate": "2025-08-11", "endDate": "2026-06-30"}).json()
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    client.post("/api/lernbereiche", json={"subject": "Deutsch", "grade": 8, "track": "RS", "code": "LB1", "title": "Gewusst wie", "richtwertUstd": 15})
    payload = json.dumps({"blocks": [{"code": "LB1", "title": "Gewusst wie", "ustd": 15, "weeks": 5, "note": "Übungsstunde vor LUE"}]})
    _install(monkeypatch, payload)
    _set_key(client)
    r = client.post("/api/ai/stoffplan", json={"schoolYearId": sy["id"], "classId": cls["id"]})
    assert r.status_code == 200, r.text
    job_id = r.json()["jobId"]
    body = client.get(f"/api/ai/jobs/{job_id}").json()
    assert body["status"] == "done"
    assert body["result"]["suggestion"]["blocks"][0]["code"] == "LB1"


def test_sequenzplan_suggestion(client, auth, monkeypatch):
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    plan = client.post("/api/stoff-plans", json={
        "classId": cls["id"], "title": "P",
        "blocks": [{"lbCode": "LB1", "title": "Gewusst wie", "ustd": 15}],
    }).json()
    block_id = plan["blocks"][0]["id"]
    payload = json.dumps({"stunden": [
        {"title": "Einstieg", "grobziel": "Erste Annäherung", "notenarten": []},
        {"title": "Lernkontrolle", "grobziel": "Wissen prüfen", "notenarten": ["lk"]},
    ]})
    _install(monkeypatch, payload)
    _set_key(client)
    r = client.post("/api/ai/sequenzplan", json={"blockId": block_id, "ideas": "Bezug zu Alltagssprache", "wantLk": True})
    assert r.status_code == 200, r.text
    body = client.get(f"/api/ai/jobs/{r.json()['jobId']}").json()
    assert body["status"] == "done", body
    assert body["kind"] == "sequenzplan"
    stunden = body["result"]["suggestion"]["stunden"]
    assert len(stunden) == 2
    assert stunden[1]["notenarten"] == ["lk"]


def test_sequenzplan_truncated_answer_reported_in_job(client, auth, monkeypatch):
    """Abgeschnittene Antwort (max_tokens ausgeschöpft) landet als lesbare Job-Fehlermeldung."""
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    plan = client.post("/api/stoff-plans", json={
        "classId": cls["id"], "title": "P", "blocks": [{"lbCode": "LB1", "title": "X", "ustd": 5}],
    }).json()
    _install(monkeypatch, json.dumps({"stunden": []}))
    _set_key(client)

    def _truncated(*a, **kw):
        raise ai.ResponseTruncated("sequenzplan")

    monkeypatch.setattr(ai, "run", _truncated)
    r = client.post("/api/ai/sequenzplan", json={"blockId": plan["blocks"][0]["id"]})
    body = client.get(f"/api/ai/jobs/{r.json()['jobId']}").json()
    assert body["status"] == "error"
    assert "abgeschnitten" in body["error"]


def test_sequenzplan_retries_once_and_recovers(client, auth, monkeypatch):
    """Erster Call liefert ungültiges JSON (Modell-Aussetzer), zweiter Call gelingt – der Job
    endet trotzdem mit status=done, der Nutzer sieht nichts vom ersten Fehlversuch."""
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    plan = client.post("/api/stoff-plans", json={
        "classId": cls["id"], "title": "P", "blocks": [{"lbCode": "LB1", "title": "X", "ustd": 5}],
    }).json()
    valid_payload = json.dumps({"stunden": [{"title": "Einstieg", "grobziel": "G", "notenarten": []}]})
    responses = iter(["<html>kein JSON</html>", valid_payload])
    calls = []

    class _FlakyClient:
        def __init__(self):
            self.messages = self

        def stream(self, **kwargs):
            calls.append(kwargs)
            return _Stream(_Resp(next(responses)))

    monkeypatch.setattr(ai, "_make_client", lambda api_key: _FlakyClient())
    _set_key(client)
    r = client.post("/api/ai/sequenzplan", json={"blockId": plan["blocks"][0]["id"]})
    body = client.get(f"/api/ai/jobs/{r.json()['jobId']}").json()
    assert body["status"] == "done", body
    assert len(body["result"]["suggestion"]["stunden"]) == 1
    assert len(calls) == 2  # genau ein Retry, kein Endlos-Loop


def test_sequenzplan_no_retry_without_api_key(client, auth, monkeypatch):
    """Fehlender API-Key ist deterministisch – wird nicht wiederholt, Job endet sofort."""
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    plan = client.post("/api/stoff-plans", json={
        "classId": cls["id"], "title": "P", "blocks": [{"lbCode": "LB1", "title": "X", "ustd": 5}],
    }).json()
    _set_key(client)

    def _remove_key(*a, **kw):
        raise ai.NoApiKey()

    monkeypatch.setattr(ai, "run", _remove_key)
    r = client.post("/api/ai/sequenzplan", json={"blockId": plan["blocks"][0]["id"]})
    body = client.get(f"/api/ai/jobs/{r.json()['jobId']}").json()
    assert body["status"] == "error", body
    assert "API-Key" in body["error"]


def test_sequenzplan_empty_result_reported_as_error(client, auth, monkeypatch):
    """Schema-valides, aber leeres Ergebnis ({"stunden": []}) ist kein Erfolg – der Job
    endet mit status=error statt einem irreführenden "0 Stunden erzeugt"."""
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    plan = client.post("/api/stoff-plans", json={
        "classId": cls["id"], "title": "P", "blocks": [{"lbCode": "LB1", "title": "X", "ustd": 5}],
    }).json()
    _install(monkeypatch, json.dumps({"stunden": []}))
    _set_key(client)
    r = client.post("/api/ai/sequenzplan", json={"blockId": plan["blocks"][0]["id"]})
    body = client.get(f"/api/ai/jobs/{r.json()['jobId']}").json()
    assert body["status"] == "error", body
    assert "leer" in body["error"] or "keinen Vorschlag" in body["error"]


def test_stoffplan_empty_result_reported_as_error(client, auth, monkeypatch):
    sy = client.post("/api/school-years", json={"label": "2025/2026", "startDate": "2025-08-11", "endDate": "2026-06-30"}).json()
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    client.post("/api/lernbereiche", json={"subject": "Deutsch", "grade": 8, "track": "RS", "code": "LB1", "title": "Gewusst wie", "richtwertUstd": 15})
    _install(monkeypatch, json.dumps({"blocks": []}))
    _set_key(client)
    r = client.post("/api/ai/stoffplan", json={"schoolYearId": sy["id"], "classId": cls["id"]})
    body = client.get(f"/api/ai/jobs/{r.json()['jobId']}").json()
    assert body["status"] == "error", body


def test_sequenzplan_requires_api_key(client, auth):
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS"}).json()
    plan = client.post("/api/stoff-plans", json={
        "classId": cls["id"], "title": "P", "blocks": [{"lbCode": "LB1", "title": "X", "ustd": 5}],
    }).json()
    r = client.post("/api/ai/sequenzplan", json={"blockId": plan["blocks"][0]["id"]})
    assert r.status_code == 400
    assert "API-Key" in r.json()["detail"]


def test_sequenzplan_foreign_block_rejected(client, auth):
    r = client.post("/api/ai/sequenzplan", json={"blockId": 9999})
    assert r.status_code == 404
