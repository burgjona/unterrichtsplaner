"""Sitzplan je Klasse (nutzer-gescoped, U18).

Ein Sitzplan speichert eine Rasteranordnung (rows x cols) mit den auf Plätze
verteilten Schülern der Klasse. Jede Operation prüft, dass Klasse bzw. Sitzplan
dem angemeldeten Nutzer gehören (sonst 404). Export als PDF (reportlab-Raster).
Optionale KI-Anordnung ordnet die Schüler nach einer Freitext-Beschreibung.
"""
import json
import sqlite3
import urllib.parse
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ..deps import get_db, get_user_id, row_or_404
from ..lib import ai
from ..lib.seating_pdf import build_pdf
from ..schemas import (
    SeatPlanAiArrange, SeatPlanCreate, SeatPlanLayout, SeatPlanOut, SeatPlanUpdate)

router = APIRouter(tags=["seating"])

_STR = {"type": "string"}


def _class_or_404(conn, user_id, cid):
    row = conn.execute(
        "SELECT * FROM classes WHERE id = ? AND user_id = ?", (cid, user_id)
    ).fetchone()
    return row_or_404(row, "Klasse")


def _to_out(row) -> SeatPlanOut:
    d = dict(row)
    layout = json.loads(d["layout_json"]) if d["layout_json"] else {"seats": []}
    return SeatPlanOut(
        id=d["id"], class_id=d["class_id"], name=d["name"], rows=d["rows"], cols=d["cols"],
        layout_json=SeatPlanLayout(**layout), created_at=d["created_at"], updated_at=d["updated_at"],
    )


def _get(conn, user_id, pid):
    row = conn.execute(
        "SELECT * FROM seat_plans WHERE id = ? AND user_id = ?", (pid, user_id)
    ).fetchone()
    return _to_out(row) if row else None


def _layout_str(layout: SeatPlanLayout) -> str:
    return json.dumps(layout.model_dump(by_alias=True), ensure_ascii=False)


@router.get("/classes/{cid}/seat-plans", response_model=List[SeatPlanOut])
def list_(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _class_or_404(conn, user_id, cid)
    rows = conn.execute(
        "SELECT * FROM seat_plans WHERE class_id = ? AND user_id = ? ORDER BY updated_at DESC, id DESC",
        (cid, user_id),
    ).fetchall()
    return [_to_out(r) for r in rows]


@router.post("/classes/{cid}/seat-plans", response_model=SeatPlanOut, status_code=201)
def create(cid: int, body: SeatPlanCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _class_or_404(conn, user_id, cid)
    cur = conn.execute(
        "INSERT INTO seat_plans(user_id, class_id, name, rows, cols, layout_json) VALUES (?,?,?,?,?,?)",
        (user_id, cid, body.name, body.rows, body.cols, _layout_str(body.layout_json)),
    )
    conn.commit()
    return _get(conn, user_id, cur.lastrowid)


@router.get("/seat-plans/{pid}", response_model=SeatPlanOut)
def get_(pid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    return row_or_404(_get(conn, user_id, pid), "Sitzplan")


@router.put("/seat-plans/{pid}", response_model=SeatPlanOut)
def update(pid: int, body: SeatPlanUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, pid), "Sitzplan")
    fields = body.model_dump(exclude_unset=True)
    if "layout_json" in fields and body.layout_json is not None:
        fields["layout_json"] = _layout_str(body.layout_json)
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        params = dict(fields, id=pid, uid=user_id)
        conn.execute(
            f"UPDATE seat_plans SET {cols}, updated_at = datetime('now') WHERE id = :id AND user_id = :uid",
            params,
        )
        conn.commit()
    return _get(conn, user_id, pid)


@router.delete("/seat-plans/{pid}", status_code=204)
def delete(pid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, pid), "Sitzplan")
    conn.execute("DELETE FROM seat_plans WHERE id = ? AND user_id = ?", (pid, user_id))
    conn.commit()


@router.get("/seat-plans/{pid}/export")
def export(pid: int, format: str = Query("pdf"),
           conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    plan = row_or_404(_get(conn, user_id, pid), "Sitzplan")
    cls = conn.execute("SELECT name, subject FROM classes WHERE id = ? AND user_id = ?",
                       (plan.class_id, user_id)).fetchone()
    class_label = f"Klasse {cls['name']} ({cls['subject']})" if cls else ""
    seats = [s.model_dump() for s in plan.layout_json.seats]
    data = build_pdf(plan.name, class_label, plan.rows, plan.cols, seats)

    base = "".join(c for c in (plan.name or "Sitzplan") if c.isalnum() or c in " -_").strip() or "Sitzplan"
    fname = f"Sitzplan_{base}.pdf"
    ascii_fb = "".join(c if c.isascii() else "_" for c in fname)      # ASCII-Fallback für den Header
    disposition = (f"attachment; filename=\"{ascii_fb}\"; "
                   f"filename*=UTF-8''{urllib.parse.quote(fname)}")    # RFC 5987: Umlaute erhalten
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": disposition})


# ---------- KI-Anordnung (U18) ----------
_AI_SYSTEM = (
    "Du bist Assistenz einer Lehrkraft und ordnest die Schüler einer Klasse auf einem "
    "Sitzplan-Raster an. Das Raster hat Reihen (row, 0 = vorne, an der Tafel) und Spalten "
    "(col, 0 = links). Berücksichtige die Freitext-Wünsche der Lehrkraft (z. B. 'Max nicht "
    "neben Paul', 'Lisa nach vorn'). Verteile möglichst alle genannten Schüler; nutze keine "
    "Namen, die nicht in der Liste stehen, und erfinde keine Schüler. Jeder Platz höchstens "
    "einmal belegen; row < Anzahl Reihen, col < Anzahl Spalten. Umlaute korrekt."
)
_AI_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["seats"],
    "properties": {"seats": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["row", "col", "name"],
        "properties": {"row": {"type": "integer"}, "col": {"type": "integer"}, "name": _STR}}}},
}


