"""Rechenkern des Notenmoduls: Tendenznoten und gewichtete Durchschnitte.

Bewusst ohne DB-Zugriff, damit die Notenlogik isoliert testbar bleibt (tests/test_noten.py).

Notenwerte sind Dezimalzahlen auf einem Viertelraster: 1+ = 0.75, 1 = 1.0, 1- = 1.25,
2+ = 1.75 usw. bis 6 = 6.0. "6-" gibt es nicht, der gültige Bereich endet bei 6.0.

Der Gesamtdurchschnitt entsteht aus zwei Töpfen (große und kleine Noten), gemischt nach dem
je Klasse eingestellten Prozentanteil der großen Noten. Ist ein Topf leer, zählt der andere
allein – siehe docs/konzept_noten.md, Abschnitt 4.
"""
from typing import Iterable, List, Optional

MIN_VALUE = 0.75
MAX_VALUE = 6.0
DEFAULT_GROSS_ANTEIL = 50

# Toleranz beim Vergleich mit dem Viertelraster (Float-Rundung aus SQLite).
_EPS = 1e-6


def parse_note(text) -> Optional[float]:
    """'2', '2+', '2-', '2,5', '2.5' → Dezimalwert. Leer/None → None (= nicht bewertet).

    Wirft ValueError bei unlesbarer Eingabe oder Werten außerhalb 0,75 … 6,0.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return _check_range(float(text))

    raw = str(text).strip()
    if not raw:
        return None

    if raw[-1] in "+-" and len(raw) > 1:
        base, tendenz = raw[:-1].strip(), raw[-1]
        try:
            value = float(base.replace(",", ".")) + (-0.25 if tendenz == "+" else 0.25)
        except ValueError:
            raise ValueError(f"'{raw}' ist keine Note.")
        return _check_range(value)

    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        raise ValueError(f"'{raw}' ist keine Note.")
    return _check_range(value)


def _check_range(value: float) -> float:
    if not (MIN_VALUE - _EPS <= value <= MAX_VALUE + _EPS):
        raise ValueError(f"Note muss zwischen 1+ und 6 liegen (Wert: {value:g}).")
    return round(value, 2)


def format_note(value: Optional[float]) -> str:
    """Dezimalwert → Anzeigeform: '2+' wenn auf dem Viertelraster, sonst '2,4'."""
    if value is None:
        return ""
    ganz = round(value)
    rest = value - ganz
    if 1 <= ganz <= 6:
        if abs(rest) < _EPS:
            return str(ganz)
        if abs(rest + 0.25) < _EPS:
            return f"{ganz}+"
        if abs(rest - 0.25) < _EPS:
            return f"{ganz}-"
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def average(values: Iterable[Optional[float]]) -> Optional[float]:
    """Mittelwert der bewerteten Noten; None, wenn keine einzige vorliegt."""
    vals: List[float] = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def gesamt_average(
    gross: Optional[float], klein: Optional[float], gross_anteil: int = DEFAULT_GROSS_ANTEIL
) -> Optional[float]:
    """Mischt die beiden Topf-Durchschnitte nach dem Prozentanteil der großen Noten.

    Ist ein Topf leer, zählt der andere allein – so braucht der Sonderfall keine eigene
    Einstellung und taucht in der Oberfläche nicht auf.
    """
    if gross is None and klein is None:
        return None
    if gross is None:
        return klein
    if klein is None:
        return gross
    anteil = clamp_anteil(gross_anteil)
    return round((gross * anteil + klein * (100 - anteil)) / 100, 2)


def clamp_anteil(gross_anteil) -> int:
    try:
        return max(0, min(100, int(gross_anteil)))
    except (TypeError, ValueError):
        return DEFAULT_GROSS_ANTEIL


def suggest_term_grade(gesamt: Optional[float]) -> Optional[float]:
    """Zeugnisnoten-Vorschlag: kaufmännisch gerundete Ganznote (2,5 → 3)."""
    if gesamt is None:
        return None
    return float(max(1, min(6, int(gesamt + 0.5))))


def summarize(entries: Iterable[dict], gross_anteil: int = DEFAULT_GROSS_ANTEIL) -> dict:
    """Fasst die Noten eines Schülers zusammen.

    entries: Dicts mit 'value' (Note oder None) und 'size' ('gross'/'klein').
    Rückgabe: die drei Durchschnitte plus Zeugnisnoten-Vorschlag.
    """
    entries = list(entries)
    gross = average(e["value"] for e in entries if e.get("size") == "gross")
    klein = average(e["value"] for e in entries if e.get("size") == "klein")
    gesamt = gesamt_average(gross, klein, gross_anteil)
    return {
        "avg_gross": gross,
        "avg_klein": klein,
        "avg_gesamt": gesamt,
        "suggested_term_grade": suggest_term_grade(gesamt),
    }
