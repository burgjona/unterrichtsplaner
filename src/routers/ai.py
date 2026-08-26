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
from ..schemas import AsuvSuggestIn, LessonSuggestIn, SequenzplanIn, StoffplanIn, TafelbildSuggestIn

router = APIRouter(prefix="/ai", tags=["ai"])

_STR = {"type": "string"}
# Deckel für ungeprüfte Freitext-/OCR-Bausteine im Prompt (Ideenfeld, Hinweise, Lehrplantext):
# unbegrenzt eingefügt kann so ein Baustein den Kontext sprengen und die KI aus dem Tritt
# bringen (leere/ungültige Antwort statt eines Vorschlags) – siehe Sequenzplan-Vorfall.
_FREE_TEXT_CAP = 4000


def _run_json(conn, user_id, function, system, user_text, schema, max_tokens=2000, bypass_cache=False):
    try:
        result = ai.run(conn, user_id, function, system, user_text, schema, max_tokens, bypass_cache)
    except ai.NoApiKey:
        raise HTTPException(status_code=400, detail="Kein API-Key hinterlegt – bitte in den Einstellungen eintragen.")
    except ai.ResponseTruncated:
        raise HTTPException(status_code=502, detail="KI-Antwort war zu lang und wurde abgeschnitten – "
                             "bitte erneut versuchen oder Hinweise/Vorgaben kürzen.")
    except Exception as exc:  # Netz-/Auth-/API-Fehler sauber weiterreichen
        raise HTTPException(status_code=502, detail=f"KI-Anfrage fehlgeschlagen: {exc}")
    try:
        return json.loads(result["text"]), result["cached"]
    except (ValueError, TypeError):
        raise HTTPException(status_code=502, detail="KI-Antwort war kein gültiges JSON.")


# ---------- Job-Infrastruktur für lang laufende KI-Calls ----------
# Der Cloudflare-Tunnel bricht Requests nach ~100 s ab. Ein synchroner Sonnet-Call, der einen
# kompletten Plan erzeugt, läuft deutlich länger – der Nutzer sah dann nur einen Abbruch
# (HTML-Fehlerseite statt JSON). Deshalb laufen alle langen Calls als Background-Job:
# POST legt den Job an und liefert sofort {"jobId": …}, das Frontend pollt GET /ai/jobs/{id}.


_JOB_MAX_ATTEMPTS = 2  # ein automatischer Retry bei inhaltlich schlechter (nicht: fehlender-Key-) Antwort


def _run_ai_job(db_path: str, job_id: int, user_id: int, function: str, system: str,
                user_text: str, schema: dict, max_tokens: int, bypass_cache: bool,
                post_process=None):
    """Background-Task: eigener DB-Connect (keine Request-Dependency), Ergebnis in ai_jobs.

    Inhaltlich schlechte Antworten (kein gültiges JSON, oder ein über post_process als leer
    erkanntes Ergebnis) sind meist Modell-Varianz, kein deterministischer Fehler – ein zweiter
    Versuch löst die meisten davon unsichtbar für die Lehrkraft. Deshalb hier ein Retry, jeweils
    mit umgangenem Cache (sonst würde ein zweiter Versuch nur die exakt gleiche schlechte
    Antwort aus dem lokalen Prompt-Cache zurückbekommen). Ein fehlender API-Key wird NICHT
    wiederholt – der ändert sich zwischen zwei Versuchen im selben Job nicht.
    """
    conn = connect(db_path)
    try:
        status, result_json, error = "error", None, None
        for attempt in range(_JOB_MAX_ATTEMPTS):
            retry_bypass = bypass_cache or attempt > 0
            try:
                result = ai.run(conn, user_id, function, system, user_text, schema, max_tokens, retry_bypass)
            except ai.NoApiKey:
                error = "Kein API-Key hinterlegt – bitte in den Einstellungen eintragen."
                break
            except ai.ResponseTruncated:
                error = ("KI-Antwort war zu lang und wurde abgeschnitten – bitte erneut versuchen "
                         "oder Hinweise/Vorgaben kürzen.")
                continue
            except Exception as exc:  # Netz-/Auth-/API-Fehler lesbar ablegen
                error = f"KI-Anfrage fehlgeschlagen: {exc}"
                continue
            try:
                data = json.loads(result["text"])
            except (ValueError, TypeError):
                error = "KI-Antwort war kein gültiges JSON."
                continue
            try:
                if post_process is not None:
                    data = post_process(data)
            except Exception as exc:  # Nachbearbeitung getrennt melden, nicht als JSON-Fehler
                error = f"Nachbearbeitung der KI-Antwort fehlgeschlagen: {exc}"
                continue
            status, error = "done", None
            result_json = json.dumps({"suggestion": data, "cached": result["cached"]}, ensure_ascii=False)
            break
        conn.execute("UPDATE ai_jobs SET status=?, result_json=?, error=? WHERE id=?",
                     (status, result_json, error, job_id))
        conn.commit()
    finally:
        conn.close()


