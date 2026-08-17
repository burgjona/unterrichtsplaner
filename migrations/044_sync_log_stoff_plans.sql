-- Offline-Sync (Rollout, Tranche 3): sync_log-Trigger für stoff_plans.
-- stoff_plan_blocks sind eingebettet im stoff_plans-Payload (kein eigener entity_type,
-- analog lesson_phases/lesson_lernziele bei lessons) — Trigger genügen auf stoff_plans selbst.

CREATE TRIGGER trg_synclog_stoff_plans_ai AFTER INSERT ON stoff_plans BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'stoff_plans', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_stoff_plans_au AFTER UPDATE ON stoff_plans BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'stoff_plans', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_stoff_plans_ad AFTER DELETE ON stoff_plans BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'stoff_plans', OLD.id, 'delete');
END;
