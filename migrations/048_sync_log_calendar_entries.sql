-- Offline-Sync (Rollout, Tranche 3 — letzte Einheit): sync_log-Trigger für calendar_entries.
-- class_ids (calendar_entry_classes) sind eingebettet im Payload (kein eigener entity_type,
-- analog stoff_plan_blocks). 'delete' bildet auf Soft-Archiv ab (siehe SYNC_HANDLER-Kommentar
-- in calendar.py), Hard-Delete/restore bleiben online-only.

-- Manche Schreibpfade (google_cal.py, lessons.py::_sync_calendar_entry, sequenzplan.py) haben
-- bislang nie updated_at gesetzt — ältere Zeilen können daher NULL haben, was die
-- Optimistic-Concurrency-Konflikterkennung falsch auslösen würde (jeder Push sähe dann einen
-- Konflikt gegen NULL). Backfill vor den Triggern.
UPDATE calendar_entries SET updated_at = created_at WHERE updated_at IS NULL;

CREATE TRIGGER trg_synclog_calendar_entries_ai AFTER INSERT ON calendar_entries BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'calendar_entries', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_calendar_entries_au AFTER UPDATE ON calendar_entries BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'calendar_entries', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_calendar_entries_ad AFTER DELETE ON calendar_entries BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'calendar_entries', OLD.id, 'delete');
END;

-- Backfill: Zeilen von vor dieser Migration bekommen sonst nie einen sync_log-Eintrag.
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'calendar_entries', id, 'upsert' FROM calendar_entries;
