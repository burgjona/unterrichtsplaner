"""Notenmodul: Fallback-Notenverwaltung neben dem Schulmanager (docs/konzept_noten.md).

Zwei Ebenen: eine Leistung (grade_items) ist der Anlass – Klassenarbeit, Referat,
Stundenleistung –, darunter hängen die Noten der einzelnen Schüler (grades). Die
Notenmatrix der Ansicht ist genau dieses Kreuzprodukt; eine Einzelnote ist eine Leistung
mit einer gefüllten Zelle.

Noten werden als Dezimalzahl auf einem Viertelraster gespeichert (1+ = 0.75, 2- = 2.25);
Parsen, Formatieren und Durchschnitte liegen in src/lib/noten.py, damit die Rechenlogik
ohne DB testbar bleibt.

Eine leere Zelle bedeutet schlicht "nicht bewertet" und zählt nicht in den Durchschnitt –
deshalb löscht das Speichern einer leeren Note die Zeile, statt sie mit NULL zu führen.
"""
import urllib.parse
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..deps import get_db, get_user_id, row_or_404
from ..lib import noten as calc
from ..lib import noten_export
from ..schemas import (
    GewichtungIn, GewichtungOut, GradeBulkIn, GradeIn, GradeItemCreate, GradeItemOut,
    GradeItemSyncCreate, GradeItemUpdate, GradeMatrixOut, GradeMatrixStudent, GradeOut,
    GradeSyncCreate, StudentGradeSummary, TermGradeIn, TermGradeOut, TermGradeSyncCreate,
)

router = APIRouter(tags=["noten"])

_NOW = "strftime('%Y-%m-%d %H:%M:%f','now')"


def term_from_date(iso_date: str) -> str:
    """Vorbelegung des Halbjahres aus dem Datum; im Formular überschreibbar.

    Sachsen: das erste Halbjahr endet Anfang Februar – August bis Januar zählen zu HJ1.
    """
    try:
        month = int(iso_date[5:7])
    except (TypeError, ValueError, IndexError):
        return "HJ1"
    return "HJ1" if month >= 8 or month == 1 else "HJ2"


def _class_or_404(conn, user_id, cid):
    # SELECT * statt einzelner Spalten: der Export braucht neben der Gewichtung auch Name,
    # Fach und Schuljahr für die Kopfzeile der Dokumente.
    row = conn.execute(
        "SELECT * FROM classes WHERE id = ? AND user_id = ?", (cid, user_id)
    ).fetchone()
    return row_or_404(row, "Klasse")


def _item_row(conn, user_id, iid):
    return conn.execute(
        "SELECT * FROM grade_items WHERE id = ? AND user_id = ?", (iid, user_id)
    ).fetchone()


def _get_item(conn, user_id, iid) -> Optional[GradeItemOut]:
    row = _item_row(conn, user_id, iid)
    return GradeItemOut(**dict(row)) if row else None


def _grade_out(row) -> GradeOut:
    data = dict(row)
    return GradeOut(**data, label=calc.format_note(data.get("value")))


def _get_grade(conn, user_id, gid) -> Optional[GradeOut]:
    row = conn.execute(
        "SELECT * FROM grades WHERE id = ? AND user_id = ?", (gid, user_id)
    ).fetchone()
    return _grade_out(row) if row else None


