-- U25 – Globale Volltextsuche über alle Inhalte (FTS5).
--
-- Ein einziger, eigenständiger FTS5-Index `search_docs`: title/body werden indiziert,
-- alle übrigen Spalten sind UNINDEXED (Metadaten, per Scan filter-/gruppierbar). Das ist
-- bewusst NICHT external-content: Quell-Trigger schreiben direkt in diesen Index (wie das
-- material_chunks-Muster, nur einstufig) → kein rowid-Abgleich, DELETE per doc_key möglich.
--
-- remove_diacritics 2: der Suchindex ist diakritik-insensitiv (märchen == marchen); die
-- gespeicherten Originaltexte in den Quelltabellen behalten ä/ö/ü/ß unverändert.
--
-- Facetten-/Anzeige-Regeln:
--  * Nur die EIGENEN Primärdokumente einer Entität tragen subject/grade (lesson, material,
--    class, lernbereich). Abhängige/Kind-Dokumente (lernziel, reflection, asuv) setzen
--    subject/grade = NULL → keine Doppelzählung, keine Fach/Klassen-Staleness bei Umbenennung.
--  * Kind-Dokumente tragen entity_type/entity_id ihres ELTERNTEILS → Klick landet am Elternteil,
--    Deduplizierung (entity_type, entity_id) im Router faltet Mehrfachtreffer je Entität zusammen.
--  * PDF-Volltext bleibt in material_chunks_fts und wird im Router dazugemischt (nicht dupliziert).

CREATE VIRTUAL TABLE search_docs USING fts5(
  title,                    -- 0 (indiziert)
  body,                     -- 1 (indiziert)
  doc_key      UNINDEXED,   -- stabiler Schlüssel, z. B. 'lesson:3', 'lernziel:7'
  user_id      UNINDEXED,   -- NULL = global (Lernbereiche)
  entity_type  UNINDEXED,   -- lesson|material|class|calendar|note|reflection|todo|asuv|stoffplan|lernbereich
  entity_id    UNINDEXED,   -- Ziel-ID fürs Frontend (bei asuv/reflection = lesson_id)
  subject      UNINDEXED,   -- nur an Primärdokumenten gesetzt
  grade        UNINDEXED,   -- nur an Primärdokumenten gesetzt
  entry_date   UNINDEXED,   -- ISO-Datum (calendar → Sprung zum Tag; lesson → Termin)
  tokenize='unicode61 remove_diacritics 2'
);

-- ============================================================================
-- Quell-Trigger. Muster je Tabelle:
--   AFTER INSERT  → INSERT (neuer doc_key)
--   AFTER UPDATE  → DELETE per altem doc_key + INSERT (kein REPLACE)
--   AFTER DELETE  → DELETE per altem doc_key
-- ============================================================================

-- ---------- Stunden ----------
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
-- Beim Löschen der Stunde alle abhängigen Dokumente mitnehmen (defensiv, unabhängig von
-- CASCADE-Trigger-Verhalten): eigenes lesson-Doc + Lernziele (entity_type='lesson') + asuv/reflection.
CREATE TRIGGER search_lessons_ad AFTER DELETE ON lessons BEGIN
  DELETE FROM search_docs WHERE entity_id=old.id AND entity_type IN ('lesson','asuv','reflection');
END;

-- ---------- Lernziele (Kind → Stunde) ----------
CREATE TRIGGER search_lernziele_ai AFTER INSERT ON lesson_lernziele BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('lernziel:'||new.id,
         (SELECT user_id FROM lessons WHERE id=new.lesson_id),
         'lesson', new.lesson_id, NULL, NULL,
         COALESCE((SELECT title FROM lessons WHERE id=new.lesson_id),''),
         COALESCE(new.text,'')||' '||COALESCE(new.bloom_stufe,''),
         NULL);
END;
CREATE TRIGGER search_lernziele_au AFTER UPDATE ON lesson_lernziele BEGIN
  DELETE FROM search_docs WHERE doc_key='lernziel:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('lernziel:'||new.id,
         (SELECT user_id FROM lessons WHERE id=new.lesson_id),
         'lesson', new.lesson_id, NULL, NULL,
         COALESCE((SELECT title FROM lessons WHERE id=new.lesson_id),''),
         COALESCE(new.text,'')||' '||COALESCE(new.bloom_stufe,''),
         NULL);
END;
CREATE TRIGGER search_lernziele_ad AFTER DELETE ON lesson_lernziele BEGIN
  DELETE FROM search_docs WHERE doc_key='lernziel:'||old.id;
