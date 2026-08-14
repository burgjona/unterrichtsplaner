-- Offline-Sync (Fundament, Teil 1): updated_at auf allen editierbaren Tabellen, die noch
-- keins haben — Basis für Optimistic-Concurrency beim Sync-Push (vgl. 019_google.sql).
--
-- SQLite-ALTER erlaubt keinen datetime('now')-Default (kein konstanter Ausdruck) → nullable
-- anlegen und aus created_at backfillen; die Pflege erfolgt fortan app-seitig in den
-- jeweiligen Routern (UPDATE ... SET updated_at = datetime('now') analog notes.py).

ALTER TABLE school_years ADD COLUMN updated_at TEXT;
UPDATE school_years SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE todos ADD COLUMN updated_at TEXT;
UPDATE todos SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE school_dates ADD COLUMN updated_at TEXT;
UPDATE school_dates SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE calendar_categories ADD COLUMN updated_at TEXT;
UPDATE calendar_categories SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE students ADD COLUMN updated_at TEXT;
UPDATE students SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE timetable_kinds ADD COLUMN updated_at TEXT;
UPDATE timetable_kinds SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE timetable_slots ADD COLUMN updated_at TEXT;
UPDATE timetable_slots SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE timetable_plans ADD COLUMN updated_at TEXT;
UPDATE timetable_plans SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE timetable_overrides ADD COLUMN updated_at TEXT;
UPDATE timetable_overrides SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE tropenplan_slots ADD COLUMN updated_at TEXT;
UPDATE tropenplan_slots SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE tropentage ADD COLUMN updated_at TEXT;
UPDATE tropentage SET updated_at = created_at WHERE updated_at IS NULL;
