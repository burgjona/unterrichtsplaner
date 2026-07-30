"""Tests für das Stundenplan-Backend (U27a).

Deckt Seeds/Idempotenz, Nutzer-Scoping (401/404), CRUD von Typen/Slots/Plänen/
Einträgen, Span-Validierung, A/B-Auflösung (beide Paritäten), Plan-Auswahl nach
valid_from inkl. Fallback, Plan-Kopie und CASCADE ab.
"""
import datetime

import pytest

BASE = "/api/stundenplan"


def _this_monday():
    today = datetime.date.today()
    return today - datetime.timedelta(days=today.weekday())


def _expected_week_type(date_str, parity):
    """Spiegelt die Server-Logik: Montag → ISO-KW → Parität → A/B."""
    d = datetime.date.fromisoformat(date_str)
    monday = d - datetime.timedelta(days=d.weekday())
    kw = monday.isocalendar()[1]
    p = "odd" if kw % 2 == 1 else "even"
    return "A" if p == parity else "B"


def _seed(client):
    """Löst das Seeding aus und liefert (kinds, slots, plans)."""
    kinds = client.get(f"{BASE}/kinds").json()
    slots = client.get(f"{BASE}/slots").json()
    plans = client.get(f"{BASE}/plans").json()
    return kinds, slots, plans


# ---------------------------------------------------------------- 1) Seeds
def test_seeds_idempotent_and_umlaute(client, auth):
    k1 = client.get(f"{BASE}/kinds").json()
    s1 = client.get(f"{BASE}/slots").json()
    p1 = client.get(f"{BASE}/plans").json()
    # Zweiter GET darf nichts vermehren.
    k2 = client.get(f"{BASE}/kinds").json()
    s2 = client.get(f"{BASE}/slots").json()
    p2 = client.get(f"{BASE}/plans").json()

    assert len(k1) == len(k2) == 7
    assert len(s1) == len(s2) == 11
    assert len(p1) == len(p2) == 1

    # Umlaute unverändert.
    assert any(k["name"] == "Förderunterricht" for k in k1)
    assert any(s["label"] == "Frühaufsicht" for s in s1)

    # Genau ein Default-Typ ('Sonstiges'), korrekte sort_order-Reihenfolge.
    defaults = [k for k in k1 if k["isDefault"]]
    assert len(defaults) == 1 and defaults[0]["name"] == "Sonstiges"
    assert [k["sortOrder"] for k in k1] == sorted(k["sortOrder"] for k in k1)

    # Default-Plan gilt ab Montag dieser Woche.
    assert p1[0]["validFrom"] == _this_monday().isoformat()
    assert p1[0]["name"] == "Stundenplan"


# ---------------------------------------------------------------- 2) Auth
def test_requires_login(client):
    for path in ("/kinds", "/slots", "/plans", "/settings",
                 "/entries?planId=1", "/resolved?start=2026-01-12"):
        assert client.get(f"{BASE}{path}").status_code == 401


# ---------------------------------------------------------------- 3) kinds CRUD
def test_kinds_crud_and_default_delete(client, auth):
    kinds, _, _ = _seed(client)
    default = next(k for k in kinds if k["isDefault"])
    nondefault = next(k for k in kinds if not k["isDefault"])

    # Anlegen.
    created = client.post(f"{BASE}/kinds", json={"name": "Vertretung", "color": "#111111"})
    assert created.status_code == 201
    cid = created.json()["id"]
    assert created.json()["isDefault"] is False

    # PUT darf is_default NICHT verändern (Feld wird ignoriert).
    put = client.put(f"{BASE}/kinds/{default['id']}",
                     json={"name": "Sonstiges (neu)", "isDefault": False})
    assert put.status_code == 200
    assert put.json()["name"] == "Sonstiges (neu)"
    assert put.json()["isDefault"] is True

    # Default-Typ löschen → 400.
    assert client.delete(f"{BASE}/kinds/{default['id']}").status_code == 400
    # Normalen Typ löschen → 204.
    assert client.delete(f"{BASE}/kinds/{cid}").status_code == 204
    assert client.delete(f"{BASE}/kinds/{nondefault['id']}").status_code == 204


