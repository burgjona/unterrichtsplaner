"""M12/U10: Profilbild-Upload, Logo-Upload + PWA-Favicon/Manifest.

Nutzt ein winziges gültiges 1×1-PNG als Testbild. Root-Guard/Pfad-Sicherheit
sinngemäß wie in tests/test_materials_upload.py.
"""
import base64
import json

# 1×1 transparentes PNG.
PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _me(client):
    return client.get("/api/auth/me").json()


# ---------- Profilbild ----------
def test_avatar_upload_sets_path_and_serves_bytes(client, auth):
    uid = _me(client)["id"]
    r = client.post(f"/api/users/{uid}/avatar",
                    files={"file": ("me.png", PNG_1x1, "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["avatarPath"] and ".branding/avatar_" in body["avatarPath"]

    g = client.get(f"/api/users/{uid}/avatar")
    assert g.status_code == 200
    assert g.content == PNG_1x1
    assert g.headers["content-type"].startswith("image/")


def test_avatar_get_404_when_none(client, auth):
    uid = _me(client)["id"]
    assert client.get(f"/api/users/{uid}/avatar").status_code == 404


def test_avatar_foreign_uid_forbidden(client, auth):
    uid = _me(client)["id"]
    r = client.post(f"/api/users/{uid + 999}/avatar",
                    files={"file": ("me.png", PNG_1x1, "image/png")})
    assert r.status_code == 403


def test_avatar_rejects_non_image(client, auth):
    uid = _me(client)["id"]
    r = client.post(f"/api/users/{uid}/avatar",
                    files={"file": ("notiz.txt", b"kein bild", "text/plain")})
    assert r.status_code == 415


def test_avatar_rejects_too_large(client, auth):
    uid = _me(client)["id"]
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024 + 10)
    r = client.post(f"/api/users/{uid}/avatar",
                    files={"file": ("big.png", big, "image/png")})
    assert r.status_code == 413


def test_avatar_requires_auth(client):
    assert client.post("/api/users/1/avatar",
                       files={"file": ("me.png", PNG_1x1, "image/png")}).status_code == 401


# ---------- Logo ----------
def test_logo_upload_get_delete_roundtrip(client, auth):
    r = client.post("/api/settings/logo", files={"file": ("logo.png", PNG_1x1, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["logoPath"].endswith(".branding/logo.png")

    g = client.get("/api/settings/logo")
    assert g.status_code == 200 and g.content == PNG_1x1

    d = client.delete("/api/settings/logo")
    assert d.status_code == 204
    assert client.get("/api/settings/logo").status_code == 404


def test_logo_get_404_when_none(client, auth):
    assert client.get("/api/settings/logo").status_code == 404


def test_logo_rejects_non_image(client, auth):
    r = client.post("/api/settings/logo", files={"file": ("x.txt", b"nope", "text/plain")})
    assert r.status_code == 415


# ---------- Favicon / Manifest (unauthentifiziert) ----------
def test_manifest_valid_json_without_logo(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    data = json.loads(r.content)
    assert data["name"] and data["short_name"]
    assert data["theme_color"] and data["background_color"]
    assert data["icons"] == []


def test_manifest_lists_icons_when_logo_set(client, auth):
    client.post("/api/settings/logo", files={"file": ("logo.png", PNG_1x1, "image/png")})
    r = client.get("/manifest.webmanifest")
    data = json.loads(r.content)
    assert len(data["icons"]) >= 1
    assert data["icons"][0]["src"] == "/api/branding/favicon"


def test_favicon_neutral_without_logo(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_favicon_serves_logo_when_set(client, auth):
    client.post("/api/settings/logo", files={"file": ("logo.png", PNG_1x1, "image/png")})
    r = client.get("/favicon.ico")
    assert r.status_code == 200 and r.content == PNG_1x1
