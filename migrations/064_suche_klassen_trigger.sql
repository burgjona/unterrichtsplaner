-- Repariert den Volltextindex für Klassen. 020_suche.sql hatte die drei Trigger
-- search_classes_ai/au/ad angelegt; 028_klasse_kein_fach.sql baute `classes` danach per
-- Table-Rebuild neu auf (DROP TABLE + RENAME) und legte nur idx_classes_user wieder an —
-- die Suchtrigger fielen mit der alten Tabelle weg (anders als in 032_lesson_freies_fach.sql,
-- wo die lessons-Trigger korrekt mitgezogen wurden). Folge seit 028: neue Klassen landen
-- nicht mehr in search_docs, Umbenennungen aktualisieren den Index nicht, gelöschte Klassen
-- hinterlassen verwaiste Einträge.
--
-- Kein Rebuild nötig — reines CREATE TRIGGER (identisch zu 020_suche.sql) plus einmaliger
-- Backfill. DROP TRIGGER IF EXISTS vorweg (Muster aus 058_hefteintrag.sql), damit die
-- Migration auch auf einer DB durchläuft, in der die Trigger von Hand nachgezogen wurden.

DROP TRIGGER IF EXISTS search_classes_ai;
DROP TRIGGER IF EXISTS search_classes_au;
DROP TRIGGER IF EXISTS search_classes_ad;

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

-- Backfill. Erst alle bestehenden class-Dokumente wegwerfen: Übrig sind nur noch Zeilen aus
-- der Zeit vor 028 — teils verwaist (Klasse längst gelöscht), teils veraltet (Umbenennung seit
-- 028 nicht nachgezogen). Ein sauberer Neuaufbau vermeidet Dubletten und Staleness in einem
-- Schritt. Der INSERT schreibt direkt in search_docs (löst keine classes-Trigger aus) und
-- spiegelt search_classes_ai Feld für Feld.
DELETE FROM search_docs WHERE entity_type = 'class';

INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
SELECT 'class:'||id, user_id, 'class', id, subject, grade,
       COALESCE(name,''),
       COALESCE(parallel_group,'')||' '||COALESCE(track,''),
       NULL
FROM classes;
