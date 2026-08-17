-- Offline-Sync (Rollout, Tranche 1): sync_log-Trigger für timetable_slots.

CREATE TRIGGER trg_synclog_timetable_slots_ai AFTER INSERT ON timetable_slots BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'timetable_slots', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_timetable_slots_au AFTER UPDATE ON timetable_slots BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'timetable_slots', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_timetable_slots_ad AFTER DELETE ON timetable_slots BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'timetable_slots', OLD.id, 'delete');
END;