# ---------------------------------------------------------------- 4) kind-delete hängt um
def test_kind_delete_reassigns_entries_to_default(client, auth):
    kinds, slots, plans = _seed(client)
    default = next(k for k in kinds if k["isDefault"])
    nondefault = next(k for k in kinds if not k["isDefault"])

    entry = client.post(f"{BASE}/entries", json={
        "planId": plans[0]["id"], "slotId": slots[1]["id"], "kindId": nondefault["id"],
        "weekday": 0,
    })
    assert entry.status_code == 201
    eid = entry.json()["id"]

    # Typ löschen → bestehende Einträge fallen auf den Default-Typ zurück.
    assert client.delete(f"{BASE}/kinds/{nondefault['id']}").status_code == 204
    entries = client.get(f"{BASE}/entries", params={"planId": plans[0]["id"]}).json()
    row = next(e for e in entries if e["id"] == eid)
    assert row["kindId"] == default["id"]


# ---------------------------------------------------------------- 5) Slot-Zeitformat
def test_slot_time_format_validation(client, auth):
    _seed(client)
    base = {"position": 20, "label": "Test"}
    assert client.post(f"{BASE}/slots", json={**base, "startTime": "25:00", "endTime": "08:00"}).status_code == 422
    assert client.post(f"{BASE}/slots", json={**base, "startTime": "7:30", "endTime": "08:00"}).status_code == 422
    ok = client.post(f"{BASE}/slots", json={**base, "startTime": "07:30", "endTime": "08:15"})
    assert ok.status_code == 201
    assert ok.json()["startTime"] == "07:30"


# ---------------------------------------------------------------- 6) Span-Validierung
def test_span_validation(client, auth):
    _, slots, plans = _seed(client)
    plan_id = plans[0]["id"]
    kinds = client.get(f"{BASE}/kinds").json()
    kind_id = kinds[0]["id"]

    # Anker = letzter Slot, span 2 → ragt hinaus → 400.
    over = client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[-1]["id"], "kindId": kind_id,
        "weekday": 0, "spanSlots": 2,
    })
    assert over.status_code == 400

    # Anker mittig, span 2 → 201.
    ok = client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[5]["id"], "kindId": kind_id,
        "weekday": 1, "spanSlots": 2,
    })
    assert ok.status_code == 201
    eid = ok.json()["id"]

    # PUT auf zu großen Span (ab Index 5 gibt es nur 6 Slots) → 400.
    assert client.put(f"{BASE}/entries/{eid}", json={"spanSlots": 11}).status_code == 400
    # PUT auf gültigen Span → 200.
    assert client.put(f"{BASE}/entries/{eid}", json={"spanSlots": 3}).status_code == 200


# ---------------------------------------------------------------- 7) Scoping
def test_entry_scoping_unknown_refs(client, auth):
    _, slots, plans = _seed(client)
    kinds = client.get(f"{BASE}/kinds").json()
    good = {"planId": plans[0]["id"], "slotId": slots[0]["id"], "kindId": kinds[0]["id"],
            "weekday": 0}

    assert client.post(f"{BASE}/entries", json={**good, "planId": 99999}).status_code == 404
    assert client.post(f"{BASE}/entries", json={**good, "slotId": 99999}).status_code == 404
    assert client.post(f"{BASE}/entries", json={**good, "kindId": 99999}).status_code == 404
    assert client.post(f"{BASE}/entries", json={**good, "classId": 99999}).status_code == 404
    # GET entries mit unbekanntem Plan → 404.
    assert client.get(f"{BASE}/entries", params={"planId": 99999}).status_code == 404