def _ai_arrange(conn, user_id, cid, body: SeatPlanAiArrange):
    _class_or_404(conn, user_id, cid)
    students = conn.execute(
        "SELECT id, name FROM students WHERE class_id = ? AND user_id = ? ORDER BY sort_order, id",
        (cid, user_id),
    ).fetchall()
    if not students:
        raise HTTPException(status_code=400, detail="Diese Klasse hat noch keine Schüler – bitte zuerst Namen erfassen.")
    if body.rows < 1 or body.cols < 1:
        raise HTTPException(status_code=400, detail="Reihen und Spalten müssen mindestens 1 sein.")

    names = [s["name"] for s in students]
    name_to_id = {s["name"]: s["id"] for s in students}
    user_text = (
        f"Raster: {body.rows} Reihen x {body.cols} Spalten.\n"
        f"Schüler ({len(names)}): {', '.join(names)}.\n"
        f"Wünsche der Lehrkraft:\n{body.description.strip() or '-'}"
    )
    try:
        result = ai.run(conn, user_id, "sitzplan", _AI_SYSTEM, user_text, _AI_SCHEMA)
    except ai.NoApiKey:
        raise HTTPException(status_code=400, detail="Kein API-Key hinterlegt – bitte in den Einstellungen eintragen.")
    except Exception as exc:  # Netz-/Auth-/API-Fehler sauber weiterreichen
        raise HTTPException(status_code=502, detail=f"KI-Anfrage fehlgeschlagen: {exc}")
    try:
        data = json.loads(result["text"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=502, detail="KI-Antwort war kein gültiges JSON.")

    # studentId anreichern; Plätze außerhalb des Rasters oder ohne bekannten Namen verwerfen.
    seats = []
    seen = set()
    for s in data.get("seats", []):
        r, c, name = s.get("row"), s.get("col"), s.get("name")
        if r is None or c is None or not (0 <= r < body.rows and 0 <= c < body.cols):
            continue
        if name not in name_to_id or (r, c) in seen:
            continue
        seen.add((r, c))
        seats.append({"row": r, "col": c, "name": name, "studentId": name_to_id[name]})
    return {"suggestion": {"seats": seats}, "cached": result["cached"]}


@router.post("/classes/{cid}/seat-plans/ai-arrange")
def ai_arrange_for_class(cid: int, body: SeatPlanAiArrange,
                         conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    return _ai_arrange(conn, user_id, cid, body)


@router.post("/seat-plans/ai-arrange")
def ai_arrange(body: SeatPlanAiArrange,
               conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    if body.class_id is None:
        raise HTTPException(status_code=400, detail="classId ist erforderlich.")
    return _ai_arrange(conn, user_id, body.class_id, body)
