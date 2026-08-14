-- Offline-Sync (Rollout, Tranche 1): sync_log-Trigger für school_years.

CREATE TRIGGER trg_synclog_school_years_ai AFTER INSERT ON school_years BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'school_years', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_school_years_au AFTER UPDATE ON school_years BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'school_years', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_school_years_ad AFTER DELETE ON school_years BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'school_years', OLD.id, 'delete');
END;
