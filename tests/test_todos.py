"""To-dos: anlegen, auflisten, abhaken, löschen."""


def test_todo_lifecycle(client, auth):
    t = client.post("/api/todos", json={"text": "Kopien für 7c vorbereiten"})
    assert t.status_code == 201
    tid = t.json()["id"]
    assert t.json()["source"] == "manuell" and t.json()["done"] is False

    done = client.put(f"/api/todos/{tid}", json={"done": True}).json()
    assert done["done"] is True

    assert client.get("/api/todos").json()[0]["id"] == tid
    assert client.delete(f"/api/todos/{tid}").status_code == 204
    assert client.get("/api/todos").json() == []


def test_todo_rejects_bad_source(client, auth):
    assert client.post("/api/todos", json={"text": "x", "source": "quatsch"}).status_code == 400


def test_todos_require_login(client):
    assert client.get("/api/todos").status_code == 401


def test_hefter_todo_dedup_by_lesson(client, auth):
    les = client.post("/api/lessons", json={"title": "Ballade", "subject": "Deutsch", "grade": 8}).json()
    payload = {"text": "Heftereintrag nachpflegen: Ballade", "source": "system", "hefterLessonId": les["id"]}
    a = client.post("/api/todos", json=payload)
    assert a.status_code == 201 and a.json()["hefterLessonId"] == les["id"]
    # zweite Anlage für dieselbe Stunde ist idempotent, kein 500
    b = client.post("/api/todos", json=payload)
    assert b.status_code == 201 and b.json()["id"] == a.json()["id"]


def test_todo_kann_an_stunde_haengen(client, auth):
    """Planungs-To-dos aus der Unterrichtsplanung hängen an der Stunde (Migration 065)."""
    les = client.post("/api/lessons", json={"title": "Kurzgeschichte", "subject": "Deutsch", "grade": 8}).json()
    a = client.post("/api/todos", json={"text": "AB kopieren", "lessonId": les["id"]})
    assert a.status_code == 201 and a.json()["lessonId"] == les["id"]
    # Mehrere To-dos zur selben Stunde sind erlaubt – anders als beim Hefter-To-do.
    b = client.post("/api/todos", json={"text": "Hörbeispiel suchen", "lessonId": les["id"]})
    assert b.status_code == 201 and b.json()["id"] != a.json()["id"]
    assert {t["id"] for t in client.get("/api/todos").json()} == {a.json()["id"], b.json()["id"]}


def test_todo_ohne_stunde_bleibt_moeglich(client, auth):
    assert client.post("/api/todos", json={"text": "Elternbrief"}).json()["lessonId"] is None
