-- Offline-Sync (Rollout, Tranche 1): sync_log-Trigger für calendar_categories.

CREATE TRIGGER trg_synclog_calendar_categories_ai AFTER INSERT ON calendar_categories BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'calendar_categories', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_calendar_categories_au AFTER UPDATE ON calendar_categories BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'calendar_categories', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_calendar_categories_ad AFTER DELETE ON calendar_categories BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'calendar_categories', OLD.id, 'delete');
END;
