-- Meilenstein 6 – ASUV-Entwürfe (je Stunde ein Entwurf)

CREATE TABLE asuv_drafts (
  lesson_id            INTEGER PRIMARY KEY REFERENCES lessons(id) ON DELETE CASCADE,
  user_id              INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  -- LASUB-Kapitel (Kap. 4.2)
  bedingung_org        TEXT,
  bedingung_lern       TEXT,
  bedingung_einordnung TEXT,
  ziele                TEXT,
  sachanalyse          TEXT,
  quellen              TEXT,
  didaktisch           TEXT,
  reduktion            TEXT,
  methodisch           TEXT,
  anhang               TEXT,
  -- Deckblatt
  schule               TEXT,
  pruefer              TEXT,
  deckblatt_datum      TEXT,
  -- Formalien-Checkliste (JSON: Index -> bool)
  checks_json          TEXT,
  created_at           TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
