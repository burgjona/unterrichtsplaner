"""Reine Verteil-Logik der Jahresplanung (ohne App/DB)."""
from datetime import date

from src.lib.planning import distribute_lernbereiche, teaching_weeks


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
