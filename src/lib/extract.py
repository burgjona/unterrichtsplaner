"""PDF-Textextraktion + Chunking – reine Textverarbeitung, keine Sprach-KI.

Zerlegt PDF-Seitentext in ~600-Wort-Abschnitte mit Seitenreferenz (page_from/
page_to) für die FTS5-Suche. Gescannte PDFs ohne Textschicht liefern leere
Seiten → keine Chunks (OCR ist nicht Teil des Umfangs).
"""
from typing import List

from pypdf import PdfReader

CHUNK_WORDS = 600


def pdf_pages_text(path: str) -> List[str]:
    reader = PdfReader(path)
    return [(page.extract_text() or "") for page in reader.pages]


def chunk_pages(pages: List[str], chunk_words: int = CHUNK_WORDS) -> List[dict]:
    """Wort-basiertes Chunking über Seitengrenzen hinweg, mit Seitenreferenz (1-basiert)."""
    chunks: List[dict] = []
    buf = []  # Liste (Wort, Seitenindex)

    def flush():
        if not buf:
            return
        pages_in = [p for _, p in buf]
        chunks.append({
            "content": " ".join(w for w, _ in buf),
            "page_from": min(pages_in) + 1,
            "page_to": max(pages_in) + 1,
        })
        buf.clear()

    for pi, text in enumerate(pages):
        for word in text.split():
            buf.append((word, pi))
            if len(buf) >= chunk_words:
                flush()
    flush()
    return chunks


def extract_chunks(path: str) -> List[dict]:
    return chunk_pages(pdf_pages_text(path))