END;

-- ---------- Materialien (nur Metadaten; PDF-Volltext bleibt in material_chunks_fts) ----------
CREATE TRIGGER search_materials_ai AFTER INSERT ON materials BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('material:'||new.id, new.user_id, 'material', new.id, new.subject, new.grade,
         COALESCE(new.filename,''),
         COALESCE(new.lb_label,'')||' '||COALESCE(new.tag,''),
         NULL);
END;
CREATE TRIGGER search_materials_au AFTER UPDATE ON materials BEGIN
  DELETE FROM search_docs WHERE doc_key='material:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('material:'||new.id, new.user_id, 'material', new.id, new.subject, new.grade,
         COALESCE(new.filename,''),
         COALESCE(new.lb_label,'')||' '||COALESCE(new.tag,''),
         NULL);
END;
CREATE TRIGGER search_materials_ad AFTER DELETE ON materials BEGIN
  DELETE FROM search_docs WHERE doc_key='material:'||old.id;
END;

-- ---------- Klassen ----------
CREATE TRIGGER search_classes_ai AFTER INSERT ON classes BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('class:'||new.id, new.user_id, 'class', new.id, new.subject, new.grade,
         COALESCE(new.name,''),
         COALESCE(new.parallel_group,'')||' '||COALESCE(new.track,''),
         NULL);
END;
CREATE TRIGGER search_classes_au AFTER UPDATE ON classes BEGIN
  DELETE FROM search_docs WHERE doc_key='class:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('class:'||new.id, new.user_id, 'class', new.id, new.subject, new.grade,
         COALESCE(new.name,''),
         COALESCE(new.parallel_group,'')||' '||COALESCE(new.track,''),
         NULL);
END;
CREATE TRIGGER search_classes_ad AFTER DELETE ON classes BEGIN
  DELETE FROM search_docs WHERE doc_key='class:'||old.id;
END;

-- ---------- Kalendereinträge (nur manuelle; auto-generierte spiegeln nur Stunden) ----------
CREATE TRIGGER search_calendar_ai AFTER INSERT ON calendar_entries WHEN new.auto_generated=0 BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('calendar:'||new.id, new.user_id, 'calendar', new.id, NULL, NULL,
         COALESCE(new.title,''), '', new.entry_date);
END;
CREATE TRIGGER search_calendar_au AFTER UPDATE ON calendar_entries BEGIN
  DELETE FROM search_docs WHERE doc_key='calendar:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  SELECT 'calendar:'||new.id, new.user_id, 'calendar', new.id, NULL, NULL,
         COALESCE(new.title,''), '', new.entry_date
  WHERE new.auto_generated=0;
END;
CREATE TRIGGER search_calendar_ad AFTER DELETE ON calendar_entries BEGIN
  DELETE FROM search_docs WHERE doc_key='calendar:'||old.id;
END;

-- ---------- Notizen ----------
CREATE TRIGGER search_notes_ai AFTER INSERT ON notes BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('note:'||new.id, new.user_id, 'note', new.id, NULL, NULL,
         substr(COALESCE(new.body_md,''),1,80), COALESCE(new.body_md,''), NULL);
END;
CREATE TRIGGER search_notes_au AFTER UPDATE ON notes BEGIN
  DELETE FROM search_docs WHERE doc_key='note:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('note:'||new.id, new.user_id, 'note', new.id, NULL, NULL,
         substr(COALESCE(new.body_md,''),1,80), COALESCE(new.body_md,''), NULL);
END;
CREATE TRIGGER search_notes_ad AFTER DELETE ON notes BEGIN
  DELETE FROM search_docs WHERE doc_key='note:'||old.id;
END;

-- ---------- Reflexionen (Kind → Stunde; eigener Facetten-Typ) ----------
CREATE TRIGGER search_reflections_ai AFTER INSERT ON reflections BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('reflection:'||new.id, new.user_id, 'reflection', new.lesson_id, NULL, NULL,
         COALESCE((SELECT title FROM lessons WHERE id=new.lesson_id),''),
         COALESCE(new.text,'')||' '||COALESCE(new.ampel_summary,''), NULL);
END;
CREATE TRIGGER search_reflections_au AFTER UPDATE ON reflections BEGIN
  DELETE FROM search_docs WHERE doc_key='reflection:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('reflection:'||new.id, new.user_id, 'reflection', new.lesson_id, NULL, NULL,
         COALESCE((SELECT title FROM lessons WHERE id=new.lesson_id),''),
         COALESCE(new.text,'')||' '||COALESCE(new.ampel_summary,''), NULL);
