"""Integrations-Smoke-Test des kompletten M1-Flows über die HTTP-API."""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["milestone"] == 9


def test_requires_login(client):
    # Ohne Session-Cookie ist jede gescopte Ressource gesperrt.
    assert client.get("/api/classes").status_code == 401


def test_full_flow_and_camelcase(client, auth):
    # Schuljahr
    sy = client.post("/api/school-years",
                     json={"label": "2025/2026", "startDate": "2025-08-01", "endDate": "2026-07-15"},
                     headers=auth).json()
    # Klasse
    cls = client.post("/api/classes",
                      json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "RS",
                            "weeklyHours": 3, "parallelGroup": "Deutsch 8", "schoolYearId": sy["id"]},
                      headers=auth).json()
    assert cls["weeklyHours"] == 3 and cls["visibleInCalendar"] is True

    # Lernbereich (Referenz) + Stunde mit Phasen
    lb = client.post("/api/lernbereiche",
                     json={"subject": "Deutsch", "grade": 8, "track": "RS", "code": "LB4",
                           "title": "Entdeckungen: Printmedien", "richtwertUstd": 15}).json()
    lesson = client.post("/api/lessons",
                         json={"title": "Balladen szenisch erschließen", "subject": "Deutsch",
                               "grade": 8, "classId": cls["id"], "lernbereichId": lb["id"],
                               "lessonType": "Einführung", "time": "08:50",
                               "klafki": {"gegenwart": "Alltagsbezug", "struktur": "Wendepunkt"},
                               "meyerPlan": ["gruen"] * 10,
                               "bibox": {"werk": "Deutschbuch 8", "seite": "S. 140"},
                               "tafelbildEingabe": "Merkmale der Ballade",
                               "tafelbild": {"titel": "Die Ballade", "bloecke": [
                                   {"ueberschrift": "Merkmale", "punkte": ["erzählend", "dramatisch"],
                                    "hervorgehoben": False}]},
                               "phases": [
                                   {"phaseName": "Einstieg", "minutes": 10, "socialForm": "Plenum",
                                    "method": "Hörimpuls", "teacherActivity": "spielt vor"},
                                   {"phaseName": "Erarbeitung", "minutes": 20, "socialForm": "GA"}]},
                         headers=auth)
    assert lesson.status_code == 201, lesson.text
    lj = lesson.json()
    assert lj["klafki"]["gegenwart"] == "Alltagsbezug"      # Umlaute/Struktur erhalten
    assert lj["meyerPlan"] == ["gruen"] * 10                 # JSON-Vektor rund
    assert lj["phases"][0]["phaseName"] == "Einstieg"        # camelCase + normalisiert
    assert lj["phases"][1]["socialForm"] == "GA"
    assert lj["tafelbild"]["titel"] == "Die Ballade"          # Tafelbild rund (KI-Struktur + Umlaute)
    assert lj["tafelbild"]["bloecke"][0]["punkte"] == ["erzählend", "dramatisch"]

    # Notizfeld separat nachtragbar (eigene Ergänzung der Lehrkraft, kein KI-Inhalt)
    upd = client.put(f"/api/lessons/{lj['id']}", json={"tafelbildNotiz": "Tafelbild-Foto: siehe Ordner"},
                     headers=auth).json()
    assert upd["tafelbildNotiz"] == "Tafelbild-Foto: siehe Ordner"
    assert upd["tafelbild"]["titel"] == "Die Ballade"         # bleibt beim reinen Notiz-Update erhalten

    # Eigenes Tafelbild-Foto: Referenz auf ein Material, per Partial-Update setzbar/löschbar
    assert lj["tafelbildBildMaterialId"] is None
    upd = client.put(f"/api/lessons/{lj['id']}", json={"tafelbildBildMaterialId": 42}, headers=auth).json()
    assert upd["tafelbildBildMaterialId"] == 42
    assert upd["tafelbildNotiz"] == "Tafelbild-Foto: siehe Ordner"   # unangetastet
    upd = client.put(f"/api/lessons/{lj['id']}", json={"tafelbildBildMaterialId": None}, headers=auth).json()
    assert upd["tafelbildBildMaterialId"] is None

    # Heftereintrag der SuS: eigenes Feld, getrennt vom Tafelbild, per Partial-Update rund
    assert lj["hefteintrag"] is None
    upd = client.put(f"/api/lessons/{lj['id']}", json={"hefteintrag": "Merkmale der Ballade, HA S. 44"},
                     headers=auth).json()
    assert upd["hefteintrag"] == "Merkmale der Ballade, HA S. 44"
    assert upd["tafelbildNotiz"] == "Tafelbild-Foto: siehe Ordner"   # unangetastet

    # Kalendereintrag
    cal = client.post("/api/calendar",
                      json={"title": "LUE Rechtschreibung", "entryDate": "2025-09-15",
                            "entryType": "lu", "classId": cls["id"], "lessonId": lj["id"]},
                      headers=auth)
    assert cal.status_code == 201

    # Material + Mehrfachverknüpfung
    mat = client.post("/api/materials",
                      json={"filename": "BalladenAB.pdf", "subject": "Deutsch", "grade": 8,
                            "schoolYearId": sy["id"], "status": "fertig"},
                      headers=auth).json()
    assert "/Deutsch/Klasse-8/2025-2026/BalladenAB.pdf" in mat["storedPath"]
    links = client.post(f"/api/materials/{mat['id']}/links",
                        json={"lessonId": lj["id"], "lernbereichId": lb["id"]}, headers=auth).json()
    assert links == {"lessons": [lj["id"]], "lernbereiche": [lb["id"]]}
    # Filter Materialien nach Lernbereich
    filtered = client.get(f"/api/materials?lernbereichId={lb['id']}", headers=auth).json()
    assert [m["id"] for m in filtered] == [mat["id"]]


def test_soft_delete_class_preserves_lesson(client, auth):
    cls = client.post("/api/classes", json={"name": "9b", "subject": "WTH", "grade": 9,
                                             "track": "gemischt"}, headers=auth).json()
    lesson = client.post("/api/lessons", json={"title": "Vertragsrecht", "subject": "WTH",
                                               "classId": cls["id"]}, headers=auth).json()
    # Soft-Delete
    assert client.delete(f"/api/classes/{cls['id']}", headers=auth).status_code == 204
    assert cls["id"] not in [c["id"] for c in client.get("/api/classes", headers=auth).json()]
    assert cls["id"] in [c["id"] for c in
                         client.get("/api/classes?includeArchived=true", headers=auth).json()]
    kept = client.get(f"/api/lessons/{lesson['id']}", headers=auth).json()
    assert kept["classId"] == cls["id"]  # Planungsdaten unverändert


def test_hard_delete_class_nulls_lesson_fk(client, auth):
    cls = client.post("/api/classes", json={"name": "7c", "subject": "Deutsch", "grade": 7,
                                             "track": "HS"}, headers=auth).json()
    lesson = client.post("/api/lessons", json={"title": "Rechtschreibung", "subject": "Deutsch",
                                               "classId": cls["id"]}, headers=auth).json()
    assert client.delete(f"/api/classes/{cls['id']}?hard=true", headers=auth).status_code == 204
    kept = client.get(f"/api/lessons/{lesson['id']}", headers=auth)
    assert kept.status_code == 200
    assert kept.json()["classId"] is None  # ON DELETE SET NULL – Stunde überlebt
