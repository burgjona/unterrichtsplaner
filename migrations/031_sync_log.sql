-- Offline-Sync (Fundament, Teil 2): generisches Sync-Log als Cursor UND Tombstone.
--
-- Jede Änderung an einer sync-fähigen Tabelle schreibt eine Zeile hierher (op='upsert' bei
-- INSERT/UPDATE, op='delete' bei DELETE). Ein Client fragt "was hat sich seit seq X geändert"
-- ab (GET /api/sync/changes) statt Timestamps zu vergleichen (Sekundenauflösung wäre bei
-- mehreren Tabellen im selben Fenster mehrdeutig). Eine op='delete'-Zeile ist gleichzeitig
-- der Tombstone: ohne sie wäre eine serverseitig hart gelöschte Zeile für einen Offline-
-- Client, der sie vorher gesehen hat, nicht von "nie existiert" zu unterscheiden.
--
-- Befüllung per Trigger statt App-Code (analog material_chunks_fts-Sync-Trigger in
-- 001_init.sql) — kein Router kann das Loggen vergessen. Diese Migration legt die Trigger
-- nur für 'notes' an (Fundament-Beweis-Entität); jede Rollout-Einheit ergänzt für ihre
-- Tabelle drei eigene Trigger in einer eigenen kleinen Migration (032_sync_log_<entity>.sql).

CREATE TABLE sync_log (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL,
  entity_type TEXT    NOT NULL,
  entity_id   INTEGER NOT NULL,
  op          TEXT    NOT NULL CHECK (op IN ('upsert','delete')),
  changed_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_sync_log_user_seq ON sync_log(user_id, seq);

CREATE TRIGGER trg_synclog_notes_ai AFTER INSERT ON notes BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'notes', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_notes_au AFTER UPDATE ON notes BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'notes', NEW.id, 'upsert');
END;

CREATE TRIGGER trg_synclog_notes_ad AFTER DELETE ON notes BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'notes', OLD.id, 'delete');
END;
