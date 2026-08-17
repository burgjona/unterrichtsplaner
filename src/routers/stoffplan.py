"""Stoffverteilungspläne persistieren (U12).

Speichert die (flüchtige) Vorschau aus /planning/preview bzw. /ai/stoffplan als
dauerhaften Plan. Regel: max. 1 aktiver Plan je (class_id, school_year_id) — beim
Aktivsetzen werden andere Pläne derselben Klasse+Schuljahr auf 'entwurf' zurückgesetzt.
Alle Endpunkte sind nutzer-gescoped.
"""
import sqlite3
import urllib.parse
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import (
    StoffPlanCreate, StoffPlanDetail, StoffPlanBlockOut, StoffPlanOut, StoffPlanUpdate,
    StoffPlanDuplicateIn, StoffPlanCombinedOut, StoffPlanBlockCombinedOut, SequenzStundeOut,
)

router = APIRouter(prefix="/stoff-plans", tags=["stoffplan"])


def _load_plan(conn, user_id, plan_id):
    return conn.execute(
        "SELECT * FROM stoff_plans WHERE id = ? AND user_id = ?", (plan_id, user_id)
    ).fetchone()


def _deactivate_others(conn, user_id, class_id, school_year_id, keep_id):
    """Setzt alle anderen aktiven Pläne derselben Klasse+Schuljahr auf 'entwurf'."""
    sql = ("UPDATE stoff_plans SET status = 'entwurf', "
           "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') "
           "WHERE user_id = ? AND class_id = ? AND status = 'aktiv' AND id != ? AND ")
    params = [user_id, class_id, keep_id]
    if school_year_id is None:
        sql += "school_year_id IS NULL"
    else:
        sql += "school_year_id = ?"
        params.append(school_year_id)
    conn.execute(sql, params)


def _insert_blocks(conn, plan_id, blocks):
    # sort_order = Position im Array → Reihenfolge ist über die Array-Reihenfolge editierbar.
    for i, b in enumerate(blocks):
        conn.execute(
            "INSERT INTO stoff_plan_blocks "
            "(plan_id, lb_code, title, ustd, start_date, end_date, sort_order, conflict_note) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (plan_id, b.lb_code, b.title, b.ustd, b.start_date, b.end_date, i, b.conflict_note),
        )


def _weeks_for_blocks(conn, user_id, school_year_id, rows):
    """Berechnet je Block die Anzahl Unterrichtswochen (Ferien abgezogen), sofern
    Start-/Enddatum und Schuljahr bekannt sind. Sonst bleibt weeks=None."""
    if school_year_id is None:
        return [None] * len(rows)
    from ..lib.planning import _d, teaching_weeks
    ferien = [(r["start_date"], r["end_date"]) for r in conn.execute(
        "SELECT start_date, end_date FROM school_dates WHERE school_year_id = ? AND user_id = ?",
        (school_year_id, user_id))]
    ferien_d = [(_d(s), _d(e)) for s, e in ferien]
    out = []
    for r in rows:
        if r["start_date"] and r["end_date"]:
            out.append(len(teaching_weeks(_d(r["start_date"]), _d(r["end_date"]), ferien_d)))
        else:
            out.append(None)
    return out


def _detail(conn, user_id, plan_id) -> StoffPlanDetail:
    row = row_or_404(_load_plan(conn, user_id, plan_id), "Stoffplan")
    rows = conn.execute(
        "SELECT * FROM stoff_plan_blocks WHERE plan_id = ? ORDER BY sort_order, id", (plan_id,)
    ).fetchall()
    weeks = _weeks_for_blocks(conn, user_id, row["school_year_id"], rows)
    blocks = [StoffPlanBlockOut(**dict(r), weeks=w) for r, w in zip(rows, weeks)]
    return StoffPlanDetail(**dict(row), blocks=blocks)


