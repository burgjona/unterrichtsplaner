-- Automatische To-dos "Heftereintrag nachpflegen": verknüpfen einen system-To-do mit der
-- Stunde, deren hefteintrag-Feld nach Stundenende noch leer ist. Kein neuer source-Wert
-- (CHECK auf todos.source bleibt 'system'/'manuell', kein riskanter Table-Rebuild) -
-- ein Hefter-To-do ist schlicht ein system-To-do mit gesetztem hefter_lesson_id.
-- Der Client (reconcileHefterTodos) legt sie an und archiviert sie wieder, sobald das
-- Feld gefüllt ist. Der partielle Unique-Index verhindert Doppelanlage (auch geräteübergrei-
-- fend / bei Sync-Races); ein einmal archivierter Hefter-To-do blockiert die Neuanlage.

ALTER TABLE todos ADD COLUMN hefter_lesson_id INTEGER;
CREATE UNIQUE INDEX idx_todos_hefter_lesson ON todos(user_id, hefter_lesson_id)
  WHERE hefter_lesson_id IS NOT NULL;
