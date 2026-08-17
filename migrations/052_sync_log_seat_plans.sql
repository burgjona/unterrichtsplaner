-- Offline-Sync (Rollout, Tranche 4 — letzte Einheit): sync_log-Trigger für seat_plans.

CREATE TRIGGER trg_synclog_seat_plans_ai AFTER INSERT ON seat_plans BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'seat_plans', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_seat_plans_au AFTER UPDATE ON seat_plans BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'seat_plans', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_seat_plans_ad AFTER DELETE ON seat_plans BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'seat_plans', OLD.id, 'delete');
END;

-- Backfill: Zeilen von vor dieser Migration bekommen sonst nie einen sync_log-Eintrag.
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'seat_plans', id, 'upsert' FROM seat_plans;
