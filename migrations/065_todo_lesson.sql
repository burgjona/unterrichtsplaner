-- To-dos, die beim Planen einer Stunde entstehen ("AB kopieren", "Hörbeispiel suchen"),
-- hängen jetzt wirklich an dieser Stunde statt nur allgemein auf der Startseite zu landen.
--
-- Bewusst NICHT hefter_lesson_id mitbenutzt: das trägt einen partiellen UNIQUE-Index
-- (genau ein "Heftereintrag nachpflegen"-To-do je Stunde) und eine eigene Bedeutung –
-- ein zweites Planungs-To-do zur selben Stunde würde daran scheitern.
--
-- Kein ON DELETE CASCADE (ALTER TABLE ADD COLUMN kann keine Fremdschlüssel nachrüsten,
-- ein Table-Rebuild wäre hier das größere Risiko, vgl. 059): wird die Stunde gelöscht,
-- bleibt das To-do als gewöhnlicher Eintrag stehen. Das ist auch gewollt – eine erledigte
-- Vorbereitung soll nicht mit der Stunde verschwinden. Der Client zeigt es dann ohne Link.

ALTER TABLE todos ADD COLUMN lesson_id INTEGER;
CREATE INDEX idx_todos_lesson ON todos(user_id, lesson_id) WHERE lesson_id IS NOT NULL;
