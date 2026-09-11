"""Backup-Endpunkt: Anmeldepflicht, Inhalt, Konsistenz, Umlaute, Verschlüsselung (U29)."""
import io
import json
import sqlite3
import zipfile

import pyzipper
import pytest

PW = "Sicherung-Test-2026"


@pytest.fixture
def backup_pw(client, auth):
    """U29: ohne Sicherungspasswort gibt es keinen Download."""
    r = client.put("/api/settings/backup-password", json={"password": PW})
    assert r.status_code == 200, r.text
    return PW


def _zip_from(response, password=PW):
    assert response.status_code == 200, response.text
    zf = pyzipper.AESZipFile(io.BytesIO(response.content))
    zf.setpassword(password.encode("utf-8"))
    return zf


def test_backup_requires_login(client):
    assert client.get("/api/backup").status_code == 401


def test_backup_requires_a_backup_password(client, auth):
    r = client.get("/api/backup")
    assert r.status_code == 409
    assert "Sicherungspasswort" in r.json()["detail"]


def test_backup_is_encrypted(client, backup_pw):
    """Kernzusage U29: ohne das richtige Passwort ist nichts lesbar."""
    r = client.get("/api/backup")
    assert r.status_code == 200, r.text
    with pytest.raises(RuntimeError):
        zipfile.ZipFile(io.BytesIO(r.content)).read("data.db")
    with pytest.raises(RuntimeError):
        _zip_from(r, "falsches-passwort").read("data.db")
    assert json.loads(_zip_from(r).read("manifest.json"))["encrypted"] is True


def test_backup_contains_db_and_manifest(client, backup_pw):
    zf = _zip_from(client.get("/api/backup"))
    assert "data.db" in zf.namelist()
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["lastMigration"]              # Migrationsstand dokumentiert
    assert manifest["includesStorage"] is True
    assert manifest["appVersion"]


def test_backup_db_is_openable_and_holds_the_data(client, backup_pw, tmp_path):
    """Kernzusage: der Snapshot laesst sich oeffnen und enthaelt die Nutzdaten."""
    client.post("/api/school-years", json={"label": "2025/2026", "startDate": "2025-08-25",
                                           "endDate": "2026-07-10"})
    zf = _zip_from(client.get("/api/backup"))
    restored = tmp_path / "restored.db"
    restored.write_bytes(zf.read("data.db"))

    conn = sqlite3.connect(str(restored))
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    labels = [r[0] for r in conn.execute("SELECT label FROM school_years")]
    assert "2025/2026" in labels
    conn.close()


def test_backup_includes_storage_files_with_umlauts(client, backup_pw, app):
    root = __import__("pathlib").Path(app.state.storage_root) / "Deutsch" / "Klasse-8"
    root.mkdir(parents=True)
    (root / "Anfangsübung_Größe.txt").write_text("Inhalt äöüß", encoding="utf-8")

    zf = _zip_from(client.get("/api/backup"))
    name = "storage/Deutsch/Klasse-8/Anfangsübung_Größe.txt"
    assert name in zf.namelist()                              # Umlaute bleiben erhalten
    assert zf.read(name).decode("utf-8") == "Inhalt äöüß"
    assert json.loads(zf.read("manifest.json"))["storageFileCount"] == 1


def test_backup_can_skip_storage(client, backup_pw, app):
    root = __import__("pathlib").Path(app.state.storage_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "gross.bin").write_bytes(b"x" * 1024)

    zf = _zip_from(client.get("/api/backup?includeStorage=false"))
    assert [n for n in zf.namelist() if n.startswith("storage/")] == []
    assert json.loads(zf.read("manifest.json"))["includesStorage"] is False


def test_backup_leaves_no_temp_files_behind(client, backup_pw, app, tmp_path):
    """Das Arbeitsverzeichnis liegt neben der DB - es darf nichts liegen bleiben."""
    assert client.get("/api/backup").status_code == 200
    leftovers = list(tmp_path.glob("ldb-backup-*"))
    assert leftovers == [], leftovers


# ---------- Sicherungspasswort in den Einstellungen (U29) ----------

def test_backup_password_starts_unset(client, auth):
    s = client.get("/api/settings").json()
    assert s["backupPasswordSet"] is False
    assert s["backupPasswordSetAt"] is None


def test_backup_password_status_but_never_the_password(client, backup_pw):
    r = client.get("/api/settings")
    s = r.json()
    assert s["backupPasswordSet"] is True
    assert s["backupPasswordSetAt"]
    assert PW not in r.text


def test_backup_password_needs_min_length(client, auth):
    r = client.put("/api/settings/backup-password", json={"password": "kurz"})
    assert r.status_code == 400
    assert client.get("/api/settings").json()["backupPasswordSet"] is False


def test_backup_password_requires_login(client):
    r = client.put("/api/settings/backup-password", json={"password": "lang-genug-123"})
    assert r.status_code == 401


def test_changed_password_applies_to_new_backups(client, backup_pw):
    neu = "Ganz-neues-Passwort-42"
    assert client.put("/api/settings/backup-password", json={"password": neu}).status_code == 200
    r = client.get("/api/backup")
    assert json.loads(_zip_from(r, neu).read("manifest.json"))["encrypted"] is True
    with pytest.raises(RuntimeError):
        _zip_from(r, PW).read("data.db")
