"""M5: Chunking (rein), Datei-Upload/Store, PDF-Extraktion, FTS-Suche, Download, Direkt-Upload."""
import os
from pathlib import Path

from src.lib.extract import chunk_pages

FIX = Path(__file__).parent / "fixtures" / "sample.pdf"


def test_chunk_pages_splits_with_page_refs():
    pages = [" ".join(["wort"] * 500), " ".join(["zwei"] * 500)]  # 1000 Wörter über 2 Seiten
    chunks = chunk_pages(pages, chunk_words=600)
    assert len(chunks) == 2
    assert chunks[0]["page_from"] == 1 and chunks[0]["page_to"] == 2   # 500 S1 + 100 S2
    assert chunks[1]["page_from"] == 2 and chunks[1]["page_to"] == 2   # Rest auf S2


def test_upload_text_file_stores_without_chunks(client, auth):
    r = client.post("/api/materials/upload",
                    files={"file": ("notiz.txt", b"nur eine Notiz", "text/plain")},
                    data={"subject": "Deutsch", "grade": "8"})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["extracted"] is False
    assert "/Deutsch/Klasse-8/" in m["storedPath"]
    assert os.path.exists(m["storedPath"])           # physisch abgelegt
    assert m["byteSize"] == len(b"nur eine Notiz")
    assert m["sha256"]


def test_upload_pdf_extracts_indexes_and_search(client, auth):
    r = client.post("/api/materials/upload",
                    files={"file": ("ballade.pdf", FIX.read_bytes(), "application/pdf")},
                    data={"subject": "Deutsch", "grade": "8"})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["extracted"] is True

    hits = client.get("/api/materials/search?q=Ballade").json()
    assert len(hits) >= 1
    assert hits[0]["materialId"] == m["id"]
    assert "allad" in hits[0]["snippet"].lower()
    assert hits[0]["pageFrom"] == 1

    d = client.get(f"/api/materials/{m['id']}/download")
    assert d.status_code == 200 and d.content[:4] == b"%PDF"


def test_search_empty_query_returns_empty(client, auth):
    assert client.get("/api/materials/search?q=%20").json() == []


def test_direct_upload_links_to_lesson(client, auth):
    lesson = client.post("/api/lessons", json={"title": "Balladen", "subject": "Deutsch"}).json()
    r = client.post("/api/materials/upload",
                    files={"file": ("ab.pdf", FIX.read_bytes(), "application/pdf")},
                    data={"subject": "Deutsch", "grade": "8", "lessonId": str(lesson["id"])})
    assert r.status_code == 201
    links = client.get(f"/api/materials/{r.json()['id']}/links").json()
    assert lesson["id"] in links["lessons"]
