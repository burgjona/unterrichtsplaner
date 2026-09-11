"""Web Push: Benachrichtigungen über die PWA auf Handy, iPad und Desktop.

Der Server schickt jede Nachricht verschlüsselt an den Push-Dienst des jeweiligen
Browsers (Apple/Google/Mozilla), der sie ans Gerät zustellt – auch wenn die App
geschlossen ist. Authentifiziert wird mit einem serverweiten VAPID-Schlüsselpaar,
das beim ersten Gebrauch erzeugt und verschlüsselt in push_vapid abgelegt wird
(kein ENV nötig, Muster: google_cal.py / schulmanager_ical.py).

Tests mocken `_webpush` – nie echte Zustellungen in Tests.
"""
from __future__ import annotations

import base64
import json
import logging
import sqlite3
from typing import Optional

from .security import decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)

# Eine Erinnerung, die erst nach Stundenbeginn ankäme, ist wertlos: Push-Dienste
# verwerfen die Nachricht nach Ablauf der TTL, statt sie verspätet zuzustellen.
TTL_SECONDS = 15 * 60
SEND_TIMEOUT = 10.0


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _generate_keypair():
    """Neues VAPID-Paar -> (public_key base64url, private_key PEM)."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02

    vapid = Vapid02()
    vapid.generate_keys()
    raw_public = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(raw_public), vapid.private_pem().decode("ascii")


def get_public_key(conn: sqlite3.Connection) -> str:
    """Öffentlicher VAPID-Schlüssel (applicationServerKey fürs Frontend); legt das Paar
    beim ersten Aufruf an."""
    row = conn.execute("SELECT public_key FROM push_vapid WHERE id = 1").fetchone()
    if row is not None:
        return row["public_key"]
    public_key, pem = _generate_keypair()
    cipher, nonce = encrypt_secret(pem)
    # OR IGNORE: legen zwei Anfragen gleichzeitig an, gewinnt die erste – danach neu lesen.
    conn.execute(
        "INSERT OR IGNORE INTO push_vapid (id, public_key, private_cipher, private_nonce) "
        "VALUES (1, ?, ?, ?)",
        (public_key, cipher, nonce),
    )
    conn.commit()
    return conn.execute("SELECT public_key FROM push_vapid WHERE id = 1").fetchone()["public_key"]


def _load_vapid(conn: sqlite3.Connection):
    from py_vapid import Vapid02

    get_public_key(conn)
    row = conn.execute(
        "SELECT private_cipher, private_nonce FROM push_vapid WHERE id = 1"
    ).fetchone()
    pem = decrypt_secret(row["private_cipher"], row["private_nonce"])
    return Vapid02.from_pem(pem.encode("ascii"))


def _webpush(subscription_info: dict, data: str, vapid, claims: dict, requests_session=None):
    """Einzige Stelle mit echtem Netzverkehr (in Tests gemockt)."""
    from pywebpush import webpush

    return webpush(
        subscription_info,
        data=data,
        vapid_private_key=vapid,
        vapid_claims=claims,
        ttl=TTL_SECONDS,
        timeout=SEND_TIMEOUT,
        requests_session=requests_session,
    )


def _status_of(exc: Exception) -> Optional[int]:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def send_to_user(conn: sqlite3.Connection, user_id: int, title: str, body: str,
                 url: str = "/", tag: Optional[str] = None) -> dict:
    """Schickt eine Benachrichtigung an alle angemeldeten Geräte des Nutzers.

    Vom Push-Dienst als erloschen gemeldete Anmeldungen (404/410 – z. B. App gelöscht,
    Erlaubnis entzogen) werden entfernt. Liefert {sent, failed, removed}.
    """
    from pywebpush import WebPushException

    result = {"sent": 0, "failed": 0, "removed": 0}
    subs = conn.execute(
        "SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    if not subs:
        return result

    vapid = _load_vapid(conn)
    user = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    # Apple verlangt im VAPID-"sub" eine gültige mailto:/https:-Kontaktadresse.
    contact = f"mailto:{user['email']}" if user and user["email"] else "mailto:admin@localhost"
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})

    for sub in subs:
        info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
        try:
            # Frisches claims-dict je Gerät: webpush() trägt "aud" (Origin des Push-Dienstes)
            # in das übergebene dict ein – geteilt würde es beim nächsten Dienst falsch sein.
            _webpush(info, payload, vapid, {"sub": contact})
        except WebPushException as exc:
            status = _status_of(exc)
            if status in (404, 410):
                conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
                result["removed"] += 1
            else:
                log.warning("Push an Gerät %s fehlgeschlagen (%s): %s", sub["id"], status, exc)
                result["failed"] += 1
            continue
        except Exception as exc:  # Netz/Timeout: nächstes Gerät trotzdem versuchen
            log.warning("Push an Gerät %s fehlgeschlagen: %s", sub["id"], exc)
            result["failed"] += 1
            continue
        conn.execute(
            "UPDATE push_subscriptions SET last_success_at = datetime('now') WHERE id = ?",
            (sub["id"],),
        )
        result["sent"] += 1

    conn.commit()
    return result
