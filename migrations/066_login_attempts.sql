-- U28: Brute-Force-Bremse für den Login.
-- Gespeichert werden ausschließlich FEHLversuche; ein erfolgreicher Login räumt
-- die Einträge der betreffenden IP weg. Kein Passwort, kein Passwort-Fragment.
CREATE TABLE IF NOT EXISTS login_attempts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  email      TEXT NOT NULL,
  ip         TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip    ON login_attempts(ip, created_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_email ON login_attempts(email, created_at);
