"""Lehrplan-Abhakmodul: Checkliste je Klasse aus Lehrplan-Referenz + Abhak-Status.

Die Referenz (lehrplan_ziele, lernbereiche) ist global; der Abhak-Status
(lehrplan_checks) haengt an der konkreten, schuljahres-spezifischen Klasse.
Reines Online-REST (keine Offline-Sync-Anbindung) - der Status ist idempotent
und unkritisch; eine Sync-Anbindung liesse sich bei Bedarf spaeter ergaenzen.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_db, get_user_id
from ..schemas import LehrplanCheckIn, LehrplanCheckOut, LehrplanChecklistItem, LehrplanChecklistOut

router = APIRouter(prefix="/lehrplan", tags=["lehrplan"])

_ITEM_TYPES = {"ziel", "lb"}


def _class_or_404(conn, user_id: int, class_id: int):
    row = conn.execute(
        "SELECT id, subject, grade, track FROM classes WHERE id = ? AND user_id = ? AND archived_at IS NULL",
        (class_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Klasse nicht gefunden.")
    return row


@router.get("/checklist", response_model=LehrplanChecklistOut)
def checklist(
    class_id: int = Query(alias="classId"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    cls = _class_or_404(conn, user_id, class_id)
    subject, grade, track = cls["subject"], cls["grade"], cls["track"]

    checked = {
        (r["item_type"], r["item_ref"]): r["checked_at"]
        for r in conn.execute(
            "SELECT item_type, item_ref, checked_at FROM lehrplan_checks WHERE user_id = ? AND class_id = ?",
            (user_id, class_id),
        ).fetchall()
    }

    def _match(sql_extra: str):
        # Bildungsgang: Deutsch ab Kl. 7 mit RS/HS getrennt; Kl. 5/6 und WTH 'gemischt'.
        params = [subject, grade]
        track_sql = ""
        if track:
            track_sql = " AND track = ?"
            params.append(track)
        return conn.execute(
            f"SELECT * FROM {sql_extra} WHERE subject = ? AND grade = ?{track_sql} ORDER BY sort_order",
            params,
        ).fetchall()

    ziele = [
        LehrplanChecklistItem(
            id=r["id"], code=r["code"], text=r["text"],
            checked_at=checked.get(("ziel", r["id"])),
        )
        for r in _match("lehrplan_ziele")
    ]
    lernbereiche = [
        LehrplanChecklistItem(
            id=r["id"], code=r["code"], text=r["title"], richtwert_ustd=r["richtwert_ustd"],
            checked_at=checked.get(("lb", r["id"])),
        )
        for r in _match("lernbereiche")
    ]
    return LehrplanChecklistOut(
        class_id=class_id, subject=subject, grade=grade, track=track,
        ziele=ziele, lernbereiche=lernbereiche,
    )


@router.put("/checks", response_model=LehrplanCheckOut)
def set_check(body: LehrplanCheckIn, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    if body.item_type not in _ITEM_TYPES:
        raise HTTPException(status_code=422, detail="itemType muss 'ziel' oder 'lb' sein.")
    cls = _class_or_404(conn, user_id, body.class_id)

    # Referenz muss existieren UND zum Fach/Klassenstufe/Bildungsgang der Klasse passen -
    # sonst entstuenden Haken auf Eintraegen, die die Checkliste nie anzeigt.
    ref_table = "lehrplan_ziele" if body.item_type == "ziel" else "lernbereiche"
    ref = conn.execute(
        f"SELECT subject, grade, track FROM {ref_table} WHERE id = ?", (body.item_ref,)
    ).fetchone()
    if ref is None or (ref["subject"], ref["grade"]) != (cls["subject"], cls["grade"]) or (
        cls["track"] and ref["track"] != cls["track"]
    ):
        raise HTTPException(status_code=404, detail="Lehrplan-Eintrag passt nicht zu dieser Klasse.")

    if body.checked:
        conn.execute(
            """INSERT INTO lehrplan_checks (user_id, class_id, item_type, item_ref)
               VALUES (?,?,?,?)
               ON CONFLICT(user_id, class_id, item_type, item_ref) DO NOTHING""",
            (user_id, body.class_id, body.item_type, body.item_ref),
        )
    else:
        conn.execute(
            "DELETE FROM lehrplan_checks WHERE user_id = ? AND class_id = ? AND item_type = ? AND item_ref = ?",
            (user_id, body.class_id, body.item_type, body.item_ref),
        )
    conn.commit()

    row = conn.execute(
        "SELECT checked_at FROM lehrplan_checks WHERE user_id = ? AND class_id = ? AND item_type = ? AND item_ref = ?",
        (user_id, body.class_id, body.item_type, body.item_ref),
    ).fetchone()
    return LehrplanCheckOut(
        class_id=body.class_id, item_type=body.item_type, item_ref=body.item_ref,
        checked=row is not None, checked_at=row["checked_at"] if row else None,
    )
