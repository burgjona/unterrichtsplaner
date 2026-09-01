"""Lehrplan-Abhakmodul: Checkliste je Klasse aus Lehrplan-Referenz + Abhak-Status.

Die Referenz (lehrplan_ziele, lernbereiche, lehrplan_lernziele) ist global; der
Abhak-Status (lehrplan_checks) haengt an der konkreten, schuljahres-spezifischen
Klasse. Reines Online-REST (keine Offline-Sync-Anbindung) - der Status ist
idempotent und unkritisch.

Die "grossen Lernziele" je Lernbereich (linke Spalte der LP-Tabelle) werden per
KI aus lernbereiche.detail_md extrahiert (POST /lehrplan/lernziele/extract, laeuft
als Hintergrund-Job ueber alle Lernbereiche, idempotent/wiederaufnehmbar).
"""
import json
import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from ..db import connect
from ..deps import get_db, get_user_id
from ..lib import ai
from ..schemas import (
    LehrplanCheckIn, LehrplanCheckOut, LehrplanChecklistItem, LehrplanChecklistOut,
    LehrplanLernzielItem,
)

router = APIRouter(prefix="/lehrplan", tags=["lehrplan"])

_ITEM_TYPES = {"ziel", "lb", "lernziel"}

_LERNZIELE_SYSTEM = (
    "Du extrahierst aus dem OCR-Rohtext eines Lernbereichs im saechsischen Lehrplan "
    "Oberschule die 'grossen Lernziele' - das ist die linke Spalte der Lehrplan-Tabelle. "
    "Diese Lernziele beginnen immer mit einem Anforderungsverb: 'Einblick gewinnen', "
    "'Kennen', 'Uebertragen', 'Beherrschen', 'Anwenden', 'Beurteilen', 'Sich positionieren', "
    "'Gestalten', 'Problemloesen'. Gib jedes grosse Lernziel als vollstaendige Ueberschrift "
    "zurueck und fuehre durch OCR entstandene Zeilenumbrueche und Silbentrennungen wieder "
    "zusammen. Ordne jedem Lernziel die zugehoerigen Lerninhalte zu (mittlere Spalte, "
    "meist Anstriche mit '-' oder '·') - als Liste kurzer Stichpunkte. Die rechte Spalte "
    "(Bemerkungen: Querverweise wie 'LB 1: ...', 'GS DE, Kl. 4', Methoden-/Differenzierungs"
    "hinweise, Bildungs- und Erziehungsziele) gehoert NICHT dazu und wird weggelassen. "
    "Behalte die Reihenfolge des Textes bei. Erfinde nichts und lass kein Lernziel aus. "
    "Antworte ausschliesslich im vorgegebenen JSON-Schema."
)
_LERNZIELE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "lernziele": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "anforderung": {"type": "string"},
                    "text": {"type": "string"},
                    "inhalte": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "inhalte"],
            },
        }
    },
    "required": ["lernziele"],
}


def _class_or_404(conn, user_id: int, class_id: int):
    row = conn.execute(
        "SELECT id, subject, grade, track FROM classes WHERE id = ? AND user_id = ? AND archived_at IS NULL",
        (class_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Klasse nicht gefunden.")
    return row


def _resolve_track(conn, subject: str, grade: int, class_track):
    """Welcher Bildungsgang der Referenz wird fuer diese Klasse angezeigt?

    Die Klasse kann 'gemischt'/leer sein, obwohl der Lehrplan fuer Deutsch ab
    Kl. 7 nur RS/HS kennt. Dann faellt die Anzeige auf einen vorhandenen
    Bildungsgang zurueck (RS bevorzugt) statt leer zu bleiben.
    Rueckgabe: (effektiver_track_oder_None, fallback_bool, verfuegbare_tracks).
    """
    avail = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT track FROM lernbereiche WHERE subject = ? AND grade = ?",
            (subject, grade),
        ).fetchall()
    }
    if not avail:
        return None, False, avail
    if class_track and class_track in avail:
        return class_track, False, avail
    eff = "RS" if "RS" in avail else sorted(avail)[0]
    return eff, True, avail