def _apply_create_stoffplan(conn, user_id: int, body: StoffPlanCreate) -> StoffPlanDetail:
    if not body.title or not body.title.strip():
        raise HTTPException(status_code=400, detail="Titel darf nicht leer sein.")
    row_or_404(conn.execute("SELECT id FROM classes WHERE id = ? AND user_id = ?",
                            (body.class_id, user_id)).fetchone(), "Klasse")
    if body.school_year_id is not None:
        row_or_404(conn.execute("SELECT id FROM school_years WHERE id = ? AND user_id = ?",
                                (body.school_year_id, user_id)).fetchone(), "Schuljahr")
    cur = conn.execute(
        "INSERT INTO stoff_plans (user_id, class_id, school_year_id, title, status, updated_at) "
        "VALUES (?,?,?,?,?, strftime('%Y-%m-%d %H:%M:%f','now'))",
        (user_id, body.class_id, body.school_year_id, body.title.strip(), body.status))
    plan_id = cur.lastrowid
    _insert_blocks(conn, plan_id, body.blocks)
    if body.status == "aktiv":
        _deactivate_others(conn, user_id, body.class_id, body.school_year_id, plan_id)
    conn.commit()
    return _detail(conn, user_id, plan_id)


@router.post("", response_model=StoffPlanDetail, status_code=201)
def create(body: StoffPlanCreate, conn: sqlite3.Connection = Depends(get_db),
           user_id: int = Depends(get_user_id)):
    return _apply_create_stoffplan(conn, user_id, body)


@router.get("", response_model=List[StoffPlanOut])
def list_(class_id: Optional[int] = Query(default=None, alias="classId"),
          school_year_id: Optional[int] = Query(default=None, alias="schoolYearId"),
          conn: sqlite3.Connection = Depends(get_db),
          user_id: int = Depends(get_user_id)):
    sql = ("SELECT p.*, (SELECT COUNT(*) FROM stoff_plan_blocks b WHERE b.plan_id = p.id) "
           "AS block_count FROM stoff_plans p WHERE p.user_id = ?")
    params = [user_id]
    if class_id is not None:
        sql += " AND p.class_id = ?"
        params.append(class_id)
    if school_year_id is not None:
        sql += " AND p.school_year_id = ?"
        params.append(school_year_id)
    sql += " ORDER BY p.updated_at DESC, p.id DESC"
    return [StoffPlanOut(**dict(r)) for r in conn.execute(sql, params)]


@router.get("/{plan_id}", response_model=StoffPlanDetail)
def detail(plan_id: int, conn: sqlite3.Connection = Depends(get_db),
           user_id: int = Depends(get_user_id)):
    return _detail(conn, user_id, plan_id)


def _stunde_out(row) -> SequenzStundeOut:
    """Wie sequenzplan.py::_out, hier dupliziert (kein Router-übergreifender Import,
    analog dem Präzedenzfall in sequenzplan.py::_week_type_for)."""
    d = dict(row)
    return SequenzStundeOut(
        id=d["id"], block_id=d["block_id"], sort_order=d["sort_order"], title=d["title"],
        grobziel=d["grobziel"], notes=d["notes"],
        is_lk=bool(d["is_lk"]), is_referat=bool(d["is_referat"]),
        is_komplexe_arbeit=bool(d["is_komplexe_arbeit"]), is_klassenarbeit=bool(d["is_klassenarbeit"]),
        weitere_notenart=d["weitere_notenart"], date=d["date"], lesson_id=d["lesson_id"],
        created_at=d["created_at"], updated_at=d["updated_at"],
    )


@router.get("/{plan_id}/combined", response_model=StoffPlanCombinedOut)
def combined(plan_id: int, conn: sqlite3.Connection = Depends(get_db),
             user_id: int = Depends(get_user_id)):
    """Stoffplan-Blöcke inkl. ihrer Sequenzstunden für die kumulierte Ansicht (Stoffplan +
    Sequenzplanung in einer Übersicht)."""
    row = row_or_404(_load_plan(conn, user_id, plan_id), "Stoffplan")
    block_rows = conn.execute(
        "SELECT * FROM stoff_plan_blocks WHERE plan_id = ? ORDER BY sort_order, id", (plan_id,)
    ).fetchall()
    weeks = _weeks_for_blocks(conn, user_id, row["school_year_id"], block_rows)
    blocks = []
    for b, w in zip(block_rows, weeks):
        stunden_rows = conn.execute(
            "SELECT * FROM sequenz_stunden WHERE block_id = ? AND user_id = ? ORDER BY sort_order, id",
            (b["id"], user_id),
        ).fetchall()
        blocks.append(StoffPlanBlockCombinedOut(
            **dict(b), weeks=w, stunden=[_stunde_out(s) for s in stunden_rows],
        ))
    return StoffPlanCombinedOut(**dict(row), blocks=blocks)


