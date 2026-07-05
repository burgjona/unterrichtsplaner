# Deployment – Synology DS723+ + Cloudflare Tunnel (Meilenstein 9)

Dieser Meilenstein wird **gemeinsam Schritt für Schritt** durchgeführt (BRIEFING Kap. 2/8.3).
Die folgenden Artefakte sind vorbereitet: `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`,
`.dockerignore`. Die eigentliche Einrichtung auf NAS/Cloudflare erfolgt mit dir.

## 0. Voraussetzungen (von dir bereitzustellen)
- Synology DS723+ mit **Container Manager** (Docker) installiert.
- Eigene **Domain** in Cloudflare (kostenloser Plan genügt) + Cloudflare-Zero-Trust-Zugang.
- **Anthropic API-Key** (wird nicht ins Image gebacken, sondern später im UI unter *Einstellungen* hinterlegt).
- `APP_SECRET_KEY` (base64, 32 Byte) – erzeugen:
  ```
  python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
  ```

## 1. `.env` anlegen (nicht committen)
Im Projektordner auf der NAS:
```
APP_SECRET_KEY=<oben erzeugter Wert>
# CLOUDFLARE_TUNNEL_TOKEN=<falls Tunnel als Sidecar, siehe Schritt 4>
```

## 2. Image bauen & starten (Container Manager oder SSH)
```
docker compose build
docker compose up -d
docker compose logs -f app        # erwartet: Seed "62 Lernbereiche", dann uvicorn läuft
```
- **Volumes (Named Volumes):** `ldb_data` (SQLite-DB) und `ldb_storage` (Materialdateien) werden
  von Docker verwaltet (unter `/volume1/@docker/volumes/`). Das ist auf Synology robust gegen
  Freigabe-ACLs, die das Schreiben in per File Station angelegte Bind-Mount-Ordner selbst für
  root blockieren (`unable to open database file`). Es müssen **keine** Host-Ordner vorab
  angelegt werden.
- **Backup:** Beide Volumes über *Hyper Backup* (schließt `/volume1/@docker` ein) oder per
  `docker cp lehrer-dashboard:/data ./backup-data` bzw. `…:/storage ./backup-storage` sichern.
- **Materialien direkt browsebar (optional, später):** Wer die Dateien in File Station sehen
  will, legt eine echte DSM-Freigabe an, setzt darauf Schreibrechte und mountet sie statt
  `ldb_storage` als Bind-Mount (`- /volume1/<freigabe>:/storage`).

## 3. Lokal testen
`http://<NAS-IP>:8097/api/health` → `{"status":"ok", ...}`. Dann `http://<NAS-IP>:8097/`
öffnen → beim Erststart **„Erstes Konto anlegen"** (danach ist die Registrierung gesperrt).

## 4. Cloudflare Tunnel + Domain + HTTPS
1. Cloudflare Zero Trust → **Networks → Tunnels → Create tunnel** (Typ: *Cloudflared*).
2. Public Hostname anlegen: `dashboard.deine-domain.de` → Service **`http://app:8000`**
   (bei Sidecar-Betrieb) bzw. `http://<NAS-IP>:8097`.
3. Tunnel-Token kopieren → in `.env` als `CLOUDFLARE_TUNNEL_TOKEN`, den `cloudflared`-Block in
   `docker-compose.yml` einkommentieren, `docker compose up -d`.
4. Cloudflare erstellt den DNS-Eintrag und terminiert **HTTPS** automatisch.
5. Test: `https://dashboard.deine-domain.de/api/health` von außen.

## 5. Nach dem ersten Login
- Unter **Einstellungen** den Anthropic-API-Key eintragen (verschlüsselt gespeichert) → ✨-Funktionen aktiv.
- Ferien/Feiertage werden beim Anlegen eines Schuljahres automatisch abgerufen (Netz nötig).

## Betriebs-Hinweise
- **`APP_SECRET_KEY` sichern & dauerhaft konstant halten** – bei Verlust ist ein gespeicherter
  API-Key nicht mehr entschlüsselbar (dann im UI neu eingeben).
- **`COOKIE_SECURE=1`** ist gesetzt – Login-Cookies gehen nur über HTTPS (durch Cloudflare gegeben).
- **Backups:** `./data/data.db` (Konto, Planung) und `./storage` (Dateien) sichern.
- **Update:** `git pull` → `docker compose build && docker compose up -d`. Migrationen laufen
  automatisch beim Start (Tabelle `schema_migrations`), der Seed ist idempotent.
- **FTS5:** Das `python:3.12-slim`-Image bringt FTS5 mit; falls nicht, bricht der Start mit klarer
  Meldung ab (`src/db.py::assert_fts5`).