def _start_ai_job(conn, user_id: int, background_tasks: BackgroundTasks, request: Request,
                  kind: str, function: str, system: str, user_text: str, schema: dict,
                  max_tokens: int, bypass_cache: bool = False, post_process=None) -> dict:
    """Legt den Job an und startet den KI-Call im Hintergrund. Liefert {"jobId": …}.

    Der fehlende API-Key wird noch synchron gemeldet (400), damit der Nutzer nicht erst
    über den Umweg eines fehlgeschlagenen Jobs davon erfährt.
    """
    if not ai.get_api_key(conn, user_id):
        raise HTTPException(status_code=400,
                            detail="Kein API-Key hinterlegt – bitte in den Einstellungen eintragen.")
    cur = conn.execute("INSERT INTO ai_jobs(user_id, kind, status) VALUES (?,?,'pending')",
                       (user_id, kind))
    conn.commit()
    job_id = cur.lastrowid
    background_tasks.add_task(_run_ai_job, request.app.state.db_path, job_id, user_id, function,
                              system, user_text, schema, max_tokens, bypass_cache, post_process)
    return {"jobId": job_id}


def _require_nonempty(list_key: str):
    """post_process-Fabrik: Das erzwungene JSON-Schema garantiert nur gültiges, nicht
    sinnvolles JSON – die KI kann z. B. bei sehr großem/verwirrendem Kontext ein leeres,
    aber schema-konformes Ergebnis liefern ({"stunden": []}). Das bisher stillschweigend
    als Erfolg durchzureichen führte zu einem irreführenden "0 Stunden erzeugt"-Toast, ohne
    dass für die Lehrkraft ersichtlich war, dass etwas schiefgegangen ist. Ein leeres
    Ergebnis ist nie ein sinnvoller Vorschlag – als Job-Fehler melden, damit ein erneuter
    Versuch naheliegt statt eines scheinbar leeren, aber "fertigen" Plans."""
    def _check(data):
        if not data.get(list_key):
            raise ValueError("KI-Antwort enthielt keinen Vorschlag (leere Liste) – bitte erneut versuchen.")
        return data
    return _check


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
    "Phasentabelle mit Sozialform (EA/PA/GA/Plenum), Methode, Material, Lehrer-/Schülertätigkeit "
    "und Differenzierung G/M/E. Erlaubte Phasenbezeichnungen: Einstieg, Erarbeitung, Sicherung, "
    "Ausstieg, Puffer. Nach einer Sicherung darf eine weitere Erarbeitung folgen; nummeriere in "
    "diesem Fall römisch (Erarbeitung I, Sicherung I, Erarbeitung II, Sicherung II …) und lasse "
    "die Nummer weg, wenn eine Bezeichnung nur einmal vorkommt. Die Summe aller Phasenminuten "
    "muss die Stundendauer exakt ergeben. Sei konkret, knapp, "
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
    if not body.ideas.strip() and not (body.title or "").strip():
        raise HTTPException(status_code=400,
                            detail="Bitte Ideen oder einen Titel angeben – ohne beides kann kein Vorschlag erzeugt werden.")
    cls = None
    if body.class_id is not None:
        cls = row_or_404(conn.execute("SELECT * FROM classes WHERE id=? AND user_id=?",
                                      (body.class_id, user_id)).fetchone(), "Klasse")
    ctx = ai.fts_context(conn, user_id, f"{body.ideas} {body.title or ''}", body.subject, body.grade)
    dur = body.duration_minutes if body.duration_minutes in (45, 90) else 45
    lines = [f"Fach: {body.subject or '-'} · Klassenstufe: {body.grade or '-'}",
             f"Stundendauer: {dur} Minuten – die Phasenminuten müssen exakt {dur} ergeben."]
    if body.title:
        lines.append(f"Titel/Thema: {body.title}")
    if body.lesson_type:
        lines.append(f"Stundentyp: {body.lesson_type}")
    if cls is not None:
        lines.append(f"Klasse: {cls['name']} · Bildungsgang: {cls['track'] or '-'}")
    if body.date:
        lines.append(f"Datum der Stunde: {body.date}")
    lines.append(f"Ideen/Impulse der Lehrkraft:\n{body.ideas.strip()[:_FREE_TEXT_CAP] or '-'}")
    user_text = "\n".join(lines) + f"\n\n{_ctx_block(ctx)}"
    data, cached = _run_json(conn, user_id, "lesson_suggestion", _LESSON_SYSTEM, user_text, _LESSON_SCHEMA, max_tokens=4000)
    return {"suggestion": data, "cached": cached}


