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
- **Backup:** Bevorzugt über die App selbst (siehe *Datensicherung* unten). Zusätzlich beide
  Volumes über *Hyper Backup* (schließt `/volume1/@docker` ein) sichern.
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
- **Backups:** siehe Abschnitt *Datensicherung*.
- **Update:** `git pull` → `docker compose build && docker compose up -d`. Migrationen laufen
  automatisch beim Start (Tabelle `schema_migrations`), der Seed ist idempotent.
- **Deploy-Zeitstempel + Commit (Einstellungen-Seite):** Damit "Letztes NAS-Update" im UI
  stimmt, muss das Update-Skript `GIT_COMMIT`/`DEPLOY_TIME` als Build-Args setzen (Dockerfile
  nimmt sie per `ARG`/`ENV` auf, `docker-compose.yml` reicht sie durch). Task-Scheduler-Skript
  entsprechend erweitern:
  ```bash
  export HOME=/root
  git config --global --add safe.directory /volume1/docker/adlerplan
  cd /volume1/docker/adlerplan
  git pull
  export GIT_COMMIT=$(git rev-parse --short HEAD)
  export DEPLOY_TIME=$(date '+%d.%m.%Y %H:%M')
  docker compose build
  docker compose up -d
  ```
  (Pfad ggf. anpassen — Beispiel aus dem bestehenden Skript.)
- **FTS5:** Das `python:3.12-slim`-Image bringt FTS5 mit; falls nicht, bricht der Start mit klarer
  Meldung ab (`src/db.py::assert_fts5`).

## Datensicherung

### Sicherung ziehen
**Einstellungen → Datensicherung → „Sicherung herunterladen"**. Das ZIP enthält:

| Datei | Inhalt |
|---|---|
| `data.db` | die komplette Datenbank – Konto, Planung, Klassen, Stundenplan, Notizen |
| `storage/…` | die abgelegten Materialdateien (abwählbar, falls das ZIP sonst zu groß wird) |
| `manifest.json` | Zeitpunkt, App-Version und Migrationsstand der Sicherung |

Die Datenbank wird per `VACUUM INTO` gesichert, nicht bloß kopiert: das erzeugt im laufenden
Betrieb einen in sich geschlossenen Stand. Eine reine Dateikopie von `data.db` kann dagegen
unvollständig sein, weil frische Schreibvorgänge im WAL (`data.db-wal`) stehen – das fällt
erst beim Zurückspielen auf.

**Wichtig: die Sicherung außerhalb der NAS aufbewahren.** Liegt die einzige Kopie auf demselben
Gerät, trifft ein Defekt, ein Verschlüsselungstrojaner oder ein Bedienfehler Original und
Sicherung gleichzeitig. RAID ersetzt kein Backup – es schützt nur vor einer defekten Platte.

### Zurückspielen
1. Container stoppen (Container Manager → Projekt → **Stoppen**).
2. `data.db` aus dem ZIP in das Volume `ldb_data` legen, `storage/` nach `ldb_storage`.
   Ohne SSH geht das über File Station unter `/volume1/@docker/volumes/<projekt>_ldb_data/_data/`
   (versteckte Ordner in File Station einblenden).
3. Eventuell vorhandene `data.db-wal` und `data.db-shm` **löschen** – sie gehören zum alten
   Stand und würden die zurückgespielte Datei verfälschen.
4. Container starten. Migrationen laufen automatisch; ist die Sicherung älter als der
   Programmstand, bringt der Start das Schema selbsttätig nach.

### Nächtlich automatisch sichern (Aufgabenplaner)

Eine Sicherung, die man von Hand anstoßen muss, wird im Schulalltag vergessen. Der
Aufgabenplaner erledigt sie nachts von selbst.

**Einmalig einrichten:** *Systemsteuerung → Aufgabenplaner → Erstellen → Geplante Aufgabe
→ Benutzerdefiniertes Skript*.

| Feld | Wert |
|---|---|
| Aufgabe | `Lehrer-Dashboard sichern` |
| Benutzer | `root` (nötig für `docker`) |
| Zeitplan | täglich, z. B. 03:00 Uhr |
| Benutzerdefiniertes Skript | siehe unten |

Unter *Einstellungen* zusätzlich **„Ausgabedetails per E-Mail senden"** aktivieren und
**„Nur bei abnormaler Beendigung"** wählen. Ohne das merkt man wochenlang nicht, wenn die
Sicherung scheitert — der häufigste Grund, warum Backups im Ernstfall fehlen.

```bash
#!/bin/bash
set -euo pipefail

ZIEL="/volume1/Backups/Lehrer-Dashboard"   # Ordner in einer DSM-Freigabe, ggf. anpassen
mkdir -p "$ZIEL"

# 1. Sicherung im Container erzeugen. Sie landet im Daten-Volume (dort ist Plattenplatz);
#    --behalte 1 hält das Volume schlank, die Aufbewahrung passiert auf der Freigabe.
docker exec lehrer-dashboard python -m src.backup_cli /data/_backup --behalte 1

# 2. auf die Freigabe holen (kein Bind-Mount nötig, deshalb ACL-unempfindlich)
docker cp lehrer-dashboard:/data/_backup/. "$ZIEL/"

# 3. auf der Freigabe aufräumen: älter als 14 Tage fliegt raus.
#    -maxdepth 1 und das Namensmuster stellen sicher, dass nur eigene Sicherungen
#    betroffen sind - andere Dateien im Ordner bleiben unangetastet.
find "$ZIEL" -maxdepth 1 -name 'lehrer-dashboard-backup-*.zip' -mtime +14 -delete
```

Für ein reines Datenbank-Backup (viel kleiner und schneller, ohne die Materialdateien)
in Zeile 1 `--ohne-materialien` ergänzen.

**Wichtig:** Den Zielordner in *Hyper Backup* aufnehmen, damit die Sicherungen die NAS
verlassen. Solange sie nur dort liegen, trifft ein Defekt Original und Kopie zugleich.

**Von Hand testen:** Das Skript im Aufgabenplaner markieren und *Ausführen* klicken, danach
in File Station nachsehen, ob im Zielordner eine ZIP-Datei liegt.

### Regelmäßig prüfen
Ein Backup, das nie zurückgespielt wurde, ist eine Vermutung. Einmal pro Halbjahr eine
Sicherung testweise in eine Zweitinstanz einspielen und schauen, ob die Planung vollständig ist.
