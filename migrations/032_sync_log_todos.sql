-- Offline-Sync (Rollout, Tranche 1): sync_log-Trigger für todos — Vorbild 031_sync_log.sql.

CREATE TRIGGER trg_synclog_todos_ai AFTER INSERT ON todos BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'todos', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_todos_au AFTER UPDATE ON todos BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'todos', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_todos_ad AFTER DELETE ON todos BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'todos', OLD.id, 'delete');
END;