# ---------- 1b) Tafelbild-Vorschlag aus Freitext ----------
_TAFELBILD_SYSTEM = (
    "Du bist didaktische Assistenz für eine Referendarin an einer sächsischen Oberschule "
    "(Fächer Deutsch und WTH). Die Lehrkraft gibt Stichworte oder Text ein, der während der "
    "Stunde an die Tafel geschrieben werden soll. Erstelle daraus ein durchdachtes, "
    "tafeltaugliches Tafelbild: kurze Stichpunkte statt ganzer Sätze, klare Gliederung. "
    "Du entscheidest frei, in wie viele Blöcke der Inhalt sinnvoll gegliedert wird und wie sie "
    "betitelt sind – es gibt keine feste Block- oder Spaltenzahl. Zentrale Regeln/Merksätze "
    "als hervorgehoben markieren. Erfinde keine fachlichen Inhalte, die nicht aus der Eingabe "
    "hervorgehen oder unmittelbar daraus ableitbar sind. Umlaute korrekt. Nur Vorschlag – die "
    "Lehrkraft prüft und ändert."
)
_TAFELBILD_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["titel", "bloecke"],
    "properties": {
        "titel": _STR,
        "bloecke": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["ueberschrift", "punkte", "hervorgehoben"],
                "properties": {
                    "ueberschrift": _STR,
                    "punkte": {"type": "array", "items": _STR},
                    "hervorgehoben": {"type": "boolean"},
                },
            },
        },
    },
}


@router.post("/tafelbild")
def tafelbild_suggestion(body: TafelbildSuggestIn, conn: sqlite3.Connection = Depends(get_db),
                         user_id: int = Depends(get_user_id)):
    if not body.eingabe.strip():
        raise HTTPException(status_code=400,
                            detail="Bitte einen Text eingeben, was an die Tafel soll.")
    lines = []
    if body.subject:
        lines.append(f"Fach: {body.subject}")
    if body.grade:
        lines.append(f"Klassenstufe: {body.grade}")
    if body.title:
        lines.append(f"Thema/Titel der Stunde: {body.title}")
    lines.append(f"Vorgabe der Lehrkraft (was an die Tafel soll):\n{body.eingabe.strip()[:_FREE_TEXT_CAP]}")
    user_text = "\n".join(lines)
    data, cached = _run_json(conn, user_id, "tafelbild", _TAFELBILD_SYSTEM, user_text,
                             _TAFELBILD_SCHEMA, max_tokens=2000)
    return {"suggestion": data, "cached": cached}


