-- Offline-Sync (Rollout, Tranche 3): sync_log-Trigger für lessons.
-- lesson_phases/lesson_lernziele sind eingebettet im lessons-Payload (Nutzer-Entscheidung,
-- kein eigener entity_type) — deshalb genügen Trigger auf der lessons-Tabelle selbst;
-- _apply_update_lesson bumpt updated_at bewusst auch bei reinen Kind-Tabellen-Änderungen.

CREATE TRIGGER trg_synclog_lessons_ai AFTER INSERT ON lessons BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'lessons', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_lessons_au AFTER UPDATE ON lessons BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'lessons', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_lessons_ad AFTER DELETE ON lessons BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'lessons', OLD.id, 'delete');
END;
