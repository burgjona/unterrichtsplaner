-- Offline-Sync (Rollout, Tranche 2): sync_log-Trigger für students.

CREATE TRIGGER trg_synclog_students_ai AFTER INSERT ON students BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'students', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_students_au AFTER UPDATE ON students BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'students', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_students_ad AFTER DELETE ON students BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'students', OLD.id, 'delete');
END;
