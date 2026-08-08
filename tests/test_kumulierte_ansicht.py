"""Kumulierte Ansicht: Stoffplan-Blöcke inkl. Sequenzstunden (GET /combined) + PDF-Export."""


def _class(client, name="7a"):
    r = client.post("/api/classes",
                    json={"name": name, "subject": "Deutsch", "grade": 7, "weeklyHours": 2})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _plan(client, cid, title="Stoffplan 7a"):
    body = {"classId": cid, "title": title, "blocks": [
        {"lbCode": "LB3", "title": "Balladen lesen", "ustd": 20,
         "startDate": "2025-09-01", "endDate": "2025-10-10"},
        {"lbCode": "LB4", "title": "Erörterung üben", "ustd": 25,
         "startDate": "2025-10-20", "endDate": "2025-12-15"},
    ]}
    r = client.post("/api/stoff-plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _stunde(client, block_id, title="Stunde 1", **extra):
    body = {"blockId": block_id, "title": title, **extra}
    r = client.post("/api/sequenz-stunden", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_combined_nests_stunden_under_blocks(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    b3 = next(b["id"] for b in plan["blocks"] if b["lbCode"] == "LB3")
    b4 = next(b["id"] for b in plan["blocks"] if b["lbCode"] == "LB4")
    _stunde(client, b3, "Einstieg", date="2025-09-05")
    _stunde(client, b3, "Vertiefung")

    r = client.get(f"/api/stoff-plans/{plan['id']}/combined")
    assert r.status_code == 200
    body = r.json()
    blocks = {b["lbCode"]: b for b in body["blocks"]}
    assert [s["title"] for s in blocks["LB3"]["stunden"]] == ["Einstieg", "Vertiefung"]
    assert blocks["LB3"]["stunden"][0]["date"] == "2025-09-05"
    assert blocks["LB4"]["stunden"] == []


def test_combined_foreign_plan_404(client, auth):
    r = client.get("/api/stoff-plans/99999/combined")
    assert r.status_code == 404


def test_export_combined_pdf_bytes_and_header(client, auth):
    cid = _class(client, "8ä")
    plan = _plan(client, cid)
    b3 = next(b["id"] for b in plan["blocks"] if b["lbCode"] == "LB3")
    _stunde(client, b3, "Einstieg", date="2025-09-05", isKlassenarbeit=True)

    r = client.get(f"/api/stoff-plans/{plan['id']}/export-combined?format=pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:4] == b"%PDF"
    disp = r.headers["content-disposition"]
    assert "attachment" in disp
    assert "filename*=UTF-8''" in disp


def test_export_combined_unknown_format_rejected(client, auth):
    cid = _class(client)
    plan = _plan(client, cid)
    r = client.get(f"/api/stoff-plans/{plan['id']}/export-combined?format=docx")
    assert r.status_code == 400


def test_export_combined_foreign_plan_404(client, auth):
    r = client.get("/api/stoff-plans/99999/export-combined?format=pdf")
    assert r.status_code == 404
