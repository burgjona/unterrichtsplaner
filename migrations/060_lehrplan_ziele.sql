-- Lehrplan-Abhakmodul, Teil 1: Referenz der "Ziele der Klassenstufe".
-- Analog zu lernbereiche (global, geseedet, nicht nutzer-gescoped): die 3-5
-- fettgesetzten Kompetenzbereich-Ueberschriften aus dem "Ziele"-Block je
-- Klassenstufe der Lehrplan-Dateien (docs/lp_os_*.md). Kuratierte Liste in
-- src/seed.py, da die LP-Detailkapitel OCR-bedingt nicht sauber parsbar sind.
-- Je (subject, grade, track) eine Zeile pro Ziel; scope folgt lernbereiche.

CREATE TABLE lehrplan_ziele (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  subject    TEXT NOT NULL CHECK (subject IN ('Deutsch','WTH')),
  grade      INTEGER NOT NULL,
  track      TEXT NOT NULL,                 -- 'RS'|'HS' (Deutsch ab 7), sonst 'gemischt'
  code       TEXT NOT NULL,                 -- "Z1", "Z2", ...
  text       TEXT NOT NULL,                 -- Kompetenzbereich-Ueberschrift
  sort_order INTEGER NOT NULL DEFAULT 0,
  source     TEXT,                          -- Provenienz "lp_os_deutsch_2019"
  UNIQUE(subject, grade, track, code)
);
CREATE INDEX idx_lehrplan_ziele_lookup ON lehrplan_ziele(subject, grade, track);
