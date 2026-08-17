-- Offline-Sync (Rollout, Tranche 4): sync_log-Trigger für asuv_drafts.
-- Kein Delete-Konzept (kein DELETE im REST) — nur INSERT/UPDATE-Trigger.
-- entity_id im generischen Sync-Protokoll = lesson_id (Primärschlüssel dieser Tabelle).

CREATE TRIGGER trg_synclog_asuv_drafts_ai AFTER INSERT ON asuv_drafts BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'asuv_drafts', NEW.lesson_id, 'upsert');
END;

CREATE TRIGGER trg_synclog_asuv_drafts_au AFTER UPDATE ON asuv_drafts BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'asuv_drafts', NEW.lesson_id, 'upsert');
END;

-- Backfill: Zeilen von vor dieser Migration bekommen sonst nie einen sync_log-Eintrag.
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'asuv_drafts', lesson_id, 'upsert' FROM asuv_drafts;
