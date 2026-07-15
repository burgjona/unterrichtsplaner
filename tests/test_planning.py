"""Reine Verteil-Logik der Jahresplanung (ohne App/DB)."""
from datetime import date

from src.lib.planning import (
    distribute_lernbereiche,
    effective_blocks,
    resolve_track,
    teaching_weeks,
)


def test_teaching_weeks_excludes_full_ferien_weeks():
    start, end = date(2025, 9, 1), date(2025, 9, 26)   # 4 volle Wochen (Mo–Fr)
    ferien = [(date(2025, 9, 8), date(2025, 9, 12))]    # Woche 2 komplett Ferien
    assert len(teaching_weeks(start, end, ferien)) == 3


def test_distribute_proportional_and_conflict():
    lbs = [{"id": 1, "code": "LB1", "title": "A", "richtwert_ustd": 4},
           {"id": 2, "code": "LB2", "title": "B", "richtwert_ustd": 2}]
    res = distribute_lernbereiche("2025-09-01", "2025-10-31", 2, lbs, [], ["2025-09-03"])
    assert res["planned"] == 2
    assert res["blocks"][0]["weeks"] == 2   # 4 Ustd / 2 Wochenstd = 2 Wochen
    assert res["blocks"][1]["weeks"] == 1
    assert res["blocks"][0]["conflict_with_fixed"] is True          # fixer 03.09. im 1. Block
    assert res["blocks"][1]["start_date"] > res["blocks"][0]["end_date"]  # sequentiell


def test_distribute_stops_when_out_of_weeks():
    lbs = [{"id": i, "code": f"LB{i}", "title": "x", "richtwert_ustd": 20} for i in range(1, 10)]
    res = distribute_lernbereiche("2025-09-01", "2025-09-12", 2, lbs, [], [])
    assert res["unplaced"] > 0


# ---------- M11: Bildungsgang-Auflösung ----------
def test_resolve_track():
    assert resolve_track("Deutsch", 8, "gemischt") == "RS"     # ab Kl. 7 → RS-Grundlage
    assert resolve_track("Deutsch", 5, "gemischt") == "gemischt"  # Orientierungsstufe bleibt
    assert resolve_track("WTH", 8, "gemischt") == "gemischt"    # WTH immer gemischt
    assert resolve_track("Deutsch", 9, "RS") == "RS"           # reiner Bildungsgang unverändert
    assert resolve_track("Deutsch", 7, "HS") == "HS"


# ---------- M11: LB1/LB2 (Deutsch) in die übrigen LB integrieren ----------
def test_effective_blocks_deutsch_sum_preserved():
    lbs = [
        {"code": "LB1", "title": "Sprechen/Zuhören", "richtwert_ustd": 10},
        {"code": "LB2", "title": "Sprache untersuchen", "richtwert_ustd": 10},
        {"code": "LB3", "title": "Lesen", "richtwert_ustd": 20},
        {"code": "LB4", "title": "Schreiben", "richtwert_ustd": 25},
        {"code": "LB5", "title": "Medien", "richtwert_ustd": 15},
    ]
    total = sum(x["richtwert_ustd"] for x in lbs)
    eff = effective_blocks("Deutsch", lbs)
    codes = [b["code"] for b in eff]
    assert "LB1" not in codes and "LB2" not in codes           # keine eigenen Blöcke mehr
    assert codes == ["LB3", "LB4", "LB5"]
    assert sum(b["richtwert_ustd"] for b in eff) == total      # Summe bleibt exakt erhalten
    # Original wird nicht mutiert (arbeitet auf Kopien):
    assert lbs[2]["richtwert_ustd"] == 20


def test_effective_blocks_wth_unchanged():
    lbs = [{"code": "LB1", "title": "x", "richtwert_ustd": 5},
           {"code": "LB2", "title": "y", "richtwert_ustd": 7},
           {"code": "LB3", "title": "z", "richtwert_ustd": 9}]
    eff = effective_blocks("WTH", lbs)
    assert [b["code"] for b in eff] == ["LB1", "LB2", "LB3"]
    assert [b["richtwert_ustd"] for b in eff] == [5, 7, 9]


def test_preview_gemischt_deutsch_grade8_liefert_bloecke(client, auth):
    """Vorher leer: Deutsch 'gemischt' ab Kl. 7 hat keine eigenen LB → jetzt RS-Grundlage."""
    sy = client.post("/api/school-years",
                     json={"label": "2025/2026", "startDate": "2025-08-11", "endDate": "2026-06-30"}).json()
    cls = client.post("/api/classes",
                      json={"name": "8a", "subject": "Deutsch", "grade": 8, "track": "gemischt",
                            "weeklyHours": 4}).json()
    for n, ustd in [(1, 10), (2, 10), (3, 20), (4, 20), (5, 20), (6, 20)]:
        client.post("/api/lernbereiche",
                    json={"subject": "Deutsch", "grade": 8, "track": "RS", "code": f"LB{n}",
                          "title": f"Thema {n}", "richtwertUstd": ustd})
    r = client.post("/api/planning/preview", json={"schoolYearId": sy["id"], "classId": cls["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    codes = [b["code"] for b in body["blocks"]]
    assert codes, "gemischte Deutsch-Klasse muss Blöcke liefern (vorher leer)"
    assert "LB1" not in codes and "LB2" not in codes
    assert body["unplaced"] == 0
    assert sum(b["ustd"] for b in body["blocks"]) == 100      # LB1/LB2-Stunden proportional aufgeschlagen
