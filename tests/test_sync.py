"""Offline-Sync: Migration, /api/sync/changes, /api/sync/push, Konflikterkennung.
Fundament-Beweis an notes (siehe Plan „Offline-Modus mit Synchronisation"); Rollout-Tranche 1
fügt todos hinzu (unten) — beide Entitäten teilen sich den generischen sync.py-Router, daher
wird die Kernlogik (Push-Konflikt, Cursor, unbekannte Entität) nur einmal an notes geprüft und
bei todos nur noch auf das Trigger-/Schema-Setup sowie den Lifecycle fokussiert.
"""
from src.db import init_db


def _make_user(conn):
    cur = conn.execute(
        "INSERT INTO users(email, password_hash, display_name) VALUES ('a@b.de','x','A')"
    )
    conn.commit()
    return cur.lastrowid


def test_migration_adds_updated_at_to_all_target_tables(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    for table in [
        "school_years", "todos", "school_dates", "calendar_categories", "students",
        "timetable_kinds", "timetable_slots", "timetable_plans", "timetable_overrides",
        "tropenplan_slots", "tropentage",
    ]:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert "updated_at" in cols, f"{table} fehlt updated_at"
    conn.close()


def test_sync_log_table_and_notes_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "sync_log" in names
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"trg_synclog_notes_ai", "trg_synclog_notes_au", "trg_synclog_notes_ad"} <= triggers
    conn.close()


def test_sync_log_populated_by_direct_rest_writes(tmp_path):
    # Trigger feuern unabhängig vom Aufrufer (Router-Endpunkt ODER Sync-Push) — hier über
    # den ganz normalen REST-Endpunkt, nicht über sync.py, um genau das zu beweisen.
    conn = init_db(str(tmp_path / "schema.db"))
    uid = _make_user(conn)
    conn.execute(
        "INSERT INTO notes(user_id, scope, body_md) VALUES (?, 'allgemein', 'x')", (uid,)
    )
    conn.commit()
    nid = conn.execute("SELECT id FROM notes").fetchone()[0]
    conn.execute("UPDATE notes SET body_md='y', updated_at=datetime('now') WHERE id=?", (nid,))
    conn.execute("DELETE FROM notes WHERE id=?", (nid,))
    conn.commit()
    rows = [tuple(r) for r in conn.execute(
        "SELECT entity_type, entity_id, op FROM sync_log ORDER BY seq"
    )]
    assert rows == [("notes", nid, "upsert"), ("notes", nid, "upsert"), ("notes", nid, "delete")]
    conn.close()


def test_sync_endpoints_require_login(client):
    assert client.get("/api/sync/changes").status_code == 401
    assert client.post("/api/sync/push", json={"mutations": []}).status_code == 401


def test_changes_reflects_direct_rest_create(client, auth):
    # entities=notes filtert die 3 bei der Registrierung geseedeten Standard-Kalender-
    # Kategorien heraus (siehe auth.py: Seeding lief früher lazy im GET-Endpunkt, jetzt bei
    # der Registrierung, da das Frontend Kategorien nur noch über die Sync-Engine liest).
    assert client.get("/api/sync/changes?since=0&entities=notes").json()["changes"] == []
    note = client.post("/api/notes", json={"scope": "allgemein", "bodyMd": "hallo"}).json()

    data = client.get("/api/sync/changes?since=0&entities=notes").json()
    assert len(data["changes"]) == 1
    change = data["changes"][0]
    assert change["op"] == "upsert"
    assert change["entityType"] == "notes"
    assert change["entity"]["bodyMd"] == "hallo"
    assert data["nextCursor"] >= 1
    assert data["hasMore"] is False


