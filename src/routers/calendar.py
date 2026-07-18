"""CRUD Kalendereinträge (nutzer-gescoped). Auto-Erzeugung aus Stunden = Meilenstein 4.

U20 (Jahresplan-Import): /import/analyze erkennt per KI Termine aus einem hochgeladenen
Schul-Jahresplan (PDF); /import/commit legt die vom Nutzer bestätigten Termine an.
"""
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from ..deps import get_db, get_storage_root, get_user_id, row_or_404
from ..lib import ai, google_cal
from ..lib.extract import pdf_pages_text
from ..schemas import (CalendarCreate, CalendarOut, CalendarUpdate, ImportCommitIn,
                       ImportSuggestion)

router = APIRouter(prefix="/calendar", tags=["calendar"])

IMPORT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB — Jahrespläne sind klein
IMPORT_MAX_CHARS = 14000            # Kontext-Deckel (token-/kostenbewusst)


def _get(conn, user_id, cid):
    row = conn.execute(
        "SELECT * FROM calendar_entries WHERE id = ? AND user_id = ?", (cid, user_id)
    ).fetchone()
    return CalendarOut(**dict(row)) if row else None


def _category_owned(conn, user_id, category_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM calendar_categories WHERE id = ? AND user_id = ?", (category_id, user_id)
    ).fetchone() is not None


