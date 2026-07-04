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


def seed_lernbereiche(conn: sqlite3.Connection, docs_dir: str = None) -> int:
    docs = Path(docs_dir or settings.docs_dir)
    inserted = 0
    for subject, fname in _FILES.items():
        path = docs / fname
        if not path.exists():
            print(f"WARN: {path} fehlt – überspringe {subject}", file=sys.stderr)
            continue
        for row in parse_lernbereiche(path.read_text(encoding="utf-8"), subject):
            cur = conn.execute(
                """INSERT OR IGNORE INTO lernbereiche
                   (subject, grade, track, code, title, richtwert_ustd, sort_order, source)
                   VALUES (:subject,:grade,:track,:code,:title,:richtwert_ustd,:sort_order,:source)""",
                row,
            )
            inserted += cur.rowcount
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
