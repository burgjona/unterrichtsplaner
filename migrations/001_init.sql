-- Meilenstein 1 – Datenmodell Lehrer-Dashboard
-- SQLite. Booleans als INTEGER 0/1, Zeitstempel als ISO-8601-Text (datetime('now')).
-- PRAGMAs (foreign_keys, journal_mode=WAL) werden pro Connection in src/db.py gesetzt.

-- 1) Nutzer (mehrbenutzerfähig von Anfang an; Login/Hashing = Meilenstein 2)
CREATE TABLE users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT,                          -- argon2id, gesetzt in M2 (nie Klartext)
  display_name  TEXT NOT NULL,
  avatar_path   TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2) Schuljahre
CREATE TABLE school_years (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  label      TEXT NOT NULL,                     -- "2025/2026"
  start_date TEXT NOT NULL,
  end_date   TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, label)
);

-- 3) Klassen (jederzeit anlegbar/änderbar/entfernbar → Soft-Delete via archived_at)
CREATE TABLE classes (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  school_year_id      INTEGER REFERENCES school_years(id) ON DELETE SET NULL,
  name                TEXT NOT NULL,            -- "8a"
  subject             TEXT NOT NULL CHECK (subject IN ('Deutsch','WTH')),
  grade               INTEGER NOT NULL,         -- 7..10
  track               TEXT,                     -- 'RS' | 'HS' | 'gemischt'
  weekly_hours        INTEGER NOT NULL DEFAULT 2,
  parallel_group      TEXT,                     -- "Deutsch 8"
  visible_in_calendar INTEGER NOT NULL DEFAULT 1,
  archived_at         TEXT,                     -- NULL = aktiv (Soft-Delete)
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_classes_user ON classes(user_id, archived_at);

-- 4) Lernbereiche = Lehrplan-Referenz (global, geseedet aus docs/lp_os_*.md)
CREATE TABLE lernbereiche (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  subject        TEXT NOT NULL CHECK (subject IN ('Deutsch','WTH')),
  grade          INTEGER NOT NULL,
  track          TEXT NOT NULL,                 -- 'RS'|'HS' (Deutsch), 'gemischt' (WTH)
  code           TEXT NOT NULL,                 -- "LB1"
  title          TEXT NOT NULL,                 -- "Fantasie und Wirklichkeit: Balladen"
  richtwert_ustd INTEGER,                       -- Stundenrichtwert
  sort_order     INTEGER NOT NULL DEFAULT 0,
  source         TEXT,                          -- Provenienz "lp_os_deutsch_2019"
  UNIQUE(subject, grade, track, code)
);
CREATE INDEX idx_lb_lookup ON lernbereiche(subject, grade, track);

-- 5) Stunden (subject/grade denormalisiert: Planung auch ohne Klassenbindung möglich)
CREATE TABLE lessons (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id           INTEGER REFERENCES classes(id) ON DELETE SET NULL,      -- überlebt Klassenlöschung
  lernbereich_id     INTEGER REFERENCES lernbereiche(id) ON DELETE SET NULL,
  title              TEXT NOT NULL,
  subject            TEXT NOT NULL CHECK (subject IN ('Deutsch','WTH')),
  grade              INTEGER,
  lesson_type        TEXT,                      -- "Einführung", "Übungsstunde vor LUE", ...
  time               TEXT,                      -- "08:50"
  klafki_gegenwart    TEXT, klafki_zukunft   TEXT, klafki_exemplarisch TEXT,
  klafki_zugang       TEXT, klafki_struktur  TEXT,
  meyer_plan_json    TEXT,                      -- JSON-Array[10] Ampelwerte (fester Vektor)
  diff               TEXT,                      -- ja|teilweise|nein
  selbst_lernen      TEXT,
  bibox_werk         TEXT, bibox_seite TEXT, bibox_notiz TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_lessons_user  ON lessons(user_id);
CREATE INDEX idx_lessons_class ON lessons(class_id);

-- 5b) Phasen (normalisiert → Sozialform-Monotonie-Check & ASUV-Verlaufsplanung per SQL)
CREATE TABLE lesson_phases (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  lesson_id        INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
  sort_order       INTEGER NOT NULL,            -- 0=Einstieg,1=Erarbeitung,...
  phase_name       TEXT NOT NULL,
  minutes          INTEGER,
  social_form      TEXT,                        -- EA|PA|GA|Plenum
  method           TEXT,
  material         TEXT,
  teacher_activity TEXT,
  student_activity TEXT,
  gme              TEXT,                         -- Differenzierung G/M/E
  UNIQUE(lesson_id, sort_order)
);
CREATE INDEX idx_phases_lesson ON lesson_phases(lesson_id);
CREATE INDEX idx_phases_social ON lesson_phases(social_form);

