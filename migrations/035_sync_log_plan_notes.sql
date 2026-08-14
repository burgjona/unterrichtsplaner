-- Offline-Sync (Rollout, Tranche 1): sync_log-Trigger für plan_notes.

CREATE TRIGGER trg_synclog_plan_notes_ai AFTER INSERT ON plan_notes BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'plan_notes', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_plan_notes_au AFTER UPDATE ON plan_notes BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'plan_notes', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_plan_notes_ad AFTER DELETE ON plan_notes BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'plan_notes', OLD.id, 'delete');
END;
