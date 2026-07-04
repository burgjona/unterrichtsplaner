from pathlib import Path

from src.db import init_db
from src.seed import parse_lernbereiche, seed_lernbereiche

DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_parse_deutsch_counts_and_values():
    rows = parse_lernbereiche((DOCS / "lp_os_deutsch_2019.md").read_text(encoding="utf-8"), "Deutsch")
    assert len(rows) == 51  # inkl. Kl. 5/6 (Orientierungsstufe, je 6 LB, 'gemischt')
    keys = [(r["grade"], r["track"], r["code"]) for r in rows]
    assert len(set(keys)) == len(keys)  # keine Dubletten trotz Detailkapitel
    # Kein Hauptschul-Bildungsgang in Klassenstufe 10
    assert (10, "HS") not in {(r["grade"], r["track"]) for r in rows}
    # Kl. 5/6 ohne Bildungsgang-Split → 'gemischt'
    assert {r["track"] for r in rows if r["grade"] in (5, 6)} == {"gemischt"}
    assert sum(1 for r in rows if r["grade"] in (5, 6)) == 12
    lb4 = next(r for r in rows if r["grade"] == 8 and r["track"] == "RS" and r["code"] == "LB4")
    assert lb4["title"] == "Entdeckungen: Printmedien"
    assert lb4["richtwert_ustd"] == 15


def test_parse_wth_counts_and_track():
    rows = parse_lernbereiche((DOCS / "lp_os_wth_2019.md").read_text(encoding="utf-8"), "WTH")
    assert len(rows) == 11
    assert {r["track"] for r in rows} == {"gemischt"}
    lb2 = next(r for r in rows if r["grade"] == 9 and r["code"] == "LB2")
    assert lb2["title"] == "Vertragsrechtliche Grundlagen"
    assert lb2["richtwert_ustd"] == 9


def test_seed_is_idempotent(tmp_path):
    conn = init_db(str(tmp_path / "seed.db"))
    first = seed_lernbereiche(conn)
    assert first == 62  # Deutsch 51 + WTH 11
    total = conn.execute("SELECT COUNT(*) FROM lernbereiche").fetchone()[0]
    assert total == 62
    second = seed_lernbereiche(conn)  # INSERT OR IGNORE → nichts Neues
    assert second == 0
    assert conn.execute("SELECT COUNT(*) FROM lernbereiche").fetchone()[0] == 62
    conn.close()
