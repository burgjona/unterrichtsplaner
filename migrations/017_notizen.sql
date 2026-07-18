-- U17: Notizen ("Gedanken sammeln") – allgemein oder je Klasse, mit Autosave.
-- Soft-Archiv via archived_at (analog To-Dos/Klassen). class_id CASCADE = Notizen
-- verschwinden beim Hard-Delete der Klasse; school_year_id SET NULL überlebt Jahr-Löschung.
-- Beim Archivieren der Klasse (Soft-Delete) bleibt die Notiz erhalten und wandert ins Archiv.

CREATE TABLE notes (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  scope          TEXT NOT NULL CHECK (scope IN ('allgemein','klasse')),
  class_id       INTEGER REFERENCES classes(id) ON DELETE CASCADE,
  school_year_id INTEGER REFERENCES school_years(id) ON DELETE SET NULL,
  body_md        TEXT NOT NULL DEFAULT '',
  archived_at    TEXT,                                 -- NULL = aktiv (Soft-Delete)
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_notes_user  ON notes(user_id, archived_at);
CREATE INDEX idx_notes_class ON notes(class_id);
