"""Deterministische Jahres-Verplanung der Lernbereiche (Platzhalter bis M7).

Verteilt Lernbereiche in ihrer Reihenfolge proportional zu den Stundenrichtwerten
auf die verfügbaren Unterrichtswochen (Ferienwochen ausgespart) und markiert
Überschneidungen mit fixen Terminen. In M7 ersetzt die Claude-Sequenzierung
distribute_lernbereiche() bei gleicher Ein-/Ausgabestruktur.
Reine Funktionen, kein I/O – testbar.
"""
import math
from datetime import date, timedelta
from typing import List, Tuple


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def _in_any(day: date, ranges: List[Tuple[date, date]]) -> bool:
    return any(s <= day <= e for s, e in ranges)


def teaching_weeks(start: date, end: date, ferien: List[Tuple[date, date]]) -> List[date]:
    """Montage aller Wochen, die nicht komplett in Ferien liegen (Mo–Fr betrachtet)."""
    weeks = []
    cur = start - timedelta(days=start.weekday())  # Montag der Startwoche
    while cur <= end:
        school_days = [cur + timedelta(days=i) for i in range(5) if start <= cur + timedelta(days=i) <= end]
        if school_days and not all(_in_any(d, ferien) for d in school_days):
            weeks.append(cur)
        cur += timedelta(days=7)
    return weeks


def distribute_lernbereiche(
    start_date: str,
    end_date: str,
    weekly_hours: int,
    lernbereiche: List[dict],
    ferien_ranges: List[Tuple[str, str]],
    fixed_dates: List[str],
) -> dict:
    start, end = _d(start_date), _d(end_date)
    ferien = [(_d(s), _d(e)) for s, e in ferien_ranges]
    fixed = [_d(x) for x in fixed_dates]
    weeks = teaching_weeks(start, end, ferien)
    wh = max(1, weekly_hours)

    blocks = []
    wi = 0
    for lb in lernbereiche:
        if wi >= len(weeks):
            break
        ustd = lb.get("richtwert_ustd") or 0
        need = max(1, math.ceil(ustd / wh))
        end_idx = min(wi + need - 1, len(weeks) - 1)
        w_start = weeks[wi]
        block_end = min(weeks[end_idx] + timedelta(days=4), end)  # bis Freitag
        conflict = any(w_start <= fd <= block_end for fd in fixed)
        blocks.append({
            "lernbereich_id": lb.get("id"),
            "code": lb.get("code"),
            "title": lb.get("title"),
            "ustd": ustd,
            "weeks": end_idx - wi + 1,
            "start_date": w_start.isoformat(),
            "end_date": block_end.isoformat(),
            "conflict_with_fixed": conflict,
        })
        wi = end_idx + 1

    return {
        "teaching_weeks": len(weeks),
        "planned": len(blocks),
        "unplaced": max(0, len(lernbereiche) - len(blocks)),
        "blocks": blocks,
    }
