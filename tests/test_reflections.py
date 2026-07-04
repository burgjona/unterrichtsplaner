"""Reflexionen: erfassen, Journal, offene Reflexionen, überspringen."""


def _make_lesson(client, title="Balladen"):
    return client.post("/api/lessons", json={"title": title, "subject": "Deutsch"}).json()


def test_create_reflection_and_summary(client, auth):
    lesson = _make_lesson(client)
    r = client.post("/api/reflections", json={
        "lessonId": lesson["id"],
        "meyerIst": ["gruen", "gruen", "gelb", "rot", "gruen",
                     "gruen", "gelb", "gruen", "gruen", "gruen"],
        "text": "Standbild hat gut funktioniert."})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ampelSummary"] == "7 grün / 2 gelb / 1 rot"
    assert body["lessonTitle"] == "Balladen"
    assert body["meyerIst"][3] == "rot"


def test_open_reflections_flow(client, auth):
    l1 = _make_lesson(client, "Stunde A")
    l2 = _make_lesson(client, "Stunde B")
    open_ids = [o["lessonId"] for o in client.get("/api/reflections/open").json()]
    assert l1["id"] in open_ids and l2["id"] in open_ids

    # Reflexion zu A -> A verschwindet aus offen
    client.post("/api/reflections", json={"lessonId": l1["id"], "meyerIst": ["gruen"] * 10})
    open_ids = [o["lessonId"] for o in client.get("/api/reflections/open").json()]
    assert l1["id"] not in open_ids and l2["id"] in open_ids

    # B überspringen -> auch weg
    assert client.post("/api/reflections/skip", json={"lessonId": l2["id"]}).status_code == 204
    open_ids = [o["lessonId"] for o in client.get("/api/reflections/open").json()]
    assert l2["id"] not in open_ids


def test_journal_lists_newest_first(client, auth):
    lesson = _make_lesson(client)
    client.post("/api/reflections", json={"lessonId": lesson["id"], "text": "erste"})
    client.post("/api/reflections", json={"lessonId": lesson["id"], "text": "zweite"})
    journal = client.get("/api/reflections").json()
    assert journal[0]["text"] == "zweite"  # DESC


def test_reflection_requires_own_lesson(client, auth):
    assert client.post("/api/reflections", json={"lessonId": 99999}).status_code == 404
