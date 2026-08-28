-- Eigenes Tafelbild-Foto pro Stunde: die Lehrkraft kann statt (oder neben) dem
-- KI-Tafelbild ein eigenes Bild hochladen. Gespeichert wird es als normales
-- Material (Upload ueber /materials/upload mit lessonId), hier nur die Referenz
-- auf genau ein Material. NULL = kein eigenes Bild.

ALTER TABLE lessons ADD COLUMN tafelbild_bild_material_id INTEGER;
