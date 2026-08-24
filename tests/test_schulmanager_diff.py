"""M1b: Soll/Ist-Abgleich Schulmanager-Feed <-> U27-Stundenplan / Planungskalender.

Baut die Fixtures über die bestehenden Stundenplan-/Klassen-/Kalender-Endpunkte auf
(wie test_stundenplan.py) und ruft compute_changes() dann direkt mit einer eigenen
DB-Connection auf demselben Test-DB-File auf.
"""
import datetime

from src.db import connect
from src.lib.schulmanager_diff import compute_changes

STUNDENPLAN = "/api/stundenplan"


def _this_monday() -> datetime.date:
    today = datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())


def _seed(client):
    kinds = client.get(f"{STUNDENPLAN}/kinds").json()
    slots = client.get(f"{STUNDENPLAN}/slots").json()
    plans = client.get(f"{STUNDENPLAN}/plans").json()
    return kinds, slots, plans


def _lesson_event(uid_kind, uid_id, iso_date, start_time, end_time, summary, location=None):
    return {
        "uid": f"{uid_kind}_{uid_id}_{iso_date}@schulmanager-online.de",
        "kind": uid_kind,
        "summary": summary,
        "start": f"{iso_date}T{start_time}",
        "end": f"{iso_date}T{end_time}",
        "all_day": False,
        "location": location,
        "description": None,
    }


def _conn(client):
    return connect(client.app.state.db_path)


# ---------------------------------------------------------------- Unterricht
def test_matching_regular_lesson_produces_no_change(client, auth, user_id):
    kinds, slots, plans = _seed(client)
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8}).json()
    slot = slots[1]
    client.post(f"{STUNDENPLAN}/entries", json={
        "planId": plans[0]["id"], "slotId": slot["id"], "kindId": kinds[0]["id"],
        "classId": cls["id"], "weekday": 0,
    })
    monday = _this_monday().isoformat()

    ev = _lesson_event("regularLesson", 1, monday, slot["startTime"], slot["endTime"], "DE (8a)")
    changes = compute_changes(_conn(client), user_id, [ev])
    assert changes["vertretung"] == []
    assert changes["ausfall"] == []


def test_special_lesson_always_flagged_as_vertretung(client, auth, user_id):
    kinds, slots, plans = _seed(client)
    cls = client.post("/api/classes", json={"name": "8a", "subject": "WTH", "grade": 8}).json()
    slot = slots[1]
    client.post(f"{STUNDENPLAN}/entries", json={
        "planId": plans[0]["id"], "slotId": slot["id"], "kindId": kinds[0]["id"],
        "classId": cls["id"], "weekday": 0,
    })
    monday = _this_monday().isoformat()

    ev = _lesson_event("specialLesson", 9, monday, slot["startTime"], slot["endTime"], "❇️ WTH-8a-1 (8a)")
    changes = compute_changes(_conn(client), user_id, [ev])
    assert len(changes["vertretung"]) == 1
    v = changes["vertretung"][0]
    assert v["actual"]["title"] == "❇️ WTH-8a-1 (8a)"
    assert v["expected"]["title"].endswith("WTH")
    assert v["class_id"] == cls["id"]  # fürs Frontend: "Ausarbeiten" öffnet den Editor für diese Klasse


def test_class_mismatch_flagged_as_vertretung(client, auth, user_id):
    kinds, slots, plans = _seed(client)
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8}).json()
    slot = slots[1]
    client.post(f"{STUNDENPLAN}/entries", json={
        "planId": plans[0]["id"], "slotId": slot["id"], "kindId": kinds[0]["id"],
        "classId": cls["id"], "weekday": 0,
    })
    monday = _this_monday().isoformat()

    # Feed zeigt eine andere Klasse (9a statt 8a) im selben Slot.
    ev = _lesson_event("regularLesson", 2, monday, slot["startTime"], slot["endTime"], "DE (9a)")
    changes = compute_changes(_conn(client), user_id, [ev])
    assert len(changes["vertretung"]) == 1


def test_missing_lesson_flagged_as_ausfall(client, auth, user_id):
    kinds, slots, plans = _seed(client)
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8}).json()
    slot_a, slot_b = slots[1], slots[3]
    client.post(f"{STUNDENPLAN}/entries", json={
        "planId": plans[0]["id"], "slotId": slot_a["id"], "kindId": kinds[0]["id"],
        "classId": cls["id"], "weekday": 0,
    })
    client.post(f"{STUNDENPLAN}/entries", json={
        "planId": plans[0]["id"], "slotId": slot_b["id"], "kindId": kinds[0]["id"],
        "classId": cls["id"], "weekday": 0,
    })
    monday = _this_monday().isoformat()

    # Der Feed deckt beide Slots ab (Fenster), zeigt aber nur slot_a -> slot_b fehlt = Ausfall.
    ev_a = _lesson_event("regularLesson", 1, monday, slot_a["startTime"], slot_a["endTime"], "DE (8a)")
    changes = compute_changes(_conn(client), user_id, [ev_a])
    assert changes["vertretung"] == []
    assert len(changes["ausfall"]) == 1
    assert changes["ausfall"][0]["start"] == slot_b["startTime"]