END;
CREATE TRIGGER search_reflections_ad AFTER DELETE ON reflections BEGIN
  DELETE FROM search_docs WHERE doc_key='reflection:'||old.id;
END;

-- ---------- To-dos ----------
CREATE TRIGGER search_todos_ai AFTER INSERT ON todos BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('todo:'||new.id, new.user_id, 'todo', new.id, NULL, NULL,
         substr(COALESCE(new.text,''),1,80), COALESCE(new.text,''), NULL);
END;
CREATE TRIGGER search_todos_au AFTER UPDATE ON todos BEGIN
  DELETE FROM search_docs WHERE doc_key='todo:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('todo:'||new.id, new.user_id, 'todo', new.id, NULL, NULL,
         substr(COALESCE(new.text,''),1,80), COALESCE(new.text,''), NULL);
END;
CREATE TRIGGER search_todos_ad AFTER DELETE ON todos BEGIN
  DELETE FROM search_docs WHERE doc_key='todo:'||old.id;
END;

-- ---------- ASUV-Entwürfe (Kind → Stunde; PK = lesson_id) ----------
CREATE TRIGGER search_asuv_ai AFTER INSERT ON asuv_drafts BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('asuv:'||new.lesson_id, new.user_id, 'asuv', new.lesson_id, NULL, NULL,
         COALESCE((SELECT title FROM lessons WHERE id=new.lesson_id),''),
         COALESCE(new.bedingung_org,'')||' '||COALESCE(new.bedingung_lern,'')||' '||
         COALESCE(new.bedingung_einordnung,'')||' '||COALESCE(new.ziele,'')||' '||
         COALESCE(new.sachanalyse,'')||' '||COALESCE(new.quellen,'')||' '||
         COALESCE(new.didaktisch,'')||' '||COALESCE(new.reduktion,'')||' '||
         COALESCE(new.methodisch,'')||' '||COALESCE(new.anhang,'')||' '||
         COALESCE(new.schule,'')||' '||COALESCE(new.pruefer,''), NULL);
END;
CREATE TRIGGER search_asuv_au AFTER UPDATE ON asuv_drafts BEGIN
  DELETE FROM search_docs WHERE doc_key='asuv:'||old.lesson_id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('asuv:'||new.lesson_id, new.user_id, 'asuv', new.lesson_id, NULL, NULL,
         COALESCE((SELECT title FROM lessons WHERE id=new.lesson_id),''),
         COALESCE(new.bedingung_org,'')||' '||COALESCE(new.bedingung_lern,'')||' '||
         COALESCE(new.bedingung_einordnung,'')||' '||COALESCE(new.ziele,'')||' '||
         COALESCE(new.sachanalyse,'')||' '||COALESCE(new.quellen,'')||' '||
         COALESCE(new.didaktisch,'')||' '||COALESCE(new.reduktion,'')||' '||
         COALESCE(new.methodisch,'')||' '||COALESCE(new.anhang,'')||' '||
         COALESCE(new.schule,'')||' '||COALESCE(new.pruefer,''), NULL);
END;
CREATE TRIGGER search_asuv_ad AFTER DELETE ON asuv_drafts BEGIN
  DELETE FROM search_docs WHERE doc_key='asuv:'||old.lesson_id;
END;

-- ---------- Stoffverteilungspläne ----------
CREATE TRIGGER search_stoffplan_ai AFTER INSERT ON stoff_plans BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('stoffplan:'||new.id, new.user_id, 'stoffplan', new.id, NULL, NULL,
         COALESCE(new.title,''), '', NULL);
END;
CREATE TRIGGER search_stoffplan_au AFTER UPDATE ON stoff_plans BEGIN
  DELETE FROM search_docs WHERE doc_key='stoffplan:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('stoffplan:'||new.id, new.user_id, 'stoffplan', new.id, NULL, NULL,
         COALESCE(new.title,''), '', NULL);
END;
CREATE TRIGGER search_stoffplan_ad AFTER DELETE ON stoff_plans BEGIN
  DELETE FROM search_docs WHERE doc_key='stoffplan:'||old.id;
END;

