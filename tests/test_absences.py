"""Abwesenheiten (Krank/Frei/…): Kaskade in der Sequenzplanung, Kalendereintrag,
automatisches Zurückrollen. Der Stundenplan selbst darf sich dabei NIE ändern.

Alle Termine liegen 2030, damit die Tests unabhängig vom heutigen Datum deterministisch
sind (der Default-Stundenplan gilt ab "heute").
"""


def _class(client, name="7a", subject="Deutsch", grade=7, hours=2):
    r = client.post("/api/classes",
                    json={"name": name, "subject": subject, "grade": grade, "weeklyHours": hours})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _timetable_entry(client, cid, weekday=0, slot_label="1.", span=1):
    kinds = client.get("/api/stundenplan/kinds").json()
    slots = client.get("/api/stundenplan/slots").json()
    plans = client.get("/api/stundenplan/plans").json()   # löst Seeding aus
    slot = next(s for s in slots if s["slotType"] == "lesson" and s["label"] == slot_label)
    r = client.post("/api/stundenplan/entries", json={
        "planId": plans[0]["id"], "slotId": slot["id"], "kindId": kinds[0]["id"],
        "classId": cid, "weekday": weekday, "spanSlots": span,
    })
    assert r.status_code == 201, r.text
    return slot


def _block(client, cid, title="Stoffplan"):
    r = client.post("/api/stoff-plans", json={
        "classId": cid, "title": title,
        "blocks": [{"lbCode": "LB3", "title": "Lesen", "ustd": 20,
                    "startDate": "2030-01-07", "endDate": "2030-03-29"}],
    })
    assert r.status_code == 201, r.text
    return r.json()["blocks"][0]["id"]


def _stunde(client, block_id, title, date, **extra):
    r = client.post("/api/sequenz-stunden",
                    json={"blockId": block_id, "title": title, "date": date, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _dates(client, block_id):
    return [s["date"] for s in client.get(f"/api/sequenz-stunden?blockId={block_id}").json()]


# ---------------------------------------------------------------- Kaskade
def test_kaskade_verschiebt_ab_dem_abwesenheitstag(client, auth):
    """Montags-Klasse, drei terminierte Stunden: fällt der 2. Montag aus, rutschen die
    2. und die 3. Stunde je eine Woche nach hinten – die 1. bleibt unangetastet."""
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0)          # Montag
    bid = _block(client, cid)
    _stunde(client, bid, "A", "2030-01-07")
    _stunde(client, bid, "B", "2030-01-14")
    _stunde(client, bid, "C", "2030-01-21")

    r = client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "krank",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["result"]["shifted"] == 2
    assert body["result"]["overflow"] == 0
    assert _dates(client, bid) == ["2030-01-07", "2030-01-21", "2030-01-28"]


def test_kaskade_endet_wenn_sie_eingeholt_ist(client, auth):
    """Liegt nach dem Ausfall eine Lücke (hier: erst wieder im Februar geplant), bleibt die
    spätere Stunde stehen – es rutscht nur, was tatsächlich kollidiert."""
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0)
    bid = _block(client, cid)
    _stunde(client, bid, "A", "2030-01-14")
    _stunde(client, bid, "B", "2030-02-25")

    r = client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "frei",
    })
    assert r.json()["result"]["shifted"] == 1
    assert _dates(client, bid) == ["2030-01-21", "2030-02-25"]


def test_zeitraum_ueber_mehrere_tage_und_klassen(client, auth):
    """Eine ganze Woche Fortbildung trifft beide Klassen (Montag bzw. Mittwoch)."""
    c1 = _class(client, "7a")
    c2 = _class(client, "9b", subject="WTH", grade=9)
    _timetable_entry(client, c1, weekday=0)                       # Montag
    _timetable_entry(client, c2, weekday=2, slot_label="3.")      # Mittwoch
    b1, b2 = _block(client, c1, "P1"), _block(client, c2, "P2")
    _stunde(client, b1, "D-A", "2030-01-14")
    _stunde(client, b2, "W-A", "2030-01-16")

    r = client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-18", "kind": "fortbildung",
        "note": "Medienbildung",
    })
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    assert res["shifted"] == 2
    assert {c["className"] for c in res["classes"]} == {"7a", "9b"}
    assert _dates(client, b1) == ["2030-01-21"]
    assert _dates(client, b2) == ["2030-01-23"]


