"""Seedet die Lernbereich-Referenz aus den amtlichen Lehrplan-MD-Dateien.

Geparst wird ausschließlich der saubere Übersichtsblock der LP-Dateien
(`### Lernbereich N: Titel NN Ustd.`). Die weiter unten folgenden Detailkapitel
enthalten OCR-bedingt teils verstümmelte Überschriften ohne "Ustd." – diese
matchen das Muster nicht und werden übersprungen; exakte Dubletten werden per
first-wins dedupliziert. App-Umfang: Deutsch 5–10 (Kl. 5/6 'gemischt', ab 7 RS/HS), WTH 7–9 (gemischt).

Aufruf als CLI:  python -m src.seed
"""
import re
import sqlite3
import sys
from pathlib import Path

from .config import settings
from .db import init_db

_LB_RE = re.compile(r"^###\s+Lernbereich\s+(\d+)\s*:?\s*(.+?)\s+(\d+)\s+Ustd\.?\s*$")
_LB_HEAD_RE = re.compile(r"^###\s+Lernbereich\s+(\d+)\b")  # LB-Überschrift, auch ohne "Ustd." (Detailkapitel)
_GRADE_RE = re.compile(r"^##\s+Klassenstufe\s+(\d+)\s*$")

_SCOPE = {"Deutsch": {5, 6, 7, 8, 9, 10}, "WTH": {7, 8, 9}}
_FILES = {"Deutsch": "lp_os_deutsch_2019.md", "WTH": "lp_os_wth_2019.md"}


def parse_lernbereiche(text: str, subject: str) -> list:
    grade = None
    track = None
    seen = set()
    rows = []
    for line in text.splitlines():
        gm = _GRADE_RE.match(line)
        if gm:
            grade = int(gm.group(1))
            if grade == 5:  # Orientierungsstufe: Bildungsgang-Kontext zurücksetzen
                track = None
            continue
        if line.startswith("## Hauptschulbildungsgang"):
            track = "HS"
            continue
        if line.startswith("## Realschulbildungsgang"):
            track = "RS"
            continue
        m = _LB_RE.match(line)
        if not m or grade is None or grade not in _SCOPE[subject]:
            continue
        if subject == "Deutsch":
            # Kl. 5/6 (Orientierungsstufe) haben keinen Bildungsgang-Split → 'gemischt'
            eff_track = track or "gemischt"
        else:
            eff_track = "gemischt"
        num = int(m.group(1))
        code = f"LB{num}"
        key = (subject, grade, eff_track, code)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "subject": subject,
                "grade": grade,
                "track": eff_track,
                "code": code,
                "title": m.group(2).strip(),
                "richtwert_ustd": int(m.group(3)),
                "sort_order": num,
                "source": f"lp_os_{subject.lower()}_2019",
            }
        )
    return rows


def extract_detail_md(text: str, subject: str) -> dict:
    """Best-effort: Roh-Detailtext je Lernbereich aus dem Lehrplan-MD.

    Erfasst den Text zwischen einer LB-Überschrift und der nächsten Überschrift
    (jeder Zeile mit führendem '#') im jeweiligen Klassenstufen-/Bildungsgang-Kontext.
    Der kompakte Übersichtsblock (LB-Überschriften ohne Fließtext) liefert leere
    Bodies und wird verworfen; die Detailkapitel (OCR-holprig) liefern Inhalt und
    werden behalten. Rückgabe: {(grade, track, code): detail_md}.
    """
    grade = None
    track = None
    result = {}
    cur_key = None
    buf = []

    def _flush():
        if cur_key is not None:
            body = "\n".join(buf).strip()
            if len(body) > 40:  # kompakte Übersicht (leerer Body) verwerfen, nur echte Detailkapitel
                result[cur_key] = body

    for line in text.splitlines():
        gm = _GRADE_RE.match(line)
        if gm:
            _flush()
            cur_key, buf = None, []
            grade = int(gm.group(1))
            if grade == 5:  # Orientierungsstufe: Bildungsgang-Kontext zurücksetzen
                track = None
            continue
        if line.startswith("## Hauptschulbildungsgang"):
            _flush()
            cur_key, buf = None, []
            track = "HS"
            continue
        if line.startswith("## Realschulbildungsgang"):
            _flush()
            cur_key, buf = None, []
            track = "RS"
            continue
        m = _LB_HEAD_RE.match(line)
        if m:
            _flush()
            buf = []
            if grade is None or grade not in _SCOPE[subject]:
                cur_key = None
                continue
            eff_track = "gemischt" if subject == "WTH" else (track or "gemischt")
            cur_key = (grade, eff_track, f"LB{int(m.group(1))}")
            continue
        if line.startswith("#"):  # sonstige Überschrift (z. B. Wahlbereich) beendet den LB-Abschnitt
            _flush()
            cur_key, buf = None, []
            continue
        if cur_key is not None:
            buf.append(line)
    _flush()
    return result


def seed_lernbereiche(conn: sqlite3.Connection, docs_dir: str = None) -> int:
    docs = Path(docs_dir or settings.docs_dir)
    inserted = 0
    for subject, fname in _FILES.items():
        path = docs / fname
        if not path.exists():
            print(f"WARN: {path} fehlt – überspringe {subject}", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        for row in parse_lernbereiche(text, subject):
            cur = conn.execute(
                """INSERT OR IGNORE INTO lernbereiche
                   (subject, grade, track, code, title, richtwert_ustd, sort_order, source)
                   VALUES (:subject,:grade,:track,:code,:title,:richtwert_ustd,:sort_order,:source)""",
                row,
            )
            inserted += cur.rowcount
        # Detail-Rohtext als KI-Kontext nachtragen (idempotent per UPDATE, auch für Bestandszeilen)
        for (grade, track, code), detail in extract_detail_md(text, subject).items():
            conn.execute(
                "UPDATE lernbereiche SET detail_md = ? WHERE subject = ? AND grade = ? AND track = ? AND code = ?",
                (detail, subject, grade, track, code),
            )
    conn.commit()
    return inserted


def main() -> None:  # pragma: no cover - CLI
    conn = init_db(settings.db_path)
    n = seed_lernbereiche(conn)
    total = conn.execute("SELECT COUNT(*) FROM lernbereiche").fetchone()[0]
    conn.close()
    print(f"Seed abgeschlossen: {n} neu eingefügt, {total} Lernbereiche gesamt.")


if __name__ == "__main__":
    main()
