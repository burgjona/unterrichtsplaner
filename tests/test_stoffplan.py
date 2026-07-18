"""Stoffplan-Persistenz (U12): speichern, laden, bearbeiten, aktiv-Regel, löschen."""


def _class(client, name="7a"):
    r = client.post("/api/classes",
                    json={"name": name, "subject": "Deutsch", "grade": 7, "weeklyHours": 2})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _year(client, label="2025/26"):
    r = client.post("/api/school-years",
                    json={"label": label, "startDate": "2025-08-01", "endDate": "2026-07-31"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _blocks():
    return [
        {"lbCode": "LB3", "title": "Lesen", "ustd": 20,
         "startDate": "2025-09-01", "endDate": "2025-10-10"},
        {"lbCode": "LB4", "title": "Schreiben", "ustd": 25,
         "startDate": "2025-10-20", "endDate": "2025-12-15"},
    ]


def test_create_and_get_detail(client, auth):
    cid, syid = _class(client), _year(client)
    r = client.post("/api/stoff-plans",
                    json={"classId": cid, "schoolYearId": syid,
                          "title": "Stoffplan 7a", "blocks": _blocks()})
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["status"] == "entwurf"          # Default
    assert plan["classId"] == cid and plan["schoolYearId"] == syid
    assert len(plan["blocks"]) == 2
    assert plan["blocks"][0]["lbCode"] == "LB3"  # camelCase + Reihenfolge

    # Detail-Abruf liefert Blöcke in Reihenfolge
    detail = client.get(f"/api/stoff-plans/{plan['id']}").json()
    assert [b["title"] for b in detail["blocks"]] == ["Lesen", "Schreiben"]


def test_list_scoped_by_class(client, auth):
    cid1, cid2 = _class(client, "7a"), _class(client, "8b")
    client.post("/api/stoff-plans", json={"classId": cid1, "title": "P1", "blocks": []})
    client.post("/api/stoff-plans", json={"classId": cid2, "title": "P2", "blocks": []})
    rows = client.get(f"/api/stoff-plans?classId={cid1}").json()
    assert len(rows) == 1 and rows[0]["title"] == "P1"
    assert rows[0]["blockCount"] == 0


def test_update_title_and_blocks(client, auth):
    cid = _class(client)
    pid = client.post("/api/stoff-plans",
                      json={"classId": cid, "title": "Alt", "blocks": _blocks()}).json()["id"]
    new_blocks = [{"lbCode": "LB5", "title": "Medien", "ustd": 15,
                   "startDate": "2026-01-10", "endDate": "2026-02-20"}]
    r = client.put(f"/api/stoff-plans/{pid}", json={"title": "Neu", "blocks": new_blocks})
    assert r.status_code == 200
    plan = r.json()
    assert plan["title"] == "Neu"
    assert len(plan["blocks"]) == 1 and plan["blocks"][0]["startDate"] == "2026-01-10"


def test_single_active_per_class_and_year(client, auth):
    cid, syid = _class(client), _year(client)
    p1 = client.post("/api/stoff-plans",
                     json={"classId": cid, "schoolYearId": syid, "title": "P1",
                           "status": "aktiv", "blocks": []}).json()
    assert p1["status"] == "aktiv"
    # Zweiten Plan aktiv setzen → erster fällt auf 'entwurf' zurück
    p2 = client.post("/api/stoff-plans",
                     json={"classId": cid, "schoolYearId": syid, "title": "P2",
                           "status": "aktiv", "blocks": []}).json()
    assert p2["status"] == "aktiv"
    assert client.get(f"/api/stoff-plans/{p1['id']}").json()["status"] == "entwurf"


def test_activate_via_put_deactivates_sibling(client, auth):
    cid, syid = _class(client), _year(client)
    p1 = client.post("/api/stoff-plans",
                     json={"classId": cid, "schoolYearId": syid, "title": "P1",
                           "status": "aktiv", "blocks": []}).json()
    p2 = client.post("/api/stoff-plans",
                     json={"classId": cid, "schoolYearId": syid, "title": "P2", "blocks": []}).json()
    client.put(f"/api/stoff-plans/{p2['id']}", json={"status": "aktiv"})
    assert client.get(f"/api/stoff-plans/{p1['id']}").json()["status"] == "entwurf"
    assert client.get(f"/api/stoff-plans/{p2['id']}").json()["status"] == "aktiv"


def test_delete(client, auth):
    cid = _class(client)
    pid = client.post("/api/stoff-plans",
                      json={"classId": cid, "title": "Weg", "blocks": _blocks()}).json()["id"]
    assert client.delete(f"/api/stoff-plans/{pid}").status_code == 204
    assert client.get(f"/api/stoff-plans/{pid}").status_code == 404


def test_invalid_status_rejected(client, auth):
    cid = _class(client)
    r = client.post("/api/stoff-plans",
                    json={"classId": cid, "title": "X", "status": "quatsch", "blocks": []})
    assert r.status_code == 422


def test_foreign_class_rejected(client, auth):
    r = client.post("/api/stoff-plans", json={"classId": 9999, "title": "X", "blocks": []})
    assert r.status_code == 404


def test_requires_login(client):
    assert client.get("/api/stoff-plans").status_code == 401
