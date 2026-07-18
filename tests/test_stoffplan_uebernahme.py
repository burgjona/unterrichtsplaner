"""U16 – Wiederverwendung: Stoffplan für Parallelklasse duplizieren / auf neues
Schuljahr übernehmen. KI wird gemockt (ai._make_client), nie echte Calls.
"""
import json

from src.lib import ai


# ---- Fake Anthropic client (Muster tests/test_ai.py) ----
class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Usage:
    input_tokens = 100
    output_tokens = 50
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

    def create(self, **kwargs):
        return _Resp(self._payload)


def _class(client, name="7a", subject="Deutsch", grade=7, hours=2):
    r = client.post("/api/classes",
                    json={"name": name, "subject": subject, "grade": grade, "weeklyHours": hours})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _year(client, label="2025/26", start="2025-08-01", end="2026-07-31"):
    r = client.post("/api/school-years",
                    json={"label": label, "startDate": start, "endDate": end})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _blocks():
    return [
        {"lbCode": "LB3", "title": "Lesen", "ustd": 20,
         "startDate": "2025-09-01", "endDate": "2025-10-10"},
        {"lbCode": "LB4", "title": "Schreiben", "ustd": 25,
         "startDate": "2025-10-20", "endDate": "2025-12-15"},
    ]


def _plan(client, cid, syid=None, title="Stoffplan 7a"):
    body = {"classId": cid, "title": title, "blocks": _blocks()}
    if syid is not None:
        body["schoolYearId"] = syid
    r = client.post("/api/stoff-plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_duplicate_kopie_copies_blocks_verbatim(client, auth):
    cid_a, cid_b = _class(client, "7a"), _class(client, "7b")
    syid = _year(client)
    pid = _plan(client, cid_a, syid)
    r = client.post(f"/api/stoff-plans/{pid}/duplicate",
                    json={"targetClassId": cid_b, "mode": "kopie"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["classId"] == cid_b
    assert new["status"] == "entwurf"
    assert new["schoolYearId"] == syid          # ohne targetSchoolYearId → Quell-Schuljahr
    assert [b["lbCode"] for b in new["blocks"]] == ["LB3", "LB4"]
    # 1:1 inkl. Datum
    assert new["blocks"][0]["startDate"] == "2025-09-01"
    assert new["blocks"][1]["endDate"] == "2025-12-15"
    # neuer, eigenständiger Plan
    assert new["id"] != pid


def test_duplicate_deterministic_recomputes_dates(client, auth):
    cid_a, cid_b = _class(client, "7a"), _class(client, "7b")
    syid = _year(client)
    pid = _plan(client, cid_a, syid)
    r = client.post(f"/api/stoff-plans/{pid}/duplicate",
                    json={"targetClassId": cid_b, "mode": "deterministisch"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert [b["lbCode"] for b in new["blocks"]] == ["LB3", "LB4"]
    # Zeiträume neu berechnet, geordnet und (bis auf Wochen-Snap) im Zielschuljahr.
    # teaching_weeks snappt auf den Montag der Startwoche → Start kann wenige Tage
    # vor dem 01.08. liegen; Ende bleibt innerhalb der Schuljahresgrenze.
    for b in new["blocks"]:
        assert b["startDate"] is not None and b["endDate"] is not None
        assert b["startDate"] <= b["endDate"]
        assert "2025-07-01" <= b["startDate"] and b["endDate"] <= "2026-07-31"


def test_duplicate_to_new_school_year(client, auth):
    cid = _class(client, "7a")
    sy1 = _year(client, "2024/25", "2024-08-01", "2025-07-31")
    sy2 = _year(client, "2025/26", "2025-08-01", "2026-07-31")
    pid = _plan(client, cid, sy1)
    r = client.post(f"/api/stoff-plans/{pid}/duplicate",
                    json={"targetClassId": cid, "targetSchoolYearId": sy2,
                          "mode": "deterministisch"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["schoolYearId"] == sy2
    # Blöcke sind ins neue Schuljahr gewandert (nicht mehr im alten 2024/25).
    for b in new["blocks"]:
        assert "2025-07-01" <= b["startDate"] and b["endDate"] <= "2026-07-31"


def test_ki_falls_back_to_deterministic_without_key(client, auth):
    # Kein API-Key hinterlegt → mode 'ki' darf NICHT 500, sondern deterministisch übernehmen.
    cid_a, cid_b = _class(client, "7a"), _class(client, "7b")
    syid = _year(client)
    pid = _plan(client, cid_a, syid)
    r = client.post(f"/api/stoff-plans/{pid}/duplicate",
                    json={"targetClassId": cid_b, "mode": "ki"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert len(new["blocks"]) == 2
    for b in new["blocks"]:
        assert b["startDate"] is not None          # deterministisch berechnet


def test_ki_uses_model_blocks_when_key_present(client, auth, monkeypatch):
    cid_a, cid_b = _class(client, "7a"), _class(client, "7b")
    syid = _year(client)
    pid = _plan(client, cid_a, syid)
    assert client.put("/api/settings/api-key",
                      json={"apiKey": "sk-ant-test-0000"}).status_code == 200
    ai._prompt_cache.clear()
    payload = json.dumps({"blocks": [
        {"code": "LB3", "title": "Lesen (KI)", "ustd": 18,
         "startDate": "2025-09-08", "endDate": "2025-10-17", "note": "angepasst"},
    ]})
    monkeypatch.setattr(ai, "_make_client", lambda api_key: _FakeClient(payload))
    r = client.post(f"/api/stoff-plans/{pid}/duplicate",
                    json={"targetClassId": cid_b, "mode": "ki"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert len(new["blocks"]) == 1
    assert new["blocks"][0]["title"] == "Lesen (KI)"
    assert new["blocks"][0]["startDate"] == "2025-09-08"
    assert new["blocks"][0]["conflictNote"] == "angepasst"
    ai._prompt_cache.clear()


def test_duplicate_foreign_target_class_rejected(client, auth):
    cid = _class(client, "7a")
    pid = _plan(client, cid)
    r = client.post(f"/api/stoff-plans/{pid}/duplicate",
                    json={"targetClassId": 9999, "mode": "kopie"})
    assert r.status_code == 404


def test_duplicate_unknown_plan_404(client, auth):
    cid = _class(client, "7a")
    r = client.post("/api/stoff-plans/9999/duplicate",
                    json={"targetClassId": cid, "mode": "kopie"})
    assert r.status_code == 404


def test_duplicate_invalid_mode_422(client, auth):
    cid = _class(client, "7a")
    pid = _plan(client, cid)
    r = client.post(f"/api/stoff-plans/{pid}/duplicate",
                    json={"targetClassId": cid, "mode": "quatsch"})
    assert r.status_code == 422


def test_duplicate_requires_login(client):
    assert client.post("/api/stoff-plans/1/duplicate",
                       json={"targetClassId": 1, "mode": "kopie"}).status_code == 401