def _get_term_grade(conn, user_id, tid) -> Optional[TermGradeOut]:
    row = conn.execute(
        "SELECT * FROM term_grades WHERE id = ? AND user_id = ?", (tid, user_id)
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    return TermGradeOut(**data, label=calc.format_note(data.get("value")))


def _student_in_class(conn, user_id, cid, sid):
    row = conn.execute(
        "SELECT id FROM students WHERE id = ? AND user_id = ? AND class_id = ?",
        (sid, user_id, cid),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Schüler nicht in dieser Klasse.")


# ---------- Leistungen ----------

def _apply_item_create(conn, user_id, cid: int, body: GradeItemCreate) -> GradeItemOut:
    _class_or_404(conn, user_id, cid)
    cur = conn.execute(
        f"INSERT INTO grade_items(user_id, class_id, title, kind, size, date, term, note, "
        f"lesson_id, updated_at) VALUES (?,?,?,?,?,?,?,?,?, {_NOW})",
        (user_id, cid, body.title, body.kind, body.size, body.date,
         body.term or term_from_date(body.date), body.note, body.lesson_id),
    )
    return _get_item(conn, user_id, cur.lastrowid)


def _apply_item_update(conn, user_id, iid: int, body: GradeItemUpdate) -> GradeItemOut:
    row_or_404(_item_row(conn, user_id, iid), "Leistung")
    fields = body.model_dump(exclude_unset=True)
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields) + f", updated_at = {_NOW}"
        fields.update(id=iid, uid=user_id)
        conn.execute(f"UPDATE grade_items SET {cols} WHERE id = :id AND user_id = :uid", fields)
    return _get_item(conn, user_id, iid)


def _apply_item_delete(conn, user_id, iid: int) -> None:
    cur = conn.execute("DELETE FROM grade_items WHERE id = ? AND user_id = ?", (iid, user_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Leistung nicht gefunden.")


@router.get("/classes/{cid}/grade-items", response_model=List[GradeItemOut])
def list_items(cid: int, term: Optional[str] = Query(None), conn=Depends(get_db),
               user_id: int = Depends(get_user_id)):
    _class_or_404(conn, user_id, cid)
    sql = "SELECT * FROM grade_items WHERE class_id = ? AND user_id = ?"
    args = [cid, user_id]
    if term:
        sql += " AND term = ?"
        args.append(term)
    rows = conn.execute(sql + " ORDER BY date, id", args).fetchall()
    return [GradeItemOut(**dict(r)) for r in rows]


@router.post("/classes/{cid}/grade-items", response_model=GradeItemOut, status_code=201)
def create_item(cid: int, body: GradeItemCreate, conn=Depends(get_db),
                user_id: int = Depends(get_user_id)):
    result = _apply_item_create(conn, user_id, cid, body)
    conn.commit()
    return result


@router.put("/grade-items/{iid}", response_model=GradeItemOut)
def update_item(iid: int, body: GradeItemUpdate, conn=Depends(get_db),
                user_id: int = Depends(get_user_id)):
    result = _apply_item_update(conn, user_id, iid, body)
    conn.commit()
    return result


@router.delete("/grade-items/{iid}", status_code=204)
def delete_item(iid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _apply_item_delete(conn, user_id, iid)
    conn.commit()


# ---------- Noten ----------

def _upsert_grade(conn, user_id, iid: int, sid: int, body: GradeIn) -> Optional[GradeOut]:
    """Legt die Zelle an oder aktualisiert sie; leere Note ohne Hinweis löscht die Zeile."""
    item = row_or_404(_item_row(conn, user_id, iid), "Leistung")
    _student_in_class(conn, user_id, item["class_id"], sid)

    if body.value is None and not (body.comment or "").strip():
        conn.execute(
            "DELETE FROM grades WHERE item_id = ? AND student_id = ? AND user_id = ?",
            (iid, sid, user_id),
        )
        return None

    existing = conn.execute(
        "SELECT id FROM grades WHERE item_id = ? AND student_id = ? AND user_id = ?",
        (iid, sid, user_id),
    ).fetchone()
    if existing:
        conn.execute(
            f"UPDATE grades SET value = ?, comment = ?, updated_at = {_NOW} WHERE id = ?",
            (body.value, body.comment, existing["id"]),
        )
        gid = existing["id"]
    else:
        gid = conn.execute(
            f"INSERT INTO grades(user_id, item_id, student_id, value, comment, updated_at) "
            f"VALUES (?,?,?,?,?, {_NOW})",
            (user_id, iid, sid, body.value, body.comment),
        ).lastrowid
    return _get_grade(conn, user_id, gid)


@router.put("/grade-items/{iid}/students/{sid}/grade", response_model=Optional[GradeOut])
def put_grade(iid: int, sid: int, body: GradeIn, conn=Depends(get_db),
              user_id: int = Depends(get_user_id)):
    result = _upsert_grade(conn, user_id, iid, sid, body)
    conn.commit()
    return result


@router.put("/grade-items/{iid}/grades", response_model=List[GradeOut])
def put_grades_bulk(iid: int, body: GradeBulkIn, conn=Depends(get_db),
                    user_id: int = Depends(get_user_id)):
    """Schnellerfassung: mehrere Zellen einer Leistung in einem Rutsch."""
    out = []
    for entry in body.grades:
        result = _upsert_grade(
            conn, user_id, iid, entry.student_id,
            GradeIn(value=entry.value, comment=entry.comment),
        )
        if result:
            out.append(result)
    conn.commit()
    return out


def _apply_grade_delete(conn, user_id, gid: int) -> None:
    cur = conn.execute("DELETE FROM grades WHERE id = ? AND user_id = ?", (gid, user_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note nicht gefunden.")


@router.delete("/grades/{gid}", status_code=204)
def delete_grade(gid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _apply_grade_delete(conn, user_id, gid)
    conn.commit()


# ---------- Zeugnisnoten ----------

def _apply_term_grade(conn, user_id, cid: int, sid: int, term: str,
                      body: TermGradeIn) -> Optional[TermGradeOut]:
    _class_or_404(conn, user_id, cid)
    _student_in_class(conn, user_id, cid, sid)
    if term not in ("HJ1", "HJ2"):
        raise HTTPException(status_code=422, detail="term muss 'HJ1' oder 'HJ2' sein.")

    existing = conn.execute(
        "SELECT id FROM term_grades WHERE student_id = ? AND term = ? AND user_id = ?",
        (sid, term, user_id),
    ).fetchone()

    if body.value is None:
        # Von Hand gesetzte Note zurücknehmen → die Ansicht zeigt wieder den Vorschlag.
        if existing:
            conn.execute("DELETE FROM term_grades WHERE id = ?", (existing["id"],))
        return None

    if existing:
        conn.execute(
            f"UPDATE term_grades SET value = ?, comment = ?, updated_at = {_NOW} WHERE id = ?",
            (body.value, body.comment, existing["id"]),
        )
        tid = existing["id"]
    else:
        tid = conn.execute(
            f"INSERT INTO term_grades(user_id, class_id, student_id, term, value, comment, "
            f"updated_at) VALUES (?,?,?,?,?,?, {_NOW})",
            (user_id, cid, sid, term, body.value, body.comment),
        ).lastrowid
    return _get_term_grade(conn, user_id, tid)


@router.put("/classes/{cid}/students/{sid}/term-grade", response_model=Optional[TermGradeOut])
def put_term_grade(cid: int, sid: int, body: TermGradeIn, term: str = Query("HJ1"),
                   conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    result = _apply_term_grade(conn, user_id, cid, sid, term, body)
    conn.commit()
    return result


# ---------- Gewichtung ----------

@router.get("/classes/{cid}/noten-gewichtung", response_model=GewichtungOut)
def get_gewichtung(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row = _class_or_404(conn, user_id, cid)
    return GewichtungOut(class_id=cid, gross_anteil=row["noten_gross_anteil"])


@router.put("/classes/{cid}/noten-gewichtung", response_model=GewichtungOut)
def put_gewichtung(cid: int, body: GewichtungIn, conn=Depends(get_db),
                   user_id: int = Depends(get_user_id)):
    _class_or_404(conn, user_id, cid)
    anteil = calc.clamp_anteil(body.gross_anteil)
    conn.execute(
        f"UPDATE classes SET noten_gross_anteil = ?, updated_at = {_NOW} "
        f"WHERE id = ? AND user_id = ?", (anteil, cid, user_id),
    )
    conn.commit()
    return GewichtungOut(class_id=cid, gross_anteil=anteil)


# ---------- Notenmatrix (Hauptansicht) ----------

def _collect(conn, user_id, cid: int, term: str) -> dict:
    """Alles, was Ansicht UND Word-Export einer Klasse für ein Halbjahr brauchen.

    Bewusst eine gemeinsame Quelle: sonst driften die Durchschnitte auf dem Bildschirm und
    die im Ausdruck irgendwann auseinander. Rückgabe in einfachen Strukturen (dict/list),
    die Pydantic-Modelle baut erst matrix() daraus.
    """
    cls = _class_or_404(conn, user_id, cid)
    anteil = calc.clamp_anteil(cls["noten_gross_anteil"])

    students = [dict(r) for r in conn.execute(
        "SELECT id, name, sort_order FROM students WHERE class_id = ? AND user_id = ? "
        "ORDER BY sort_order, id", (cid, user_id),
    ).fetchall()]
    items = [dict(r) for r in conn.execute(
        "SELECT * FROM grade_items WHERE class_id = ? AND user_id = ? AND term = ? "
        "ORDER BY date, id", (cid, user_id, term),
    ).fetchall()]
    size_by_item = {it["id"]: it["size"] for it in items}

    grade_rows = []
    if size_by_item:
        placeholders = ",".join("?" for _ in size_by_item)
        grade_rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM grades WHERE user_id = ? AND item_id IN ({placeholders})",
            (user_id, *size_by_item),
        ).fetchall()]

    term_grades = {
        r["student_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM term_grades WHERE user_id = ? AND class_id = ? AND term = ?",
            (user_id, cid, term),
        ).fetchall()
    }

    by_student = {}
    for g in grade_rows:
        by_student.setdefault(g["student_id"], []).append(
            {"value": g["value"], "size": size_by_item.get(g["item_id"])}
        )

    summaries = {}
    for s in students:
        summary = calc.summarize(by_student.get(s["id"], []), anteil)
        tg = term_grades.get(s["id"])
        summary["term_grade"] = tg["value"] if tg else None
        summary["term_grade_comment"] = tg["comment"] if tg else None
        summaries[s["id"]] = summary

    year = conn.execute(
        "SELECT label FROM school_years WHERE id = ?", (cls["school_year_id"],)
    ).fetchone() if cls["school_year_id"] else None

    return {
        "class": dict(cls), "school_year": year["label"] if year else None,
        "term": term, "gross_anteil": anteil,
        "students": students, "items": items,
        "grade_rows": grade_rows,
        "grades": {(g["item_id"], g["student_id"]): g for g in grade_rows},
        "summaries": summaries,
    }


@router.get("/classes/{cid}/noten", response_model=GradeMatrixOut)
def matrix(cid: int, term: str = Query("HJ1"), conn=Depends(get_db),
           user_id: int = Depends(get_user_id)):
    ctx = _collect(conn, user_id, cid, term)
    return GradeMatrixOut(
        class_id=cid, term=term, gross_anteil=ctx["gross_anteil"],
        students=[GradeMatrixStudent(**s) for s in ctx["students"]],
        items=[GradeItemOut(**it) for it in ctx["items"]],
        grades=[_grade_out(g) for g in ctx["grade_rows"]],
        summaries=[StudentGradeSummary(student_id=sid, **summary)
                   for sid, summary in ctx["summaries"].items()],
    )


# ---------- Word-Export (docs/konzept_noten.md, Abschnitt 7) ----------

def _docx_response(data: bytes, filename: str) -> Response:
    # ASCII-Fallback + RFC 5987, damit Umlaute im Dateinamen erhalten bleiben.
    ascii_fb = "".join(c if c.isascii() else "_" for c in filename)
    disposition = (f"attachment; filename=\"{ascii_fb}\"; "
                   f"filename*=UTF-8''{urllib.parse.quote(filename)}")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": disposition},
    )


def _safe(text: str) -> str:
    """Dateinamens-Baustein: Umlaute bleiben, nur Pfad-/Sonderzeichen fliegen raus."""
    cleaned = "".join(c if (c.isalnum() or c in " -_") else "_" for c in (text or "")).strip()
    return cleaned or "Noten"


@router.get("/classes/{cid}/noten/export/matrix")
def export_matrix(cid: int, term: str = Query("HJ1"), conn=Depends(get_db),
                  user_id: int = Depends(get_user_id)):
    ctx = _collect(conn, user_id, cid, term)
    data = noten_export.build_matrix_docx(ctx)
    return _docx_response(data, f"Notenübersicht_{_safe(ctx['class']['name'])}_{term}.docx")


@router.get("/classes/{cid}/noten/export/schueler")
def export_student_sheets(cid: int, term: str = Query("HJ1"), conn=Depends(get_db),
                          user_id: int = Depends(get_user_id)):
    ctx = _collect(conn, user_id, cid, term)
    data = noten_export.build_student_sheets_docx(ctx)
    return _docx_response(data, f"Notenblätter_{_safe(ctx['class']['name'])}_{term}.docx")


@router.get("/classes/{cid}/noten/export/zeugnis")
def export_term_grades(cid: int, term: str = Query("HJ1"), conn=Depends(get_db),
                       user_id: int = Depends(get_user_id)):
    ctx = _collect(conn, user_id, cid, term)
    data = noten_export.build_term_docx(ctx)
    return _docx_response(data, f"Zeugnisnoten_{_safe(ctx['class']['name'])}_{term}.docx")


@router.get("/grade-items/{iid}/export")
def export_item(iid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    item = dict(row_or_404(_item_row(conn, user_id, iid), "Leistung"))
    ctx = _collect(conn, user_id, item["class_id"], item["term"])
    data = noten_export.build_item_docx(ctx, item)
    return _docx_response(data, f"Auswertung_{_safe(item['title'])}.docx")


# ---------- Sync-Handler-Registry (src/routers/sync.py) ----------

def _sync_item_create(conn, user_id, payload: dict) -> GradeItemOut:
    body = GradeItemSyncCreate(**payload)
    return _apply_item_create(conn, user_id, body.class_id, body)


SYNC_HANDLER_GRADE_ITEMS = {
    "fetch": _get_item,
    "create": _sync_item_create,
    "update": lambda conn, uid, eid, payload: _apply_item_update(
        conn, uid, eid, GradeItemUpdate(**payload)),
    "delete": lambda conn, uid, eid: _apply_item_delete(conn, uid, eid),
}


def _sync_grade_create(conn, user_id, payload: dict) -> GradeOut:
    body = GradeSyncCreate(**payload)
    result = _upsert_grade(conn, user_id, body.item_id, body.student_id,
                           GradeIn(value=body.value, comment=body.comment))
    if result is None:
        raise HTTPException(status_code=422, detail="Leere Note kann nicht angelegt werden.")
    return result


def _sync_grade_update(conn, user_id, eid, payload: dict) -> GradeOut:
    row = row_or_404(conn.execute(
        "SELECT item_id, student_id FROM grades WHERE id = ? AND user_id = ?", (eid, user_id)
    ).fetchone(), "Note")
    result = _upsert_grade(conn, user_id, row["item_id"], row["student_id"], GradeIn(**payload))
    if result is None:
        raise HTTPException(status_code=404, detail="Note nicht gefunden.")
    return result


SYNC_HANDLER_GRADES = {
    "fetch": _get_grade,
    "create": _sync_grade_create,
    "update": _sync_grade_update,
    "delete": lambda conn, uid, eid: _apply_grade_delete(conn, uid, eid),
}


def _sync_term_grade_create(conn, user_id, payload: dict) -> TermGradeOut:
    body = TermGradeSyncCreate(**payload)
    row = row_or_404(conn.execute(
        "SELECT class_id FROM students WHERE id = ? AND user_id = ?", (body.student_id, user_id)
    ).fetchone(), "Schüler")
    result = _apply_term_grade(conn, user_id, row["class_id"], body.student_id, body.term,
                               TermGradeIn(value=body.value, comment=body.comment))
    if result is None:
        raise HTTPException(status_code=422, detail="Zeugnisnote ohne Wert.")
    return result


def _sync_term_grade_update(conn, user_id, eid, payload: dict) -> TermGradeOut:
    row = row_or_404(conn.execute(
        "SELECT class_id, student_id, term FROM term_grades WHERE id = ? AND user_id = ?",
        (eid, user_id),
    ).fetchone(), "Zeugnisnote")
    result = _apply_term_grade(conn, user_id, row["class_id"], row["student_id"], row["term"],
                               TermGradeIn(**payload))
    if result is None:
        raise HTTPException(status_code=404, detail="Zeugnisnote nicht gefunden.")
    return result


def _apply_term_grade_delete(conn, user_id, tid: int) -> None:
    cur = conn.execute("DELETE FROM term_grades WHERE id = ? AND user_id = ?", (tid, user_id))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Zeugnisnote nicht gefunden.")


SYNC_HANDLER_TERM_GRADES = {
    "fetch": _get_term_grade,
    "create": _sync_term_grade_create,
    "update": _sync_term_grade_update,
    "delete": _apply_term_grade_delete,
}
