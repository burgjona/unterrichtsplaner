"""Web-Push M1: VAPID-Schlüssel, Geräte-Anmeldung, Versand (Zustellung gemockt)."""
import base64
import json
import os
import types

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException

from src.db import connect
from src.lib import push

PUSH = "/api/push"


def _conn(client):
    return connect(client.app.state.db_path)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _browser_keys():
    """Echte Geräteschlüssel wie von PushSubscription.toJSON() geliefert."""
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {"p256dh": _b64url(raw), "auth": _b64url(os.urandom(16))}


def _subscribe(client, endpoint="https://fcm.googleapis.com/fcm/send/abc", label="Mac"):
    return client.post(f"{PUSH}/subscriptions",
                       json={"endpoint": endpoint, "expirationTime": None,
                             "keys": _browser_keys(), "label": label})


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake(info, data, vapid, claims, requests_session=None):
        calls.append({"info": info, "data": data, "vapid": vapid, "claims": claims})

    monkeypatch.setattr(push, "_webpush", fake)
    return calls


# ---------------------------------------------------------------- VAPID-Schlüssel
def test_public_key_is_created_once_and_stays_stable(client, auth):
    first = client.get(f"{PUSH}/public-key")
    assert first.status_code == 200
    key = first.json()["publicKey"]
    assert len(base64.urlsafe_b64decode(key + "==")) == 65  # unkomprimierter P-256-Punkt
    assert client.get(f"{PUSH}/public-key").json()["publicKey"] == key


def test_private_key_is_stored_encrypted(client, auth):
    client.get(f"{PUSH}/public-key")
    row = _conn(client).execute("SELECT private_cipher FROM push_vapid").fetchone()
    assert b"PRIVATE KEY" not in bytes(row["private_cipher"])


def test_stored_key_signs_vapid_header(client, auth):
    client.get(f"{PUSH}/public-key")
    vapid = push._load_vapid(_conn(client))
    headers = vapid.sign({"sub": "mailto:ref@stolpen.de", "aud": "https://web.push.apple.com",
                          "exp": 9999999999})
    assert headers["Authorization"].startswith("vapid t=")


def test_endpoints_require_login(client):
    assert client.get(f"{PUSH}/public-key").status_code == 401
    assert client.post(f"{PUSH}/test").status_code == 401


# ---------------------------------------------------------------- Anmeldung
def test_subscribe_is_idempotent_per_endpoint(client, auth):
    assert _subscribe(client, label="iPhone").status_code == 201
    r = _subscribe(client, label="iPhone 15")
    assert r.status_code == 201
    subs = client.get(f"{PUSH}/subscriptions").json()
    assert len(subs) == 1
    assert subs[0]["label"] == "iPhone 15"
    assert "endpoint" not in subs[0]  # Geräte-URL/Schlüssel verlassen den Server nicht


def test_subscribe_rejects_non_https_endpoint(client, auth):
    assert _subscribe(client, endpoint="http://evil.example/push").status_code == 400


def test_unsubscribe_removes_only_that_device(client, auth):
    _subscribe(client, endpoint="https://web.push.apple.com/a", label="iPhone")
    _subscribe(client, endpoint="https://web.push.apple.com/b", label="iPad")
    r = client.post(f"{PUSH}/unsubscribe", json={"endpoint": "https://web.push.apple.com/a"})
    assert r.status_code == 204
    assert [s["label"] for s in client.get(f"{PUSH}/subscriptions").json()] == ["iPad"]


# ---------------------------------------------------------------- Versand
def test_test_push_without_device_is_rejected(client, auth, sent):
    assert client.post(f"{PUSH}/test").status_code == 400
    assert sent == []


def test_test_push_reaches_every_device(client, auth, sent):
    _subscribe(client, endpoint="https://web.push.apple.com/a")
    _subscribe(client, endpoint="https://fcm.googleapis.com/fcm/send/b")
    r = client.post(f"{PUSH}/test")
    assert r.json() == {"sent": 2, "failed": 0, "removed": 0}
    assert {c["info"]["endpoint"] for c in sent} == {
        "https://web.push.apple.com/a", "https://fcm.googleapis.com/fcm/send/b"}
    assert all(c["claims"] == {"sub": "mailto:ref@stolpen.de"} for c in sent)
    assert sent[0]["claims"] is not sent[1]["claims"]  # webpush() schreibt "aud" hinein
    assert json.loads(sent[0]["data"])["title"] == "Test-Benachrichtigung"
    row = _conn(client).execute("SELECT last_success_at FROM push_subscriptions LIMIT 1").fetchone()
    assert row["last_success_at"] is not None


def test_expired_subscription_is_removed(client, auth, monkeypatch):
    _subscribe(client, endpoint="https://web.push.apple.com/weg")
    _subscribe(client, endpoint="https://web.push.apple.com/da")

    def fake(info, data, vapid, claims, requests_session=None):
        if info["endpoint"].endswith("/weg"):
            raise WebPushException("Gone", response=types.SimpleNamespace(status_code=410))
        if info["endpoint"].endswith("/da"):
            raise WebPushException("Server", response=types.SimpleNamespace(status_code=500))

    monkeypatch.setattr(push, "_webpush", fake)
    assert client.post(f"{PUSH}/test").json() == {"sent": 0, "failed": 1, "removed": 1}
    assert len(client.get(f"{PUSH}/subscriptions").json()) == 1  # 500 = vorübergehend, bleibt


def test_umlauts_survive_payload(client, auth, user_id, sent):
    _subscribe(client)
    push.send_to_user(_conn(client), user_id, "Aufsicht Schulhof", "Frühaufsicht in 5 Minuten – Größe")
    assert json.loads(sent[0]["data"])["body"] == "Frühaufsicht in 5 Minuten – Größe"


def test_real_encryption_pipeline_without_network(client, auth, user_id):
    """Echter pywebpush-Pfad bis zum HTTP-POST: Verschlüsselung + VAPID-Header mit dem
    gespeicherten Schlüssel für echte Geräteschlüssel. Nur die HTTP-Session ist gefälscht."""
    posted = []

    class FakeSession:
        def post(self, url, data=None, headers=None, timeout=None):
            posted.append({"url": url, "data": data, "headers": headers})
            return types.SimpleNamespace(status_code=201, text="", headers={})

    info = {"endpoint": "https://web.push.apple.com/x", "keys": _browser_keys()}
    conn = _conn(client)
    push._webpush(info, json.dumps({"title": "Ä"}), push._load_vapid(conn),
                  {"sub": "mailto:ref@stolpen.de"}, requests_session=FakeSession())
    assert posted[0]["url"] == "https://web.push.apple.com/x"
    assert posted[0]["headers"]["Authorization"].startswith("vapid t=")
    assert posted[0]["headers"]["content-encoding"] == "aes128gcm"
    assert posted[0]["headers"]["ttl"] == str(push.TTL_SECONDS)
