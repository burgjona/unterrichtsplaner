"""KI-Endpunkte (BRIEFING Kap. 5). Liefern ausschließlich Vorschläge – editierbar,
nichts wird automatisch gespeichert. Modell-Routing/Kosten in src/lib/ai.py.
"""
import json
import sqlite3
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from ..db import connect
from ..deps import get_db, get_user_id, row_or_404
from ..lib import ai
from ..schemas import AsuvSuggestIn, LessonSuggestIn, StoffplanIn

router = APIRouter(prefix="/ai", tags=["ai"])

_STR = {"type": "string"}


def _run_json(conn, user_id, function, system, user_text, schema, max_tokens=2000):
    try:
        result = ai.run(conn, user_id, function, system, user_text, schema, max_tokens)
    except ai.NoApiKey:
        raise HTTPException(status_code=400, detail="Kein API-Key hinterlegt – bitte in den Einstellungen eintragen.")
    except Exception as exc:  # Netz-/Auth-/API-Fehler sauber weiterreichen
        raise HTTPException(status_code=502, detail=f"KI-Anfrage fehlgeschlagen: {exc}")
    try:
        return json.loads(result["text"]), result["cached"]
    except (ValueError, TypeError):
        raise HTTPException(status_code=502, detail="KI-Antwort war kein gültiges JSON.")


def _ctx_block(ctx: List[dict]) -> str:
    if not ctx:
        return "Keine verknüpften Begleitmaterialien gefunden."
    lines = ["Relevante Auszüge aus Begleitmaterialien (nur diese verwenden, nicht erfinden):"]
    for c in ctx:
        lines.append(f"- [{c['filename']}, S. {c.get('page_from')}] {(c['content'] or '')[:500]}")
    return "\n".join(lines)


# ---------- 1) Stundenvorschlag aus dem Ideenfeld (Klafki/Meyer/Phasen) ----------
_LESSON_SYSTEM = (
    "Du bist didaktische Assistenz für eine Referendarin an einer sächsischen Oberschule "
    "(Fächer Deutsch und WTH). Erzeuge aus losen Ideen einen Erstentwurf einer Unterrichtsstunde: "
    "Titel, Klafki-Analyse (5 Grundfragen), Meyer-Ampel (10 Merkmale: gruen/gelb/rot) und eine "
    "Phasentabelle (Einstieg, Erarbeitung, Sicherung, Abschluss) mit Sozialform (EA/PA/GA/Plenum), "
    "Methode, Material, Lehrer-/Schülertätigkeit und Differenzierung G/M/E. Sei konkret, knapp, "
    "praxistauglich. Umlaute korrekt. Nur Vorschlag – die Lehrkraft prüft und ändert."
)
_LESSON_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "klafki", "meyerPlan", "phases"],
    "properties": {
        "title": _STR,
        "klafki": {
            "type": "object", "additionalProperties": False,
            "required": ["gegenwart", "zukunft", "exemplarisch", "zugang", "struktur"],
            "properties": {k: _STR for k in ["gegenwart", "zukunft", "exemplarisch", "zugang", "struktur"]},
        },
        "meyerPlan": {"type": "array", "items": {"type": "string", "enum": ["gruen", "gelb", "rot"]}},
        "phases": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["phaseName", "minutes", "socialForm", "method", "material",
                             "teacherActivity", "studentActivity", "gme"],
                "properties": {
                    "phaseName": _STR, "minutes": {"type": "integer"}, "socialForm": _STR,
                    "method": _STR, "material": _STR, "teacherActivity": _STR,
                    "studentActivity": _STR, "gme": _STR,
                },
            },
        },
    },
}


@router.post("/lesson-suggestion")
def lesson_suggestion(body: LessonSuggestIn, conn: sqlite3.Connection = Depends(get_db),
                      user_id: int = Depends(get_user_id)):
    ctx = ai.fts_context(conn, user_id, f"{body.ideas} {body.title or ''}", body.subject, body.grade)
    user_text = (f"Fach: {body.subject or '-'} · Klassenstufe: {body.grade or '-'}\n"
                 f"Ideen/Impulse der Lehrkraft:\n{body.ideas}\n\n{_ctx_block(ctx)}")
    data, cached = _run_json(conn, user_id, "lesson_suggestion", _LESSON_SYSTEM, user_text, _LESSON_SCHEMA)
    return {"suggestion": data, "cached": cached}


