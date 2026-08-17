"""ASUV-Entwurf je Stunde: laden (mit Vorbefüllung), speichern, exportieren (docx/pdf).

Vorbefüllung ist reine Ableitung aus Klafki/Stundendaten (keine KI). Die
KI-Ausformulierung/Konsistenzprüfung kommt in Meilenstein 7.
"""
import json
import sqlite3
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ..deps import get_db, get_user_id, row_or_404
from ..lib.asuv_export import build_docx, build_pdf
from ..schemas import AsuvDraft, AsuvListItem, AsuvOut, AsuvSyncCreate, AsuvSyncUpdate

router = APIRouter(tags=["asuv"])

_FIELDS = ("bedingung_org", "bedingung_lern", "bedingung_einordnung", "ziele", "sachanalyse",
           "quellen", "didaktisch", "reduktion", "methodisch", "anhang",
           "schule", "pruefer", "deckblatt_datum")


def _lesson(conn, user_id, lid):
    return conn.execute("SELECT * FROM lessons WHERE id = ? AND user_id = ?", (lid, user_id)).fetchone()


def _phase_names(conn, lesson_id) -> dict:
    """Map phase_sort_order (== lesson_phases.sort_order) -> Phasenname."""
    rows = conn.execute(
        "SELECT sort_order, phase_name FROM lesson_phases WHERE lesson_id = ?", (lesson_id,)).fetchall()
    return {r["sort_order"]: r["phase_name"] for r in rows}


def _ziele_from_lernziele(conn, lesson_id) -> str:
    """Kap. 2 aus den erfassten Lernzielen ableiten – je Feinziel Phasennachweis."""
    rows = conn.execute(
        "SELECT kind, text, bloom_stufe, phase_sort_order FROM lesson_lernziele "
        "WHERE lesson_id = ? ORDER BY sort_order, id", (lesson_id,)).fetchall()
    if not rows:
        return ""
    names = _phase_names(conn, lesson_id)
    grob = [r for r in rows if r["kind"] == "grob"]
    fein = [r for r in rows if r["kind"] == "fein"]
    lines = []
    if grob:
        lines.append("Grobziel(e):")
        for r in grob:
            bloom = f" (Bloom: {r['bloom_stufe']})" if r["bloom_stufe"] else ""
            lines.append(f"- {r['text']}{bloom}")
    if fein:
        lines.append("Feinziele:")
        for r in fein:
            bloom = f" (Bloom: {r['bloom_stufe']})" if r["bloom_stufe"] else ""
            pso = r["phase_sort_order"]
            phase = names.get(pso) if pso is not None else None
            nachweis = f"erreicht in Phase: {phase}" if phase else "(keiner Phase zugeordnet)"
            lines.append(f"- {r['text']}{bloom} — {nachweis}")
    return "\n".join(lines)


def _prefill(conn, lrow) -> dict:
    d = dict(lrow)
    klafki = [d["klafki_gegenwart"], d["klafki_zukunft"], d["klafki_exemplarisch"],
              d["klafki_zugang"], d["klafki_struktur"]]
    joined = " ".join(x for x in klafki if x)
    pre = {f: "" for f in _FIELDS}
    pre["bedingung_einordnung"] = (
        f"Diese Stunde ({d['lesson_type'] or 'Unterrichtsstunde'}) ist Teil der laufenden "
        f"Unterrichtseinheit in {d['subject']}, Klasse {d['grade'] or '?'}.")
    ziele_lz = _ziele_from_lernziele(conn, d["id"])
    if ziele_lz:                                    # erfasste Lernziele haben Vorrang vor der Klafki-Ableitung
        pre["ziele"] = ziele_lz
    elif joined:
        pre["ziele"] = "Ableitung aus der Klafki-Analyse: " + joined
    if d["klafki_exemplarisch"]:
        pre["didaktisch"] = "Exemplarische Bedeutung: " + d["klafki_exemplarisch"]
    return pre


