"""Schüler-Namensliste je Klasse (nutzer-gescoped, U14).

Bewusst minimal: nur Name + Reihenfolge – Basis für einen späteren Sitzplan.
Jede Schreib-/Leseoperation prüft, dass die betroffene Klasse dem Nutzer gehört
(Fremdzugriff / nicht existent → 404).
"""
from typing import List

from fastapi import APIRouter, Depends

from ..deps import get_db, get_user_id, row_or_404
from ..schemas import StudentBulkCreate, StudentCreate, StudentOut, StudentUpdate

router = APIRouter(tags=["students"])


def _class_or_404(conn, user_id, cid):
    row = conn.execute(
        "SELECT id FROM classes WHERE id = ? AND user_id = ?", (cid, user_id)
    ).fetchone()
    return row_or_404(row, "Klasse")


def _get(conn, user_id, sid):
    row = conn.execute(
        "SELECT * FROM students WHERE id = ? AND user_id = ?", (sid, user_id)
    ).fetchone()
    return StudentOut(**dict(row)) if row else None


def _next_sort_order(conn, user_id, cid):
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM students WHERE class_id = ? AND user_id = ?",
        (cid, user_id),
    ).fetchone()
    return row["n"]


@router.get("/classes/{cid}/students", response_model=List[StudentOut])
def list_(cid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _class_or_404(conn, user_id, cid)
    rows = conn.execute(
        "SELECT * FROM students WHERE class_id = ? AND user_id = ? ORDER BY sort_order, id",
        (cid, user_id),
    ).fetchall()
    return [StudentOut(**dict(r)) for r in rows]


@router.post("/classes/{cid}/students", response_model=StudentOut, status_code=201)
def create(cid: int, body: StudentCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _class_or_404(conn, user_id, cid)
    cur = conn.execute(
        "INSERT INTO students(user_id, class_id, name, sort_order) VALUES (?,?,?,?)",
        (user_id, cid, body.name, _next_sort_order(conn, user_id, cid)),
    )
    conn.commit()
    return _get(conn, user_id, cur.lastrowid)


@router.post("/classes/{cid}/students/bulk", response_model=List[StudentOut], status_code=201)
def create_bulk(cid: int, body: StudentBulkCreate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    _class_or_404(conn, user_id, cid)
    names = [n.strip() for n in body.names if n and n.strip()]
    order = _next_sort_order(conn, user_id, cid)
    created = []
    for i, name in enumerate(names):
        cur = conn.execute(
            "INSERT INTO students(user_id, class_id, name, sort_order) VALUES (?,?,?,?)",
            (user_id, cid, name, order + i),
        )
        created.append(cur.lastrowid)
    conn.commit()
    return [_get(conn, user_id, sid) for sid in created]


@router.put("/students/{sid}", response_model=StudentOut)
def update(sid: int, body: StudentUpdate, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, sid), "Schüler")
    fields = body.model_dump(exclude_unset=True)
    if fields:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        fields.update(id=sid, uid=user_id)
        conn.execute(f"UPDATE students SET {cols} WHERE id = :id AND user_id = :uid", fields)
        conn.commit()
    return _get(conn, user_id, sid)


@router.delete("/students/{sid}", status_code=204)
def delete(sid: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row_or_404(_get(conn, user_id, sid), "Schüler")
    conn.execute("DELETE FROM students WHERE id = ? AND user_id = ?", (sid, user_id))
    conn.commit()
