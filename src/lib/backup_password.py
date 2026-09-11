"""Sicherungspasswort (U29): schützt die Datensicherung und die Word-Exporte des
Notenmoduls, falls eine dieser Dateien im Download-Ordner, in der iCloud oder auf einem
fremden Rechner liegen bleibt.

Abgelegt wie der Anthropic-Key (AES-256-GCM mit APP_SECRET_KEY, migrations/070). Der
Server muss das Passwort selbst lesen können, weil auch die nächtliche Sicherung
(src/backup_cli.py) ohne Anmeldung damit verschlüsselt.
"""
from __future__ import annotations

import io
from typing import Optional

from msoffcrypto.format.ooxml import OOXMLFile

from .security import decrypt_secret

MIN_LENGTH = 10

MISSING_DETAIL = ("Bitte zuerst unter Einstellungen → Datensicherung ein Sicherungspasswort "
                  "festlegen – Sicherung und Noten-Exporte werden damit verschlüsselt.")


def _decrypt_row(row) -> Optional[str]:
    if row is None or row[0] is None:
        return None
    try:
        return decrypt_secret(row[0], row[1])
    except Exception:
        # APP_SECRET_KEY fehlt oder wurde getauscht: dann lieber "nicht festgelegt" als ein
        # 500er - die Oberfläche fordert zum erneuten Festlegen auf.
        return None


def get_password(conn, user_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT backup_pw_cipher, backup_pw_nonce FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return _decrypt_row(row)


def get_password_for_cli(conn) -> Optional[str]:
    """Die nächtliche Sicherung läuft ohne Anmeldung. Die App kennt genau ein Konto
    (die Registrierung sperrt sich nach dem ersten), also gilt dessen Passwort."""
    row = conn.execute(
        "SELECT backup_pw_cipher, backup_pw_nonce FROM user_settings "
        "WHERE backup_pw_cipher IS NOT NULL ORDER BY user_id LIMIT 1"
    ).fetchone()
    return _decrypt_row(row)


def encrypt_docx(data: bytes, password: str) -> bytes:
    """Passwortschutz im Office-eigenen Format (ECMA-376 Agile Encryption): Word fragt
    beim Öffnen direkt nach dem Passwort, es braucht kein Zusatzprogramm."""
    out = io.BytesIO()
    OOXMLFile(io.BytesIO(data)).encrypt(password, out)
    return out.getvalue()
