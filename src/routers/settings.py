"""Einstellungen: Anthropic-API-Key (verschlüsselt) + Statusanzeige (BRIEFING Kap. 6).

Der Key wird AES-256-GCM-verschlüsselt gespeichert; nur die letzten 4 Zeichen
liegen im Klartext für die Anzeige vor. Die eigentliche Nutzung des Keys (Calls)
kommt in Meilenstein 7.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, get_user_id
from ..lib.security import encrypt_secret, secret_available
from ..schemas import ApiKeyIn, AppearanceIn, SettingsOut

router = APIRouter(prefix="/settings", tags=["settings"])


def _settings_out(conn, user_id) -> SettingsOut:
    row = conn.execute(
        "SELECT anthropic_key_last4, anthropic_key_set_at, theme, dark_mode, font "
        "FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    has_key = row is not None and row["anthropic_key_last4"] is not None
    return SettingsOut(
        api_key_status="aktiv" if has_key else "kein Key",
        api_key_last4=row["anthropic_key_last4"] if has_key else None,
        api_key_set_at=row["anthropic_key_set_at"] if has_key else None,
        secret_configured=secret_available(),
        theme=row["theme"] if row is not None else "fruehling",
        dark_mode=bool(row["dark_mode"]) if row is not None else False,
        font=row["font"] if row is not None else "verspielt",
    )


@router.get("", response_model=SettingsOut)
def get_settings(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    return _settings_out(conn, user_id)


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
