-- Offline-Sync: Backfill für sync_log bei allen bislang migrierten Entitäten.
--
-- Root Cause des Bugs "Klasse/Block-Dropdown in Stoffverteilungsplan/Sequenzplanung leer":
-- die trg_synclog_*-Trigger (031-042) feuern nur bei INSERT/UPDATE/DELETE ab dem Zeitpunkt
-- ihrer eigenen Migration. Zeilen, die VOR der jeweiligen Migration bereits existierten,
-- bekamen nie einen sync_log-Eintrag und blieben beim initialen Full-Sync (since=0) für
-- den Client unsichtbar — SyncEngine.materialize("classes") kam leer zurück, state.classes
-- blieb [] und damit auch jedes davon abgeleitete Dropdown.
--
-- Fix: für jede sync-fähige Tabelle einmalig alle bestehenden Zeilen als 'upsert' nachtragen.
-- Reihenfolge/Zeitpunkt der seq-Vergabe ist irrelevant (kein Konflikt mit künftigen echten
-- Änderungen), Duplikate für bereits nach ihrer Migration aktualisierte Zeilen sind harmlos.

INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'notes', id, 'upsert' FROM notes;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'todos', id, 'upsert' FROM todos;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'calendar_categories', id, 'upsert' FROM calendar_categories;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'school_years', id, 'upsert' FROM school_years;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'plan_notes', id, 'upsert' FROM plan_notes;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'timetable_kinds', id, 'upsert' FROM timetable_kinds;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'timetable_slots', id, 'upsert' FROM timetable_slots;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'tropenplan_slots', id, 'upsert' FROM tropenplan_slots;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'classes', id, 'upsert' FROM classes;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'students', id, 'upsert' FROM students;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'timetable_plans', id, 'upsert' FROM timetable_plans;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'lessons', id, 'upsert' FROM lessons;
