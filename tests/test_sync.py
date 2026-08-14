"""Offline-Sync (Fundament, F6-Beweis): Migration, /api/sync/changes, /api/sync/push,
Konflikterkennung — nur für die Beweis-Entität notes (siehe Plan „Offline-Modus mit
Synchronisation"). Weitere Entitäten kommen erst in der Rollout-Phase dazu.
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
    assert client.get("/api/sync/changes?since=0").json()["changes"] == []
    note = client.post("/api/notes", json={"scope": "allgemein", "bodyMd": "hallo"}).json()

    data = client.get("/api/sync/changes?since=0").json()
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
