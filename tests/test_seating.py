"""U18: Sitzplan – CRUD, PDF-Export, KI-Anordnung (Anthropic-Client gemockt)."""
import json

from src.lib import ai


def _class_with_students(client):
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8}).json()
    client.post(f"/api/classes/{cls['id']}/students/bulk",
                json={"names": ["Anna Müller", "Ben Groß", "Lisa Öztürk", "Max Weiß"]})
    return cls


def _layout(students):
    # zwei Schüler platzieren
    return {"seats": [
        {"row": 0, "col": 0, "studentId": students[0]["id"], "name": students[0]["name"]},
        {"row": 0, "col": 1, "studentId": students[1]["id"], "name": students[1]["name"]},
    ]}


def test_crud_and_camelcase(client, auth):
    cls = _class_with_students(client)
    students = client.get(f"/api/classes/{cls['id']}/students").json()
    body = {"name": "Standardplan", "rows": 3, "cols": 4, "layoutJson": _layout(students)}
    r = client.post(f"/api/classes/{cls['id']}/seat-plans", json=body)
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["classId"] == cls["id"]
    assert plan["rows"] == 3 and plan["cols"] == 4
    assert plan["layoutJson"]["seats"][0]["studentId"] == students[0]["id"]
    assert plan["layoutJson"]["seats"][0]["name"] == "Anna Müller"   # Umlaut erhalten

    # Liste
    lst = client.get(f"/api/classes/{cls['id']}/seat-plans").json()
    assert len(lst) == 1 and lst[0]["id"] == plan["id"]

    # Einzeln
    got = client.get(f"/api/seat-plans/{plan['id']}").json()
    assert got["name"] == "Standardplan"

    # Update
    upd = client.put(f"/api/seat-plans/{plan['id']}",
                     json={"name": "Gruppenplan", "layoutJson": {"seats": [
                         {"row": 1, "col": 2, "studentId": students[2]["id"], "name": students[2]["name"]}]}}).json()
    assert upd["name"] == "Gruppenplan"
    assert len(upd["layoutJson"]["seats"]) == 1
    assert upd["layoutJson"]["seats"][0]["name"] == "Lisa Öztürk"

    # Delete
    d = client.delete(f"/api/seat-plans/{plan['id']}")
    assert d.status_code == 204
    assert client.get(f"/api/seat-plans/{plan['id']}").status_code == 404


def test_foreign_and_missing_404(client, auth):
    assert client.get("/api/seat-plans/9999").status_code == 404
    assert client.get("/api/classes/9999/seat-plans").status_code == 404
    r = client.post("/api/classes/9999/seat-plans",
                    json={"name": "X", "rows": 2, "cols": 2, "layoutJson": {"seats": []}})
    assert r.status_code == 404


def test_export_pdf(client, auth):
    cls = _class_with_students(client)
    students = client.get(f"/api/classes/{cls['id']}/students").json()
    plan = client.post(f"/api/classes/{cls['id']}/seat-plans",
                       json={"name": "Plan Öl", "rows": 2, "cols": 3, "layoutJson": _layout(students)}).json()
    r = client.get(f"/api/seat-plans/{plan['id']}/export?format=pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 1000
    cd = r.headers["content-disposition"]
    assert "filename*=UTF-8''" in cd and ".pdf" in cd


# ---- KI-Anordnung (gemockt) ----
class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Usage:
    input_tokens = 500
    output_tokens = 200
    cache_read_input_tokens = 0


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


def _install(monkeypatch, payload):
    ai._prompt_cache.clear()
    state = {"calls": []}
    monkeypatch.setattr(ai, "_make_client", lambda key: _FakeClient(payload, state["calls"]))
    return state


def _set_key(client):
    client.put("/api/settings/api-key", json={"apiKey": "sk-ant-test-0000"})


def test_ai_arrange_requires_key(client, auth):
    cls = _class_with_students(client)
    r = client.post(f"/api/classes/{cls['id']}/seat-plans/ai-arrange",
                    json={"rows": 2, "cols": 3, "description": "Lisa nach vorn"})
    assert r.status_code == 400
    assert "API-Key" in r.json()["detail"]


def test_ai_arrange_enriches_and_filters(client, auth, monkeypatch):
    cls = _class_with_students(client)
    students = client.get(f"/api/classes/{cls['id']}/students").json()
    payload = json.dumps({"seats": [
        {"row": 0, "col": 0, "name": "Lisa Öztürk"},
        {"row": 0, "col": 1, "name": "Anna Müller"},
        {"row": 9, "col": 9, "name": "Ben Groß"},        # außerhalb Raster -> verworfen
        {"row": 1, "col": 0, "name": "Unbekannt"},       # kein bekannter Schüler -> verworfen
    ]})
    _install(monkeypatch, payload)
    _set_key(client)
    r = client.post(f"/api/classes/{cls['id']}/seat-plans/ai-arrange",
                    json={"rows": 2, "cols": 3, "description": "Lisa nach vorn"})
    assert r.status_code == 200, r.text
    seats = r.json()["suggestion"]["seats"]
    assert len(seats) == 2
    by_name = {s["name"]: s for s in seats}
    assert by_name["Lisa Öztürk"]["studentId"] == next(s["id"] for s in students if s["name"] == "Lisa Öztürk")
    assert all("studentId" in s for s in seats)


def test_ai_arrange_no_students_400(client, auth, monkeypatch):
    cls = client.post("/api/classes", json={"name": "9b", "subject": "WTH", "grade": 9}).json()
    _install(monkeypatch, "{}")
    _set_key(client)
    r = client.post(f"/api/classes/{cls['id']}/seat-plans/ai-arrange",
                    json={"rows": 2, "cols": 2, "description": "egal"})
    assert r.status_code == 400
    assert "Schüler" in r.json()["detail"]