# ---------------------------------------------------------------- 8) A/B-Auflösung
def test_resolved_ab_parity_both_directions(client, auth):
    _seed(client)
    # Default-Parität 'odd'.
    a = client.get(f"{BASE}/resolved", params={"start": "2026-01-12"}).json()  # KW3 ungerade → A
    b = client.get(f"{BASE}/resolved", params={"start": "2026-01-05"}).json()  # KW2 gerade → B
    assert a["weekType"] == _expected_week_type("2026-01-12", "odd") == "A"
    assert b["weekType"] == _expected_week_type("2026-01-05", "odd") == "B"
    assert a["isoWeek"] == 3 and b["isoWeek"] == 2
    # Beliebiges Datum wird auf den Montag normalisiert.
    assert a["weekStart"] == "2026-01-12"

    # Parität invertieren → A/B kippt.
    put = client.put(f"{BASE}/settings", json={"weekAParity": "even"})
    assert put.status_code == 200 and put.json()["weekAParity"] == "even"
    a2 = client.get(f"{BASE}/resolved", params={"start": "2026-01-12"}).json()
    b2 = client.get(f"{BASE}/resolved", params={"start": "2026-01-05"}).json()
    assert a2["weekType"] == _expected_week_type("2026-01-12", "even") == "B"
    assert b2["weekType"] == _expected_week_type("2026-01-05", "even") == "A"


# ---------------------------------------------------------------- 9) Plan-Auswahl
def test_plan_selection_by_valid_from_and_fallback(client, auth):
    _, _, plans = _seed(client)
    p0 = plans[0]["id"]                                    # valid_from = Montag dieser Woche (immer <= heute)
    # Zukunftsdaten relativ zu heute, damit der Seed nie kollidiert oder zum MAX wird.
    today = datetime.date.today()
    vf1 = (today + datetime.timedelta(days=400)).isoformat()
    vf2 = (today + datetime.timedelta(days=800)).isoformat()
    between = (today + datetime.timedelta(days=600)).isoformat()
    p1 = client.post(f"{BASE}/plans", json={"validFrom": vf1, "name": "Zukunft 1"}).json()["id"]
    client.post(f"{BASE}/plans", json={"validFrom": vf2, "name": "Zukunft 2"})

    # Datum zwischen vf1 und vf2 → MAX(valid_from) <= Montag ist vf1.
    r = client.get(f"{BASE}/resolved", params={"start": between}).json()
    assert r["planId"] == p1

    # Weit in der Vergangenheit → Fallback ältester Plan (Seed).
    r_old = client.get(f"{BASE}/resolved", params={"start": "2000-01-03"}).json()
    assert r_old["planId"] == p0


# ---------------------------------------------------------------- 10) Kopie & CASCADE
def test_plan_copy_delete_and_last_plan(client, auth):
    _, slots, plans = _seed(client)
    p0 = plans[0]
    kinds = client.get(f"{BASE}/kinds").json()

    # Eintrag in P0.
    e = client.post(f"{BASE}/entries", json={
        "planId": p0["id"], "slotId": slots[1]["id"], "kindId": kinds[0]["id"],
        "weekday": 0, "room": "204",
    }).json()

    # Plan-Kopie zieht Einträge mit (Zukunftsdatum relativ zu heute → nie Kollision mit dem Seed).
    future = (datetime.date.today() + datetime.timedelta(days=500)).isoformat()
    p1 = client.post(f"{BASE}/plans", json={"validFrom": future, "copyFromPlanId": p0["id"]})
    assert p1.status_code == 201
    p1_id = p1.json()["id"]
    copied = client.get(f"{BASE}/entries", params={"planId": p1_id}).json()
    assert len(copied) == 1
    assert copied[0]["id"] != e["id"] and copied[0]["room"] == "204"

    # Doppeltes validFrom → 400.
    dup = client.post(f"{BASE}/plans", json={"validFrom": p0["validFrom"]})
    assert dup.status_code == 400

    # Plan löschen → Einträge weg (CASCADE); P0 unberührt.
    assert client.delete(f"{BASE}/plans/{p1_id}").status_code == 204
    assert client.get(f"{BASE}/entries", params={"planId": p1_id}).status_code == 404
    assert len(client.get(f"{BASE}/entries", params={"planId": p0['id']}).json()) == 1

    # Jetzt bleibt nur P0 → letzten Plan löschen → 400.
    assert client.delete(f"{BASE}/plans/{p0['id']}").status_code == 400


