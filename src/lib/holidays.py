"""Abruf von Feiertagen (feiertage-api.de) und Schulferien (ferien-api.de) für Sachsen.

Wird beim Anlegen eines Schuljahres einmalig aufgerufen; das Ergebnis landet in
SQLite (Tabelle school_dates). Kein Live-Abruf bei jedem Kalenderaufruf.
Nur stdlib (urllib) – keine Laufzeit-Zusatzabhängigkeit. In Tests wird
collect_school_dates gemockt (kein Netz).
"""
import json
import urllib.request
from typing import List

_TIMEOUT = 12


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "lehrer-dashboard"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_feiertage(year: int, state: str = "SN") -> List[dict]:
    data = _get_json(f"https://feiertage-api.de/api/?jahr={year}&nur_land={state}")
    out = []
    for name, info in data.items():
        d = (info or {}).get("datum")
        if d:
            out.append({"kind": "feiertag", "name": name, "start_date": d,
                        "end_date": d, "source": "feiertage-api.de"})
    return out


def fetch_ferien(year: int, state: str = "SN") -> List[dict]:
    data = _get_json(f"https://ferien-api.de/api/v1/holidays/{state}/{year}")
    out = []
    for h in data:
        start = (h.get("start") or "")[:10]
        end = (h.get("end") or "")[:10]
        if start and end:
            out.append({"kind": "ferien", "name": (h.get("name") or "Ferien").strip(),
                        "start_date": start, "end_date": end, "source": "ferien-api.de"})
    return out


def collect_school_dates(start_year: int, end_year: int, state: str = "SN") -> List[dict]:
    """Feiertage + Ferien für alle Jahre im Bereich; einzelne Ausfälle brechen nicht ab."""
    rows = []
    for year in range(start_year, end_year + 1):
        for fetch in (fetch_feiertage, fetch_ferien):
            try:
                rows += fetch(year, state)
            except Exception:  # Netz-/API-Ausfall: best effort, Schuljahr entsteht trotzdem
                pass
    return rows
