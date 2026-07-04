-- Meilenstein 7 – KI-Nutzung & Kostentransparenz (BRIEFING Kap. 6)

CREATE TABLE ai_usage (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  function          TEXT NOT NULL,          -- z. B. "lesson_suggestion", "stoffplan", "asuv"
  model             TEXT NOT NULL,
  input_tokens      INTEGER NOT NULL DEFAULT 0,
  output_tokens     INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd          REAL NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_ai_usage_user ON ai_usage(user_id, created_at);
