"""Auth-Flow: Bootstrap-Register, Login, Session-Cookie, Logout, Sperre."""

REG = {"email": "ref@stolpen.de", "displayName": "Referendar", "password": "Geheim1234!"}


def test_register_sets_session_cookie(client):
    r = client.post("/api/auth/register", json=REG)
    assert r.status_code == 201, r.text
    assert "ldb_session" in r.cookies
    # direkt eingeloggt -> geschützte Route erreichbar
    assert client.get("/api/auth/me").json()["email"] == REG["email"]


def test_register_locked_after_first_account(client):
    assert client.post("/api/auth/register", json=REG).status_code == 201
    second = client.post("/api/auth/register",
                         json={"email": "z@z.de", "displayName": "Z", "password": "Geheim1234!"})
    assert second.status_code == 403  # Bootstrap-Register gesperrt


def test_register_rejects_short_password(client):
    r = client.post("/api/auth/register",
                    json={"email": "a@b.de", "displayName": "A", "password": "kurz"})
    assert r.status_code == 400


def test_login_logout_cycle(client):
    client.post("/api/auth/register", json=REG)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401  # abgemeldet

    assert client.post("/api/auth/login",
                       json={"email": REG["email"], "password": "falsch"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": REG["email"], "password": REG["password"]})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").json()["email"] == REG["email"]


def test_invalid_session_cookie_rejected(client):
    client.cookies.set("ldb_session", "unsinniger-token")
    assert client.get("/api/auth/me").status_code == 401
