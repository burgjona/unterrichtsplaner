"""Einstellungen: API-Key-Status + verschlüsselte Ablage (BRIEFING Kap. 6)."""


def test_status_without_key(client, auth):
    s = client.get("/api/settings").json()
    assert s["apiKeyStatus"] == "kein Key"
    assert s["apiKeyLast4"] is None
    assert s["secretConfigured"] is True  # APP_SECRET_KEY in conftest gesetzt


def test_set_and_delete_api_key(client, auth):
    put = client.put("/api/settings/api-key", json={"apiKey": "sk-ant-api03-XYZ-abcd"})
    assert put.status_code == 200, put.text
    s = put.json()
    assert s["apiKeyStatus"] == "aktiv"
    assert s["apiKeyLast4"] == "abcd"      # nur letzte 4 Zeichen sichtbar
    assert s["apiKeySetAt"] is not None

    # Rohdaten in der DB sind verschlüsselt, kein Klartext
    conn = client.app.state.db_path
    import sqlite3
    c = sqlite3.connect(conn)
    cipher = c.execute("SELECT anthropic_key_cipher FROM user_settings").fetchone()[0]
    c.close()
    assert cipher is not None and b"sk-ant" not in cipher

    dele = client.delete("/api/settings/api-key").json()
    assert dele["apiKeyStatus"] == "kein Key"
    assert dele["apiKeyLast4"] is None


def test_settings_requires_login(client):
    assert client.get("/api/settings").status_code == 401


# ---------- Darstellung (Meilenstein 12, U9) ----------
def test_appearance_defaults(client, auth):
    s = client.get("/api/settings").json()
    assert s["theme"] == "fruehling"
    assert s["darkMode"] is False
    assert s["font"] == "verspielt"


def test_set_and_read_appearance(client, auth):
    put = client.put("/api/settings/appearance",
                     json={"theme": "herbst", "darkMode": True, "font": "standard"})
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["theme"] == "herbst"
    assert body["darkMode"] is True
    assert body["font"] == "standard"
    # Persistenz: erneutes GET liefert dieselben Werte
    s = client.get("/api/settings").json()
    assert (s["theme"], s["darkMode"], s["font"]) == ("herbst", True, "standard")


def test_appearance_invalid_theme_rejected(client, auth):
    r = client.put("/api/settings/appearance",
                   json={"theme": "sommerloch", "darkMode": False, "font": "verspielt"})
    assert r.status_code == 422


def test_appearance_invalid_font_rejected(client, auth):
    r = client.put("/api/settings/appearance",
                   json={"theme": "winter", "darkMode": False, "font": "fancy"})
    assert r.status_code == 422


def test_appearance_requires_login(client):
    r = client.put("/api/settings/appearance",
                   json={"theme": "winter", "darkMode": False, "font": "standard"})
    assert r.status_code == 401


def test_appearance_coexists_with_api_key(client, auth):
    # Appearance-Upsert darf einen bereits gesetzten API-Key nicht löschen.
    client.put("/api/settings/api-key", json={"apiKey": "sk-ant-api03-XYZ-wxyz"})
    client.put("/api/settings/appearance",
               json={"theme": "sommer", "darkMode": True, "font": "standard"})
    s = client.get("/api/settings").json()
    assert s["apiKeyStatus"] == "aktiv"
    assert s["apiKeyLast4"] == "wxyz"
    assert s["theme"] == "sommer"