# ---------------------------------------------------------------- 11) Farben/Titel/source
def test_resolved_colors_titles_and_source(client, auth):
    _, slots, plans = _seed(client)
    plan_id = plans[0]["id"]
    kinds = client.get(f"{BASE}/kinds").json()
    kind_id = kinds[0]["id"]

    # WTH-Klasse anlegen.
    cls = client.post("/api/classes", json={"name": "9b", "subject": "WTH", "grade": 9})
    assert cls.status_code == 201
    class_id = cls.json()["id"]

    # a) WTH-Klasse ohne Farbe → Fachfarbe orange, Titel endet auf 'WTH', span=2 timeRange.
    client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[1]["id"], "kindId": kind_id,
        "classId": class_id, "weekday": 0, "spanSlots": 2,
    })
    # b) Eintrags-Farbe überschreibt Fachfarbe.
    client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[4]["id"], "kindId": kind_id,
        "classId": class_id, "weekday": 0, "color": "#123456",
    })

    monday = _this_monday().isoformat()
    day0 = client.get(f"{BASE}/resolved", params={"start": monday}).json()["days"][0]["items"]
    assert len(day0) == 2

    by_slot = {it["slotId"]: it for it in day0}
    wth = by_slot[slots[1]["id"]]
    assert wth["color"] == "#f97316"
    assert wth["title"].endswith("WTH")
    assert wth["timeRange"] == "07:30–09:10"     # "1." bis Ende "2." (en-dash)
    assert wth["spanSlots"] == 2

    override = by_slot[slots[4]["id"]]
    assert override["color"] == "#123456"

    # Jedes Item trägt source == 'plan'.
    assert all(it["source"] == "plan" for it in day0)


# ---------------------------------------------------------------- 12) Slot-DELETE CASCADE
def test_slot_delete_cascades_to_entries(client, auth):
    _, slots, plans = _seed(client)
    plan_id = plans[0]["id"]
    kinds = client.get(f"{BASE}/kinds").json()
    kind_id = kinds[0]["id"]

    e1 = client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[2]["id"], "kindId": kind_id, "weekday": 0,
    }).json()
    e2 = client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[6]["id"], "kindId": kind_id, "weekday": 0,
    }).json()

    # Anker-Slot von e1 löschen → e1 verschwindet, e2 bleibt.
    assert client.delete(f"{BASE}/slots/{slots[2]['id']}").status_code == 204
    remaining = {e["id"] for e in client.get(f"{BASE}/entries", params={"planId": plan_id}).json()}
    assert e1["id"] not in remaining
    assert e2["id"] in remaining


# ---------------------------------------------------------------- 13) Tropenplan-Slots (Seed)
def test_tropen_slots_seed_idempotent(client, auth):
    t1 = client.get(f"{BASE}/tropenslots").json()
    t2 = client.get(f"{BASE}/tropenslots").json()
    assert len(t1) == len(t2) == 13

    lessons = [s for s in t1 if s["slotType"] == "lesson"]
    assert [s["label"] for s in lessons] == ["1.", "2.", "3.", "4.", "5.", "6.", "7./8."]
    # Summe covers == Anzahl normaler 'lesson'-Slots (8, siehe DEFAULT_SLOTS).
    assert sum(s["covers"] for s in lessons) == 8
    merged = next(s for s in lessons if s["label"] == "7./8.")
    assert merged["covers"] == 2 and merged["startTime"] == "12:10" and merged["endTime"] == "13:10"

    # Umlaute unverändert.
    assert any(s["label"] == "Frühstückspause" for s in t1)


def test_tropen_slots_crud(client, auth):
    client.get(f"{BASE}/tropenslots")  # Seed auslösen
    created = client.post(f"{BASE}/tropenslots", json={
        "position": 20, "slotType": "lesson", "label": "Test", "startTime": "07:00", "endTime": "07:30",
    })
    assert created.status_code == 201
    sid = created.json()["id"]
    assert created.json()["covers"] == 1

    put = client.put(f"{BASE}/tropenslots/{sid}", json={"label": "Test2", "covers": 2})
    assert put.status_code == 200
    assert put.json()["label"] == "Test2" and put.json()["covers"] == 2

    assert client.delete(f"{BASE}/tropenslots/{sid}").status_code == 204
    assert client.delete(f"{BASE}/tropenslots/{sid}").status_code == 404
    assert client.put(f"{BASE}/tropenslots/{sid}", json={"label": "x"}).status_code == 404


# ---------------------------------------------------------------- 14) Tropentage
def test_tropentag_requires_login(client):
    assert client.put(f"{BASE}/tropentage/2026-01-12", json={"active": True}).status_code == 401


