# Lehrer-Dashboard – Backend

Referendariat Oberschule Stolpen (Deutsch & WTH). Backend: **FastAPI + SQLite**.
Design-/UX-Referenz: `reference/dash_v15.html`. Anforderungen: `claude_code_briefing_lehrer_dashboard.md`.

## Stand: Meilenstein 1–8

**M1 – Datenmodell & Grundgerüst:** SQLite-Schema (Migration + FTS5), FastAPI-Grundgerüst,
CRUD für Nutzer · Schuljahre · Klassen · Lernbereiche · Stunden (inkl. normalisierter Phasen) ·
Kalendereinträge · Materialien (Metadaten) · Verknüpfungen, `build_storage_path()`-Helfer,
Lernbereich-Seed aus den amtlichen LP-Dateien.

**M2 – Nutzerverwaltung & Login:** Registrierung (Bootstrap: nur solange 0 Konten) mit
Passwort-Hashing (argon2id), serverseitige Sessions via HttpOnly-Cookie, Einstellungen mit
AES-256-GCM-verschlüsseltem Anthropic-API-Key + Statusanzeige. Nutzer-Scoping über Session-Cookie.

**M3 – Kernfunktionen migriert:** Frontend unter `web/` (CSS/HTML/JS getrennt) gegen die API
statt localStorage – Login-Gate, Heute-Übersicht (KPIs, Todos), Klassen, Unterrichtsplanung
(Klafki/Meyer-Ampel/Phasen), Reflexion, Einstellungen (API-Key). Backend um `reflections` und
`todos` (Migration 003) erweitert. FastAPI liefert `web/` statisch aus. Keine Testdaten.

**M4 – Kalender-Automatik & Jahresplanung:** Stunde mit Klasse + Datum → automatischer,
mitgeführter Kalendereintrag; Kalender-UI (Monat/Woche, Klassenfilter, Lernbereichs-Zeitleiste,
manuelle/fixe Termine); Ferien & Feiertage Sachsen werden beim Anlegen eines Schuljahres von
öffentlichen APIs (feiertage-api.de / ferien-api.de) abgerufen und lokal gespeichert (Migration
004); deterministische Jahres-Verplanung der Lernbereiche (Stoffverteilungsplan) als
Platzhalter – in M7 durch Claude ersetzt (gleiche Schnittstelle). Schultermine-MD-Import
bewusst noch offen (Format vorher abzustimmen).

**M5 – Materialbibliothek:** echter Datei-Upload in den NAS-Baum `/storage/{Fach}/{Klasse}/{Schuljahr}/`
({Klasse} = Klassenstufe) mit atomarem Ablauf (upload→store→extract→index→link); PDF-Text wird
automatisch (pypdf, keine KI) in ~600-Wort-Abschnitte mit Seitenangabe zerlegt und in FTS5
indexiert; Volltextsuche `GET /materials/search` (Grundlage für den KI-Abruf in M7); auth-geschützter
Download; Mehrfachverknüpfung; **Direkt-Upload** aus der Stunde (Detail-Dialog) und dem
Stoffverteilungsplan (je Lernbereich) über denselben Pfad. Max. 50 MB, Nicht-PDF wird gespeichert
ohne Extraktion.

**M6 – ASUV-Modul & Export:** ASUV-Entwurf je Stunde (`asuv_drafts`, Migration 006) mit
deterministischer Vorbefüllung aus Klafki/Phasen/Stundendaten, Formalien-Checkliste, nicht-blockierender
BiBox-Erinnerung; Export als **Word (.docx)** und **PDF** im bindenden Format (Arial 11, Zeilenabstand
1,5, Blocksatz, Deckblatt, Inhaltsverzeichnis, Verlaufsplanung-Tabelle, Quellen,
Selbständigkeitserklärung). Endpunkte `GET/PUT /lessons/{id}/asuv`, `GET …/asuv/export?format=docx|pdf`.
Hinweis Deploy (M9): für exaktes Arial im **PDF** unter Docker `fonts-liberation` installieren
(sonst Fallback Helvetica); Word nutzt Arial ohnehin nativ.

