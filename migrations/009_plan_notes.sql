-- Meilenstein 11 – Freitext-Ideen für den Jahresplan (Stoffverteilungsplan).
-- Pro Klasse + Schuljahr ein Notizfeld; die KI-Stoffplan-Generierung liest es und
-- behandelt die Hinweise mit Vorrang vor den Standardregeln.

CREATE TABLE plan_notes (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id       INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  school_year_id INTEGER NOT NULL REFERENCES school_years(id) ON DELETE CASCADE,
  text           TEXT NOT NULL DEFAULT '',
  updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, class_id, school_year_id)
);
CREATE INDEX idx_plan_notes_scope ON plan_notes(user_id, class_id, school_year_id);
