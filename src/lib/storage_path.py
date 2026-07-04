"""Reine Helferfunktion für die NAS-Ablagestruktur.

Konvention (BRIEFING Kap. 1): {root}/{fach}/{klasse}/{schuljahr}/{dateiname}
({klasse} = Klassenstufe, z. B. "Klasse-8"). Umlaute (ä/ö/ü/ß) bleiben erhalten
(BRIEFING Kap. 3); nur Pfad-Trenner, Path-Traversal und Steuerzeichen werden
entschärft. Keine I/O – testbar.
"""
import re
import unicodedata
from pathlib import PurePosixPath

_SEP_RE = re.compile(r"[\\/]+")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize(value: str, fallback: str) -> str:
    value = unicodedata.normalize("NFC", value or "").strip()
    value = value.replace("..", "-")      # kein Traversal
    value = _SEP_RE.sub("-", value)       # keine Pfad-Trenner
    value = _CTRL_RE.sub("", value)       # keine Steuerzeichen
    value = value.strip(". ")             # keine führenden/folgenden Punkte/Spaces
    return value or fallback


def build_storage_path(
    school_year: str,
    subject: str,
    class_name: str,
    filename: str,
    root: str = "/storage",
) -> str:
    year = _sanitize(school_year, "unbekanntes-schuljahr")
    fach = _sanitize(subject, "unbekanntes-fach")
    klasse = _sanitize(class_name, "unbekannte-klasse")
    # Nur der Basisname des Uploads zählt – verwirft mitgeschickte Verzeichnisanteile.
    name = _sanitize(PurePosixPath((filename or "").replace("\\", "/")).name, "datei")
    return str(PurePosixPath(root) / fach / klasse / year / name)
