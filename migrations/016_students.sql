-- U14: Schüler-Namensliste je Klasse (Basis für späteren Sitzplan).
-- Bewusst minimal: nur Name + Reihenfolge. class_id CASCADE = Schüler verschwinden
-- beim Hard-Delete der Klasse mit; user_id für nutzergescopte Abfragen.

CREATE TABLE students (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_students_class ON students(class_id);
CREATE INDEX idx_students_user  ON students(user_id);