@router.get("/checklist", response_model=LehrplanChecklistOut)
def checklist(
    class_id: int = Query(alias="classId"),
    conn=Depends(get_db),
    user_id: int = Depends(get_user_id),
):
    cls = _class_or_404(conn, user_id, class_id)
    subject, grade = cls["subject"], cls["grade"]
    eff_track, fallback, _ = _resolve_track(conn, subject, grade, cls["track"])

    checked = {
        (r["item_type"], r["item_ref"]): r["checked_at"]
        for r in conn.execute(
            "SELECT item_type, item_ref, checked_at FROM lehrplan_checks WHERE user_id = ? AND class_id = ?",
            (user_id, class_id),
        ).fetchall()
    }

    def _match(table: str):
        params = [subject, grade]
        track_sql = ""
        if eff_track:
            track_sql = " AND track = ?"
            params.append(eff_track)
        return conn.execute(
            f"SELECT * FROM {table} WHERE subject = ? AND grade = ?{track_sql} ORDER BY sort_order",
            params,
        ).fetchall()

    ziele = [
        LehrplanChecklistItem(
            id=r["id"], code=r["code"], text=r["text"],
            checked_at=checked.get(("ziel", r["id"])),
        )
        for r in _match("lehrplan_ziele")
    ]

    lb_rows = _match("lernbereiche")
    lz_by_lb = {}
    if lb_rows:
        placeholders = ",".join("?" for _ in lb_rows)
        for r in conn.execute(
            f"SELECT id, lernbereich_id, text, inhalte FROM lehrplan_lernziele "
            f"WHERE lernbereich_id IN ({placeholders}) ORDER BY lernbereich_id, sort_order",
            [r["id"] for r in lb_rows],
        ).fetchall():
            lz_by_lb.setdefault(r["lernbereich_id"], []).append(
                LehrplanLernzielItem(
                    id=r["id"], text=r["text"], inhalte=r["inhalte"],
                    checked_at=checked.get(("lernziel", r["id"])),
                )
            )

    lernbereiche = [
        LehrplanChecklistItem(
            id=r["id"], code=r["code"], text=r["title"], richtwert_ustd=r["richtwert_ustd"],
            checked_at=checked.get(("lb", r["id"])),
            lernziele=lz_by_lb.get(r["id"], []),
        )
        for r in lb_rows
    ]
    lernziele_missing = sum(1 for r in lb_rows if not lz_by_lb.get(r["id"]))

    return LehrplanChecklistOut(
        class_id=class_id, subject=subject, grade=grade, track=eff_track,
        class_track=cls["track"], track_fallback=fallback,
        lernziele_missing=lernziele_missing,
        ziele=ziele, lernbereiche=lernbereiche,
    )


def _ref_scope(conn, item_type: str, item_ref: int):
    """(subject, grade, track) des referenzierten Eintrags - oder None."""
    if item_type == "ziel":
        return conn.execute(
            "SELECT subject, grade, track FROM lehrplan_ziele WHERE id = ?", (item_ref,)
        ).fetchone()
    if item_type == "lb":
        return conn.execute(
            "SELECT subject, grade, track FROM lernbereiche WHERE id = ?", (item_ref,)
        ).fetchone()
    return conn.execute(
        "SELECT lb.subject, lb.grade, lb.track FROM lehrplan_lernziele z "
        "JOIN lernbereiche lb ON lb.id = z.lernbereich_id WHERE z.id = ?", (item_ref,)
    ).fetchone()


