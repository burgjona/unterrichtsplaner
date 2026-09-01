-- Lehrplan-Abhakmodul, Teil 2: Abhak-Status je konkreter Klasse.
-- Eine Klasse ist bereits schuljahres-spezifisch (classes.school_year_id), daher
-- reicht die Bindung an class_id: naechstes Schuljahr = neue Klassenzeile = leere
-- Haken. Zeile vorhanden = abgehakt; Abwaehlen = Zeile loeschen.
-- item_ref verweist auf lehrplan_ziele.id ('ziel') bzw. lernbereiche.id ('lb').

CREATE TABLE lehrplan_checks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  item_type  TEXT NOT NULL CHECK (item_type IN ('ziel','lb')),
  item_ref   INTEGER NOT NULL,
  checked_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, class_id, item_type, item_ref)
);
CREATE INDEX idx_lehrplan_checks_scope ON lehrplan_checks(user_id, class_id);
