-- U12 – Stoffverteilungsplan-Persistenz. Speichert deterministische/KI-Vorschläge als Plan.
-- Regel (app-seitig, siehe stoffplan-Router): max. 1 aktiver Plan je (class_id, school_year_id);
-- beim Aktivsetzen werden andere Pläne derselben Klasse+Schuljahr auf 'entwurf' zurückgesetzt.

CREATE TABLE stoff_plans (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id       INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  school_year_id INTEGER REFERENCES school_years(id) ON DELETE SET NULL,
  title          TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'entwurf' CHECK (status IN ('entwurf','aktiv')),
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_stoff_plans_scope ON stoff_plans(user_id, class_id, school_year_id);

CREATE TABLE stoff_plan_blocks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id       INTEGER NOT NULL REFERENCES stoff_plans(id) ON DELETE CASCADE,
  lb_code       TEXT,
  title         TEXT,
  ustd          INTEGER,
  start_date    TEXT,                    -- ISO (YYYY-MM-DD) oder NULL
  end_date      TEXT,                    -- ISO (YYYY-MM-DD) oder NULL
  sort_order    INTEGER NOT NULL DEFAULT 0,
  conflict_note TEXT
);
CREATE INDEX idx_stoff_plan_blocks_plan ON stoff_plan_blocks(plan_id);