# ---------- 2) Stoffverteilungsplan-Generierung ----------
_STOFF_SYSTEM = (
    "Du bist didaktische Assistenz und erstellst einen lehrplanbasierten Stoffverteilungsplan "
    "für ein Schuljahr. Ordne die vorgegebenen Lernbereiche sinnvoll über das Jahr, berücksichtige "
    "Stundenrichtwerte und Wochenstunden, und plane vor jeder Lernerfolgskontrolle eine Übungsstunde ein. "
    "Aktualität/Alltagsrelevanz einbeziehen. Nur Vorschlag."
)
_STOFF_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["blocks"],
    "properties": {"blocks": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["code", "title", "ustd", "weeks", "note"],
        "properties": {"code": _STR, "title": _STR, "ustd": {"type": "integer"},
                       "weeks": {"type": "integer"}, "note": _STR}}}},
}


@router.post("/stoffplan")
def stoffplan(body: StoffplanIn, conn: sqlite3.Connection = Depends(get_db),
              user_id: int = Depends(get_user_id)):
    sy = row_or_404(conn.execute("SELECT * FROM school_years WHERE id=? AND user_id=?",
                                 (body.school_year_id, user_id)).fetchone(), "Schuljahr")
    cls = row_or_404(conn.execute("SELECT * FROM classes WHERE id=? AND user_id=?",
                                  (body.class_id, user_id)).fetchone(), "Klasse")
    lbs = conn.execute(
        "SELECT code, title, richtwert_ustd FROM lernbereiche WHERE subject=? AND grade=? AND track=? ORDER BY sort_order",
        (cls["subject"], cls["grade"], cls["track"])).fetchall()
    if not lbs:
        raise HTTPException(status_code=404, detail="Keine Lernbereiche für diese Klasse gefunden.")
    lb_text = "\n".join(f"- {r['code']}: {r['title']} ({r['richtwert_ustd']} Ustd.)" for r in lbs)
    user_text = (f"Fach {cls['subject']}, Klassenstufe {cls['grade']}, Bildungsgang {cls['track']}, "
                 f"{cls['weekly_hours']} Wochenstunden. Schuljahr {sy['label']} "
                 f"({sy['start_date']} bis {sy['end_date']}).\nLernbereiche:\n{lb_text}")
    data, cached = _run_json(conn, user_id, "stoffplan", _STOFF_SYSTEM, user_text, _STOFF_SCHEMA, max_tokens=2500)
    return {"suggestion": data, "cached": cached}


# ---------- 3) ASUV-Ausformulierung ----------
_ASUV_SYSTEM = (
    "Du bist didaktische Assistenz und formulierst Kapitel eines ausführlichen schriftlichen "
    "Unterrichtsentwurfs (ASUV) nach LASUB-Struktur aus. Schreibe fachlich fundiert, in ganzen "
    "Sätzen, Blocksatz-tauglich. Greife in Kapitel 4 Faktoren aus Kapitel 1 wieder auf. Nur Vorschlag."
)
_ASUV_FIELDS = ["bedingungOrg", "bedingungLern", "bedingungEinordnung", "ziele",
                "sachanalyse", "quellen", "didaktisch", "reduktion", "methodisch"]
_ASUV_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": _ASUV_FIELDS,
    "properties": {f: _STR for f in _ASUV_FIELDS},
}


def _run_asuv_job(db_path: str, job_id: int, user_id: int, user_text: str):
    """Background-Task: eigener DB-Connect (keine Request-Dependency), Ergebnis in ai_jobs."""
    conn = connect(db_path)
    try:
        status, result_json, error = "error", None, None
        try:
            result = ai.run(conn, user_id, "asuv", _ASUV_SYSTEM, user_text, _ASUV_SCHEMA, max_tokens=3000)
            data = json.loads(result["text"])
        except ai.NoApiKey:
            error = "Kein API-Key hinterlegt – bitte in den Einstellungen eintragen."
        except (ValueError, TypeError):
            error = "KI-Antwort war kein gültiges JSON."
        except Exception as exc:  # Netz-/Auth-/API-Fehler lesbar ablegen
            error = f"KI-Anfrage fehlgeschlagen: {exc}"
        else:
            status = "done"
            result_json = json.dumps({"suggestion": data, "cached": result["cached"]}, ensure_ascii=False)
        conn.execute("UPDATE ai_jobs SET status=?, result_json=?, error=? WHERE id=?",
                     (status, result_json, error, job_id))
        conn.commit()
    finally:
        conn.close()