**M7 – Claude-API-Integration:** offizielles `anthropic`-SDK, festes Modell-Routing (Haiku/Sonnet
je Funktion, Kap. 5), lokaler Prompt-Cache + Anthropic-Prompt-Caching, gezielter FTS-Kontext (Top-K
statt Volltext), Kosten-Logging (`ai_usage`, Migration 007) + monatliche Kostenanzeige. Drei
✨-Funktionen: Stundenvorschlag aus dem Ideenfeld, Stoffverteilungsplan-Generierung,
ASUV-Ausformulierung (alle Sonnet). API-Key aus M2 entschlüsselt; ohne Key sind alle ✨-Buttons
deaktiviert (Hinweis statt Fehler). Nutzereigene Kosten – der echte Call läuft erst mit hinterlegtem
Key. Verbleibende Haiku-Helfer (Methodenvorschlag, Ressourcen-/Sozialform-Warnung) = Folge-Iteration.

**M8 – Mobile-Feinschliff & QA:** alle Detailseiten an den Breakpoints 375/600/920/1080/1280 geprüft –
**kein horizontales Scrollen** auf irgendeiner Ansicht, Off-Canvas-Nav + Burger unter 920px,
Tabellen brechen um, Touch-Ziele ≥44px, Eingabefelder 16px. Desktop-Layout (≥1081px: feste Sidebar,
mehrspaltige Grids) durch die `@media`-Regeln unverändert. Keine CSS-Korrekturen nötig.

**M9 – Deployment (vorbereitet, Einrichtung gemeinsam):** `Dockerfile`, `docker-compose.yml`,
`entrypoint.sh`, `.dockerignore` und [DEPLOY.md](DEPLOY.md) liegen bereit. Die eigentliche
Einrichtung auf der Synology DS723+ (Container Manager) + Cloudflare Tunnel + Domain + HTTPS wird
laut Briefing (Kap. 2/8.3) **gemeinsam Schritt für Schritt** durchgeführt.

**Bewusst später:** Semantische Suche (Embeddings); die Haiku-Micro-KI-Helfer aus Kap. 5
(Methodenvorschlag, Ressourcen-/Sozialform-Warnung) als Folge-Iteration.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt      # oder requirements.txt ohne Tests
cp .env.example .env

# Pflicht ab M2: Master-Key für die API-Key-Verschlüsselung erzeugen und in .env eintragen
./.venv/bin/python -c "import os,base64;print('APP_SECRET_KEY='+base64.b64encode(os.urandom(32)).decode())"
```

## Datenbank initialisieren & Lernbereiche seeden

Migrationen laufen automatisch beim App-Start. Der Lernbereich-Seed (aus `docs/lp_os_*.md`)
wird einmalig angestoßen:

```bash
./.venv/bin/python -m src.seed        # -> "Seed abgeschlossen: 50 neu eingefügt, 50 gesamt."
```

## Server starten

```bash
./.venv/bin/python -m uvicorn src.main:app --reload --port 8099
# App:  http://127.0.0.1:8099/       (beim Erststart „Erstes Konto anlegen")
# Docs: http://127.0.0.1:8099/docs   ·   Health: /api/health
```

## Tests

```bash
./.venv/bin/python -m pytest -q       # 18 Tests, In-Memory/Temp-DB, ohne Netz
```

## API-Kurzreferenz (Auszug)

Auth über **Session-Cookie** (HttpOnly). Mit curl per Cookie-Jar (`-c` schreibt, `-b` liest).
Request/Response in **camelCase**, DB/Code in snake_case. Umlaute bleiben überall erhalten.

```bash
B=http://127.0.0.1:8099/api
J=cookies.txt

# Erststart: einziges Konto anlegen (danach ist /auth/register gesperrt). Setzt Session-Cookie.
curl -c $J -X POST $B/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"ref@stolpen.de","displayName":"Referendar","password":"Mind8Zeichen!"}'

