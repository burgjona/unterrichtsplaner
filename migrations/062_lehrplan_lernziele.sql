-- Lehrplan-Abhakmodul, Teil 3: die "grossen Lernziele" je Lernbereich.
-- Im saechsischen Lehrplan die linke Spalte der LB-Tabelle ("Kennen von ...",
-- "Beherrschen ...", "Anwenden von ...", "Beurteilen ...", "Sich positionieren ...",
-- "Uebertragen ...", "Einblick gewinnen in ...", "Gestalten ...", "Problemloesen ...").
-- Wird per KI aus lernbereiche.detail_md extrahiert (OCR-Rohtext, Spalten ineinander
-- geflossen -> Regex zu unzuverlaessig). Globale Referenz, nicht nutzer-gescoped.

CREATE TABLE lehrplan_lernziele (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  lernbereich_id INTEGER NOT NULL REFERENCES lernbereiche(id) ON DELETE CASCADE,
  sort_order     INTEGER NOT NULL DEFAULT 0,
  anforderung    TEXT,                 -- Anforderungsverb ("Kennen", "Beherrschen", ...)
  text           TEXT NOT NULL,        -- vollstaendige Lernziel-Ueberschrift
  inhalte        TEXT,                 -- zugehoerige Anstriche, "; "-getrennt
  source         TEXT DEFAULT 'ki',
  UNIQUE(lernbereich_id, sort_order)
);
CREATE INDEX idx_lehrplan_lernziele_lb ON lehrplan_lernziele(lernbereich_id);

-- lehrplan_checks: item_type um 'lernziel' erweitern. SQLite kann CHECK nicht per ALTER
-- aendern -> Table-Rebuild. lehrplan_checks (061) ist neu, ohne Trigger/FTS/Querverweise,
-- der Rebuild ist daher unkritisch (vgl. Muster 032, dort nur wegen Trigger heikel).
PRAGMA foreign_keys = OFF;

CREATE TABLE lehrplan_checks_new (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  item_type  TEXT NOT NULL CHECK (item_type IN ('ziel','lb','lernziel')),
  item_ref   INTEGER NOT NULL,
  checked_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, class_id, item_type, item_ref)
);
INSERT INTO lehrplan_checks_new SELECT * FROM lehrplan_checks;
DROP TABLE lehrplan_checks;
ALTER TABLE lehrplan_checks_new RENAME TO lehrplan_checks;
CREATE INDEX idx_lehrplan_checks_scope ON lehrplan_checks(user_id, class_id);

PRAGMA foreign_keys = ON;
