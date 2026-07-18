"""U19: Stoffverteilungsplan als PDF-Tabelle exportieren (Bytes, Header, Scoping)."""


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


def _plan(client, cid, syid=None, title="Stoffplan 7a"):
    body = {"classId": cid, "title": title, "blocks": [
        {"lbCode": "LB3", "title": "Balladen lesen", "ustd": 20,
         "startDate": "2025-09-01", "endDate": "2025-10-10", "conflictNote": "Ferienüberschneidung"},
        {"lbCode": "LB4", "title": "Erörterung üben", "ustd": 25,
         "startDate": "2025-10-20", "endDate": "2025-12-15"},
    ]}
    if syid is not None:
        body["schoolYearId"] = syid
    r = client.post("/api/stoff-plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_export_pdf_bytes_and_header(client, auth):
    cid, syid = _class(client, "8ä"), _year(client)
    pid = _plan(client, cid, syid)
    r = client.get(f"/api/stoff-plans/{pid}/export?format=pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 1000
    disp = r.headers["content-disposition"]
    assert "attachment" in disp
    assert ".pdf" in disp
    assert "filename*=UTF-8''" in disp          # RFC 5987 für Umlaute


def test_export_pdf_without_school_year(client, auth):
    cid = _class(client, "9a")
    pid = _plan(client, cid, None, title="Plan ohne Schuljahr")
    r = client.get(f"/api/stoff-plans/{pid}/export?format=pdf")
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_export_unknown_format_rejected(client, auth):
    cid = _class(client)
    pid = _plan(client, cid)
    r = client.get(f"/api/stoff-plans/{pid}/export?format=docx")
    assert r.status_code == 400


def test_export_foreign_plan_404(client, auth):
    r = client.get("/api/stoff-plans/99999/export?format=pdf")
    assert r.status_code == 404
