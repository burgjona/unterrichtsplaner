-- Meilenstein 10 – asynchrone KI-Jobs (ASUV-Ausformulierung dauert länger als
-- der Cloudflare-Tunnel-Timeout von 100 s; daher Job anlegen + Ergebnis pollen).

CREATE TABLE ai_jobs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,                -- z. B. "asuv"
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','error')),
  result_json TEXT,                         -- bei status='done': {suggestion, cached}
  error       TEXT,                         -- bei status='error': lesbare Fehlermeldung
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_ai_jobs_user ON ai_jobs(user_id, created_at);
