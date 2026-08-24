-- Bugfix: automatisch aus lessons erzeugte Kalendereinträge (lessons.py::_sync_calendar_entry)
-- haben bislang nie all_day/start_time/end_time gesetzt bekommen -> im Kalender erschienen
-- terminierte Stunden mit Uhrzeit immer als ganztägig. Backfill für Bestandsdaten; der
-- Schreibpfad selbst wurde in _sync_calendar_entry korrigiert.
UPDATE calendar_entries
SET all_day = 0,
    start_time = (SELECT l.time FROM lessons l WHERE l.id = calendar_entries.lesson_id),
    end_time = (
      SELECT
        substr('0' || ((CAST(substr(l.time,1,2) AS INTEGER) * 60 + CAST(substr(l.time,4,2) AS INTEGER) + COALESCE(l.duration_minutes, 45)) / 60), -2, 2)
        || ':' ||
        substr('0' || ((CAST(substr(l.time,1,2) AS INTEGER) * 60 + CAST(substr(l.time,4,2) AS INTEGER) + COALESCE(l.duration_minutes, 45)) % 60), -2, 2)
      FROM lessons l WHERE l.id = calendar_entries.lesson_id
    )
WHERE auto_generated = 1
  AND lesson_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM lessons l WHERE l.id = calendar_entries.lesson_id AND l.time IS NOT NULL);
