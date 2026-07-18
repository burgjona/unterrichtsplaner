"""U11 Kalender-Kern: Zeitmodell (Uhrzeit/Enddatum/ganztägig), Kategorien, klassenlose Termine."""


def test_calendar_time_and_multiday_fields(client, auth):
    e = client.post("/api/calendar", json={
        "title": "Projektwoche", "entryDate": "2025-09-15", "endDate": "2025-09-19",
        "allDay": False, "startTime": "08:00", "endTime": "13:15",
    }).json()
    assert e["endDate"] == "2025-09-19"
    assert e["allDay"] is False
    assert e["startTime"] == "08:00" and e["endTime"] == "13:15"

    got = client.get(f"/api/calendar/{e['id']}").json()
    assert got["startTime"] == "08:00" and got["endDate"] == "2025-09-19"

    upd = client.put(f"/api/calendar/{e['id']}", json={"allDay": True, "endTime": "14:00"}).json()
    assert upd["allDay"] is True and upd["endTime"] == "14:00"


def test_calendar_backwards_compatible_defaults(client, auth):
    e = client.post("/api/calendar", json={"title": "Elternabend", "entryDate": "2025-10-01"}).json()
    assert e["allDay"] is True
    assert e["endDate"] is None and e["startTime"] is None and e["endTime"] is None
    assert e["categoryId"] is None


def test_calendar_categories_seeded_and_crud(client, auth):
    cats = client.get("/api/calendar-categories").json()
    names = [c["name"] for c in cats]
    assert "Organisatorisch" in names
    assert "Leistungsüberprüfung" in names
    assert "Unterricht/Lernbereich" in names

    created = client.post("/api/calendar-categories", json={"name": "Elternabend", "color": "#7c3aed"})
    assert created.status_code == 201
    cid = created.json()["id"]

    upd = client.put(f"/api/calendar-categories/{cid}", json={"name": "Elterngespräch"}).json()
    assert upd["name"] == "Elterngespräch"

    # Termin mit Kategorie
    e = client.post("/api/calendar", json={"title": "Gespräch", "entryDate": "2025-11-05", "categoryId": cid}).json()
    assert e["categoryId"] == cid

    # Kategorie löschen -> Termin behält seine Existenz, categoryId wird NULL (ON DELETE SET NULL)
    assert client.delete(f"/api/calendar-categories/{cid}").status_code == 204
    assert client.get(f"/api/calendar/{e['id']}").json()["categoryId"] is None


def test_calendar_rejects_unknown_category(client, auth):
    r = client.post("/api/calendar", json={"title": "X", "entryDate": "2025-11-05", "categoryId": 99999})
    assert r.status_code == 400


def test_classless_entry_visible(client, auth):
    e = client.post("/api/calendar", json={"title": "Konferenz", "entryDate": "2025-12-01"}).json()
    assert e["classId"] is None
    ids = [x["id"] for x in client.get("/api/calendar").json()]
    assert e["id"] in ids
