-- Offline-Sync (Rollout, Tranche 2): sync_log-Trigger für classes.

CREATE TRIGGER trg_synclog_classes_ai AFTER INSERT ON classes BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'classes', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_classes_au AFTER UPDATE ON classes BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'classes', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_classes_ad AFTER DELETE ON classes BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'classes', OLD.id, 'delete');
END;
