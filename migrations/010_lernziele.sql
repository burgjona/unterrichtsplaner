-- Meilenstein 11 – Lernziele-Modul (SMART, Bloom-Taxonomie) + 45/90-Minuten-Auswahl.
-- Grob-/Feinziele je Stunde, optional einer Phase zugeordnet (ASUV-Nachweis, wo welches
-- Ziel erreicht wird). Stundendauer app-seitig auf 45|90 begrenzt (Pydantic-Validator;
-- SQLite-ALTER erlaubt kein CHECK auf neuer Spalte). detail_md = Roh-Lehrplantext als KI-Kontext.

ALTER TABLE lessons ADD COLUMN duration_minutes INTEGER NOT NULL DEFAULT 45;

CREATE TABLE lesson_lernziele (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  lesson_id        INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  kind             TEXT NOT NULL CHECK (kind IN ('grob','fein')),
  text             TEXT NOT NULL,
  bloom_stufe      TEXT,                          -- Erinnern|Verstehen|Anwenden|Analysieren|Bewerten|Erschaffen
  phase_sort_order INTEGER,                       -- NULL = keiner Phase zugeordnet
  sort_order       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_lernziele_lesson ON lesson_lernziele(lesson_id);

ALTER TABLE lernbereiche ADD COLUMN detail_md TEXT;   -- Roh-Detailtext aus dem Lehrplan-MD (KI-Kontext)