-- 6) Kalendereinträge (lesson_id: in M4 auto-erzeugt; is_fixed für M4-Konfliktlogik)
CREATE TABLE calendar_entries (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id       INTEGER REFERENCES classes(id) ON DELETE SET NULL,
  lesson_id      INTEGER REFERENCES lessons(id) ON DELETE SET NULL,
  school_year_id INTEGER REFERENCES school_years(id) ON DELETE SET NULL,
  title          TEXT NOT NULL,
  entry_date     TEXT NOT NULL,                 -- ISO-Datum
  entry_type     TEXT NOT NULL DEFAULT 'normal' CHECK (entry_type IN ('normal','lu','exam')),
  is_fixed       INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_cal_user_date ON calendar_entries(user_id, entry_date);
CREATE INDEX idx_cal_class     ON calendar_entries(class_id);

-- 7) Materialien (Metadaten; Binär-Upload + Textextraktion = Meilenstein 5)
CREATE TABLE materials (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename       TEXT NOT NULL,                 -- Originalname (mit Umlauten)
  stored_path    TEXT NOT NULL,                 -- /storage/{jahr}/{fach}/{klasse}/{file}
  mime_type      TEXT,
  byte_size      INTEGER,
  sha256         TEXT,                          -- Integrität/Dedup
  subject        TEXT,
  grade          INTEGER,
  school_year_id INTEGER REFERENCES school_years(id) ON DELETE SET NULL,
  lb_label       TEXT,                          -- Freitext-LB aus Prototyp ("LB4 Printmedien")
  status         TEXT NOT NULL DEFAULT 'neu',   -- neu | in Bearbeitung | fertig
  tag            TEXT,
  external_link  TEXT,                          -- optionaler Turory-Link
  extracted      INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX        idx_materials_user ON materials(user_id);
CREATE UNIQUE INDEX idx_materials_path ON materials(stored_path);

-- 7b) Textabschnitte je Material (M5 befüllt; Schema hier als FTS-Fundament)
CREATE TABLE material_chunks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  page_from   INTEGER,
  page_to     INTEGER,
  heading     TEXT,
  content     TEXT NOT NULL,
  UNIQUE(material_id, chunk_index)
);
CREATE INDEX idx_chunks_material ON material_chunks(material_id);

-- 7c) FTS5-Volltextindex (external content), synchron via Trigger.
--     remove_diacritics 2 wirkt nur auf den Suchindex; gespeicherte Daten behalten ä/ö/ü/ß.
CREATE VIRTUAL TABLE material_chunks_fts USING fts5(
  content,
  heading,
  content='material_chunks',
  content_rowid='id',
  tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER material_chunks_ai AFTER INSERT ON material_chunks BEGIN
  INSERT INTO material_chunks_fts(rowid, content, heading) VALUES (new.id, new.content, new.heading);
END;
CREATE TRIGGER material_chunks_ad AFTER DELETE ON material_chunks BEGIN
  INSERT INTO material_chunks_fts(material_chunks_fts, rowid, content, heading)
  VALUES ('delete', old.id, old.content, old.heading);
END;
CREATE TRIGGER material_chunks_au AFTER UPDATE ON material_chunks BEGIN
  INSERT INTO material_chunks_fts(material_chunks_fts, rowid, content, heading)
  VALUES ('delete', old.id, old.content, old.heading);
  INSERT INTO material_chunks_fts(rowid, content, heading) VALUES (new.id, new.content, new.heading);
END;

-- 8) Verknüpfungstabellen (Mehrfachverknüpfung: Material ↔ Stunde / ↔ Lernbereich)
CREATE TABLE material_lessons (
  material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  lesson_id   INTEGER NOT NULL REFERENCES lessons(id)   ON DELETE CASCADE,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (material_id, lesson_id)
);
CREATE TABLE material_lernbereiche (
  material_id    INTEGER NOT NULL REFERENCES materials(id)    ON DELETE CASCADE,
  lernbereich_id INTEGER NOT NULL REFERENCES lernbereiche(id) ON DELETE CASCADE,
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (material_id, lernbereich_id)
);
