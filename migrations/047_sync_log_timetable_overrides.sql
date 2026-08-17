-- Offline-Sync (Rollout, Tranche 3): sync_log-Trigger für timetable_overrides.
-- Kein Update-Konzept (auch im REST kein PUT) — nur INSERT/DELETE-Trigger nötig.

CREATE TRIGGER trg_synclog_timetable_overrides_ai AFTER INSERT ON timetable_overrides BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'timetable_overrides', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_timetable_overrides_ad AFTER DELETE ON timetable_overrides BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'timetable_overrides', OLD.id, 'delete');
END;

-- Backfill: Zeilen von vor dieser Migration bekommen sonst nie einen sync_log-Eintrag
-- (vgl. 043_sync_log_backfill.sql/046_sync_log_backfill_2.sql).
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'timetable_overrides', id, 'upsert' FROM timetable_overrides;