def test_existing_override_suppresses_flag(client, auth, user_id):
    kinds, slots, plans = _seed(client)
    cls = client.post("/api/classes", json={"name": "8a", "subject": "WTH", "grade": 8}).json()
    slot = slots[1]
    monday = _this_monday().isoformat()

    # Vertretung wurde schon manuell erfasst (U30, timetable_overrides).
    client.post(f"{STUNDENPLAN}/overrides", json={
        "date": monday, "slotId": slot["id"], "kindId": kinds[0]["id"], "classId": cls["id"],
    })

    ev = _lesson_event("specialLesson", 9, monday, slot["startTime"], slot["endTime"], "❇️ Sonderthema (8a)")
    changes = compute_changes(_conn(client), user_id, [ev])
    assert changes["vertretung"] == []
    assert changes["ausfall"] == []


def test_holiday_suppresses_ausfall(client, auth, user_id):
    kinds, slots, plans = _seed(client)
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8}).json()
    slot = slots[1]
    client.post(f"{STUNDENPLAN}/entries", json={
        "planId": plans[0]["id"], "slotId": slot["id"], "kindId": kinds[0]["id"],
        "classId": cls["id"], "weekday": 0,
    })
    monday = _this_monday().isoformat()

    # Ferien über die ganze Woche eintragen -> Ausfall wird unterdrückt.
    year = client.post("/api/school-years", json={
        "label": "Testjahr", "startDate": f"{monday[:4]}-08-01", "endDate": f"{int(monday[:4]) + 1}-07-31",
    })
    school_year_id = year.json()["id"]
    conn = _conn(client)
    conn.execute(
        "INSERT INTO school_dates (user_id, school_year_id, kind, name, start_date, end_date) "
        "VALUES (?, ?, 'ferien', 'Testferien', ?, ?)",
        (user_id, school_year_id, monday, monday),
    )
    conn.commit()

    # Feed liefert für diese Woche gar keine Unterrichtsstunde (leer) -> ohne Ferien wäre das Ausfall.
    other_monday_slot_ev = []  # kein Event -> lessons-Liste leer -> compute_changes prüft Ausfall nicht mal
    # Deshalb: ein Event an einem ANDEREN Tag derselben Woche, damit die Woche überhaupt aufgelöst wird.
    tuesday = (datetime.date.fromisoformat(monday) + datetime.timedelta(days=1)).isoformat()
    dummy = _lesson_event("regularLesson", 5, tuesday, slot["startTime"], slot["endTime"], "XX (zz)")
    changes = compute_changes(_conn(client), user_id, [dummy])
    assert changes["ausfall"] == []  # Montag ist Ferien -> keine Ausfall-Meldung für den Montags-Slot


# ---------------------------------------------------------------- Aufsicht
def test_new_supervision_flagged(client, auth, user_id):
    monday = _this_monday().isoformat()
    ev = _lesson_event("supervision", 1, monday, "09:20", "09:35", "Aufsicht: Ebene 1", "Ebene 1: Cafeteria")
    changes = compute_changes(_conn(client), user_id, [ev])
    assert len(changes["aufsicht_neu"]) == 1


def test_matching_supervision_not_flagged(client, auth, user_id):
    monday = _this_monday().isoformat()
    client.post("/api/calendar", json={
        "title": "Aufsicht: Ebene 1", "entryDate": monday, "startTime": "09:20", "endTime": "09:35",
        "allDay": False, "room": "Ebene 1: Cafeteria",
    })
    ev = _lesson_event("supervision", 1, monday, "09:20", "09:35", "Aufsicht: Ebene 1", "Ebene 1: Cafeteria")
    changes = compute_changes(_conn(client), user_id, [ev])
    assert changes["aufsicht_neu"] == []
    assert changes["aufsicht_geaendert"] == []


def test_supervision_room_change_flagged(client, auth, user_id):
    monday = _this_monday().isoformat()
    client.post("/api/calendar", json={
        "title": "Aufsicht: Ebene 1", "entryDate": monday, "startTime": "09:20", "endTime": "09:35",
        "allDay": False, "room": "Ebene 2: Turnhalle",
    })
    ev = _lesson_event("supervision", 1, monday, "09:20", "09:35", "Aufsicht: Ebene 1", "Ebene 1: Cafeteria")
    changes = compute_changes(_conn(client), user_id, [ev])
    assert changes["aufsicht_neu"] == []
    assert len(changes["aufsicht_geaendert"]) == 1
