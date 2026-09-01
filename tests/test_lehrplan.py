"""Lehrplan-Abhakmodul: Checkliste je Klasse + Abhak-Status."""
import sqlite3

import pytest

from src.seed import seed_lehrplan_ziele, seed_lernbereiche


@pytest.fixture
def seeded(app):
    conn = sqlite3.connect(app.state.db_path)
    seed_lernbereiche(conn)
    seed_lehrplan_ziele(conn)
    conn.close()
    return app


def _make_class(client, **over):
    body = {"name": "8b", "subject": "Deutsch", "grade": 8, "track": "RS", "weeklyHours": 4}
    body.update(over)
    r = client.post("/api/classes", json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_checklist_matches_class_scope(seeded, client, auth):
    cid = _make_class(client, grade=8, track="RS")
    r = client.get("/api/lehrplan/checklist", params={"classId": cid})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["subject"] == "Deutsch" and data["grade"] == 8 and data["track"] == "RS"
    assert len(data["ziele"]) == 4
    assert [z["text"] for z in data["ziele"]][0] == "Entwickeln des Leseverstehens"
    assert len(data["lernbereiche"]) == 6
    assert all(z["checkedAt"] is None for z in data["ziele"])
    assert data["lernbereiche"][0]["richtwertUstd"] is not None


def test_check_toggle_roundtrip(seeded, client, auth):
    cid = _make_class(client)
    lb = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()["lernbereiche"][0]

    r = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "lb", "itemRef": lb["id"], "checked": True})
    assert r.status_code == 200, r.text
    assert r.json()["checked"] is True and r.json()["checkedAt"]

    data = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()
    hit = next(x for x in data["lernbereiche"] if x["id"] == lb["id"])
    assert hit["checkedAt"] is not None

    # Erneut True => idempotent (kein zweiter Datensatz, checkedAt bleibt)
    r2 = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "lb", "itemRef": lb["id"], "checked": True})
    assert r2.json()["checkedAt"] == r.json()["checkedAt"]

    # Abwaehlen
    r3 = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "lb", "itemRef": lb["id"], "checked": False})
    assert r3.json()["checked"] is False and r3.json()["checkedAt"] is None
    data = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()
    assert next(x for x in data["lernbereiche"] if x["id"] == lb["id"])["checkedAt"] is None


def test_check_ziel_and_scoping(seeded, client, auth):
    cid = _make_class(client)
    ziel = client.get("/api/lehrplan/checklist", params={"classId": cid}).json()["ziele"][0]
    r = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "ziel", "itemRef": ziel["id"], "checked": True})
    assert r.status_code == 200 and r.json()["checked"] is True

    # Andere Klasse (anderes Schuljahr / anderer Kurs) startet leer
    cid2 = _make_class(client, name="8c")
    data2 = client.get("/api/lehrplan/checklist", params={"classId": cid2}).json()
    assert all(z["checkedAt"] is None for z in data2["ziele"])


def test_check_rejects_out_of_scope_ref(seeded, client, auth):
    d8 = _make_class(client, name="8b", grade=8, track="RS")
    d7 = _make_class(client, name="7a", grade=7, track="RS")
    # LB aus Klasse 7 gegen Klasse 8 abhaken -> 404
    lb7 = client.get("/api/lehrplan/checklist", params={"classId": d7}).json()["lernbereiche"][0]
    r = client.put("/api/lehrplan/checks", json={
        "classId": d8, "itemType": "lb", "itemRef": lb7["id"], "checked": True})
    assert r.status_code == 404


def test_unknown_class_404(seeded, client, auth):
    assert client.get("/api/lehrplan/checklist", params={"classId": 999999}).status_code == 404
    r = client.put("/api/lehrplan/checks", json={
        "classId": 999999, "itemType": "lb", "itemRef": 1, "checked": True})
    assert r.status_code == 404


def test_bad_item_type_422(seeded, client, auth):
    cid = _make_class(client)
    r = client.put("/api/lehrplan/checks", json={
        "classId": cid, "itemType": "quatsch", "itemRef": 1, "checked": True})
    assert r.status_code == 422


def test_requires_auth(seeded, client):
    assert client.get("/api/lehrplan/checklist", params={"classId": 1}).status_code == 401