# ---------- 2) Stoffverteilungsplan-Generierung ----------
_STOFF_SYSTEM = (
    "Du bist didaktische Assistenz und erstellst einen lehrplanbasierten Stoffverteilungsplan "
    "für ein Schuljahr. Ordne die vorgegebenen Lernbereiche sinnvoll über das Jahr, berücksichtige "
    "Stundenrichtwerte und Wochenstunden, und plane vor jeder Lernerfolgskontrolle eine Übungsstunde ein. "
    "Verplane das gesamte Schuljahr, also alle angegebenen verfügbaren Unterrichtswochen (Ferien sind "
    "bereits abgezogen), sofern die Lehrer-Hinweise nichts anderes vorgeben. Reichen die "
    "Richtwertstunden der Lernbereiche nicht aus, um alle Wochen zu füllen, verteile die übrige Zeit "
    "als Puffer (Wiederholung, Vertiefung, Übung) auf die bestehenden Lernbereiche oder schlage darin "
    "konkrete Exkursionen/außerschulische Lernorte vor – erhöhe dafür deren weeks entsprechend und "
    "vermerke den Grund im note-Feld des jeweiligen Blocks. Keine zusätzlichen Blöcke ohne "
    "Lernbereich-Code erzeugen. Aktualität/Alltagsrelevanz einbeziehen. Nur Vorschlag."
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
def stoffplan(body: StoffplanIn, background_tasks: BackgroundTasks, request: Request,
              conn: sqlite3.Connection = Depends(get_db),
              user_id: int = Depends(get_user_id)):
    sy = row_or_404(conn.execute("SELECT * FROM school_years WHERE id=? AND user_id=?",
                                 (body.school_year_id, user_id)).fetchone(), "Schuljahr")
    cls = row_or_404(conn.execute("SELECT * FROM classes WHERE id=? AND user_id=?",
                                  (body.class_id, user_id)).fetchone(), "Klasse")
    from ..lib.planning import effective_blocks, resolve_track, teaching_weeks, _d
    track = resolve_track(cls["subject"], cls["grade"], cls["track"])
    lbs = conn.execute(
        "SELECT code, title, richtwert_ustd FROM lernbereiche WHERE subject=? AND grade=? AND track=? ORDER BY sort_order",
        (cls["subject"], cls["grade"], track)).fetchall()
    if not lbs:
        raise HTTPException(status_code=404, detail="Keine Lernbereiche für diese Klasse gefunden.")
    blocks = effective_blocks(cls["subject"], [dict(r) for r in lbs])
    lb_text = "\n".join(f"- {b['code']}: {b['title']} ({b['richtwert_ustd']} Ustd.)" for b in blocks)
    richtwert_sum = sum(b["richtwert_ustd"] or 0 for b in blocks)

    note_row = conn.execute(
        "SELECT text FROM plan_notes WHERE user_id=? AND class_id=? AND school_year_id=?",
        (user_id, body.class_id, body.school_year_id)).fetchone()
    note = (note_row["text"] if note_row else "").strip()

    # Ferien kommen bereits automatisch aus der Sachsen-Ferien-API (school_dates, s.
    # src/lib/holidays.py) – der KI hier mitgeben, damit sie die verfügbaren
    # Unterrichtswochen kennt und das Schuljahr tatsächlich vollständig verplanen kann.
    ferien_rows = conn.execute(
        "SELECT start_date, end_date FROM school_dates WHERE school_year_id = ? AND user_id = ?",
        (body.school_year_id, user_id)).fetchall()
    ferien = [(r["start_date"], r["end_date"]) for r in ferien_rows]
    weeks_total = len(teaching_weeks(_d(sy["start_date"]), _d(sy["end_date"]),
                                     [(_d(s), _d(e)) for s, e in ferien]))
    available_ustd = weeks_total * (cls["weekly_hours"] or 1)

    parts = [(f"Fach {cls['subject']}, Klassenstufe {cls['grade']}, Bildungsgang {cls['track']}, "
              f"{cls['weekly_hours']} Wochenstunden. Schuljahr {sy['label']} "
              f"({sy['start_date']} bis {sy['end_date']}).")]
    if ferien:
        parts.append("Ferien/unterrichtsfreie Zeiträume (bereits abgezogen):\n"
                     + "\n".join(f"- {s} bis {e}" for s, e in ferien))
    parts.append(f"Verfügbare Unterrichtswochen im Schuljahr: {weeks_total} "
                f"(ca. {available_ustd} Unterrichtsstunden). Summe der Richtwertstunden aller "
                f"Lernbereiche: {richtwert_sum} Ustd.")
    if note:
        parts.append("Hinweise/Ideen des Lehrers – diese haben Vorrang vor den Standardregeln:\n"
                     + note[:_FREE_TEXT_CAP])
    if cls["subject"] == "Deutsch" and cls["track"] == "gemischt" and (cls["grade"] or 0) >= 7:
        parts.append("Die Klasse ist ein gemischter Bildungsgang: Richte die Planung nach dem "
                     "Realschulbildungsgang aus und plane durchgängig Differenzierung auf "
                     "Hauptschulniveau ein – außer die Lehrer-Hinweise (Freitext) sagen etwas anderes.")
    if cls["subject"] == "Deutsch":
        parts.append("Lernbereiche 1 und 2 (Deutsch) nicht als eigene Blöcke ausweisen – ihre Lernziele "
                     "(Sprechen/Zuhören, Sprache untersuchen/Rechtschreibung) durchgängig in die "
                     "thematischen Lernbereiche 3–6 integrieren und in den Blocknotizen erwähnen.")
    parts.append("Lernbereiche:\n" + lb_text)
    user_text = "\n\n".join(parts)
    # Zeiträume erst nach der KI-Antwort aus den vorgeschlagenen Wochen + Ferienkalender setzen.
    from ..lib.planning import assign_dates_from_weeks
    ferien_d = [(_d(a), _d(b)) for a, b in ferien]
    sy_start, sy_end = _d(sy["start_date"]), _d(sy["end_date"])

    def _dates(data):
        data = _require_nonempty("blocks")(data)
        blocks = data["blocks"]
        for b, d_ in zip(blocks, assign_dates_from_weeks(sy_start, sy_end, ferien_d, blocks)):
            b["startDate"] = d_["start_date"]
            b["endDate"] = d_["end_date"]
        return data

    # Kein Cache: Der Stoffplan-Vorschlag ist ein bewusster Einzelaufruf, ein gecachter alter
    # (evtl. unvollständiger) Vorschlag soll nie stillschweigend erneut ausgeliefert werden.
    return _start_ai_job(conn, user_id, background_tasks, request, "stoffplan", "stoffplan",
                         _STOFF_SYSTEM, user_text, _STOFF_SCHEMA, max_tokens=8000,
                         bypass_cache=True, post_process=_dates)


# ---------- 2b) Sequenzplan-Generierung (Einzelstunden je Stoffplan-Block) ----------
_SEQUENZ_SYSTEM = (
    "Du bist didaktische Assistenz für eine Referendarin an einer sächsischen Oberschule "
    "(Fächer Deutsch und WTH). Zerlege einen Lernbereichs-Block eines Stoffverteilungsplans in "
    "einzelne Unterrichtsstunden: Titel und ein knappes, konkretes Grobziel je Stunde. Die Anzahl "
    "der Stunden soll dem Stundenrichtwert des Blocks entsprechen. Plane didaktisch sinnvoll "
    "aufeinander aufbauend (Einführung, Erarbeitung, Übung, Sicherung/Lernkontrolle). Wenn die "
    "Lehrkraft bestimmte Bewertungsformen wünscht (siehe Hinweise), ordne genau diese je einer "
    "passenden Stunde zu (z. B. eine Übungsstunde vor einer Lernkontrolle). Nur Vorschlag – die "
    "Lehrkraft prüft und ändert."
)
_SEQUENZ_NOTENART = {"lk", "referat", "komplexeArbeit", "klassenarbeit"}
_SEQUENZ_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["stunden"],
    "properties": {"stunden": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["title", "grobziel", "notenarten"],
        "properties": {
            "title": _STR, "grobziel": _STR,
            "notenarten": {"type": "array", "items": {
                "type": "string", "enum": ["lk", "referat", "komplexeArbeit", "klassenarbeit"]}},
        },
    }}},
}