def test_tropentag_invalid_date(client, auth):
    assert client.put(f"{BASE}/tropentage/not-a-date", json={"active": True}).status_code == 400


def test_tropentag_toggle_idempotent(client, auth):
    on = client.put(f"{BASE}/tropentage/2026-01-12", json={"active": True})
    assert on.status_code == 200 and on.json() == {"date": "2026-01-12", "active": True}
    # Zweimal aktivieren (ON CONFLICT DO NOTHING) darf nicht knallen.
    assert client.put(f"{BASE}/tropentage/2026-01-12", json={"active": True}).status_code == 200

    off = client.put(f"{BASE}/tropentage/2026-01-12", json={"active": False})
    assert off.status_code == 200 and off.json() == {"date": "2026-01-12", "active": False}
    # Deaktivieren eines nie gesetzten Tages darf ebenfalls nicht knallen.
    assert client.put(f"{BASE}/tropentage/2026-02-01", json={"active": False}).status_code == 200


# ---------------------------------------------------------------- 15) Resolved: Tropentag-Zeiten
def test_resolved_tropentag_overrides_times(client, auth):
    _, slots, plans = _seed(client)
    plan_id = plans[0]["id"]
    kinds = client.get(f"{BASE}/kinds").json()
    kind_id = kinds[0]["id"]
    client.get(f"{BASE}/tropenslots")  # Tropenplan-Raster seeden

    monday = _this_monday()
    monday_str = monday.isoformat()
    tuesday_str = (monday + datetime.timedelta(days=1)).isoformat()

    # Montag: 1. Stunde (slots[1] = "1.", normal 07:30–08:15) + Doppelstunde 7./8. (slots[9]="7.", span 2).
    e_first = client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[1]["id"], "kindId": kind_id, "weekday": 0,
    }).json()
    e_double = client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[9]["id"], "kindId": kind_id, "weekday": 0, "spanSlots": 2,
    }).json()
    # Dienstag: dieselbe 1. Stunde, aber kein Tropentag → Zeiten bleiben normal.
    client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[1]["id"], "kindId": kind_id, "weekday": 1,
    })

    # Nur Montag als Tropentag markieren.
    assert client.put(f"{BASE}/tropentage/{monday_str}", json={"active": True}).status_code == 200

    r = client.get(f"{BASE}/resolved", params={"start": monday_str}).json()
    mon, tue = r["days"][0], r["days"][1]
    assert mon["date"] == monday_str and mon["isTropentag"] is True
    assert tue["date"] == tuesday_str and tue["isTropentag"] is False

    by_id = {it["entryId"]: it for it in mon["items"]}
    assert by_id[e_first["id"]]["timeRange"] == "07:50–08:20"          # Tropenplan "1."
    assert by_id[e_double["id"]]["timeRange"] == "12:10–13:10"         # 7./8. zusammengelegt

    tue_item = next(it for it in tue["items"] if it["slotId"] == slots[1]["id"])
    assert tue_item["timeRange"] == "07:30–08:15"                      # normaler Klingelplan

    # Tropentag wieder deaktivieren → Montag zeigt wieder normale Zeiten.
    assert client.put(f"{BASE}/tropentage/{monday_str}", json={"active": False}).status_code == 200
    r2 = client.get(f"{BASE}/resolved", params={"start": monday_str}).json()
    mon2 = r2["days"][0]
    assert mon2["isTropentag"] is False
    assert next(it for it in mon2["items"] if it["entryId"] == e_first["id"])["timeRange"] == "07:30–08:15"


# ---------------------------------------------------------------- 16) Overrides (U30: Vertretung)
def test_override_requires_login(client):
    assert client.post(f"{BASE}/overrides", json={
        "date": "2026-01-12", "slotId": 1, "kindId": 1,
    }).status_code == 401
    assert client.delete(f"{BASE}/overrides/1").status_code == 401


