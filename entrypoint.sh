#!/bin/sh
set -e

# FTS5 muss verfügbar sein (sonst bricht init_db mit klarer Meldung ab).
# Lehrplan-Lernbereiche einmalig seeden – idempotent (INSERT OR IGNORE).
python -m src.seed || echo "WARN: Seed übersprungen (LP-Dateien fehlen?)"

exec python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