def _apply_update_stoffplan(conn, user_id: int, plan_id: int, body: StoffPlanUpdate) -> StoffPlanDetail:
    row = row_or_404(_load_plan(conn, user_id, plan_id), "Stoffplan")
    new_title = row["title"]
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(status_code=400, detail="Titel darf nicht leer sein.")
        new_title = body.title.strip()
    new_status = body.status if body.status is not None else row["status"]
    conn.execute(
        "UPDATE stoff_plans SET title = ?, status = ?, "
        "updated_at = strftime('%Y-%m-%d %H:%M:%f','now') WHERE id = ? AND user_id = ?",
        (new_title, new_status, plan_id, user_id))
    if body.blocks is not None:
        conn.execute("DELETE FROM stoff_plan_blocks WHERE plan_id = ?", (plan_id,))
        _insert_blocks(conn, plan_id, body.blocks)
    if new_status == "aktiv":
        _deactivate_others(conn, user_id, row["class_id"], row["school_year_id"], plan_id)
    conn.commit()
    return _detail(conn, user_id, plan_id)


@router.put("/{plan_id}", response_model=StoffPlanDetail)
def update(plan_id: int, body: StoffPlanUpdate, conn: sqlite3.Connection = Depends(get_db),
           user_id: int = Depends(get_user_id)):
    return _apply_update_stoffplan(conn, user_id, plan_id, body)


def _apply_delete_stoffplan(conn, user_id: int, plan_id: int) -> None:
    cur = conn.execute("DELETE FROM stoff_plans WHERE id = ? AND user_id = ?", (plan_id, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Stoffplan nicht gefunden.")


@router.delete("/{plan_id}", status_code=204)
def delete(plan_id: int, conn: sqlite3.Connection = Depends(get_db),
           user_id: int = Depends(get_user_id)):
    _apply_delete_stoffplan(conn, user_id, plan_id)


# ---------- Sync-Handler-Registry: stoff_plans (src/routers/sync.py) ----------
# stoff_plan_blocks sind eingebettet im Payload (analog lessons/phases, siehe dortiger
# Kommentar) — kein eigener entity_type, kein eigenes sync_log. _deactivate_others ändert
# ggf. weitere stoff_plans-Zeilen derselben Klasse+Schuljahr; deren eigene AU-Trigger feuern
# unabhängig vom Aufrufer (Sync-Push oder REST), sync_log bleibt also vollständig.

def _sync_fetch_stoffplan(conn, user_id, entity_id):
    row = _load_plan(conn, user_id, entity_id)
    return _detail(conn, user_id, entity_id) if row is not None else None


def _sync_create_stoffplan(conn, user_id, payload: dict) -> StoffPlanDetail:
    return _apply_create_stoffplan(conn, user_id, StoffPlanCreate(**payload))


def _sync_update_stoffplan(conn, user_id, entity_id, payload: dict) -> StoffPlanDetail:
    return _apply_update_stoffplan(conn, user_id, entity_id, StoffPlanUpdate(**payload))


def _sync_delete_stoffplan(conn, user_id, entity_id) -> None:
    _apply_delete_stoffplan(conn, user_id, entity_id)


SYNC_HANDLER = {
    "fetch": _sync_fetch_stoffplan,
    "create": _sync_create_stoffplan,
    "update": _sync_update_stoffplan,
    "delete": _sync_delete_stoffplan,
}


# ======================================================================================
# U16 – Wiederverwendung: Plan für Parallelklasse duplizieren bzw. auf neues Schuljahr
# übernehmen. Additiver Block; erzeugt stets einen NEUEN Plan (status 'entwurf').
# ======================================================================================

_UEBERNAHME_SYSTEM = (
    "Du bist didaktische Assistenz und überträgst einen bestehenden Stoffverteilungsplan "
    "auf eine andere Klasse bzw. ein anderes Schuljahr. Behalte die Lernbereiche/Themen und "
    "ihre Reihenfolge bei; passe nur die Zeiträume (und bei Bedarf den Stundenumfang leicht) "
    "an Ferien, Wochenstunden und Schuljahresgrenzen des Ziels an. Halte dich an die "
    "Schuljahresgrenzen und spare Ferien aus. Umlaute korrekt. Nur Vorschlag."
)
_UEBERNAHME_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["blocks"],
    "properties": {"blocks": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["code", "title", "ustd", "startDate", "endDate", "note"],
        "properties": {
            "code": {"type": "string"}, "title": {"type": "string"},
            "ustd": {"type": "integer"},
            "startDate": {"type": "string"}, "endDate": {"type": "string"},
            "note": {"type": "string"},
        }}}},
}


