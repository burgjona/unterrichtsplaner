import base64
import os

# Vor dem Import von src.main setzen:
# - :memory: verhindert, dass das modul-level app = create_app() eine echte data.db anlegt.
# - APP_SECRET_KEY (32 Byte base64) wird für die API-Key-Verschlüsselung im Test gebraucht.
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("APP_SECRET_KEY", base64.b64encode(b"x" * 32).decode())

import pytest
from fastapi.testclient import TestClient

from src.main import create_app

TEST_EMAIL = "ref@stolpen.de"
TEST_PW = "Geheim1234!"


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "test.db"), storage_root=str(tmp_path / "storage"))


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def user_id(client):
    """Legt via Bootstrap-Register das (einzige) Konto an; setzt zugleich das Session-Cookie."""
    r = client.post("/api/auth/register",
                    json={"email": TEST_EMAIL, "displayName": "Referendar", "password": TEST_PW})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _no_network_holidays(monkeypatch):
    """Kein Netz in Tests: Ferien/Feiertage-Abruf standardmäßig neutralisieren."""
    from src.lib import holidays
    monkeypatch.setattr(holidays, "collect_school_dates", lambda *a, **k: [])


@pytest.fixture
def auth(client, user_id):
    """Stellt sicher, dass der client eingeloggt ist. Auth läuft über das Cookie im
    TestClient-Cookiejar; Rückgabe {} hält bestehende headers=auth-Aufrufe als No-Op gültig."""
    client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PW})
    return {}
