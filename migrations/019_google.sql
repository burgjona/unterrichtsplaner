-- U21 Google-Kalender-Sync: Service-Account-Schlüssel (verschlüsselt) + Event-Mapping.
--
-- Der Service-Account-JSON-Schlüssel wird wie der Anthropic-Key AES-256-GCM-verschlüsselt
-- in user_settings abgelegt (nie im Klartext). google_sync_token trägt den Google-
-- nextSyncToken für inkrementellen Abgleich; google_last_sync den Zeitpunkt des letzten Syncs.

-- 1) Google-Zugangsdaten + Sync-Status je Nutzer.
ALTER TABLE user_settings ADD COLUMN google_key_cipher   BLOB;   -- verschlüsselter JSON-Schlüssel
ALTER TABLE user_settings ADD COLUMN google_key_nonce    BLOB;   -- AES-GCM-Nonce
ALTER TABLE user_settings ADD COLUMN google_calendar_id  TEXT;   -- Ziel-Kalender-ID (E-Mail o. ID)
ALTER TABLE user_settings ADD COLUMN google_key_set_at   TEXT;   -- ISO-Zeitpunkt der Hinterlegung
ALTER TABLE user_settings ADD COLUMN google_sync_token   TEXT;   -- Google nextSyncToken (inkrementell), NULL = Vollsync
ALTER TABLE user_settings ADD COLUMN google_last_sync    TEXT;   -- ISO-Zeitpunkt des letzten Syncs

-- 2) Mapping eines Kalendereintrags auf ein Google-Event.
ALTER TABLE calendar_entries ADD COLUMN google_event_id TEXT;    -- gemapptes Google-Event, NULL = nicht synchronisiert
ALTER TABLE calendar_entries ADD COLUMN google_etag     TEXT;    -- ETag des Google-Events (Änderungserkennung)

-- 3) updated_at für Last-write-wins. SQLite-ALTER erlaubt keinen datetime('now')-Default
--    (kein konstanter Ausdruck) → nullable anlegen und aus created_at backfillen; die
--    Pflege erfolgt fortan app-seitig (calendar.py setzt updated_at bei INSERT/UPDATE).
ALTER TABLE calendar_entries ADD COLUMN updated_at TEXT;
UPDATE calendar_entries SET updated_at = created_at WHERE updated_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_cal_google_event ON calendar_entries(user_id, google_event_id);
