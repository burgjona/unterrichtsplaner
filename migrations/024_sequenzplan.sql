-- Sequenzplan: Einzelstunden-Ebene je Stoffplan-Block. Eigenständiges Objekt mit optionaler
-- 1:1-Verknüpfung zu einer lessons-Zeile (lesson_id), analog stoff_plan_blocks-Reihenfolge
-- per sort_order.

CREATE TABLE sequenz_stunden (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  block_id           INTEGER NOT NULL REFERENCES stoff_plan_blocks(id) ON DELETE CASCADE,
  sort_order         INTEGER NOT NULL DEFAULT 0,
  title              TEXT NOT NULL,
  grobziel           TEXT,
  notes              TEXT,
  is_lk              INTEGER NOT NULL DEFAULT 0,
  is_referat         INTEGER NOT NULL DEFAULT 0,
  is_komplexe_arbeit INTEGER NOT NULL DEFAULT 0,
  is_klassenarbeit   INTEGER NOT NULL DEFAULT 0,
  weitere_notenart   TEXT,
  lesson_id          INTEGER REFERENCES lessons(id) ON DELETE SET NULL,
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_sequenz_stunden_block ON sequenz_stunden(block_id, sort_order);
CREATE UNIQUE INDEX idx_sequenz_stunden_lesson_uniq ON sequenz_stunden(lesson_id) WHERE lesson_id IS NOT NULL;