def _export_lesson(conn, lrow) -> dict:
    d = dict(lrow)
    phases = conn.execute(
        "SELECT * FROM lesson_phases WHERE lesson_id = ? ORDER BY sort_order", (d["id"],)).fetchall()
    return {
        "title": d["title"], "subject": d["subject"], "grade": d["grade"],
        "lesson_type": d["lesson_type"],
        "bibox": {"werk": d["bibox_werk"], "seite": d["bibox_seite"], "notiz": d["bibox_notiz"]},
        "phases": [dict(p) for p in phases],
    }


@router.get("/asuv", response_model=list[AsuvListItem])
def list_asuv(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    """Alle gespeicherten ASUV-Entwürfe des Nutzers (für die Materialbibliothek, U29)."""
    rows = conn.execute(
        "SELECT ad.lesson_id, ad.updated_at, l.title AS lesson_title, l.subject, l.grade, "
        "l.class_id, c.name AS class_name "
        "FROM asuv_drafts ad JOIN lessons l ON l.id = ad.lesson_id "
        "LEFT JOIN classes c ON c.id = l.class_id "
        "WHERE ad.user_id = ? ORDER BY ad.updated_at DESC",
        (user_id,),
    ).fetchall()
    return [AsuvListItem(**dict(r)) for r in rows]


def _get_asuv(conn, user_id, lid) -> AsuvOut:
    lrow = row_or_404(_lesson(conn, user_id, lid), "Stunde")
    bibox_empty = not (lrow["bibox_werk"] or "").strip()
    row = conn.execute("SELECT * FROM asuv_drafts WHERE lesson_id = ? AND user_id = ?",
                       (lid, user_id)).fetchone()
    if row:
        d = dict(row)
        return AsuvOut(id=lid, lesson_id=lid, saved=True, bibox_empty=bibox_empty,
                       updated_at=d["updated_at"],
                       checks=json.loads(d["checks_json"]) if d["checks_json"] else {},
                       **{f: d[f] or "" for f in _FIELDS})
    return AsuvOut(id=lid, lesson_id=lid, saved=False, bibox_empty=bibox_empty, checks={},
                   **_prefill(conn, lrow))


@router.get("/lessons/{lid}/asuv", response_model=AsuvOut)
def get_asuv(lid: int, conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    return _get_asuv(conn, user_id, lid)


def _apply_upsert_asuv(conn, user_id: int, lid: int, body: AsuvDraft) -> AsuvOut:
    row_or_404(_lesson(conn, user_id, lid), "Stunde")
    values = [getattr(body, f) for f in _FIELDS]
    cols = ", ".join(["lesson_id", "user_id", *_FIELDS, "checks_json", "updated_at"])
    placeholders = ", ".join(["?"] * (len(_FIELDS) + 3)) + ", strftime('%Y-%m-%d %H:%M:%f','now')"
    updates = ", ".join(f"{f} = excluded.{f}" for f in (*_FIELDS, "checks_json"))
    conn.execute(
        f"""INSERT INTO asuv_drafts({cols}) VALUES ({placeholders})
            ON CONFLICT(lesson_id) DO UPDATE SET {updates}, updated_at = strftime('%Y-%m-%d %H:%M:%f','now')""",
        (lid, user_id, *values, json.dumps(body.checks or {})),
    )
    return _get_asuv(conn, user_id, lid)


@router.put("/lessons/{lid}/asuv", response_model=AsuvOut)
def put_asuv(lid: int, body: AsuvDraft, conn: sqlite3.Connection = Depends(get_db),
             user_id: int = Depends(get_user_id)):
    result = _apply_upsert_asuv(conn, user_id, lid, body)
    conn.commit()
    return result


# ---------- Sync-Handler-Registry: asuv_drafts (src/routers/sync.py) ----------
# Natürlicher Schlüssel: lesson_id IST der Primärschlüssel von asuv_drafts (keine separate
# autoincrement-id, anders als bei allen bisherigen Rollout-Einheiten) — der generische
# entity_id-Parameter des Sync-Protokolls transportiert hier direkt die lesson_id, AsuvOut.id
# ist bewusst ein Alias darauf (siehe Kommentar dort). create ist ein reines INSERT (kein
# ON CONFLICT DO UPDATE wie der REST-PUT) — legen zwei Geräte offline beide erstmals einen
# Entwurf für dieselbe Stunde an, soll das als Konflikt auffallen statt sich still zu
# überschreiben (analog plan_notes). Frontend unterscheidet create/update anhand des zuvor
# geladenen saved-Flags (wie bei lessons: isNew).

def _sync_fetch_asuv(conn, user_id, entity_id):
    lrow = _lesson(conn, user_id, entity_id)
    if lrow is None:
        return None
    row = conn.execute("SELECT * FROM asuv_drafts WHERE lesson_id = ? AND user_id = ?",
                       (entity_id, user_id)).fetchone()
    if row is None:
        return None  # noch nicht gespeichert — kein Sync-Datensatz, nur eine Vorbefüllung
    return _get_asuv(conn, user_id, entity_id)


def _apply_create_asuv(conn, user_id, payload: dict) -> AsuvOut:
    body = AsuvSyncCreate(**payload)
    lid = body.lesson_id
    row_or_404(_lesson(conn, user_id, lid), "Stunde")
    values = [getattr(body, f) for f in _FIELDS]
    cols = ", ".join(["lesson_id", "user_id", *_FIELDS, "checks_json", "updated_at"])
    placeholders = ", ".join(["?"] * (len(_FIELDS) + 3)) + ", strftime('%Y-%m-%d %H:%M:%f','now')"
    try:
        conn.execute(
            f"INSERT INTO asuv_drafts({cols}) VALUES ({placeholders})",
            (lid, user_id, *values, json.dumps(body.checks or {})),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Für diese Stunde existiert bereits ein ASUV-Entwurf — bitte neu laden.",
        )
    return _get_asuv(conn, user_id, lid)


def _apply_update_asuv(conn, user_id, entity_id, payload: dict) -> AsuvOut:
    row_or_404(
        conn.execute("SELECT 1 FROM asuv_drafts WHERE lesson_id = ? AND user_id = ?",
                     (entity_id, user_id)).fetchone(),
        "ASUV-Entwurf",
    )
    return _apply_upsert_asuv(conn, user_id, entity_id, AsuvSyncUpdate(**payload))


def _sync_reject_delete_asuv(conn, user_id, entity_id):
    raise HTTPException(status_code=400, detail="ASUV-Entwürfe können nicht gelöscht werden.")


SYNC_HANDLER = {
    "fetch": _sync_fetch_asuv,
    "create": _apply_create_asuv,
    "update": _apply_update_asuv,
    "delete": _sync_reject_delete_asuv,
}


@router.get("/lessons/{lid}/asuv/export")
def export_asuv(lid: int, format: str = Query("docx"),
                conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    lrow = row_or_404(_lesson(conn, user_id, lid), "Stunde")
    row = conn.execute("SELECT * FROM asuv_drafts WHERE lesson_id = ? AND user_id = ?",
                       (lid, user_id)).fetchone()
    if row:
        d = dict(row)
        draft = {f: d[f] or "" for f in _FIELDS}
    else:
        draft = _prefill(conn, lrow)
    author = conn.execute("SELECT display_name FROM users WHERE id = ?", (user_id,)).fetchone()["display_name"]
    ldict = _export_lesson(conn, lrow)
    base = "".join(c for c in (ldict["title"] or "ASUV") if c.isalnum() or c in " -_").strip() or "ASUV"

    if format == "pdf":
        data, media, ext = build_pdf(ldict, draft, author), "application/pdf", "pdf"
    else:
        data = build_docx(ldict, draft, author)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"

    fname = f"ASUV_{base}.{ext}"
    ascii_fb = "".join(c if c.isascii() else "_" for c in fname)  # ASCII-Fallback für den Header
    disposition = (f"attachment; filename=\"{ascii_fb}\"; "
                   f"filename*=UTF-8''{urllib.parse.quote(fname)}")  # RFC 5987: Umlaute erhalten
    return Response(content=data, media_type=media, headers={"Content-Disposition": disposition})
