-- Erlaubt freie Fachwahl bei Stunden (z. B. Vertretungsstunden ohne eigenen Lehrplan,
-- Fach "+ Neues Fach anlegen…" in der Unterrichtsplanung). Die CHECK-Constraint auf
-- lessons.subject erlaubte bisher nur 'Deutsch'/'WTH' und ließ das Speichern mit einem
-- 400er auflaufen. SQLite kann CHECK-Constraints nicht per ALTER ändern → Table-Rebuild
-- (gleiches Muster wie 028_klasse_kein_fach.sql). Trigger/Indizes werden identisch neu
-- angelegt (siehe 020_suche.sql); lernbereiche.subject bleibt bewusst unverändert (globale
-- Lehrplan-Referenz, nur für Deutsch/WTH geseedet).
PRAGMA foreign_keys = OFF;

CREATE TABLE lessons_new (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  class_id           INTEGER REFERENCES classes(id) ON DELETE SET NULL,
  lernbereich_id     INTEGER REFERENCES lernbereiche(id) ON DELETE SET NULL,
  title              TEXT NOT NULL,
  subject            TEXT NOT NULL,
  grade              INTEGER,
  lesson_type        TEXT,
  time               TEXT,
  klafki_gegenwart    TEXT, klafki_zukunft   TEXT, klafki_exemplarisch TEXT,
  klafki_zugang       TEXT, klafki_struktur  TEXT,
  meyer_plan_json    TEXT,
  diff               TEXT,
  selbst_lernen      TEXT,
  bibox_werk         TEXT, bibox_seite TEXT, bibox_notiz TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
  reflection_skipped INTEGER NOT NULL DEFAULT 0,
  date               TEXT,
  duration_minutes   INTEGER NOT NULL DEFAULT 45
);
INSERT INTO lessons_new SELECT * FROM lessons;
DROP TABLE lessons;
ALTER TABLE lessons_new RENAME TO lessons;
CREATE INDEX idx_lessons_user  ON lessons(user_id);
CREATE INDEX idx_lessons_class ON lessons(class_id);

CREATE TRIGGER search_lessons_ai AFTER INSERT ON lessons BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('lesson:'||new.id, new.user_id, 'lesson', new.id, new.subject, new.grade,
         COALESCE(new.title,''),
         COALESCE(new.lesson_type,'')||' '||COALESCE(new.klafki_gegenwart,'')||' '||
         COALESCE(new.klafki_zukunft,'')||' '||COALESCE(new.klafki_exemplarisch,'')||' '||
         COALESCE(new.klafki_zugang,'')||' '||COALESCE(new.klafki_struktur,'')||' '||
         COALESCE(new.diff,'')||' '||COALESCE(new.selbst_lernen,'')||' '||
         COALESCE(new.bibox_werk,'')||' '||COALESCE(new.bibox_seite,'')||' '||COALESCE(new.bibox_notiz,''),
         new.date);
END;
CREATE TRIGGER search_lessons_au AFTER UPDATE ON lessons BEGIN
  DELETE FROM search_docs WHERE doc_key='lesson:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('lesson:'||new.id, new.user_id, 'lesson', new.id, new.subject, new.grade,
         COALESCE(new.title,''),
         COALESCE(new.lesson_type,'')||' '||COALESCE(new.klafki_gegenwart,'')||' '||
         COALESCE(new.klafki_zukunft,'')||' '||COALESCE(new.klafki_exemplarisch,'')||' '||
         COALESCE(new.klafki_zugang,'')||' '||COALESCE(new.klafki_struktur,'')||' '||
         COALESCE(new.diff,'')||' '||COALESCE(new.selbst_lernen,'')||' '||
         COALESCE(new.bibox_werk,'')||' '||COALESCE(new.bibox_seite,'')||' '||COALESCE(new.bibox_notiz,''),
         new.date);
END;
CREATE TRIGGER search_lessons_ad AFTER DELETE ON lessons BEGIN
  DELETE FROM search_docs WHERE entity_id=old.id AND entity_type IN ('lesson','asuv','reflection');
END;

PRAGMA foreign_keys = ON;