@router.post("", response_model=CalendarOut, status_code=201)
def create(body: CalendarCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    # Kategorie (falls gesetzt) muss dem Nutzer gehören.
    if body.category_id is not None and not _category_owned(conn, user_id, body.category_id):
        raise HTTPException(status_code=400, detail="Unbekannte Kategorie.")
    try:
        cur = conn.execute(
            """INSERT INTO calendar_entries
               (user_id, class_id, lesson_id, school_year_id, title, entry_date, end_date,
                start_time, end_time, all_day, entry_type, category_id, is_fixed, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
            (user_id, body.class_id, body.lesson_id, body.school_year_id, body.title,
             body.entry_date, body.end_date, body.start_time, body.end_time,
             int(body.all_day), body.entry_type, body.category_id, int(body.is_fixed)),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültiger Eintrag: {exc}")
    return _get(conn, user_id, cur.lastrowid)


@router.get("", response_model=List[CalendarOut])
def list_(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    class_id: Optional[int] = Query(None, alias="classId"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    sql = "SELECT * FROM calendar_entries WHERE user_id = ?"
    params = [user_id]
    if from_ is not None:
        sql += " AND entry_date >= ?"
        params.append(from_)
    if to is not None:
        sql += " AND entry_date <= ?"
        params.append(to)
    if class_id is not None:
        sql += " AND class_id = ?"
        params.append(class_id)
    sql += " ORDER BY entry_date"
    return [CalendarOut(**dict(r)) for r in conn.execute(sql, params).fetchall()]


@router.get("/{cid}", response_model=CalendarOut)
def get_(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    return row_or_404(_get(conn, user_id, cid), "Kalendereintrag")


@router.put("/{cid}", response_model=CalendarOut)
def update(cid: int, body: CalendarUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, cid), "Kalendereintrag")
    fields = body.model_dump(exclude_unset=True)
    if fields.get("category_id") is not None and not _category_owned(conn, user_id, fields["category_id"]):
        raise HTTPException(status_code=400, detail="Unbekannte Kategorie.")
    if "is_fixed" in fields:
        fields["is_fixed"] = int(fields["is_fixed"])
    if "all_day" in fields:
        fields["all_day"] = int(fields["all_day"])
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        cols += ", updated_at = datetime('now')"  # Last-write-wins für Google-Sync (U21)
        fields.update(id=cid, uid=user_id)
        conn.execute(
            f"UPDATE calendar_entries SET {cols} WHERE id = :id AND user_id = :uid", fields
        )
        conn.commit()
    return _get(conn, user_id, cid)


@router.delete("/{cid}", status_code=204)
def delete(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    cur = conn.execute("DELETE FROM calendar_entries WHERE id = ? AND user_id = ?", (cid, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Kalendereintrag nicht gefunden.")


# ---------- Google-Kalender-Sync (U21) ----------
@router.post("/google/sync")
def google_sync(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    """Push + Pull mit Google. Ohne hinterlegten Schlüssel sauberer 4xx (kein 500)."""
    try:
        return google_cal.sync(conn, user_id)
    except google_cal.NoGoogleKey:
        raise HTTPException(
            status_code=400,
            detail="Kein Google-Schlüssel hinterlegt – bitte in den Einstellungen eintragen.",
        )
    except HTTPException:
        raise
    except Exception as exc:  # Auth-/Netz-/API-Fehler sauber weiterreichen (nie 500-Traceback)
        raise HTTPException(status_code=502, detail=f"Google-Sync fehlgeschlagen: {exc}")


# ---------- Jahresplan-Import (U20) ----------
_IMPORT_SYSTEM = (
    "Du bist Assistenz für eine Referendarin an einer sächsischen Oberschule und liest den "
    "Jahresplan/Terminplan der Schule aus. Extrahiere aus dem Text ALLE datierten schulischen "
    "Termine (z. B. Ferien, Feiertage, Elternabende, Zeugnisausgaben, Projekttage, Konferenzen, "
    "Wandertage, Prüfungen). Gib je Termin ein ISO-Datum (YYYY-MM-DD) an; bei mehrtägigen "
    "Terminen zusätzlich ein ISO-Enddatum, sonst null. Erfinde nichts – nur was im Text steht. "
    "Wenn Jahreszahlen fehlen, leite sie aus dem Schuljahres-Kontext ab. Schlage je Termin eine "
    "passende Kategorie aus der vorgegebenen Liste vor (Feld kategorieVorschlag, exakter Name aus "
    "der Liste); passt keine, gib den leeren String. Umlaute korrekt erhalten."
)
_IMPORT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["termine"],
    "properties": {"termine": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["datum", "endDatum", "titel", "kategorieVorschlag"],
        "properties": {
            "datum": {"type": "string"},
            "endDatum": {"type": ["string", "null"]},
            "titel": {"type": "string"},
            "kategorieVorschlag": {"type": "string"},
        },
    }}},
}


@router.post("/import/analyze", response_model=List[ImportSuggestion])
async def import_analyze(
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db),
    user_id: int = Depends(get_user_id),
    storage_root: str = Depends(get_storage_root),
):
    """PDF hochladen → Text extrahieren → KI erkennt Terminvorschläge (nichts wird gespeichert)."""
    # Frühzeitiger Key-Check spart einen unnötigen Upload, wenn keine KI möglich ist.
    if not ai.get_api_key(conn, user_id):
        raise HTTPException(status_code=400,
                            detail="Kein API-Key hinterlegt – bitte in den Einstellungen eintragen.")

    tmp_dir = Path(storage_root) / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"jahresplan_{uuid.uuid4().hex}.pdf"
    size = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > IMPORT_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="Datei zu groß (max. 20 MB).")
                out.write(chunk)
        try:
            pages = pdf_pages_text(str(tmp))
        except Exception:
            raise HTTPException(status_code=400,
                                detail="PDF konnte nicht gelesen werden – bitte ein Text-PDF hochladen.")
    finally:
        if tmp.exists():
            tmp.unlink()

    text = "\n".join(pages).strip()
    if not text:
        raise HTTPException(status_code=400,
                            detail="Im PDF wurde kein auslesbarer Text gefunden (evtl. gescannt).")
    text = text[:IMPORT_MAX_CHARS]

    cats = conn.execute(
        "SELECT name FROM calendar_categories WHERE user_id = ? ORDER BY sort_order, id", (user_id,)
    ).fetchall()
    cat_names = ", ".join(c["name"] for c in cats) or "(keine)"
    user_text = (f"Verfügbare Kategorien: {cat_names}\n\n"
                 f"Jahresplan-Text:\n{text}")

    try:
        result = ai.run(conn, user_id, "jahresplan_import", _IMPORT_SYSTEM, user_text,
                        _IMPORT_SCHEMA, max_tokens=3000)
    except ai.NoApiKey:
        raise HTTPException(status_code=400,
                            detail="Kein API-Key hinterlegt – bitte in den Einstellungen eintragen.")
    except Exception as exc:  # Netz-/Auth-/API-Fehler sauber weiterreichen
        raise HTTPException(status_code=502, detail=f"KI-Anfrage fehlgeschlagen: {exc}")
    try:
        data = json.loads(result["text"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=502, detail="KI-Antwort war kein gültiges JSON.")

    out_list = []
    for t in data.get("termine", []):
        kv = (t.get("kategorieVorschlag") or "").strip() or None
        out_list.append(ImportSuggestion(datum=t.get("datum", ""), end_datum=t.get("endDatum"),
                                         titel=t.get("titel", ""), kategorie_vorschlag=kv))
    return out_list


@router.post("/import/commit", response_model=List[CalendarOut], status_code=201)
def import_commit(body: ImportCommitIn, conn: sqlite3.Connection = Depends(get_db),
                  user_id: int = Depends(get_user_id)):
    """Legt die vom Nutzer ausgewählten Terminvorschläge als Kalendereinträge an (all_day)."""
    created_ids = []
    for e in body.entries:
        if not e.titel.strip() or not e.datum.strip():
            continue  # unvollständige Zeilen überspringen
        if e.category_id is not None and not _category_owned(conn, user_id, e.category_id):
            raise HTTPException(status_code=400, detail="Unbekannte Kategorie.")
        end_date = e.end_datum if (e.end_datum and e.end_datum >= e.datum) else None
        try:
            cur = conn.execute(
                """INSERT INTO calendar_entries
                   (user_id, title, entry_date, end_date, all_day, entry_type, category_id)
                   VALUES (?,?,?,?,1,'normal',?)""",
                (user_id, e.titel.strip(), e.datum, end_date, e.category_id),
            )
            created_ids.append(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=400, detail=f"Ungültiger Eintrag: {exc}")
    conn.commit()
    return [_get(conn, user_id, cid) for cid in created_ids]
