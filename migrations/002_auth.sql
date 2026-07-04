-- Meilenstein 2 – Authentifizierung & Einstellungen

-- Server-seitige Sessions: opaker Token im HttpOnly-Cookie, sofort widerrufbar.
CREATE TABLE sessions (
  token        TEXT PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at   TEXT NOT NULL,
  last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_sessions_user ON sessions(user_id);

-- Nutzereinstellungen: Anthropic-API-Key AES-256-GCM-verschlüsselt (nie Klartext).
-- Nur die letzten 4 Zeichen werden zur Anzeige/Statusprüfung im Klartext gehalten.
CREATE TABLE user_settings (
  user_id              INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  anthropic_key_cipher BLOB,
  anthropic_key_nonce  BLOB,
  anthropic_key_last4  TEXT,
  anthropic_key_set_at TEXT,
  updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
