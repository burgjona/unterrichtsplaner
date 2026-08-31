-- Heftereintrag der SuS pro Stunde: festhalten, was die Schüler:innen tatsächlich in
-- ihren Hefter geschrieben haben (unterscheidet sich bewusst vom Tafelbild und von
-- tafelbild_notiz). Freitext, ein Feld je Stunde. Übergreifend sichtbar über die
-- Klassen-Detailansicht ("Hefter der SuS"), die die Stunden der Klasse chronologisch
-- auflistet - kein eigenes Datenmodell, der Hefter folgt 1:1 der Stundenchronologie.

ALTER TABLE lessons ADD COLUMN hefteintrag TEXT;

-- FTS-Body der Stunde um den Heftereintrag erweitern (Trigger neu, sonst bleibt das Feld
-- unsuchbar - zuletzt definiert in 032_lesson_freies_fach.sql).
DROP TRIGGER IF EXISTS search_lessons_ai;
DROP TRIGGER IF EXISTS search_lessons_au;

CREATE TRIGGER search_lessons_ai AFTER INSERT ON lessons BEGIN
  INSERT INTO search_docs(doc_key,user_id,entity_type,entity_id,subject,grade,title,body,entry_date)
  VALUES('lesson:'||new.id, new.user_id, 'lesson', new.id, new.subject, new.grade,
         COALESCE(new.title,''),
         COALESCE(new.lesson_type,'')||' '||COALESCE(new.klafki_gegenwart,'')||' '||
         COALESCE(new.klafki_zukunft,'')||' '||COALESCE(new.klafki_exemplarisch,'')||' '||
         COALESCE(new.klafki_zugang,'')||' '||COALESCE(new.klafki_struktur,'')||' '||
         COALESCE(new.diff,'')||' '||COALESCE(new.selbst_lernen,'')||' '||
         COALESCE(new.bibox_werk,'')||' '||COALESCE(new.bibox_seite,'')||' '||COALESCE(new.bibox_notiz,'')||' '||
         COALESCE(new.hefteintrag,''),
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
         COALESCE(new.bibox_werk,'')||' '||COALESCE(new.bibox_seite,'')||' '||COALESCE(new.bibox_notiz,'')||' '||
         COALESCE(new.hefteintrag,''),
         new.date);
END;