@router.post("/sequenzplan")
def sequenzplan(body: SequenzplanIn, background_tasks: BackgroundTasks, request: Request,
                conn: sqlite3.Connection = Depends(get_db),
                user_id: int = Depends(get_user_id)):
    block = conn.execute(
        "SELECT b.*, p.class_id FROM stoff_plan_blocks b JOIN stoff_plans p ON p.id = b.plan_id "
        "WHERE b.id = ? AND p.user_id = ?",
        (body.block_id, user_id),
    ).fetchone()
    if block is None:
        raise HTTPException(status_code=404, detail="Block nicht gefunden.")
    cls = row_or_404(conn.execute("SELECT * FROM classes WHERE id = ? AND user_id = ?",
                                  (block["class_id"], user_id)).fetchone(), "Klasse")

    lb_detail = ""
    if block["lb_code"]:
        from ..lib.planning import resolve_track
        track = resolve_track(cls["subject"], cls["grade"], cls["track"])
        lb = conn.execute(
            "SELECT detail_md FROM lernbereiche WHERE subject=? AND grade=? AND track=? AND code=?",
            (cls["subject"], cls["grade"], track, block["lb_code"]),
        ).fetchone()
        # Ungekürzt konnte ein langer/OCR-holpriger Lehrplantext den Kontext sprengen und die
        # KI aus dem Tritt bringen (leere/ungültige Antwort) – wie bei den anderen Stellen, die
        # denselben Text nutzen (Lernziele/Einordnung), deshalb hier ebenfalls gekappt.
        lb_detail = (lb["detail_md"] or "")[:3000] if lb else ""

    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM sequenz_stunden WHERE block_id = ?", (body.block_id,)
    ).fetchone()["n"]

    ctx = ai.fts_context(conn, user_id, f"{block['title']} {body.ideas}", cls["subject"], cls["grade"])
    lines = [f"Lernbereich {block['lb_code'] or '-'}: {block['title'] or '-'} "
            f"({block['ustd'] or '?'} Stundenrichtwert), Klasse {cls['name']} "
            f"({cls['subject']}, Klassenstufe {cls['grade']}, Bildungsgang {cls['track'] or '-'})."]
    if lb_detail:
        lines.append(f"Lehrplantext des Lernbereichs:\n{lb_detail}")
    if cls["subject"] == "Deutsch":
        lines.append("Da Lernbereich 1 und 2 (Sprechen/Zuhören bzw. Sprache untersuchen/"
                     "Rechtschreibung) nicht als eigene Blöcke geführt werden, nenne im Grobziel "
                     "jeder Stunde zusätzlich zum thematischen Lernbereich explizit den "
                     "Lehrplanbezug zu LB 1 und LB 2.")
    if existing:
        lines.append(f"Es existieren bereits {existing} Sequenzstunden für diesen Block – "
                     "erzeuge einen kompletten, in sich stimmigen Vorschlag (ersetzt die bisherigen).")
    wanted = [n for n, flag in (("Lernkontrolle (LK)", body.want_lk), ("Referat", body.want_referat),
                                ("komplexe Arbeit", body.want_komplexe_arbeit),
                                ("Klassenarbeit", body.want_klassenarbeit)) if flag]
    if wanted:
        lines.append("Gewünschte Bewertungsformen, die im Verlauf vorkommen sollen: " + ", ".join(wanted) + ".")
    if body.ideas.strip():
        lines.append(f"Ideen/Hinweise der Lehrkraft:\n{body.ideas.strip()[:_FREE_TEXT_CAP]}")
    user_text = "\n\n".join(lines) + f"\n\n{_ctx_block(ctx)}"

    # Längster KI-Call der App (ein kompletter Block mit bis zu ~40 Stunden). Als Job im
    # Hintergrund darf er beliebig lange laufen, deshalb ist max_tokens großzügig gesetzt –
    # das frühere Pendeln zwischen abgeschnittener Antwort und Gateway-Timeout entfällt.
    # Kein Cache: „nochmal generieren" muss einen wirklich neuen Vorschlag liefern.
    return _start_ai_job(conn, user_id, background_tasks, request, "sequenzplan", "sequenzplan",
                         _SEQUENZ_SYSTEM, user_text, _SEQUENZ_SCHEMA, max_tokens=32000,
                         bypass_cache=True, post_process=_require_nonempty("stunden"))


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


