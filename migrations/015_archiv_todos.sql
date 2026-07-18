-- Meilenstein 12 – U13: Archiv-Infrastruktur
-- To-Dos werden nicht mehr hart gelöscht, sondern soft-archiviert (archived_at gesetzt).
-- Das ✕ im Heute-View archiviert; endgültiges Löschen bleibt über DELETE erhalten (im Archiv).

ALTER TABLE todos ADD COLUMN archived_at TEXT;
CREATE INDEX idx_todos_archived ON todos(user_id, archived_at);