@router.post("/asuv/{lesson_id}")
def asuv_suggestion(lesson_id: int, background_tasks: BackgroundTasks, request: Request,
                    body: AsuvSuggestIn = AsuvSuggestIn(),
                    conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    l = row_or_404(conn.execute("SELECT * FROM lessons WHERE id=? AND user_id=?",
                                (lesson_id, user_id)).fetchone(), "Stunde")
    if not ai.get_api_key(conn, user_id):
        raise HTTPException(status_code=400, detail="Kein API-Key hinterlegt – bitte in den Einstellungen eintragen.")
    phases = conn.execute("SELECT * FROM lesson_phases WHERE lesson_id=? ORDER BY sort_order",
                          (lesson_id,)).fetchall()
    klafki = [l["klafki_gegenwart"], l["klafki_zukunft"], l["klafki_exemplarisch"],
              l["klafki_zugang"], l["klafki_struktur"]]
    phase_text = "; ".join(f"{p['phase_name']} ({p['minutes']} Min., {p['social_form']}): {p['method']}"
                           for p in phases) or "keine Phasen erfasst"
    ctx = ai.fts_context(conn, user_id, f"{l['title']} {l['subject']}", l["subject"], l["grade"])
    user_text = (f"Stunde: {l['title']} · Fach {l['subject']} · Klasse {l['grade']} · Typ {l['lesson_type']}\n"
                 f"Klafki: {' | '.join(x for x in klafki if x) or '-'}\n"
                 f"Phasen: {phase_text}\n"
                 f"Lehrwerk: {l['bibox_werk'] or '-'} {l['bibox_seite'] or ''}\n\n{_ctx_block(ctx)}")
    # Lang laufender KI-Call asynchron (Cloudflare-Tunnel bricht Requests nach 100 s ab):
    # Job anlegen, sofort jobId liefern, Frontend pollt GET /ai/jobs/{id}.
    cur = conn.execute("INSERT INTO ai_jobs(user_id, kind, status) VALUES (?, 'asuv', 'pending')", (user_id,))
    conn.commit()
    job_id = cur.lastrowid
    background_tasks.add_task(_run_asuv_job, request.app.state.db_path, job_id, user_id, user_text)
    return {"jobId": job_id}


@router.get("/jobs/{job_id}")
def ai_job_status(job_id: int, conn: sqlite3.Connection = Depends(get_db),
                  user_id: int = Depends(get_user_id)):
    row = row_or_404(conn.execute("SELECT * FROM ai_jobs WHERE id=? AND user_id=?",
                                  (job_id, user_id)).fetchone(), "KI-Job")
    out = {"jobId": row["id"], "kind": row["kind"], "status": row["status"]}
    if row["status"] == "done":
        out["result"] = json.loads(row["result_json"]) if row["result_json"] else None
    elif row["status"] == "error":
        out["error"] = row["error"]
    return out


# ---------- Kostenübersicht ----------
@router.get("/usage")
def usage(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        """SELECT substr(created_at,1,7) AS month, model,
                  SUM(input_tokens) inp, SUM(output_tokens) outp, SUM(cost_usd) cost
           FROM ai_usage WHERE user_id=? GROUP BY month, model ORDER BY month DESC, model""",
        (user_id,)).fetchall()
    total = conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM ai_usage WHERE user_id=?", (user_id,)).fetchone()[0]
    return {
        "totalUsd": round(total, 4),
        "rows": [{"month": r["month"], "model": r["model"], "inputTokens": r["inp"],
                  "outputTokens": r["outp"], "costUsd": round(r["cost"], 4)} for r in rows],
    }
