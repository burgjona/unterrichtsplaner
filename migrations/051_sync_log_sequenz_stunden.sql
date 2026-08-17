-- Offline-Sync (Rollout, Tranche 4): sync_log-Trigger für sequenz_stunden.
-- Nur Kern-CRUD ist sync-fähig (reorder/link/apply-calendar-entry/shift bleiben Online-REST,
-- siehe Kommentar bei SYNC_HANDLER in sequenzplan.py) — die Trigger feuern trotzdem bei
-- JEDEM INSERT/UPDATE/DELETE, unabhängig vom Aufrufer, also auch bei diesen REST-Aktionen.

CREATE TRIGGER trg_synclog_sequenz_stunden_ai AFTER INSERT ON sequenz_stunden BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'sequenz_stunden', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_sequenz_stunden_au AFTER UPDATE ON sequenz_stunden BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'sequenz_stunden', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_sequenz_stunden_ad AFTER DELETE ON sequenz_stunden BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'sequenz_stunden', OLD.id, 'delete');
END;

-- Backfill: Zeilen von vor dieser Migration bekommen sonst nie einen sync_log-Eintrag.
INSERT INTO sync_log(user_id, entity_type, entity_id, op)
  SELECT user_id, 'sequenz_stunden', id, 'upsert' FROM sequenz_stunden;