def _insert_block_dicts(conn, plan_id, block_dicts):
    """Wie _insert_blocks, aber für einfache dict-Blöcke (Duplikat-Pfad)."""
    for i, b in enumerate(block_dicts):
        conn.execute(
            "INSERT INTO stoff_plan_blocks "
            "(plan_id, lb_code, title, ustd, start_date, end_date, sort_order, conflict_note) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (plan_id, b.get("lb_code"), b.get("title"), b.get("ustd"),
             b.get("start_date"), b.get("end_date"), i, b.get("conflict_note")),
        )


def _recompute_dates(conn, user_id, target_cls, school_year_id, src_blocks):
    """Verteilt die Quellblöcke über Ferien/Wochenstunden des Ziels neu.

    Nutzt die deterministische Jahresverteilung (src/lib/planning.py). Gibt die
    berechneten Blöcke (index-gleich zu src_blocks, ggf. kürzer) zurück oder None,
    wenn kein Zielschuljahr auflösbar ist.
    """
    from ..lib.planning import distribute_lernbereiche
    sy = conn.execute("SELECT * FROM school_years WHERE id = ? AND user_id = ?",
                      (school_year_id, user_id)).fetchone()
    if sy is None:
        return None
    ferien = [(r["start_date"], r["end_date"]) for r in conn.execute(
        "SELECT start_date, end_date FROM school_dates WHERE school_year_id = ? AND user_id = ?",
        (school_year_id, user_id))]
    fixed = [r["entry_date"] for r in conn.execute(
        "SELECT entry_date FROM calendar_entries WHERE user_id = ? AND class_id = ? AND is_fixed = 1",
        (user_id, target_cls["id"]))]
    lbs = [{"id": None, "code": b["lb_code"], "title": b["title"],
            "richtwert_ustd": b["ustd"] or 0} for b in src_blocks]
    return distribute_lernbereiche(
        sy["start_date"], sy["end_date"], target_cls["weekly_hours"], lbs, ferien, fixed
    )["blocks"]


def _deterministic_blocks(conn, user_id, target_cls, school_year_id, src_blocks):
    """Blöcke des Quellplans übernehmen, Zeiträume fürs Ziel neu berechnen."""
    computed = _recompute_dates(conn, user_id, target_cls, school_year_id, src_blocks) if school_year_id else None
    out = []
    for i, b in enumerate(src_blocks):
        if computed is not None and i < len(computed):
            c = computed[i]
            out.append({
                "lb_code": b["lb_code"], "title": b["title"], "ustd": b["ustd"],
                "start_date": c["start_date"], "end_date": c["end_date"],
                "conflict_note": ("Überschneidet einen fixen Termin"
                                  if c.get("conflict_with_fixed") else None),
            })
        elif computed is not None:
            # Kein Zeitfenster mehr im Zielschuljahr → Datum offen lassen.
            out.append({
                "lb_code": b["lb_code"], "title": b["title"], "ustd": b["ustd"],
                "start_date": None, "end_date": None,
                "conflict_note": "Kein Zeitfenster mehr im Schuljahr",
            })
        else:
            # Kein Zielschuljahr auflösbar → Datumsangaben des Quellblocks unverändert.
            out.append({
                "lb_code": b["lb_code"], "title": b["title"], "ustd": b["ustd"],
                "start_date": b["start_date"], "end_date": b["end_date"],
                "conflict_note": b["conflict_note"],
            })
    return out


