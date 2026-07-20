-- U27 – Persönlicher Stundenplan des Lehrers (nutzer-gescoped).
--
-- Fünf Tabellen: Typen (Unterricht/Aufsicht/…), Klingelraster-Slots, Pläne (mit
-- Gültigkeit ab Datum), Einträge (je Plan/Slot/Wochentag/A-B-Woche) sowie eine
-- Settings-Zeile pro Nutzer (A/B-Wochen-Parität). Alle Seeds legt der Router
-- idempotent beim ersten GET an; hier NUR CREATEs. Booleans als INTEGER 0/1,
-- Zeiten/Daten als Text (lexikographisch vergleichbar dank fester Formate).

-- 1) Termin-/Eintragstypen (Unterricht, Aufsicht, Seminar, …); genau einer ist Default.
CREATE TABLE timetable_kinds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, color TEXT NOT NULL,
  is_default INTEGER NOT NULL DEFAULT 0, sort_order INTEGER DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_timetable_kinds_user ON timetable_kinds(user_id);

-- 2) Klingelraster-Slots (Stunden + Pausen), über position sortiert; editierbar.
CREATE TABLE timetable_slots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  slot_type TEXT NOT NULL DEFAULT 'lesson' CHECK (slot_type IN ('lesson','break')),
  label TEXT NOT NULL,
  start_time TEXT NOT NULL CHECK (start_time GLOB '[0-2][0-9]:[0-5][0-9]'),
  end_time   TEXT NOT NULL CHECK (end_time   GLOB '[0-2][0-9]:[0-5][0-9]'),
  created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_timetable_slots_user ON timetable_slots(user_id, position);

-- 3) Pläne mit Gültigkeit-ab-Datum (Auflösung wählt MAX(valid_from) <= Montag).
CREATE TABLE timetable_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '',
  valid_from TEXT NOT NULL CHECK (valid_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (user_id, valid_from));
CREATE INDEX idx_timetable_plans_user ON timetable_plans(user_id);

-- 4) Einträge je Plan: Slot (Anker) + Wochentag + A/B-Woche; span_slots = Höhe.
CREATE TABLE timetable_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  plan_id INTEGER NOT NULL REFERENCES timetable_plans(id) ON DELETE CASCADE,
  slot_id INTEGER NOT NULL REFERENCES timetable_slots(id) ON DELETE CASCADE,
  kind_id INTEGER NOT NULL REFERENCES timetable_kinds(id) ON DELETE RESTRICT,
  class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL,
  weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 4),
  week_type TEXT NOT NULL DEFAULT 'both' CHECK (week_type IN ('both','A','B')),
  span_slots INTEGER NOT NULL DEFAULT 1 CHECK (span_slots BETWEEN 1 AND 12),
  label TEXT, room TEXT, color TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_timetable_entries_plan ON timetable_entries(plan_id);
CREATE INDEX idx_timetable_entries_user ON timetable_entries(user_id);

-- 5) Settings-Zeile je Nutzer: welche ISO-Wochen-Parität die A-Woche ist.
CREATE TABLE timetable_settings (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  week_a_parity TEXT NOT NULL DEFAULT 'odd' CHECK (week_a_parity IN ('odd','even')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')));
