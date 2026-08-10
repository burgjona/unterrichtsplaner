-- Kalender: Zimmer-Feld je Termin, analog zum Stundenplan (TimetableEntry.room).

ALTER TABLE calendar_entries ADD COLUMN room TEXT;