-- ---------- Lernbereiche (global, user_id NULL) ----------
CREATE TRIGGER search_lernbereich_ai AFTER INSERT ON lernbereiche BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('lernbereich:'||new.id, NULL, 'lernbereich', new.id, new.subject, new.grade,
         COALESCE(new.code,'')||' '||COALESCE(new.title,''), COALESCE(new.detail_md,''), NULL);
END;
CREATE TRIGGER search_lernbereich_au AFTER UPDATE ON lernbereiche BEGIN
  DELETE FROM search_docs WHERE doc_key='lernbereich:'||old.id;
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('lernbereich:'||new.id, NULL, 'lernbereich', new.id, new.subject, new.grade,
         COALESCE(new.code,'')||' '||COALESCE(new.title,''), COALESCE(new.detail_md,''), NULL);
END;
CREATE TRIGGER search_lernbereich_ad AFTER DELETE ON lernbereiche BEGIN
  DELETE FROM search_docs WHERE doc_key='lernbereich:'||old.id;
END;

-- ============================================================================
-- Backfill des Bestands (direkt in den Index; umgeht die Quell-Trigger bewusst).
-- ============================================================================
INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'lesson:'||id, user_id, 'lesson', id, subject, grade, COALESCE(title,''),
       COALESCE(lesson_type,'')||' '||COALESCE(klafki_gegenwart,'')||' '||COALESCE(klafki_zukunft,'')||' '||
       COALESCE(klafki_exemplarisch,'')||' '||COALESCE(klafki_zugang,'')||' '||COALESCE(klafki_struktur,'')||' '||
       COALESCE(diff,'')||' '||COALESCE(selbst_lernen,'')||' '||COALESCE(bibox_werk,'')||' '||
       COALESCE(bibox_seite,'')||' '||COALESCE(bibox_notiz,''), date
FROM lessons;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'lernziel:'||lz.id, l.user_id, 'lesson', lz.lesson_id, NULL, NULL, COALESCE(l.title,''),
       COALESCE(lz.text,'')||' '||COALESCE(lz.bloom_stufe,''), NULL
FROM lesson_lernziele lz JOIN lessons l ON l.id=lz.lesson_id;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'material:'||id, user_id, 'material', id, subject, grade, COALESCE(filename,''),
       COALESCE(lb_label,'')||' '||COALESCE(tag,''), NULL
FROM materials;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'class:'||id, user_id, 'class', id, subject, grade, COALESCE(name,''),
       COALESCE(parallel_group,'')||' '||COALESCE(track,''), NULL
FROM classes;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'calendar:'||id, user_id, 'calendar', id, NULL, NULL, COALESCE(title,''), '', entry_date
FROM calendar_entries WHERE auto_generated=0;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'note:'||id, user_id, 'note', id, NULL, NULL, substr(COALESCE(body_md,''),1,80),
       COALESCE(body_md,''), NULL
FROM notes;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'reflection:'||r.id, r.user_id, 'reflection', r.lesson_id, NULL, NULL, COALESCE(l.title,''),
       COALESCE(r.text,'')||' '||COALESCE(r.ampel_summary,''), NULL
FROM reflections r JOIN lessons l ON l.id=r.lesson_id;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'todo:'||id, user_id, 'todo', id, NULL, NULL, substr(COALESCE(text,''),1,80),
       COALESCE(text,''), NULL
FROM todos;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'asuv:'||a.lesson_id, a.user_id, 'asuv', a.lesson_id, NULL, NULL, COALESCE(l.title,''),
       COALESCE(a.bedingung_org,'')||' '||COALESCE(a.bedingung_lern,'')||' '||
       COALESCE(a.bedingung_einordnung,'')||' '||COALESCE(a.ziele,'')||' '||COALESCE(a.sachanalyse,'')||' '||
       COALESCE(a.quellen,'')||' '||COALESCE(a.didaktisch,'')||' '||COALESCE(a.reduktion,'')||' '||
       COALESCE(a.methodisch,'')||' '||COALESCE(a.anhang,'')||' '||COALESCE(a.schule,'')||' '||
       COALESCE(a.pruefer,''), NULL
FROM asuv_drafts a JOIN lessons l ON l.id=a.lesson_id;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'stoffplan:'||id, user_id, 'stoffplan', id, NULL, NULL, COALESCE(title,''), '', NULL
FROM stoff_plans;

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'lernbereich:'||id, NULL, 'lernbereich', id, subject, grade,
       COALESCE(code,'')||' '||COALESCE(title,''), COALESCE(detail_md,''), NULL
FROM lernbereiche;
