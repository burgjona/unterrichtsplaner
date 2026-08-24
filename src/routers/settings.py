"""Einstellungen: Anthropic-API-Key (verschlüsselt) + Statusanzeige (BRIEFING Kap. 6).

Der Key wird AES-256-GCM-verschlüsselt gespeichert; nur die letzten 4 Zeichen
liegen im Klartext für die Anzeige vor. Die eigentliche Nutzung des Keys (Calls)
kommt in Meilenstein 7.
"""
import json
import os
import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from ..deps import get_db, get_storage_root, get_user_id
from ..lib import schulmanager_ical
from ..lib.branding import media_type_for, resolve_relpath, save_image_upload
from ..lib.security import encrypt_secret, secret_available
from ..schemas import ApiKeyIn, AppearanceIn, GoogleKeyIn, SchulmanagerIcalIn, SettingsOut

router = APIRouter(prefix="/settings", tags=["settings"])


def _settings_out(conn, user_id) -> SettingsOut:
    row = conn.execute(
        "SELECT anthropic_key_last4, anthropic_key_set_at, theme, dark_mode, font, "
        "       google_key_cipher, google_calendar_id, google_last_sync, "
        "       schulmanager_ical_cipher, schulmanager_last_sync "
        "FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    has_key = row is not None and row["anthropic_key_last4"] is not None
    google_set = row is not None and row["google_key_cipher"] is not None
    schulmanager_set = row is not None and row["schulmanager_ical_cipher"] is not None
    return SettingsOut(
        api_key_status="aktiv" if has_key else "kein Key",
        api_key_last4=row["anthropic_key_last4"] if has_key else None,
        api_key_set_at=row["anthropic_key_set_at"] if has_key else None,
        secret_configured=secret_available(),
        theme=row["theme"] if row is not None else "fruehling",
        dark_mode=bool(row["dark_mode"]) if row is not None else False,
        font=row["font"] if row is not None else "verspielt",
        google_key_set=google_set,
        google_calendar_id=row["google_calendar_id"] if google_set else None,
        google_last_sync=row["google_last_sync"] if row is not None else None,
        schulmanager_ical_set=schulmanager_set,
        schulmanager_last_sync=row["schulmanager_last_sync"] if schulmanager_set else None,
        deploy_commit=os.environ.get("GIT_COMMIT", "unbekannt"),
        deploy_time=os.environ.get("DEPLOY_TIME", "unbekannt"),
    )


@router.get("", response_model=SettingsOut)
def get_settings(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    return _settings_out(conn, user_id)


@router.post("/clear-cache", status_code=204)
def clear_cache(user_id: int = Depends(get_user_id)):
    """Weist den Browser per Clear-Site-Data-Header an, HTTP-Cache + Service-Worker/
    Cache-Storage für diese Origin zu leeren. Rein clientseitiges Löschen (caches.delete,
    registration.unregister) erreicht den normalen HTTP-Disk-Cache nicht — dieser Header
    ist der einzige zuverlässige, browserübergreifende Weg dafür (fehlte bislang, deshalb
    wirkte der Button in Chrome nicht, in Edge zufällig schon)."""
    return Response(status_code=204, headers={"Clear-Site-Data": '"cache", "storage"'})


@router.put("/api-key", response_model=SettingsOut)
def set_api_key(body: ApiKeyIn, conn: sqlite3.Connection = Depends(get_db),
                user_id: int = Depends(get_user_id)):
    if not secret_available():
        raise HTTPException(
            status_code=503,
            detail="APP_SECRET_KEY ist nicht konfiguriert – der API-Key kann nicht verschlüsselt gespeichert werden.",
        )
    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Leerer API-Key.")
    cipher, nonce = encrypt_secret(key)
    conn.execute(
        """INSERT INTO user_settings
             (user_id, anthropic_key_cipher, anthropic_key_nonce, anthropic_key_last4,
              anthropic_key_set_at, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
           ON CONFLICT(user_id) DO UPDATE SET
             anthropic_key_cipher = excluded.anthropic_key_cipher,
             anthropic_key_nonce  = excluded.anthropic_key_nonce,
             anthropic_key_last4  = excluded.anthropic_key_last4,
             anthropic_key_set_at = excluded.anthropic_key_set_at,
             updated_at           = datetime('now')""",
        (user_id, cipher, nonce, key[-4:]),
    )
    conn.commit()
    return _settings_out(conn, user_id)


@router.delete("/api-key", response_model=SettingsOut)
def delete_api_key(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    conn.execute(
        """UPDATE user_settings SET anthropic_key_cipher = NULL, anthropic_key_nonce = NULL,
             anthropic_key_last4 = NULL, anthropic_key_set_at = NULL, updated_at = datetime('now')
           WHERE user_id = ?""",
        (user_id,),
    )
    conn.commit()
    return _settings_out(conn, user_id)


# ---------- Google-Kalender-Sync (U21) ----------
@router.put("/google-key", response_model=SettingsOut)
def set_google_key(body: GoogleKeyIn, conn: sqlite3.Connection = Depends(get_db),
                   user_id: int = Depends(get_user_id)):
    """Service-Account-JSON-Schlüssel + Kalender-ID verschlüsselt speichern (Muster api-key)."""
    if not secret_available():
        raise HTTPException(
            status_code=503,
            detail="APP_SECRET_KEY ist nicht konfiguriert – der Schlüssel kann nicht verschlüsselt gespeichert werden.",
        )
    key_json = body.key_json.strip()
    calendar_id = body.calendar_id.strip()
    if not key_json:
        raise HTTPException(status_code=400, detail="Leerer Google-Schlüssel.")
    if not calendar_id:
        raise HTTPException(status_code=400, detail="Kalender-ID fehlt.")
    # Frühe, freundliche Validierung: muss wenigstens gültiges JSON eines Service-Accounts sein.
    try:
        info = json.loads(key_json)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Der Schlüssel ist kein gültiges JSON.")
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise HTTPException(status_code=400,
                            detail="Kein Service-Account-Schlüssel (Feld \"type\": \"service_account\" fehlt).")
    cipher, nonce = encrypt_secret(key_json)
    conn.execute(
        """INSERT INTO user_settings
             (user_id, google_key_cipher, google_key_nonce, google_calendar_id,
              google_key_set_at, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
           ON CONFLICT(user_id) DO UPDATE SET
             google_key_cipher  = excluded.google_key_cipher,
             google_key_nonce   = excluded.google_key_nonce,
             google_calendar_id = excluded.google_calendar_id,
             google_key_set_at  = excluded.google_key_set_at,
             updated_at         = datetime('now')""",
        (user_id, cipher, nonce, calendar_id),
    )
    conn.commit()
    return _settings_out(conn, user_id)


@router.delete("/google-key", response_model=SettingsOut)
def delete_google_key(conn: sqlite3.Connection = Depends(get_db),
                      user_id: int = Depends(get_user_id)):
    """Google-Schlüssel + Sync-Status entfernen (Mapping der Einträge bleibt bestehen)."""
    conn.execute(
        """UPDATE user_settings SET google_key_cipher = NULL, google_key_nonce = NULL,
             google_calendar_id = NULL, google_key_set_at = NULL, google_sync_token = NULL,
             google_last_sync = NULL, updated_at = datetime('now')
           WHERE user_id = ?""",
        (user_id,),
    )
    conn.commit()
    return _settings_out(conn, user_id)


# ---------- Schulmanager-Online-ICS-Sync (M1a) ----------
@router.put("/schulmanager-ical", response_model=SettingsOut)
def set_schulmanager_ical(body: SchulmanagerIcalIn, conn: sqlite3.Connection = Depends(get_db),
                          user_id: int = Depends(get_user_id)):
    """Persönlichen ICS-Link (aus Schulmanager: Stundenplan → 'Kalender abonnieren') verschlüsselt speichern."""
    if not secret_available():
        raise HTTPException(
            status_code=503,
            detail="APP_SECRET_KEY ist nicht konfiguriert – der Link kann nicht verschlüsselt gespeichert werden.",
        )
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Leerer ICS-Link.")
    if not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Der Link muss mit https:// beginnen.")
    cipher, nonce = encrypt_secret(url)
    conn.execute(
        """INSERT INTO user_settings (user_id, schulmanager_ical_cipher, schulmanager_ical_nonce,
                                      schulmanager_ical_set_at, updated_at)
           VALUES (?, ?, ?, datetime('now'), datetime('now'))
           ON CONFLICT(user_id) DO UPDATE SET
             schulmanager_ical_cipher  = excluded.schulmanager_ical_cipher,
             schulmanager_ical_nonce   = excluded.schulmanager_ical_nonce,
             schulmanager_ical_set_at  = excluded.schulmanager_ical_set_at,
             updated_at                = datetime('now')""",
        (user_id, cipher, nonce),
    )
    conn.commit()
    return _settings_out(conn, user_id)


@router.delete("/schulmanager-ical", response_model=SettingsOut)
def delete_schulmanager_ical(conn: sqlite3.Connection = Depends(get_db),
                             user_id: int = Depends(get_user_id)):
    conn.execute(
        """UPDATE user_settings SET schulmanager_ical_cipher = NULL, schulmanager_ical_nonce = NULL,
             schulmanager_ical_set_at = NULL, schulmanager_last_sync = NULL, updated_at = datetime('now')
           WHERE user_id = ?""",
        (user_id,),
    )
    conn.commit()
    return _settings_out(conn, user_id)


@router.post("/schulmanager-ical/test-sync")
def test_schulmanager_ical(conn: sqlite3.Connection = Depends(get_db),
                           user_id: int = Depends(get_user_id)):
    """Ruft den hinterlegten Feed ab und zählt die erkannten Event-Typen (M1a-Smoke-Test,
    noch ohne Soll/Ist-Abgleich oder Übernahme in den Kalender)."""
    try:
        events = schulmanager_ical.fetch_and_parse(conn, user_id)
    except schulmanager_ical.NoIcalUrl:
        raise HTTPException(status_code=400, detail="Kein Schulmanager-ICS-Link hinterlegt.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Abruf fehlgeschlagen: {exc}")
    counts: dict = {}
    for ev in events:
        counts[ev["kind"]] = counts.get(ev["kind"], 0) + 1
    return {"total": len(events), "byKind": counts}


# ---------- Darstellung (Meilenstein 12, U9) ----------
@router.put("/appearance", response_model=SettingsOut)
def set_appearance(body: AppearanceIn, conn: sqlite3.Connection = Depends(get_db),
                   user_id: int = Depends(get_user_id)):
    """Jahreszeit-Theme, Hell/Dunkel und Schriftart persistieren (user-gescoped, upsert).

    Validierung der Werte erfolgt bereits im Pydantic-Modell (AppearanceIn).
    Legt die Settings-Zeile bei Erstzugriff an, falls sie noch nicht existiert.
    """
    conn.execute(
        """INSERT INTO user_settings (user_id, theme, dark_mode, font, updated_at)
             VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(user_id) DO UPDATE SET
             theme      = excluded.theme,
             dark_mode  = excluded.dark_mode,
             font       = excluded.font,
             updated_at = datetime('now')""",
        (user_id, body.theme, 1 if body.dark_mode else 0, body.font),
    )
    conn.commit()
    return _settings_out(conn, user_id)


# ---------- Branding: Logo (Favicon & PWA-App-Icon) — M12/U10, ans Router-Ende ----------
@router.post("/logo")
async def upload_logo(file: UploadFile = File(...),
                      conn: sqlite3.Connection = Depends(get_db),
                      user_id: int = Depends(get_user_id),
                      storage_root: str = Depends(get_storage_root)):
    """Logo hochladen (image/*, max. 5 MB). Dient als Favicon + PWA-App-Icon."""
    rel = await save_image_upload(file, "logo", storage_root)
    conn.execute(
        """INSERT INTO user_settings (user_id, logo_path, updated_at)
             VALUES (?, ?, datetime('now'))
           ON CONFLICT(user_id) DO UPDATE SET
             logo_path = excluded.logo_path, updated_at = datetime('now')""",
        (user_id, rel),
    )
    conn.commit()
    return {"logoPath": rel}


@router.get("/logo")
def get_logo(conn: sqlite3.Connection = Depends(get_db),
             user_id: int = Depends(get_user_id),
             storage_root: str = Depends(get_storage_root)):
    row = conn.execute("SELECT logo_path FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    if not row or not row["logo_path"]:
        raise HTTPException(status_code=404, detail="Kein Logo hinterlegt.")
    path = resolve_relpath(row["logo_path"], storage_root)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Logo-Datei nicht gefunden.")
    return FileResponse(path, media_type=media_type_for(path))


@router.delete("/logo", status_code=204)
def delete_logo(conn: sqlite3.Connection = Depends(get_db),
                user_id: int = Depends(get_user_id),
                storage_root: str = Depends(get_storage_root)):
    row = conn.execute("SELECT logo_path FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    if row and row["logo_path"]:
        try:
            path = resolve_relpath(row["logo_path"], storage_root)
            if os.path.exists(path):
                os.remove(path)
        except HTTPException:  # Fremdpfad-Altbestand: nur DB-Feld leeren
            pass
        conn.execute("UPDATE user_settings SET logo_path = NULL, updated_at = datetime('now') WHERE user_id = ?",
                     (user_id,))
        conn.commit()
