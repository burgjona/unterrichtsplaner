-- Archiv (Soft-Delete) für Materialien und Kalendereinträge, analog Klassen/To-Dos/Notizen.
-- DELETE bleibt endgültiges Löschen (im Archiv-Bereich nutzbar); POST /archive setzt
-- archived_at, POST /restore hebt es wieder auf. GET-Listen zeigen standardmäßig nur
-- nicht-archivierte Einträge.

ALTER TABLE materials ADD COLUMN archived_at TEXT;
CREATE INDEX idx_materials_archived ON materials(user_id, archived_at);

ALTER TABLE calendar_entries ADD COLUMN archived_at TEXT;
CREATE INDEX idx_cal_archived ON calendar_entries(user_id, archived_at);
