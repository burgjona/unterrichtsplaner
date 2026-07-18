-- U11 Kalender-Kern: Zeitmodell erweitern + Termin-Kategorien

-- 1) Zeitmodell: mehrtägige Termine + Uhrzeiten. Abwärtskompatibel:
--    Bestandstermine bleiben ganztägig/eintägig (all_day = 1, Zeiten NULL).
ALTER TABLE calendar_entries ADD COLUMN end_date   TEXT;              -- ISO YYYY-MM-DD, NULL = eintägig
ALTER TABLE calendar_entries ADD COLUMN start_time TEXT;              -- "HH:MM", NULL = ganztägig
ALTER TABLE calendar_entries ADD COLUMN end_time   TEXT;             -- "HH:MM", NULL
ALTER TABLE calendar_entries ADD COLUMN all_day    INTEGER NOT NULL DEFAULT 1;

-- 2) Termin-Kategorien (nutzer-gescoped, unabhängig von entry_type).
CREATE TABLE calendar_categories (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  color      TEXT NOT NULL,
  sort_order INTEGER DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_calendar_categories_user ON calendar_categories(user_id);

-- Kategorie-Zuordnung am Termin (nullable, beim Löschen der Kategorie auf NULL).
ALTER TABLE calendar_entries ADD COLUMN category_id INTEGER REFERENCES calendar_categories(id) ON DELETE SET NULL;