def test_override_scoping_unknown_refs(client, auth):
    _, slots, plans = _seed(client)
    kinds = client.get(f"{BASE}/kinds").json()
    good = {"date": "2026-01-12", "slotId": slots[1]["id"], "kindId": kinds[0]["id"]}

    assert client.post(f"{BASE}/overrides", json={**good, "slotId": 99999}).status_code == 404
    assert client.post(f"{BASE}/overrides", json={**good, "kindId": 99999}).status_code == 404
    assert client.post(f"{BASE}/overrides", json={**good, "classId": 99999}).status_code == 404
    assert client.post(f"{BASE}/overrides", json={**good, "date": "not-a-date"}).status_code == 400
    assert client.delete(f"{BASE}/overrides/99999").status_code == 404


def test_override_span_validation(client, auth):
    _, slots, plans = _seed(client)
    kinds = client.get(f"{BASE}/kinds").json()
    over = client.post(f"{BASE}/overrides", json={
        "date": "2026-01-12", "slotId": slots[-1]["id"], "kindId": kinds[0]["id"], "spanSlots": 2,
    })
    assert over.status_code == 400


def test_override_appears_only_in_its_own_week_and_is_deletable(client, auth):
    _, slots, plans = _seed(client)
    kinds = client.get(f"{BASE}/kinds").json()
    kind_id = kinds[0]["id"]

    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8})
    assert cls.status_code == 201
    class_id = cls.json()["id"]

    monday = _this_monday()
    monday_str = monday.isoformat()
    tuesday_str = (monday + datetime.timedelta(days=1)).isoformat()
    next_monday_str = (monday + datetime.timedelta(days=7)).isoformat()

    created = client.post(f"{BASE}/overrides", json={
        "date": tuesday_str, "slotId": slots[1]["id"], "kindId": kind_id,
        "classId": class_id, "room": "204",
    })
    assert created.status_code == 201
    oid = created.json()["id"]
    assert created.json()["date"] == tuesday_str

    # Erscheint in der betroffenen Woche, am richtigen Wochentag, mit source="override".
    week = client.get(f"{BASE}/resolved", params={"start": monday_str}).json()
    tue_items = week["days"][1]["items"]
    assert week["days"][1]["date"] == tuesday_str
    assert len(tue_items) == 1
    item = tue_items[0]
    assert item["entryId"] == oid
    assert item["source"] == "override"
    assert item["title"].endswith("Deutsch")
    assert item["subtitle"] == "204"
    # Alle anderen Tage dieser Woche bleiben leer.
    assert all(len(d["items"]) == 0 for d in week["days"] if d["date"] != tuesday_str)

    # Erscheint NICHT in der Folgewoche (kein wiederkehrender Eintrag).
    next_week = client.get(f"{BASE}/resolved", params={"start": next_monday_str}).json()
    assert all(len(d["items"]) == 0 for d in next_week["days"])

    # Löschen → verschwindet aus der Woche.
    assert client.delete(f"{BASE}/overrides/{oid}").status_code == 204
    week2 = client.get(f"{BASE}/resolved", params={"start": monday_str}).json()
    assert all(len(d["items"]) == 0 for d in week2["days"])
    assert client.delete(f"{BASE}/overrides/{oid}").status_code == 404


def test_override_and_plan_entry_merge_same_day(client, auth):
    """Ein Override an einem Tag mit bestehendem wiederkehrendem Eintrag ergänzt (verdrängt nicht)."""
    _, slots, plans = _seed(client)
    plan_id = plans[0]["id"]
    kinds = client.get(f"{BASE}/kinds").json()
    kind_id = kinds[0]["id"]

    monday_str = _this_monday().isoformat()
    entry = client.post(f"{BASE}/entries", json={
        "planId": plan_id, "slotId": slots[1]["id"], "kindId": kind_id, "weekday": 0,
    }).json()
    override = client.post(f"{BASE}/overrides", json={
        "date": monday_str, "slotId": slots[4]["id"], "kindId": kind_id, "label": "Vertretung Bio",
    }).json()

    mon_items = client.get(f"{BASE}/resolved", params={"start": monday_str}).json()["days"][0]["items"]
    assert len(mon_items) == 2
    by_source = {it["source"]: it for it in mon_items}
    assert by_source["plan"]["entryId"] == entry["id"]
    assert by_source["override"]["entryId"] == override["id"]
    assert by_source["override"]["title"] == "Vertretung Bio"
    # Nach Slot-Position sortiert (1. vor 3.).
    assert [it["source"] for it in mon_items] == ["plan", "override"]
