-- Abwesenheiten (Krank / Frei / Fortbildung / Exkursion / Kur / Dienstreise).
--
-- Ein Datensatz je zusammenhängendem Zeitraum (Einzeltag: end_date = start_date). Der
-- Stundenplan selbst bleibt unverändert -- eine Abwesenheit verschiebt ausschliesslich die
-- bereits terminierten Sequenzstunden der betroffenen Klassen nach hinten (blockuebergreifend
-- bis zum Schuljahresende, siehe src/routers/absences.py).
--
-- Nummer 064 statt 063: 063 ist auf dem noch nicht gemergten Zweig feat/musik vergeben.

CREATE TABLE absences (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  start_date TEXT NOT NULL CHECK (start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  end_date   TEXT NOT NULL CHECK (end_date   GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  kind       TEXT NOT NULL CHECK (kind IN ('krank','frei','fortbildung','exkursion','kur','dienstreise')),
  note       TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (end_date >= start_date)
);
CREATE INDEX idx_absences_user_range ON absences(user_id, start_date, end_date);

-- Verschiebe-Protokoll: Grundlage für das automatische Zurückrollen beim Löschen der
-- Abwesenheit. Zurückgesetzt wird nur, was seither nicht von Hand geändert wurde -- deshalb
-- wird neben old_* auch new_* festgehalten (Vergleich mit dem Ist-Zustand).
CREATE TABLE absence_shifts (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  absence_id        INTEGER NOT NULL REFERENCES absences(id) ON DELETE CASCADE,
  user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sequenz_stunde_id INTEGER NOT NULL REFERENCES sequenz_stunden(id) ON DELETE CASCADE,
  lesson_id         INTEGER REFERENCES lessons(id) ON DELETE CASCADE,
  old_date          TEXT,
  old_time          TEXT,
  new_date          TEXT,
  new_time          TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_absence_shifts_absence ON absence_shifts(absence_id);

-- Automatischer (ganztägiger, ein- oder mehrtägiger) Kalendereintrag je Abwesenheit.
-- ON DELETE CASCADE: Abwesenheit weg -> Eintrag weg.
ALTER TABLE calendar_entries ADD COLUMN absence_id INTEGER REFERENCES absences(id) ON DELETE CASCADE;
CREATE INDEX idx_cal_absence ON calendar_entries(absence_id);
