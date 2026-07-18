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
)

router = APIRouter(prefix="/stoff-plans", tags=["stoffplan"])


def _load_plan(conn, user_id, plan_id):
    return conn.execute(
        "SELECT * FROM stoff_plans WHERE id = ? AND user_id = ?", (plan_id, user_id)
    ).fetchone()


def _deactivate_others(conn, user_id, class_id, school_year_id, keep_id):
    """Setzt alle anderen aktiven Pläne derselben Klasse+Schuljahr auf 'entwurf'."""
    sql = ("UPDATE stoff_plans SET status = 'entwurf', updated_at = datetime('now') "
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


def _detail(conn, user_id, plan_id) -> StoffPlanDetail:
    row = row_or_404(_load_plan(conn, user_id, plan_id), "Stoffplan")
    blocks = [StoffPlanBlockOut(**dict(r)) for r in conn.execute(
        "SELECT * FROM stoff_plan_blocks WHERE plan_id = ? ORDER BY sort_order, id", (plan_id,)
    )]
    return StoffPlanDetail(**dict(row), blocks=blocks)


@router.post("", response_model=StoffPlanDetail, status_code=201)
def create(body: StoffPlanCreate, conn: sqlite3.Connection = Depends(get_db),
           user_id: int = Depends(get_user_id)):
    if not body.title or not body.title.strip():
        raise HTTPException(status_code=400, detail="Titel darf nicht leer sein.")
    row_or_404(conn.execute("SELECT id FROM classes WHERE id = ? AND user_id = ?",
                            (body.class_id, user_id)).fetchone(), "Klasse")
    if body.school_year_id is not None:
        row_or_404(conn.execute("SELECT id FROM school_years WHERE id = ? AND user_id = ?",
                                (body.school_year_id, user_id)).fetchone(), "Schuljahr")
    cur = conn.execute(
        "INSERT INTO stoff_plans (user_id, class_id, school_year_id, title, status) "
        "VALUES (?,?,?,?,?)",
        (user_id, body.class_id, body.school_year_id, body.title.strip(), body.status))
    plan_id = cur.lastrowid
    _insert_blocks(conn, plan_id, body.blocks)
    if body.status == "aktiv":
        _deactivate_others(conn, user_id, body.class_id, body.school_year_id, plan_id)
    conn.commit()
    return _detail(conn, user_id, plan_id)


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


@router.put("/{plan_id}", response_model=StoffPlanDetail)
def update(plan_id: int, body: StoffPlanUpdate, conn: sqlite3.Connection = Depends(get_db),
           user_id: int = Depends(get_user_id)):
    row = row_or_404(_load_plan(conn, user_id, plan_id), "Stoffplan")
    new_title = row["title"]
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(status_code=400, detail="Titel darf nicht leer sein.")
        new_title = body.title.strip()
    new_status = body.status if body.status is not None else row["status"]
    conn.execute(
        "UPDATE stoff_plans SET title = ?, status = ?, updated_at = datetime('now') "
        "WHERE id = ? AND user_id = ?", (new_title, new_status, plan_id, user_id))
    if body.blocks is not None:
        conn.execute("DELETE FROM stoff_plan_blocks WHERE plan_id = ?", (plan_id,))
        _insert_blocks(conn, plan_id, body.blocks)
    if new_status == "aktiv":
        _deactivate_others(conn, user_id, row["class_id"], row["school_year_id"], plan_id)
    conn.commit()
    return _detail(conn, user_id, plan_id)


@router.delete("/{plan_id}", status_code=204)
def delete(plan_id: int, conn: sqlite3.Connection = Depends(get_db),
           user_id: int = Depends(get_user_id)):
    cur = conn.execute("DELETE FROM stoff_plans WHERE id = ? AND user_id = ?", (plan_id, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Stoffplan nicht gefunden.")


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
