-- Meilenstein 3 – Reflexionen & To-dos (Prototyp-Funktionen gegen SQLite)

-- "Reflexion übersprungen" (z. B. Vertretungsstunde) direkt an der Stunde.
ALTER TABLE lessons ADD COLUMN reflection_skipped INTEGER NOT NULL DEFAULT 0;

-- Reflexionsjournal: Meyer-Ist-Werte (tatsächlich beobachtet) + Freitext, pro Stunde.
CREATE TABLE reflections (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id      INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  meyer_ist_json TEXT,                 -- JSON-Array[10] Ampelwerte
  ampel_summary  TEXT,                 -- z. B. "7 grün / 2 gelb / 1 rot"
  text           TEXT,
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_reflections_user   ON reflections(user_id);
CREATE INDEX idx_reflections_lesson ON reflections(lesson_id);

-- To-dos der Heute-Ansicht (Quelle system = automatisch erzeugt, manuell = vom Nutzer).
CREATE TABLE todos (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text       TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'manuell' CHECK (source IN ('system','manuell')),
  done       INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_todos_user ON todos(user_id);