@router.post("/asuv/{lesson_id}")
def asuv_suggestion(lesson_id: int, background_tasks: BackgroundTasks, request: Request,
                    body: AsuvSuggestIn = AsuvSuggestIn(),
                    conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    l = row_or_404(conn.execute("SELECT * FROM lessons WHERE id=? AND user_id=?",
                                (lesson_id, user_id)).fetchone(), "Stunde")
    phases = conn.execute("SELECT * FROM lesson_phases WHERE lesson_id=? ORDER BY sort_order",
                          (lesson_id,)).fetchall()
    klafki = [l["klafki_gegenwart"], l["klafki_zukunft"], l["klafki_exemplarisch"],
              l["klafki_zugang"], l["klafki_struktur"]]
    phase_text = "; ".join(f"{p['phase_name']} ({p['minutes']} Min., {p['social_form']}): {p['method']}"
                           for p in phases) or "keine Phasen erfasst"
    # Erfasste Lernziele + Phasen-Verortung: Kap. 2 und Verlaufsplan konsistent formulieren.
    phase_by_so = {p["sort_order"]: p["phase_name"] for p in phases}
    lz_rows = conn.execute(
        "SELECT kind, text, bloom_stufe, phase_sort_order FROM lesson_lernziele "
        "WHERE lesson_id=? ORDER BY sort_order, id", (lesson_id,)).fetchall()
    lz_lines = []
    for z in lz_rows:
        bloom = f", Bloom: {z['bloom_stufe']}" if z["bloom_stufe"] else ""
        pso = z["phase_sort_order"]
        phase = phase_by_so.get(pso) if pso is not None else None
        verortung = f", erreicht in Phase: {phase}" if phase else ""
        lz_lines.append(f"- [{z['kind']}{bloom}{verortung}] {z['text']}")
    lz_text = ("Erfasste Lernziele (Kapitel 2 und Verlaufsplan konsistent damit formulieren, "
               "die Phasen-Verortung je Feinziel im Verlaufsplan nachweisen):\n" + "\n".join(lz_lines)
               ) if lz_lines else "Keine Lernziele erfasst – aus Klafki/Phasen ableiten."
    ctx = ai.fts_context(conn, user_id, f"{l['title']} {l['subject']}", l["subject"], l["grade"])
    user_text = (f"Stunde: {l['title']} · Fach {l['subject']} · Klasse {l['grade']} · Typ {l['lesson_type']}\n"
                 f"Klafki: {' | '.join(x for x in klafki if x) or '-'}\n"
                 f"Phasen: {phase_text}\n"
                 f"{lz_text}\n"
                 f"Lehrwerk: {l['bibox_werk'] or '-'} {l['bibox_seite'] or ''}\n\n{_ctx_block(ctx)}")
    return _start_ai_job(conn, user_id, background_tasks, request, "asuv", "asuv",
                         _ASUV_SYSTEM, user_text, _ASUV_SCHEMA, max_tokens=4000)


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


# ---------- 4) Lernziele (SMART, Bloom-Taxonomie) — Meilenstein 11 ----------
_BLOOM_STUFEN = ["Erinnern", "Verstehen", "Anwenden", "Analysieren", "Bewerten", "Erschaffen"]
_LERNZIELE_SYSTEM = (
    "Du bist didaktische Assistenz für eine Referendarin an einer sächsischen Oberschule "
    "(Fächer Deutsch und WTH). Formuliere kompetenzorientierte, prüfbar und beobachtbar "
    "formulierte Lernziele nach der Bloom-Taxonomie "
    f"(Stufen: {', '.join(_BLOOM_STUFEN)}) und – wo möglich – SMART. Unterscheide Grobziele "
    "(übergeordnet, 'grob') und Feinziele (konkret, operationalisiert, überprüfbar, 'fein'). "
    "Ordne jedes Feinziel möglichst einer Phase der Stunde zu – phaseSortOrder ist die in "
    "eckigen Klammern angegebene Nummer der Phase aus der übergebenen Phasentabelle, sonst "
    "null –, damit nachweisbar ist, an welcher Stelle der Stunde welches Ziel erreicht wird. "
    "Schreibe jedes Ziel im Feld 'text' aus Schülersicht, beginnend mit 'Die Schülerinnen und "
    "Schüler', und wähle ein aktives, beobachtbares Bloom-Verb passend zur bloomStufe (z. B. "
    "benennen, erläutern, anwenden, unterscheiden, beurteilen, entwerfen). Baue in jedes "
    "Feinziel einen konkreten, messbaren Indikator ein – Muster: 'Die Schülerinnen und Schüler "
    "[Bloom-Verb] [Inhalt], indem sie [beobachtbare Handlung/Ergebnis]'; Grobziele bleiben "
    "übergeordnet und brauchen den 'indem'-Zusatz nicht. "
    "Verboten sind vage Verben (z. B. 'verstehen', 'wissen', 'sich bewusst sein') und reine "
    "Aufgabenbeschreibungen; formuliere stattdessen ein beobachtbares Ergebnis. Vermeide das "
    "Wort 'können', wenn die Handlung selbst schon die Kompetenz zeigt. Ist ein Ziel nicht "
    "überprüfbar, formuliere es um, bis das Erreichen an einer konkreten Handlung erkennbar ist. "
    "Umlaute korrekt. Nur Vorschlag – die Lehrkraft prüft und ändert."
)
_LERNZIELE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["ziele"],
    "properties": {"ziele": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "text", "bloomStufe", "phaseSortOrder"],
        "properties": {
            "kind": {"type": "string", "enum": ["grob", "fein"]},
            "text": _STR,
            "bloomStufe": {"type": "string", "enum": _BLOOM_STUFEN},
            "phaseSortOrder": {"type": ["integer", "null"]},
        },
    }}},
}


