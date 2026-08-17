-- Offline-Sync (Rollout, Tranche 4): sync_log-Trigger für reflections.
-- Nur INSERT-Trigger nötig (kein Update/Delete-Konzept, reine Journal-Entität).

CREATE TRIGGER trg_synclog_reflections_ai AFTER INSERT ON reflections BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'reflections', NEW.id, 'upsert');
END;

-- Backfill: Zeilen von vor dieser Migration bekommen sonst nie einen sync_log-Eintrag.
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'reflections', id, 'upsert' FROM reflections;
