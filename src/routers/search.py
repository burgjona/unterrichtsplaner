"""Globale Volltextsuche (U25) über alle Inhalte.

Kombiniert den Cross-Entity-FTS5-Index `search_docs` (Migration 020) mit dem bestehenden
PDF-Volltext `material_chunks_fts`. Treffer werden je Entität (entity_type, entity_id)
dedupliziert; Facetten (Typ/Fach/Klassenstufe) werden über die UNGEFILTERTE Treffermenge
gezählt, damit die Chips beim Filtern stabil bleiben. remove_diacritics 2 macht die Suche
umlaut-tolerant (märchen == marchen).
"""
import sqlite3
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, get_user_id
from ..schemas import SearchFacet, SearchFacets, SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])

_FETCH_CAP = 1000   # je Teilquery; für einen Einzelnutzer großzügig bemessen
_MAX_LIMIT = 200


def _fts_terms(q: str) -> str:
    """Jedes Wort als gequotete Präfix-Phrase → Teilwort-Treffer.

    Das Quoten verhindert FTS-Syntaxfehler (Sonderzeichen/Keywords) und hält das
    implizite UND zwischen den Wörtern. Das nachgestellte ``*`` macht jedes Wort zur
    Präfixsuche, sodass „Tara" auch „Taras"/„Tarantel" findet (Suche-als-Tippen).
    remove_diacritics 2 des Index bleibt wirksam („Mul" findet „Müller").
    """
    return " ".join(f'"{w}" *' for w in q.split() if w)


@router.get("", response_model=SearchResponse)
def search(
    q: str,
    type: Optional[str] = None,
    subject: Optional[str] = None,
    grade: Optional[int] = None,
    limit: int = 50,
    conn: sqlite3.Connection = Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    terms = _fts_terms(q)
    if not terms:
        return SearchResponse(query=q, total=0, facets=SearchFacets(), results=[])
    limit = max(1, min(limit, _MAX_LIMIT))

    entities = {}   # (type, id) -> akkumuliertes Trefferobjekt

    def merge(key, *, bm25, title, snippet, subject, grade, date, page_from=None, page_to=None):
        e = entities.get(key)
        if e is None:
            entities[key] = {
                "type": key[0], "id": key[1], "bm25": bm25,
                "title": title or "", "snippet": snippet or "",
                "subject": subject, "grade": grade, "date": date,
                "page_from": page_from, "page_to": page_to,
            }
            return
        if bm25 < e["bm25"]:          # kleineres bm25 = relevanter → dessen Titel/Snippet zeigen
            e["bm25"] = bm25
            if title:
                e["title"] = title
            if snippet:
                e["snippet"] = snippet
        # Metadaten stammen vom Primärdokument (Kind-Dokumente tragen None) → erstes Nicht-None gewinnt
        if e["subject"] is None and subject is not None:
            e["subject"] = subject
        if e["grade"] is None and grade is not None:
            e["grade"] = grade
        if e["date"] is None and date is not None:
            e["date"] = date
        if e["page_from"] is None and page_from is not None:
            e["page_from"], e["page_to"] = page_from, page_to
        if not e["snippet"] and snippet:
            e["snippet"] = snippet

    # 1) Cross-Entity-Index (alle Typen inkl. Material-Metadaten)
    try:
        rows = conn.execute(
            "SELECT entity_type, entity_id, subject, grade, entry_date, title, "
            "snippet(search_docs, 1, '[[', ']]', '…', 10) AS snip, bm25(search_docs) AS score "
            "FROM search_docs WHERE search_docs MATCH ? AND (user_id = ? OR user_id IS NULL) "
            "ORDER BY bm25(search_docs) LIMIT ?",
            (terms, user_id, _FETCH_CAP),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige Suchanfrage: {exc}")
    for r in rows:
        merge((r["entity_type"], r["entity_id"]), bm25=r["score"], title=r["title"],
              snippet=r["snip"], subject=r["subject"], grade=r["grade"], date=r["entry_date"])

    # 2) PDF-Volltext (bestehender Index) dazumischen – nicht dupliziert, per Material-ID zusammengeführt
    try:
        prows = conn.execute(
            "SELECT m.id AS mid, m.filename, m.subject, m.grade, mc.page_from, mc.page_to, "
            "snippet(material_chunks_fts, 0, '[[', ']]', '…', 10) AS snip, "
            "bm25(material_chunks_fts) AS score "
            "FROM material_chunks_fts JOIN material_chunks mc ON mc.id = material_chunks_fts.rowid "
            "JOIN materials m ON m.id = mc.material_id "
            "WHERE material_chunks_fts MATCH ? AND m.user_id = ? "
            "ORDER BY bm25(material_chunks_fts) LIMIT ?",
            (terms, user_id, _FETCH_CAP),
        ).fetchall()
    except sqlite3.OperationalError:
        prows = []
    for r in prows:
        merge(("material", r["mid"]), bm25=r["score"], title=r["filename"], snippet=r["snip"],
              subject=r["subject"], grade=r["grade"], date=None,
              page_from=r["page_from"], page_to=r["page_to"])

    # 2b) Stunden-Treffer aus der Basistabelle anreichern (frisches Fach/Klasse/Titel/Datum).
    #     Nötig, wenn eine Stunde NUR über ein Kind-Dokument (Lernziel) matcht – dieses trägt
    #     bewusst kein Fach/Klasse (Facetten-Staleness-Vermeidung), sodass sonst die Klassenstufe
    #     in Ergebnis UND Facette fehlte.
    lesson_ids = [eid for (etype, eid) in entities if etype == "lesson"]
    if lesson_ids:
        ph = ",".join("?" * len(lesson_ids))
        for r in conn.execute(
            f"SELECT id, title, subject, grade, date FROM lessons WHERE id IN ({ph}) AND user_id = ?",
            (*lesson_ids, user_id),
        ).fetchall():
            e = entities.get(("lesson", r["id"]))
            if e:
                e["subject"], e["grade"] = r["subject"], r["grade"]
                if r["title"]:
                    e["title"] = r["title"]
                if e["date"] is None:
                    e["date"] = r["date"]

    all_entities = list(entities.values())

    # 3) Facetten über die ungefilterte Treffermenge (jede Entität zählt einmal)
    tc, sc, gc = Counter(), Counter(), Counter()
    for e in all_entities:
        tc[e["type"]] += 1
        if e["subject"]:
            sc[e["subject"]] += 1
        if e["grade"] is not None:
            gc[e["grade"]] += 1
    facets = SearchFacets(
        types=[SearchFacet(key=k, count=n) for k, n in tc.most_common()],
        subjects=[SearchFacet(key=k, count=sc[k]) for k in sorted(sc)],
        grades=[SearchFacet(key=str(k), count=gc[k]) for k in sorted(gc)],
    )

    # 4) Filter (Typ/Fach/Klassenstufe) auf die Trefferliste anwenden, nach Relevanz sortieren
    def keep(e):
        if type and e["type"] != type:
            return False
        if subject and e["subject"] != subject:
            return False
        if grade is not None and e["grade"] != grade:
            return False
        return True

    filtered = sorted((e for e in all_entities if keep(e)), key=lambda e: e["bm25"])
    results = [
        SearchResult(type=e["type"], id=e["id"], title=e["title"], snippet=e["snippet"],
                     subject=e["subject"], grade=e["grade"], date=e["date"],
                     page_from=e["page_from"], page_to=e["page_to"])
        for e in filtered[:limit]
    ]
    return SearchResponse(query=q, total=len(filtered), facets=facets, results=results)
