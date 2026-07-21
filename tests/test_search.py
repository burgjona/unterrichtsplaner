"""U25 – Globale Volltextsuche über alle Inhalte (FTS5, Facetten, Umlaut-Toleranz)."""
import sqlite3


def _mk_class(client, name="8a", subject="Deutsch", grade=8):
    return client.post("/api/classes",
                       json={"name": name, "subject": subject, "grade": grade, "track": "RS"}).json()


def _mk_lesson(client, title, subject="Deutsch", grade=8, **extra):
    body = {"title": title, "subject": subject, "grade": grade}
    body.update(extra)
    return client.post("/api/lessons", json=body).json()


def test_search_requires_auth(client):
    assert client.get("/api/search?q=test").status_code == 401


def test_search_empty_query(client, auth):
    r = client.get("/api/search?q=%20%20").json()   # nur Leerzeichen
    assert r["total"] == 0 and r["results"] == []


def test_search_finds_across_types_umlaut(client, auth):
    _mk_lesson(client, "Märchen und Balladen", lessonType="Einführung")
    client.post("/api/notes", json={"scope": "allgemein", "bodyMd": "Idee zu Märchen im Unterricht"})
    client.post("/api/calendar", json={"title": "Märchen-Projekttag", "entryDate": "2026-03-12"})

    # Umlaut-Toleranz: mit und ohne Umlaut identische Treffermenge
    with_uml = client.get("/api/search?q=märchen").json()
    without = client.get("/api/search?q=marchen").json()
    assert with_uml["total"] >= 3
    assert {(x["type"], x["id"]) for x in with_uml["results"]} == \
           {(x["type"], x["id"]) for x in without["results"]}

    types = {f["key"] for f in with_uml["facets"]["types"]}
    assert {"lesson", "note", "calendar"} <= types
    # Kalendertreffer trägt sein Datum (für Sprung zum Tag)
    cal = [x for x in with_uml["results"] if x["type"] == "calendar"][0]
    assert cal["date"] == "2026-03-12"


def test_search_snippet_has_markers(client, auth):
    client.post("/api/notes", json={"scope": "allgemein",
                                    "bodyMd": "Ein langer Text über Balladen und ihre Merkmale im Deutschunterricht"})
    r = client.get("/api/search?q=balladen").json()
    note = [x for x in r["results"] if x["type"] == "note"][0]
    assert "[[" in note["snippet"] and "]]" in note["snippet"]


def test_search_prefix_matches_partial_word(client, auth):
    # Teilwort-Suche: „Tara" muss den längeren Namen „Taras" finden (Präfix), nicht nur exakt.
    client.post("/api/notes", json={"scope": "allgemein", "bodyMd": "Sitzplan: Taras neben Mira"})
    partial = client.get("/api/search?q=Tara").json()
    exact = client.get("/api/search?q=Taras").json()
    assert partial["total"] >= 1
    # Präfix findet mindestens die exakte Treffermenge
    assert {(x["type"], x["id"]) for x in exact["results"]} <= \
           {(x["type"], x["id"]) for x in partial["results"]}
    # Präfix wirkt auch bei Umlaut-Namen: „Mul" findet „Müller"
    client.post("/api/notes", json={"scope": "allgemein", "bodyMd": "Elterngespräch mit Familie Müller"})
    assert client.get("/api/search?q=Mul").json()["total"] >= 1


def test_search_type_filter_and_facets(client, auth):
    _mk_lesson(client, "Gedichtanalyse Herbst")
    client.post("/api/notes", json={"scope": "allgemein", "bodyMd": "Herbst Gedichte sammeln"})

    unfiltered = client.get("/api/search?q=herbst").json()
    assert unfiltered["total"] >= 2   # lesson + note

    only_lessons = client.get("/api/search?q=herbst&type=lesson").json()
    assert only_lessons["total"] == 1
    assert all(x["type"] == "lesson" for x in only_lessons["results"])
    # Facetten bleiben bei aktivem Filter über die ungefilterte Menge stabil
    ftypes = {f["key"]: f["count"] for f in only_lessons["facets"]["types"]}
    assert ftypes.get("lesson") == 1 and ftypes.get("note") == 1