def _ki_blocks(conn, user_id, src_blocks, target_cls, school_year_id):
    """KI-gestützte Übernahme. Wirft (NoApiKey/Netz/JSON) → Aufrufer fällt auf det. zurück."""
    import json as _json
    from ..lib import ai
    sy = None
    ferien = []
    if school_year_id:
        sy = conn.execute("SELECT * FROM school_years WHERE id = ? AND user_id = ?",
                          (school_year_id, user_id)).fetchone()
        ferien = [(r["start_date"], r["end_date"]) for r in conn.execute(
            "SELECT start_date, end_date FROM school_dates WHERE school_year_id = ? AND user_id = ?",
            (school_year_id, user_id))]
    lb_lines = "\n".join(
        f"- {b['lb_code'] or '?'}: {b['title'] or ''} ({b['ustd'] or 0} Ustd.)" for b in src_blocks)
    parts = [(f"Zielklasse {target_cls['name']}: Fach {target_cls['subject']}, "
              f"Klassenstufe {target_cls['grade']}, Bildungsgang {target_cls['track'] or '-'}, "
              f"{target_cls['weekly_hours']} Wochenstunden.")]
    if sy:
        parts.append(f"Zielschuljahr {sy['label']} ({sy['start_date']} bis {sy['end_date']}).")
    if ferien:
        parts.append("Ferien/unterrichtsfreie Zeiträume:\n"
                     + "\n".join(f"- {s} bis {e}" for s, e in ferien))
    parts.append("Zu übertragende Blöcke (Reihenfolge beibehalten, Zeiträume neu setzen):\n" + lb_lines)
    result = ai.run(conn, user_id, "stoffplan_uebernahme", _UEBERNAHME_SYSTEM,
                    "\n\n".join(parts), _UEBERNAHME_SCHEMA, max_tokens=2500)
    ki_blocks = (_json.loads(result["text"]).get("blocks") or [])
    if not ki_blocks:
        raise ValueError("KI lieferte keine Blöcke")
    return [{
        "lb_code": b.get("code"), "title": b.get("title"), "ustd": b.get("ustd"),
        "start_date": (b.get("startDate") or None), "end_date": (b.get("endDate") or None),
        "conflict_note": (b.get("note") or None),
    } for b in ki_blocks]


@router.post("/{plan_id}/duplicate", response_model=StoffPlanDetail, status_code=201)
def duplicate(plan_id: int, body: StoffPlanDuplicateIn,
              conn: sqlite3.Connection = Depends(get_db),
              user_id: int = Depends(get_user_id)):
    """Dupliziert einen Plan für eine Zielklasse (Parallelklasse) bzw. ein neues Schuljahr.

    mode='kopie'          → Blöcke 1:1 (inkl. Datum).
    mode='deterministisch'→ Blöcke übernehmen, Zeiträume fürs Ziel neu berechnen.
    mode='ki'             → KI-gestützte Anpassung; ohne API-Key/Fehler → deterministisch.
    Der neue Plan ist immer 'entwurf'; Nachbearbeitung via PUT /stoff-plans/{id}.
    """
    src = row_or_404(_load_plan(conn, user_id, plan_id), "Stoffplan")
    src_blocks = conn.execute(
        "SELECT * FROM stoff_plan_blocks WHERE plan_id = ? ORDER BY sort_order, id", (plan_id,)
    ).fetchall()
    target_cls = row_or_404(
        conn.execute("SELECT * FROM classes WHERE id = ? AND user_id = ?",
                     (body.target_class_id, user_id)).fetchone(), "Zielklasse")
    if body.target_school_year_id is not None:
        row_or_404(conn.execute("SELECT id FROM school_years WHERE id = ? AND user_id = ?",
                                (body.target_school_year_id, user_id)).fetchone(), "Zielschuljahr")
    new_syid = body.target_school_year_id if body.target_school_year_id is not None else src["school_year_id"]

    if body.mode == "kopie":
        new_blocks = [{
            "lb_code": b["lb_code"], "title": b["title"], "ustd": b["ustd"],
            "start_date": b["start_date"], "end_date": b["end_date"],
            "conflict_note": b["conflict_note"],
        } for b in src_blocks]
    elif body.mode == "ki":
        try:
            new_blocks = _ki_blocks(conn, user_id, src_blocks, target_cls, new_syid)
        except Exception:
            # Kein API-Key hinterlegt oder KI-Fehler → sauber deterministisch übernehmen.
            new_blocks = _deterministic_blocks(conn, user_id, target_cls, new_syid, src_blocks)
    else:  # deterministisch
        new_blocks = _deterministic_blocks(conn, user_id, target_cls, new_syid, src_blocks)

    title = f"{src['title']} (Übernahme {target_cls['name']})"
    cur = conn.execute(
        "INSERT INTO stoff_plans (user_id, class_id, school_year_id, title, status) "
        "VALUES (?,?,?,?, 'entwurf')",
        (user_id, target_cls["id"], new_syid, title))
    new_id = cur.lastrowid
    _insert_block_dicts(conn, new_id, new_blocks)
    conn.commit()
    return _detail(conn, user_id, new_id)
