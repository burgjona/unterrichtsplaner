"""Schulmanager-Online-Abgleich (M1c): Feed abrufen, gegen U27-Stundenplan/Kalender
diffen, nur die Abweichungen zurückgeben. Reines Lesen, keine Persistenz – s.
schulmanager_diff.py für die Absprachen zum Referenzpunkt je Kategorie."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, get_user_id
from ..lib import schulmanager_diff, schulmanager_ical
from ..schemas import SchulmanagerChangesOut

router = APIRouter(prefix="/schulmanager", tags=["schulmanager"])


@router.get("/changes", response_model=SchulmanagerChangesOut)
def get_changes(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    try:
        events = schulmanager_ical.fetch_and_parse(conn, user_id)
    except schulmanager_ical.NoIcalUrl:
        raise HTTPException(status_code=400, detail="Kein Schulmanager-ICS-Link hinterlegt.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Abruf fehlgeschlagen: {exc}")
    return SchulmanagerChangesOut(**schulmanager_diff.compute_changes(conn, user_id, events))
