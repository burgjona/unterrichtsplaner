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
