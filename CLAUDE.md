# Lehrer-Dashboard — Referendariat Oberschule Stolpen (Deutsch + WTH)

Planungs-Dashboard für einen einzelnen Lehrer (Single-User). Backend **FastAPI + SQLite**
(stdlib `sqlite3`, kein ORM), Frontend **Vanilla HTML/CSS/JS** in `web/` (statisch von
FastAPI ausgeliefert, API unter `/api`). Live auf Synology DS723+ (Docker) hinter
Cloudflare Tunnel.

- Verbindliche Anforderungen: `claude_code_briefing_lehrer_dashboard.md` (nur lesen)
- Bindende UI/UX-Referenz: `reference/dash_v15.html` — CSS wurde **verbatim** übernommen;
  dessen JS ist nur Prototyp, nie übernehmen.

## Arbeitsregeln (verbindlich, vom Projektleiter)

- **Bei Unklarheit stoppen und nachfragen** — keine Annahmen. Strukturentscheidungen
  (Datenmodell, Architektur) vor der Umsetzung in 2–3 Sätzen bestätigen lassen.
- **Meilensteinweise arbeiten**: kleine testbare Einheiten, Artefakte + Smoke-Test zeigen,
  **Freigabe abwarten**, erst dann weiter.
- **Kein Feature-Creep**: nur bauen, was das Briefing nennt; Extras vorschlagen, nicht bauen.
- Gezielte Patches statt Rewrites; token-/kostenbewusst arbeiten.
- NAS-/Cloudflare-Schritte führt der Nutzer aus (Sandbox erreicht das LAN nicht) —
  präzise anleiten, Fehlermeldungen anfordern, **nicht raten**.

## Befehle

```bash
./.venv/bin/python -m pytest -q                                  # alle Tests (ohne Netz)
./.venv/bin/python -m uvicorn src.main:app --reload --port 8099  # Dev-Server
./.venv/bin/python -m src.seed                                   # Lernbereich-Seed (idempotent, 62 LB)
```

Dev-Preview: `.claude/launch.json` (uvicorn auf 8097). Pflicht-ENV ab M2: `APP_SECRET_KEY`
(base64, 32 Byte; siehe `.env.example`) — Tests setzen ihn selbst (conftest).

## Konventionen

- **API camelCase, DB/Code snake_case**: Pydantic-Modelle in `src/schemas.py` erben von
  `Base` (`to_camel`-Alias, `populate_by_name`). Query-Parameter brauchen explizit
  `Query(alias="camelCase")`.
- **Nutzer-Scoping**: JEDER neue Endpunkt bekommt `user_id: int = Depends(get_user_id)`
  und filtert Queries mit `user_id` (Ausnahme: globale Lernbereich-Referenz — aber auch
  die nur angemeldet). Auth = serverseitige Session, HttpOnly-Cookie `ldb_session`.
- **Umlaute (ä/ö/ü/ß) überall erhalten** — UI, DB, Dateinamen, Exporte; nie transliterieren.
  Download-Header: ASCII-Fallback + RFC-5987 `filename*`.
- **Mobile-CSS nur in `@media`-Blöcken** (Breakpoints 1080/920/600); Desktop-Layout nie
  verändern; kein horizontales Scrollen.
- **Secrets nie im Klartext committen**: ENV-Variablen; Anthropic-API-Key AES-256-GCM in
  `user_settings`; Passwörter argon2id (`src/lib/security.py`).
- **KI** (`src/lib/ai.py`): festes Modell-Routing (Briefing Kap. 5), lokaler Prompt-Cache,
  Anthropic `cache_control`, FTS5-Top-K-Kontext statt Volltext, Kosten-Logging in `ai_usage`.
  Tests mocken `ai._make_client` — nie echte API-Calls in Tests.
- **Migrationen**: neue Datei `migrations/NNN_name.sql`; Tracker-Tabelle `schema_migrations`;
  laufen automatisch beim App-Start; Seed idempotent.
- `sqlite3.connect(..., check_same_thread=False)` + `busy_timeout` in `src/db.py` ist
  **absichtlich** (FastAPI-Threadpool) — nicht „aufräumen"; Regressionstest vorhanden.
- Storage-Pfade nur über `build_storage_path()` (`{root}/{Fach}/{Klasse-N}/{Schuljahr}/`);
  client-gelieferte Pfade müssen unter `storage_root` liegen (`_ensure_under_root`).

## Struktur (Kurzüberblick)

```
src/main.py        App-Factory (create_app), Router-Registrierung, StaticFiles(web/)
src/deps.py        get_db, get_user_id (Session-Cookie), get_storage_root, row_or_404
src/routers/       je Ressource ein Router (auth, settings, lessons, materials, ai, …)
src/lib/           security, ai, storage_path, extract (PDF→FTS), asuv_export, planning, holidays
migrations/        001_init … 007_ai (keine 005)
web/               index.html, styles.css (verbatim!), api.js, app.js — esc() für alles Dynamische
tests/             pytest; conftest: DB :memory:/tmp, Auth-Fixture, Holidays gemockt
```

## Deployment

Synology Container Manager (GUI), Named Volumes `ldb_data`/`ldb_storage`, Container läuft
als root (`user: "0:0"`, Synology-ACL-Kompromiss) — Details in `DEPLOY.md`. Update-Weg:
committen + pushen, auf der NAS ZIP aktualisieren und Projekt neu bauen (Container Manager
übernimmt YAML-Änderungen an bestehenden Projekten oft nicht → im Zweifel Projekt löschen
und mit eingefügter YAML neu anlegen).
