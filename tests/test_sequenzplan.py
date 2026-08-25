"""Sequenzplan-Router: CRUD, Reorder, Link/Unlink, Shift (Budget-Warnung)."""


def _class(client, name="7a", subject="Deutsch", grade=7, track=None, hours=2):
    body = {"name": name, "subject": subject, "grade": grade, "weeklyHours": hours}
    if track is not None:
        body["track"] = track
    r = client.post("/api/classes", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _blocks():
    return [
        {"lbCode": "LB3", "title": "Lesen", "ustd": 20,
         "startDate": "2025-09-01", "endDate": "2025-10-10"},
        {"lbCode": "LB4", "title": "Schreiben", "ustd": 25,
         "startDate": "2025-10-20", "endDate": "2025-12-15"},
    ]


def _plan(client, cid, title="Stoffplan 7a"):
    r = client.post("/api/stoff-plans", json={"classId": cid, "title": title, "blocks": _blocks()})
    assert r.status_code == 201, r.text
    return r.json()


def _block_id(plan, code="LB3"):
    return next(b["id"] for b in plan["blocks"] if b["lbCode"] == code)


def _stunde(client, block_id, title="Stunde 1", **extra):
    body = {"blockId": block_id, "title": title, **extra}
    r = client.post("/api/sequenz-stunden", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_list(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "Einstieg", grobziel="Erste Annäherung")
    s2 = _stunde(client, bid, "Vertiefung")
    assert s1["sortOrder"] == 0 and s2["sortOrder"] == 1
    assert s1["grobziel"] == "Erste Annäherung"
    rows = client.get(f"/api/sequenz-stunden?blockId={bid}").json()
    assert [r["title"] for r in rows] == ["Einstieg", "Vertiefung"]


def test_notenart_flags_roundtrip(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s = _stunde(client, bid, "Test", isKlassenarbeit=True, isReferat=False, weitereNotenart="Portfolio")
    assert s["isKlassenarbeit"] is True
    assert s["isLk"] is False
    assert s["weitereNotenart"] == "Portfolio"


def test_date_set_and_clear(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s = _stunde(client, bid, "Termin", date="2025-09-15")
    assert s["date"] == "2025-09-15"
    r = client.put(f"/api/sequenz-stunden/{s['id']}", json={"date": None})
    assert r.status_code == 200
    assert r.json()["date"] is None


def test_update(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s = _stunde(client, bid, "Alt")
    r = client.put(f"/api/sequenz-stunden/{s['id']}", json={"title": "Neu", "isReferat": True})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Neu" and body["isReferat"] is True


def test_delete(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s = _stunde(client, bid)
    assert client.delete(f"/api/sequenz-stunden/{s['id']}").status_code == 204
    rows = client.get(f"/api/sequenz-stunden?blockId={bid}").json()
    assert rows == []


def test_reorder(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "A")
    s2 = _stunde(client, bid, "B")
    s3 = _stunde(client, bid, "C")
    r = client.post("/api/sequenz-stunden/reorder",
                    json={"blockId": bid, "orderedIds": [s3["id"], s1["id"], s2["id"]]})
    assert r.status_code == 200
    rows = r.json()
    assert [x["title"] for x in rows] == ["C", "A", "B"]


def test_reorder_rejects_incomplete_set(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "A")
    _stunde(client, bid, "B")
    r = client.post("/api/sequenz-stunden/reorder", json={"blockId": bid, "orderedIds": [s1["id"]]})
    assert r.status_code == 400


def test_link_and_unlink(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s = _stunde(client, bid)
    lesson = client.post("/api/lessons", json={
        "title": "Testlektion", "subject": "Deutsch", "grade": 7, "classId": cid,
    }).json()
    r = client.post(f"/api/sequenz-stunden/{s['id']}/link", json={"lessonId": lesson["id"]})
    assert r.status_code == 200
    assert r.json()["lessonId"] == lesson["id"]

    r2 = client.post(f"/api/sequenz-stunden/{s['id']}/link", json={"lessonId": None})
    assert r2.status_code == 200
    assert r2.json()["lessonId"] is None


def test_link_allows_up_to_two_for_doppelstunde(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "A")
    s2 = _stunde(client, bid, "B")
    s3 = _stunde(client, bid, "C")
    lesson = client.post("/api/lessons", json={
        "title": "Testlektion", "subject": "Deutsch", "grade": 7, "classId": cid,
    }).json()
    assert client.post(f"/api/sequenz-stunden/{s1['id']}/link",
                       json={"lessonId": lesson["id"]}).status_code == 200
    # Doppelstunde: eine zweite Sequenzstunde darf auf dieselbe Lesson zeigen.
    assert client.post(f"/api/sequenz-stunden/{s2['id']}/link",
                       json={"lessonId": lesson["id"]}).status_code == 200
    # Eine dritte wird abgelehnt (max. 2 je Lesson).
    r = client.post(f"/api/sequenz-stunden/{s3['id']}/link", json={"lessonId": lesson["id"]})
    assert r.status_code == 400


def test_shift_reorders_and_reports_budget(client, auth):
    cid = _class(client, track="RS", grade=7)
    r = client.post("/api/stoff-plans", json={
        "classId": cid, "title": "Kleiner Block",
        "blocks": [{"lbCode": "LB3", "title": "Lesen", "ustd": 2,
                    "startDate": "2025-09-01", "endDate": "2025-09-10"}],
    })
    assert r.status_code == 201, r.text
    plan = r.json()
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "A")
    _stunde(client, bid, "B")
    _stunde(client, bid, "C")

    r = client.post(f"/api/sequenz-stunden/{s1['id']}/shift", json={"withCalendar": False})
    assert r.status_code == 200
    body = r.json()
    assert body["plannedCount"] == 3
    assert body["richtwertUstd"] == 2
    assert body["overBudget"] is True

    # Relative Reihenfolge bleibt erhalten, aber es entsteht eine Lücke (sort_order +1 ab s1) –
    # Platz für eine zusätzliche Stunde, die die ursprüngliche Position "A" nicht mehr schafft.
    rows = client.get(f"/api/sequenz-stunden?blockId={bid}").json()
    assert [x["title"] for x in rows] == ["A", "B", "C"]
    assert [x["sortOrder"] for x in rows] == [1, 2, 3]


def test_shift_with_calendar_moves_linked_lesson_to_next_slot(client, auth):
    cid = _class(client)
    kinds = client.get("/api/stundenplan/kinds").json()
    slots = client.get("/api/stundenplan/slots").json()
    plans = client.get("/api/stundenplan/plans").json()   # löst Seeding aus (Default-Plan gilt ab "heute")
    r = client.post("/api/stundenplan/entries", json={
        "planId": plans[0]["id"], "slotId": slots[1]["id"], "kindId": kinds[0]["id"],
        "classId": cid, "weekday": 0,
    })
    assert r.status_code == 201, r.text

    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "A")

    lesson = client.post("/api/lessons", json={
        "title": "Testlektion", "subject": "Deutsch", "grade": 7, "classId": cid,
        "date": "2030-01-07",   # Montag, sicher in der Zukunft (unabhängig vom Testlauf-Datum)
    }).json()
    client.post(f"/api/sequenz-stunden/{s1['id']}/link", json={"lessonId": lesson["id"]})

    r = client.post(f"/api/sequenz-stunden/{s1['id']}/shift", json={"withCalendar": True})
    assert r.status_code == 200, r.text

    updated = client.get(f"/api/lessons/{lesson['id']}").json()
    assert updated["date"] == "2030-01-14"   # nächster Montag mit Unterricht laut Stundenplan
    assert updated["time"] == slots[1]["startTime"]


def test_shift_without_calendar_leaves_linked_lesson_date_unchanged(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "A")
    lesson = client.post("/api/lessons", json={
        "title": "Testlektion", "subject": "Deutsch", "grade": 7, "classId": cid,
        "date": "2026-01-05",
    }).json()
    client.post(f"/api/sequenz-stunden/{s1['id']}/link", json={"lessonId": lesson["id"]})

    r = client.post(f"/api/sequenz-stunden/{s1['id']}/shift", json={"withCalendar": False})
    assert r.status_code == 200, r.text

    updated = client.get(f"/api/lessons/{lesson['id']}").json()
    assert updated["date"] == "2026-01-05"


def test_apply_calendar_entry_updates_auto_generated_entry(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "A", isKlassenarbeit=True)
    lesson = client.post("/api/lessons", json={
        "title": "A", "subject": "Deutsch", "grade": 7, "classId": cid, "date": "2030-01-07",
    }).json()
    client.post(f"/api/sequenz-stunden/{s1['id']}/link", json={"lessonId": lesson["id"]})

    cal_before = client.get("/api/calendar").json()
    entry = next(e for e in cal_before if e["lessonId"] == lesson["id"])
    assert entry["entryType"] == "normal"

    r = client.post(f"/api/sequenz-stunden/{s1['id']}/apply-calendar-entry", json={"type": "exam"})
    assert r.status_code == 200, r.text

    cal_after = client.get("/api/calendar").json()
    entry_after = next(e for e in cal_after if e["lessonId"] == lesson["id"])
    assert entry_after["entryType"] == "exam"


def test_apply_calendar_entry_requires_link_and_date(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "A")

    r = client.post(f"/api/sequenz-stunden/{s1['id']}/apply-calendar-entry", json={"type": "exam"})
    assert r.status_code == 400   # nicht verknüpft

    lesson = client.post("/api/lessons", json={
        "title": "A", "subject": "Deutsch", "grade": 7, "classId": cid,
    }).json()   # kein Datum
    client.post(f"/api/sequenz-stunden/{s1['id']}/link", json={"lessonId": lesson["id"]})
    r = client.post(f"/api/sequenz-stunden/{s1['id']}/apply-calendar-entry", json={"type": "exam"})
    assert r.status_code == 400   # kein Datum


def test_apply_calendar_entry_invalid_type_rejected(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "A")
    r = client.post(f"/api/sequenz-stunden/{s1['id']}/apply-calendar-entry", json={"type": "quatsch"})
    assert r.status_code == 422


def test_requires_login(client):
    assert client.get("/api/sequenz-stunden?blockId=1").status_code == 401


def test_foreign_block_rejected(client, auth):
    r = client.post("/api/sequenz-stunden", json={"blockId": 9999, "title": "X"})
    assert r.status_code == 404


def test_suggest_date_without_timetable_returns_null(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    r = client.get(f"/api/sequenz-stunden/suggest-date?blockId={bid}")
    assert r.status_code == 200
    assert r.json()["date"] is None


def test_suggest_date_uses_block_start_then_last_stunde(client, auth):
    cid = _class(client)
    kinds = client.get("/api/stundenplan/kinds").json()
    slots = client.get("/api/stundenplan/slots").json()
    plans = client.get("/api/stundenplan/plans").json()   # löst Seeding aus (Default-Plan gilt ab "heute")
    r = client.post("/api/stundenplan/entries", json={
        "planId": plans[0]["id"], "slotId": slots[0]["id"], "kindId": kinds[0]["id"],
        "classId": cid, "weekday": 0,  # Montag
    })
    assert r.status_code == 201, r.text

    r = client.post("/api/stoff-plans", json={
        "classId": cid, "title": "Zukunftsplan",
        "blocks": [{"lbCode": "LB3", "title": "Lesen", "ustd": 20,
                    "startDate": "2030-01-07", "endDate": "2030-02-10"}],   # Montag
    })
    assert r.status_code == 201, r.text
    bid = _block_id(r.json())

    r = client.get(f"/api/sequenz-stunden/suggest-date?blockId={bid}")
    assert r.status_code == 200
    assert r.json()["date"] == "2030-01-07"

    _stunde(client, bid, "A", date="2030-01-07")
    r = client.get(f"/api/sequenz-stunden/suggest-date?blockId={bid}")
    assert r.status_code == 200
    assert r.json()["date"] == "2030-01-14"   # nächster Montag nach der zuletzt terminierten Stunde


def test_suggest_date_after_param_chains_without_persisted_stunde(client, auth):
    """`after` erlaubt es dem Client, mehrere noch ungespeicherte Karten in Folge zu terminieren
    (z.B. nach einem KI-Vorschlag) – ohne dass jede Karte zwischenzeitlich gespeichert werden muss."""
    cid = _class(client)
    kinds = client.get("/api/stundenplan/kinds").json()
    slots = client.get("/api/stundenplan/slots").json()
    plans = client.get("/api/stundenplan/plans").json()
    r = client.post("/api/stundenplan/entries", json={
        "planId": plans[0]["id"], "slotId": slots[0]["id"], "kindId": kinds[0]["id"],
        "classId": cid, "weekday": 0,  # Montag
    })
    assert r.status_code == 201, r.text

    r = client.post("/api/stoff-plans", json={
        "classId": cid, "title": "Zukunftsplan",
        "blocks": [{"lbCode": "LB3", "title": "Lesen", "ustd": 20,
                    "startDate": "2030-01-07", "endDate": "2030-02-10"}],   # Montag
    })
    assert r.status_code == 201, r.text
    bid = _block_id(r.json())

    r = client.get(f"/api/sequenz-stunden/suggest-date?blockId={bid}")
    assert r.json()["date"] == "2030-01-07"

    r = client.get(f"/api/sequenz-stunden/suggest-date?blockId={bid}&after=2030-01-07")
    assert r.status_code == 200
    assert r.json()["date"] == "2030-01-14"


def test_suggest_date_reports_span_slots_for_real_doppelstunde(client, auth):
    """Steht laut Stundenplan an dem Tag eine echte Doppelstunde (span_slots=2), muss
    suggest-date das über spanSlots melden – sonst terminiert der Client zwei
    Sequenzstunden-Karten fälschlich auf zwei verschiedene Tage statt auf denselben."""
    cid = _class(client)
    kinds = client.get("/api/stundenplan/kinds").json()
    slots = client.get("/api/stundenplan/slots").json()
    plans = client.get("/api/stundenplan/plans").json()
    lesson_slot = next(s for s in slots if s["slotType"] == "lesson" and s["label"] == "1.")
    r = client.post("/api/stundenplan/entries", json={
        "planId": plans[0]["id"], "slotId": lesson_slot["id"], "kindId": kinds[0]["id"],
        "classId": cid, "weekday": 0, "spanSlots": 2,  # Montag, 1./2. Stunde als Doppelstunde
    })
    assert r.status_code == 201, r.text

    r = client.post("/api/stoff-plans", json={
        "classId": cid, "title": "Zukunftsplan",
        "blocks": [{"lbCode": "LB3", "title": "Lesen", "ustd": 20,
                    "startDate": "2030-01-07", "endDate": "2030-02-10"}],   # Montag
    })
    assert r.status_code == 201, r.text
    bid = _block_id(r.json())

    r = client.get(f"/api/sequenz-stunden/suggest-date?blockId={bid}")
    assert r.status_code == 200
    assert r.json()["date"] == "2030-01-07"
    assert r.json()["spanSlots"] == 2

    r = client.get(f"/api/sequenz-stunden/suggest-date?blockId={bid}&after=2030-01-07")
    assert r.json()["date"] == "2030-01-14"
    assert r.json()["spanSlots"] == 2


def test_suggest_date_unknown_block_rejected(client, auth):
    r = client.get("/api/sequenz-stunden/suggest-date?blockId=9999")
    assert r.status_code == 404


# ---------- "Stunde verschieben" im Planungskalender (lessons.py, cascade hier getestet
# wegen der engen Kopplung an move_sequenz_for_lesson in diesem Modul) ----------

def _timetable_entry(client, cid, weekday=0, slot_label="1."):
    kinds = client.get("/api/stundenplan/kinds").json()
    slots = client.get("/api/stundenplan/slots").json()
    plans = client.get("/api/stundenplan/plans").json()   # löst Seeding aus (Default-Plan gilt ab "heute")
    slot = next(s for s in slots if s["slotType"] == "lesson" and s["label"] == slot_label)
    r = client.post("/api/stundenplan/entries", json={
        "planId": plans[0]["id"], "slotId": slot["id"], "kindId": kinds[0]["id"],
        "classId": cid, "weekday": weekday,
    })
    assert r.status_code == 201, r.text
    return slot


def test_upcoming_slots_lists_next_real_timetable_dates(client, auth):
    cid = _class(client)
    slot = _timetable_entry(client, cid, weekday=0)   # Montag
    lesson = client.post("/api/lessons", json={
        "title": "A", "subject": "Deutsch", "grade": 7, "classId": cid, "date": "2030-01-07",
    }).json()
    r = client.get(f"/api/lessons/{lesson['id']}/upcoming-slots?count=3")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["date"] for x in body] == ["2030-01-14", "2030-01-21", "2030-01-28"]
    assert body[0]["time"] == slot["startTime"]


def test_upcoming_slots_without_class_is_empty(client, auth):
    lesson = client.post("/api/lessons", json={"title": "A", "subject": "Deutsch", "grade": 7}).json()
    r = client.get(f"/api/lessons/{lesson['id']}/upcoming-slots")
    assert r.status_code == 200
    assert r.json() == []


def test_move_to_slot_without_sequenz_link_just_moves_lesson(client, auth):
    cid = _class(client)
    lesson = client.post("/api/lessons", json={
        "title": "A", "subject": "Deutsch", "grade": 7, "classId": cid, "date": "2030-01-07",
    }).json()
    r = client.post(f"/api/lessons/{lesson['id']}/move-to-slot",
                     json={"date": "2030-01-14", "time": "08:00"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lesson"]["date"] == "2030-01-14"
    assert body["lesson"]["time"] == "08:00"
    assert body["newSequenzStundeId"] is None


def test_move_to_slot_duplicates_linked_sequenz_stunde_and_cascades(client, auth):
    """Kernverhalten: die verschobene Sequenzstunde bekommt eine neue, verknüpfte Zeile am
    Zielort; die Ursprungszeile bleibt (moved_to_id) stehen statt gelöscht zu werden – "die
    Stunde erscheint zweimal im Sequenzplan". Übrige Karten rücken sinnvoll nach (sort_order,
    plus verknüpfte künftige Lessons auf den nächsten realen Termin)."""
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0)   # Montag, für die kaskadierte Folge-Lesson

    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "Verschobene Stunde")
    s2 = _stunde(client, bid, "Nachfolgerin")

    lesson1 = client.post("/api/lessons", json={
        "title": "Verschobene Stunde", "subject": "Deutsch", "grade": 7, "classId": cid,
        "date": "2030-01-07",
    }).json()
    lesson2 = client.post("/api/lessons", json={
        "title": "Nachfolgerin", "subject": "Deutsch", "grade": 7, "classId": cid,
        "date": "2030-01-14",
    }).json()
    client.post(f"/api/sequenz-stunden/{s1['id']}/link", json={"lessonId": lesson1["id"]})
    client.post(f"/api/sequenz-stunden/{s2['id']}/link", json={"lessonId": lesson2["id"]})

    r = client.post(f"/api/lessons/{lesson1['id']}/move-to-slot",
                     json={"date": "2030-02-04", "time": "07:30", "withCalendar": True})
    assert r.status_code == 200, r.text
    body = r.json()
    new_id = body["newSequenzStundeId"]
    assert new_id is not None
    assert body["lesson"]["date"] == "2030-02-04"

    rows = {x["id"]: x for x in client.get(f"/api/sequenz-stunden?blockId={bid}").json()}
    original = rows[s1["id"]]
    assert original["movedToId"] == new_id
    assert original["lessonId"] is None
    assert original["title"] == "Verschobene Stunde"   # Inhalt bleibt als Hinweis erhalten

    new_row = rows[new_id]
    assert new_row["date"] == "2030-02-04"
    assert new_row["lessonId"] == lesson1["id"]
    assert new_row["title"] == "Verschobene Stunde"

    # s2 ("Nachfolgerin") rückt sinnvoll nach: sort_order hinter die neue Zeile geschoben,
    # und die verknüpfte lesson2 auf den nächsten realen Montags-Termin vorgezogen.
    assert rows[s2["id"]]["sortOrder"] > new_row["sortOrder"]
    updated_lesson2 = client.get(f"/api/lessons/{lesson2['id']}").json()
    assert updated_lesson2["date"] == "2030-01-21"   # nächster Montag laut Stundenplan


def test_move_to_slot_doppelstunde_moves_both_linked_rows_together(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    bid = _block_id(plan)
    s1 = _stunde(client, bid, "Teil 1")
    s2 = _stunde(client, bid, "Teil 2")
    lesson = client.post("/api/lessons", json={
        "title": "Doppelstunde", "subject": "Deutsch", "grade": 7, "classId": cid,
        "date": "2030-01-07", "durationMinutes": 90,
    }).json()
    client.post(f"/api/sequenz-stunden/{s1['id']}/link", json={"lessonId": lesson["id"]})
    client.post(f"/api/sequenz-stunden/{s2['id']}/link", json={"lessonId": lesson["id"]})

    r = client.post(f"/api/lessons/{lesson['id']}/move-to-slot",
                     json={"date": "2030-02-04", "withCalendar": False})
    assert r.status_code == 200, r.text

    rows = {x["id"]: x for x in client.get(f"/api/sequenz-stunden?blockId={bid}").json()}
    assert rows[s1["id"]]["movedToId"] is not None
    assert rows[s2["id"]]["movedToId"] is not None
    new_ids = {rows[s1["id"]]["movedToId"], rows[s2["id"]]["movedToId"]}
    assert len(new_ids) == 2   # zwei eigenständige neue Zeilen, keine geteilte
    for nid in new_ids:
        assert rows[nid]["lessonId"] == lesson["id"]
        assert rows[nid]["date"] == "2030-02-04"