def test_push_create_update_delete_lifecycle(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "notes", "op": "create",
        "payload": {"scope": "allgemein", "bodyMd": "via sync"},
    }]})
    assert r.status_code == 200
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    note_id = result["entityId"]
    base_updated = result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "notes", "op": "update", "entityId": note_id,
        "baseUpdatedAt": base_updated, "payload": {"bodyMd": "geändert via sync"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["bodyMd"] == "geändert via sync"
    new_updated = result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "notes", "op": "delete", "entityId": note_id,
        "baseUpdatedAt": new_updated,
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    assert client.get("/api/notes").json() == []


def test_push_detects_conflict_and_manual_resolution(client, auth):
    # Zwei "Geräte": ein zweiter TestClient mit eigenem Cookie-Jar, eingeloggt als
    # derselbe (einzige) Nutzer — Single-Tenant-Multi-Device-Szenario laut Plan.
    from fastapi.testclient import TestClient
    device_b = TestClient(client.app)
    device_b.post("/api/auth/login", json={"email": "ref@stolpen.de", "password": "Geheim1234!"})

    created = client.post("/api/notes", json={"scope": "allgemein", "bodyMd": "v1"}).json()
    note_id, base_updated = created["id"], created["updatedAt"]

    # Gerät B pusht zuerst erfolgreich.
    r = device_b.post("/api/sync/push", json={"mutations": [{
        "clientId": "locB", "entityType": "notes", "op": "update", "entityId": note_id,
        "baseUpdatedAt": base_updated, "payload": {"bodyMd": "von Gerät B"},
    }]})
    assert r.json()["results"][0]["status"] == "applied"

    # Gerät A pusht mit der jetzt veralteten Basis -> Konflikt, KEIN automatisches
    # Last-Write-Wins, Server-Version wird mitgeliefert für die manuelle Auflösung.
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "locA", "entityType": "notes", "op": "update", "entityId": note_id,
        "baseUpdatedAt": base_updated, "payload": {"bodyMd": "von Gerät A"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["bodyMd"] == "von Gerät B"
    assert client.get("/api/notes").json()[0]["bodyMd"] == "von Gerät B"  # kein Datenverlust

    # Nutzer entscheidet "meine Version behalten": erneuter Push mit server.updatedAt als Basis.
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "locA2", "entityType": "notes", "op": "update", "entityId": note_id,
        "baseUpdatedAt": result["serverEntity"]["updatedAt"], "payload": {"bodyMd": "von Gerät A"},
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    assert client.get("/api/notes").json()[0]["bodyMd"] == "von Gerät A"


def test_push_delete_conflict_when_already_deleted_on_server(client, auth):
    created = client.post("/api/notes", json={"scope": "allgemein", "bodyMd": "v1"}).json()
    note_id, base_updated = created["id"], created["updatedAt"]
    assert client.delete(f"/api/notes/{note_id}").status_code == 204

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "notes", "op": "update", "entityId": note_id,
        "baseUpdatedAt": base_updated, "payload": {"bodyMd": "zu spät"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"] is None


def test_push_unknown_entity_type_returns_error_not_crash(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "ghosts", "op": "create", "payload": {},
    }]})
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "error"


def test_changes_pagination_cursor_advances(client, auth):
    for i in range(3):
        client.post("/api/notes", json={"scope": "allgemein", "bodyMd": f"n{i}"})
    first = client.get("/api/sync/changes?since=0&entities=notes").json()
    assert len(first["changes"]) == 3
    cursor = first["nextCursor"]
    assert client.get(f"/api/sync/changes?since={cursor}").json()["changes"] == []


def test_changes_filters_by_entities_param(client, auth):
    client.post("/api/notes", json={"scope": "allgemein", "bodyMd": "x"})
    assert client.get("/api/sync/changes?since=0&entities=lessons").json()["changes"] == []
    assert len(client.get("/api/sync/changes?since=0&entities=notes").json()["changes"]) == 1


# ---------- Rollout Tranche 1: todos ----------

def test_sync_log_table_and_todos_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"trg_synclog_todos_ai", "trg_synclog_todos_au", "trg_synclog_todos_ad"} <= triggers
    conn.close()