@router.post("/lernziele/{lesson_id}")
def lernziele_suggestion(lesson_id: int, conn: sqlite3.Connection = Depends(get_db),
                         user_id: int = Depends(get_user_id)):
    l = row_or_404(conn.execute("SELECT * FROM lessons WHERE id=? AND user_id=?",
                                (lesson_id, user_id)).fetchone(), "Stunde")
    dur = l["duration_minutes"] or 45
    grob, fein = (2, 4) if dur == 90 else (1, 2)
    regel = (f"Diese Stunde dauert {dur} Minuten. Regel: pro 45-Minuten-Einheit 1 Grobziel und "
             f"mindestens 2 Feinziele – hier also {grob} Grobziel(e) und mindestens {fein} Feinziele.")
    phases = conn.execute("SELECT * FROM lesson_phases WHERE lesson_id=? ORDER BY sort_order",
                          (lesson_id,)).fetchall()
    phase_text = "; ".join(
        f"[{p['sort_order']}] {p['phase_name']} ({p['minutes']} Min., {p['social_form']}): {p['method']}"
        for p in phases) or "keine Phasen erfasst"
    lb_text = "frei geplante Stunde – passenden Lernbereich aus dem Lehrplan ableiten."
    if l["lernbereich_id"] is not None:
        lb = conn.execute("SELECT title, detail_md FROM lernbereiche WHERE id=?",
                          (l["lernbereich_id"],)).fetchone()
        if lb is not None:
            lb_text = f"Zugeordneter Lernbereich: {lb['title']}"
            if lb["detail_md"]:
                lb_text += ("\nLehrplan-Detailkontext (nur als fachliche Grundlage nutzen, "
                            f"OCR-holprig):\n{lb['detail_md'][:2500]}")
    user_text = (
        f"Stunde: {l['title']} · Fach {l['subject']} · Klassenstufe {l['grade'] or '-'} · "
        f"Stundentyp {l['lesson_type'] or '-'} · Dauer {dur} Minuten\n"
        f"Phasen: {phase_text}\n"
        f"{lb_text}\n\n{regel}\n\n{_ctx_block(ai.lesson_material_context(conn, user_id, lesson_id))}"
    )
    data, cached = _run_json(conn, user_id, "lernziele", _LERNZIELE_SYSTEM, user_text, _LERNZIELE_SCHEMA, max_tokens=4000)
    return {"suggestion": data, "cached": cached}


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


