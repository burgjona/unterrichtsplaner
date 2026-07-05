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


# ---------- M9.1: vormals ungeschützte Router ----------

def test_users_endpoints_locked_down(client):
    """Regression M9.1: /users war ohne Login erreichbar (inkl. DELETE -> Kontoübernahme)."""
    client.post("/api/auth/register", json=REG)
    uid = client.get("/api/auth/me").json()["id"]
    client.post("/api/auth/logout")
    assert client.get("/api/users").status_code == 404                # Nutzerliste entfernt
    assert client.get(f"/api/users/{uid}").status_code == 401         # nur angemeldet
    assert client.put(f"/api/users/{uid}", json={"displayName": "X"}).status_code == 401
    assert client.request("DELETE", f"/api/users/{uid}").status_code == 405  # Löschen entfernt


def test_users_own_profile_only(client, user_id):
    fremd = user_id + 1
    assert client.get(f"/api/users/{fremd}").status_code == 403
    assert client.put(f"/api/users/{fremd}", json={"displayName": "X"}).status_code == 403
    r = client.put(f"/api/users/{user_id}", json={"displayName": "Neuer Name"})
    assert r.status_code == 200 and r.json()["displayName"] == "Neuer Name"


def test_lernbereiche_require_login(client):
    """Regression M9.1: Referenzdaten waren unangemeldet veränderbar."""
    assert client.get("/api/lernbereiche").status_code == 401
    assert client.post("/api/lernbereiche",
                       json={"subject": "Deutsch", "grade": 8, "track": "RS",
                             "code": "LBX", "title": "X", "richtwertUstd": 1}).status_code == 401
    assert client.request("DELETE", "/api/lernbereiche/1").status_code == 401


def test_expired_sessions_purged_on_login(client, app, user_id):
    from src.db import connect
    conn = connect(app.state.db_path)
    conn.execute(
        "INSERT INTO sessions(token, user_id, expires_at) VALUES ('alt-token', ?, datetime('now', '-1 hour'))",
        (user_id,))
    conn.commit()
    client.post("/api/auth/login", json={"email": REG["email"], "password": REG["password"]})
    left = conn.execute("SELECT COUNT(*) FROM sessions WHERE token = 'alt-token'").fetchone()[0]
    conn.close()
    assert left == 0