def test_search_subject_and_grade_facets(client, auth):
    _mk_lesson(client, "Balladen Klasse 8", subject="Deutsch", grade=8)
    _mk_lesson(client, "Balladen Klasse 7", subject="Deutsch", grade=7)
    r = client.get("/api/search?q=balladen").json()
    subjects = {f["key"]: f["count"] for f in r["facets"]["subjects"]}
    grades = {f["key"]: f["count"] for f in r["facets"]["grades"]}
    assert subjects.get("Deutsch") == 2
    assert grades.get("7") == 1 and grades.get("8") == 1

    # Klassenstufen-Facette filtert
    only7 = client.get("/api/search?q=balladen&grade=7").json()
    assert only7["total"] == 1 and only7["results"][0]["grade"] == 7


def test_search_dedup_lesson_via_lernziel(client, auth):
    """Treffer im Lernziel-Text zählt zur Stunde – Entität erscheint genau einmal."""
    lesson = _mk_lesson(client, "Stunde ohne Suchwort", grade=8,
                        lernziele=[{"kind": "grob", "text": "Zauberwald erkunden", "bloomStufe": "Verstehen"}])
    r = client.get("/api/search?q=zauberwald").json()
    lesson_hits = [x for x in r["results"] if x["type"] == "lesson"]
    assert len(lesson_hits) == 1
    assert lesson_hits[0]["id"] == lesson["id"]
    # Fach/Klasse werden vom Primärdokument der Stunde übernommen (nicht vom Kind-Dokument)
    assert lesson_hits[0]["grade"] == 8


def test_search_update_and_delete_sync(client, auth):
    lesson = _mk_lesson(client, "Einzigartiges Suchwort Xylophon")
    assert client.get("/api/search?q=xylophon").json()["total"] == 1

    client.put(f"/api/lessons/{lesson['id']}", json={"title": "Ganz anderer Titel"})
    assert client.get("/api/search?q=xylophon").json()["total"] == 0

    assert client.get("/api/search?q=anderer").json()["total"] == 1
    client.delete(f"/api/lessons/{lesson['id']}")
    assert client.get("/api/search?q=anderer").json()["total"] == 0


def test_search_scoping_excludes_other_user(client, auth, app):
    """Fremde Nutzerdaten tauchen nicht auf; globale Lernbereiche schon."""
    conn = sqlite3.connect(app.state.db_path)
    other = conn.execute("INSERT INTO users(email, display_name) VALUES('other@x.de','Other')").lastrowid
    conn.execute("INSERT INTO lessons(user_id, title, subject) VALUES(?,'Geheimwort Fremduser','Deutsch')", (other,))
    conn.execute("INSERT INTO lernbereiche(subject, grade, track, code, title, detail_md) "
                 "VALUES('Deutsch', 8, 'RS', 'LBZ', 'Testlernbereich', 'Suchwort Zebrastreifen')")
    conn.commit()
    conn.close()

    assert client.get("/api/search?q=fremduser").json()["total"] == 0     # fremd → nicht sichtbar
    lb = client.get("/api/search?q=zebrastreifen").json()                 # global → sichtbar
    assert lb["total"] == 1 and lb["results"][0]["type"] == "lernbereich"


def test_search_merges_pdf_fulltext(client, auth, app):
    """PDF-Volltext (material_chunks_fts) wird zum Material-Metadatenindex zusammengeführt."""
    conn = sqlite3.connect(app.state.db_path)
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    mid = conn.execute(
        "INSERT INTO materials(user_id, filename, stored_path, subject, grade) "
        "VALUES(?, 'Arbeitsblatt.pdf', '/x/Arbeitsblatt.pdf', 'Deutsch', 8)", (uid,)).lastrowid
    conn.execute(
        "INSERT INTO material_chunks(material_id, chunk_index, page_from, page_to, content) "
        "VALUES(?, 0, 3, 4, 'Seiteninhalt über das Zaubereinhorn und seine Reise')", (mid,))
    conn.commit()
    conn.close()

    r = client.get("/api/search?q=zaubereinhorn").json()
    mats = [x for x in r["results"] if x["type"] == "material"]
    assert len(mats) == 1
    assert mats[0]["id"] == mid
    assert mats[0]["pageFrom"] == 3 and mats[0]["pageTo"] == 4
    assert "[[" in mats[0]["snippet"]
