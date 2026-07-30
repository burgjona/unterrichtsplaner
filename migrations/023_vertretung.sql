-- U30 – Vertretung: einmalige (nicht wiederkehrende) Stundenplan-Einträge.
--
-- Im Unterschied zu timetable_entries (wiederkehrend über weekday/week_type/plan_id)
-- hängt ein Override an einem konkreten Datum. GET /stundenplan/resolved mergt beide
-- Quellen für die angefragte Woche (source="override" statt "plan" im Resolved-Item) –
-- das ist der in schemas.py vorbereitete Einsteckpunkt für spätere Overrides.

CREATE TABLE timetable_overrides (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date       TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  slot_id    INTEGER NOT NULL REFERENCES timetable_slots(id) ON DELETE CASCADE,
  kind_id    INTEGER NOT NULL REFERENCES timetable_kinds(id) ON DELETE RESTRICT,
  class_id   INTEGER REFERENCES classes(id) ON DELETE SET NULL,
  span_slots INTEGER NOT NULL DEFAULT 1 CHECK (span_slots BETWEEN 1 AND 12),
  label      TEXT, room TEXT, color TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_timetable_overrides_user_date ON timetable_overrides(user_id, date);
