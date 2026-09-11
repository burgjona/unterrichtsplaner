"""Web-Push-Benachrichtigungen (M1): Geräte an-/abmelden, Test-Push.

Jedes Gerät (Handy, iPad, Desktop-Browser) meldet sich einzeln an – die Erlaubnis
erteilt der Browser je Gerät. Das Frontend schickt seine PushSubscription bei jedem
App-Start erneut (idempotent über den endpoint), damit eine serverseitig entfernte
Anmeldung von selbst wieder auftaucht.
"""
import sqlite3
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db, get_user_id
from ..lib import push
from ..lib.security import secret_available
from ..schemas import (
    PushPublicKeyOut, PushSendResultOut, PushSubscriptionIn, PushSubscriptionOut, PushUnsubscribeIn,
)

router = APIRouter(prefix="/push", tags=["push"])

_SUB_COLS = "id, label, created_at, last_success_at"


@router.get("/public-key", response_model=PushPublicKeyOut)
def public_key(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    if not secret_available():
        raise HTTPException(status_code=503, detail="APP_SECRET_KEY ist serverseitig nicht gesetzt.")
    return PushPublicKeyOut(public_key=push.get_public_key(conn))


@router.get("/subscriptions", response_model=List[PushSubscriptionOut])
def list_subscriptions(conn: sqlite3.Connection = Depends(get_db),
                       user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        f"SELECT {_SUB_COLS} FROM push_subscriptions WHERE user_id = ? ORDER BY created_at, id",
        (user_id,),
    ).fetchall()
    return [PushSubscriptionOut(**dict(r)) for r in rows]


@router.post("/subscriptions", response_model=PushSubscriptionOut, status_code=201)
def subscribe(body: PushSubscriptionIn, conn: sqlite3.Connection = Depends(get_db),
              user_id: int = Depends(get_user_id)):
    if not body.endpoint.startswith("https://"):
        raise HTTPException(status_code=400, detail="Ungültiger Push-Endpunkt.")
    # Upsert über den endpoint: dasselbe Gerät erneut anmelden aktualisiert nur Schlüssel/Label.
    conn.execute(
        "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, label) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id, "
        "p256dh = excluded.p256dh, auth = excluded.auth, label = excluded.label",
        (user_id, body.endpoint, body.keys.p256dh, body.keys.auth, body.label),
    )
    conn.commit()
    row = conn.execute(
        f"SELECT {_SUB_COLS} FROM push_subscriptions WHERE endpoint = ?", (body.endpoint,)
    ).fetchone()
    return PushSubscriptionOut(**dict(row))


@router.post("/unsubscribe", status_code=204)
def unsubscribe(body: PushUnsubscribeIn, conn: sqlite3.Connection = Depends(get_db),
                user_id: int = Depends(get_user_id)):
    conn.execute(
        "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
        (user_id, body.endpoint),
    )
    conn.commit()


@router.post("/test", response_model=PushSendResultOut)
def send_test(conn: sqlite3.Connection = Depends(get_db), user_id: int = Depends(get_user_id)):
    has_device = conn.execute(
        "SELECT 1 FROM push_subscriptions WHERE user_id = ? LIMIT 1", (user_id,)
    ).fetchone()
    if has_device is None:
        raise HTTPException(status_code=400, detail="Kein Gerät für Benachrichtigungen angemeldet.")
    result = push.send_to_user(
        conn, user_id, "Test-Benachrichtigung",
        "Benachrichtigungen funktionieren – so sehen Erinnerungen und Vertretungen aus.",
        tag="test",
    )
    return PushSendResultOut(**result)