# Später erneut anmelden
curl -c $J -X POST $B/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"ref@stolpen.de","password":"Mind8Zeichen!"}'

# ab hier immer -b $J mitgeben:
curl -b $J -X POST $B/school-years -H 'Content-Type: application/json' \
  -d '{"label":"2025/2026","startDate":"2025-08-01","endDate":"2026-07-15"}'

curl -b $J -X POST $B/classes -H 'Content-Type: application/json' \
  -d '{"name":"8a","subject":"Deutsch","grade":8,"track":"RS","weeklyHours":3,"schoolYearId":1}'

curl -b $J "$B/lernbereiche?subject=Deutsch&grade=8&track=RS"

curl -b $J -X POST $B/lessons -H 'Content-Type: application/json' -d '{
  "title":"Balladen szenisch erschließen","subject":"Deutsch","grade":8,"classId":1,
  "lessonType":"Einführung","time":"08:50",
  "klafki":{"gegenwart":"Alltagsbezug","struktur":"Wendepunkt"},
  "meyerPlan":["gruen","gruen","gelb","gruen","gruen","gruen","gelb","gruen","gruen","gruen"],
  "phases":[{"phaseName":"Einstieg","minutes":10,"socialForm":"Plenum","method":"Hörimpuls"}]}'

curl -b $J -X POST $B/materials -H 'Content-Type: application/json' \
  -d '{"filename":"BalladenAB.pdf","subject":"Deutsch","grade":8,"schoolYearId":1,"status":"fertig"}'
curl -b $J -X POST $B/materials/1/links -H 'Content-Type: application/json' \
  -d '{"lessonId":1,"lernbereichId":27}'

# Einstellungen: Anthropic-API-Key (verschlüsselt) setzen und Status prüfen
curl -b $J -X PUT $B/settings/api-key -H 'Content-Type: application/json' -d '{"apiKey":"sk-ant-..."}'
curl -b $J $B/settings                               # {"apiKeyStatus":"aktiv","apiKeyLast4":"...",...}

# Klasse "entfernen" = Soft-Archiv (Planungsdaten bleiben erhalten)
curl -b $J -X DELETE $B/classes/1                     # 204, Klasse archiviert
curl -b $J "$B/classes?includeArchived=true"         # zeigt sie wieder an
```

## Projektstruktur

```
migrations/001_init.sql     Schema M1: Indizes, FTS5 + Trigger
migrations/002_auth.sql     Schema M2: sessions, user_settings
src/db.py                   Connection (WAL, FK on), FTS5-Check, Migrationsrunner
src/config.py               ENV-Konfiguration (Pfade, Auth/Cookie)
src/schemas.py              Pydantic-Modelle (camelCase-Alias)
src/deps.py                 DB-Connection + Session-Cookie-Dependency
src/lib/storage_path.py     reine NAS-Pfad-Helferfunktion
src/lib/security.py         Passwort-Hashing (argon2id), Token, AES-256-GCM
src/seed.py                 Lernbereich-Seed aus docs/lp_os_*.md
src/routers/                auth, settings + CRUD-Router je Ressource
src/main.py                 App-Factory
tests/                      pytest (Schema/FTS, Storage-Path, Seed, API-Flow, Auth, Settings, Security)
```

## Offene Punkte (in späteren Meilensteinen zu klären)

- **NAS-Pfad `{klasse}`:** In der Materialbibliothek sind Materialien nach *Klassenstufe*
  (grade) getaggt, nicht nach konkreter Klasse ("8a"). M1 nutzt daher provisorisch
  `Klasse-{grade}`. Vor M5 klären: konkrete Klasse vs. Klassenstufe im Ablagepfad.
- **Schultermine-MD-Format (M4):** vor Parser-Bau gemeinsam festlegen (BRIEFING Kap. 8.1).
- **`APP_SECRET_KEY` (Betrieb):** muss auf der Synology dauerhaft gesetzt sein – bei Verlust
  sind bereits gespeicherte API-Keys nicht mehr entschlüsselbar (dann Key neu eingeben).