def test_todos_push_create_update_delete_lifecycle(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "todos", "op": "create",
        "payload": {"text": "Kopien vorbereiten", "source": "manuell"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["done"] is False
    todo_id, base_updated = result["entityId"], result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "todos", "op": "update", "entityId": todo_id,
        "baseUpdatedAt": base_updated, "payload": {"done": True},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["done"] is True

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "todos", "op": "delete", "entityId": todo_id,
        "baseUpdatedAt": result["entity"]["updatedAt"],
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    assert client.get("/api/todos").json() == []


def test_todos_push_detects_conflict(client, auth):
    created = client.post("/api/todos", json={"text": "x"}).json()
    tid, base_updated = created["id"], created["updatedAt"]
    assert client.put(f"/api/todos/{tid}", json={"done": True}).status_code == 200

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "todos", "op": "update", "entityId": tid,
        "baseUpdatedAt": base_updated, "payload": {"text": "zu spät geändert"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["done"] is True


# ---------- Rollout Tranche 1: calendar_categories ----------

def test_sync_log_table_and_calendar_categories_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {
        "trg_synclog_calendar_categories_ai",
        "trg_synclog_calendar_categories_au",
        "trg_synclog_calendar_categories_ad",
    } <= triggers
    conn.close()


def test_calendar_categories_push_create_update_delete_lifecycle(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "calendar_categories", "op": "create",
        "payload": {"name": "Elternabend", "color": "#123456"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    cid, base_updated = result["entityId"], result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "calendar_categories", "op": "update", "entityId": cid,
        "baseUpdatedAt": base_updated, "payload": {"color": "#abcdef"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["color"] == "#abcdef"

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "calendar_categories", "op": "delete", "entityId": cid,
        "baseUpdatedAt": result["entity"]["updatedAt"],
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    names = [c["name"] for c in client.get("/api/calendar-categories").json()]
    assert "Elternabend" not in names


def test_calendar_categories_push_detects_conflict(client, auth):
    created = client.post("/api/calendar-categories", json={"name": "x", "color": "#000000"}).json()
    cid, base_updated = created["id"], created["updatedAt"]
    assert client.put(f"/api/calendar-categories/{cid}", json={"color": "#111111"}).status_code == 200

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "calendar_categories", "op": "update", "entityId": cid,
        "baseUpdatedAt": base_updated, "payload": {"color": "#zu-spaet"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["color"] == "#111111"


# ---------- Rollout Tranche 1: school_years ----------

def test_sync_log_table_and_school_years_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {
        "trg_synclog_school_years_ai",
        "trg_synclog_school_years_au",
        "trg_synclog_school_years_ad",
    } <= triggers
    conn.close()


def test_school_years_push_create_update_delete_lifecycle(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "school_years", "op": "create",
        "payload": {"label": "2026/2027", "startDate": "2026-08-01", "endDate": "2027-07-31"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    sid, base_updated = result["entityId"], result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "school_years", "op": "update", "entityId": sid,
        "baseUpdatedAt": base_updated, "payload": {"label": "2026/2027 (korrigiert)"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["label"] == "2026/2027 (korrigiert)"

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "school_years", "op": "delete", "entityId": sid,
        "baseUpdatedAt": result["entity"]["updatedAt"],
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    assert client.get("/api/school-years").json() == []


def test_school_years_push_detects_conflict(client, auth):
    created = client.post("/api/school-years", json={
        "label": "2026/2027", "startDate": "2026-08-01", "endDate": "2027-07-31",
    }).json()
    sid, base_updated = created["id"], created["updatedAt"]
    assert client.put(f"/api/school-years/{sid}", json={"label": "geaendert"}).status_code == 200

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "school_years", "op": "update", "entityId": sid,
        "baseUpdatedAt": base_updated, "payload": {"label": "zu spaet"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["label"] == "geaendert"


# ---------- Rollout Tranche 1: plan_notes (natürlicher Schlüssel statt sichtbarer id) ----------

def test_sync_log_table_and_plan_notes_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {
        "trg_synclog_plan_notes_ai",
        "trg_synclog_plan_notes_au",
        "trg_synclog_plan_notes_ad",
    } <= triggers
    conn.close()


def _make_class_and_year(client):
    sy = client.post("/api/school-years", json={
        "label": "2026/2027", "startDate": "2026-08-01", "endDate": "2027-07-31",
    }).json()
    cls = client.post("/api/classes", json={
        "name": "8a", "subject": "Deutsch", "grade": 8, "schoolYearId": sy["id"], "weeklyHours": 4,
    }).json()
    return cls["id"], sy["id"]


def test_plan_notes_get_has_null_id_when_no_row_yet(client, auth):
    cls_id, sy_id = _make_class_and_year(client)
    r = client.get(f"/api/planning/notes?classId={cls_id}&schoolYearId={sy_id}")
    assert r.status_code == 200
    assert r.json()["id"] is None
    assert r.json()["text"] == ""


def test_plan_notes_push_create_update_delete_lifecycle(client, auth):
    cls_id, sy_id = _make_class_and_year(client)
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "plan_notes", "op": "create",
        "payload": {"classId": cls_id, "schoolYearId": sy_id, "text": "Projektwoche im Mai"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    pid, base_updated = result["entityId"], result["entity"]["updatedAt"]
    assert client.get(
        f"/api/planning/notes?classId={cls_id}&schoolYearId={sy_id}"
    ).json()["id"] == pid

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "plan_notes", "op": "update", "entityId": pid,
        "baseUpdatedAt": base_updated, "payload": {"text": "Lektüre im Herbst"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["text"] == "Lektüre im Herbst"

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "plan_notes", "op": "delete", "entityId": pid,
        "baseUpdatedAt": result["entity"]["updatedAt"],
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    assert client.get(
        f"/api/planning/notes?classId={cls_id}&schoolYearId={sy_id}"
    ).json()["id"] is None


def test_plan_notes_push_detects_update_conflict(client, auth):
    cls_id, sy_id = _make_class_and_year(client)
    created = client.put("/api/planning/notes", json={
        "classId": cls_id, "schoolYearId": sy_id, "text": "v1",
    }).json()
    pid, base_updated = created["id"], created["updatedAt"]
    assert client.put("/api/planning/notes", json={
        "classId": cls_id, "schoolYearId": sy_id, "text": "von Gerät B",
    }).status_code == 200

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "plan_notes", "op": "update", "entityId": pid,
        "baseUpdatedAt": base_updated, "payload": {"text": "zu spaet von Gerät A"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["text"] == "von Gerät B"


def test_plan_notes_double_create_race_is_error_not_silent_overwrite(client, auth):
    # Zwei Geräte legen offline beide die ERSTE Notiz für dieselbe Klasse/Schuljahr an, ohne
    # vorher voneinander zu wissen - das zweite INSERT darf die erste Version nicht still
    # überschreiben (anders als beim alten Upsert-Endpunkt), sondern muss klar fehlschlagen.
    cls_id, sy_id = _make_class_and_year(client)
    r1 = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "locA", "entityType": "plan_notes", "op": "create",
        "payload": {"classId": cls_id, "schoolYearId": sy_id, "text": "von Gerät A"},
    }]})
    assert r1.json()["results"][0]["status"] == "applied"

    r2 = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "locB", "entityType": "plan_notes", "op": "create",
        "payload": {"classId": cls_id, "schoolYearId": sy_id, "text": "von Gerät B"},
    }]})
    result2 = r2.json()["results"][0]
    assert result2["status"] == "error"
    assert client.get(
        f"/api/planning/notes?classId={cls_id}&schoolYearId={sy_id}"
    ).json()["text"] == "von Gerät A"


# ---------- Rollout Tranche 1: timetable_kinds ----------

def test_sync_log_table_and_timetable_kinds_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {
        "trg_synclog_timetable_kinds_ai",
        "trg_synclog_timetable_kinds_au",
        "trg_synclog_timetable_kinds_ad",
    } <= triggers
    conn.close()


def test_timetable_kinds_push_create_update_delete_lifecycle(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "timetable_kinds", "op": "create",
        "payload": {"name": "Aufsicht", "color": "#123456", "sortOrder": 5},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["isDefault"] is False
    kid, base_updated = result["entityId"], result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "timetable_kinds", "op": "update", "entityId": kid,
        "baseUpdatedAt": base_updated, "payload": {"name": "Pausenaufsicht"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["name"] == "Pausenaufsicht"

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "timetable_kinds", "op": "delete", "entityId": kid,
        "baseUpdatedAt": result["entity"]["updatedAt"],
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    assert kid not in [k["id"] for k in client.get("/api/stundenplan/kinds").json()]


def test_timetable_kinds_push_detects_conflict(client, auth):
    created = client.post("/api/stundenplan/kinds", json={"name": "x", "color": "#000000"}).json()
    kid, base_updated = created["id"], created["updatedAt"]
    assert client.put(f"/api/stundenplan/kinds/{kid}", json={"color": "#111111"}).status_code == 200

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "timetable_kinds", "op": "update", "entityId": kid,
        "baseUpdatedAt": base_updated, "payload": {"color": "#zu-spaet"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["color"] == "#111111"


def test_timetable_kinds_push_delete_default_is_error(client, auth):
    # Seeding laeuft beim ersten GET (list_kinds/resolved) - hier ueber den bestehenden
    # REST-Endpunkt ausloesen, um den echten Default-Typ zu bekommen.
    kinds = client.get("/api/stundenplan/kinds").json()
    default_kind = next(k for k in kinds if k["isDefault"])

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "timetable_kinds", "op": "delete",
        "entityId": default_kind["id"], "baseUpdatedAt": default_kind["updatedAt"],
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "error"
    assert "Standard-Typ" in result["detail"]


# ---------- Rollout Tranche 1: timetable_slots ----------

def test_sync_log_table_and_timetable_slots_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {
        "trg_synclog_timetable_slots_ai",
        "trg_synclog_timetable_slots_au",
        "trg_synclog_timetable_slots_ad",
    } <= triggers
    conn.close()


def test_timetable_slots_push_create_update_delete_lifecycle(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "timetable_slots", "op": "create",
        "payload": {
            "position": 20, "slotType": "lesson", "label": "9. Stunde",
            "startTime": "15:00", "endTime": "15:45",
        },
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    sid, base_updated = result["entityId"], result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "timetable_slots", "op": "update", "entityId": sid,
        "baseUpdatedAt": base_updated, "payload": {"label": "9. Stunde (spät)"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["label"] == "9. Stunde (spät)"

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "timetable_slots", "op": "delete", "entityId": sid,
        "baseUpdatedAt": result["entity"]["updatedAt"],
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    assert sid not in [s["id"] for s in client.get("/api/stundenplan/slots").json()]


def test_timetable_slots_push_detects_conflict(client, auth):
    created = client.post("/api/stundenplan/slots", json={
        "position": 21, "slotType": "lesson", "label": "x", "startTime": "16:00", "endTime": "16:45",
    }).json()
    sid, base_updated = created["id"], created["updatedAt"]
    assert client.put(f"/api/stundenplan/slots/{sid}", json={"label": "geaendert"}).status_code == 200

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "timetable_slots", "op": "update", "entityId": sid,
        "baseUpdatedAt": base_updated, "payload": {"label": "zu spaet"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["label"] == "geaendert"


# ---------- Rollout Tranche 1: tropenplan_slots (letzte Einheit) ----------
# tropentage (Kompensationstage-Toggle) bleibt bewusst online-only (reiner Existenz-Toggle
# ohne Inhalt, siehe Rückfrage an den Nutzer) — kein Test dafür hier nötig.

def test_sync_log_table_and_tropenplan_slots_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {
        "trg_synclog_tropenplan_slots_ai",
        "trg_synclog_tropenplan_slots_au",
        "trg_synclog_tropenplan_slots_ad",
    } <= triggers
    conn.close()


def test_tropenplan_slots_push_create_update_delete_lifecycle(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "tropenplan_slots", "op": "create",
        "payload": {
            "position": 20, "slotType": "lesson", "label": "T9",
            "startTime": "13:00", "endTime": "13:35", "covers": 1,
        },
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    sid, base_updated = result["entityId"], result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "tropenplan_slots", "op": "update", "entityId": sid,
        "baseUpdatedAt": base_updated, "payload": {"covers": 2},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["covers"] == 2

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "tropenplan_slots", "op": "delete", "entityId": sid,
        "baseUpdatedAt": result["entity"]["updatedAt"],
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    assert sid not in [s["id"] for s in client.get("/api/stundenplan/tropenslots").json()]


def test_tropenplan_slots_push_detects_conflict(client, auth):
    created = client.post("/api/stundenplan/tropenslots", json={
        "position": 21, "slotType": "lesson", "label": "x",
        "startTime": "14:00", "endTime": "14:35", "covers": 1,
    }).json()
    sid, base_updated = created["id"], created["updatedAt"]
    assert client.put(f"/api/stundenplan/tropenslots/{sid}", json={"label": "geaendert"}).status_code == 200

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "tropenplan_slots", "op": "update", "entityId": sid,
        "baseUpdatedAt": base_updated, "payload": {"label": "zu spaet"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["label"] == "geaendert"


# ---------- Rollout Tranche 2: classes ----------

def test_sync_log_table_and_classes_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {
        "trg_synclog_classes_ai",
        "trg_synclog_classes_au",
        "trg_synclog_classes_ad",
    } <= triggers
    conn.close()


def test_classes_push_create_update_archive_lifecycle(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "classes", "op": "create",
        "payload": {"name": "8a", "subject": "Deutsch", "grade": 8},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["archivedAt"] is None
    cid, base_updated = result["entityId"], result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "classes", "op": "update", "entityId": cid,
        "baseUpdatedAt": base_updated, "payload": {"weeklyHours": 5},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["weeklyHours"] == 5

    # 'delete' bildet auf Soft-Archiv ab, nicht auf Hard-Delete.
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "classes", "op": "delete", "entityId": cid,
        "baseUpdatedAt": result["entity"]["updatedAt"],
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert cid not in [c["id"] for c in client.get("/api/classes").json()]
    archived = [c for c in client.get("/api/classes?includeArchived=true").json() if c["id"] == cid]
    assert len(archived) == 1
    assert archived[0]["archivedAt"] is not None


def test_classes_push_detects_conflict(client, auth):
    created = client.post("/api/classes", json={"name": "x", "subject": "WTH", "grade": 9}).json()
    cid, base_updated = created["id"], created["updatedAt"]
    assert client.put(f"/api/classes/{cid}", json={"name": "geaendert"}).status_code == 200

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "classes", "op": "update", "entityId": cid,
        "baseUpdatedAt": base_updated, "payload": {"name": "zu spaet"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["name"] == "geaendert"


def test_classes_hard_delete_and_restore_stay_rest_only(client, auth):
    # Nicht Teil des generischen Sync-Modells (siehe Kommentar in classes.py) — hier nur
    # verifizieren, dass die bestehenden REST-Endpunkte durch den Refactor unverändert
    # funktionieren.
    created = client.post("/api/classes", json={"name": "x", "subject": "Deutsch", "grade": 7}).json()
    cid = created["id"]
    assert client.delete(f"/api/classes/{cid}").status_code == 204  # soft
    assert client.post(f"/api/classes/{cid}/restore").status_code == 200
    assert client.delete(f"/api/classes/{cid}?hard=true").status_code == 204
    assert client.get("/api/classes?includeArchived=true").json() == []


# ---------- Rollout Tranche 2: students ----------

def test_sync_log_table_and_students_triggers_exist(tmp_path):
    conn = init_db(str(tmp_path / "schema.db"))
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {
        "trg_synclog_students_ai",
        "trg_synclog_students_au",
        "trg_synclog_students_ad",
    } <= triggers
    conn.close()


def test_students_push_create_update_delete_lifecycle(client, auth):
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8}).json()

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "students", "op": "create",
        "payload": {"classId": cls["id"], "name": "Max"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["sortOrder"] == 0
    sid, base_updated = result["entityId"], result["entity"]["updatedAt"]

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_2", "entityType": "students", "op": "update", "entityId": sid,
        "baseUpdatedAt": base_updated, "payload": {"name": "Maximilian"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "applied"
    assert result["entity"]["name"] == "Maximilian"

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_3", "entityType": "students", "op": "delete", "entityId": sid,
        "baseUpdatedAt": result["entity"]["updatedAt"],
    }]})
    assert r.json()["results"][0]["status"] == "applied"
    assert client.get(f"/api/classes/{cls['id']}/students").json() == []


def test_students_push_detects_conflict(client, auth):
    cls = client.post("/api/classes", json={"name": "8a", "subject": "Deutsch", "grade": 8}).json()
    created = client.post(f"/api/classes/{cls['id']}/students", json={"name": "x"}).json()
    sid, base_updated = created["id"], created["updatedAt"]
    assert client.put(f"/api/students/{sid}", json={"name": "geaendert"}).status_code == 200

    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "students", "op": "update", "entityId": sid,
        "baseUpdatedAt": base_updated, "payload": {"name": "zu spaet"},
    }]})
    result = r.json()["results"][0]
    assert result["status"] == "conflict"
    assert result["serverEntity"]["name"] == "geaendert"


def test_students_push_create_unknown_class_is_error(client, auth):
    r = client.post("/api/sync/push", json={"mutations": [{
        "clientId": "loc_1", "entityType": "students", "op": "create",
        "payload": {"classId": 999999, "name": "Phantom"},
    }]})
    assert r.json()["results"][0]["status"] == "error"
