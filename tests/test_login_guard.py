"""Brute-Force-Bremse und Passwortwechsel (U28)."""
import pytest

from src.lib import loginguard
from tests.conftest import TEST_EMAIL, TEST_PW

WRONG = {"email": TEST_EMAIL, "password": "falsch-falsch"}


def _fail(client, times, ip="203.0.113.7"):
    codes = []
    for _ in range(times):
        r = client.post("/api/auth/login", json=WRONG, headers={"CF-Connecting-IP": ip})
        codes.append(r.status_code)
    return codes


def test_wrong_password_still_401_below_threshold(client, user_id):
    assert _fail(client, loginguard.MAX_PER_IP - 1) == [401] * (loginguard.MAX_PER_IP - 1)


def test_ip_is_locked_after_threshold(client, user_id):
    _fail(client, loginguard.MAX_PER_IP)
    r = client.post("/api/auth/login", json=WRONG, headers={"CF-Connecting-IP": "203.0.113.7"})
    assert r.status_code == 429
    assert r.headers["Retry-After"] == str(loginguard.WINDOW_MINUTES * 60)
    assert "Fehlversuche" in r.json()["detail"]


def test_lock_blocks_even_the_correct_password(client, user_id):
    """Kern der Sperre: sie greift VOR der Passwortpruefung - sonst wäre sie gegen
    genau das wirkungslos, was sie verhindern soll."""
    _fail(client, loginguard.MAX_PER_IP)
    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PW},
                    headers={"CF-Connecting-IP": "203.0.113.7"})
    assert r.status_code == 429


def test_other_ip_stays_usable_until_account_threshold(client, user_id):
    """Eine gesperrte IP darf nicht das ganze Konto lahmlegen - erst die hoehere
    Kontoschwelle greift IP-uebergreifend."""
    _fail(client, loginguard.MAX_PER_IP)          # IP A gesperrt
    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PW},
                    headers={"CF-Connecting-IP": "198.51.100.4"})
    assert r.status_code == 200


def test_account_threshold_locks_across_ips(client, user_id):
    for i in range(loginguard.MAX_PER_EMAIL):
        client.post("/api/auth/login", json=WRONG, headers={"CF-Connecting-IP": f"198.51.100.{i}"})
    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PW},
                    headers={"CF-Connecting-IP": "198.51.100.250"})
    assert r.status_code == 429


def test_successful_login_clears_the_counter(client, user_id):
    _fail(client, loginguard.MAX_PER_IP - 1)
    assert client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PW},
                       headers={"CF-Connecting-IP": "203.0.113.7"}).status_code == 200
    # Zähler zurueckgesetzt: es sind wieder volle Fehlversuche moeglich
    assert _fail(client, loginguard.MAX_PER_IP - 1) == [401] * (loginguard.MAX_PER_IP - 1)


def test_unknown_email_does_not_reveal_itself(client, user_id):
    r = client.post("/api/auth/login", json={"email": "fremd@example.org", "password": "x" * 12},
                    headers={"CF-Connecting-IP": "198.51.100.9"})
    assert r.status_code == 401
    assert r.json()["detail"] == "E-Mail oder Passwort ist falsch."   # gleiche Meldung wie oben


def test_no_password_material_is_stored(client, user_id, app):
    """Die Tabelle darf Fehlversuche zaehlen, aber nichts Geheimes aufbewahren."""
    client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": "streng-geheim-123"},
                headers={"CF-Connecting-IP": "203.0.113.7"})
    from src.db import connect
    conn = connect(app.state.db_path)
    rows = conn.execute("SELECT * FROM login_attempts").fetchall()
    assert len(rows) == 1
    assert "streng-geheim-123" not in str([dict(r) for r in rows])
    conn.close()


# ---------- Passwortwechsel ----------

NEW_PW = "NeuesGeheim456!"


def test_change_password_requires_login(client, user_id):
    client.cookies.clear()   # die user_id-Fixture meldet über /register schon an
    r = client.post("/api/auth/password",
                    json={"currentPassword": TEST_PW, "newPassword": NEW_PW})
    assert r.status_code == 401


def test_change_password_works_and_old_one_stops_working(client, auth):
    r = client.post("/api/auth/password",
                    json={"currentPassword": TEST_PW, "newPassword": NEW_PW})
    assert r.status_code == 200, r.text
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login",
                       json={"email": TEST_EMAIL, "password": TEST_PW}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": TEST_EMAIL, "password": NEW_PW}).status_code == 200


def test_change_password_rejects_wrong_current(client, auth):
    r = client.post("/api/auth/password",
                    json={"currentPassword": "falsch", "newPassword": NEW_PW})
    assert r.status_code == 401
    assert "Aktuelles Passwort" in r.json()["detail"]


@pytest.mark.parametrize("new_pw,expected", [("kurz", 400), (TEST_PW, 400)])
def test_change_password_validates_new(client, auth, new_pw, expected):
    r = client.post("/api/auth/password",
                    json={"currentPassword": TEST_PW, "newPassword": new_pw})
    assert r.status_code == expected


def test_change_password_keeps_own_session_and_drops_others(client, app, auth):
    """Andere Geraete fliegen raus, die eigene Sitzung bleibt bestehen."""
    from fastapi.testclient import TestClient
    other = TestClient(app)
    assert other.post("/api/auth/login",
                      json={"email": TEST_EMAIL, "password": TEST_PW}).status_code == 200

    r = client.post("/api/auth/password",
                    json={"currentPassword": TEST_PW, "newPassword": NEW_PW})
    # register und login der Fixtures hinterlassen je eine Sitzung, dazu die des
    # zweiten Geraets - alle ausser der eigenen müssen weg sein.
    assert r.json()["loggedOutDevices"] >= 1
    assert client.get("/api/auth/me").status_code == 200      # eigene Sitzung läuft weiter
    assert other.get("/api/auth/me").status_code == 401       # das andere Geraet ist abgemeldet
