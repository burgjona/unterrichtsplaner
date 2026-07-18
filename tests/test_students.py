"""Schüler-Namensliste je Klasse (U14): CRUD, Bulk, Nutzer-Scoping."""


def _make_class(client, auth, name="8a"):
    r = client.post("/api/classes",
                    json={"name": name, "subject": "Deutsch", "grade": 8, "track": "RS"},
                    headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_student_lifecycle(client, auth):
    cid = _make_class(client, auth)

    s = client.post(f"/api/classes/{cid}/students", json={"name": "Änne Müller"}, headers=auth)
    assert s.status_code == 201
    body = s.json()
    assert body["name"] == "Änne Müller"
    assert body["classId"] == cid          # camelCase
    assert body["sortOrder"] == 0
    sid = body["id"]

    lst = client.get(f"/api/classes/{cid}/students", headers=auth).json()
    assert [x["id"] for x in lst] == [sid]

    up = client.put(f"/api/students/{sid}", json={"name": "Änne Schmidt", "sortOrder": 5}, headers=auth)
    assert up.status_code == 200
    assert up.json()["name"] == "Änne Schmidt" and up.json()["sortOrder"] == 5

    assert client.delete(f"/api/students/{sid}", headers=auth).status_code == 204
    assert client.get(f"/api/classes/{cid}/students", headers=auth).json() == []


def test_student_bulk_and_order(client, auth):
    cid = _make_class(client, auth, "9b")
    r = client.post(f"/api/classes/{cid}/students/bulk",
                    json={"names": ["Ben", "  ", "Clara", "Dora"]}, headers=auth)
    assert r.status_code == 201
    names = [x["name"] for x in r.json()]
    assert names == ["Ben", "Clara", "Dora"]     # Leerzeilen verworfen
    orders = [x["sortOrder"] for x in r.json()]
    assert orders == sorted(orders)              # aufsteigend, kollisionsfrei


def test_students_require_login(client):
    assert client.get("/api/classes/1/students").status_code == 401


def test_students_foreign_class_404(client, auth):
    # Nicht existierende Klasse
    assert client.get("/api/classes/99999/students", headers=auth).status_code == 404
    assert client.post("/api/classes/99999/students", json={"name": "X"}, headers=auth).status_code == 404


def test_student_foreign_id_404(client, auth):
    cid = _make_class(client, auth, "10a")
    sid = client.post(f"/api/classes/{cid}/students", json={"name": "Emil"}, headers=auth).json()["id"]
    # Fremd-ID existiert nicht → 404
    assert client.put(f"/api/students/{sid + 999}", json={"name": "Y"}, headers=auth).status_code == 404
    assert client.delete(f"/api/students/{sid + 999}", headers=auth).status_code == 404
