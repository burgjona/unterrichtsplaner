-- U27d – Tropenplan (verkürzter Unterricht an heißen Tagen), nutzer-gescoped.
--
-- Zwei Tabellen: ein eigenes, editierbares Klingelraster für den Tropenplan
-- (Schema analog timetable_slots, zusätzlich `covers` – wie viele aufeinander-
-- folgende normale Unterrichtsstunden dieser Tropen-Slot zeitlich zusammenfasst,
-- z. B. 2 für die zusammengelegte 7./8. Stunde) sowie eine Tabelle der konkret
-- markierten Tropentage (Datum). Die inhaltliche Zuordnung (welche Klasse/welches
-- Fach) bleibt unverändert der normale Plan – nur die Uhrzeiten weichen an
-- Tropentagen ab; das Mapping geschieht über die Reihenfolge der 'lesson'-Slots.

CREATE TABLE tropenplan_slots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  slot_type TEXT NOT NULL DEFAULT 'lesson' CHECK (slot_type IN ('lesson','break')),
  label TEXT NOT NULL,
  start_time TEXT NOT NULL CHECK (start_time GLOB '[0-2][0-9]:[0-5][0-9]'),
  end_time   TEXT NOT NULL CHECK (end_time   GLOB '[0-2][0-9]:[0-5][0-9]'),
  covers INTEGER NOT NULL DEFAULT 1 CHECK (covers BETWEEN 1 AND 4),
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_tropenplan_slots_user ON tropenplan_slots(user_id, position);

CREATE TABLE tropentage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (user_id, date));
CREATE INDEX idx_tropentage_user ON tropentage(user_id, date);
