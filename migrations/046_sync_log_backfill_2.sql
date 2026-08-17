-- Offline-Sync: Backfill für sync_log bei Entitäten, die NACH der ersten Backfill-Migration
-- (043_sync_log_backfill.sql) hinzugekommen sind (stoff_plans in 044, timetable_entries in
-- 045) — sonst derselbe Bug wie dort beschrieben: Zeilen von vor der jeweiligen Migration
-- bleiben beim initialen Full-Sync unsichtbar.

INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'stoff_plans', id, 'upsert' FROM stoff_plans;
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'timetable_entries', id, 'upsert' FROM timetable_entries;
