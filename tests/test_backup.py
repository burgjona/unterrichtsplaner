"""Backup-Endpunkt: Anmeldepflicht, Inhalt, Konsistenz, Umlaute."""
import io
import json
import sqlite3
import zipfile


def _zip_from(response):
    assert response.status_code == 200, response.text
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_backup_requires_login(client):
    assert client.get("/api/backup").status_code == 401


def test_backup_contains_db_and_manifest(client, auth):
    zf = _zip_from(client.get("/api/backup"))
    assert "data.db" in zf.namelist()
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["lastMigration"]              # Migrationsstand dokumentiert
    assert manifest["includesStorage"] is True
    assert manifest["appVersion"]


def test_backup_db_is_openable_and_holds_the_data(client, auth, tmp_path):
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


def test_backup_includes_storage_files_with_umlauts(client, auth, app):
    root = __import__("pathlib").Path(app.state.storage_root) / "Deutsch" / "Klasse-8"
    root.mkdir(parents=True)
    (root / "Anfangsübung_Größe.txt").write_text("Inhalt äöüß", encoding="utf-8")

    zf = _zip_from(client.get("/api/backup"))
    name = "storage/Deutsch/Klasse-8/Anfangsübung_Größe.txt"
    assert name in zf.namelist()                              # Umlaute bleiben erhalten
    assert zf.read(name).decode("utf-8") == "Inhalt äöüß"
    assert json.loads(zf.read("manifest.json"))["storageFileCount"] == 1


def test_backup_can_skip_storage(client, auth, app):
    root = __import__("pathlib").Path(app.state.storage_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "gross.bin").write_bytes(b"x" * 1024)

    zf = _zip_from(client.get("/api/backup?includeStorage=false"))
    assert [n for n in zf.namelist() if n.startswith("storage/")] == []
    assert json.loads(zf.read("manifest.json"))["includesStorage"] is False


def test_backup_leaves_no_temp_files_behind(client, auth, app, tmp_path):
    """Das Arbeitsverzeichnis liegt neben der DB - es darf nichts liegen bleiben."""
    client.get("/api/backup")
    leftovers = list(tmp_path.glob("ldb-backup-*"))
    assert leftovers == [], leftovers
