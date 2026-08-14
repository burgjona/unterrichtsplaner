-- Offline-Sync (Rollout, Tranche 1): sync_log-Trigger für timetable_kinds.

CREATE TRIGGER trg_synclog_timetable_kinds_ai AFTER INSERT ON timetable_kinds BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'timetable_kinds', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_timetable_kinds_au AFTER UPDATE ON timetable_kinds BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'timetable_kinds', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_timetable_kinds_ad AFTER DELETE ON timetable_kinds BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'timetable_kinds', OLD.id, 'delete');
END;
