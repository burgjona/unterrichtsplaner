"""U13 – Archiv-Infrastruktur: To-Dos soft-archivieren/wiederherstellen/endgültig löschen,
Klassen soft-archivieren/wiederherstellen."""


def test_todo_archive_restore_and_hard_delete(client, auth):
    t = client.post("/api/todos", json={"text": "Kopien für 7c"})
    assert t.status_code == 201
    tid = t.json()["id"]
    assert t.json()["archivedAt"] is None

    # Archivieren: verschwindet aus der Standardliste, taucht im Archiv auf.
    a = client.post(f"/api/todos/{tid}/archive")
    assert a.status_code == 200 and a.json()["archivedAt"] is not None
    assert client.get("/api/todos").json() == []
    archived = client.get("/api/todos?archived=true").json()
    assert [x["id"] for x in archived] == [tid]

    # Wiederherstellen: wieder in der Standardliste, weg aus dem Archiv.
    r = client.post(f"/api/todos/{tid}/restore")
    assert r.status_code == 200 and r.json()["archivedAt"] is None
    assert [x["id"] for x in client.get("/api/todos").json()] == [tid]
    assert client.get("/api/todos?archived=true").json() == []

    # Endgültig löschen (aus dem Archiv heraus).
    client.post(f"/api/todos/{tid}/archive")
    assert client.delete(f"/api/todos/{tid}").status_code == 204
    assert client.get("/api/todos").json() == []
    assert client.get("/api/todos?archived=true").json() == []


def test_todo_archive_missing_is_404(client, auth):
    assert client.post("/api/todos/999/archive").status_code == 404
    assert client.post("/api/todos/999/restore").status_code == 404


def test_class_soft_archive_and_restore(client, auth):
    c = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8}).json()
    cid = c["id"]
    assert c["archivedAt"] is None

    # DELETE ohne hard = Soft-Archiv.
    assert client.delete(f"/api/classes/{cid}").status_code == 204
    assert client.get("/api/classes").json() == []
    all_ = client.get("/api/classes?includeArchived=true").json()
    assert len(all_) == 1 and all_[0]["archivedAt"] is not None

    # Wiederherstellen.
    r = client.post(f"/api/classes/{cid}/restore")
    assert r.status_code == 200 and r.json()["archivedAt"] is None
    assert [x["id"] for x in client.get("/api/classes").json()] == [cid]


def test_class_restore_missing_is_404(client, auth):
    assert client.post("/api/classes/999/restore").status_code == 404


def test_archiv_endpoints_require_login(client):
    assert client.post("/api/todos/1/archive").status_code == 401
    assert client.post("/api/classes/1/restore").status_code == 401
