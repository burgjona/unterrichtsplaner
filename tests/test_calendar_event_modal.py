"""U26 – CalendarOut liefert googleEventId + updatedAt (fürs Bearbeiten-Modal:
Google-Badge erkennen, Last-write-wins nachvollziehen)."""
import sqlite3


def test_calendar_out_exposes_google_and_updated_fields(client, auth):
    e = client.post("/api/calendar", json={"title": "Elternabend", "entryDate": "2026-03-01"}).json()
    assert "googleEventId" in e and e["googleEventId"] is None
    assert "updatedAt" in e and e["updatedAt"]            # bei Create gesetzt (datetime('now'))

    got = client.get(f"/api/calendar/{e['id']}").json()
    assert got["googleEventId"] is None and got["updatedAt"]


def test_calendar_update_via_modal_fields(client, auth):
    e = client.post("/api/calendar", json={"title": "Projekt", "entryDate": "2026-03-05",
                                           "allDay": False, "startTime": "08:00", "endTime": "09:30"}).json()
    upd = client.put(f"/api/calendar/{e['id']}", json={
        "title": "Projekt verschoben", "entryDate": "2026-03-06", "endDate": None,
        "allDay": True, "startTime": None, "endTime": None,
        "entryType": "normal", "categoryId": None, "classId": None, "isFixed": True,
    }).json()
    assert upd["title"] == "Projekt verschoben" and upd["entryDate"] == "2026-03-06"
    assert upd["allDay"] is True and upd["startTime"] is None and upd["isFixed"] is True
    assert upd["updatedAt"] is not None


def test_calendar_out_reflects_google_link(client, auth, app):
    e = client.post("/api/calendar", json={"title": "Sync-Termin", "entryDate": "2026-03-02"}).json()
    conn = sqlite3.connect(app.state.db_path)
    conn.execute("UPDATE calendar_entries SET google_event_id='g_abc123' WHERE id=?", (e["id"],))
    conn.commit()
    conn.close()
    got = client.get(f"/api/calendar/{e['id']}").json()
    assert got["googleEventId"] == "g_abc123"
