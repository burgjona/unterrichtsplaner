"""ASUV-Entwurf je Stunde: laden (mit Vorbefüllung), speichern, exportieren (docx/pdf).

Vorbefüllung ist reine Ableitung aus Klafki/Stundendaten (keine KI). Die
KI-Ausformulierung/Konsistenzprüfung kommt in Meilenstein 7.
"""
import json
import sqlite3
import urllib.parse

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from ..deps import get_db, get_user_id, row_or_404
from ..lib.asuv_export import build_docx, build_pdf
from ..schemas import AsuvDraft, AsuvOut

router = APIRouter(tags=["asuv"])

_FIELDS = ("bedingung_org", "bedingung_lern", "bedingung_einordnung", "ziele", "sachanalyse",
           "quellen", "didaktisch", "reduktion", "methodisch", "anhang",
           "schule", "pruefer", "deckblatt_datum")


def _lesson(conn, user_id, lid):
    return conn.execute("SELECT * FROM lessons WHERE id = ? AND user_id = ?", (lid, user_id)).fetchone()


def _prefill(lrow) -> dict:
    d = dict(lrow)
    klafki = [d["klafki_gegenwart"], d["klafki_zukunft"], d["klafki_exemplarisch"],
              d["klafki_zugang"], d["klafki_struktur"]]
    joined = " ".join(x for x in klafki if x)
    pre = {f: "" for f in _FIELDS}
    pre["bedingung_einordnung"] = (
        f"Diese Stunde ({d['lesson_type'] or 'Unterrichtsstunde'}) ist Teil der laufenden "
        f"Unterrichtseinheit in {d['subject']}, Klasse {d['grade'] or '?'}.")
    if joined:
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


@router.get("/lessons/{lid}/asuv", response_model=AsuvOut)
def get_asuv(lid: int, conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    lrow = row_or_404(_lesson(conn, user_id, lid), "Stunde")
    bibox_empty = not (lrow["bibox_werk"] or "").strip()
    row = conn.execute("SELECT * FROM asuv_drafts WHERE lesson_id = ? AND user_id = ?",
                       (lid, user_id)).fetchone()
    if row:
        d = dict(row)
        return AsuvOut(lesson_id=lid, saved=True, bibox_empty=bibox_empty,
                       checks=json.loads(d["checks_json"]) if d["checks_json"] else {},
                       **{f: d[f] or "" for f in _FIELDS})
    return AsuvOut(lesson_id=lid, saved=False, bibox_empty=bibox_empty, checks={}, **_prefill(lrow))


@router.put("/lessons/{lid}/asuv", response_model=AsuvOut)
def put_asuv(lid: int, body: AsuvDraft, conn: sqlite3.Connection = Depends(get_db),
             user_id: int = Depends(get_user_id)):
    row_or_404(_lesson(conn, user_id, lid), "Stunde")
    values = [getattr(body, f) for f in _FIELDS]
    cols = ", ".join(["lesson_id", "user_id", *_FIELDS, "checks_json"])
    placeholders = ", ".join(["?"] * (len(_FIELDS) + 3))
    updates = ", ".join(f"{f} = excluded.{f}" for f in (*_FIELDS, "checks_json"))
    conn.execute(
        f"""INSERT INTO asuv_drafts({cols}) VALUES ({placeholders})
            ON CONFLICT(lesson_id) DO UPDATE SET {updates}, updated_at = datetime('now')""",
        (lid, user_id, *values, json.dumps(body.checks or {})),
    )
    conn.commit()
    return get_asuv(lid, conn, user_id)


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
        draft = _prefill(lrow)
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
