-- Offline-Sync (Rollout, Tranche 1, letzte Einheit): sync_log-Trigger für tropenplan_slots.
-- tropentage (Kompensationstage-Toggle) bleibt bewusst online-only, siehe stundenplan.py.

CREATE TRIGGER trg_synclog_tropenplan_slots_ai AFTER INSERT ON tropenplan_slots BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'tropenplan_slots', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_tropenplan_slots_au AFTER UPDATE ON tropenplan_slots BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'tropenplan_slots', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_tropenplan_slots_ad AFTER DELETE ON tropenplan_slots BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'tropenplan_slots', OLD.id, 'delete');
END;
