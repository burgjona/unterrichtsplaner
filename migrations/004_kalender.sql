-- Meilenstein 4 – Kalender-Automatik & Jahresplanung

-- Einzelstunde auf konkreten Tag terminierbar → erzeugt einen Auto-Kalendereintrag.
ALTER TABLE lessons ADD COLUMN date TEXT;   -- ISO YYYY-MM-DD, NULL = noch nicht terminiert

-- Kennzeichnung automatisch (aus einer Stunde) erzeugter Kalendereinträge.
ALTER TABLE calendar_entries ADD COLUMN auto_generated INTEGER NOT NULL DEFAULT 0;

-- Ferien & Feiertage Sachsen (einmalig aus öffentlicher API abgerufen, lokal gespeichert).
CREATE TABLE school_dates (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  school_year_id INTEGER NOT NULL REFERENCES school_years(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL CHECK (kind IN ('feiertag','ferien')),
  name           TEXT NOT NULL,
  start_date     TEXT NOT NULL,        -- YYYY-MM-DD
  end_date       TEXT NOT NULL,        -- YYYY-MM-DD (= start_date bei Feiertag)
  source         TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(school_year_id, kind, name, start_date)
);
CREATE INDEX idx_school_dates_year  ON school_dates(school_year_id);
CREATE INDEX idx_school_dates_range ON school_dates(user_id, start_date, end_date);
