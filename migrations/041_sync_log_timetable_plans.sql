-- Offline-Sync (Rollout, Tranche 2): sync_log-Trigger für timetable_plans.

CREATE TRIGGER trg_synclog_timetable_plans_ai AFTER INSERT ON timetable_plans BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'timetable_plans', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_timetable_plans_au AFTER UPDATE ON timetable_plans BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'timetable_plans', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_timetable_plans_ad AFTER DELETE ON timetable_plans BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'timetable_plans', OLD.id, 'delete');
END;