def test_doppelstunde_bleibt_zusammen(client, auth):
    """Zwei Karten an derselben lessons-Zeile (Doppelstunde) landen auf demselben Termin."""
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0, span=2)
    bid = _block(client, cid)
    lesson = client.post("/api/lessons", json={
        "title": "Doppel", "subject": "Deutsch", "grade": 7, "classId": cid,
        "date": "2030-01-14", "durationMinutes": 90,
    }).json()
    for title in ("A", "B"):
        s = _stunde(client, bid, title, "2030-01-14")
        assert client.post(f"/api/sequenz-stunden/{s['id']}/link",
                           json={"lessonId": lesson["id"]}).status_code == 200

    client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "krank",
    })
    assert _dates(client, bid) == ["2030-01-21", "2030-01-21"]
    assert client.get(f"/api/lessons/{lesson['id']}").json()["date"] == "2030-01-21"


# ---------------------------------------------------------------- Stundenplan bleibt
def test_stundenplan_bleibt_unveraendert_nur_markiert(client, auth):
    """Der Stundenplan selbst ändert sich nicht – der Tag wird lediglich markiert."""
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0)
    before = client.get("/api/stundenplan/resolved?start=2030-01-14").json()
    assert len(before["days"][0]["items"]) == 1

    client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "kur",
    })
    after = client.get("/api/stundenplan/resolved?start=2030-01-14").json()
    assert after["days"][0]["items"] == before["days"][0]["items"]
    assert after["days"][0]["absenceKind"] == "kur"
    assert after["days"][0]["absenceLabel"] == "Kur"
    assert after["days"][1]["absenceKind"] is None


# ---------------------------------------------------------------- Kalendereintrag
def test_kalendereintrag_eintaegig_und_mehrtaegig(client, auth):
    r = client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "krank",
    })
    aid = r.json()["absence"]["id"]
    entries = client.get("/api/calendar?start=2030-01-01&end=2030-01-31").json()
    entry = next(e for e in entries if e["title"] == "Krank")
    assert entry["entryDate"] == "2030-01-14"
    assert entry["endDate"] is None
    assert entry["allDay"] is True

    r = client.put(f"/api/absences/{aid}", json={"endDate": "2030-01-16", "note": "Grippe"})
    assert r.status_code == 200, r.text
    entries = client.get("/api/calendar?start=2030-01-01&end=2030-01-31").json()
    entry = next(e for e in entries if e["title"].startswith("Krank"))
    assert entry["title"] == "Krank – Grippe"
    assert entry["endDate"] == "2030-01-16"

    assert client.delete(f"/api/absences/{aid}").status_code == 200
    entries = client.get("/api/calendar?start=2030-01-01&end=2030-01-31").json()
    assert not [e for e in entries if e["title"].startswith("Krank")]


# ---------------------------------------------------------------- Zurückrollen
def test_loeschen_rollt_zurueck(client, auth):
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0)
    bid = _block(client, cid)
    _stunde(client, bid, "A", "2030-01-14")
    _stunde(client, bid, "B", "2030-01-21")

    aid = client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "exkursion",
    }).json()["absence"]["id"]
    assert _dates(client, bid) == ["2030-01-21", "2030-01-28"]

    r = client.delete(f"/api/absences/{aid}")
    assert r.status_code == 200, r.text
    assert r.json() == {"restored": 2, "kept": 0}
    assert _dates(client, bid) == ["2030-01-14", "2030-01-21"]


def test_zurueckrollen_laesst_haendisch_geaendertes_stehen(client, auth):
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0)
    bid = _block(client, cid)
    a = _stunde(client, bid, "A", "2030-01-14")
    _stunde(client, bid, "B", "2030-01-21")

    aid = client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "krank",
    }).json()["absence"]["id"]
    # A von Hand auf einen anderen Termin gelegt – das darf das Zurückrollen nicht überschreiben.
    client.put(f"/api/sequenz-stunden/{a['id']}", json={"date": "2030-02-04"})

    r = client.delete(f"/api/absences/{aid}").json()
    assert r == {"restored": 1, "kept": 1}
    # Reihenfolge = sortOrder (A, B): A behält den handgesetzten Termin, B wird zurückgesetzt.
    assert _dates(client, bid) == ["2030-02-04", "2030-01-21"]


def test_verschobene_exkursion_rollt_zurueck_und_neu(client, auth):
    """Zeitraum ändern = zurückrollen + neu verschieben (z. B. verlegte Exkursion)."""
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0)
    bid = _block(client, cid)
    _stunde(client, bid, "A", "2030-01-14")
    _stunde(client, bid, "B", "2030-01-21")

    aid = client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "exkursion",
    }).json()["absence"]["id"]
    assert _dates(client, bid) == ["2030-01-21", "2030-01-28"]

    r = client.put(f"/api/absences/{aid}",
                   json={"startDate": "2030-01-21", "endDate": "2030-01-21"})
    assert r.status_code == 200, r.text
    # A steht wieder auf seinem ursprünglichen Termin, nur B rutscht jetzt.
    assert _dates(client, bid) == ["2030-01-14", "2030-01-28"]