# ---------- 5) Einordnung freier Stunden (Lernbereich/Lernziel-Vorschlag) — Meilenstein 12 (U7) ----------
_EINORDNUNG_SYSTEM = (
    "Du bist didaktische Assistenz für eine Referendarin an einer sächsischen Oberschule "
    "(Fächer Deutsch und WTH). Eine frei geplante Stunde ohne Lernbereichszuordnung soll in den "
    "sächsischen Lehrplan eingeordnet werden. Wähle aus den vorgegebenen Kandidaten-Lernbereichen "
    "den am besten passenden aus (nur aus der Liste, nichts erfinden) und gib einen kurzen Hinweis, "
    "unter welchem Lernziel des Lehrplans die Stunde dort verortet werden kann. Umlaute korrekt. "
    "Nur Vorschlag – die Lehrkraft prüft und entscheidet."
)
_EINORDNUNG_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["lernbereichCode", "lernbereichTitle", "lernzielHinweis", "begruendung"],
    "properties": {k: _STR for k in
                   ["lernbereichCode", "lernbereichTitle", "lernzielHinweis", "begruendung"]},
}


@router.post("/einordnung/{lesson_id}")
def einordnung_suggestion(lesson_id: int, conn: sqlite3.Connection = Depends(get_db),
                          user_id: int = Depends(get_user_id)):
    l = row_or_404(conn.execute("SELECT * FROM lessons WHERE id=? AND user_id=?",
                                (lesson_id, user_id)).fetchone(), "Stunde")
    # Kandidaten-Lernbereiche über subject/grade (+ Bildungsgang der Klasse, falls verknüpft).
    from ..lib.planning import resolve_track
    track = None
    if l["class_id"] is not None:
        cls = conn.execute("SELECT * FROM classes WHERE id=? AND user_id=?",
                           (l["class_id"], user_id)).fetchone()
        if cls is not None:
            track = resolve_track(cls["subject"], cls["grade"], cls["track"])
    params = [l["subject"], l["grade"]]
    sql = "SELECT code, title, detail_md FROM lernbereiche WHERE subject=? AND grade=?"
    if track:
        sql += " AND track=?"
        params.append(track)
    sql += " ORDER BY track, sort_order"
    lbs = conn.execute(sql, params).fetchall()
    if not lbs:
        raise HTTPException(status_code=404, detail="Keine passenden Lernbereiche gefunden.")
    lb_lines = []
    for b in lbs:
        line = f"- {b['code']}: {b['title']}"
        if b["detail_md"]:
            line += f"\n  Lehrplan-Detail (OCR-holprig, nur als Grundlage): {b['detail_md'][:800]}"
        lb_lines.append(line)
    user_text = (
        f"Frei geplante Stunde: {l['title']} · Fach {l['subject']} · Klassenstufe {l['grade'] or '-'} · "
        f"Stundentyp {l['lesson_type'] or '-'}\n\n"
        "Kandidaten-Lernbereiche:\n" + "\n".join(lb_lines) +
        f"\n\n{_ctx_block(ai.lesson_material_context(conn, user_id, lesson_id))}"
    )
    data, cached = _run_json(conn, user_id, "einordnung", _EINORDNUNG_SYSTEM, user_text, _EINORDNUNG_SCHEMA, max_tokens=4000)
    return {"suggestion": data, "cached": cached}
