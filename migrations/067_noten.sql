-- Notenmodul (Fallback zum Schulmanager), siehe docs/konzept_noten.md.
--
-- Zwei Ebenen: eine Leistung (grade_items) ist der Anlass -- Klassenarbeit, Referat,
-- Stundenleistung --, darunter haengen die Noten der einzelnen Schueler (grades). Die
-- Notenmatrix der Ansicht ist genau dieses Kreuzprodukt; Einzelnoten sind eine Leistung
-- mit einer gefuellten Zelle.
--
-- Bewusst OHNE Status-Feld an der Note: eine fehlende Leistung bleibt leer und zaehlt
-- nicht in den Durchschnitt. Ein Grund gehoert ins Freifeld comment.
--
-- Nummer 067: 063 ist auf dem noch nicht gemergten Zweig feat/musik vergeben, 066 ist die
-- letzte auf main.

CREATE TABLE grade_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  title      TEXT NOT NULL,
  kind       TEXT NOT NULL CHECK (kind IN (
               'Leistungskontrolle','Komplexe Leistung','Klassenarbeit','Referat',
               'Präsentation','mündliche Leistung','Hausaufgabe','Stundenleistung')),
  size       TEXT NOT NULL CHECK (size IN ('gross','klein')),
  date       TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  term       TEXT NOT NULL CHECK (term IN ('HJ1','HJ2')),
  note       TEXT,
  lesson_id  INTEGER REFERENCES lessons(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_grade_items_class ON grade_items(class_id, term, date);
CREATE INDEX idx_grade_items_user  ON grade_items(user_id);

-- value: Note als Dezimalzahl, Tendenz = Viertelschritt (1+ = 0.75, 2- = 2.25).
-- NULL = noch nicht bewertet; zaehlt nicht in den Durchschnitt.
CREATE TABLE grades (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_id    INTEGER NOT NULL REFERENCES grade_items(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  value      REAL CHECK (value IS NULL OR (value >= 0.75 AND value <= 6.0)),
  comment    TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (item_id, student_id)
);
CREATE INDEX idx_grades_item    ON grades(item_id);
CREATE INDEX idx_grades_student ON grades(student_id);

-- Zeugnisnote: nur vorhanden, wenn von Hand gesetzt. Sonst zeigt die Ansicht den
-- berechneten Vorschlag aus dem gewichteten Durchschnitt.
CREATE TABLE term_grades (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  term       TEXT NOT NULL CHECK (term IN ('HJ1','HJ2')),
  value      REAL NOT NULL CHECK (value >= 0.75 AND value <= 6.0),
  comment    TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (student_id, term)
);
CREATE INDEX idx_term_grades_class ON term_grades(class_id, term);

-- Gewichtung: eine Einstellung je Klasse -- da eine Klasse bereits Fach und Schuljahr
-- traegt, ist das zugleich "je Klasse und Fach pro Schuljahr einmal". Prozentanteil der
-- grossen Noten am Gesamtdurchschnitt; der Rest entfaellt auf die kleinen.
ALTER TABLE classes ADD COLUMN noten_gross_anteil INTEGER NOT NULL DEFAULT 50;

-- Offline-Sync: die drei sync_log-Trigger je Tabelle (vgl. migrations/031_sync_log.sql).
CREATE TRIGGER trg_synclog_grade_items_ai AFTER INSERT ON grade_items BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'grade_items', NEW.id, 'upsert');
END;
CREATE TRIGGER trg_synclog_grade_items_au AFTER UPDATE ON grade_items BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'grade_items', NEW.id, 'upsert');
END;
CREATE TRIGGER trg_synclog_grade_items_ad AFTER DELETE ON grade_items BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'grade_items', OLD.id, 'delete');
END;

CREATE TRIGGER trg_synclog_grades_ai AFTER INSERT ON grades BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'grades', NEW.id, 'upsert');
END;
CREATE TRIGGER trg_synclog_grades_au AFTER UPDATE ON grades BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'grades', NEW.id, 'upsert');
END;
CREATE TRIGGER trg_synclog_grades_ad AFTER DELETE ON grades BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'grades', OLD.id, 'delete');
END;

CREATE TRIGGER trg_synclog_term_grades_ai AFTER INSERT ON term_grades BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'term_grades', NEW.id, 'upsert');
END;
CREATE TRIGGER trg_synclog_term_grades_au AFTER UPDATE ON term_grades BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (NEW.user_id, 'term_grades', NEW.id, 'upsert');
END;
CREATE TRIGGER trg_synclog_term_grades_ad AFTER DELETE ON term_grades BEGIN
  INSERT INTO sync_log(user_id, entity_type, entity_id, op) VALUES (OLD.user_id, 'term_grades', OLD.id, 'delete');
END;