# ============================================================ U19: PDF-Export
def _safe_name(text: str) -> str:
    """Umlaut-freundlicher, aber dateisystem-tauglicher Namensbaustein (leer möglich)."""
    cleaned = "".join(c for c in (text or "") if c.isalnum() or c in " -_/äöüÄÖÜß").strip()
    return cleaned.replace(" ", "_").replace("/", "-")


@router.get("/{plan_id}/export")
def export_plan(plan_id: int, format: str = Query("pdf"),
                conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    """Rendert den Stoffverteilungsplan als PDF-Tabelle (LB-Code | Thema | UStd |
    Zeitraum | Bemerkung). Nutzer-gescoped: fremder Plan -> 404."""
    from ..lib.stoffplan_pdf import build_stoffplan_pdf

    plan = row_or_404(_load_plan(conn, user_id, plan_id), "Stoffplan")
    if format != "pdf":
        raise HTTPException(status_code=400, detail="Nur format=pdf wird unterstützt.")

    blocks = conn.execute(
        "SELECT * FROM stoff_plan_blocks WHERE plan_id = ? ORDER BY sort_order, id", (plan_id,)
    ).fetchall()

    crow = conn.execute("SELECT name FROM classes WHERE id = ? AND user_id = ?",
                        (plan["class_id"], user_id)).fetchone()
    class_name = crow["name"] if crow else "Klasse"
    year_label = "—"
    if plan["school_year_id"] is not None:
        yrow = conn.execute("SELECT label FROM school_years WHERE id = ? AND user_id = ?",
                            (plan["school_year_id"], user_id)).fetchone()
        if yrow:
            year_label = yrow["label"]

    data = build_stoffplan_pdf(plan, blocks, class_name, year_label)

    parts = [_safe_name(p) for p in ("Stoffverteilungsplan", class_name, year_label) if _safe_name(p)]
    fname = "_".join(parts) + ".pdf"
    ascii_fb = "".join(c if c.isascii() else "_" for c in fname)  # ASCII-Fallback für den Header
    disposition = (f"attachment; filename=\"{ascii_fb}\"; "
                   f"filename*=UTF-8''{urllib.parse.quote(fname)}")  # RFC 5987: Umlaute erhalten
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": disposition})


@router.get("/{plan_id}/export-combined")
def export_combined(plan_id: int, format: str = Query("pdf"),
                    conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    """Kumulierte Ansicht (Stoffverteilungsplan + Sequenzplanung je Block) als PDF."""
    from ..lib.kumulierte_ansicht_pdf import build_kumulierte_ansicht_pdf

    if format != "pdf":
        raise HTTPException(status_code=400, detail="Nur format=pdf wird unterstützt.")
    plan_out = combined(plan_id, conn, user_id)

    crow = conn.execute("SELECT name FROM classes WHERE id = ? AND user_id = ?",
                        (plan_out.class_id, user_id)).fetchone()
    class_name = crow["name"] if crow else "Klasse"
    year_label = "—"
    if plan_out.school_year_id is not None:
        yrow = conn.execute("SELECT label FROM school_years WHERE id = ? AND user_id = ?",
                            (plan_out.school_year_id, user_id)).fetchone()
        if yrow:
            year_label = yrow["label"]

    plan_dict = plan_out.model_dump()
    data = build_kumulierte_ansicht_pdf(plan_dict, plan_dict["blocks"], class_name, year_label)

    parts = [_safe_name(p) for p in ("Kumulierte_Ansicht", class_name, year_label) if _safe_name(p)]
    fname = "_".join(parts) + ".pdf"
    ascii_fb = "".join(c if c.isascii() else "_" for c in fname)
    disposition = (f"attachment; filename=\"{ascii_fb}\"; "
                   f"filename*=UTF-8''{urllib.parse.quote(fname)}")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": disposition})