def test_verknuepfte_stunde_und_kalendereintrag_wandern_mit(client, auth):
    cid = _class(client)
    slot = _timetable_entry(client, cid, weekday=0)
    bid = _block(client, cid)
    lesson = client.post("/api/lessons", json={
        "title": "Balladen", "subject": "Deutsch", "grade": 7, "classId": cid,
        "date": "2030-01-14", "time": "09:00",
    }).json()
    s = _stunde(client, bid, "A", "2030-01-14")
    client.post(f"/api/sequenz-stunden/{s['id']}/link", json={"lessonId": lesson["id"]})

    aid = client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "dienstreise",
    }).json()["absence"]["id"]

    moved = client.get(f"/api/lessons/{lesson['id']}").json()
    assert moved["date"] == "2030-01-21"
    assert moved["time"] == slot["startTime"]
    entries = client.get("/api/calendar?start=2030-01-01&end=2030-01-31").json()
    auto = next(e for e in entries if e.get("lessonId") == lesson["id"])
    assert auto["entryDate"] == "2030-01-21"

    client.delete(f"/api/absences/{aid}")
    back = client.get(f"/api/lessons/{lesson['id']}").json()
    assert back["date"] == "2030-01-14" and back["time"] == "09:00"


# ---------------------------------------------------------------- Vorschau & Warnungen
def test_preview_schreibt_nichts(client, auth):
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0)
    bid = _block(client, cid)
    _stunde(client, bid, "A", "2030-01-14")

    r = client.post("/api/absences/preview",
                    json={"startDate": "2030-01-14", "endDate": "2030-01-14"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["shifted"] == 1
    assert body["classes"][0]["lastNewDate"] == "2030-01-21"
    assert body["schoolDays"] == 1
    assert _dates(client, bid) == ["2030-01-14"]          # unverändert
    assert client.get("/api/absences").json() == []


def test_preview_warnt_bei_leistungsueberpruefung(client, auth):
    cid = _class(client)
    _timetable_entry(client, cid, weekday=0)
    bid = _block(client, cid)
    _stunde(client, bid, "Klassenarbeit 1", "2030-01-14", isKlassenarbeit=True)

    body = client.post("/api/absences/preview",
                       json={"startDate": "2030-01-14", "endDate": "2030-01-14"}).json()
    assert len(body["warnings"]) == 1
    w = body["warnings"][0]
    assert w["art"] == "Klassenarbeit" and w["oldDate"] == "2030-01-14"
    assert w["newDate"] == "2030-01-21"


def test_ohne_stundenplan_kein_platz_meldet_overflow(client, auth):
    """Ohne Stundenplan-Eintrag findet die Kaskade keinen Folgetermin – die Stunde bleibt
    stehen und wird als 'kein Platz mehr' gemeldet statt still zu verschwinden."""
    cid = _class(client)
    bid = _block(client, cid)
    _stunde(client, bid, "A", "2030-01-14")

    body = client.post("/api/absences/preview",
                       json={"startDate": "2030-01-14", "endDate": "2030-01-14"}).json()
    assert body["shifted"] == 0 and body["overflow"] == 1
    assert body["classes"][0]["overflow"] == 1
    assert body["classes"][0]["lastNewDate"] is None


# ---------------------------------------------------------------- Validierung & Liste
def test_ende_vor_start_abgelehnt(client, auth):
    r = client.post("/api/absences", json={
        "startDate": "2030-01-16", "endDate": "2030-01-14", "kind": "krank",
    })
    assert r.status_code == 400


def test_ueberlappung_abgelehnt(client, auth):
    client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-16", "kind": "krank",
    })
    r = client.post("/api/absences", json={
        "startDate": "2030-01-16", "endDate": "2030-01-18", "kind": "frei",
    })
    assert r.status_code == 400


def test_liste_mit_zeitraumfilter(client, auth):
    client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "krank"})
    client.post("/api/absences", json={
        "startDate": "2030-03-04", "endDate": "2030-03-08", "kind": "kur"})
    rows = client.get("/api/absences").json()
    assert [r["kind"] for r in rows] == ["kur", "krank"]
    assert rows[0]["kindLabel"] == "Kur"
    rows = client.get("/api/absences?from=2030-02-01&to=2030-04-01").json()
    assert [r["kind"] for r in rows] == ["kur"]


def test_abwesenheit_ohne_login_abgelehnt(client):
    assert client.get("/api/absences").status_code == 401
    assert client.post("/api/absences", json={
        "startDate": "2030-01-14", "endDate": "2030-01-14", "kind": "krank"}).status_code == 401
