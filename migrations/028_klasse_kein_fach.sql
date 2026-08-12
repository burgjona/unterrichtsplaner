-- Erlaubt Klassen ohne festes Fach (z. B. stellvertretende Klassenleitung), die einzelne
-- Stunden in mehreren Fächern geplant bekommen. Die CHECK-Constraint auf classes.subject
-- erlaubte bisher nur 'Deutsch'/'WTH' und ließ das Frontend-Angebot "kein Fach" (Commit 24c2346)
-- mit einem 500er auflaufen. SQLite kann CHECK-Constraints nicht per ALTER ändern → Table-Rebuild.
PRAGMA foreign_keys = OFF;

CREATE TABLE classes_new (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  school_year_id      INTEGER REFERENCES school_years(id) ON DELETE SET NULL,
  name                TEXT NOT NULL,
  subject             TEXT NOT NULL CHECK (subject IN ('Deutsch','WTH','kein Fach')),
  grade               INTEGER NOT NULL,
  track               TEXT,
  weekly_hours        INTEGER NOT NULL DEFAULT 2,
  parallel_group      TEXT,
  visible_in_calendar INTEGER NOT NULL DEFAULT 1,
  archived_at         TEXT,
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO classes_new SELECT * FROM classes;
DROP TABLE classes;
ALTER TABLE classes_new RENAME TO classes;
CREATE INDEX idx_classes_user ON classes(user_id, archived_at);

PRAGMA foreign_keys = ON;
