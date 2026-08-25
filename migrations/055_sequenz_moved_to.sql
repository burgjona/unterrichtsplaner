-- "Stunde verschieben" im Planungskalender: die verschobene Sequenzstunde bekommt eine neue,
-- verknüpfte Zeile am Zielort (eigene Karte im Sequenzplan); die Ursprungszeile bleibt stehen
-- und zeigt per moved_to_id auf die neue Zeile ("verschoben nach ..."-Hinweis in der UI).
-- ON DELETE SET NULL: wird die Zielzeile später gelöscht, verliert die Ursprungszeile nur den
-- Verweis (kein Kaskadenlöschen der Ursprungszeile).

ALTER TABLE sequenz_stunden ADD COLUMN moved_to_id INTEGER REFERENCES sequenz_stunden(id) ON DELETE SET NULL;