@router.put("/checks", response_model=LehrplanCheckOut)
def set_check(body: LehrplanCheckIn, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    if body.item_type not in _ITEM_TYPES:
        raise HTTPException(status_code=422, detail="itemType muss 'ziel', 'lb' oder 'lernziel' sein.")
    cls = _class_or_404(conn, user_id, body.class_id)

    # Referenz muss existieren UND zum Fach/Klassenstufe/Bildungsgang der Klasse passen -
    # sonst entstuenden Haken auf Eintraegen, die die Checkliste nie anzeigt.
    ref = _ref_scope(conn, body.item_type, body.item_ref)
    eff_track, _, _ = _resolve_track(conn, cls["subject"], cls["grade"], cls["track"])
    if ref is None or (ref["subject"], ref["grade"]) != (cls["subject"], cls["grade"]) or (
        eff_track and ref["track"] != eff_track
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


# ---------- KI-Batch: grosse Lernziele je Lernbereich extrahieren ----------

def _lz_progress(conn, job_id: int, processed: int, total: int, failed: int):
    conn.execute(
        "UPDATE ai_jobs SET result_json = ? WHERE id = ?",
        (json.dumps({"processed": processed, "total": total, "failed": failed}), job_id),
    )
    conn.commit()


def _extract_lernziele_job(db_path: str, job_id: int, user_id: int):
    """Hintergrund-Job: je Lernbereich ohne Feinziele einen KI-Call, Zeilen schreiben.

    Idempotent: Lernbereiche mit vorhandenen lehrplan_lernziele-Zeilen werden
    uebersprungen -> ein erneuter Start nach Abbruch macht dort weiter, wo es
    stehen geblieben ist.
    """
    conn = connect(db_path)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM lernbereiche WHERE detail_md IS NOT NULL AND TRIM(detail_md) <> ''"
        ).fetchone()[0]
        todo = conn.execute(
            "SELECT id, detail_md FROM lernbereiche lb "
            "WHERE detail_md IS NOT NULL AND TRIM(detail_md) <> '' "
            "AND NOT EXISTS (SELECT 1 FROM lehrplan_lernziele z WHERE z.lernbereich_id = lb.id) "
            "ORDER BY subject, grade, track, sort_order"
        ).fetchall()
        processed = total - len(todo)
        failed = 0
        _lz_progress(conn, job_id, processed, total, failed)

        for lb in todo:
            try:
                res = ai.run(conn, user_id, "lehrplan_lernziele", _LERNZIELE_SYSTEM,
                             lb["detail_md"], _LERNZIELE_SCHEMA, max_tokens=3000)
                rows = (json.loads(res["text"]).get("lernziele") or [])
                for so, z in enumerate(rows, start=1):
                    txt = (z.get("text") or "").strip()
                    if not txt:
                        continue
                    inh = "; ".join(s.strip() for s in (z.get("inhalte") or []) if s and s.strip())
                    conn.execute(
                        "INSERT OR IGNORE INTO lehrplan_lernziele "
                        "(lernbereich_id, sort_order, anforderung, text, inhalte) VALUES (?,?,?,?,?)",
                        (lb["id"], so, (z.get("anforderung") or "").strip() or None, txt, inh or None),
                    )
                conn.commit()
            except ai.NoApiKey:
                conn.execute(
                    "UPDATE ai_jobs SET status='error', error=? WHERE id=?",
                    ("Kein API-Key hinterlegt - bitte in den Einstellungen eintragen.", job_id),
                )
                conn.commit()
                return
            except Exception:  # einzelner LB scheitert -> zaehlen, weitermachen
                conn.rollback()
                failed += 1
            processed += 1
            _lz_progress(conn, job_id, processed, total, failed)

        status = "done" if failed == 0 else "error"
        error = None if failed == 0 else (
            f"{failed} Lernbereich(e) konnten nicht ausgewertet werden - „Feinziele erzeugen“ "
            "erneut starten holt sie nach."
        )
        conn.execute(
            "UPDATE ai_jobs SET status=?, error=?, result_json=? WHERE id=?",
            (status, error, json.dumps({"processed": processed, "total": total, "failed": failed}), job_id),
        )
        conn.commit()
    finally:
        conn.close()


@router.post("/lernziele/extract")
def extract_lernziele(
    background_tasks: BackgroundTasks, request: Request,
    conn=Depends(get_db), user_id: int = Depends(get_user_id),
):
    if not ai.get_api_key(conn, user_id):
        raise HTTPException(status_code=400,
                            detail="Kein API-Key hinterlegt - bitte in den Einstellungen eintragen.")
    running = conn.execute(
        "SELECT id FROM ai_jobs WHERE user_id=? AND kind='lehrplan_lernziele' AND status='pending' "
        "ORDER BY id DESC LIMIT 1", (user_id,),
    ).fetchone()
    if running:
        return {"jobId": running["id"]}
    cur = conn.execute(
        "INSERT INTO ai_jobs(user_id, kind, status) VALUES (?, 'lehrplan_lernziele', 'pending')",
        (user_id,),
    )
    conn.commit()
    job_id = cur.lastrowid
    background_tasks.add_task(_extract_lernziele_job, request.app.state.db_path, job_id, user_id)
    return {"jobId": job_id}


@router.get("/lernziele/extract/{job_id}")
def extract_lernziele_status(job_id: int, conn=Depends(get_db), user_id: int = Depends(get_user_id)):
    row = conn.execute(
        "SELECT * FROM ai_jobs WHERE id=? AND user_id=? AND kind='lehrplan_lernziele'",
        (job_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden.")
    return {
        "jobId": row["id"],
        "status": row["status"],
        "progress": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": row["error"],
    }
