-- Offline-Sync (Rollout, Tranche 3): sync_log-Trigger für timetable_entries.

CREATE TRIGGER trg_synclog_timetable_entries_ai AFTER INSERT ON timetable_entries BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'timetable_entries', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_timetable_entries_au AFTER UPDATE ON timetable_entries BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'timetable_entries', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_timetable_entries_ad AFTER DELETE ON timetable_entries BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'timetable_entries', OLD.id, 'delete');
END;
